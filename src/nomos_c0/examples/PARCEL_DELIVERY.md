# C0 货件派送样本（non-canon）

此样本只验证作者构建链，不属于 GV 或 FG 剧情。文件分工：

- `parcel_delivery_v0.lib.json`：声明名义记录、字段约束和 replace-one Owner；C0 检查后生成 K0 载体与私有 owner codec。
- `parcel_delivery_v0.ports.json`：声明 Action、直接 Event、到期 Event 的模板端口、可读写字段和输出类型；C0 检查后生成受信端口。
- `parcel_delivery_v0.py`：选择资产路径并呈现 GameForm 的薄终端；不手写 Owner 或 Action/Event/due 端口。
- `parcel_delivery_v0.source.json`：作者 LawDef、Action/Event 绑定、有限候选、席位读回、GameForm 和时间策略。
- `parcel_delivery_v0.a.assets.json`、`parcel_delivery_v0.b.assets.json`：同一世界的两份开局资产，路线耗时分别为 2 和 4 tick。

从仓库根目录运行：

```bash
PYTHONPATH=src:engine/kernel/src .venv/bin/python -m nomos_c0.examples.parcel_delivery_v0
PYTHONPATH=src:engine/kernel/src .venv/bin/python -m nomos_c0.examples.parcel_delivery_v0 --assets src/nomos_c0/examples/parcel_delivery_v0.b.assets.json
```

`--lib PATH`、`--ports PATH`、`--source PATH` 可分别装入同合同的编辑版名义 Lib、端口 Lib 和 Source。端口 Lib 声明能力形状和 Scene Owner 符号；每个能力实例的 source/event/causal identity 只在 Source 声明。终端只需输入当前菜单的数字：默认开局依次选 `1` 派货、`1` 结束派货员机会、`1` 结束收货员机会；时间自动推进到到货停点，再选 `1` 签收。此后也可继续选 `1` 结束两个席位直至终局。切换席位与退出同样是当时菜单中的编号，不必记忆文字命令。放弃/结束席位只写 GameForm 控制记录，不是世界 Action。

收货岗只能从自身席位读到离库通知；实际到货由到期 Event 结算，随后才可执行签收 Action。终端不读取 K0 私有 Scene 审计或代替世界规则。

例如把 Source 中 `event.arrive` 的 `parcel.copy.changes.status` 从 `arrived` 改为 Lib 已声明的 `held`，重新运行后货件仍按路线到期，但收货岗不会得到签收选项。这是作者 Law 改变世界后果，不是终端按文件名切换路线。

只改名义 Lib 的 `Route.travel` 下限会改变 Start 对同一 Assets 的接受结果；删去端口 Lib 中 Law 所需的读/写字段会在 Compile 拒绝，不回退到 Python 定义。这证明本样本的模板端口确实来自声明文件。不过模板端口目前只支持已有的 Action、直接 Event、到期 Event 形式及 replace-one Owner；Source 身份绑定仍由现行 `owner_graph.v6` 解释。它不是独立发行的游戏，也不证明任意题材 Lib、完整 L1、GV Source 化或生成独立 `.py`。当前 playable 是同一进程中的 `CheckLib -> Compile -> Start -> Form read/submit -> K0`。
