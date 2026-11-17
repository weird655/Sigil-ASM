# Brute backend

`sigil_asm_brute.py` is the **unsafe / brute** sibling of `sigil_asm.py`.

It still reads `.sigil` with Sigil-C's lexer/parser, but it does **not** try to
prove anything:

- no overflow checks
- no lifetime checks
- no heap checks
- no bounds checks
- no `!` flyline risk analysis
- no ABI proof beyond the generated subset

It is closer to "assembly+++": same source syntax, direct x86-64 output, and
the unsafe parts are your problem.

## Usage

```bash
export SIGILC_ROOT=/path/to/Sigil-C
python sigil_asm_brute.py demo.sigil -o demo.s
gcc demo.s -o demo
./demo
```

Windows:

```powershell
$env:SIGILC_ROOT="C:\path\to\Sigil-C"
python sigil_asm_brute.py demo.sigil -o demo.s
gcc demo.s -o demo.exe
```

`--abi sysv|win64` selects the calling convention; the default follows the
host platform.

## Current subset

- integer/pointer locals
- parameters and return values
- `+ - * / %`, bitwise, comparisons
- `i? / e:`, `w~`, `d~`, `f~`
- `b! / c^`
- global integer variables
- string literals + `printf`
- unary `- ! ~ * &`
- local arrays and real stack slots
- structs with natural field layout
- function pointers and indirect calls
- `sizeof(type)`
- `!reg` register rewrites, `!asm` and `!{...}!` raw-assembly flylines
- pointer subscript reads/writes
- `p@ a[i]` address-of
- `#asm "..."` raw assembly injection
- SysV and Win64 register + stack arguments

Not supported (fails loudly):

- bitfields, floats
- complex `!` package/plant forms
- indirect calls / function pointers
- stack-passed arguments
- complex lvalue writes
- optimization / register allocation

See [`LOWLEVEL.md`](LOWLEVEL.md) for array/pointer/raw-asm examples.

## Relation to the strict backend

- `sigil_asm.py` — refuses almost everything; proof-oriented; `CHECKS.md`
- `sigil_asm_brute.py` — accepts a broad subset and emits; **not proof-oriented**

Keep the strict backend as the contract. Use the brute backend when you know
what you are doing.
