# 璀璨宝石基本规则

本目录把 Splendor 基本版写成高级作者规则：收集筹码、保留/购买发展牌、积累折扣、取得贵族，
达标后补齐最后一轮，依据分数和购牌数量判定胜者。官方共享桌面直接展示牌市、筹码、本人保留牌与结算。

## 文件

| 文件 | 内容 |
| --- | --- |
| types.lib.yaml | 筹码、发展牌、贵族、玩家与公共/私人字段 |
| resources.lib.yaml | 支付、折扣、供给、分数及牌堆查询 |
| world.lib.yaml | 开桌洗牌与玩家实际行动 |
| turns.lib.yaml | 补牌、回合末义务、等回合终局 |
| world.source.yaml | 人数/顺序、政策、规则选择及完整数值目录 |
| world.assets.yaml | 初态与受信随机种子 |
| world.ai.yaml | 独立电脑策略、付款/归还提议及纯评分辅助 |
| world.presentation.yaml | 牌卡、筹码、玩家表格、输入建议及预览 |

目录使用 `!table` 共享表头，一张牌一行；`cost.white` 等列展开为原 Gems 记录。
规则读取普通的类型化记录，不关心作者使用列表还是表格。

## 运行

在研究仓库安装后：

```bash
.venv/bin/python -m nomos_play src/nomos_c0/author_abilities/examples/splendor/world --port 8862
.venv/bin/python -m nomos_c0.author_abilities src/nomos_c0/author_abilities/examples/splendor/world --plan
.venv/bin/python -m nomos_c0.author_abilities src/nomos_c0/author_abilities/examples/splendor/world --manual
.venv/bin/python tools/run_tabletop_match.py src/nomos_c0/author_abilities/examples/splendor/world --progress
```

CLI 是受信作者调试入口，输入 `seat a` / `seat b` 换席、`auto` 提交该席的一次策略提案。
共享桌面用颜色与形状辨识六种筹码，点击公开牌上的当前操作，或从侧栏选择取筹码。
付款窗显示永久折扣、折扣后费用和库存，默认填入一份作者声明的合法付款建议，可以自行调整。
超额筹码和贵族选择在本人真实后续机会处理；终局弹窗显示胜者和排名。
headless 命令只驱动已有规则与独立策略，不按游戏名分支、不在宿主写入胜负。
`--budget` 是单次驱动的工程预算；耗尽报告 budget，不算游戏失败。

Source 默认两人，明确首席 a。扩到三/四人需修改 actors、order 并补对应 Assets 玩家初态；
供给数量和贵族数量由同一规则按人数计算。改变 seed 会改变真实洗牌，准备和查看不消耗随机流。
`target_score`、`token_limit` 与 `reserve_limit` 是作者政策参数，默认 15/10/3。

发展牌库存提供永久折扣，不是消耗品。黄金允许替代任何费用色，即使仍有该色筹码；
AI 的 canonical_payment 只是一种合法付款提议，人工 typed 输入可以选其他组合。
牌堆顺序和他人保留牌不进入公开 Context；牌堆剩余数量和保留数量有单独受检投影。
全部玩家都能看到各席筹码、已购牌、贵族、回合数和最终排名。

## 依据与数据

- 规则：[SPACE Cowboys 2024 基本版](https://cdn.svc.asmodee.net/production-spacecowboys/uploads/2025/10/SCSPL01EN_SPLENDOR_RULES_LIGHT.pdf)。
- 90 张牌的费用/奖励/分数：实物照片转录项目 [anicolao/splendor 固定提交](https://github.com/anicolao/splendor/tree/5b3efd26f2e460b1bef3839a058270b536a13648)，
  `data/verified_card_properties.csv`。本目录按该表为发展牌重新分配 1–90 的数据键，不复制图片/实现代码。
- 贵族以匿名数据键表示 10 组基本条件，不复制人物名或肖像；对照 [数值目录](https://github.com/boardgamers/splendor/blob/main/packages/engine/src/data.ts)。
  该项目的发展牌表与实物转录表存在差异，不能作为全表相等的证据；本片统一采用照片转录表。

数据转录仍应在公开发行前核对实物版本与授权；本轮不发布到发行仓库或公开游戏平台。
规则与数据采用独立声明，后续核查某张牌只需调整目录，不修改执行程序。

详细接受范围与通用能力见设计记录（研究仓路径：`docs/design_notes/TABLETOP_POLICY_AND_SPLENDOR_BASE_V1.md`）。
