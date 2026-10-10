# 表达式与谓词选型

作者条件进入受检 IR，不执行 Python。普通字段比较和算术直接写可读表达式；
集合问题先区分「有没有」「恰好一个」「实际数量」和「要取得哪些记录」。

## 普通表达式

```yaml
where: ballot.round == scene.round and ballot.target == candidate.id
```

名字必须属于已声明端口、参数或当前词法作用域。解析时检查类型、读权和阶段，
`let` 只复用纯值计算，不创建权威状态或扩大端口权限。

## 集合选择

| 意图 | 写法 | 执行特点 |
| --- | --- | --- |
| 至少有一个匹配 | `exists` | 找到首个匹配即可返回 |
| 没有匹配 | `none_matching` | 找到首个匹配即可返回 false |
| 恰好一个匹配 | `exactly_one` | 找到第二个匹配即可返回 false |
| 需要真实数量 | `count_matching` | 计算全部匹配数量，返回整数 |
| 键必须唯一 | `unique_by` | 检查重复键；不去重或授予个体身份 |
| 需要筛选、连接或输出记录 | `query` | 构造有限结果；不能用布尔谓词替代 |

例如拒绝同一轮重复投票：

```yaml
none_matching:
  collection: scene.ballots
  as: prior
  where: prior.round == scene.round and prior.voter == payload.actor
```

同样的 `collection/as/where` 结构可用于 `exists`、`exactly_one` 和 `count_matching`。
集合必须有受检的有限类型；行别名只在对应条件作用域中有效。
`exists` 不能把先行构造的 `query` 本身变成惰性查询，也不保证整局一定加速。

## 不应简化的区别

- 「没有反对票」不等于全票一致：空票表也没有反对票，须另检查支持票存在与投票完成。
- 多数票与胜负计算需要真实数量，不为了缩短 YAML 把整数规则改成布尔检查。
- 取得唯一记录与判断唯一记录不同；需要读取字段时用受检匹配/绑定，不能只返回 true。
- 共享字段结构不等于同一名义类型或写许可，谓词不绕过 owner 边界。

真实例子：[狼人杀 Lib](../src/nomos_c0/examples/three_seat_werewolf_v0.lib.yaml)的
`event.select_unanimous`、`event.select_majority` 和 `action.vote`。
实现：[集合编译与求值](../src/nomos_c0/composable_value_v1.py)；
测试：[量词执行](../tests/nomos_c0/test_quantifier_collection_execution_v1.py)、
[狼人杀样例](../tests/nomos_c0/test_werewolf_predicate_authoring_v1.py)。
