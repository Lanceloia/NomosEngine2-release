# 三席测试世界作者文件

这四份 YAML 是一份世界定义和一份开局，不是四份剧情。C0 编译规则后，
通用终端启动同一个 K0 Session；席位选择在运行时形成 Action/Event 记录。

| 文件 | 作者修改的内容 |
| --- | --- |
| [`lib.yaml`](three_seat_werewolf_v0.lib.yaml) | 命名字段类型、名义记录、owner、共享 Law 与纯定义。 |
| [`ports.yaml`](three_seat_werewolf_v0.ports.yaml) | 每类 Action 一份受信端口模板及 Event 端口。 |
| [`source.yaml`](three_seat_werewolf_v0.source.yaml) | 封闭 Actor 域、共享 Law 绑定、能力家族、开局约束与候选条件。 |
| [`assets.yaml`](three_seat_werewolf_v0.assets.yaml) | A/B/C 的身份、职业和开局状态。 |

Source 用一份 `opening_actor_guards` 校验域内每名 Actor 的开局身份与职业；
夜间三个 Action 家族共用一份 `resolve_night` Event Law 绑定。三席样例仍由
Lib 使用参与者 owner 模板；Source 选择实例，Assets 提供一致的玩家与职业开局。
扩人数需要同时修改实例名单与开局，而不是为每人另写一份 Lib。

从仓库根目录运行：

```bash
.venv/bin/python -m nomos_c0.owner_graph_play_v1 three_seat_werewolf_v0
```

数字选择当前席位的选项；该席位完成本轮行动后，用 `seat B` 或 `seat C`
切到另一席位。也可用 `--lib`、`--ports`、`--source`、`--assets` 指向四份
显式文件。改动共享 Lib 中 `event.resolve_day` 的领先票数条件，
会改变真实 Event 结算；改动 `assets.yaml` 中的职业还须通过开局一致性检查。

`source.yaml` 的 `participants` 域明确列出 `a/b/c`。例如一条 `attack` 家族声明
引用这个域、一份 `attack` 端口模板和 `action.attack` LawDef；C0 由此生成
`attack_a/b/c` 三个独立 K0 Action。席位读回与条件选项也从一份 `seat_family`
为 A/B/C 分别展开；作者没有逐席位复制选项，也没有预列目标 A/B/C 的菜单文案。
投票、查验、袭击的目标由运行时从当前玩家集合生成。只有当前职业为狼的 Actor 能通过袭击 Law。
新增同类型 owner 不会自动得到能力，必须修改域；逐席候选与读边界目前仍显式声明。

YAML 是受检作者前端，不是可执行 Python。没有生成专属 `.py` 世界。
当前另有六席实例化 Source，以及真实 T0 见证入口；
见[当前规则编辑指南](../../../docs/AUTHORING.md)。
三席静态样例与六席实例化声明不是同一份 Source，不凭文件名推导人数上限。

领域字段类型提前在 `type_aliases` 中声明，包括单次使用的类型；字段仅引用名字。
`fields` 统一用一行 `TypeName field_name` 声明，例如 `RoundNumber round`。
内建类型直接使用已有类型名；普通条件用可读表达式，集合布尔检查
用语义谓词，多数票支持票用 `let` 局部复用。具体选型见
[类型与规则写法](../../../docs/C0_LIB_TYPE_ALIASES_V1.md)和
[谓词指南](../../../docs/AUTHORING_PREDICATES.md)。
