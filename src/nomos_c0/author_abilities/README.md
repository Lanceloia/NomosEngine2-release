# 命名输入与结构值作者语言

作者声明类型、输入、费用和后果，C0 组织引用绑定并生成 Python；Runtime 核对当前状态并原子发布 Action。

    Lib + Source --检查--> AuthorProgram 编译计划 --生成--> Python PROGRAM
    Python PROGRAM + Assets --Start--> nomos_runtime.Session
    选择能力 → 构造命名输入 → Runtime 当前准入 → 实际结果与来源

Program 不带本局 Assets。同一个 Program 可以启动不同开局，各自拥有独立身份与状态。

独立规划模型（研究仓路径：`docs/guides/SCENARIO_PLANNING_FEEDBACK_V1.md`）可以从本人本地值
构造已有能力的输入；结构化配方（研究仓路径：`docs/guides/STRUCTURED_PLANNING_CONSTRUCTION_V1.md`）
进一步按类型逐字段／逐项组织复合内容，世界规则仍负责最终准入和实际交付。
续行窗口（研究仓路径：`docs/guides/OBSERVED_PLANNING_CONTINUATION_V1.md`）将本人实际收件、
行动机会与同范围累计预算组织起来，等待不替代世界让权。

过程与阶段（研究仓路径：`docs/author_language/process_d/README.md`）提供揭示后选择、独立回应，
以及“先取资源、归还超额再完成”的真实三文件样例。
过程可显式声明 `stage.actors` 和 `stage.complete_when`；阶段条件检查本次效果后的状态，
参与者完成前的行动门禁在 Runtime 准入重核。
同一入口还支持独立/声明顺序的多人回应窗口和显式循环；每轮每人一次，旧轮请求失效，
每个答案仍有自己的 Action 和信息边界。

## 直接体验

[通行 Lib](examples/passage.lib.yaml)声明一次有费用的尝试，门是否可通行只决定实际结果。
[携带 Lib](examples/custody.lib.yaml)声明取得、放下、提议交接与接受交接，两种物件共用规则。

    .venv/bin/python -m nomos_c0.python_codegen src/nomos_c0/author_abilities/examples/passage.lib.yaml src/nomos_c0/author_abilities/examples/passage.source.yaml build/python-codegen/passage.py
    .venv/bin/python -m nomos_runtime build/python-codegen/passage.py --assets src/nomos_c0/author_abilities/examples/passage.assets.yaml --manual
    .venv/bin/python -m nomos_c0.python_codegen src/nomos_c0/author_abilities/examples/custody.lib.yaml src/nomos_c0/author_abilities/examples/custody.source.yaml build/python-codegen/custody.py
    .venv/bin/python -m nomos_runtime build/python-codegen/custody.py --assets src/nomos_c0/author_abilities/examples/custody.assets.yaml --manual
    .venv/bin/python -m nomos_c0.author_abilities src/nomos_c0/author_abilities/examples/custody --plan

阿瓦隆完整规则（研究仓路径：`docs/author_language/avalon_g3/README.md`）使用同一入口：五至十席，
秘密表决/匿名任务牌收齐揭示、队长轮换、角色开局信息、刺杀与原生终局。
狼人杀完整核心规则（研究仓路径：`docs/author_language/werewolf_g4/README.md`）支持三至十席、
昼夜投票、查验/放弃、独立双药政策、共同死亡与阵营灭绝终局；每人只有一份身份初设。

CLI 先列能力，再依次询问命名输入。通行输入 1、1，得到付费 Blocked；将
[Assets](examples/passage.assets.yaml) 的 passable 改为 true，同一规则得到 Moved。
seat keeper 切换携带样例中的控制人物，q 退出；构造输入期间 q 取消本次选择。
子集使用空格分隔的编号，序列保留输入顺序；完整选择只提交一次。
typed 输入使用 YAML 值，引用写 {actor: keeper} 或 {object: true_horn}。

## 值类型与透明别名

同一个类型需要第二个业务名称时，可直接引用已有声明：

```yaml
values:
  Role: {enum: [wolf, seer, villager]}
  Roles: {sequence: Role}
  RoleReports: Roles
```

这是已有的透明别名，两个名称使用同一类型计划；别名不会创建新名义身份。
独立声明的Set／Sequence／Optional按元素类型和结构形成类型身份，
但独立枚举、记录与variant仍有名义边界，Ref保留实体sort身份；不能按字段相同自动合并。
别名继承目标的结构及诊断来源／名称，若需要独立演化则分别声明。
`reports`仍须显式声明历史类型，Source仍须绑定实际通道；复用类型不授予任何收件权限。

## 三份文件

高级活动合同（研究仓路径：`docs/design_notes/C0_AUTHORED_ACTIVITIES_G6_V1.md`）支持从真实 Action
开始的独立持续实例：封存 typed 参数，到期按当前状态完成/受阻，另做真实付费取消。
[reading Lib](examples/reading.lib.yaml)与同名 Source/Assets 使用一条规则支持两名读者，
正文只在各自完成后交付本人；完成/取消都可触发后继 Reaction。

    .venv/bin/python -m nomos_c0.python_codegen src/nomos_c0/author_abilities/examples/reading.lib.yaml src/nomos_c0/author_abilities/examples/reading.source.yaml build/python-codegen/reading.py
    .venv/bin/python -m nomos_runtime build/python-codegen/reading.py --assets src/nomos_c0/author_abilities/examples/reading.assets.yaml --manual

输入 `1`、`1` 开始 Alice 的活动，`wait 2` 尚无正文，`wait` 抵达真实到期；
开始后选当前编号的“取消活动”会发布取消 Action 并扣费，不再产生完成报告。
`seat bob` 可查看独立人物视图。Source 显式选择时间机制与到期顺序，Assets 设置实际初始时刻。
没有选择时间机制的世界保持原子行动，不自动增时。

自动 Reaction（研究仓路径：`docs/author_language/reactions_g2/README.md`）已能从高级源码生成
Action→Event→Event：原发生参数/结果保持不变，实体字段按当前波读取，报告只交给明确受众。
Source 用 after 选择实际订阅；同一 compiler 处理不同领域词汇。
`on.definition` 与 Source `after` 可选有限互异来源列表，捕获签名在全部来源上逐项核对。
捕获不同但兼容的实体Ref时，编译器沿已声明的名义sort层级求唯一最近父类型；
例如 BeingRef 与 IceElementalRef 共同捕获为 BeingRef，仍指向各自真实个体与owner。
兄弟子类也可共有名义父类型；无关Ref、不同本体类别与不同非Ref值类型仍拒绝。
这不会创建父类型个体，也不按共同字段做结构兼容。
同一规则体可以由最后一项真实选择触发，每个 Event 保留实际父发生及对应 causal Law。
因果发生额度按无环图路径推导，汇合不会把两个实际触发吞成一个。
终局在原生根闭包检查点求值：Action 及其后继 Event 全部结算后，再决定停止、计分与受众。
闭包计分样例（研究仓路径：`docs/author_language/reactions_g2/README.md#完整闭包后计分`）可直接运行。
结算政策样例（研究仓路径：`docs/author_language/settlement_g3/README.md`）用同一 Lib/Assets 对照普通波与有序重读。
Source 的 settlement 配置完整列出实际订阅的顺序与 required，生成器负责执行接线。

共享协议状态（研究仓路径：`docs/author_language/context_g3/README.md`）将固定 `parameters` 与可变 `state`
分开：能力/Reaction 明确绑定 context，字段效果在 Runtime 的同一事务中结算。
`public` 决定 Actor-local 可读字段，World 结算可读取完整所绑定状态；两个实例和两次 Start 相互隔离。
Assets 用 `contexts` 填写选定状态实例，CLI 只显示其公共字段。

| 文件 | 声明 |
| --- | --- |
| Lib：nomos.author.lib | 值类型、实体字段与视图、纯定义、关系、能力、过程、投影与信息 |
| Source：nomos.author.source | 人物符号、选定 Object sorts、能力实例与固定参数 |
| Assets：nomos.author.assets | 本局人物状态、Object 实例和初态、选定共享状态初设 |

Source 的固定引用参数在 Start 后绑定实际开局身份；固定费用和引用都会在 Runtime 准入中重核。
Assets 中的前向、循环、自引用由生成的开局代码统一绑定，创建失败不返回半装配 Session。
Object 初态可写 holder: {actor: keeper}，持有者是实际人物引用。

    Take:
      actor: {person: PersonRef}
      parameters: {fee: Energy}
      inputs:
        item: {type: PortableRef, choose: known(Portable)}
      where: can_try_take(item, person)
      cost: ['consume(person.energy, fee)']
      results: TakeOutcome
      resolve:
        attempt: custody.take(item, person)
        success: {result: TakeOutcome.Taken()}
        failure: {result: TakeOutcome.Unavailable()}

所有实参均是普通命名输入，没有特殊 target/others。actor 与另一个输入可以指向同一实际个体；
需要不同人的规则显式声明 constraint。

### 显式固定参数预设

Source 的 `presets` 只复用普通 ability 的完整固定配置；实例明确选 `preset`，
与 `definition` 互斥。已有完整 `with` 写法保持。

```yaml
presets:
  melee:
    definition: Melee
    with: {ap_fee: 1, damage: {power: 2, kind: physical, shield_damage: 0}}
ability_sets:
  Attacks:
    context: battle
    members:
      strike: {preset: melee}
      heavy: {preset: melee, with: {ap_fee: 2, damage: {power: 4}}}
```

同样可写 `use.strike: {preset: melee, context: battle}`。预设必须完整、合法，即便未使用，
或非法值在实例中被覆盖也会拒绝。实例 `with` 只写明确差异：仅名义 record 按字段递归覆盖；
其他值（包括集合、引用、Optional、variant）整体替换并检查。字段／参数拼写错误拒绝，
不自动补新参数。示例省略 Lib 的 Melee／Damage 等声明，不是独立可编译文件。

预设不包含 context／scope／views／after 或权限，不支持继承、链式引用或多预设合并。
imports 可拆分具名预设，重名拒绝；错误保留预设／覆盖字段原文件位置。
C0 展开为原有完整 definition／with，仍走现行类型检查、费用、机会、反应和私有反馈。
引用预设是明确共享配置：修改预设会影响所有未覆盖该字段的实例，局部覆盖保持不变。

### 注释

三份 YAML 都支持 `#` 独占行注释和字段尾注释，供作者解释规则意图：

```yaml
# A blocked passage still costs one energy.
TryPass: {definition: TryPass, with: {fee: 1}}  # Movement fee
```

注释留在源码中，reader 不把它们当规则或数据字段。来源摘要仍覆盖完整原文，
诊断行号对应真实文件；修改注释会改变源码摘要，但不改变解析后的规则数据。
引号中的 `#` 是普通文本。`expression: >` 或 `|` 内的文字是表达式内容，
当前表达式 parser 不支持内嵌注释；将说明写在字段上方即可。
注释没有玩家可见语义；局内显示文案须由相应呈现声明提供。
布尔字面量使用 true/false（大小写形式也可）；on/off/yes/no 是普通字符串，
不会再被 reader 隐式当作布尔值。该约定只作用于作者 reader，不修改第三方 YAML loader。

## 输入与共同值

| 输入 | 写法 | 运行语义 |
| --- | --- | --- |
| 成员 | choose: known(Person) | 从当前获准指认域选择一个引用 |
| 子集 | choose: {subset: pool, min: 1, max: limit} | 构造并核完整子集，不展开幂集 |
| 序列 | choose: {sequence: pool, length: count, repetition: forbid} | 核顺序、长度与重复政策 |
| typed | enter: typed | 提交完整有名值，递归核字段、引用与预算 |
| 派生 | derive: size(team) | Actor 上下文计算，不由玩家填 |

绑定依赖按拓扑排序；整组 constraint 在所有输入绑定后检查。
字段、输入、参数、纯定义、结果都使用同一类型表：Bool、Unit、受约束整数、文本、Enum、
Ref、Optional、Record、Variant、Set、Sequence。Set是数据值，不自动形成具有独立身份的集合实体。

构造示例：Pair(first=a, second=b)、Reply.Pass()、People([a, b])。
Variant 拆解使用穷尽 match：
match(reply, Pick(value) => value.score, Pass() => 0)。
静态检查覆盖全部分支，运行只求实际分支；纯定义可以接收和返回结构值。

## 权限、费用与后果

- 每个 entity 显式声明 reference: public 或 projected；known 提供获准本局个体的指认许可。
- Actor-visible 域、constraint、where、费用读取受 view/public 约束；
  同一个实际人物的其他逻辑参数不会继承 actor 私态许可。
- 结果与后果使用 World 上下文；结果是作者显式授予的反馈值。交互入口只展示已发布结果。
- consume 消费主体资源，非负且零合法。普通字段使用 set；
  所有 RHS 从同一前态求值，一次按实际 owner 合成后态。
- `for/in/effects` 对有限 typed 集合逐元素声明普通效果；嵌套保持共同前态，
  空集合没有普通写入，同一实际字段的重复写仍拒绝。它不替 Actor 选择行动。
- 同一实体的不同字段可合成；同字段多写在准入拒绝。费用与后果的重复写也进入此检查。
- Runtime 按当前获准视图重新核原始输入/费用，再从当前 World 结算分支。
  越权、外局或当前已失效的目标不发布；合法的不确定尝试发布正常结果。
- 原生 Actor 身份／控制独立于调度；本入口没有选时间机制，Action 不暗增 tick。

实际参与者记录保留每个命名值及结构内引用路径；事务核对实际状态读取与写入许可。
只用作数据的引用核身份但不投影 owner 状态，字段读取与写入分别选择当前 owner。
prepare 返回一次性不透明句柄，只含 actor/ability；隐藏 World 样本和未发布结果留在受信内部。
submit 才交给 Runtime，遗弃句柄可由普通 Python GC 回收，不发布世界发生。
可用 `epoch: round` 显式标记请求轮次。prepare 采样 typed 值，native admission 先按声明类型
重绑定，再比较当前轮次；同轮其他行动不使请求失效，旧轮请求零写拒绝。
结果的 actual participants 保留规范 epoch，而不是信任请求附带的类型标识。

类型与纯定义还可独立检查：

    .venv/bin/python -m nomos_c0.author_abilities --types src/nomos_c0/author_abilities/examples/structured_values.lib.yaml
    .venv/bin/python -m nomos_c0.author_abilities --pure src/nomos_c0/author_abilities/examples/structured_expressions.lib.yaml

这两个命令不加载开局，也不创建 Session。

## 共享决策机会

Lib的`decision_groups`将同一Actor／epoch内互斥的普通动作集中声明。例如守卫样例中的查验与跳过：

```yaml
decision_groups:
  Inspection:
    context: Match
    actor: {player: PlayerRef}
    epoch: round
    marker: {field: seer_round, type: Round, initial: 0}
    views: {identity: {reports: RoleReports}}
    where: phase == Phase.night and player.alive and exists(reports(identity), role => role == Role.seer)
    alternatives: [Inspect, SkipInspection]
```

选项保留自己的inputs、results、resolve；共同actor/context/epoch不可另行覆盖，额外where与组条件相与。
C0生成同类型Actor字段、本人可读的私态初值、准入条件及发布时的原子标记写入，
不需要手写各选项的次数检查或set。`Inspection_done(player, round)`是生成的纯完成查询，
可在原有世界阶段条件中使用；不是自动调度，参与者、死亡资格和后继反应仍由作者声明。
初值不自动成为永久不变量，已有require_opening继续独立检查；结果为False的已发布选择也消耗机会。

同一动作只能属于一组，多个Source别名共享机会且必须绑定同一context实例；
标记字段与生成的完成查询发生名称冲突会拒绝，不静默覆盖。组条件与单项条件在合并前分别检查，
诊断保留原文件位置，导入的组声明同样可定位。语法展开后仍使用原生Action准入和事务，
不为决策组创建新的运行期实体或解释器。

## 公共编译与加载

```python
from nomos_c0.python_codegen.loading import AuthorPrograms
from nomos_runtime.documents import read_data

with AuthorPrograms() as builds:
    program = builds.load("world.lib.yaml", "world.source.yaml", build_dir="build/world")
    session = program.start(read_data("world.assets.yaml"))
    # 在此作用域内消费session；重复load相同输入复用Program，每次start仍是独立世界。
```

`context_parameters={"match": {"allow_self_save": True}}`只覆盖Source中已有的固定context参数，
不改写Source；类型照常检查，非法wire不会因缓存命中而被接受。输入模块摘要和覆盖参数组成
进程内缓存key，修改导入文件也会重新编译。生成Python保持可检查，运行产物只依赖Runtime。
加载器复用既有`load_world`的模块作用域，消费结束调用close／退出with；不跨线程共享writer。

## 实体公共开局初值

相同类型的开局实体可在Lib显式声明一次公共初值，Assets只写个体差异。例如Lib实体片段：

```yaml
Player:
  kind: person
  reference: public
  fields: {role: Role, alive: Bool, guard_round: Round}
  initial: {alive: true, guard_round: 0}
  view: [alive, guard_round]
  public: [alive]
```

对应Assets可写`a: {role: seer}`；显式提供`alive: false`会覆盖公共初值，随后仍须通过
类型检查和已有require_opening。未声明初值的字段不会被猜成0／False，仍须显式提供。
初值必须是该字段类型的无身份依赖字面量；允许空引用集合和可选引用的null，
不支持用具体Actor／Object引用或表达式生成初值。父类型初值继承，子类型可明确覆盖。

初值与开局发牌写同一类型范围／字段时编译拒绝；Assets与发牌的既有冲突也继续拒绝。
Start独立物化缺省字段，不补写输入Assets；开局断言、信息报告和后续行动看到相同的完整状态。
受信`session.inspect_initials()`返回实际采用的初值来源、目标、字段和值，不授予Actor额外读取权限；
`inspect_opening()`仍专门记录发牌。后续formation必须继续明确提供字段，本项不改变其生命周期。

## 携带协议

custody.position(item) 从实际 holder 当前位置或 ground 推导；纯查询不存一份派生位置。
取得与放下分别用 custody.take/drop。custody.offer(item, giver, recipient) 保留真实提议 Action，
接收者另选 custody.transfer；准入重核当前持有者、双方位置与被寻址的提议。
无提议可产生已发布的付费失败；成功接收保留原提议 occurrence 作为支持来源。
holder/ground 属于关系管理字段，通用 set 不能绕过协议。

## 当前信息投影

Lib 可以声明共享 context 与当前 projection，Source 绑定一次实参并选择输出。
花火三份文件（研究仓路径：`docs/author_language/information_b/README.md`）现在可直接运行：

    .venv/bin/python -m nomos_c0.python_codegen docs/author_language/information_b/fireworks.lib.yaml docs/author_language/information_b/fireworks.source.yaml build/python-codegen/fireworks.py
    .venv/bin/python -m nomos_runtime build/python-codegen/fireworks.py --assets docs/author_language/information_b/fireworks.assets.yaml --manual
    .venv/bin/python -m nomos_c0.author_abilities docs/author_language/information_b/fireworks --plan

`seat b` 查看另一人的获准视图。这个信息样本只读取牌面，没有出牌流程。
本人手牌只返回引用，他人已发手牌返回牌面，未发牌不在输出中。
`session.project(actor, name)` 返回 available 与已编码 value；无许可不同于空集合。
每次查询在同一当前快照上重算，读取本身不写世界或发布 occurrence。
Sequence `filter(xs, x => predicate)` 保留原顺序和重复值。

`reference: projected` 的引用通过获准输出进入当前指认域；指认许可不开放字段私态。
`session.view_codec(actor)` 给受信控制器当前引用许可，不向玩家公开整个目录。
公开和 projected 引用均可进入 Action 输入：当前本人指认许可与域在 Runtime 准入重核，
不知道的引用或已撤出域的目标拒绝，未授权秘密变化不让同一合法选择额外失效。
`require_opening` 在 Start 原子创建内检查基础初态，不构成永久不变量。

## 开局信息报告

`information` 声明 `trigger: opening` 和 `access: acquired`：Runtime 在成功创建边界
交付带接收者身份的开局报告，保存在本Session的实际收件中。
`audience` 选择接收者，`returns/value` 描述当时内容；资格后来变化，已取得内容仍可读。

    .venv/bin/python -m nomos_c0.python_codegen docs/author_language/information_b/avalon.lib.yaml docs/author_language/information_b/avalon.source.yaml build/python-codegen/avalon_information.py
    .venv/bin/python -m nomos_runtime build/python-codegen/avalon_information.py --assets docs/author_language/information_b/avalon.assets.yaml --manual
    .venv/bin/python -m nomos_c0.python_codegen docs/author_language/information_b/werewolf.lib.yaml docs/author_language/information_b/werewolf.source.yaml build/python-codegen/werewolf_information.py
    .venv/bin/python -m nomos_runtime build/python-codegen/werewolf_information.py --assets docs/author_language/information_b/werewolf.assets.yaml --manual

`session.report(actor, name)` 返回 `{acquired: true, value: ...}` 或 `{acquired: false}`。
空集合是已取得的内容，区别于未取得。多个报告分别保存，普通 Action 保留它们。
阿瓦隆的 Candidates 给帕西瓦尔人物集合和角色槽，配对保持未区分；OwnRole 给本人初始角色。
狼人杀各狼收到排除自己的同伴集合，其他席位只收到本人角色。
报告中的引用授予指认许可，字段读取仍按实体视图声明检查。
这两个信息样本供换席阅读；完整流程见上面的阿瓦隆和狼人杀作者世界。

Runtime 保留本局的非 occurrence 开局依据，所有声明读取同一基础初态。
约束、内容求值、状态装配或最终不变量失败时，Start 不返回半份报告。
原生依据留在受信审计面；CLI 仅展示本人获准内容。

## 行动信息

disclosures 声明参数化的信息函数：sample 选择 before/after，to 选择接收者，
returns/value 定义报告。resolve.deliver 调用它，C0 自动组织 typed 槽和后态装配。
槽还可声明`{for: item, in: items, value: 'Notice(item)'}`进行逐项交付。
Sequence保序，Set按稳定值顺序展开；局部绑定与每项调用在Compile受检，
生成Python循环并按迭代计effect预算。示例和原子边界见
复合发言的通用交付合同（研究仓路径：`docs/design_notes/COMPOUND_PUBLIC_SPEECH_V1.md`）。
完整查验/秘密交换样本（研究仓路径：`docs/author_language/information_c/README.md`）可直接运行。

```yaml
resolve:
  result: CheckDone.Completed()
  deliver:
    sighting: InspectionResult(inspector, subject)
```

before 是该 Action 费用/字段效果前，after 是这些普通效果后、同次报告追加前。
全部报告取同一声明阶段的真实快照；多个接收者、同 owner 多报告、费用与效果一起原子提交。
报告原文保持；显式逐项交付可在同一发生、同一渠道内保留多项值。
普通集合载荷仍是一份报告，只有显式逐项调用才产生多份收件。
session.reports(actor, "Inspect.sighting") 返回 acquired 与原生 values 历史。
Lib views 声明本地读取类型，Source 绑定渠道；reports(alias) 是本人内容序列，
projected(alias) 是本人当前投影。不存在的投影与空投影区分，别名冲突 Compile 拒绝。
exists/forall 支持 Set 和 Sequence，保留短路求值。
`at(sequence, index)` 用零起点下标，越界明确拒绝；`append(sequence, value)` 返回保序的新序列。
`concat(left, right)` 拼接同名义成员类型的两个 Sequence，保留顺序与重复，并检查有限值预算。
`index_of(sequence, member)` 返回第一次出现的零起点序号；不存在时报告 `MissingSequenceMember`。
它们可用于拼接工位表和计算已声明座位的顺序，不引入世界写入或隐式集合转换。
Set 不接受下标。整数范围可写 `int: [0, null]` 或 `[null, null]`，开放上界与工程资源预算分开。

submit/act 统一返回 ActorActionResult(status, feedback, reports, code)。
反馈及报告已按声明编码；完整发生记录与Actor获准内容分开，受信审计使用`session.history()`。

## 继续选择

桌游还可以由 Source 选择 `play.joint_decisions`：使用一个获准当前投影中的参与者 Ref、
锁定 Bool 和同 context 的公开整数 epoch，绑定本窗口使用的 Action。
这是一项独立控制协议，世界依然通过 Action/Reaction 决定改选、锁定和收齐结果。
它与 process 的一次性 response `window` 分工不同，见
共同决策合同（研究仓路径：`docs/design_notes/TABLETOP_JOINT_DECISIONS_V1.md`）。

`processes` 声明 begin 和若干 decisions；每个叶子的 `next` 指向下一选择点或 finish。
费用、世界效果、报告和待选择事实一起提交；到后续点才接受后续输入。
每次回应是实际 chooser 的独立 Action，前面的费用与结果保持。
完整检查/请求双样本（研究仓路径：`docs/author_language/process_d/README.md`）可运行：

    .venv/bin/python -m nomos_c0.python_codegen docs/author_language/process_d/reveal.lib.yaml docs/author_language/process_d/reveal.source.yaml build/python-codegen/reveal.py
    .venv/bin/python -m nomos_runtime build/python-codegen/reveal.py --assets docs/author_language/process_d/reveal.assets.yaml --manual
    .venv/bin/python -m nomos_c0.python_codegen docs/author_language/process_d/request.lib.yaml docs/author_language/process_d/request.source.yaml build/python-codegen/request.py
    .venv/bin/python -m nomos_runtime build/python-codegen/request.py --assets docs/author_language/process_d/request.assets.yaml --manual

`session.requests(actor)` 返回本人的不透明机会；`session.reply(actor, request, choices)` 提交新选择。
`from: begin.finding` 将 typed reports 限定到本次过程、本接收者、对应祖先发生的实际报告。
过程的外部 typed views 由当前 chooser 重读；跨人物的私有前缀输入不自动开放。
重复、错人、旧点/外局回应在 Runtime 再核；正常失败结果可完成过程。
过程报告历史通道为 `Survey.begin.finding`，普通能力仍为 `Inspect.sighting`。
顶层 `instances: one_pending_per_initiator` 显式限制同一发起者重入；其他请求仍可独立回应。
当前支持分支汇合、多人回应窗口与有结构出口的可约循环。finish 完成一次过程；
阶段义务用 stage 声明，世界终局用 terminals 声明。

## 代码地图

| 模块 | 责任 |
| --- | --- |
| frontend.py | 唯一 Lib/Source 编译入口 |
| value_types.py、values.py | 名义类型、共同值 codec 与引用许可 |
| expression_syntax.py、expressions.py | 结构化 parser、纯表达式、类型与短路 |
| entity_reads.py | 实体／关系读摘要与当前受检视图 |
| inputs.py | 命名输入、依赖顺序与完整约束 |
| projections.py | shared context/当前投影 IR 与受检读依赖 |
| context_state.py | 共享状态声明、公共引用与固定 context 效果 |
| information.py | 开局信息 IR、受检派生/装配与管理报告 |
| local_views.py、disclosures.py | 本地渠道输入、行动信息函数与采样计划 |
| feedback.py | 保存选择与本人实际收件的反馈政策、类型化关联集合 |
| processes.py、process_graph.py | typed 选择图、作用域、控制者与普通输入/效果复用 |
| terminals.py | 世界终局 IR、边界、受众与返回类型检查 |
| settlements.py | Source 结算政策 IR、实际订阅覆盖检查与有序步骤计划 |
| reactions.py | 多来源 typed 签名、实际 Event/causal Law 与因果 DAG 额度 |
| activities.py、periodic.py | typed 活动完成/取消、周期根与正式原生到期绑定 |
| scheduling.py | 作者本人状态速率、独立行动时间成本与原生机会控制 |
| randomness.py | 作者选定的可重放骰子、普通机制 owner 与实际抽样记录 |
| formation.py | Object typed 初始化、数量槽推导、实际产品捕获和受检 Object 读域 |
| assembly.py | 同一 Lib/Source 的多文件声明装配、重复/循环检查及原文件位置 |
| strategies.py | 当前 Actor-local 候选评分、显式平局/等待及局内提案句柄 |
| effects.py | typed 费用、字段、有限效果组与携带计划 |
| opening.py、literal_values.py | 受检开局符号与类型化字面量计划 |
| fixed_values.py | 编译期固定结构值求值，符号引用与局内身份分离 |
| execution_io.py | 分阶段状态／身份／信息读写依赖，供生成器接线 |
| program.py | 无Assets的编译计划及规范化能力输入 |

可执行Program由[Python生成器](../python_codegen/README.md)构建；
事务、Start、信息与控制由[Runtime](../../nomos_runtime/README.md)实现。

当前运行子集是 Entry/后续选择、当前指认域、结构值、携带协议、当前投影、开局与发生报告，
以及阶段义务、多人窗口、可约循环、因果 Event、显式结算政策、共享状态与类型化终局。
terminals 的 action/freeze 与 processes/complete_existing 政策均由作者显式选用，
详见五份过程/终局样本（研究仓路径：`docs/author_language/process_d/README.md`）。
活动、周期与 Actor-first 已接入显式 event_jump；可重放骰子已接入结算期 draw，
Object 形成与实际产品捕获、本地策略和模块装配已接入。
Source 中固定 Object 参数尚无实例符号声明，不能从 Assets 猜测绑定。
编译计划保留在内存中；生成的`.py`由Runtime直接执行，发行/Web保持独立冻结版本。

## 周期规则

```yaml
periodic:
  PracticePulse:
    parameters: {worker: WorkerRef, interval: Duration}
    interval: interval
    results: Bool
    resolve:
      when: worker.awake
      then:
        effects: ['set(worker.count, worker.count + 1)']
        result: 'True'
        deliver: {progress: 'Progress(worker)'}
      else: {result: 'False'}
```

在 Source.use 中传固定参数，Source.time 显式选择 event_jump，并在 due_order 中列全周期与活动。
Assets.time.at 定义开局时刻；周期首刻默认在 interval 后，可另写正整数 first_after 表达式。
尺度只依赖固定参数，实际效果每次读取当前 owner；无效果分支也发布正常 Event。
没有隐含最大回合，世界终局规则负责停止。工程容量耗尽是诊断，不是游戏结局。
周期可触发普通 Reaction；progress 只进入声明接收者的真实报告通道。

运行[双人独立周期样本](examples/periodic_workshop.lib.yaml)：

    .venv/bin/python -m nomos_c0.python_codegen src/nomos_c0/author_abilities/examples/periodic_workshop.lib.yaml src/nomos_c0/author_abilities/examples/periodic_workshop.source.yaml build/python-codegen/periodic_workshop.py
    .venv/bin/python -m nomos_runtime build/python-codegen/periodic_workshop.py --assets src/nomos_c0/author_abilities/examples/periodic_workshop.assets.yaml --manual

输入 `wait` 前进到下一实际到期，`seat bob` 切换受信控制席位；两人分别在 3、5 的周期上练习。
`--plan` 只编译规则并展示周期尺度，不启动 Session。
完整合同（研究仓路径：`docs/design_notes/C0_AUTHORED_PERIODIC_G6_V1.md`）说明身份构造、原子回滚与当前边界。

## 速度与行动机会

```yaml
schedules:
  BySpeed:
    actor: {worker: WorkerRef}
    parameters: {initial: ActionValue}
    speed: worker.speed
    eligible: worker.awake
    initial: initial
```

Source.time.scheduling 为全部选定人物类型绑定 schedule，声明 `wait: next_world_change`。
每项能力、过程步骤和取消活动另写正整数 `time_cost`；资源 `cost` 仍独立。
速度只读取人物本人当前状态；暂停人物可以为 0，合格人物必须为正。
可在 Assets.time.readiness 中给每个开局人物配置非负初始行动值。

```python
control = session.next_opportunity()
if control.status == "ready":
    actor = control.opportunity.actor
    # Choose a current local ability, or yield control without a world Action.
    session.defer_opportunity(actor, control.opportunity)
```

`ready/due/idle/closed` 区分人物机会、实际到期事件、当前无后续机会与真实终局。
同刻准备机会先于 due；等待不扣资源、不发布 Action、不积累免费的连发行动值。
错人、外局或过时句柄明确拒绝。调度世界不允许 ordinary advance 绕过当前人物。
CLI 根据真实机会切换受信控制席位，输入 `wait` 交还本次机会。

    .venv/bin/python -m nomos_c0.python_codegen src/nomos_c0/author_abilities/examples/scheduled_workshop.lib.yaml src/nomos_c0/author_abilities/examples/scheduled_workshop.source.yaml build/python-codegen/scheduled_workshop.py
    .venv/bin/python -m nomos_runtime build/python-codegen/scheduled_workshop.py --assets src/nomos_c0/author_abilities/examples/scheduled_workshop.assets.yaml --manual

样本两人以速度 2/3、初始行动值 6 开局；Bob 在时刻 2 先行动，Alice 在时刻 3 先于周期脉冲行动。
周期后速度真实更新，下一次机会读取新状态。正式合同（研究仓路径：`docs/design_notes/C0_ACTOR_FIRST_SCHEDULING_G6_V1.md`）。

## 骰子检定

```yaml
resolve:
  draw:
    rolled: {type: DieRoll, sides: '20'}
  then:
    effects: ['set(worker.last_roll, rolled)']
    result: 'Trial(roll=rolled, success=rolled >= threshold)'
```

在 values 中预先声明 `DieRoll: {int: [1,20]}` 和 Trial 结果类型。
Source 选择 `random: {mechanism: replayable_seed}`，Assets 设置 `random: {seed: 42}`。

开局随机分配可声明 `opening: {identities: {context: match, deal: public_cast, to: order, field: role}}`。
`deal`/`to`是同一Context的固定Sequence参数，后者含实体引用；牌元素必须与目标字段名义类型一致。
Assets省略由发牌填入的字段；人数不等、重复目标、冲突赋值或最终缺字段均拒绝Start。
发牌在开局断言、信息通知及认知之前完成。`seed: fresh`每次Start生成私有种子，整数种子供重放。
完整时序与审计（研究仓路径：`docs/design_notes/AUTHOR_OPENING_DEALS_V1.md`）、
[阿瓦隆实例](examples/avalon_random.source.yaml)。
样本别名只在 then 结算中有效；菜单、输入、费用和行动时间不预知骰子。
同一 seed 与同一实际行动顺序重放一致，换 seed 可分叉。合法失败仍发布并支付声明费用。
费用、抽样、效果、报告与后继共用 Runtime 原子提交；准备选项不会消耗随机状态。

需要互不干扰的抽样时，可选择独立具名流：

```yaml
# Lib: name the finite selection type before using it.
values:
  ColdStream: {enum: [cold_alice, cold_bob]}
# Within a resolution, use a parameter or a typed constant:
resolve:
  draw:
    rolled: {type: DieRoll, sides: '20', stream: ColdStream.cold_alice}
  then: {result: rolled >= 10}
# Source:
random: {mechanism: replayable_seed, streams: [cold_alice, cold_bob]}
# Assets:
random: {seed: 13, streams: {cold_alice: 1, cold_bob: 2}}
```

省略 `stream` 时选择 `main`，其种子是 `random.seed`。每条其他流有独立状态、
种子与计数，逐个开局绑定；枚举的所有可能流必须在 Source 声明。
也可用具名文本参数接收 Source 固定绑定的流键；编译只读求出精确键并核选定池，
不接受 owner 状态或运行时开放文本。新增一条流不必修改这份泛型 Lib。
实际样本保留流名及该流的抽样序号。不同流同波可并存，同流仍需作者明确有序政策；
菜单、准备和未选分支不推进流。参见具名流合同（研究仓路径：`docs/design_notes/C0_RANDOM_STREAMS_M1_G8_V1.md`）。

    .venv/bin/python -m nomos_c0.python_codegen src/nomos_c0/author_abilities/examples/random_workshop.lib.yaml src/nomos_c0/author_abilities/examples/random_workshop.source.yaml build/python-codegen/random_workshop.py
    .venv/bin/python -m nomos_runtime build/python-codegen/random_workshop.py --assets src/nomos_c0/author_abilities/examples/random_workshop.assets.yaml --manual

输入 `1` 执行一次付费检定；`seat bob` 可让第二位人物使用同一规则。
这是[可运行的随机子项](examples/random_workshop.lib.yaml)，
随机已与形成、本地引用组合通过 C08；实际样本见下节。抽样合同（研究仓路径：`docs/design_notes/C0_AUTHORED_RANDOMNESS_G6_V1.md`）。

## 形成物件

```yaml
resolve:
  form:
    - type: Tool
      fields: {charge: '2', ready: 'True'}
  result: 'True'
```

先在 Lib 中声明 Tool，在 Source.objects 中选中它。字段使用普通表达式；
每个产品由 Runtime 分配独立身份和状态，失败分支省略 form 就不生成物件。
后继 Reaction 用 `on.bind: {made: {formed: Tool}}` 捕获这一次实际形成的引用集合，
可通过普通 disclosure 交付人物。指认许可与字段读取许可分开。

    .venv/bin/python -m nomos_c0.python_codegen src/nomos_c0/author_abilities/examples/formation_workshop.lib.yaml src/nomos_c0/author_abilities/examples/formation_workshop.source.yaml build/python-codegen/formation_workshop.py
    .venv/bin/python -m nomos_runtime build/python-codegen/formation_workshop.py --assets src/nomos_c0/author_abilities/examples/formation_workshop.assets.yaml --manual

[锻造样本](examples/formation_workshop.lib.yaml)保留一件开局工具；同一 Use 规则也适用于新工具。
默认 seed42 的前两次 Forge 分别失败、成功，人物各付一能量；成功时本人取得新工具引用。
`reference: projected` 需通过报告或投影得知，`reference: public` 是作者明确声明的全局身份公开政策。
形成不会向人物写入未声明的观察。完整合同（研究仓路径：`docs/design_notes/C0_AUTHORED_FORMATION_G6_V1.md`）。

## 形成人物

`form` 同样支持 `kind: person`。在 Source 的 `actor_kinds` 选定未来类型，
Assets 只列真实开局人物；出生后由 Runtime 分配独立 Actor 身份与状态。
`{formed: Creature}` 捕获本次实际形成的兼容人物，不预置未来席位。
Person 与 Object 均可显式 `extends` 同类别父类型，继承字段与读取合同，
父类型能力可作用于已选子类型，实际身份始终保留叶类型。

```yaml
actors: {alice: Worker, bob: Worker}
actor_kinds: [Spirit]
```

`session.actor_controllers()` 返回受信操作者的当前控制入口；
开局入口为 Source 名字，新生入口为该 Session 签出的 `ActorControl`。
控制入口可以读取本人、准备/提交能力、提出本地策略、取得调度机会与取消本人活动。
人物知识由报告和当前投影分别授予；控制入口清单不会写入任何玩家观察。

    .venv/bin/python -m nomos_c0.python_codegen src/nomos_c0/author_abilities/examples/actor_workshop.lib.yaml src/nomos_c0/author_abilities/examples/actor_workshop.source.yaml build/python-codegen/actor_workshop.py --ai src/nomos_c0/author_abilities/examples/actor_workshop.ai.yaml
    .venv/bin/python -m nomos_runtime build/python-codegen/actor_workshop.py --assets src/nomos_c0/author_abilities/examples/actor_workshop.assets.yaml --manual

输入 `1` 形成 Spirit，`controllers` 查看控制入口，`seat 3` 切到新生者，
`auto` 提交一次其本地提案。调度世界自动停在实际获得机会的人物，
新生者从出生时开始积累自己的行动值。容量由工程参数 `actors_per_type` 控制。
高级合同（研究仓路径：`docs/design_notes/C0_AUTHORED_ACTOR_FORMATION_G8_V1.md`）。

## 集合谓词

`exists(items, x => predicate)`、`forall(items, x => predicate)` 和
`exactly_one(items, x => predicate)` 都是独立 typed 表达式节点。
exactly_one 在第二个满足者出现时立即返回 false；没有展开成计数加比较的长式。
Set 按不同成员计数，Sequence 按每次出现计数；空集合的 exactly_one 为 false。
有一个满足者但其他成员判断失败时保留错误，不把未知当 false；
两个确定满足者已足以否定唯一性，与 Set 遍历顺序无关。

[M1 地图声明](examples/everflame/types.lib.yaml)用这个谓词检查路线键及恢复引用。

`distinct(sequence)` 显式取得不重复的成员 Set，Sequence 本身仍保留出现顺序和重复。
可将 `distinct(reports(offers))` 作为有限成员输入域；记录中有 Ref 时仍使用同一名义类型与识别许可。

## 最优元素

按分组保留最新记录时，使用：

```text
latest_by(messages, message => message.topic, message => message.turn)
```

输入为 Sequence；按完整名义键分组、取最大整数版本，保持所有并列项、重复与原顺序。
key/version 各求值一次，生成局部索引和两次线性遍历。
适合当前发言、修订记录等“每组最新版本”，比逐项嵌套 `not exists` 更直接。
撤回项应先参与选择，再由调用方排除，避免旧版本复活。
合同（研究仓路径：`docs/design_notes/GROUPED_LATEST_VALUES_V1.md`）。

```text
min_by(items, x => score)
min_by(items, x => score, x => tie_key)
max_by(items, x => score, x => tie_key)
```

输入为 Set 或 Sequence，评分和可选平局键均为整数；两个键按词典序取最小或最大。
返回 Optional<Element>，空集合返回 `None`，作者用显式分支处理。
Sequence 完全同键时保留第一项；Set 最优元素完全同键且不唯一时报告 `AmbiguousSelection`，
此时可声明能区分它们的平局键。键的读取仍遵守名义类型与本人权限。
独立执行节点每个元素每个键只求值一次，不展开成嵌套筛选，也不静默截断表达预算。
用于具名纯定义时，预声明 optional 返回类型，例如 `MaybeCard: {optional: Card}`。

[璀璨宝石 AI](examples/splendor/world.ai.yaml)的 `ai_target` 使用最小付款缺口＋牌ID选目标，
`ai_return_for_target` 处理没有目标的情况。合同与审计（研究仓路径：`docs/design_notes/TABLETOP_STRATEGY_SELECTION_V1.md`）。

## 多文件声明

记录列表可用作者数据表（研究仓路径：`docs/guides/AUTHOR_DATA_TABLES_V1.md`）共享列名。
`!table` 在文档读取层展开，保留真实单元格位置；所有字段仍交原有名义类型检查。

Lib 和 Source 都可用 `imports: [types.lib.yaml, rules.lib.yaml]` 选择相对路径模块。
模块使用与入口相同的 schema，命名声明合并，重名、重复导入或循环直接拒绝。
整体配置只声明一次；Source 的 objects/actor_kinds 清单可分文件追加，不允许重复。
Assets 保持独立；装配后的声明仍交给同一个 `compile_author_world`。

```python
from nomos_c0.author_abilities import compile_author_files

program = compile_author_files("world.lib.yaml", "world.source.yaml")
session = program.start(assets)
```

完整样本（研究仓路径：`docs/author_language/modules_g7/README.md`）把类型、规则、人物与能力选择分开，
现有 CLI 同时支持单文件和分文件项目。表达式来源保留模块文件及原行列。

## 本地策略

独立 `.ai.yaml` 的 strategies 声明有限候选评分，control 显式绑定到人物或类型。
世界 Lib/Source 不携带策略；同一 Program 可手动运行，或绑定不同的 ControllerPlan。
每项必须恰有 `actor`（开局名字）或 `kind`（名义类型）之一；
kind 同时覆盖已选兼容子类型及未来实例。一个人物可能匹配两条策略时编译拒绝。

也可在独立AI中声明`semantics`，以特征／先验／目标描述完整候选，交由经验估计器评价。
这一路不混用下述固定`score/minimum`；用法见候选语义（研究仓路径：`docs/guides/AUTHOR_CANDIDATE_SEMANTICS_V1.md`）。
可选`consideration: {per_ability: 6}`及逐规则`screen`／`diversify`先做本地廉价粗筛，
再构造入围者的完整语义；全部合法行动与真实提交准入保持，覆盖数量保存在候选帧中。
现有桌面仍选择固定评分配置；新的语义帧与实际选择端口由受信调用方显式使用。
`semantics.feedback`声明实际选择与本人收件的关联及解释，生成纯值函数；
调用`session.feedback_memory`得到带多项原始依据的样本，见反馈指南（研究仓路径：`docs/guides/EXPERIENTIAL_FEEDBACK_V1.md`）。
集合端口可声明类型化`related: {key, link, roots, depth}`，按收件引用定义候选范围；
普通`collect/where`仍表示整个封闭区间。投影、根的读域及深度由C0检查，
生成Python执行局部关联，原始收件与where的完整上下文保持。

```yaml
schema: nomos.author.ai
strategies:
  SpiritChoice:
    actor: {self: CreatureRef}
    candidates:
      - definition: Act
        guard: self.energy > 0
        priority: '0'
        score: self.energy
    minimum: '0'
    tie: canonical
    wait: no_candidate
control:
  spirits_choice: {kind: Spirit, definition: SpiritChoice}
```

```python
from nomos_c0.author_abilities.strategies import read_controllers
from nomos_c0.python_codegen import emit_world_module

controllers = read_controllers(checked, "world.ai.yaml")
python_source = emit_world_module(checked, controllers=controllers)
```

`checked`是作者编译计划。生成Python后由产物的`PROGRAM.start`启动；编译计划本身不提供运行Session。

固定评分候选按三层比较，而不是把流程控制伪装成极大分数：

1. `guard`是可选的`Bool`。为假时该完整候选不参加策略选择；它不修改世界的准入规则，手动控制者仍只能由真实 Action 的`where`决定是否合法。
2. `priority`是可选的整数，默认`0`。先选最高优先层；只要最高层大于`0`，该层代表当前必须处理的流程机会，`minimum`不把它静默丢弃。
3. `score`仍是同一优先层内的具名软偏好总和，受`minimum`与`tie`处理。人格、经验、信任和成本应该写在这里。

例如“已知绝非梅林者不能刺杀、确定梅林优先、其余目标按公开表现比较”可以写成：

```yaml
- definition: Assassinate
  guard: 'local_merlin_bounds(target).maximum > 0'
  priority: '1 if local_merlin_bounds(target).minimum > 0 else 0'
  score:
    公开表现: public_signal(target)
    发言线索: claim_signal(target)
```

`Session.proposal_score_frame`与`proposal_details`分别读回每个候选和最终提案的`priority`，供受信审计；
它不是作者可伪造的输入。语义候选帧已有独立的评价／选择合同，不能混用`score`、`guard`或`priority`。

AI 可另声明 `queries` 作为纯评分辅助，复用世界已有查询，但不能覆盖它们。
候选输入可用`inputs: {name: expression}`固定一个值，或用`choices: {name: set_expression}`
提供多个值；未指定的输入按世界合法域枚举。集合元素与输入类型一致，依赖顺序和本地读取受检。
例如`choices: {rationale: 'MaybeTeamArguments([None, TeamArgument.TestTeam()])'}`
保留两种表达供正式评价；空集只略过该策略分支，每个实际候选仍走世界准入。
同字段不能混用inputs与choices；typed-entry也可由两者之一显式提供。
候选集合合同（研究仓路径：`docs/design_notes/CANDIDATE_CHOICE_POOLS_V1.md`）说明预算与指纹。
可选 `predictors`／`rankings` 把冻结模型绑定到受检本地值，
`control.<name>.rankings` 为指定能力选择概率排名；见模型策略指南（研究仓路径：`docs/guides/AUTHOR_LEARNED_POLICY_V1.md`）。
编译评分仍检查 Actor-local 读取权限；策略不能声明世界效果或获取秘密。
例如阿瓦隆的[集合查询](examples/avalon_local_bounds.ai.yaml)由独立AI模块导入，
合并本人已取得的个人范围和名单补集；[角色评分](examples/avalon_local.ai.yaml)再消费该结果。
群组相交时不能直接相加人数下界，未完成或冲突的认知结果也不作为可靠范围使用。
[角色目标查询](examples/avalon_role_goals.ai.yaml)进一步区分破坏、信誉、隐蔽与关键任务，
刺杀只评价本人已获身份范围及公开行为；这些属于独立AI配置，世界结算规则可以保持原样。

固定风格通过已有`parameters`及`control.with`绑定。阿瓦隆的
[均衡](examples/avalon_local.ai.yaml)、[谨慎](examples/avalon_cautious.ai.yaml)、
[直率](examples/avalon_forthright.ai.yaml)三入口共用[策略主体](examples/avalon_policy.ai.yaml)，
只改变风险、隐蔽、发言、采信四项权重。可以按`actor`分别绑定，或按`kind`统一绑定；仍拒绝重叠控制。

策略与候选可声明类型化的本人说明：

```yaml
explain:
  information:
    本人体力: {type: Count, value: worker.energy}
  judgment:
    当前顾虑: {type: Score, value: concern(worker.energy)}
  motive:
    工作倾向: {type: Score, value: use_weight}
```

`type/value`必填，`when`可选且为布尔表达式；公共项与当前候选项合并最多24条、同类标题唯一。
固定评分策略在选出建议后计算一次；语义策略按需准备实际选择与领先备选的说明。
`proposal_details`返回当时快照，重复查看不评分、不发布行动。
类别组织作者说明，不产生新的事实保证；完整边界见说明快照合同（研究仓路径：`docs/design_notes/STRATEGY_EXPLANATION_SNAPSHOT_V1.md`）。

可选独立 `.cognition.yaml` 声明本人证据通道与软判断修订。
`read_cognition(program, path)` 绑定模型，`read_controllers(program, ai_path, cognition=model)`
编译策略对本人的 `views: {mind: {cognition: MindView}}` 导入；
评分使用 `cognition(mind)`。模型在开局/真实结算时修订，提案读取不写状态。
阿瓦隆的可组合表达（研究仓路径：`docs/guides/COMPOSABLE_DELIBERATION_V1.md`）用Record/Variant/Set、
纯查询及实际披露实现比较、条件立场、引用回应和转移话题。
这类领域表达优先放在作者Lib/独立AI；话题版本和引用检查显式声明，不为每句话增加C0关键字。
完整文件分工、来源/撤销和预算合同见心智指南（研究仓路径：`docs/guides/AUTHOR_COGNITION_V1.md`）。
控制配置绑定精确 Program，不能套到另一次编译的世界。

策略复用实际能力的命名输入和获准读取；同一能力的所有当前候选都可评分。
typed 自由输入须由策略显式提供表达式，其余有限域可枚举。
平局选择 wait 或 canonical；没有高于 minimum 的候选返回控制等待。

    decision = session.propose("alice")
    if decision.proposal is not None:
        result = session.submit_proposal("alice", decision.proposal)

评分不结算、不抽骰，也不推演隐藏结果。实际提交仍重新经 Runtime 准入。
`score` 可用具名整数表达式表声明分项；实际总分为其和，单表达式为一项得分。
`session.proposal_details(actor, proposal)` 读取同一签发提案的分项和命名输入副本，
不消费或重新评分；控制者、签发完整性与本人引用域继续受检。
具体语法及阿瓦隆发言回顾见评分解释合同（研究仓路径：`docs/design_notes/LOCAL_SCORE_EXPLANATIONS_AND_SOCIAL_CHOICE_V1.md`）。
旧提案可能被拒绝；跨局、跨人物、被改写或已消费的句柄不能提交。
过程决策用 definition 与 point 选定，各个实际待回应实例独立评分。

    .venv/bin/python -m nomos_c0.python_codegen src/nomos_c0/author_abilities/examples/local_workshop.lib.yaml src/nomos_c0/author_abilities/examples/local_workshop.source.yaml build/python-codegen/local_workshop.py --ai src/nomos_c0/author_abilities/examples/local_workshop.ai.yaml
    .venv/bin/python -m nomos_runtime build/python-codegen/local_workshop.py --assets src/nomos_c0/author_abilities/examples/local_workshop.assets.yaml --manual

输入 auto 只执行一次当前人物的策略提案；普通编号仍由玩家自主选择。
[策略源码](examples/local_workshop.ai.yaml)改变 use_weight 就能改变实际选择，
并可使用通过真实报告取得的新工具。合同（研究仓路径：`docs/design_notes/C0_LOCAL_STRATEGY_G7_V1.md`）。

## 默认玩家停点

有原生Actor调度的Source可显式选择：

```yaml
play: {mechanism: player_turn, player: adventurer, others: local_strategy}
```

自动推进前检查每位其他开局人物的本地策略，以及真实新生个体的kind策略覆盖。
这项检查属于控制配置，缺少 AI 不阻止世界本身编译或手动运行。
`session.drive_play(budget=64)` 自动提交NPC真实提案，到玩家实际机会返回 `ready`；
无候选/无正分/保守平局只交还机会。`closed` 来自作者世界终局，`idle` 来自原生无机会，
`rejected` 停止而不换动作重试，`budget` 保留合法前缀并允许显式继续，不是世界终局或行动总上限。
每个Action及后继闭包分别原子；多次自动行动不组成可整体撤回的事务。

CLI默认只展示所选玩家本地视图，`--manual` 显式进入受信多席调试。
未选择play的Source由受信控制者逐席操作。合同（研究仓路径：`docs/design_notes/C0_PLAYER_TURN_CONTROL_G8_V1.md`）。

若世界终局也需要同一个玩家，Lib用 `world_parameters: {player: BeingRef}` 声明固定世界角色，
Source.contexts实例的with绑定该开局符号，play引用 `player: {context: palace, parameter: player}`。
控制器与终局同源解析身份；Assets不提供该角色。world_parameters只进入World作用域，
不会向Actor输入域、where或评分提供隐藏引用，也不自动授予识别许可。


## Unit动作／反应的确定省写

普通`abilities`与`reactions`可省`results`，其含义固定为内置`Unit`；Unit发布叶可省`result: None`。仍须显式写`resolve`，例如`resolve: {}`表示发布无额外效果的Unit结果，并非没有发生动作。反应的`on.bind`省略时只补空捕获映射，definition／after和非空捕获仍显式声明。

编译前统一正规化，之后仍走原决策组、channel、类型和事务路径；已有完整写法继续有效。Bool／Count等非Unit结果不能省叶结果；省results却返回True同样拒绝，不从表达式猜类型。缺resolve、null／缺失分支和未知字段不被当作空动作。原始表达式来源保持，合成值就近定位到声明／resolve。

v1只覆盖普通能力与反应；periodic、activities／cancel及processes仍使用原有显式结果合同。没有运行期默认解释器或行为回退。


## 显式反应订阅组合

普通reaction的`on.definition`列表可以包含`{decision_group: Inspection}`，按组成员顺序展开允许的能力定义。Source只有显式写`after: {declared: true}`时，才按允许定义顺序选择同context实例中唯一已选的普通能力／反应实例。每个定义都必须恰好命中一个；缺失、重名、组重叠均拒绝，不静默省略或去重。

```yaml
# Lib
on: {definition: [CloseDay, LockWolfVote, {decision_group: Inspection}, Protect]}
# Source.use.night_ready
after: {declared: true}
```

原`after: alias`／`after: [aliases]`仍可表达部分订阅、多实例及原来允许的跨context接线；没有opt-in就不会自动补订阅。无context的反应只自动匹配无context来源；别的context不被自动接入。绑定展开之后仍检查捕获类型、循环、因果与结算，Runtime不增加调度器或解释分支。

`compile_author_world`的可选`source_context`只携带Source诊断位置；文件编译与AuthorPrograms自动传入，独立于Lib上下文。新接线错误报告Source.after、Lib声明与候选实例原位置。静态绑定预览只说明选择结果，不替代完整C0检查。


## 显式行动报告集合

Source可声明集合，让增加同组同标签选项不再需要修改Python汇总：

```yaml
report_collections:
  inspections:
    type: Inspection
    channels: [{decision_group: Inspection, context: match, label: sighting}]
  notices:
    type: NightNotice
    channels: [night_ready.notice]
```

组选择要求同context实例中每个成员恰有一个选定实例；没有该投递标签的Skip等成员不贡献通道。
未知／歧义／空集合／重叠来源或不同名义类型拒绝。相同类型的其他报告不会自动加入。
集合只覆盖行动投递历史，不接入开局information或实时projection，也不改变投递和引用权限。
`session.report_collection(actor, "inspections")`返回acquired与原生values；
`session.wire(actor, reference=...).reports("inspections")`按声明类型编码成列表。
只读本人实际收到的已提交报告，按原收件流顺序返回，保留重复投递；不按通道拼接或按轮次排序。
新增同组同标签选项只改能力定义、组成员与Source实例；应用仍自行决定对外字段名。


## 显式公共作者作用域

Lib与Source各自声明`scopes`，每个使用点写`scope: name`，只展开引用的声明：

```yaml
# Lib（片段）
scopes:
  informed:
    context: Match
    actor: {player: PlayerRef}
    views: {identity: {reports: RoleReports}}
abilities:
  Protect:
    scope: informed
    # 输入、资格、epoch和结果仍显式声明
# Source（片段，作用域名不自动关联Lib）
scopes:
  informed: {context: match, views: {identity: own_role}}
use:
  protect: {definition: Protect, scope: informed}
```

Lib的context指已声明schema，Source的context指选定实例。Lib scope的actor／views仅用于
abilities与decision_groups；其他可执行类别只支持context作用域。Source scope只含context／views。
没有scope就不继承，不猜唯一context，不自动接入私人报告；所有视图仍检查名义类型、精确绑定和本人权限。
局部views可补充不同别名；重名拒绝。同一context／actor可重复明确声明，但不同值报冲突。
换环境／角色或重绑视图时选择另一scope或完整局部声明，不静默覆盖。
作用域不嵌套或继承；空／未知／不适用字段拒绝。scope可经imports共享，重名仍报错。

C0先展开作用域，再执行Unit正规化、决策组、订阅与既有检查；Runtime没有作用域解释器。
组成员仍不能覆盖组共享actor／context。源码映射保留scope原文件位置，组的二次展开继续解析到原物理路径。
不含诊断位置的生成代码与完整声明一致；实际文件产物保留不同SourceSpan路径、摘要及行号。


## 可弃权的单值选择域

`optional_choices(pool, allow_none)`把Set<T>转换为Set<Optional<T>>，保留全部候选，
仅在显式Bool条件为True时加None。T不能已经是Optional或Unit；Sequence也不接受。
输入仍声明既有Optional名义类型，wire仍传单个Ref或None，不改为集合：

```yaml
target:
  type: GuardTarget
  choose: 'optional_choices(filter(players, p => p.alive and p != player), True)'
```

作者继续声明禁自保／连保等目标规则及弃权条件。可读的空pool在条件True时只提供None；
投影不可用仍报原错误，不把不可读取的域当成空集合。局部输入依赖、名义类型、引用许可、
准备后重核和预算仍走原路径。C0展开为已有集合／条件节点，不增加Runtime操作。
GuardTarget及原GuardTargets名义导出保持；药水subset仍是集合，不自动改写为单个可选目标。

## 具名参数化能力实例集合

Source的`ability_sets`集中声明普通能力实例，成员沿用Lib的typed `parameters`与Source的`with`。

```yaml
ability_sets:
  Attacks:
    context: battle
    members:
      strike: {definition: Melee, with: {ap_fee: 1, power: 2}}
      heavy: {definition: Melee, with: {ap_fee: 2, power: 4}}
use:
  shield: {definition: ConsumeShield, context: battle, after: {ability_set: Attacks}}
report_collections:
  hits: {type: Hit, channels: [{ability_set: Attacks, label: hit}]}
```

集合只含可选context与非空members；成员只写definition／with／views，别名全局唯一，
不允许嵌套、隐式继承或局部覆盖context。context省略表示无context，不猜唯一实例。
成员展开为普通use，参数、Actor本人视图、决策组与许可照常检查。
集合本身不新增共享次数或互斥规则；机会仍由Lib决策组明确声明。
反应选择器只用于普通Reaction，要求同一context；可用`only: [strike]`选择非空唯一子集，
或在after列表混用显式别名与集合选择器。未列入集合的同definition实例不会被吸收。
报告选择器要求每个选中成员都有label通道且名义类型相符，仍只汇总本人实际取得的收件，
不改变收件顺序。after／channels重叠均拒绝；旧declared和decision_group唯一实例规则保持。
集合与选择器各有131072项展开上限，超额报错，不截断。只在C0展开，不引入运行时集合或新IR。
完整边界见设计合同（研究仓路径：`docs/design_notes/AUTHOR_ABILITY_SETS_V1.md`）。
