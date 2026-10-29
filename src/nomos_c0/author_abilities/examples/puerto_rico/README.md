# 波多黎各作者规则草案

当前完成 P1、共享分配 P2 和经济阶段 P3：真实角色选择、全体依序行动、
拓殖、建造、配员、生产、交易与轮末接入同一共享桌面。
船运、特殊建筑和完整计分按 P4/P5 接入。

## 先玩经济阶段

```bash
.venv/bin/python -m nomos_play --catalog src/nomos_c0/author_abilities/examples/puerto_rico/economy.games.yaml --port 8881
```

打开 `http://127.0.0.1:8881/`，选 A，然后按三人规则开局。
你只控制自己的选择，其他两席按独立策略行动；人员领取、配员等变化会自动播放。
市长阶段可在自己的玩家板点“安排人员”，在工位上调整人数、查看产能，再一次确认。
播放工具支持变速、暂停、快进和回看，观看不会再次执行行动。
选角色时，牌面直接展示能力、特权与积累金币；建造阶段直接点当前合法建筑，
查看实际费用和支付后金币，再确认建造。点击牌面还没有执行行动。
页面上方“规则与流程”包含本桌经济阶段的规则、轮转和收束说明，以及完整原版规则书链接。
摘要由作者在 [呈现资产](economy.presentation.yaml) 的 `rules` 中维护，源码注释不自动公开。

**要做什么：** 建立田地、生产设施和人员的配合，将商品卖成金币。
每轮每人选择一个角色，该角色使全体依序行动；只有选择者得到角色特权。

| 角色 | 你的选择及后果 |
| --- | --- |
| 拓殖者 | 增加一块田地；选择者可改取采石场，配置人员后减少建造费用 |
| 建筑师 | 支付费用建设施，新工位为空；选择者少付一金 |
| 市长 | 接收新人员，然后重配全部工位；选择者可多取一人 |
| 工匠 | 根据已配置田地和建筑领取商品；选择者在全体生产后可再取一桶 |
| 商人 | 卖一桶不同货种给交易所，选择者多得一金 |
| 勘探者 | 四／五人开局的独立角色牌，选择者领取一金 |

靛蓝等货种需要同货种田地和生产建筑都有人员，产量取两边较小值；玉米直接由田地生产。
建成设施后，等下次市长阶段才安排人员。若首次分配的人员只有一名，可以先占一个工位，
之后再补人形成生产链。付款、分配产能、生产数量与卖货收入会在确认前显示。
公共供给和各玩家选择共同影响实际结果，AI 配置可独立修改。

本片开放五种全体经济角色、按人数出现的勘探者和六种生产建筑。
经济收束按真实城市／人员供给触发并完成本轮；完整船运、特殊建筑及胜利点结果随下一片交付。
正常玩法有持续轮转，未设置最大行动次数或演示回合上限。

| 经济文件 | 职责 |
| --- | --- |
| [Source](economy.source.yaml) / [Assets](economy.assets.yaml) | 选择规则、限定本片范围、配置三人席位与开局 |
| [Player 与公共状态](economy_types.lib.yaml) | 独立个人板、私有胜利点数与共享阶段 |
| [经济查询](economy_queries.lib.yaml) | 合法工位、生产瓶颈、建造费用、交易资格与预览 |
| [角色能力](roles.lib.yaml) / [因果轮转](turns.lib.yaml) | 玩家真实选择和已有行动触发的 Event |
| [独立 AI](economy.ai.yaml) | 本人信息下的候选评分及完整配员值构造 |
| [呈现](economy.presentation.yaml) | 中文目的、公共玩家板、人员指示物、桌面配员与后果预览 |

## 基础目录与查询

| 文件 | 阅读内容 |
| --- | --- |
| [共享目录](catalog.source.yaml) / [只读 Source](world.source.yaml) | 23 种建筑、3/4/5 人开局表、50 种植园和八张角色牌；共享表头 |
| [棋具类型](component_types.lib.yaml) / [只读类型入口](types.lib.yaml) | 棋具值、数量分配、船仓；不同 Program 选择各自的 Player 定义 |
| [分配规则](allocation.lib.yaml) | 各工位只出现一次、数量不超容量、可安置人员优先安置、余量保留 |
| [船运规则](shipping.lib.yaml) | 从所持货种筛选合法船、推导装载数量；常规义务与可选私有码头分开 |
| [目录规则](catalog.lib.yaml) | 名单唯一性/供给完整性、按人数选择角色牌与许可读回 |
| [Lib 入口](world.lib.yaml) | 正常模块 imports |
| [目录核对与建筑后续账](CATALOG.md) | 版本、图示来源、特殊建筑的后续实现检查点 |

例如三块工位容量为 1、3、1，有 4 名人员，`1/2/1` 和 `0/3/1` 都合法。
同一条 `valid_allocation` 接收工位表和完整草稿，不需要为每一座建筑生成一条规则。
若有 7 人则安置 5 人、保留 2 人；容量变化后重新检查，而不沿用旧布局的合格结论。

船运也采用参数化查询：`legal_ships(ships, stock, kind)` 返回当前合法船集合。
所选货种只有 3 桶时，空的 4/5/7 格船都能装完，三艘均可选择；有 6 桶时只能选 7 格船。
已存在同货种的货船时，按该船剩余容量结算；玩家仍可选择另一种合法货种。

以下输入片段也通过现行 C0 的具名短门；角色机会与阶段效果在后续能力中接入：

```yaml
inputs:
  kind: {type: Good, choose: shippable_goods(ships, stock)}
  vessel: {type: Ship, choose: 'distinct(legal_ships(ships, stock, kind))'}
  loaded: {type: Count, derive: 'shipping_amount(stock, kind, vessel)'}
```

`distinct` 把有序船表转为有限候选集合；装货数量由当前输入推导，玩家不手填该数值。

## 查看编译结果

```bash
.venv/bin/python -m nomos_c0.author_abilities --pure src/nomos_c0/author_abilities/examples/puerto_rico/world.lib.yaml
.venv/bin/python -m nomos_c0.author_abilities src/nomos_c0/author_abilities/examples/puerto_rico/world --plan
.venv/bin/python -m pytest -q tests/nomos_c0/test_author_puerto_rico_draft_v1.py
```

`--pure` 检查并列出查询参数、返回类型与读取依赖；`--plan` 编译真实 Source 的四项目录投影。
`world` 前缀负责目录核对；具名测试使用只读初态验证目录装配。
测试中的小船仓/工位是查询反例，不是改编的完整游戏开局。

## 试玩数量分配

[工位能力](workers.lib.yaml)导入同一 `valid_allocation`，
[Source](workers.source.yaml)声明三块工位与四名人员；
[呈现](workers.presentation.yaml)映射数量字段及获准目标，
[独立 AI](workers.ai.yaml)直接构造完整布局。每席一次确认，另一席位也由真实 K0 发布。

```bash
.venv/bin/python -m nomos_play --catalog src/nomos_c0/author_abilities/examples/allocation.games.yaml --port 8879
```

选择“人员分配试验”与 A，安排 `1/3/0` 或 `0/3/1` 后确认。
每行显示容量，总额、已分配与保留实时变化。超额可继续编辑，合法后确认恢复。
此处是工位控件的独立短样本；正式市长阶段已接入上面的经济世界。
同一桌面也提供[中性预算样本](../allocation_budget/README.md)，其规则允许保留部分预算。

## 下一片

之后接船运、全部特殊建筑、正式计分与标准整局。
范围与计划（研究仓路径：`docs/design_notes/PUERTO_RICO_BASE_SCOPE_AND_GAP_AUDIT_V1.md`）
列出整局返回门；完整游戏接入标准共享目录随 P3–P5 推进。
