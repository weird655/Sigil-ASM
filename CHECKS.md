# Checks: every reason this backend will refuse you

The backend validates the entire program before emitting a single line. All
violations are reported at once, each with a code. Nothing is guessed.

| Code | Refuses | What would lift it |
|---|---|---|
| E000 | the front end (lexer/parser/type checker) refused the program before this backend saw it; the message is included | fixing the source |
| E001 | any top-level node that is not a function (e.g. `#include`) | a preprocessor model |
| E002 | duplicate function names | name mangling or modules |
| E003 | no `i4 main(v.)` | — |
| E004 | `main` with parameters | an argv/argc model |
| E005 | `main` (or any function) returning something other than `i4` | more return-value ABIs |
| E006 | a parameter that is not `i4` | struct/float/pointer parameters |
| E007 | more than 4 parameters | stack-passed arguments and a real ABI |
| E008 | a body that is not exactly one `r; expr;` | every other statement |
| E009 | any expression node except literal/identifier/binary/call | casts, unary, arrays, members, … |
| E010 | an identifier that is not a parameter | locals and globals |
| E011 | non-integer or out-of-range literals | negative/64-bit literals |
| E012 | a call to a function not defined in the file | external symbols and relocations |
| E013 | a call with the wrong argument count | varargs and overloads |
| E014 | recursion (any call-graph cycle) | a fixed-point analysis |
| E015 | expression depth over 32 | — |
| E016 | any operator except `+ - *` | division, shifts, comparisons, … |
| E017 | a platform that is not win32/linux/darwin | another ABI |
| E021 | calling `main` | — |
| E022 | a function unreachable from `main` | — (remove it) |
| E023 | more than 32 functions | — |

## Contract summary

A program is accepted only if **all** of these hold:

1. Only function definitions at top level.
2. Exactly one `i4 main(v.)`, taking no parameters.
3. Every function returns `i4`, every parameter is `i4`, at most 4 parameters.
4. Every body is one `r; expr;`.
5. Expressions: integer literals in `0..2147483647`, parameters, `+ - *`,
   and direct calls to functions defined in the same file.
6. No recursion, no calls to `main`, no unreachable functions.
7. At most 32 functions, expression depth at most 32.
8. Platform is win32, linux or darwin (SysV or Microsoft x64).

If you need anything outside this list, this is the wrong backend.
Sigil-C (the C99 transpiler) supports far more, with tests.
