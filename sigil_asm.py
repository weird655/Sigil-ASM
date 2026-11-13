"""Sigil-ASM: .sigil AST -> x86-64 assembly, no C in between.

Experimental. It reuses Sigil-C's lexer/parser and implements only the backend.
Supports exactly:

  - i4 functions with up to 4 i4 parameters
  - a body whose only statement is `r; <expr>;`
  - literals, parameters, + - *, and calls to other functions in the file

Everything else raises. Not a compiler, not maintained.

    python sigil_asm.py demo.sigil -o demo.s
    gcc demo.s -o demo && ./demo; echo $?
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SIGILC_ROOT = os.environ.get("SIGILC_ROOT", os.path.join(HERE, "..", "Sigil-C"))
if os.path.isdir(SIGILC_ROOT):
    sys.path.insert(0, os.path.abspath(SIGILC_ROOT))

from sigilc_core.lexer import Lexer  # noqa: E402
from sigilc_core.nodes import (  # noqa: E402
    BinaryExpr,
    BlockStmt,
    CallExpr,
    FuncDefNode,
    IdentExpr,
    LiteralExpr,
    ReturnStmt,
)
from sigilc_core.parser import Parser  # noqa: E402

if sys.platform == "win32":
    ARG32 = ["%ecx", "%edx", "%r8d", "%r9d"]
    ARG64 = ["%rcx", "%rdx", "%r8", "%r9"]
else:
    ARG32 = ["%edi", "%esi", "%edx", "%ecx"]
    ARG64 = ["%rdi", "%rsi", "%rdx", "%rcx"]


class Unsupported(Exception):
    pass


class AsmGen:
    def __init__(self):
        self.lines = []
        self.params = {}

    def emit(self, line=""):
        self.lines.append(line)

    def expr(self, e):
        if isinstance(e, LiteralExpr):
            if e.lit_kind != "INT_NUM":
                raise Unsupported("only integer literals")
            self.emit(f"    mov ${int(e.code, 0)}, %eax")
        elif isinstance(e, IdentExpr):
            if e.name not in self.params:
                raise Unsupported(f"unknown identifier {e.name}")
            self.emit(f"    mov {self.params[e.name]}(%rbp), %eax")
        elif isinstance(e, BinaryExpr):
            if e.op not in ("+", "-", "*"):
                raise Unsupported(f"operator {e.op}")
            self.expr(e.left)
            self.emit("    push %rax")
            self.expr(e.right)
            self.emit("    mov %eax, %ecx")
            self.emit("    pop %rax")
            self.emit(f"    {'add' if e.op == '+' else 'sub' if e.op == '-' else 'imul'} %ecx, %eax")
        elif isinstance(e, CallExpr):
            if not isinstance(e.callee, IdentExpr):
                raise Unsupported("indirect call")
            if len(e.args) > len(ARG32):
                raise Unsupported("more than 4 arguments")
            for arg in e.args:
                self.expr(arg)
                self.emit("    push %rax")
            for i in reversed(range(len(e.args))):
                self.emit(f"    pop {ARG64[i]}")
            self.emit(f"    call {e.callee.name}")
        else:
            raise Unsupported(type(e).__name__)

    def function(self, fn):
        if not fn.params and fn.name != "main":
            pass
        if len(fn.params) > len(ARG32):
            raise Unsupported("more than 4 parameters")
        if not isinstance(fn.body, BlockStmt) or len(fn.body.stmts) != 1:
            raise Unsupported("body must be exactly one `r; expr;`")
        stmt = fn.body.stmts[0]
        if not isinstance(stmt, ReturnStmt):
            raise Unsupported("body must be a return")

        self.emit("    .text")
        self.emit(f"    .globl {fn.name}")
        self.emit(f"{fn.name}:")
        self.emit("    push %rbp")
        self.emit("    mov %rsp, %rbp")
        self.emit("    sub $16, %rsp")
        self.params = {}
        for i, (_type, name) in enumerate(fn.params):
            off = -4 * (i + 1)
            self.params[name] = off
            self.emit(f"    mov {ARG32[i]}, {off}(%rbp)")
        self.expr(stmt.expr)
        self.emit("    leave")
        self.emit("    ret")
        self.emit("")

    def program(self, text, filename):
        ast = Parser(Lexer(text, filename).tokenize(), filename).parse_program()
        funcs = [n for n in ast if isinstance(n, FuncDefNode)]
        if not funcs:
            raise Unsupported("no functions")
        for fn in funcs:
            self.function(fn)
        return "\n".join(self.lines)


def main():
    ap = argparse.ArgumentParser(description="Sigil-ASM: .sigil -> x86-64 assembly (experimental)")
    ap.add_argument("input")
    ap.add_argument("-o", "--output", default="out.s")
    args = ap.parse_args()

    text = open(args.input, encoding="utf-8").read()
    try:
        asm = AsmGen().program(text, args.input)
    except Unsupported as exc:
        print(f"sigil-asm: unsupported: {exc}", file=sys.stderr)
        return 1
    with open(args.output, "w", encoding="utf-8", newline="\n") as f:
        f.write(asm + "\n")
    print(f"sigil-asm: {args.input} -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
