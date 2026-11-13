#!/usr/bin/env python3
"""Sigil-ASM: .sigil AST -> x86-64 assembly, no C in between.

This is a proof-of-concept backend that refuses far more than it accepts. It
validates the whole program up front, reports every violation with a code,
and emits nothing unless the program is inside the contract in CHECKS.md.

It reuses Sigil-C's lexer/parser:

    SIGILC_ROOT=/path/to/Sigil-C python sigil_asm.py demo.sigil -o demo.s

Not a compiler. Not maintained. No support.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SIGILC_ROOT = os.environ.get("SIGILC_ROOT", os.path.join(HERE, "..", "Sigil-C"))
if os.path.isdir(SIGILC_ROOT):
    sys.path.insert(0, os.path.abspath(SIGILC_ROOT))

from sigilc_core.lexer import Lexer, LexerError  # noqa: E402
from sigilc_core.nodes import (  # noqa: E402
    BinaryExpr,
    BlockStmt,
    CallExpr,
    FuncDefNode,
    IdentExpr,
    LiteralExpr,
    ParseError,
    ReturnStmt,
    SemanticError,
)
from sigilc_core.parser import Parser  # noqa: E402

MAX_PARAMS = 4
MAX_FUNCS = 32
MAX_DEPTH = 32
MAX_LITERAL = 2**31 - 1

if sys.platform == "win32":
    ABI = "win64"
    ARG32 = ["%ecx", "%edx", "%r8d", "%r9d"]
    ARG64 = ["%rcx", "%rdx", "%r8", "%r9"]
elif sys.platform in ("linux", "darwin"):
    ABI = "sysv"
    ARG32 = ["%edi", "%esi", "%edx", "%ecx"]
    ARG64 = ["%rdi", "%rsi", "%rdx", "%rcx"]
else:
    ABI = None
    ARG32 = ARG64 = []


class Errors:
    def __init__(self):
        self.items = []

    def add(self, code, line, message):
        self.items.append((code, line, message))

    def __bool__(self):
        return bool(self.items)


def _is_i4(t) -> bool:
    return getattr(t, "c_name", None) == "int32_t"


def _check_expr(e, params, funcs, errs, depth=0):
    if depth > MAX_DEPTH:
        errs.add("E015", getattr(e, "line", 0), f"expression deeper than {MAX_DEPTH}")
        return
    if isinstance(e, LiteralExpr):
        if e.lit_kind != "INT_NUM":
            errs.add("E011", e.line, f"literal kind {e.lit_kind} is not an integer")
            return
        value = int(e.code, 0)
        if value < 0 or value > MAX_LITERAL:
            errs.add("E011", e.line, f"literal {value} outside 0..{MAX_LITERAL}")
    elif isinstance(e, IdentExpr):
        if e.name not in params:
            errs.add("E010", e.line, f"identifier '{e.name}' is not a parameter")
    elif isinstance(e, BinaryExpr):
        if e.op not in ("+", "-", "*"):
            errs.add("E016", e.line, f"operator '{e.op}' is refused (only + - *)")
        _check_expr(e.left, params, funcs, errs, depth + 1)
        _check_expr(e.right, params, funcs, errs, depth + 1)
    elif isinstance(e, CallExpr):
        if not isinstance(e.callee, IdentExpr):
            errs.add("E009", e.line, "calls must name a function directly")
            return
        name = e.callee.name
        if name == "main":
            errs.add("E021", e.line, "main must not be called")
        elif name not in funcs:
            errs.add("E012", e.line, f"call to unknown function '{name}'")
        elif len(e.args) != len(funcs[name].params):
            errs.add("E013", e.line, f"'{name}' takes {len(funcs[name].params)} argument(s), got {len(e.args)}")
        for arg in e.args:
            _check_expr(arg, params, funcs, errs, depth + 1)
    else:
        errs.add("E009", getattr(e, "line", 0), f"expression node {type(e).__name__} is refused")


def _validate_ast(ast):
    errs = Errors()
    funcs = {}
    for node in ast:
        if not isinstance(node, FuncDefNode):
            errs.add("E001", getattr(node, "line", 0), f"top-level {type(node).__name__} is refused (only functions)")
            continue
        if node.name in funcs:
            errs.add("E002", node.line, f"duplicate function '{node.name}'")
            continue
        funcs[node.name] = node
    if len(funcs) > MAX_FUNCS:
        errs.add("E023", 0, f"{len(funcs)} functions, limit is {MAX_FUNCS}")
    if "main" not in funcs:
        errs.add("E003", 0, "missing i4 main(v.)")
        return funcs, errs
    main = funcs["main"]
    if main.params:
        errs.add("E004", main.line, "main must take no parameters")
    if not _is_i4(main.return_type):
        errs.add("E005", main.line, "main must return i4")

    for fn in funcs.values():
        if not _is_i4(fn.return_type):
            errs.add("E005", fn.line, f"'{fn.name}' must return i4")
        if len(fn.params) > MAX_PARAMS:
            errs.add("E007", fn.line, f"'{fn.name}' has {len(fn.params)} parameters, limit is {MAX_PARAMS}")
        params = set()
        for t, name in fn.params:
            if not _is_i4(t):
                errs.add("E006", fn.line, f"'{fn.name}' parameter '{name}' is not i4")
            params.add(name)
        if not isinstance(fn.body, BlockStmt) or len(fn.body.stmts) != 1 or not isinstance(fn.body.stmts[0], ReturnStmt):
            errs.add("E008", fn.line, f"'{fn.name}' body must be exactly one `r; expr;`")
            continue
        _check_expr(fn.body.stmts[0].expr, params, funcs, errs)

    # call graph: cycles and reachability
    edges = {}
    for name, fn in funcs.items():
        targets = set()

        def walk(e):
            if isinstance(e, CallExpr) and isinstance(e.callee, IdentExpr):
                targets.add(e.callee.name)
            for child in getattr(e, "args", []):
                walk(child)
            if isinstance(e, BinaryExpr):
                walk(e.left)
                walk(e.right)

        if isinstance(fn.body, BlockStmt) and fn.body.stmts and isinstance(fn.body.stmts[0], ReturnStmt):
            walk(fn.body.stmts[0].expr)
        edges[name] = targets

    color = {}

    def dfs(name, stack):
        if color.get(name) == 1:
            cycle = " -> ".join(stack + [name])
            errs.add("E014", funcs[name].line, f"recursion is refused: {cycle}")
            return
        if color.get(name) == 2:
            return
        color[name] = 1
        for nxt in edges.get(name, ()):
            if nxt in funcs:
                dfs(nxt, stack + [name])
        color[name] = 2

    dfs("main", [])
    reachable = set()

    def mark(name):
        if name in reachable or name not in funcs:
            return
        reachable.add(name)
        for nxt in edges.get(name, ()):
            mark(nxt)

    mark("main")
    for name in funcs:
        if name not in reachable:
            errs.add("E022", funcs[name].line, f"'{name}' is unreachable from main; remove it")
    return funcs, errs


def validate(text, filename):
    try:
        ast = Parser(Lexer(text, filename).tokenize(), filename).parse_program()
    except (LexerError, ParseError, SemanticError) as exc:
        errs = Errors()
        errs.add("E000", 0, f"front end refused: {exc}")
        return {}, errs
    return _validate_ast(ast)


class AsmGen:
    def __init__(self):
        self.lines = []
        self.params = {}

    def emit(self, line=""):
        self.lines.append(line)

    def expr(self, e):
        if isinstance(e, LiteralExpr):
            self.emit(f"    mov ${int(e.code, 0)}, %eax")
        elif isinstance(e, IdentExpr):
            self.emit(f"    mov {self.params[e.name]}(%rbp), %eax")
        elif isinstance(e, BinaryExpr):
            self.expr(e.left)
            self.emit("    push %rax")
            self.expr(e.right)
            self.emit("    mov %eax, %ecx")
            self.emit("    pop %rax")
            op = {"+": "add", "-": "sub", "*": "imul"}[e.op]
            self.emit(f"    {op} %ecx, %eax")
        elif isinstance(e, CallExpr):
            for arg in e.args:
                self.expr(arg)
                self.emit("    push %rax")
            for i in reversed(range(len(e.args))):
                self.emit(f"    pop {ARG64[i]}")
            self.emit(f"    call {e.callee.name}")

    def function(self, fn):
        self.emit(f"    # {fn.name}: {len(fn.params)} param(s), i4")
        self.emit("    .text")
        self.emit(f"    .globl {fn.name}")
        self.emit(f"{fn.name}:")
        self.emit("    push %rbp")
        self.emit("    mov %rsp, %rbp")
        self.emit("    sub $16, %rsp")
        self.params = {}
        for i, (_t, name) in enumerate(fn.params):
            self.params[name] = -4 * (i + 1)
            self.emit(f"    mov {ARG32[i]}, {self.params[name]}(%rbp)")
        self.expr(fn.body.stmts[0].expr)
        self.emit("    leave")
        self.emit("    ret")
        self.emit("")

    def program(self, funcs):
        self.emit(f"    # generated by sigil-asm; ABI={ABI}; DO NOT EDIT")
        for fn in funcs.values():
            self.function(fn)
        if ABI == "sysv":
            self.emit('    .section .note.GNU-stack,"",@progbits')
        return "\n".join(self.lines)


def main():
    ap = argparse.ArgumentParser(description="Sigil-ASM: .sigil -> x86-64 (experimental, refuses most input)")
    ap.add_argument("input")
    ap.add_argument("-o", "--output", default="out.s")
    ap.add_argument("--check", action="store_true", help="validate only, emit nothing")
    args = ap.parse_args()

    if ABI is None:
        print(f"sigil-asm: E017 platform {sys.platform!r} is not supported (win32/linux/darwin only)", file=sys.stderr)
        return 2
    text = open(args.input, encoding="utf-8").read()
    funcs, errs = validate(text, args.input)
    if errs:
        print(f"sigil-asm: refusing to emit: {len(errs.items)} violation(s)", file=sys.stderr)
        for code, line, message in errs.items:
            print(f"  {code} line {line}: {message}", file=sys.stderr)
        print("  see CHECKS.md for what each code means and what would lift it", file=sys.stderr)
        return 2
    if args.check:
        print(f"sigil-asm: {args.input} is inside the contract ({len(funcs)} function(s), ABI={ABI})")
        return 0
    with open(args.output, "w", encoding="utf-8", newline="\n") as f:
        f.write(AsmGen().program(funcs) + "\n")
    print(f"sigil-asm: {args.input} -> {args.output} (ABI={ABI})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
