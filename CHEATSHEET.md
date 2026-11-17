# Sigil-ASM 速查表

> 源语法仍是 `.sigil`。这里只列 **brute 后端**当前真正认识的东西。  
> 不认识的会报 `ASM backend does not support ...`，不静默生成。

---

## 1. 命令

```bash
# Linux / WSL（SysV）
python sigil_asm_brute.py prog.sigil -o prog.s
gcc prog.s -o prog

# Windows（Win64）
python sigil_asm_brute.py prog.sigil --abi win64 -o prog.s
gcc prog.s -o prog.exe
```

| 选项 | 作用 |
|---|---|
| `--abi sysv` | System V AMD64 |
| `--abi win64` | Microsoft x64 |
| 默认 | Windows → win64，其它 → sysv |
| `SIGILC_ROOT` | Sigil-C 前端路径 |

---

## 2. 类型 / 变量

```sigil
i4 x;                  /* 局部标量 */
o! i4 x m, 1;          /* 带初值 */
o! i4[4] a;            /* 局部数组 */
o! p* i4 p;            /* 指针 */
o! P p;                /* 结构体 */
```

- 栈槽按真实大小分配
- 数组下标读写
- 指针 `p[i]`、`p@ a[i]`
- 结构体 `.` / `->`
- `sizeof(T)` / `sizeof(expr)`

---

## 3. 运算

```text
+ - * / % & | ^ << >> ~ !
== != < <= > >= && ||
```

- 所有值按 64 位处理
- 不做溢出检查
- 不做类型检查

---

## 4. 判定

```sigil
i? (x == 0) {
    ...
} e: {
    ...
}
```

## 5. 循环

```sigil
w~ (x < 10) { ... }
d~ { ... } w~ (x < 10);
f~ (i4 i m, 0; i < 10; i m+ 1) { ... }
loop 没有；用 w~ / f~ / goto
```

## 6. `switch`

```sigil
s? (x) {
    k: 1: { ... b!; }
    k: 2: { ... b!; }
    d:    { ... }
}
```

## 7. `goto` / label

```sigil
l! again;
...
g! again;
```

---

## 8. 函数 / 调用

```sigil
i4 add(i4 a, i4 b) { r; a + b; }

i4 main(v.) {
    r; add(1, 2);
}
```

- 直接调用
- 函数指针间接调用
- SysV 前 6 个寄存器参数，第 7 个起走栈
- Win64 最多 4 个参数

---

## 9. 结构体 / 函数指针

```sigil
s{ P {
    i4 x;
    i4 y;
};

p->x;
p.y;
sizeof(P);

o! f^(i4, i4) -> i4 cb m, add;
cb(1, 2);
```

---

## 10. `!` 飞线

| 写法 | 作用 |
|---|---|
| `!reg %rax m, 7!` | 寄存器赋值 |
| `!reg %rbx m+ 3!` | 寄存器复合运算 |
| `!reg %rcx m, %rax!` | 寄存器复制 |
| `!asm "nop"!` | 单行原生汇编 |
| `!{ ... }!` | 多行原生汇编 |

支持 `m, m+ m- m* m& m| m^ m<< m>>`，只支持 `%r*` 64 位寄存器。

---

## 11. `#asm`

```sigil
#asm "nop"
#asm "syscall"
```

和 `!asm` 等价，直接进输出汇编。

---

## 12. 当前边界

| 能力 | 状态 |
|---|---|
| 局部标量/数组/指针 | ✅ |
| 结构体/成员/`sizeof` | ✅ |
| 函数指针/间接调用 | ✅ |
| `switch` / `goto` | ✅ |
| SysV 栈参数 | ✅ |
| Win64 栈参数 | ⛔ |
| 浮点 / SSE | ⛔ |
| 位域 | ⛔ |
| 复杂聚合初始化 | ⛔ |
| 优化/寄存器分配 | ⛔ |
| 安全检查 | ⛔ 故意没有 |

---

## 13. 测试

```bash
python tests.py          # strict 后端 20 项拒绝矩阵
python brute_tests.py    # brute demo / 低层 / 结构体 / ! 飞线 / 栈参数
```

---

## 14. 一句话

> **认得的直接生成，不认得的才报；安全检查没有，寄存器/汇编自己负责。**
