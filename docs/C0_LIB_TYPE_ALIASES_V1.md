# Lib 类型别名与可读规则

作者应当写「轮数」「参与者名字」等有含义的类型，不必在每个字段重复范围。
现行 Lib 可声明透明类型别名：

```yaml
type_aliases:
  ParticipantName: {str: [1, 64]}
  RoundNumber: {int: [1, 1000000]}
  Role: {enum: [wolf, seer, witch, villager]}
  OptionalParticipant: {optional: ParticipantName}
  BallotHistory: {tuple: {item: Vote, max: 128}}

records:
  - name: WitchNotice
    fields:
      - {name: round, type: RoundNumber}
      - {name: target, type: OptionalParticipant}
      - {name: selection, type: occurrence_ref}
      - {name: notice, type: occurrence_ref}
    invariant: null
```

这是类型片段，不是独立可运行的完整 Lib；`Vote`、owner 和其他声明仍须提供。

## 样例书写规范

具名声明是帮助理解领域含义的规范，不只是一项去重优化。
现行狼人杀样例的 record 字段只使用内建类型名、已声明 record 名或 `type_aliases` 名：

- 范围、枚举、可选类型和集合类型集中声明，即使只用一次也不在字段内展开定义。
- 按用途命名：`GamePhase`、`WinningSide`、`PlayerRoster`、`InspectionHistory`、`OptionalWitchNotice`。
  读字段时不必先解码一棵类型表达式才能知道含义。
- `bool`、`occurrence_ref` 等内建类型已有明确名字，直接引用；不为了凑数量再套一层别名。
- 类型别名与 record 可以相互引用已有的具名类型；文本顺序不是解析依赖，未知类型与递归仍拒绝。
- 这是一条现行样例规范，有测试防止重新引入内联字段定义；不把其他消费者的合法内联语法
  突然变成编译错误。纯函数签名仍遵守下述独立合同。

## 编译含义

- 别名只复用已有字段类型表达式。C0 在生成名义签名、类型指纹与字段校验前展开它们。
- `RoundNumber` 仍是有范围检查的整数；不会创建 `RoundNumber` 实体或新 K0 owner。
  `ParticipantName` 也不自动成为具有独立身份的标识类型。
- 别名可引用其他别名或已声明 record，可用于 record 字段和 variant payload，支持 `optional`、有限 `tuple` 的嵌套。
- 只改别名名称、不改展开类型，不改变 owner 类型指纹；修改被使用的边界会改变指纹与实际校验。
- 类型名重复、与内建或 record 名冲突、未知引用、循环、非法范围、冗余 optional 和无界 tuple 均拒绝。
  未使用的别名也必须合法。最多 64 个别名；展开后的类型仍遵守既有嵌套限制。
- 不引入隐式范围、子类型推断或默认值。`optional` 许可 `None`，与 Assets 字段缺省规则不是一回事。
- owner 的 `state` 仍须指向实际名义 record；纯函数参数的类型合同仍是现有独立签名语法，
  本片不把字段别名搬入参数后悄悄丢掉范围检查。

运行时只使用展开后的受检字段描述和既有校验器，不解析别名，也不新增 K0 类型指令。
实现：[别名展开](../src/nomos_c0/nominal_type_aliases_v1.py)、[Lib 检查](../src/nomos_c0/declarative_nominal_v0.py)。

## 狼人杀样例整理

[共享 Lib](../src/nomos_c0/examples/three_seat_werewolf_v0.lib.yaml)同时使用：

- 命名类型：所有领域字段类型集中声明，包括单次使用的阵营、阶段、名单与个人历史类型；
  内建 `bool` 和来源引用仍直接使用。
- 可读条件：`candidate.id == payload.target`，不手写 `eq/ref/const` 树。
- 布尔集合谓词：存在、无匹配、唯一匹配分别使用 `exists`、`none_matching`、`exactly_one`。
- 多数票：用 `let support` 只计算一次支持票，比较 `support * 2` 与有效人数／票数。
- 全票一致：确有支持票，并且没有本轮投给其他人的票；不能只写「没有反对票」而接受空票表。
- 真实计数：人数、完整投票、剩余阵营与胜负计算仍返回整数，不把数值规则全部改成布尔谓词。

纯定义内的角色匹配仍使用受检 `query`；输入先完整求值，不承诺外层 `exists` 能让整个 join 短路。
本批没有修改人数、职业、救人、胜负或来源边界；也没有证明整局加速。
谓词与结构化集合操作仍是同一现行语法，不为历史报告增加备用运行入口。

短测试：[别名与边界](../tests/nomos_c0/test_nominal_type_aliases_v1.py)、
[样例选型](../tests/nomos_c0/test_werewolf_predicate_authoring_v1.py)。
旧输入与采集：[历史输入](showcase/historical-inputs/README.md)；现行展示见[矩阵](SHOWCASE_MATRIX.md)。
