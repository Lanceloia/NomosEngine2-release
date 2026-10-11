# T0：运行迹见证检查

## 设计动机与当前能力

作者可以先描述一个精彩故事，再探索怎样的事实、能力与规则能让它自然发生。
T0 的长期目标，是帮助作者把故事整理为约束，提出并修订规则候选，最后通过真实运行检验。
故事是创作样例，实际游玩仍由玩家选择与世界规则共同推进。

当前模块实现这条路线中的**行动见证检查**；故事理解、规则推导与自动设计尚待建设。
完整创作路线见[项目定位与北极星](../../docs/NOMOS_PRODUCT_PROPOSITION.md#为什么需要-t0从故事开始创作)。

## 当前运行方式

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

控制预算结束只表示 `not_met_within_bound`，不是全局不可达证明。
已发生的前缀保留；诊断不保证能定位作者错误根因。
当前范围见[语义说明](../../docs/SEMANTICS.md)，旧实验不作为备用入口。
