# 现行源码

本目录包含五个可安装 Python 包，安装配置以根目录 [pyproject.toml](../pyproject.toml) 为准。
现行导航见 CURRENT（研究仓路径：`docs/CURRENT.md`），目录分工见项目结构（研究仓路径：`docs/PROJECT_STRUCTURE.md`）。

| 包 | 职责 | 阅读入口 |
| --- | --- | --- |
| `nomos_c0` | 作者声明装配、类型与语义检查、编译计划、生成 Python | [C0](nomos_c0/README.md) |
| `nomos_runtime` | Start、Session、身份、信息、准入、原子事务与控制 | [Runtime](nomos_runtime/README.md) |
| `nomos_cognition` | 纯认知、经验、评价与规划算法 | [Cognition](nomos_cognition/README.md) |
| `nomos_play` | 游戏目录、共享桌面、玩家输入与电脑参与 | [Play](nomos_play/README.md) |
| `nomos_t0` | 用同一生成产物执行命名行动见证 | [T0](nomos_t0/README.md) |

```text
nomos_c0: Lib + Source -> 检查 -> Python Program
nomos_runtime: Program + Assets -> Session -> 行动、结果与许可信息
nomos_play / CLI / nomos_t0: 消费同一产物
nomos_cognition: 为运行消费者提供认知与规划算法
```

作者声明集中在 [author_abilities/examples](nomos_c0/author_abilities/examples/)，
M1 现行资产在其中的 [everflame](nomos_c0/author_abilities/examples/everflame/README.md)。
见证在 [nomos_t0/examples/current](nomos_t0/examples/current/)。
新增或修改声明先读作者指南（研究仓路径：`docs/AUTHORING.md`）。

旧 `engine/kernel`、OwnerGraph/Ports、`nomos_examples` 与早期 K/T 链已
归档（研究仓路径：`archive/README.md`），不提供安装根、转发或备用执行链。
研究脚本留在 tools（研究仓路径：`tools/README.md`），测试支撑留在
tests/nomos_test_support（研究仓路径：`tests/nomos_test_support/README.md`），不作为生产包入口。
