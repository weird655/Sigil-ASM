#!/usr/bin/env python3
"""Smoke test for the brute ASM backend."""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    work = tempfile.mkdtemp(prefix="sigil-asm-brute-")
    spath = os.path.join(work, "demo.s")
    exe = os.path.join(work, "demo.exe")
    r = subprocess.run([sys.executable, os.path.join(HERE, "sigil_asm_brute.py"),
                        os.path.join(HERE, "demo.sigil"), "-o", spath],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return 1
    r = subprocess.run(["gcc", spath, "-o", exe], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return 1
    r = subprocess.run([exe], capture_output=True, text=True)
    if r.returncode != 42:
        print(f"expected exit 42, got {r.returncode}", file=sys.stderr)
        return 1
    print("brute demo: exit 42")
    return lowlevel()


def lowlevel() -> int:
    src = """#asm "nop"
i4 main(v.) {
    o! i4[3] a;
    o! p* i4 p m, p@ a[0];
    p[0] m, 4;
    p[1] m, 5;
    p[2] m, 6;
    r; a[0] + a[1] + a[2];
}
"""
    work = tempfile.mkdtemp(prefix="sigil-asm-low-")
    spath = os.path.join(work, "low.s")
    exe = os.path.join(work, "low.exe")
    with open(os.path.join(work, "low.sigil"), "w", encoding="utf-8") as f:
        f.write(src)
    r = subprocess.run([sys.executable, os.path.join(HERE, "sigil_asm_brute.py"),
                        os.path.join(work, "low.sigil"), "-o", spath],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return 1
    r = subprocess.run(["gcc", spath, "-o", exe], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return 1
    r = subprocess.run([exe], capture_output=True, text=True)
    if r.returncode != 15:
        print(f"lowlevel: expected 15, got {r.returncode}", file=sys.stderr)
        return 1
    print("lowlevel: arrays/pointers/#asm exit 15")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
