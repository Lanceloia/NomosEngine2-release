# K0：受检结算内核

K0 接收 C0 绑定后的有限类型化端点，不解析 YAML，不含游戏领域规则。
当前是 private Python runtime，不是完整公开 API、存档服务或恶意插件沙箱。

```text
Action 尝试 → 当前态准入 → 隔离候选事务
                         → 效果与发布产品
                         → 因果/due 闭包与不变量
                         → 原子发布状态、身份、来源和历史
```

guard false 为零写、可继续拒绝；准入后缺陷整体回滚并 fatal。
正常终局在根闭包结束封闭，未执行后缀不分配身份或来源。
owner 是权威状态边界，不要求每个实体只能有一个读视图。

| 入口 | 责任 |
| --- | --- |
| [_atomic_inmemory_session](src/nomos_kernel/_atomic_inmemory_session.py) | 准入、候选事务、调度与发布 |
| [_owner_state_runtime](src/nomos_kernel/_owner_state_runtime.py) | 类型化隔离、复制与 opening 校验 |
| [_candidate_owner_state_runtime](src/nomos_kernel/_candidate_owner_state_runtime.py) | 候选 owner 状态操作 |
| [_dynamic_owner_abi](src/nomos_kernel/_dynamic_owner_abi.py)、[_dynamic_actor_abi](src/nomos_kernel/_dynamic_actor_abi.py) | 实例、形成和访问端口 |
| [_causal_law_abi](src/nomos_kernel/_causal_law_abi.py)、[_rule_products_abi](src/nomos_kernel/_rule_products_abi.py) | 规则端点、贡献与来源产品 |
| [_temporal_runtime](src/nomos_kernel/_temporal_runtime.py) | 有限时间/due 机制 |
| [_collective_abi](src/nomos_kernel/_collective_abi.py) | 有来源的成员入集 |

具体限制见[发行语义](../../docs/SEMANTICS.md)。原生端点没有检查豁免。
本轮修复见[事务记录](../../docs/KERNEL_TRANSACTION_REPAIR.md)，
短门与长测边界见[测试指南](../../docs/TESTING.md)。
