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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
