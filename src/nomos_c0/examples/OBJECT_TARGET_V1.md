# 动态 Object 目标示例

这个作者小世界由四份纯数据工件构成：

| 工件 | 作者声明 |
| --- | --- |
| [`lib.yaml`](object_target_v1.lib.yaml) | `Tool` 状态、`fine_tool` 对 `tool` 的显式 sort 专门化、各自独立 owner 类别、Actor 与 Action payload 类型 |
| [`ports.yaml`](object_target_v1.ports.yaml) | `inspect` 的形式目标 `target: Tool`、可读字段和 `ready` 写入端口 |
| [`source.yaml`](object_target_v1.source.yaml) | 将检查目标绑定到 `tool` 基类，形成动作选 `fine_tool`；定义一份 `inspect` Law 和有限候选条件 |
| [`assets.yaml`](object_target_v1.assets.yaml) | 开局 Actor、可见旧工具和不可见工具 |

从仓库根目录运行：

```bash
.venv/bin/python -m nomos_c0.owner_graph_play_v1 object_target_v1
```

依次选 `2`（检查开局 `tool`）、`1`（制造 `fine_tool`）、`1`（检查新工具）。
两次检查使用同一条 `action.inspect` 和同一个 K0 Action source；Source 的目标仍只写
`tool`，编译器依据 Lib 的受检专门化关系把 `fine_tool` 纳入有限允许集合。
目标个体引用由候选携带，K0 在 Action 结算时解析各自独立 owner 并重读当前状态。
不可见工具没有候选。`for_each_object.read` 明确列出该席位候选可读取的目标字段，并须覆盖
所选 Action 的全部目标读取端口。`visible_when` 是本例作者显式选择的当下可见条件，不是形成 Object
自动授予知识、持有或可及的通用规则。对这种候选 Action，`visible_when` 与 `when` 的合取
必须和 Law 的准入 guard 对齐；改变 guard 时也要同步改变候选条件，否则 C0 拒绝编译。
单独修改 `action.inspect` 的 `ready` 输出则会改变真实 K0 写入，不需要改 Python。

本例只覆盖不同 sort 共享同一名义状态记录的显式专门化；不支持子类新增字段的泛型
视图，也不证明跨局恢复、持久知识、物品转移或任意新类型的运行时定义。
