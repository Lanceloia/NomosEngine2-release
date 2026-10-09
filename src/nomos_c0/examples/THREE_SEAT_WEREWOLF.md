# 三席测试世界作者文件

这四份 YAML 是一份世界定义和一份开局，不是四份剧情。C0 编译规则后，
通用终端启动同一个 K0 Session；席位选择在运行时形成 Action/Event 记录。

| 文件 | 作者修改的内容 |
| --- | --- |
| [`lib.yaml`](three_seat_werewolf_v0.lib.yaml) | 名义记录、owner 与席位可读字段。 |
| [`ports.yaml`](three_seat_werewolf_v0.ports.yaml) | 每类 Action 一份受信端口模板及 Event 端口。 |
| [`source.yaml`](three_seat_werewolf_v0.source.yaml) | 封闭 Actor 域、LawDef、能力家族、开局约束与候选条件。 |
| [`assets.yaml`](three_seat_werewolf_v0.assets.yaml) | A/B/C 的身份、职业和开局状态。 |

Source 用一份 `opening_actor_guards` 校验域内每名 Actor 的开局身份与职业；
夜间三个 Action 家族共用一份 `resolve_night` Event Law 绑定。三席样例仍由
Lib 显式声明三个 owner 和最多三个玩家；扩为六人局不能只改 Source。

从仓库根目录运行：

```bash
PYTHONPATH=src:engine/kernel/src .venv/bin/python -m nomos_c0.owner_graph_play_v1 three_seat_werewolf_v0
```

数字选择当前席位的选项；该席位完成本轮行动后，用 `seat B` 或 `seat C`
切到另一席位。也可用 `--lib`、`--ports`、`--source`、`--assets` 指向四份
显式文件。改动 `source.yaml` 中 `event.resolve_day` 的领先票数条件，
会改变真实 Event 结算；改动 `assets.yaml` 中的职业还须通过开局一致性检查。

`source.yaml` 的 `participants` 域明确列出 `a/b/c`。例如一条 `attack` 家族声明
引用这个域、一份 `attack` 端口模板和 `action.attack` LawDef；C0 由此生成
`attack_a/b/c` 三个独立 K0 Action。席位读回与条件选项也从一份 `seat_family`
为 A/B/C 分别展开；作者没有逐席位复制选项，也没有预列目标 A/B/C 的菜单文案。
投票、查验、袭击的目标由运行时从当前玩家集合生成。只有当前职业为狼的 Actor 能通过袭击 Law。
新增同类型 owner 不会自动得到能力，必须修改域；逐席候选与读边界目前仍显式声明。

YAML 当前只是更可读的结构化作者前端，不是独立 `.nomos` 语言；`source`
中的逐席候选仍需要后续语法抽象。没有生成专属
`.py` 文件，也没有自动心智选择或 T0 运行迹验证。
