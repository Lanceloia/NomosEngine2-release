# T0：运行迹见证检查

T0 接受当前 C0 的作者文件、某局 Assets，以及作者提出的一串行动。
它启动真实 K0 Session，按当前席位的实际候选逐步提交，而不是自己模拟规则后果。

```text
Lib / Ports / Source -> C0 Program
Program / Assets / trace -> T0 -> 实际 K0 发布或结构化失败报告
```

[`witness_v0.py`](witness_v0.py) 定义检查与报告；
[`author_check_v0.py`](author_check_v0.py) 提供文件入口：

```bash
.venv/bin/python -m nomos_t0.author_check_v0 --help
.venv/bin/python -m pytest -q tests/nomos_t0/test_witness_v0.py
```

见证通过只说明这条行动序列在给定规则和开局中实际成功，不证明所有玩法可达，
不求解 NPC 心智，不生成剧情，也不自动定位作者错误的根因。
候选缺失、K0 有限拒绝和准入后的结算缺陷须分别报告。

旧 T0 中与讨论、host handoff、selected-K 分类有关的实验已
[归档](../../archive/README.md)，不是当前检查器的前置或备用入口。
