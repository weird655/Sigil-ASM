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
    rc = structs_and_fp()
    if rc:
        return rc
    rc = flyline()
    if rc:
        return rc
    return stack_args()


def structs_and_fp() -> int:
    src = """s{ P {
    i4 x;
    i4 y;
};
i4 add(i4 a, i4 b) { r; a + b; }
i4 main(v.) {
    o! P p;
    p.x m, 10;
    p.y m, 20;
    o! f^(i4, i4) -> i4 cb m, add;
    r; p.x + p.y + cb(4, 5);
}
"""
    work = tempfile.mkdtemp(prefix="sigil-asm-struct-")
    spath = os.path.join(work, "s.s")
    exe = os.path.join(work, "s.exe")
    src_path = os.path.join(work, "s.sigil")
    with open(src_path, "w", encoding="utf-8") as f:
        f.write(src)
    r = subprocess.run([sys.executable, os.path.join(HERE, "sigil_asm_brute.py"), src_path, "-o", spath],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return 1
    r = subprocess.run(["gcc", spath, "-o", exe], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return 1
    r = subprocess.run([exe], capture_output=True, text=True)
    if r.returncode != 39:
        print(f"struct/fp: expected 39, got {r.returncode}", file=sys.stderr)
        return 1
    print("struct/fp: exit 39")
    return 0


def flyline() -> int:
    src = """i4 main(v.) {
    !reg %rax = 7!
    !reg %rbx += 3!
    !asm "nop"!
    !{ nop
       nop }!
    r; 0;
}
"""
    work = tempfile.mkdtemp(prefix="sigil-asm-fly-")
    src_path = os.path.join(work, "fly.sigil")
    spath = os.path.join(work, "fly.s")
    exe = os.path.join(work, "fly.exe")
    with open(src_path, "w", encoding="utf-8") as f:
        f.write(src)
    r = subprocess.run([sys.executable, os.path.join(HERE, "sigil_asm_brute.py"), src_path, "-o", spath],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return 1
    text = open(spath, encoding="utf-8").read()
    if "movq $7, %rax" not in text or "addq $3, %rbx" not in text:
        print("flyline: register rewrite missing", file=sys.stderr)
        return 1
    r = subprocess.run(["gcc", spath, "-o", exe], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return 1
    r = subprocess.run([exe], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"flyline: expected 0, got {r.returncode}", file=sys.stderr)
        return 1
    print("flyline: !reg/!asm/!{} injected")
    return 0


def stack_args() -> int:
    src = """i4 sum7(i4 a, i4 b, i4 c, i4 d, i4 e, i4 f, i4 g) {
    r; a + b + c + d + e + f + g;
}
i4 main(v.) { r; sum7(1, 2, 3, 4, 5, 6, 7); }
"""
    work = tempfile.mkdtemp(prefix="sigil-asm-args-")
    src_path = os.path.join(work, "args.sigil")
    spath = os.path.join(work, "args.s")
    exe = os.path.join(work, "args.exe")
    with open(src_path, "w", encoding="utf-8") as f:
        f.write(src)
    r = subprocess.run([sys.executable, os.path.join(HERE, "sigil_asm_brute.py"), src_path,
                        "--abi", "sysv", "-o", spath], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return 1
    r = subprocess.run(["gcc", spath, "-o", exe], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr, file=sys.stderr)
        return 1
    r = subprocess.run([exe], capture_output=True, text=True)
    if r.returncode != 28:
        print(f"stack args: expected 28, got {r.returncode}", file=sys.stderr)
        return 1
    print("stack args: SysV 7 args exit 28")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
