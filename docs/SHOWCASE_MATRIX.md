# 实验与证据地图

这组实验服务于规则驱动自由探索世界的创作目标，统一定位见[项目北极星](NOMOS_PRODUCT_PROPOSITION.md)。

一个拒绝请求不能说明整个引擎。本项目分别检验作者能否编辑人物、
更换规则，以及让位置、资源和局部信息共同影响运行结果。

## 可复现实验

| 实验 | 修改 | 实际结果 | 不能据此推断 |
| --- | --- | --- | --- |
| [禁止自救](SHOWCASE.md) | 救人 Law 增加一个条件 | 相同前九步后，第十步从发布变为拒绝 | 菜单自动变化、任意规则均正确 |
| [全票与多数票](showcase/wolf-vote/README.md) | 选择另一条目标结算 Law | 十次行动都发布；清晨从无人死亡变为 F 死亡 | 游戏公平、任意新 Law 或运行时热更新 |
| [换女巫](showcase/world-edits/README.md) | B/E 的职业与药水开局 | 通知、选项和真实来源移到 E | 一项字段就能完成职业编辑、多人认证 |
| [六人扩八人](showcase/world-edits/README.md) | 实例名单及合法 opening | G/H 有独立视图，G 实际投票 | 任意规模、完整八人局已试玩 |

这四项比较使用同一个 C0/K0，而不是四份各自补写结局的宿主程序。
每项中文说明链接到实际输入、逐步报告和采集摘要；报告保留其原始版本。
历史报告与当前运行的关系见[证据目录](showcase/README.md)。

## 冰宫：规则组合

[M1 装配清单](../src/nomos_examples/everflame/world.bundle.yaml)组合：
[局部观察](../src/nomos_examples/everflame/source/rules/local_observation.yaml)、
[解冻](../src/nomos_examples/everflame/source/rules/thaw.yaml)、
[寒冷](../src/nomos_examples/everflame/source/rules/cold.yaml)和
[有限 NPC 策略](../src/nomos_examples/everflame/source/control/policies.yaml)。

这里可见观察、人物位置、永焰充能、保护与行动选择的关系。
「解冻」「邀请」「实际到达安全区」是不同事实，不能用一个营救图标替代它们。
本人读回是有限信息；作者审计中的私态不属于玩家视图。

已有一条 43 项玩家行动、1180 条发生的整局核对记录；摘要见[验证说明](VERIFICATION.md)。
完整报告没有随发行仓库分发，因此这里不把摘要当作可直接下载的原始证据。
这条路线也不独立证明每项机制的因果贡献；M1 局部对照与更易读的过程展示仍需补充。

## 已知缺口与未来

- 菜单与准入分别声明。公开规则怎样复用到选项生成仍需设计，不能把含隐私的全部 guard 暴露给玩家。
- 职业与人数修改仍要同步部分开局字段；目前没有图形化资产编辑器或一键转换器。
- NPC 使用有限 Appraisal 对有限选项评分，不是通用自主规划、心智求解或 LLM DM。
- 未来希望让作者通过规则与库创造更多沙盒世界，TRPG 是验证场景之一；模型提议行动和讲述已发生的故事属于未来管线。

支持范围见[语义](SEMANTICS.md)，第一次阅读建议从[项目导览](PROJECT_TOUR.md)进入。
