# C0：作者规则编译器

C0 把有限声明式世界编成 K0 可以准入、原子结算并记录来源的 Action/Event。
它不把剧情 capsule 编成固定行动顺序，不执行作者 Python 回调。
现行作者格式是 `c0.owner_graph.v6`，文件可用 YAML 或 JSON；没有旧 schema 回退。

## 四份输入

| 文件 | 声明什么 |
| --- | --- |
| Lib | 名义记录、owner/kind、有限基础类型、LawDef、纯定义与受信端口 |
| Ports | 选定端点、参数、字段读写许可及结果签名 |
| Source | 能力与 Law 绑定、形成边、席位、可见性、有限候选与 GameForm |
| Assets | 某局人物、物件、位置、资源、种子和时间开局数据 |

Source 声明“可以发生什么”。独立 trace 声明“作者想验证什么”，交给
[T0](../nomos_t0/README.md)，不混进 Source 控制剧情。

## 编译与运行

```text
read_author_document -> frozen author documents
check_nominal_lib / check_graph_ports / check_owner_graph
    -> C0ProgramIR + generated layout
bind_program -> executable rule Program, without Assets
Program.start(Assets) -> checked opening -> one K0 Session
read / offers / submit / continue_form -> actual K0 settlement
```

| 阶段 | 入口 | 边界 |
| --- | --- | --- |
| 文件与来源 | [author_document_v1](author_document_v1.py) | 冻结文件字节/位置；JSON/YAML 共用声明合同 |
| 声明 | [graph_contracts_v1](graph_contracts_v1.py)、[declarative_nominal_v0](declarative_nominal_v0.py) | 封闭名义类型、选定 owner/端口与生成布局 |
| 前端 | [graph_frontend_v1](graph_frontend_v1.py) | 检查 Source；产无 Assets/carrier/实际地址的 Program IR |
| 后端 | [program_binding_v1](program_binding_v1.py) | IR 与布局机械绑定；不再解析 Source |
| Start | [program_start_v1](program_start_v1.py) | 开局先检查并冻结，再一次原子建局 |
| Run | [program_runtime_v1](program_runtime_v1.py) | 当前状态下的本地读回、候选、控制和 K0 重核 |
| 组合入口 | [owner_graph_v1](owner_graph_v1.py) | 只组合编译阶段，不重导出旧 runtime 符号 |

生成布局是必需输入，没有 native/`None` 备用后端。
Run 不重新编译或读取作者文件；世界读权不自动授予席位公开读取。
静态拒绝、Start 拒绝、K0 有限拒绝和准入后的 fatal 缺陷分开报告。

运行合同是：作者编辑 Lib/Ports/Source 后重新 Compile；
已发布 Program 不支持原地热改规则或类型。debug/release 共享此合同，
当前世界状态、身份、权限、费用和准入仍逐次受检。
表达式/纯定义/端口捕获拥有自己的只读容器；生成记录及贡献类型完成组装后，
字段、注解、描述符和校验回调均拒绝公开改写。完整 Program 只由 checked Bind 发布，
不支持手工构造或 `dataclasses.replace` 进行局部重接线。
专用不变量执行器不再逐节点扫描热更新条件；生成类型不再逐读扫描固定 Field 元数据。
native 记录和回调仍走原检查。受检声明生成图可在一次 owner 复制/隔离/视图装配中，
复用同一实际不可变值的完整验证；新副本、其他 owner、独立操作及失败仍重新验证。
这不是全 Session 成功缓存，也不替代 closed、身份、许可、准入或回滚。
见[操作内验证合同](../../docs/design_notes/C0_OPERATION_LOCAL_VALIDATION_REUSE_V1.md)。
这不是针对恶意同进程 Python 的沙箱，也没有两套 debug/release 世界语义。
见[合同](../../docs/design_notes/C0_READ_ONLY_PROGRAM_HARD_CUT_V1.md)与
[实现/短路线证据](../../docs/closure_notes/C0_READ_ONLY_PROGRAM_IMPLEMENTATION_V1.md)。

### 多文件 Source

Source 可按规则、接线、席位与控制拆成片段；片段仍使用上表的同一套语法，
不产生独立 Scene 或 Session。清单显式选择文件，装配后只编译一个 Program。

```bash
python -m nomos_c0.owner_graph_play_v1 \
  --bundle src/nomos_c0/examples/modular_counter_v1/world.bundle.yaml
```

输入 `1` 调用共享计数 Law；输入 `seat seat_1` 换席，再输入 `1`，最后 `quit`。
两席分别把步长 1/2 传给同一 Law，不包含预定剧情。
文件入口见[清单](examples/modular_counter_v1/world.bundle.yaml)、
[共享规则](examples/modular_counter_v1/source/rules.yaml)、
[行动与席位](examples/modular_counter_v1/source/abilities.yaml)。

`read_source_bundle(Path(...))` 一次读取并冻结清单、Lib、Ports、Assets 和 Source 片段；
`compile_source_bundle(bundle)` 仍走唯一前端/后端链，
`program.start(bundle.assets.to_data())` 才绑定开局。
声明列表保留清单及文件内顺序；重名拒绝，不覆盖、不深合并，GameForm 等整体声明只有一处。
错误的已记录来源保留原文件、原路径、行列与摘要；Run 不再读取文件。
完整合同及限制见[装配记录](../../docs/closure_notes/C0_SOURCE_BUNDLE_V1.md)。
当前仅完成通用入口和短样例，尚未把大型 M1 Source 迁移为多文件。

Source 的因果 `events` 只选择模板、Law、触发关系、接收者及效果/产物绑定；
不再填写 `form` 或 `when_false`。C0 按所选 Scene/Actor 模板生成内部形成约定，
false guard 不形成因果 Event。旧字段即使值正确也在 Compile 拒绝，没有兼容回退。
Ports 的端点分类、Action 的 Object `form`、due 的声明与失败边界不是这些旧字段，
仍按各自合同受检。分层、保留项与后续迁移见[作者合同清点](../../docs/C0_DECLARATIVE_AUTHOR_CONTRACT_AUDIT_V1.md)。

Action/Event 可用[有限查询](../../docs/C0_FINITE_PARTICIPANT_QUERY_V1.md)声明两个
记录集合（或集合与所选参与者组）的按键匹配/筛选；C0 检查名义类型与读权并生成查询计划。
这不是完整 SQL，查询不授予世界观察或写权限。
查询结果可交给[按键更新](../../docs/C0_KEYED_RECORD_UPDATE_V1.md)，只声明匹配记录
中要改的字段；类型、构造/字段权限与当前子集受检，实际 owner 写入仍由原输出与 K0 结算。
新增记录可用[按键插入](../../docs/C0_KEYED_RECORD_INSERT_V1.md)：从所选参与者生成
候选，声明唯一键，保留旧行并追加缺失行；不需要作者手写累积器。

Assets 的名义记录中，Lib 声明为 `optional` 的字段可以省略；Start 按类型递归补成
`null`，包括嵌套记录、列表元素及分支类型的公共字段/所选负载。必填字段、未知字段
和类型错误仍拒绝，不推断 `0`、`false` 或空集合。Assets 是开局快照，不是状态补丁；
运行时记录构造、Event 输出与 owner 写入不采用这条缺省规则。
[合同与短测试](../../docs/C0_ASSETS_OPTIONAL_DEFAULTS.md)。

### 受检开局构造

`Ports.opening_constructions` 明列 Object kind 的字面输入字段、派生字段及名义构造器。
Source 选择有限规则，Assets 只给 `opening_seeds` 和其余字面开局信息。例如：

```yaml
# Ports
opening_constructions:
  - symbol: prepare_tool
    kind: tool
    read: [sides]
    fields: [ready]
    construct: []
# Source
opening_constructions:
  - kind: tool
    using: prepare_tool
    seed: opening_tools
    bindings:
      - {name: choice, draw: {ref: sides}}
    outputs:
      ready: {eq: [{ref: choice}, {const: 1}]}
# Assets
opening_seeds: {opening_tools: 42}
opening_objects:
  - {kind: tool, state: {label: A, visible: true, sides: 4}}
```

这里假定 Lib 的 Tool 已声明示例字段；派生字段不得同时出现在 Assets。
bindings 依声明顺序使用 `value` 或 `draw`，draw 是受检整数 sides 表达式，
使用专用 `seed` 并自动推进。普通表达式不得藏骰子，effect 纯定义仍不可调用。
`seed`、`occurrence` 和下划线开头名字是保留名。读域只有本人槽位的明列字面字段；
不接受 occurrence/Actor/Object ref、live owner、时间或 due。

每 kind 只选择一项规则。执行按 Source 规则顺序及 Assets 同 kind 的槽位顺序，
不按 label 定位、不增减实例、不暗改其他字段。Compile 产出不可变 symbolic IR，
Start 在唯一 K0 create 前检查完整类型、不变量和容量；任何失败均无 Session 出口。
无构造选择仍只走原字面 Start，没有备用后端。

`session.author_opening_construction()` 只供受信作者审计，返回不可变输入/Source/规则/
名义签名/算法/seed 链与稳定 opening 槽位，并对应本局实际 ref/owner。
重读和菜单不执行构造；receipt 不是 K0 occurrence、formed_by、玩家知识或恢复凭证，
不接收 caller 提供的 receipt。不同 Start 的数据可重放，局内 ref 不承诺相同。
[实现与短门](../../docs/C0_OPENING_CONSTRUCTION_V1.md)。

## 类型 IR 与绑定检查

当前 C0 自持必要语义和后端检查，不安装或重导出旧 ontology/lowering 包。

| 入口 | 职责 |
| --- | --- |
| [nominal_types_v1](nominal_types_v1.py) | 版本化名义类型标识、Object/Event sort 引用、显式无环 Object 子类型层级；无 K0 依赖 |
| [event_formation_ir_v2](event_formation_ir_v2.py) | Source 可选的 causal/due Event 形成声明；只含 Event sort 表和形成边，不分配个体 |
| [object_owner_binding_v1](object_owner_binding_v1.py) | Object sort 到所选 owner family/状态/容量的精确覆盖，核对实际 K0 factory |
| [event_formation_binding_v2](event_formation_binding_v2.py) | 形成边到选定 source/type/owner/predecessor/law 的端口绑定 |
| [event_formation_v2](event_formation_v2.py) | 作者声明检查、最终 profile 核对与实际 K0 发生来源投影 |

Object 检查真实用于 M1 的物件；Event 形成声明由 parcel 样例选择，当前 M1 没有选择。
旧十类 `DeclarationTables`、完整 `FoundationalProgram`、Quality/Quantity 和命名空间原型
已归档，不是隐含前置，也没有旧导出兼容。`Source.ontology` 的现行形成声明格式仍是
`c0.event_formation.v2`，只接受这一版；移除 Python 包不改变该作者合同。
当前类型引用不提供完整 UFO 本体分类、跨局身份或通用生命周期执行。

名义声明也支持封闭分支类型：`variants: {case: PayloadType, ...}`。
使用 `variant` 选一项构造，`match` 必须穷尽，`is_case` 只在 true 路径提供分支证明；
这些关系进入签名与 Bind 检查，不靠每个世界重复 XOR 不变量。
匹配别名不扩大端口读权，类型也不认证证据真实。
[语法、IR/codec 与 M3 校准](../../docs/C0_VARIANT_TYPES_AND_MATCH.md)。

## 可运行样本

```bash
.venv/bin/python -m nomos_c0.owner_graph_play_v1 three_seat_werewolf_v0
```

完整四文件入口：

```bash
.venv/bin/python -m nomos_c0.owner_graph_play_v1 \
  --lib src/nomos_c0/examples/three_seat_werewolf_v0.lib.yaml \
  --ports src/nomos_c0/examples/three_seat_werewolf_v0.ports.yaml \
  --source src/nomos_c0/examples/six_seat_werewolf_v0.source.yaml \
  --assets src/nomos_c0/examples/six_seat_werewolf_v0.assets.yaml
```

输入当前编号、`seat B`、`view` 或 `quit`。席位切换是受信控制器，不是多人认证。
[狼人杀](examples/THREE_SEAT_WEREWOLF.md)解释角色/人数与规则编辑；
[M1](../../packages/thawed_everflame/README.md)给出当前单玩家入口。
[货件](examples/PARCEL_DELIVERY.md)、[Object 目标](examples/OBJECT_TARGET_V1.md)
及有限区域/骰子四文件用于中性编译能力校准，不是替代底层能力的整局测试。

## 表达式与复用

结构化表达式和受限文本表达式进入同一不可变
[C0Expression](expression_ir_v1.py)。类型、nullable 证明、读写端口和求值阶段
都在编译时受检；Run 拒绝 raw 作者 AST。

- `const/ref`、记录、tuple 与有限集合查询/替换有明确类型与字段权限。
- 可直接声明 `exists` / `exactly_one`（`collection/as/where`）表达存在/唯一匹配，
  在 IR 保留语义并按合同短路；需要数值时才用 `count(...)`，不执行 Python。
  `none_matching` 表达无匹配。[选型、执行分类与边界](../../docs/C0_FINITE_QUERY_PREDICATES_V1.md)。
- `unique_by: {collection: scene.paths, as: path, keys: [path.start, path.end]}`
  声明单键/复合键无重复，保留独立 IR、单次查重与重复短路；不去重、不授予身份，
  不绕过 Ports 已有集合键约束，见同页合同。
- `collect_matching` 保序筛选并投影有限 tuple；整体记录返回须核完整读权，
  不自动成为 Actor 知识，见[合同与 M1 消费](../../docs/C0_FINITE_COLLECTION_PROJECTION.md)。
- `tuple_at: {collection: <表达式>, index: <表达式>}` 从 `tuple[T, ...]`
  按零起始 exact int 索引返回原名义 T；空域、负数、越界或运行类型错误为
  `C0ValueStateError`。不排序、不掷骰、不查 owner；let、call 与整记录输出保留
  集合来源读权，见[合同](../../docs/design_notes/C0_TUPLE_AT_V1.md)。
- occurrence、Actor 和 Object 引用是不可拆解的原子值；可以在记录中保留引用，
  不能把它们当普通记录读取内部整数、构造新引用或据此证明来源真实。
- `all/any/if` 按顺序短路；非空证明只在合法作用域/分支中有效。
- `add/sub/mul/ceil_div` 有明确整数界；不把溢出/下溢伪装成世界拒绝。
- `let` 和 Lib 纯 `call` 使用封闭形式参数、无环定义与每次求值局部复用。
- 输出族可声明有序的成员局部 `bindings`，供本成员字段效果惰性复用；
  文本可写整数算术及条件取值，见[成员计算](../../docs/C0_OUTPUT_MEMBER_COMPUTATIONS_V1.md)。
- Lib `appraisal_definitions` 共享评分规则和形式行动槽；Source 显式绑定实际席位、
  Action 或封闭 family，展开后仍核本人读权与完整覆盖，不授予行动资格。
  [参数化评分](../../docs/C0_APPRAISAL_DEFINITIONS.md)。
- `require` 为条件命名；来源保留冻结的定义/调用/绑定/展开坐标。
- `die_roll/die_next_seed` 在运行时仅在效果阶段结算；开局的独立构造阶段只允许
  显式 `draw` 绑定，菜单与诊断不能消耗种子。
- debit/transfer/consume 生成选定的足额、容量、资格和成套原子效果。

这些抽象不暗加题材规则。持有、同地、清醒、角色、药水限制和地图仍由作者
明确声明。纯函数不隐藏 owner 读取，也不能洗掉参数的字段权限。

## 端点、形成与有限展开

端点已经声明 Scene/Actor/payload/参与者后，值许可不重复声明 roots 或
Python carrier 类型，使用 `read` 与 `write_paths`，例如：

```yaml
effects: {scene: [], actor: [sent_ref]}
envelope_fields: [action]
value:
  read: [actor.sent_ref, payload.destination]
  write_paths: [actor.sent_ref]
  fields: {}
  construct: []
  collections: {}
```

端点生成结果类型不等于自动授予写权。`effects` 决定实际写图，
`write_paths` 是允许的值修改上界；同类型只读参与者不会因此可写。
席位可读字段是另一份显式声明。

因果 Event 的写图只由 Ports 的输出目的地声明；Source 不再重复填写 `effect`：

```yaml
value:
  read: [actor.notice, trigger.occurrence]
  write_paths: [actor.notice]
  outputs:
    heard: {target: actor.notice, type: Notice}
  fields: {}
  construct: [Notice]
  collections: {}
```

这里 `heard` 是 Law 计算结果的别名，`actor.notice` 是唯一目的地，不能按同名猜测。
普通输出可简写为 `heard: actor.notice`，类型由目的字段推导；`target/type` 只用于
显式精化，例如可空字段本次输出非空 `Notice`，必须符合目的字段类型。
写入仍须单独具有 `write_paths` 许可；Scene Event 只能写 Scene，Actor Event
只能写所选接收者的字段，不能借输出声明写 trigger 或只读域。
独立形成输出仍声明产物类型（如 `newborn: Tool`），由 Source 的
`object_product` / `actor_product` 选择形成，不自动成为已有 owner 的字段更新。
旧 Source 因果 `form/when_false/effect` 一律编译拒绝，无兼容或回退。
due 主效果同样从 Ports `value.outputs` 目的地生成；可写范围只限 Scene 与
显式 `owner_roots`，每个目的地必须具有自己的 `write_paths`，同状态类型不授予
另一个 owner 的写权。固定物件/只读域不是可写根。Source due 不接受 `effect`。
Action/due 人物域效果也只由成员端口生成，Source 域项只保留 `name/law`。
普通 Action 的 `effects`、envelope 与形成端口仍是各自唯一的端点声明。

定时 Action 的 Source 只选到期来源：`schedule: {source: world.arrive.due}`；
`subject_output` / `delay_output` 在 Ports 模板声明一次，C0 生成内部接线。
Source 重复这两个字段即使完全匹配也拒绝，不提供兼容回退。

共同发生体与独立形成边进入 [Transition IR](semantic_ir_v0.py)：
Action false 为有限拒绝，causal false 不形成 Event，required due 形成后的
失败沿 K0 原子 fatal 边界。实际前驱与参与者不得靠模板名回猜。

有限 Action/recipient/seat/output 族只展开 Source 明列的域。
每个实例保有独立来源、owner 和权限；output family 可在同一 Event 中写
多 owner，但不是自动发现所有人物，也不是通用同波合并。

## Object、时间与控制

### 局内 Actor 模板与形成

Lib `actor_kinds` 声明名义状态、容量与实例本地读权；Source `actor_templates`
声明能力、选项、资格、费用、正出生债务、平局优先级和显式控制器。
`actor: {self: kind}` 能力以实际 Actor ref 寻址本人 owner，不展开成假静态人物。
Action、因果 Event、due 均可声明产品：

```yaml
actor_product: {kind: sprite, cardinality: zero_or_one, initial_output: newborn}
```

`one` 必须形成；`zero_or_one` 明确允许输出 None。它们不吞容量或后态错误。
Assets `opening_actors` 只给 kind/state/debt，运行时分配身份；开局和新生随后使用
同一能力合同。形成 occurrence 与个体 ref 不相同。身份、owner、形成配额、
席位与债务由 K0 一次原子发布，失败不留下半个 Actor；形成不向其他席位广播知识。

due 的 `actor_domains` / `actor_domain_effects` 显式选择当前实际 kind 域与逐实例
Law；Action 的人物域同样使用这条合同。Source 的每个域只填 `name/law`，
旧域内 `effect` 一律拒绝。Ports 的域 `value.outputs` 必须逐项声明 `actor.<field>`
目的地（可显式精化类型），C0 生成逐实例写图；不能把裸类型按同名猜成写入。
空域不取消主 due，任一实例结算缺陷回滚整次推进；本 Event 才形成的
Actor 不追溯参与本根的前态效果。Actor Event 的 `read_actor_domains` 则只提供
actual ref 和明列字段的有限名义投影，作者 Law 仍须形成收件人本地观察记录。
世界读权、审计参与者和 Actor 已知内容三者不同；多匹配不任意选一名。
此接口不提供动态因果收件人、任意广播或公共恢复。

入口：[模板](actor_template_v1.py)、[产品](actor_product_v1.py)、
[有限域](actor_domain_v1.py)；中性门 `test_actor_formation_v1.py`、
`test_actor_domain_due_v1.py`、`test_actor_domain_observation_v1.py`。

### Object 与参与者

Ports 的 `participant_groups` 可让多项 Action 引用同一份有限参与者签名，
统一展开共同读字段和效果端口，再逐项检查名义类型和权限。
它不形成运行时集合，不自动绑定实际人物，也不扩大知识或 owner 权威。
语法与 M1 例子见[成组参与者](../../docs/C0_PARTICIPANT_GROUPS_V1.md)。

Source 的 `participant_bindings` / Action `use_participants` 可复用实际人物/物件
选择，和 Ports 签名组分工不同；每项使用仍独立核名义类型与读写许可。
见[实名绑定](../../docs/C0_PARTICIPANT_BINDINGS_V1.md)。
Source 的 `offer_sets` 在原位置复用菜单片段，不共享席位读权；
GameForm 的 `cost_groups` 为显式 Action 名单复用费用，仍逐 Action 编译检查。
见[菜单与费用复用](../../docs/C0_SOURCE_MENU_AND_COST_REUSE_V1.md)。
所选组还可在 Action value 中使用 `any_participant`、`all_participants`、
`fold_participants`，让同一判断或累积模板只写一次，按已授权成员展开并检查。
见[组表达式](../../docs/C0_PARTICIPANT_EXPRESSIONS_V1.md)。

Ports due 模板可声明 `read_object_domains`，按已选 Object kind 读取当前实际有限域：

```yaml
read_object_domains:
  - name: items
    kind: artifact
    wrapper: ArtifactDomain
    members_field: members
    record: ArtifactEntry
    identity_field: individual
    fields: {holder: holder, site: site}
```

Lib 的 `ArtifactEntry.individual` 必须是 `individual_ref`，其余字段逐项匹配
物件状态的类型与约束；wrapper 仅含有界 `tuple[ArtifactEntry]`，容量覆盖 kind
上限。Source 选定 kind 后，due Law 的普通 read/fields 端口决定可读字段。
同一 due 的 Actor-domain Law 可显式读取这个共同 wrapper 根，不获得物件写权。
K0 每个 due 微步从当前 candidate 的实际 bindings 读取，包括开局、此前形成或
更新的实例；空域合法，同边界前序合法因果闭包形成的实例会进入后序 due。
证据封存实际 ref/owner/state，participants/envelope 的 `objects` 保留域名与 ref。
这不是 Actor 观察，不自动添加选项或知识，不扩展 Action/因果 Event 的域入口，
不允许域写入或 due 形成 Object。中性门：`test_read_object_domain_due_v1.py`。

同一 Action 可以组合已选 `participants` 与 `form: {kind, initial_output}`：
原参与者按明列权限更新，新 Object 按精确初态输出形成独立 owner；K0 原子发布
或回滚两者。同 family 不合并身份，形成不自动授予 Actor 知识。
参与者与 scheduling 的组合仍未开放。见[组合验证](../../docs/closure_notes/C0_PARTICIPANT_OBJECT_FORMATION.md)。

开局与运行时形成的 Object 各有受检个体 owner。目标引用、所选 family、
名义 sort/有限专门化、当前位置和声明可及性在候选与 K0 准入分别核查。
这不等于全局任意 subtype 或异构 carrier 自动适配。

有限 Actor Action family 可声明动态 Object `target`，与 `participants` 互斥。
本地已知的 individual ref 可作身份比较，不因此获得 Object 字段读权。
Object/participant 候选的 `read` 是显式投影读域，可只声明 Action 许可输入的子集；
该读域留在 Visibility IR，不自动继承世界 Law 的全部输入。候选条件不必复制
准入 guard，菜单可以显示一个会被世界拒绝的尝试，提交仍由 K0 重核。
跨题材取放/交接样本见[灯店首片](../../packages/findlays_lamp_emporium/README.md)。

多参与者候选枚举多个明确的Object角色，角色可以共享kind，实际ref各自独立。
可选地枚举一本人知识中的Actor域，另显式固定singleton Object/Actor。
不需要人物目标的行为不用创建假Actor。固定资源不按每个目标复制：

```yaml
for_each_participants:
  target: {kind: tool, read: [target.label]}
  resource: {fixed_kind: resource, read: [resource.units]}
  recipient: {collection: {ref: actor.known_people}, as: candidate}
payload:
  target: {ref: target_ref}
  resource: {ref: resource_ref}
  recipient: {ref: candidate.name}
```

固定 kind 必须已选定、容量为一并精确匹配参与者端口。缺失资源不生成选项，
角色的读域与ref在编译及IR Bind两处核查，不按kind合并权限。
标签使用有序字符串表达式片段，例如：

```yaml
label: [{const: 'Use '}, {ref: target.label}, {const: ' for '}, {ref: candidate.name}]
```

完整角色绑定先核可见性，再求标签和payload；每声明组合工作量受provider的
`limit²`约束，产出及整个席位累计另受`limit`约束，超限报告fault而非截断前缀。
受检IR把人物集合、alias和身份域组织成完整可选枚举声明。
显式固定的人物参数仍须完整填写，并非可选的Action参数。
这些是候选机制的边界，世界许可、资源扣除和后态仍由实际 K0 Action 决定。
当前源码、组合合同及返回门见[物件角色组合](../../docs/C0_OBJECT_ROLE_PRODUCTS.md)。
直接试玩：`python -m nomos_c0.owner_graph_play_v1 container_transfer_v1`。
这是同一Law对不同容器的真实编译验证，不是M1人物合作已完成。

`fixed_participants: true` 可把所有参与者固定到各自 singleton 域，选项中不公开
它们的 selector；Submit 才解析实际个体。参与者可全为封闭域 Actor，不要求
额外绑定 Object，但集合必须非空。其 `payload` 精确填写剩余非 selector
字段，可从该席位显式读域计算 `str/int/bool/occurrence_ref`。不能覆盖 actor
或参与者字段，不能读取其他人物私态；`when` 的非空证明只支持本次参数投影。
参数表达式保留在 Visibility IR，Bind 核字段和类型；提交仍匹配当前选项并经 K0。
中性门为 `test_multi_participant_action_v0.py`，M1 地面解冻使用同一接口。

即时 Action 也可选择一个有独立 owner 的动态 Actor。Ports 用 `selector: actor`
和 `actor_ref` payload，Source 将角色绑定到一个已选 Actor kind：

```yaml
# Ports Action.participants
- {name: recipient, selector: actor, state: Sprite, payload_field: recipient, write: true}
# Source Action.participants
recipient: {kind: sprite}
```

候选只能来自本人有限、已读的本地记录，明确指出记录中的 Actor-ref 字段：

```yaml
for_each_participants:
  recipient: {collection: {ref: actor.known}, as: candidate, identity_field: subject}
payload:
  recipient: {ref: candidate.subject}
```

这一路可以只有 Actor 目标，也可以组合已声明的 Object 资源；不需静态人物影子。
形成不自动生成知识，当前 ref 必须属于所选 family 和本局真实实例。
候选不取得目标私态读权；需要只读可用性信号时仍显式声明 `candidate_inputs`。
提交按当前 owner 重核 Law，资源与目标更新同次原子结算。
该 selector 不支持 `fixed_actor` 或自动 singleton 猜选，不要求未来目标在开局已存在。
独立 Bind 重核相同名义 carrier、family、payload 与读写许可。
中性短门为 `test_selected_actor_participant_v1.py`；完整边界见
[动态 Actor 参与者](../../docs/C0_SELECTED_ACTOR_PARTICIPANTS_V1.md)。

`offers[].availability` 可用 Ports 显式声明的 `candidate_inputs` 筛选已经生成的
候选。输入仅限所选 Action 原有的 Scene / 本人 Actor / 完整 payload 及本次已选
target/participants 准入只读权限，不另扩 owner 域，
输出只能是布尔值；不会扩大席位 read、候选 label/payload 或 Appraisal 的读取域。
条件保留在 Visibility IR，独立 Bind 重核，同步读取/提交时重新计算，K0 仍最终准入。
出现/消失本身也是信息，因此作者须明确许可该信号，不能借过滤查询未知目标。
说明与中性短门见[候选可用性](../../docs/C0_CANDIDATE_INPUTS.md)。

候选 payload 可传已授权读域中的 opaque `occurrence_ref`，例如本人观察的来源：

```yaml
when: {not_none: {ref: actor.evidence}}
payload: {basis: {ref: actor.evidence.observation}}
```

`when` 成立后，其受检非空条件可用于 payload；Object/participant 的 `visible_when`
也只在通过后提供这种证明。该证明不增加字段读权、不跨候选传递，`any`/反向 `not`
不能充当必然非空。整数和字符串不能转换成来源引用；引用也不授予读取历史的权利。
Submit 保留精确类型，K0 Law 仍重核它是否是当前合格依据。
中性门：`test_occurrence_reference_offers_v1.py`；真实消费见
[M3 幻火](../../docs/M3_FIRE_BELIEF_SLICE.md)。
此入口补充覆盖静态席位候选；动态 Actor 模板 payload 仍为原有有限标量合同。

`value.effects` 支持命名的 `assign` 成组赋值：

```yaml
effects:
  - change_pair:
      when: selected
      assign:
        actor.strength: {mul: [actor.base_strength, 2]}
        actor.size: {mul: [actor.base_size, 2]}
```

条件属于 effect 阶段，不额外限制 Action 准入。false 保持本组字段原值，其他
输出照常发布；true 的所有赋值读同一前态，不是微步。端点须在 Ports 实际写图中，
隐含保留须有旧值读权；重叠写和错类型在编译拒绝。算术使用现有结构化操作，
文本条件不开放任意 Python。资源 `debit/transfer/consume` 仍自带准入检查。
两项设计与验证见[本片记录](../../docs/C0_PROJECTION_AND_GROUPED_EFFECTS.md)。

作者可选有限 manual/event-jump 控制、一次性/周期 due、显式同刻策略与
机会停止。GameForm defer 只记控制历史，不伪造世界 Action；时间推进与
真实 due 的发生则由 K0 记录。预算/成本、动态 delay 和 finite Appraisal
仍受声明及当前态限制，不保证 NPC 合作。

`action_value_event_jump` 的有序 `world_stops` 是正常终局声明：每项显式列
`outcome`、所读 `owners` 和布尔 `when`。C0 Bind 把受检只读谓词绑定进同一
K0 Profile；Run 只读已发布的终止状态，不再用另一份后置检查裁结果。
合法开局、完整 Action 因果闭包、每项 due 的完整闭包后检查，不在子 Event 中途停。
命中时原子发布实际前缀；同刻后缀未投影、分配或抽骰，已有有限 pending 记
`not_reached`，周期计划封闭且不展开无限未来。Session 永久只读，正常封闭与
准入拒绝/fatal 区分。此机制不提供存档、取消 Event 或任意 yield。
短门：`test_authored_terminal_settlement_v1.py`；K0 中性门见
`engine/kernel/tests/test_terminal_settlement_v1.py`。

只需要人物机会、没有 due Event 时，`action_value_event_jump` 可显式声明
`order: []`、`max_pending: 0`、`periodic: []` 与空 `due_events`。
无需添加假脉冲；这不允许非空 due 配零容量，也不允许空的 ordered-due 微步。

`scene_action_v1`、`scene_due_v1` 等保留的组件是当前受检 builder，不是旧备用
完整编译链。具体能力、失败阶段和测试 nodeid 统一见
[语义地图](../../docs/guides/C0_CURRENT_SEMANTIC_TEST_MATRIX_V1.md)。

## 有限玩家反馈

Source 的 `seats[].presentation` 可为合法行动入口声明固定公开文本：

```yaml
published_actions:
  dispatch: You sent the parcel; arrival is not implied.
```

Frontend 与独立 Visibility IR 均核 entry 属于本席位、文本非空且不超过400字符，
禁止重复入口。终端仅在该次提交返回 `K0Published` 后显示对应文本；
无映射时仍用 `published`，拒绝时只用 `rejected`。
可用同样受检的 `rejected_actions` 为本席位入口提供固定拒绝提示。
提示不是失败guard的证明；不得据此披露作者诊断或声称隐藏原因已被核实。
文本没有变量插值、owner查询或写入，不产生知识、回执、Event 或新的行动许可；
文本内容由作者负责，编译器不证明自然语言主张为真。
不能把本人已发话写成对方已听见、相信或同意；后者需要真实来源和独立读权。
当前新增短门为 `test_published_action_presentation_v1.py`；与终端、M1本地观察
三具名模块合计26项通过，独立复跑同26项通过且无实质finding。
`view`只重看允许的字段；显示值差分不是事件日志。

`preview_fields` 按当前入口标记已有 `offer_previews` 的输出：

```yaml
preview_fields:
  inspect:
    condition: Expected condition
```

字段必须来自该入口的已选受检预测端口，且为`str/int/bool`；
Frontend与独立IR均拒绝外来入口/字段、空标签、重复声明和复合值序列化。
终端只显示所选标签，应用`terms`；缺少预测时仍保留原选项并提示预测不可用。
预测不是K0准入或后果承诺，不产生世界写入。
菜单变化提示只比较本人当前已渲染的选项/预测，不打印payload或私态。

`projection_focus` 可把一张已有只读投影在普通反馈中收起为当前行：

```yaml
projection_focus:
  known_condition: actor.site
```

投影必须属于本席位；焦点必须恰为该投影声明的 `actor.current_field`，
且是本人已获读权、具有显示标签的非 optional 字符串或 enum。
按原始键匹配，不按译名匹配；渲染前仍验证全部行。
完整 `view` 显示全部已授权行，但不会覆盖普通反馈的聚焦差分缓存。
这只是呈现选择，不缩减或扩大读权，也不推断未匹配行。

`finish_fields` 为已有 `finish_on_action` 入口选择一个有限、按序的本人记录回顾：

```yaml
finish_fields:
  leave: [actor.last_seen.name, actor.remaining_charge]
```

仅允许已读且有显示标签的 `str/enum/int/bool` 字段（可穿过 optional 记录）；
拒绝复合记录、引用、集合、重复字段和外来入口。
必须由本人真实发布该行动且匹配结束 outcome，才显示回顾。
复用每次成功呈现时同一次读取，省略未知值、保留 `0/False`。
终端在本进程内保留这些同帧显示记录；连续相同记录去重，不把 `view` 重绘称为新观察。
每入口最多保留最近64个不同显示，截断时明确提示；显示帧不是世界时间或Event数量。
结束时回放这些此前已显示的记录，不只保留最后一人。
这是纯UI日志，不写Actor/Assets/Session，不恢复已清除记忆、不驱动候选或Law，
也不是远处世界的当前安全报告。若需要Actor可用的观测历史，必须另在Source中建模。

`published_fields` 为普通行动选择同类受检标量，在真实发布后立即重印，
不受普通视图差分抑制；在 GameForm 后继推进之前读本人，不增加观察或知识。
未准入不显示成功记录，发布也不自动表示移动成功或营救完成。
完整合同与 M1 消费见[行动发布后的本人记录](../../docs/C0_PUBLISHED_LOCAL_RECORDS_V1.md)。

## 测试与发布

每次只运行明确模块或 nodeid；仓库锁要求串行 pytest：

```bash
.venv/bin/python -m pytest -q \
  tests/nomos_c0/test_program_phases_v1.py \
  tests/nomos_c0/test_program_binding_v1.py
```

发布 wheel 从提交的干净导出构建，不复用 `build/lib`：

```bash
export_root=$(mktemp -d)
git archive HEAD | tar -x -C "$export_root"
.venv/bin/python -m pip wheel --no-deps --no-build-isolation \
  --wheel-dir /tmp/ne2-wheels "$export_root"
```

当前不承诺任意作者语言、完整 UFO、独立 `.py` 世界发布、公开 save/load、
连续/分支时间、通用同波 merge 或自动心智求解。
旧 compiler、GV/FG 消费路径及各片优化记录在[归档](../../archive/README.md)，
不提供兼容层。当前能力以代码、语义地图和对应短测试为准。
