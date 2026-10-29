# 生成世界运行库

运行 C0 构建好的 Python 规则；Assets 独立提供每局初态。
规则正文是生成函数，公共库负责身份、事务、控制、来源及信息边界。

正式Subject可通过`bind_subject(..., planning=world.PLANNING)`显式选择
单步有界规划（研究仓路径：`docs/guides/SUBJECT_PLANNING_V1.md`）。本人正式记忆引导参数构造，
原经验估计器按需评价完整行动，原Participation权限发布Action与Choice并继续取得真实反馈。
纯预测持有捕获的本地读值；提交复核当前世界。显式导出的ControllerLibrary.planning由
公共SubjectGroup选择；`Participation.choose`及TableControl让配方和普通有限能力
共用一次搜索、累计预算及原经验估值，见统一构造（研究仓路径：`docs/design_notes/SUBJECT_DEFAULT_CONSTRUCTION_V1.md`）。
同一Subject后继参与可召回已结束visit的抽象反馈；原始报告引导只来自本局，
跨局个人target经验仍按原Context隔离。`contrast`提供全部／仅本局／空经验的只读对照。

表达式预算由[expressions.py](expressions.py)执行。C0可把受证明的直线访问段生成到
`ExpressionBudget.visit_block`：成功时一次增加原逻辑步数，低预算按原点顺序给出同一诊断。
这项优化不跨过读取、运算、调用或控制流；`steps`与物理`visit`调用次数分别计量。
规划另计当前实际Work：同帧成功查询保留原Source重放与深度约束，
跳过正文只支付已执行前缀和查表费用；成功集合前缀可供中断后的后继准备复用。
累计账本不退款，缓存不跨捕获reads／Actor／ValueLimits／实参身份，
见查询计费（研究仓路径：`docs/design_notes/PLANNING_QUERY_WORK_ACCOUNTING_V1.md`）。

`ReferenceDomain.require`逐次检查身份、类型和许可；同类型accepts直接返回，不创建层级遍历容器。
`ReadContext.checked_input/checked_construct`另核当前schema条目快照，映射内替换也失效；
可变身份／许可容器不共享整值证明。见审计与验证（研究仓路径：`docs/closure_notes/REFERENCE_MEMBERSHIP_PROOFS_V1.md`）。
当前域派生共享私有复制的只读开局符号表及其内部身份标记，每次仍从当前states重建引用集合、
检查开局符号存续与许可子集；实时投影、公开字段和Actor当前权限不缓存。
替换symbols后重新复制；旧域不随外部映射变化，不把可变映射当作只读证明。

## 构建与运行

在仓库根安装项目后：

```bash
python -m nomos_c0.python_codegen \
  src/nomos_c0/author_abilities/examples/everflame/world.lib.yaml \
  src/nomos_c0/author_abilities/examples/everflame/world.source.yaml \
  build/python-codegen/everflame.py \
  --ai src/nomos_c0/author_abilities/examples/everflame/world.ai.yaml
python -m nomos_runtime build/python-codegen/everflame.py \
  --assets src/nomos_c0/author_abilities/examples/everflame/world.assets.yaml
```

生成器与运行库的调用约定由生成ABI（研究仓路径：`docs/design_notes/GENERATED_ARTIFACT_ABI_V1.md`）标识；
无标记或不匹配的旧产物在执行前拒收，应从原声明重新编译。

构建完成后可移动 `.py` 和 Assets；运行需要本库、Pyrsistent、文档加载用的PyYAML
及产物实际选择的纯认知依赖。项目安装会自动安装声明的依赖。
规则改变后重新构建；开局改变只需另选 Assets。产物是受信 Python，应确认来源后运行。

选择开局发牌时，Assets省略发牌提供的实体字段；Start先完成分配，再检查初态和发出身份通知。
`random: {seed: fresh}`每局产生私有种子；指定整数可重放。受信`session.inspect_opening()`返回
不可变的初始化来源、分配和随机流记录，普通玩家视图只取得作者许可的信息。

## 有类型的wire消费

已有Session可直接提交JSON形态数据，不必每个作品再手写一遍字段解码。例如warming样例：

```python
wire = session.wire("traveler")
options = wire.choices("touch", limit=256)
result = wire.act("touch", {"gate": {"object": "gate"}})
```

`act`返回原生ActionResult，保留AdmissionError、ValueBindingError和执行缺陷；不会统一转成False。
`choices`只列当前Actor获准的完整有限输入，支持依赖成员、子集和序列；typed无限输入需用
`prefix={"limit": 2}`明确提供。额度计入构造路径，超额或不能有限枚举时抛ChoiceEnumerationError，
不会把截断列表当完整菜单。空域及不可能的序列长度直接结束，巨大长度在创建迭代器前受值预算约束。

应用需要布尔／空列表协议时，可显式调用`wire.try_act(...)`与`wire.available_choices(...)`。
前者按发布状态返回True／False，反馈False仍算已发布；仅指定的准入拒绝和非预算值绑定错误转False。
后者仅把指定的不可用准入错误转空菜单。ValueBudget、执行缺陷及无法完整枚举的错误均透传，
原生方法保持。完整错误码见消费合同（研究仓路径：`docs/design_notes/AUTHOR_REJECTION_CONSUMERS_V1.md`）。

默认引用仍为`{actor: name}`／`{object: name}`。应用可给`session.wire`传入`reference(ref)`编码回调
及`resolve_reference(wire, nominal_sort)`解码回调，修改引用表示；ValueCodec始终重核当前身份和许可。
仅编码格式由回调负责，不允许它把外局或未获准引用变为合法输入。与Session一样，这些操作是单writer。

## 终端操作

- 选择当前能力编号，按命名输入选成员；子集/顺序输入使用空格分隔编号，空集合可直接回车。
- typed 输入填写 YAML 值，引用使用 `{actor: 名字}` 或 `{object: 名字}`；输入错误可重新填写。
- `q` 退出或取消正在填写的输入，取消不发布 Action。
- `auto` 让当前人物按已编译的独立策略提出并提交一次选择。
- `wait` 交还调度机会；没有人物调度的时间世界可用 `wait 时刻` 推进至最近边界。
- M1 默认停在作者声明的冒险者；NPC 由 `drive_play` 按本人策略推进。
- `--manual` 开启受信作者调试；`seat 名字` 切换开局人物，`controllers` 与 `seat 编号` 可选新生人物。
- 桌游默认使用固定本人视角与 TableControl；`coordinate` 取得当前共同决策的电脑回应。

读取显示只包含本人的字段、公开共享状态、许可投影和实际取得的报告。
玩家 `Session.project` 的世界侧求值失败返回 `ProjectionFailed`，不输出内部表达式诊断；
受信开发工具可用 `project_value` 核对原始错误。读取失败不发布行动，也不标记结算 fatal。
当前输入表单只读；完整提交重新检查当前资格。付费失败仍显示真实结果。
终局按作者规则显示结算并退出。电脑预算停点由 `continue` 明确恢复。
结算缺陷退出码4；加载/开局错误为2，运行输出故障为3。
已提交后显示失败保留真实世界，不重试行动。

## 代码地图

| 入口 | 责任 |
| --- | --- |
| [artifacts.py](artifacts.py) | 精确加载生成 PROGRAM/CONTROLLERS/DISPLAY，执行前检查生成ABI |
| [artifact_format.py](artifact_format.py) | 生成调用约定版本及字面量标记检查，缺失或不匹配要求重新编译 |
| [world.py](world.py) | 独立 Start、会话控制、准备/提交与原子发布 |
| [initialization.py](initialization.py) | 校验单次开局的 Assets、分配身份、解码实体／共享／随机初态；同类实体只复用本次字段描述，逐个解码实际值 |
| [actions.py](actions.py) | 编译规则定义、准入、准备句柄与行动结果 |
| [information.py](information.py) | 开局信息、结算收件生成与当前可见引用；行动、事件波和到期路径直接调用同一交付函数，收件由原事务发布 |
| [records.py](records.py) | 实际发生、交付、epoch、时间与有序结算来源记录 |
| [effects.py](effects.py) | 事务内写入草稿、形成、抽样与效果预算，不自行发布 |
| [errors.py](errors.py) | 准入拒绝、控制拒绝与结算缺陷的统一类型 |
| [report_inputs.py](report_inputs.py) | 按本人、来源、通道与过程起点筛选报告输入，普通报告的成功格式检查仅在精确批次内复用；生成器直接调用 |
| [local_inputs.py](local_inputs.py) | 本人开局／交付／获准终局输入、稳定身份与增量游标 |
| [processes.py](processes.py) | 同一不可变ProcessStore维护完整历史与活动位置；请求／清理只查活动流程 |
| [ordering.py](ordering.py) | 运行值的稳定本地排序，供候选、终端与显示共用 |
| [candidates.py](candidates.py) | 编译控制合同、当前策略选择及统一的有限合法候选枚举 |
| [consideration.py](consideration.py) | Actor本地粗筛、稳定分组多样性及实际考虑覆盖 |
| [decisions.py](decisions.py) | 受检候选语义帧、过期检查及真实发布的本人选择 |
| [choices.py](choices.py)、[values.py](values.py) | 当前表单与生成名义编解码 |
| [play.py](play.py) | 玩家机会、桌面轮转和共同决策 |
| [terminal.py](terminal.py)、[__main__.py](__main__.py) | 通用终端与显式产物入口 |
| [presentation.py](presentation.py) | 本人显示帧、授权引用与输入提示 |
| [cognition.py](cognition.py)、[analysis.py](analysis.py) | 本人实际依据、生成模型接入与原子认知检查点 |
| [strategies.py](strategies.py) | 直接评分、预测检查、选中候选说明快照与本人提案签发 |
| [participation.py](participation.py) | 主体开局绑定、记忆同步、经验评价及真实选择记录 |
| [planning.py](planning.py) | 生成确定性能力的本地纯快照、逐步规划与真实单步提交 |
| [scenario_planning.py](scenario_planning.py) | 独立有限假设模型、本人报告捕获、一致过滤和条件重规划 |
| [planning_bindings.py](planning_bindings.py) | 前缀成员域与索引、集合草稿逐人增加／完成，不预展开组合 |
| [planning_construction.py](planning_construction.py) | 记录／变体／集合的逐步纯值构造，完整后交原能力准入 |
| [planning_preparation.py](planning_preparation.py) | 同捕获帧的纯表达式准备、成员规范域与对象身份隔离 |
| [planning_appraisal.py](planning_appraisal.py) | 正式主体的纯Candidate解释／经验估值，按阶段记录累计Work |
| [planning_continuation.py](planning_continuation.py) | 由真实本地输入判断窗口、等待与完成；同一累计预算恢复实际单步选择 |
| [planning_recall.py](planning_recall.py) | 正式Actor收件的局内只读Memory／Recall与来源，不修改Subject生命周期 |
| [feedback_index.py](feedback_index.py) | 原Session／精确样本追加前缀绑定的检查点；不可变索引结构共享与失败隔离 |
| [subject_audit.py](subject_audit.py) | 已提交决定的惰性序列，持冷回忆引用及小型元数据，按需复原原评分与规划解释 |
| [subject_repository.py](subject_repository.py) | 受管主体的独占、显式保存、只读检查点、局间恢复与关闭 |
| [artifact_binding.py](artifact_binding.py) | 实际加载工件、配置及执行依赖内容匹配 |
| [subject_values.py](subject_values.py) | 封闭审计／参与值编码，历史引用不转换成新局身份 |

产物注册从实际加载的源码字节解析静态import根，遍历所有语句作用域（含未执行分支、函数／类、异常和match分支），只跳过不可能包含import语句的表达式内部。源码摘要与实际代码指纹仍完整计算；完整内容绑定还会重核当前运行库等依赖，不跨版本复用静态import扫描结果。

生成器直接导入各职责模块；`world`不转发已移出的类型，`temporal`／`settlement`
不转发已归入`records`的来源类型。升级后重新生成主线产物，冻结发行与原运行库配套。
错误类型、记录与草稿可独立导入，不依赖Session装配；可选算法和实际执行组件仍按需加载。
根事务、前态共读、有序步骤、预算及权限合同保持，未增加执行层或通用缓存。

`session.planning_problem(actor, world.PLANNING, goal)`从本人所需可读字段捕获纯值，
`advance`只搜索生成模型，`submit`仍调用正式Action入口；`refresh`按实际读回保留累计额度。
首片为non-canon钥匙题（研究仓路径：`docs/author_language/planning_t1/README.md`），
支持范围、模型假设和失败处理见指南（研究仓路径：`docs/guides/GENERATED_LOCAL_PLANNING_V1.md`）。

`candidates`提供同一条表单／实际准入枚举路径：直接评分策略和经验评价帧均消费它。
生成控制合同也由该模块持有；它不依赖评分提案模块或纯认知算法。
终端、显示及分析直接使用`ordering.canonical`，排序不加载策略执行。
该键保留值的名义形状，以sort／ordinal稳定排列局内引用；它不是跨局身份认证或工具传输codec。
`strategies`不转发已迁出的合同、枚举或排序入口；当前生成产物随接口变更重编译。
帧发行、实际提交与主体同步各自的快照／过期边界保持原处，不合成通用缓存。

`session.cognition(actor)` 返回当前名义判断值；`session.explain_cognition(actor)` 返回其实际依据、
条件推导和有限/局部分析摘要。两者均只读已提交检查点，不因查看而重新求解。
桌面说明共用本人显示帧的引用编码，其他人物的判断不进入当前玩家时间线。
通用算法位于 `nomos_cognition`；世界读取、接收者授权和事务边界留在运行库。
收到的可靠依据先核验，再构建有限分析输入；输入集合超预算时，保留已核验依据和截止位置，
分析标记为 pending，不沿用上一份完整结论。普通发言仍只影响其声明的软判断。

局部人数分析在完成实际收件核验和归一化后，通过[local_calculation.py](local_calculation.py)
复用本Session内相同的纯传播。键包含全部带类型的Context／Term／Ground、输入与查询顺序、
实际剩余Limits及算法函数；bool／int不同。每次仍按原Result.work计入逻辑预算，
重新构建当前cutoff、发布值及类型检查。最多保留8位holder各自最新的小型完整结果，
键超过4096节点／65536字符／64层或结果超过1024个bound时重新计算；pending／conflict不保留。
这些上限仅约束内部复用内存，不改变作者预算或结果。新Session初始化为空，未用局部分析时不加载该机制。

`session.proposal_details(actor, proposal)` 读取签发提案时保存的评分与 typed 说明快照。
固定评分策略在选定候选后求值其说明；重复查看不重新执行评分或说明回调。
说明按 information/judgment/motive 分类，保持本人的读取权限和签发时刻取值；
它不自动产生公开发言或新的可靠依据。正式 `submit_proposal` 仍重新检查当前准入。
生成产物须与当前运行库接口配套，升级后重新构建产物。

`session.table_control(player, record_decisions=True)`可选记录电脑实际提交的策略快照。
`control.decisions`返回不可变记录元组，包含actor、实际Action ref、能力、评分分项和原typed说明。
拒绝／失败的提交不写入；默认关闭，查看建议和手动行动不自动冒充策略执行。
记录与该控制器同寿命，属于受信诊断数据；共享桌面仅在显式选用认知复盘的真实终局后编码展示。
读取记录不再次执行策略，其他人物的说明不加入局中玩家过程流。

## 工具值边界

独立AI选择`semantics`时，`session.candidate_frame(actor)`取得所选考虑政策的受检候选。
默认完整；显式选择`consideration`后先做廉价screen／diversify，再精评各Action／机会的入围项。
`frame.consideration`记录枚举与入围数量；`exhaustive=True`供显式完整核查，世界合法域不变。
纯评价器只读取帧内Model／Candidate值；`submit_candidate(actor, frame, key)`核对原帧、
当前世界与正式准入，成功后在本人输入中保存`choice`及原始发生来源。
帧不运行固定评分，也不在估计失败时回退旧策略；详见候选语义指南（研究仓路径：`docs/guides/AUTHOR_CANDIDATE_SEMANTICS_V1.md`）。
`candidate_details(actor, frame, key)`读取单项说明；`candidate_frame_details(actor, frame)`一次读取整帧。
两者先完整核验原Session签发、Actor归属和帧语义，再按原基准延迟准备说明与反馈背景；
整帧读取只做一次完整核验，返回按实际候选键组织的新字典和独立输入映射；
说明作为一份完整报告深复制，保留报告内共享值，再次读取建立独立副本。
已准备的旧帧详情仍描述该次捕获；未准备部分过时后拒绝展开，实际提交另核当前世界与正式准入。

Participation在实际提交成功时记录全部入围候选的实际参数与评分对应键及考虑覆盖，
详细判断有界保留各类前两项及实际选择。赛后可比较全部目标，不重算历史心理。
经验调整的呈现按冻结估计的原分母分摊，各段之和等于总调整；
这属于估计的算术解释，逐消息的因果归因需另有证据。

生成的语义`prepare`是私有工厂，返回screen与describe两个阶段；describe只构造选择前必需语义，
另持有反馈metadata与说明的独立延迟函数。每帧按能力规则／具体机会建立一次，
本地环境及成功纯表达式结果在该作用域复用，随帧释放。
实际选择前准备自身说明与metadata，各类领先备选只准备说明，避免对未选项封存反馈背景。
帧构造期间状态／收件／限额变化会拒绝发行；另一个Actor、请求或帧重新建立读取范围。
该内部ABI采用当前生成格式，旧工件应重编译；实际候选准入与提交检查不使用这些缓存。

候选枚举的完整选择由实际准入返回所有绑定值，不再重复构造完整表单；
部分选择仍通过表单解析依赖与可选域。语义评价器的ReadContext可在该短命范围复用
精确验证器／输入对象／值限额／引用许可集合的成功名义检查，普通Action执行不启用。
失败、计算结果及实际owned读取保持检查，缓存不跨Actor／机会／帧。

候选枚举和单次`available_abilities`扫描的`information.candidate_input_batch`同时管理已获身份提取与
[普通收件格式检查](report_inputs.py)。精确快照、validator、接收者及来源相同的reports
通过`report_inputs.checked_reports`复用成功值；Actor当前权限与每个候选的真实准入仍执行。
实时投影／认知／process-point收件不参加共享，批次外实际读取；旧scope名已删除。
生成器直接消费 `report_inputs`，Session 不再保留三个内部报告输入方法；已有生成产物需重新编译。
玩家的 `report`、`reports` 和 `report_collection` 接口保持。
可用行动列表返回或报错后释放该扫描批次并恢复外层；后续扫描重新建立，当前投影与准入仍逐项检查。

同一批次还由[input_proofs.py](input_proofs.py)复用`cache_inputs=True`读取上下文的成功名义输入验证。
每个ReadContext继续建立当前引用域；快照、reader、schema、模式、Actor、validator、输入对象、
精确ValueLimits、当前引用／许可集合与符号映射共同限制复用。schema对象替换会失效，失败不保存。
命中路径直接核对原schema条目并复用只读符号标记，避免每次分配两组元数据元组及重复查表。
最多保留256项，正常／异常退出后清空并关闭；脱离的读取快照不携带该批次。
构造结果仍使用各ReadContext原有的独立范围，字段读取、视图与行动条件继续实际求值。

同一发生和渠道可显式交付多项值。认知按共同Evidence收齐后一次消费，
不同主题分别修订，同一规则／slot按收件顺序保留最后一项，重读不强化证据。
逐项收件仍完整保存在本人历史中；见复合发言与共同证据（研究仓路径：`docs/design_notes/COMPOUND_PUBLIC_SPEECH_V1.md`）。

`session.local_inputs(actor, after=cursor, limit=128)`按本人顺序读取不可变输入：
开局收件、实际Action／Event交付与获准终局结果。来源和before／after采样原样保留，
游标严格绑定当前Session／Actor；重读保持身份，失败根不追加输入。
该端口随世界成功发布暂存并提交，读取本身不运行学习。
详见本人输入指南（研究仓路径：`docs/guides/ACTOR_LOCAL_INPUTS_V1.md`）。

`session.feedback_memory(actor, memory, checkpoint=None, budget=None)`按选定AI的受检政策，
用本人真实选择和后来实际收件形成多依据样本；重放幂等、缺结果保持pending。
它返回纯记忆更新值，不发布主体状态或改变世界；异常不重执行已发生行动。
反馈端口可显式选择已绑定终局，以本人实际获准终局结果评价此前选择；普通消息继续精确关联。
中断不当作失败，同一终局共享计权。内部FeedbackPort包含必需的kind与relation槽，生成工件须重编译。
原始输入、解释样本、摘要及共享证据计权见反馈指南（研究仓路径：`docs/guides/EXPERIENTIAL_FEEDBACK_V1.md`）。
唯一收件端口按原名义Term关联键建立有序索引；增量检查点绑定原Session／Actor、
Program／ControllerLibrary、策略、值限额、原Episode序列及精确样本追加谱系，
后继仅编码新收件并更新受影响trial；同一前缀的冷热表示变化不失效检查点。
查找仍排除选择之前的消息并拒绝迟到多重匹配；内部256条分页不限制总历史量。
普通集合端口逐项检查原封闭区间；显式`related`集合按受检key／link建立局部反向索引，
在每层原区间内从roots查找，保留实际输入身份、顺序及where的完整区间上下文。
投影只覆盖实际查询窗口并集，空roots惰性跳过；共享键包含名义类型、限额和依赖。
关联集合投影不跨调用；唯一收件索引经受检检查点在原输入流内继续，错误时旧索引不变。
见历史与计算限制（研究仓路径：`docs/design_notes/HISTORY_GROWTH_AND_COMPUTATION_LIMITS_V1.md`）。

Session历史发生记录的默认总容量为None；`settlement_occurrences=10000`单独约束一次根因果结算，
旧历史长度不消耗该额度。`processes`只计未结束流程，完成流程的来源与步骤仍保留。
显式历史总容量、表达式／值大小、活动实体和待到期等限制仍可按用途配置。

`session.bind_subject(actor, Subject(personality=...), goals=...)`登记进程内主体的单一开局参与。
返回的Participation通过`propose/submit`评价并提交，通过`sync`原子更新记忆／游标／待反馈记录，
通过`finish/interrupt`同步后结束参与。处理错误保留旧检查点，重试不再执行世界Action。
同一已加载Program／AI profile的新Session可继续绑定该主体；用法及控制边界（研究仓路径：`docs/guides/COGNITIVE_PARTICIPATION_V1.md`）。
主体通过`nomos_cognition.storage`归档新增后缀；磁盘失败保留精确待发布草稿，
成功重试后再消费新收件。当前索引、样本和摘要保持热驻留，
样本／经验旧修订及已提交决策解释按需读取。
临时目录随最后一项主体／快照／审计持有释放而清理，不作为跨进程身份恢复入口。
另可通过`subject_repository.SubjectRepository`受管保存／续接主体；
`create`取得独占身份，显式`save`原子发布，`close`关闭旧writer，`open`只续接最新head。
重开检查完整工件／执行内容并重建当前热状态，旧scope、审计和来源保持；
详见保存指南（研究仓路径：`docs/guides/SUBJECT_REPOSITORY_V1.md`）。
`subject.decisions`保留跨参与的有序轻量审计目录，`visit.decisions`只包含本次参与。
`subject_values.py`对完整审计元数据使用封闭值编码，历史Reference保留原scope，
按调用者提供的工件校验名义值；受管仓库另核完整内容绑定，纯审计读回不恢复Subject或控制票据。
成功`finish/interrupt`后，Participation只保留冻结快照、参与元数据和冷审计，
解除Session／Subject运行引用并撤销旧writer；原Session中的该Actor仍保持关闭绑定。
同步失败则保留原绑定重试。外部保留的Session／规划flow不由此接口强制释放。
主体可显式配置`EpsilonGreedy`探索；先评价全部入围项，再按稳定候选顺序抽样，实际提交仍走原准入。
抽样trace随真正发布的主体决策保存，原最高分依据不改写；重试不刷新抽样、不消耗世界骰子。

`ParticipationDecision.timing`分别记录反馈同步、候选构造、经验召回、估计与选择的毫秒数，
以及本次候选／召回样本数。`TableControl.timings`保留实际电脑提交的分段；
共享桌面的`computation.decision_phases_ms`只交付累计时间，不交付他人候选或私有样本数。
`timing.construction`及桌面的`computation.candidate_stages_ms`另列枚举、准备、语义、
筛选、关联／捕获、说明与核验；它们属于候选段的内部细分，不能与外层时间重复相加。
延迟的关联／捕获与说明在实际查询或提交阶段计时，不计为已经完成的候选段工作。
固定真实前缀的诊断方法见决策剖析（研究仓路径：`docs/guides/AVALON_DECISION_PROFILING_V1.md`）。

`session.values(actor).decode(name, wire)` 和 `.encode(name, value)` 使用生成的名义编解码函数，
在本人的当前身份域内工作。运行值是不可变 Python 值；工具数据保留作者字段和 Variant 标签。
自定义 reference 回调只改变引用的传输表示，实际个体与读取权限仍由 Session 核对。

`ValueLimits` 分别限制结构深度、节点、集合大小及 `wire_bytes`（默认 1 MiB）。
整份工具数据按紧凑 UTF-8 JSON 计字节，包含键、转义和标点；输出共用预算时累计计算。
循环、非封闭数据、非法 Unicode 或超预算产生具名 `ValueBindingError`，不截断内容。
这些检查位于工具输入/输出边界，不进入每条世界算术表达式。

当前范围见CURRENT（研究仓路径：`docs/CURRENT.md`），本轮职责拆分与验证见
运行库整理（研究仓路径：`docs/closure_notes/RUNTIME_CODE_ORGANIZATION_V1.md`）及
候选／策略整理（研究仓路径：`docs/closure_notes/CANDIDATE_RUNTIME_ORGANIZATION_V1.md`）。


显式行动报告集合由生成Program携带不可变的类型／通道元数据。
`session.report_collection(actor, name)`在原收件流上过滤本人已获得的选定通道，返回acquired与原生values；
`session.wire(actor, reference=...).reports(name)`按集合类型编码列表，沿用本人当前引用权限与逐值预算。
开局report、单通道reports与实时project保持各自接口。集合不投递信息，不重排、不去重、不扩大身份域，
未知集合报UnknownInformation；同Program的新Session不共享收件。


`session.inspect_snapshot()`组合十项已有受信诊断：state、contexts、acquisitions、opening、
history、terminal、processes、pending、individuals、random。返回原生值字典；外层及状态／context／
random容器与现场分离，记录沿用已有不可变值，读取不提交行动或投递信息。单writer读取期间没有额外锁或缓存。
这是常用诊断集合，不是整局完整状态、存档／恢复或跨版本稳定的序列化格式；其他inspect接口仍独立可用。
玩家继续使用read／report(s)／project／ending，公共wire不加入受信诊断。应用自行选择诊断格式，例如：

```python
return {name: repr(value) for name, value in session.inspect_snapshot().items()}
```
