# Sigil-ASM

**实验性项目**：把 `.sigil` 直接降到 x86-64 汇编，不经过 C。

这是 [Sigil-C](https://github.com/weird655/Sigil-C) 的姊妹实验，独立仓库：

| 项目 | 后端 | 状态 |
|---|---|---|
| **Sigil-C** | `.sigil → ISO C99` | 可用、有测试、v1.1 |
| **Sigil-ASM** | `.sigil → x86-64 汇编` | 概念验证，只支持一个子集 |

Sigil-ASM **复用 Sigil-C 的 lexer / parser / AST**，自己只实现"AST → 汇编"这一层。所以它需要能 import 到 `sigilc_core`：

```bash
# 开发时：把 Sigil-C 放在同级目录，或显式指定
export SIGILC_ROOT=/path/to/Sigil-C      # Windows: $env:SIGILC_ROOT="C:\path\to\Sigil-C"
```

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

## 支持范围

- `i4` 函数，最多 4 个 `i4` 形参
- 函数体恰好一条 `r; <expr>;`
- 整数字面量、形参、`+ - *`、同文件函数调用
- Linux 用 SysV 寄存器（`rdi/rsi/rdx/rcx`），Windows 用 Microsoft x64（`rcx/rdx/r8/r9`）

其他一律 `unsupported`，直接报错，不猜。

## 不支持（也是 Sigil-C 不自己写后端的原因）

- 所有语句与类型、结构体布局、位域
- 浮点、可变参数、`va_list`
- 完整的 ABI、目标文件格式、重定位
- 优化器

这些 C 工具链已经做了几十年。Sigil-ASM 的存在只是证明"AST 能直接到机器码"，不是要替代 gcc。

## 许可

MIT，见 [`LICENSE`](LICENSE)。
