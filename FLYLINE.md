# `!` 飞线：直接穿透寄存器/汇编

Sigil-ASM 的 brute 后端在 Parser 之前处理三类 `!` 飞线。它们不是 Sigil-C 的包飞线，是**低层逃生口**。

---

## 1. 寄存器改写

```sigil
!reg %rax = 7!
!reg %rbx += 3!
!reg %rcx = %rax!
```

支持：

```text
=  +=  -=  &=  |=  ^=
```

只支持 64 位寄存器：

```text
%rax %rbx %rcx %rdx %rsi %rdi %rbp %rsp %r8 ... %r15
```

生成：

```asm
movq $7, %rax
addq $3, %rbx
movq %rax, %rcx
```

不检查寄存器是否被后续代码覆盖，也不检查调用约定。

---

## 2. 单行汇编

```sigil
!asm "nop"!
!asm "movq $42, %rax"!
!asm "syscall"!
```

引号内内容原样进汇编。

---

## 3. 多行汇编块

```sigil
!{
    nop
    movq $1, %rax
    nop
}!
```

每行原样进入当前函数体。

---

## 4. 行为

- 在 Lexer/Parser 之前替换成 `#asm` 行
- 注入位置就是源码位置
- 不参与类型检查、生命周期、ABI 检查
- 写坏寄存器/栈/返回地址，程序自己承担
- `!reg` 的值只接受整数立即数或 `%reg`；其它直接生成注释，不静默猜

---

## 5. 例子

```sigil
i4 main(v.) {
    !reg %rax = 7!
    !reg %rbx += 3!
    !asm "nop"!
    !{ nop
       nop }!
    r; 0;
}
```

生成片段：

```asm
movq $7, %rax
addq $3, %rbx
nop
nop
nop
```

退出码仍是 `0`，因为最后 `r; 0` 覆盖了 `%rax`。

---

一句话：**`!reg` 改寄存器，`!asm` 改单行，`!{...}!` 改一段；没有安全检查。**
