# Sigil-ASM

**拒绝优先。**

这是一个证明"AST 能直接到 x86-64 汇编"的后端，不是一个编译器。它拒绝的程序比接受的多；如果你不在契约里，它一行都不生成，也不会"尽力而为"。

先读 [`CHECKS.md`](CHECKS.md)。那是完整的拒绝清单，每条都有错误码和"什么条件下才会支持"。

## 它只接受这些

1. 顶层只有函数定义（`#include` 也不行）
2. 恰好一个 `i4 main(v.)`，无参数
3. 所有函数返回 `i4`，所有参数是 `i4`，最多 4 个
4. 函数体恰好一条 `r; expr;`
5. 表达式只有：`0..2147483647` 的整数字面量、参数、`+ - *`、同文件函数调用
6. 无递归、不调用 `main`、没有从 `main` 不可达的函数
7. 最多 32 个函数，表达式深度最多 32
8. 平台是 win32 / linux / darwin（Microsoft x64 或 SysV）

除此之外，全部拒绝。

## 拒绝长什么样

```console
$ python sigil_asm.py bad.sigil -o bad.s
sigil-asm: refusing to emit: 2 violation(s)
  E016 line 3: operator '/' is refused (only + - *)
  E010 line 4: identifier 'nope' is not a parameter
  see CHECKS.md for what each code means and what would lift it
```

退出码 `2`，不落盘。它不会生成"半对"的汇编。

## 环境要求

- x86-64；其它架构直接拒绝（E017）
- 能 import 到 Sigil-C 的 lexer/parser：

```bash
export SIGILC_ROOT=/path/to/Sigil-C        # Windows: $env:SIGILC_ROOT="C:\...\Sigil-C"
```

这里复用 Sigil-C 的前端，不复制一份 parser——分仓，但不重复实现。

## 用法

```bash
python sigil_asm.py demo.sigil -o demo.s
gcc demo.s -o demo
./demo
echo $?
```

`demo.sigil`：

```sigil
i4 add(i4 a, i4 b) { r; a + b; }

i4 main(v.) {
    r; add(20, 22);
}
```

退出码：`42`。

只校验、不生成：

```bash
python sigil_asm.py demo.sigil --check
```

## 自测

```bash
python tests.py
python brute_tests.py   # brute backend smoke
```

20 项检查：demo 必须干净通过，每个拒绝码各有一个反例，深度和函数数上限各有一个。任何一项不符合预期就退出 `1`。

## 为什么这么严

因为每放宽一条，都要先证明：ABI、栈布局、生命周期、类型布局。这个后端只做它能证明的那部分；证明不了就拒绝，而不是猜。

需要更多能力，用 [Sigil-C](https://github.com/weird655/Sigil-C)——它转 C99，有 200 项测试；这里只负责证明"直接到机器码"这条路存在。

## Brute backend

`sigil_asm.py` 是拒绝优先的证明后端；同仓库还有一个暴力版本：

```bash
python sigil_asm_brute.py demo.sigil -o demo.s
gcc demo.s -o demo
```

它复用同一套 `.sigil` 语法和 x86-64 后端，但**不查**溢出、生命周期、堆、越界、`!` 飞线风险。
当前子集包括整数/指针局部变量、算术、分支、循环、直接调用、字符串、简单指针下标。
限制与行为见 [`BRUTE.md`](BRUTE.md)。

## 许可证

MIT，见 [`LICENSE`](LICENSE)。
