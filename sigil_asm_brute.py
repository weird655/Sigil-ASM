"""Sigil-ASM brute: direct .sigil -> x86-64, no safety checks.

This is deliberately a brute-force first cut: integer/pointer locals,
arithmetic, comparisons, branches, loops, direct calls and string literals.
Unsupported constructs fail loudly instead of silently miscompiling.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in (os.environ.get("SIGILC_ROOT"),
                   os.path.join(HERE, "..", "Sigil-C"),
                   os.path.join(HERE, "Sigil-C")):
    if _candidate and os.path.isdir(_candidate):
        sys.path.insert(0, os.path.abspath(_candidate))
        break

from sigilc_core.lexer import EXTERNAL_C_SPELLING, Lexer
from sigilc_core.nodes import (
    AssignStmt,
    BinaryExpr,
    BlockStmt,
    CallExpr,
    CastExpr,
    DoWhileStmt,
    ExprNode,
    ExprStmt,
    ForStmt,
    FuncDefNode,
    GotoStmt,
    IdentExpr,
    IfStmt,
    IndexExpr,
    JumpStmt,
    LabelStmt,
    MemberExpr,
    LiteralExpr,
    PreprocNode,
    ReturnStmt,
    SizeofExpr,
    StmtNode,
    StructDefNode,
    SwitchStmt,
    TernaryExpr,
    TrapStmt,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)
from sigilc_core.parser import Parser
from sigilc_core.type_system import ArrayType, BaseType, PointerType


class AsmError(Exception):
    pass


_TYPE_SIZE = {
    "i1": 1, "u1": 1, "char": 1, "bool": 1,
    "i2": 2, "u2": 2, "short": 2,
    "i4": 4, "u4": 4, "int": 4, "unsigned": 4, "uint32_t": 4, "int32_t": 4,
    "i8": 8, "u8": 8, "long": 8, "uint64_t": 8, "int64_t": 8,
}


def _align_up(n: int, a: int) -> int:
    return ((n + a - 1) // a) * a


def _type_size(t) -> int:
    if isinstance(t, PointerType):
        return 8
    if isinstance(t, ArrayType):
        if t.size_val is None:
            return 8
        return max(8, t.size_val * _type_size(t.element_type))
    if isinstance(t, BaseType):
        if t.c_name in _TYPE_SIZE:
            return _TYPE_SIZE[t.c_name]
        if t.c_name in ("float",):
            return 4
        if t.c_name in ("double", "long double"):
            return 8
    return 8


def _is_global_name(name: str, globals_: Dict[str, str]) -> bool:
    return name in globals_


class AsmGenerator:
    def __init__(self, filename: str = "input.sigil", abi: str = "sysv"):
        self.filename = filename
        self.abi = abi
        self.lines: List[str] = []
        self.strings: Dict[str, str] = {}
        self.globals: Dict[str, str] = {}
        self.var_types: Dict[str, object] = {}
        self.structs: Dict[str, Dict[str, tuple]] = {}
        self.struct_sizes: Dict[str, int] = {}
        self.functions: set = set()
        self.func_name = ""
        self.locals: Dict[str, int] = {}
        self.frame_size = 0
        self.used = 0
        self.label_id = 0
        self.ret_label = ""
        self.break_labels: List[str] = []
        self.continue_labels: List[str] = []
        self.string_id = 0

    def emit(self, text: str = "") -> None:
        self.lines.append(("    " + text) if text else "")

    def label(self, prefix: str = "L") -> str:
        self.label_id += 1
        return f".L{prefix}{self.label_id}"

    def fail(self, why: str) -> None:
        raise AsmError(f"{self.filename}: ASM backend does not support {why}")

    def tsize(self, t) -> int:
        if isinstance(t, BaseType) and t.c_name in self.struct_sizes:
            return self.struct_sizes[t.c_name]
        return _type_size(t)

    def collect_structs(self, nodes) -> None:
        for node in nodes:
            if not isinstance(node, StructDefNode):
                continue
            layout = {}
            off = 0
            max_align = 1
            for f in node.fields:
                if f.bit_width:
                    self.fail("struct bitfields")
                sz = self.tsize(f.var_type)
                al = min(max(sz, 1), 8)
                off = _align_up(off, al)
                layout[f.name] = (off, f.var_type)
                off += sz
                max_align = max(max_align, al)
            self.structs[node.name] = layout
            self.struct_sizes[node.name] = _align_up(off, max_align)

    # ------------------------------------------------------------------ types
    def slot(self, name: str, t=None) -> int:
        if name not in self.locals:
            size = max(8, self.tsize(t)) if t is not None else 8
            self.used = ((self.used + 7) // 8) * 8 + size
            self.locals[name] = self.used
            if t is not None:
                self.var_types[name] = t
        return self.locals[name]

    def mem(self, name: str) -> str:
        return f"-{self.slot(name)}(%rbp)"

    def global_mem(self, name: str) -> str:
        return f"{name}(%rip)"

    # --------------------------------------------------------------- functions
    def collect_vars(self, stmt: Optional[StmtNode]) -> None:
        if stmt is None:
            return
        if isinstance(stmt, VarDeclStmt):
            if not stmt.is_static:
                self.slot(stmt.name, stmt.var_type)
        elif isinstance(stmt, BlockStmt):
            for s in stmt.stmts:
                self.collect_vars(s)
        elif isinstance(stmt, IfStmt):
            self.collect_vars(stmt.then_block)
            self.collect_vars(stmt.else_branch)
        elif isinstance(stmt, (WhileStmt, DoWhileStmt)):
            self.collect_vars(stmt.body)
        elif isinstance(stmt, ForStmt):
            self.collect_vars(stmt.init_stmt)
            self.collect_vars(stmt.body)

    def gen_function(self, fn: FuncDefNode) -> None:
        if fn.body is None:
            return
        self.locals = {}
        self.used = 0
        self.func_name = fn.name
        self.break_labels = []
        self.continue_labels = []
        # params first
        for ptype, pname in fn.params:
            self.slot(pname, ptype)
        self.collect_vars(fn.body)
        self.frame_size = ((self.used + 15) // 16) * 16
        self.ret_label = self.label("ret")
        self.lines.append(f".globl {fn.name}")
        self.lines.append(f"{fn.name}:")
        self.emit("pushq %rbp")
        self.emit("movq %rsp, %rbp")
        if self.frame_size:
            self.emit(f"subq ${self.frame_size}, %rsp")
        if self.abi == "win64":
            regs = ["%rcx", "%rdx", "%r8", "%r9"]
            regs32 = ["%ecx", "%edx", "%r8d", "%r9d"]
        else:
            regs = ["%rdi", "%rsi", "%rdx", "%rcx", "%r8", "%r9"]
            regs32 = ["%edi", "%esi", "%edx", "%ecx", "%r8d", "%r9d"]
        for i, (ptype, pname) in enumerate(fn.params):
            if i >= len(regs):
                if self.abi == "win64":
                    self.fail("stack parameters on win64")
                off = 16 + 8 * (i - len(regs))
                self.emit(f"movq {off}(%rbp), %rax")
                self.emit(f"movq %rax, {self.mem(pname)}")
                continue
            if self.tsize(ptype) == 8:
                self.emit(f"movq {regs[i]}, {self.mem(pname)}")
            else:
                self.emit(f"movslq {regs32[i]}, %rax")
                self.emit(f"movq %rax, {self.mem(pname)}")
        self.gen_stmt(fn.body)
        if not self.lines or self.lines[-1] != f"{self.ret_label}:":
            self.lines.append(f"{self.ret_label}:")
        self.emit("leave")
        self.emit("ret")
        self.lines.append("")

    # --------------------------------------------------------------- statements
    def gen_stmt(self, stmt: Optional[StmtNode]) -> None:
        if stmt is None:
            return
        if isinstance(stmt, BlockStmt):
            for s in stmt.stmts:
                self.gen_stmt(s)
            return
        if isinstance(stmt, VarDeclStmt):
            if stmt.is_static:
                self.fail("static local variables")
            if stmt.init_expr is not None:
                self.expr(stmt.init_expr)
            else:
                self.emit("xorl %eax, %eax")
            self.emit(f"movq %rax, {self.mem(stmt.name)}")
            return
        if isinstance(stmt, ExprStmt):
            self.expr(stmt.expr)
            return
        if isinstance(stmt, AssignStmt):
            self.gen_assign(stmt)
            return
        if isinstance(stmt, ReturnStmt):
            if stmt.expr is not None:
                self.expr(stmt.expr)
            else:
                self.emit("xorl %eax, %eax")
            self.emit(f"jmp {self.ret_label}")
            return
        if isinstance(stmt, IfStmt):
            else_l = self.label("else")
            end_l = self.label("endif")
            self.expr(stmt.cond)
            self.emit("testq %rax, %rax")
            self.emit(f"jz {else_l}")
            self.gen_stmt(stmt.then_block)
            self.emit(f"jmp {end_l}")
            self.lines.append(f"{else_l}:")
            if stmt.else_branch is not None:
                self.gen_stmt(stmt.else_branch)
            self.lines.append(f"{end_l}:")
            return
        if isinstance(stmt, WhileStmt):
            top = self.label("while")
            end = self.label("endwhile")
            self.break_labels.append(end)
            self.continue_labels.append(top)
            self.lines.append(f"{top}:")
            self.expr(stmt.cond)
            self.emit("testq %rax, %rax")
            self.emit(f"jz {end}")
            self.gen_stmt(stmt.body)
            self.emit(f"jmp {top}")
            self.lines.append(f"{end}:")
            self.break_labels.pop()
            self.continue_labels.pop()
            return
        if isinstance(stmt, DoWhileStmt):
            top = self.label("do")
            cont = self.label("docont")
            end = self.label("enddo")
            self.break_labels.append(end)
            self.continue_labels.append(cont)
            self.lines.append(f"{top}:")
            self.gen_stmt(stmt.body)
            self.lines.append(f"{cont}:")
            self.expr(stmt.cond)
            self.emit("testq %rax, %rax")
            self.emit(f"jnz {top}")
            self.lines.append(f"{end}:")
            self.break_labels.pop()
            self.continue_labels.pop()
            return
        if isinstance(stmt, ForStmt):
            top = self.label("for")
            cont = self.label("forcont")
            end = self.label("endfor")
            if stmt.init_stmt is not None:
                self.gen_stmt(stmt.init_stmt)
            self.break_labels.append(end)
            self.continue_labels.append(cont)
            self.lines.append(f"{top}:")
            if stmt.cond_expr is not None:
                self.expr(stmt.cond_expr)
                self.emit("testq %rax, %rax")
                self.emit(f"jz {end}")
            self.gen_stmt(stmt.body)
            self.lines.append(f"{cont}:")
            if stmt.step_stmt is not None:
                self.gen_stmt(stmt.step_stmt)
            self.emit(f"jmp {top}")
            self.lines.append(f"{end}:")
            self.break_labels.pop()
            self.continue_labels.pop()
            return
        if isinstance(stmt, JumpStmt):
            if stmt.keyword == "break":
                if not self.break_labels:
                    self.fail("break outside loop")
                self.emit(f"jmp {self.break_labels[-1]}")
            elif stmt.keyword == "continue":
                if not self.continue_labels:
                    self.fail("continue outside loop")
                self.emit(f"jmp {self.continue_labels[-1]}")
            else:
                self.fail(f"jump {stmt.keyword}")
            return
        if isinstance(stmt, LabelStmt):
            self.lines.append(f".L{self.func_name}_{stmt.name}:")
            return
        if isinstance(stmt, GotoStmt):
            self.emit(f"jmp .L{self.func_name}_{stmt.label}")
            return
        if isinstance(stmt, SwitchStmt):
            self.gen_switch(stmt)
            return
        if isinstance(stmt, TrapStmt):
            self.emit("ud2")
            return
        if isinstance(stmt, PreprocNode):
            text = stmt.text.strip()
            if text.startswith("#asm"):
                raw = text[4:].strip()
                if len(raw) >= 2 and raw[0] == raw[-1] == '"':
                    raw = raw[1:-1]
                self.lines.append(raw)
            return
        self.fail(type(stmt).__name__)

    def const_value(self, e: ExprNode) -> int:
        if isinstance(e, LiteralExpr) and e.lit_kind in ("INT_NUM", "CHAR"):
            raw = e.code.strip()
            if e.lit_kind == "CHAR":
                return ord(raw.strip("'"))
            raw = raw.replace("u", "").replace("U", "").replace("l", "").replace("L", "")
            return int(raw, 0)
        if isinstance(e, UnaryExpr) and e.op == "-":
            return -self.const_value(e.operand)
        self.fail("non-constant switch case")

    def gen_switch(self, stmt: SwitchStmt) -> None:
        end = self.label("endswitch")
        self.break_labels.append(end)
        self.expr(stmt.cond)
        self.emit("movq %rax, %r10")
        labels = []
        default = None
        for case in stmt.cases:
            lab = self.label("case")
            labels.append((case, lab))
            if case.value is None:
                default = lab
            else:
                self.emit(f"cmpq ${self.const_value(case.value)}, %r10")
                self.emit(f"je {lab}")
        self.emit(f"jmp {default or end}")
        for case, lab in labels:
            self.lines.append(f"{lab}:")
            for s in case.stmts:
                self.gen_stmt(s)
        self.lines.append(f"{end}:")
        self.break_labels.pop()

    def gen_assign(self, stmt: AssignStmt) -> None:
        if isinstance(stmt.target, IdentExpr):
            name = stmt.target.name
            t = self.var_types.get(name)
            if isinstance(t, ArrayType):
                self.fail("array assignment")
            size = self.tsize(t) if t is not None else 8
            if stmt.op == "=":
                self.expr(stmt.value)
            else:
                self.load_lvalue(name)
                self.emit("pushq %rax")
                self.expr(stmt.value)
                self.emit("movq %rax, %rcx")
                self.emit("popq %rax")
                self.binop(stmt.op[:-1], "%rcx")
            if name in self.globals:
                self.store_at(self.global_mem(name), size)
            else:
                self.store_at(self.mem(name), size)
            return
        if isinstance(stmt.target, (IndexExpr, MemberExpr, UnaryExpr)):
            t = getattr(stmt.target, "sem_type", None)
            size = self.tsize(t) if t is not None else 8
            if isinstance(stmt.target, UnaryExpr) and stmt.target.op != "*":
                self.fail("complex assignment")
            self.gen_addr(stmt.target)
            self.emit("pushq %rax")
            if stmt.op == "=":
                self.expr(stmt.value)
            else:
                self.load_addr_from_stack(size)
                self.emit("pushq %rax")
                self.expr(stmt.value)
                self.emit("movq %rax, %rcx")
                self.emit("popq %rax")
                self.binop(stmt.op[:-1], "%rcx")
            self.emit("popq %rcx")
            self.store_at("(%rcx)", size)
            return
        self.fail("non-addressable assignment in ASM backend")

    def store_at(self, addr: str, size: int) -> None:
        if size == 1:
            self.emit(f"movb %al, {addr}")
        elif size == 2:
            self.emit(f"movw %ax, {addr}")
        elif size == 4:
            self.emit(f"movl %eax, {addr}")
        else:
            self.emit(f"movq %rax, {addr}")

    def load_addr_from_stack(self, size: int) -> None:
        self.emit("movq (%rsp), %rax")
        if size == 1:
            self.emit("movsbq (%rax), %rax")
        elif size == 2:
            self.emit("movswq (%rax), %rax")
        elif size == 4:
            self.emit("movslq (%rax), %rax")
        else:
            self.emit("movq (%rax), %rax")

    def load_lvalue(self, name: str) -> None:
        t = self.var_types.get(name)
        if isinstance(t, ArrayType):
            self.fail("array load")
        if name in self.globals:
            self.emit(f"movq {self.global_mem(name)}, %rax")
        else:
            self.emit(f"movq {self.mem(name)}, %rax")

    def gen_addr(self, e: ExprNode) -> None:
        if isinstance(e, IdentExpr):
            if e.name in self.globals:
                self.emit(f"leaq {self.global_mem(e.name)}, %rax")
            else:
                self.emit(f"leaq {self.mem(e.name)}, %rax")
            return
        if isinstance(e, IndexExpr):
            self.expr(e.base)
            self.emit("pushq %rax")
            self.expr(e.index)
            self.emit("movq %rax, %rcx")
            self.emit("popq %rax")
            t = getattr(e, "sem_type", None)
            size = self.tsize(t) if t is not None else 8
            if size in (1, 2, 4, 8):
                self.emit(f"leaq (%rax,%rcx,{size}), %rax")
            else:
                self.emit(f"imulq ${size}, %rcx")
                self.emit("addq %rcx, %rax")
            return
        if isinstance(e, MemberExpr):
            bt = getattr(e.base, "sem_type", None)
            if e.is_arrow:
                self.expr(e.base)
                sname = bt.pointee.c_name if isinstance(bt, PointerType) and isinstance(bt.pointee, BaseType) else None
            else:
                self.gen_addr(e.base)
                sname = bt.c_name if isinstance(bt, BaseType) else None
            if sname is None or sname not in self.structs:
                self.fail("member base type")
            off, _ = self.structs[sname].get(e.field, (None, None))
            if off is None:
                self.fail(f"member {e.field}")
            if off:
                self.emit(f"addq ${off}, %rax")
            return
        if isinstance(e, UnaryExpr) and e.op == "*":
            self.expr(e.operand)
            return
        self.fail("address of expression")

    # --------------------------------------------------------------- expressions
    def expr(self, e: ExprNode) -> None:
        if isinstance(e, LiteralExpr):
            self.gen_literal(e)
            return
        if isinstance(e, IdentExpr):
            if e.name in self.globals:
                vt = self.var_types.get(e.name)
                if isinstance(vt, ArrayType) or (isinstance(vt, BaseType) and vt.c_name in self.struct_sizes):
                    self.emit(f"leaq {self.global_mem(e.name)}, %rax")
                else:
                    self.emit(f"movq {self.global_mem(e.name)}, %rax")
            elif e.name in self.locals:
                vt = self.var_types.get(e.name)
                if isinstance(vt, ArrayType) or (isinstance(vt, BaseType) and vt.c_name in self.struct_sizes):
                    self.emit(f"leaq {self.mem(e.name)}, %rax")
                else:
                    self.emit(f"movq {self.mem(e.name)}, %rax")
            elif e.name in self.functions:
                self.emit(f"leaq {e.name}(%rip), %rax")
            else:
                self.fail(f"identifier '{e.name}' (function pointers/externs)")
            return
        if isinstance(e, UnaryExpr):
            self.gen_unary(e)
            return
        if isinstance(e, BinaryExpr):
            self.gen_binary(e)
            return
        if isinstance(e, CastExpr):
            self.expr(e.operand)
            size = self.tsize(e.target_type)
            if size == 1:
                self.emit("movsbq %al, %rax")
            elif size == 2:
                self.emit("movswq %ax, %rax")
            elif size == 4:
                self.emit("movslq %eax, %rax")
            return
        if isinstance(e, SizeofExpr):
            t = e.target_type if e.target_type is not None else getattr(e.operand, "sem_type", None)
            if t is None:
                self.fail("sizeof without type")
            self.emit(f"movq ${self.tsize(t)}, %rax")
            return
        if isinstance(e, MemberExpr):
            self.gen_addr(e)
            ft = getattr(e, "sem_type", None)
            sz = self.tsize(ft) if ft is not None else 8
            if sz == 1:
                self.emit("movsbq (%rax), %rax")
            elif sz == 2:
                self.emit("movswq (%rax), %rax")
            elif sz == 4:
                self.emit("movslq (%rax), %rax")
            else:
                self.emit("movq (%rax), %rax")
            return
        if isinstance(e, CallExpr):
            self.gen_call(e)
            return
        if isinstance(e, IndexExpr):
            self.gen_index(e)
            return
        if isinstance(e, TernaryExpr):
            else_l = self.label("tern_else")
            end_l = self.label("tern_end")
            self.expr(e.cond)
            self.emit("testq %rax, %rax")
            self.emit(f"jz {else_l}")
            self.expr(e.then_expr)
            self.emit(f"jmp {end_l}")
            self.lines.append(f"{else_l}:")
            self.expr(e.else_expr)
            self.lines.append(f"{end_l}:")
            return
        self.fail(type(e).__name__)

    def gen_literal(self, e: LiteralExpr) -> None:
        code = e.code.strip()
        if e.lit_kind == "STRING":
            label = f".Lstr{self.string_id}"
            self.string_id += 1
            self.strings[label] = code
            self.emit(f"leaq {label}(%rip), %rax")
            return
        if e.lit_kind == "CHAR":
            try:
                val = ord(code.strip("'"))
            except Exception:
                self.fail(f"char literal {code}")
            self.emit(f"movq ${val}, %rax")
            return
        if e.lit_kind == "FLOAT_NUM":
            self.fail("float literal")
        raw = code.replace("u", "").replace("U", "").replace("l", "").replace("L", "")
        try:
            val = int(raw, 0)
        except ValueError:
            self.fail(f"integer literal {code}")
        self.emit(f"movq ${val}, %rax")

    def gen_unary(self, e: UnaryExpr) -> None:
        if e.op == "&":
            if isinstance(e.operand, (IdentExpr, IndexExpr, UnaryExpr)):
                self.gen_addr(e.operand)
                return
            self.fail("address-of expression")
        self.expr(e.operand)
        if e.op == "-":
            self.emit("negq %rax")
        elif e.op == "!":
            self.emit("testq %rax, %rax")
            self.emit("sete %al")
            self.emit("movzbq %al, %rax")
        elif e.op == "~":
            self.emit("notq %rax")
        elif e.op == "+":
            pass
        elif e.op == "*":
            self.emit("movq (%rax), %rax")
        else:
            self.fail(f"unary {e.op}")

    def gen_binary(self, e: BinaryExpr) -> None:
        op = e.op
        if op in ("&&", "||"):
            end = self.label("logicend")
            short = self.label("logicshort")
            self.expr(e.left)
            self.emit("testq %rax, %rax")
            self.emit(f"{'jz' if op == '&&' else 'jnz'} {short}")
            self.expr(e.right)
            self.emit("testq %rax, %rax")
            self.emit("setne %al")
            self.emit("movzbq %al, %rax")
            self.emit(f"jmp {end}")
            self.lines.append(f"{short}:")
            self.emit(f"movq ${0 if op == '&&' else 1}, %rax")
            self.lines.append(f"{end}:")
            return
        self.expr(e.left)
        self.emit("pushq %rax")
        self.expr(e.right)
        self.emit("movq %rax, %rcx")
        self.emit("popq %rax")
        if op in ("+", "-", "*", "&", "|", "^"):
            self.binop(op, "%rcx")
            return
        if op in ("/", "%"):
            self.emit("cqto")
            self.emit("idivq %rcx")
            if op == "%":
                self.emit("movq %rdx, %rax")
            return
        if op in ("<<", ">>"):
            self.emit("movq %rcx, %rcx")
            self.emit("salq %cl, %rax" if op == "<<" else "sarq %cl, %rax")
            return
        if op in ("==", "!=", "<", "<=", ">", ">="):
            self.emit("cmpq %rcx, %rax")
            cc = {"==": "e", "!=": "ne", "<": "l", "<=": "le", ">": "g", ">=": "ge"}[op]
            self.emit(f"set{cc} %al")
            self.emit("movzbq %al, %rax")
            return
        self.fail(f"binary {op}")

    def binop(self, op: str, rhs: str) -> None:
        ins = {"+": "addq", "-": "subq", "*": "imulq", "&": "andq", "|": "orq", "^": "xorq"}.get(op)
        if ins is None:
            self.fail(f"binary {op}")
        self.emit(f"{ins} {rhs}, %rax")

    def gen_index(self, e: IndexExpr) -> None:
        self.gen_addr(e)
        t = getattr(e, "sem_type", None)
        size = self.tsize(t) if t is not None else 8
        if size == 1:
            self.emit("movsbq (%rax), %rax")
        elif size == 2:
            self.emit("movswq (%rax), %rax")
        elif size == 4:
            self.emit("movslq (%rax), %rax")
        else:
            self.emit("movq (%rax), %rax")

    def gen_call(self, e: CallExpr) -> None:
        indirect = not isinstance(e.callee, IdentExpr)
        if not indirect:
            assert isinstance(e.callee, IdentExpr)
            indirect = e.callee.name in self.locals or e.callee.name in self.globals
        regs = (["%rcx", "%rdx", "%r8", "%r9"] if self.abi == "win64"
                else ["%rdi", "%rsi", "%rdx", "%rcx", "%r8", "%r9"])
        extra = max(0, len(e.args) - len(regs))
        if extra and self.abi == "win64":
            self.fail("stack arguments on win64")
        if indirect and extra:
            self.fail("indirect call with stack arguments")
        if indirect:
            self.expr(e.callee)
            self.emit("pushq %rax")
            name = ""
        else:
            assert isinstance(e.callee, IdentExpr)
            name = e.callee.name
        pad = 8 if (extra + (1 if indirect else 0)) % 2 else 0
        if 32 + pad:
            self.emit(f"subq ${32 + pad}, %rsp")
        for a in reversed(e.args[len(regs):]):
            self.expr(a)
            self.emit("pushq %rax")
        for a in e.args[:len(regs)]:
            self.expr(a)
            self.emit("pushq %rax")
        for i in range(len(e.args[:len(regs)]) - 1, -1, -1):
            self.emit(f"popq {regs[i]}")
        if indirect:
            # callee is at [rsp + 32 + pad + 8*extra]
            self.emit(f"movq {32 + pad + 8 * extra}(%rsp), %r11")
        self.emit("xorl %eax, %eax")
        if indirect:
            self.emit("call *%r11")
        else:
            self.emit(f"call {name}")
        self.emit(f"addq ${32 + pad + 8 * extra + (8 if indirect else 0)}, %rsp")

    # --------------------------------------------------------------- top level
    def generate(self, nodes: List[StmtNode]) -> str:
        self.collect_structs(nodes)
        funcs = []
        for node in nodes:
            if isinstance(node, StructDefNode):
                continue
            if isinstance(node, PreprocNode):
                text = node.text.strip()
                if text.startswith("#asm"):
                    raw = text[4:].strip()
                    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
                        raw = raw[1:-1]
                    self.lines.append(raw)
                continue
            if isinstance(node, VarDeclStmt):
                self.globals[node.name] = "global"
                self.var_types[node.name] = node.var_type
                gsize = self.tsize(node.var_type)
                if node.init_expr is None:
                    self.lines.append(f".comm {node.name},{gsize},8")
                else:
                    self.lines.append(".data")
                    self.lines.append(".align 8")
                    self.lines.append(f"{node.name}:")
                    # only integer constant globals
                    if isinstance(node.init_expr, LiteralExpr):
                        self.gen_literal(node.init_expr)
                        # gen_literal emitted into .text; use value directly instead
                        self.lines.pop()
                        raw = node.init_expr.code
                        self.lines.append(f"    .quad {raw}")
                    else:
                        self.fail("non-constant global initializer")
                continue
            if isinstance(node, FuncDefNode):
                funcs.append(node)
                continue
            self.fail(type(node).__name__)
        self.functions = {fn.name for fn in funcs}
        self.lines.append(".text")
        for fn in funcs:
            self.gen_function(fn)
        if self.strings:
            self.lines.append(".section .rodata")
            for label, code in self.strings.items():
                self.lines.append(f"{label}:")
                self.lines.append(f"    .string {code}")
        return "\n".join(self.lines) + "\n"


_REG_RE = re.compile(r"^\s*!reg\s+(%[a-z0-9]+)\s*(m,|m\+|m-|m\*|m&|m\||m\^|m<<|m>>|=|\+=|-=|&=|\|=|\^=|<<=|>>=)\s*(.+?)\s*!\s*$")
_ASM_RE = re.compile(r"^\s*!asm\s+\"(.*)\"!\s*$")


def _flyline_reg(line: str) -> str | None:
    m = _REG_RE.match(line)
    if not m:
        return None
    reg, op, value = m.groups()
    if not reg.startswith("%r"):
        return "#asm " + "/* unsupported register */"
    if re.fullmatch(r"-?\d+", value):
        src = "$" + value
    elif re.fullmatch(r"%[a-z0-9]+", value):
        src = value
    else:
        return "#asm " + "/* unsupported register value */"
    ins = {"m,": "movq", "m+": "addq", "m-": "subq", "m&": "andq",
           "m|": "orq", "m^": "xorq", "m*": "imulq", "m<<": "salq", "m>>": "sarq",
           "=": "movq", "+=": "addq", "-=": "subq", "&=": "andq", "|=": "orq", "^=": "xorq"}.get(op)
    if ins is None:
        return "#asm " + f"/* unsupported register op {op} */"
    if op in ("m<<", "m>>", "m*") and not re.fullmatch(r"-?\d+", value):
        return "#asm " + f"/* {op} needs an immediate */"
    return f"#asm {ins} {src}, {reg}"


def preprocess_flylines(src: str) -> str:
    """Turn !reg/!asm/!{...}! into #asm preprocessor lines."""
    out = []
    lines = src.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _ASM_RE.match(line)
        if m:
            out.append("#asm " + m.group(1))
            i += 1
            continue
        r = _flyline_reg(line)
        if r is not None:
            out.append(r)
            i += 1
            continue
        if line.strip().startswith("!{"):
            body = []
            rest = line.split("!{", 1)[1]
            if "}!" in rest:
                out.append("#asm " + rest.split("}!", 1)[0].strip())
                i += 1
                continue
            if rest.strip():
                body.append(rest)
            i += 1
            while i < len(lines) and "}!" not in lines[i]:
                body.append(lines[i])
                i += 1
            if i < len(lines):
                body.append(lines[i].split("}!", 1)[0])
                i += 1
            for b in body:
                if b.strip():
                    out.append("#asm " + b.rstrip())
            continue
        out.append(line)
        i += 1
    return "\n".join(out) + "\n"


def compile_asm(src: str, filename: str = "input.sigil", abi: str = "sysv") -> str:
    EXTERNAL_C_SPELLING.clear()
    src = preprocess_flylines(src)
    tokens = Lexer(src, filename).tokenize()
    ast = Parser(tokens, filename).parse_program()
    return AsmGenerator(filename, abi).generate(ast)



def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sigil-ASM brute: .sigil -> x86-64, no safety checks")
    ap.add_argument("input")
    ap.add_argument("-o", "--output")
    ap.add_argument("--abi", choices=("sysv", "win64"), default=("win64" if os.name == "nt" else "sysv"))
    args = ap.parse_args(argv)
    with open(args.input, encoding="utf-8") as f:
        src = f.read()
    try:
        asm = compile_asm(src, os.path.basename(args.input), args.abi)
    except AsmError as e:
        print(f"sigil-asm-brute: {e}", file=sys.stderr)
        return 2
    out = args.output or (os.path.splitext(args.input)[0] + ".s")
    with open(out, "w", encoding="utf-8") as f:
        f.write(asm)
    print(f"sigil-asm-brute: {args.input} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
