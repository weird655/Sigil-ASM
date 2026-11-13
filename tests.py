#!/usr/bin/env python3
"""Refusal matrix for sigil-asm. Every case must produce its code.

    SIGILC_ROOT=/path/to/Sigil-C python tests.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SIGILC_ROOT = os.environ.get("SIGILC_ROOT", os.path.join(HERE, "..", "Sigil-C"))
if os.path.isdir(SIGILC_ROOT):
    sys.path.insert(0, os.path.abspath(SIGILC_ROOT))
sys.path.insert(0, HERE)

import sigil_asm as sa  # noqa: E402

DEMO = """i4 add(i4 a, i4 b) { r; a + b; }

i4 main(v.) {
    r; add(20, 22);
}
"""

CASES = [
    ("E001", "#include <stdio.h>\ni4 main(v.) { r; 0; }"),
    ("E000", "i4 main(v.) { r; 0; }\ni4 main(v.) { r; 1; }"),
    ("E003", "i4 f(v.) { r; 1; }"),
    ("E004", "i4 main(i4 argc) { r; 0; }"),
    ("E005", "f8 main(v.) { r; 0; }"),
    ("E006", "i4 f(f8 x) { r; 0; }\ni4 main(v.) { r; 0; }"),
    ("E007", "i4 f(i4 a, i4 b, i4 c, i4 d, i4 e) { r; a; }\ni4 main(v.) { r; 0; }"),
    ("E008", "i4 f(v.) { r; 1; r; 2; }\ni4 main(v.) { r; 0; }"),
    ("E009", "i4 main(v.) { r; (i4)1; }"),
    ("E000", "i4 main(v.) { r; nope; }"),
    ("E011", "i4 main(v.) { r; 1.5; }"),
    ("E000", "i4 main(v.) { r; nope(); }"),
    ("E000", "i4 f(i4 a) { r; a; }\ni4 main(v.) { r; f(); }"),
    ("E014", "i4 f(i4 n) { r; f(n); }\ni4 main(v.) { r; f(1); }"),
    ("E016", "i4 main(v.) { r; 4 / 2; }"),
    ("E021", "i4 main(v.) { r; main(); }"),
    ("E022", "i4 f(v.) { r; 1; }\ni4 main(v.) { r; 0; }"),
]


def codes_for(src):
    _funcs, errs = sa.validate(src, "case.sigil")
    return {code for code, _line, _msg in errs.items}


def main():
    failures = 0
    funcs, errs = sa.validate(DEMO, "demo.sigil")
    if errs or not funcs:
        failures += 1
        print("FAIL demo should validate clean:", errs.items)
    else:
        print("ok   demo validates clean")
        asm = sa.AsmGen().program(funcs)
        if ".globl add" not in asm or ".globl main" not in asm:
            failures += 1
            print("FAIL generated assembly is missing function symbols")

    # deep expression -> E015
    deep = "i4 main(v.) { r; " + "(" * 33 + "1" + " + 1)" * 33 + "; }"
    if "E015" not in codes_for(deep):
        failures += 1
        print("FAIL E015 not raised for a 33-deep expression")
    else:
        print("ok   E015 depth limit")

    # too many functions -> E023
    many = "".join(f"i4 fn{i}(v.) {{ r; {i}; }}\n" for i in range(33))
    many += "i4 main(v.) { r; 0; }"
    if "E023" not in codes_for(many):
        failures += 1
        print("FAIL E023 not raised for 33 functions")
    else:
        print("ok   E023 function limit")

    for expected, src in CASES:
        got = codes_for(src)
        if expected not in got:
            failures += 1
            print(f"FAIL {expected} missing; got {sorted(got)} for:\n{src}")
        else:
            print(f"ok   {expected}")

    if failures:
        print(f"\n{failures} failure(s)")
        return 1
    print(f"\n{len(CASES) + 3} checks passed; backend is as strict as advertised")
    return 0


if __name__ == "__main__":
    sys.exit(main())
