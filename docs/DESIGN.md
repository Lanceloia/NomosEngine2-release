# 设计取舍

目标是让作者定义世界规律，让玩家或 Agent 的实际选择产生历史。
项目的创作动机、北极星与当前成果见[项目定位](NOMOS_PRODUCT_PROPOSITION.md)。
为了避免世界模型变成另一套剧情脚本，编译、控制与结算分别承担责任。

## 规则程序不包含开局

C0 检查 Lib、Ports 与 Source，生成规则 Program；Start 才接受 Assets。
同一个 Program 可以启动多个独立 Session。编译、绑定与开局错误各在所属阶段拒绝，
不让 Run 靠重新读取文件或宿主补数据来修复缺失声明。

实现：[Program 组合](../src/nomos_c0/owner_graph_v1.py)、
[开局](../src/nomos_c0/program_start_v1.py)；
反例：[阶段测试](../tests/nomos_c0/test_program_phases_v1.py)。

## 相同类型不代表相同权威

owner 是权威状态边界。例如 actor 和 peer 可以有同一种状态记录，
但许可写 `actor.ready` 不等于许可写 `peer.ready`。
端口的精确 `root.field` 路径进入检查、IR 和 Bind；不能由效果反推权限。
纯值构造记录，也不等于获得替换 owner 状态的许可。

类似地，许可改 `scene.items[].value` 不自动许可替换整个 `scene.items`。
只读投影没有 owner 写权限；字段名称、共同类型或共享规则不能洗掉这条边界。

实现：[规则端口](../src/nomos_c0/composable_value_v1.py)、
[绑定](../src/nomos_c0/program_binding_v1.py)；
反例：[精确写权](../tests/nomos_c0/test_owner_write_authority_v1.py)。

## 世界真相与玩家知识分开

世界 Law 可以读它显式获准的权威状态，席位只能读自己的授权投影。
生成菜单、查看预测或换席不会自动增加人物知识。观察、交付和阅读是不同的实际发生。
作者审计可以用于验证，但不能拿来替玩家决定或填充玩家界面。

候选不是当前态准入的证明：情况可能改变，或限制不属于本人已知信息。
K0 在提交时仍检查身份、权限和当前状态。现在公开菜单条件与 Law guard 分开声明，
二者自动联动仍是缺口，不能把隐私 guard 直接复制到菜单。

实现：[席位绑定](../src/nomos_c0/private_actor_binding_v1.py)；
反例：[候选隔离](../tests/nomos_c0/test_dynamic_offer_fault_isolation_v1.py)。

## 一次行动作为原子事务

K0 在隔离候选状态上准入、计算效果及因果/due 闭包，再一起发布状态和来源。
guard 为假是零写、可继续的拒绝；准入后的结算缺陷回滚整次事务并进入 fatal。
开局验证回调也只能拿到隔离临时值，不能持有或改写权威状态。

这意味着一封札实际到达、一项知识取得或一个新物件形成，应有真实记录支撑。
来源 ref 描述发生，实体 ref 描述个体；不能互相充当。
一个 Event 可以按许可更新多个 owner，其形成来源不规定贡献 owner 的数量。

实现：[K0 事务](../engine/kernel/src/nomos_kernel/_atomic_inmemory_session.py)；
反例：[开局隔离](../engine/kernel/tests/test_opening_validation_isolation.py)、
[pre-due 原子边界](../engine/kernel/tests/test_pre_due_transaction_boundary.py)、
[形成与效果](../tests/nomos_c0/test_formation_effect_cardinality_v1.py)。

## 工具不再模拟一遍世界

T0 在同一 Program 和 Session 中实际执行有限行动见证，检查其前缀和目标。
失败只描述本见证在该规则与开局下的结果，不证明所有选择都不可达。
控制额度停点保留实际前缀，也不是世界结算 fatal。

实现：[T0](../src/nomos_t0/witness_v0.py)；
反例：[有限见证](../tests/nomos_t0/test_witness_v0.py)、
[控制预算](../tests/nomos_c0/test_control_budget_v1.py)。

## 优化执行，不改变合同

生成器可以预绑定封存的布局、短路条件和字段读取路径，但不能缓存当前值或准入成功。
输出顺序、首错和运行中不变量仍需保留。详见[执行后端](EXECUTION_BACKEND.md)。
这些工程边界不是恶意 Python 插件沙箱，也不承诺通用恢复或完整本体论。
