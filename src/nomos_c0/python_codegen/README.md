# Python 代码生成

C0 的生成后端。当前已有纯表达式/查询、**行动 → 因果 Event → 本人报告**、多步决策、阶段/窗口和世界终局。
共享桌面、T0、作者调试 CLI 与可移动桌游包已消费生成 Session；编译前端也已解除 K0 导入依赖。
旧K0、解释执行链及其私有协议入口已退役。当前任务与已返回证据见现行索引（研究仓路径：`docs/CURRENT.md`）。

世界产物携带生成ABI（研究仓路径：`docs/design_notes/GENERATED_ARTIFACT_ABI_V1.md`）字面量版本，Runtime加载时核对。
CLI在写入前保护所有作者输入及imports路径，输出／优化报告不能与输入或彼此重合。

## 作者与编译器的分工

可选`compile_planning`与`emit_world_module(..., planning=plan)`从已选确定性能力生成
独立纯预测函数，并将`PLANNING`绑定同一实际`PROGRAM`。
`subject_planning=True`或CLI的`--subject-planning Model.yaml`显式选择受检原子机会声明
（`compile_opportunity_planning`／`nomos.author.opportunity_planning`），
生成ControllerLibrary对同一PLANNING的引用。Unit目标／观察及Bool完成标志由编译器生成；
真实骰子、时间和due继续在实际事务内执行，见合同（研究仓路径：`docs/design_notes/OPPORTUNITY_PLANNING_V1.md`）。
显式配方与[编译器生成的有限参数绑定](subject_binding.py)在默认电脑选择中共用一次搜索与预算，
后者只捕获本人可读输入，不展开整张菜单，见
统一构造合同（研究仓路径：`docs/design_notes/SUBJECT_DEFAULT_CONSTRUCTION_V1.md`）。
独立模型导出与控制选择分开，见桌面接入合同（研究仓路径：`docs/design_notes/SUBJECT_PLANNING_TABLE_CONTROL_V1.md`）。
输入域、where、效果与结果复用原受检规则及表达式后端，见
T1真实单步指南（研究仓路径：`docs/guides/GENERATED_LOCAL_PLANNING_V1.md`）。
`compile_scenario_planning`选择独立主观模型，生成本地报告捕获与值输入预测函数，
使用同一个`PLANNING`／`Session.planning_problem`入口，见
T2报告与条件处置（研究仓路径：`docs/guides/SCENARIO_PLANNING_FEEDBACK_V1.md`）。
该后端也生成既有subset输入的逐成员构造接口，绑定原公开投影／开局报告，见
A1真实提队（研究仓路径：`docs/author_language/planning_a1/README.md`）。
可选`guidance`再生成受检priority函数及原报告codec，接入局内只读Memory／Recall后排序生成。
`construct`为已有typed输入生成纯结构化构造配方与名义carrier，通用运行库逐字段／逐项细化，
表达式仍是生成Python函数，见结构化发言（研究仓路径：`docs/guides/STRUCTURED_PLANNING_CONSTRUCTION_V1.md`）。
可选`continuation`生成纯值窗口检查，与本地捕获一起运行；已有实际能力处理发言／让过／表决，
见观察续行（研究仓路径：`docs/guides/OBSERVED_PLANNING_CONTINUATION_V1.md`）。

作者语言的目标是声明可组合的世界规则，由 C0 分析依赖并完成接线。
算术和条件沿用熟悉的表达式写法，Python 是执行目标。
后续工作的重点是自动装配能力、效果、因果和信息通路，而不是扩展一门通用编程语言。

用现有 `queries` 声明校准最基础的依赖生成，例如：

```yaml
queries:
  remaining:
    parameters: {lamp: Lamp}
    returns: Charge
    expression: current(lamp) - 1
  current:
    parameters: {lamp: Lamp}
    returns: Charge
    expression: lamp.flame.charges
```

编译 `remaining(lamp)` 时，生成器自动收集 `current`，生成共享的名义值类型及两个实际函数。
声明可以倒置，公共依赖只生成一次；未选中的查询不进入产物。
缺失引用、循环、类型或读取权限错误继续由现行前端检查。
世界组合继续使用相同的表达式生成器，规则的参数捕获、订阅、效果和交付由 C0 接线。
本地行动菜单和候选表单只生成所需Actor读取上下文，避免建立未使用的world上下文；
当前可见域、参数类型、输入依赖、条件和预算继续实际检查，正式准入与执行仍保留所需世界读取。

## 代码路径

优化维护入口见阶段／证明地图（研究仓路径：`docs/guides/COMPILER_OPTIMIZATION_MAINTENANCE_V1.md`）。
[proofs.py](proofs.py)统一实际值证明及函数／分支／binder寿命；
[pipeline.py](pipeline.py)统一七项AST后处理的实际顺序、前置条件与报告。
表达式生成器只消费这些接口，测试与测量直接消融对应所有者。

```text
当前语法/类型检查 -> CheckedValueExpression -> 纯查询控制块／共享计划
                         ↓
emit_expression_module -> Python AST -> 可导入 .py
                         ↓
evaluate(values) -> 直接算术/if/字段/函数调用 -> 原始不可变值
```

- [expressions.py](expressions.py)：遍历编译期依赖、生成正文、短路分支和来源位置；if／match所有结果均有精确名义证明时省去汇合后复检，match binder只继承已检查subject的证明。
- [budget_blocks.py](budget_blocks.py)：对生成函数做直线块分析，只跨已定义局部复制／literal合并预算访问；调用、字段读取、运算和控制流是边界。成功一次扣原步数，低预算按原点定位，优化报告列出实际合并项。
- [local_budget.py](local_budget.py)：块合并／复制传播后，证明整函数预算不逃逸，缓存局部steps／限额并内联正式访问判断；私有查询和保留访问调用前发布／finally读回，函数finally发布成功或失败步数。小直线叶函数保留原方式，公开输入与预算构造检查不移动。

  该pass仍完整扫描当前区域做所有权检查；通过后只复制并改写含`_budget`引用的祖先路径，共享子节点保留各次出现的父路径，list字段也独立复制，其余子树保留。未选中时丢弃候选树，不修改原AST。新增改写规则须保持“改写点含字面`_budget`名字”的选择前提，不能把路径剪枝用于省略安全扫描。
- [limit_guards.py](limit_guards.py)：相同不变形参上，只删除已有成功内在类型守卫支配的重复守卫；首次检查、分支／异常与完整预算保持，局部重绑定／名称遮蔽拒绝改写。
- [correlated_sum_plan.py](../correlated_sum_plan.py)与[correlated_sum.py](correlated_sum.py)：把受检嵌套sum_by的相等键／0回退转为按键sum和短路前缀计数；支持有限纯query路径链，实际数据路径与各原callee费用分开，所有层参数（含后继未使用者）仍须有证明。内层空池可直接生成0并补原固定费用，其他少量数据或低资源走原生成循环。字段／词法池分析与grouped-latest共用[query_fields.py](../query_fields.py)。
- [local_copies.py](local_copies.py)：预算块生成后，对查询／表达式函数传播确定已绑定的局部名字，删除无读取的私有临时复制／literal赋值；字段读取、调用、运算及检查留在原处。分支取共同别名，循环／异常／模式绑定保守失效；不作一般死存储消除或记录标量替换。
- [query_plan.py](../query_plan.py)：生成前分析控制块、稳定值编号和成功查询的支配关系；[query_reuse.py](query_reuse.py)把共享组编成直接局部值，逻辑预算和失败位置保留。
- [expression_analysis.py](../expression_analysis.py)：一次编译内共享正文依赖、失败与资源界，查询共享消费其深度界；已验证输入且无传递外部读取时，证明Bool／Unit／无界整数的fresh scalar检查恒通过，省去validator与ValueBudget分配，原位置保留限额参数类型拒绝。参数／记录字段还由`checked_operands`核对实际词法证明；raw本地绑定不因类型声明而省检。[optimization_report.py](../optimization_report.py)收集作者位置及生成决策。
- [integer_ranges.py](../integer_ranges.py)：从实际分支和原生整数运算求保守范围；区间落在声明域内且操作数已检查时，省去恒通过的窄整数参数／结果检查。expected标注不充当区间证明，未知范围保留检查。
- [query_inline.py](../query_inline.py)：选择不读取外界、不物化值的短标量叶查询及纯call转发层，转发实参不含query／循环；在原调用点生成正文，参数／必要返回检查和逻辑访问顺序保持，已有共享组优先，逐层展开仍计入同一函数名额。复杂callee保持直接调用，不扩递归图。
- [query_plan.py](../query_plan.py)与[query_reuse.py](query_reuse.py)：按支配关系复用查询；对只依赖函数参数／名义字段／常量的较重纯查询另选循环首次使用缓存，不提前跨空循环／分支。原参数／返回检查、逻辑费用和低资源诊断保持；临时名与全局查询名称互斥。
- [loop_query_memo.py](../loop_query_memo.py)与[loop_query_memo.py](loop_query_memo.py)：固定复杂参数、按少量变化标量／引用键复用本次函数调用内返回的纯查询正文；保留所有参数／返回边界及精确逻辑费用。有限留存／键大小只决定是否复用；最外层Set完整元素键已知不重复时不建memo。
- [record_projection.py](../record_projection.py)：以编译器字段局部值替代非逃逸临时carrier；字段按原序求值，已证明标量且结构限额足够时省去恒通过检查。复杂字段在world中保留受检构造复用，返回／整体比较等逃逸仍构造，展开受单函数名额限制。
- [record_parameters.py](../record_parameters.py)：沿纯查询图分析非逃逸record参数及其字段需求，生成一份字段参数签名；转交只传实际使用字段，人物读权限仍按原始参数索引。私有查询ABI由编译器统一生成，公开表达式入口不变；测试／测量工具的ABI解码不参与生产执行。
- [variant_query_plan.py](../variant_query_plan.py)与[variant_queries.py](variant_queries.py)：识别查询直接match参数的常量case，在全部参数检查后以精确carrier查表；常量case省去调用和逐case匹配，原三次预算visit与必要返回检查保留，活动case仍调用原函数。
- [grouped_latest_plan.py](../grouped_latest_plan.py)与[grouped_latest.py](grouped_latest.py)：识别同一Sequence的严格同键较新反存在查询，按版本／位置分组，保留顺序、并列与精确虚拟步数；计数消费不构造结果集合。
- [finite.py](finite.py)：生成量词短路、排名和集合/序列操作；有输入证明时把筛选计数融合成单循环。
  map／distinct／union／concat／append通过实际元素来源与原结构检查组合结果证明，
  省去后继重复名义遍历；保留生产循环、元素首次检查与全部结构预算。
  append的实际插入合同若较推导元素更宽，则不能借用旧范围省检。
- [values.py](values.py)：统一类型注册、命名、不可变record与辅助函数注册表；编译期合同键可复用已检查结构值的等价检查，保留全部原生约束／容器层级及enum／Ref／record／variant名义身份，不改变作者类型身份。
  [nominal.py](nominal.py)生成正式校验、结构预算和构造；[codecs.py](codecs.py)生成编解码；
  [references.py](references.py)生成引用提取；共用[syntax.py](syntax.py)的AST构造原语。
  引用提取另消费既有`ValueType.has_references`：无引用子树不扫描，直接引用集合不逐元素包装，
  record字段直接合并引用；名义验证和当前`ReferenceDomain.require`保留。
- [value_budget.py](value_budget.py)：在正式生成nominal／shape／codec边界内联ValueBudget节点访问，保留同次序计数／限额／失败及所有类型／引用核验。正式预算与已绑定纯参数是前提；未知参数不重排。物理方法次数不再等于逻辑结构节点数。
- [scalar_checks.py](scalar_checks.py)：在复合validator内部有界展开Bool／Unit／Int／Enum叶检查，保留原路径、节点顺序与错误；引用、文本和codec返回另按原函数核验，不把名义检查整体删去。
  结构shape另内联六种标量／引用叶的原始结构预算，原字段参数仍先求值，再求路径和检查；
  不把shape当作名义／权限证明，报告与正式标量内联分开计数。
- [world.py](world.py)：生成已选 Action、Reaction 和 Disclosure 的实际函数，并提供 `emit_world_module` 入口；收集待链接表达式与精确证明元数据，不再保存当前函数的输入绑定状态。
- [input_bindings.py](input_bindings.py)：每个生成函数独立创建 InputBindings，负责输入域、名义检查、派生值、绑定证明及初始行动环境。菜单、eligibility、admit、策略、显示和Subject绑定使用各自作用域；过程world捕获不成为Actor输入证明。运行时仍逐次重建权限，不共享准入结果。
- [costs.py](costs.py)：生成当前资源可负担性检查与Draft内扣费；准入与执行分别求值，不跨准备／提交复用余额。
- [resolution.py](resolution.py)：生成随机节点、条件／携带尝试分支、叶效果／形成／过程转移及批量交付；统一管理临时编号和披露定义登记。行动、事件、due与取消共用同一生成器，实际发布仍由Runtime事务负责。
- [fixed_values.py](fixed_values.py)：从受检类型表和固定参数生成名义值构造；默认值、策略、调度、规划等直接共用，不依赖 WorldEmitter 的可变收集状态。
- [module_linking.py](module_linking.py)：按既有顺序链接规则、认知、规划、显示、运行时导入及 Program 导出，最后修复 AST 位置。内部 `WorldEmitter.module/fixed` 已删除，调用者使用实际所有者；作者仍使用 `emit_world_module`。
- [information.py](information.py)：生成静态共享参数、当前投影、开局信息与行动本地读函数。
- [report_inputs.py](../../nomos_runtime/report_inputs.py)：普通reports生成到受检读取入口；同次候选枚举内按精确来源／快照复用格式检查，当前Actor权限与准入保持，动态投影／认知／过程筛选另行读取。
- [assurances.py](assurances.py)：生成facts、私有约束实现/分类检查及公开保证记录。
- [carrying.py](carrying.py)：生成携带查询及拿取/放下/提议/接受的实际条件、效果与付费分支。
- [提议运行设施](../../nomos_runtime/carrying.py)：保存私有转交提议、发生依据与管理字段不变量。
- [形成运行设施](../../nomos_runtime/formation.py)：事务内分配实体的独立身份、容量和实际生成来源。
- [人物控制句柄](../../nomos_runtime/controllers.py)：选择本局实际Actor的受信控制权，与世界引用和知识分开。
- [随机运行设施](../../nomos_runtime/randomness.py)：显式种子、独立流、受限骰子/洗牌及实际采样记录，与字段效果同事务。
- [结算运行设施](../../nomos_runtime/settlement.py)：普通阶段共读前态，作者显式有序步骤逐阶段重读，先排空子闭包再继续父步骤。
- [temporal.py](temporal.py)：生成活动开始捕获、完成、取消及周期回调，正文为直接Python。
- [时间运行设施](../../nomos_runtime/temporal.py)：最近到期跃迁、实际到期身份/续期与整次推进原子发布。
- [scheduling.py](scheduling.py)：生成自有字段的速度/资格投影及准入后的前态行动成本。
- [调度运行设施](../../nomos_runtime/scheduling.py)：余债、当前机会、控制等待及Actor-first的到期阶段。
- [保证运行设施](../../nomos_runtime/assurances.py)：读取本人已取得的保证和采样来源，保留历史而不重新求值。
- [control.py](control.py)：生成过程接口元数据与终局判断正文；决策效果与next分支由world生成。
- [choices.py](choices.py)：生成当前本地能力条件、依赖输入域和部分输入校验。
- [选项接口](../../nomos_runtime/choices.py)：核对控制门并返回不可变输入描述，供后续桌面/策略消费。
- [strategies.py](strategies.py)：生成独立AI配置的供值、评分项及纯查询调用。
- [候选执行计划](../evaluation_plan.py)：Compile时记录纯节点、输入／信息依赖、批次／候选生命周期和原始使用点，合并同一描述作用域内的等价根。
- [调用方输入证明](../expression_entry_proofs.py)：将单次Actor准备路径的精确绑定传给条件／输入域／约束／派生入口，只消除必成功的输入检查；保留上下文、controller、结果及预算，公开表达式及world捕获不借用。
- [evaluation.py](evaluation.py)：消费计划生成专用懒求值函数；批次节点共享单值，候选节点按精确所需输入分组，原始分支与诊断位置保留。
- [frame_queries.py](frame_queries.py)：识别候选语义中传递重复、返回来源已证明的纯record及含迭代集合／int／bool查询；同一prepared rule内按实际操作数身份共享成功正文。参数与返回检查保留，复用重放Source费用，原Source／深度不足时走原正文诊断。外部读取查询不参与，下一帧重新计算。
  表达式临时step限额不进入值键，每次命中仍核已保存cost与当前depth；Work分片变化不会自行打散共享。
  局部query共用／循环memo也遵守Source与实际Work分账（研究仓路径：`docs/design_notes/LOCAL_QUERY_EXECUTION_WORK_V1.md`）：
  访问先付元数据费用，成功命中只重放Source；相同函数之外不延长局部缓存寿命。
- [候选设施](../../nomos_runtime/candidates.py)：控制合同、当前策略选择和有界真实候选，供直接评分与经验帧共用。
- [策略设施](../../nomos_runtime/strategies.py)：直接评分、预测检查、去重/平局与封存提议；当前提交仍走Session准入。
- [cognition.py](cognition.py)：生成独立认知修订、prior视图、条件/each/结论函数。
- [cognition_terms.py](cognition_terms.py)：生成接到纯算法的专用名义term编解码，不在Run解释类型IR。
- [analysis.py](analysis.py)：生成受保证输入、有限变量/公式/query、局部规范化和类别函数。
- [认知设施](../../nomos_runtime/cognition.py)：本人实际证据、受限身份、预算和同根原子发布。
- [play.py](play.py)：生成已有控制机制及潜在新生人物的策略覆盖要求。
- [控制设施](../../nomos_runtime/play.py)：玩家机会停点、固定席位轮转、预算和共同决策协调。
- [过程设施](../../nomos_runtime/processes.py)：实际请求/访问、捕获及按本次过程隔离的报告。
- [终局设施](../../nomos_runtime/terminals.py)：开局/稳定根终局、冻结与排空；不解释作者表达式。
- [信息运行设施](../../nomos_runtime/information.py)：初始化开局报告并构造当前可指认域；值内引用由专用生成函数提取。
- [共享运行设施](../../nomos_runtime/world.py)：局内身份、候选字段修改、因果波次及原子发布；表达式诊断和计数单独保留。
  生成规则直接引用[actions](../../nomos_runtime/actions.py)、[effects](../../nomos_runtime/effects.py)、
  [records](../../nomos_runtime/records.py)与[errors](../../nomos_runtime/errors.py)的实际所有者；
  `world`不转发这些类型。运行库升级后重建主线产物，冻结发行保持其配套运行库。
- 具名测试（研究仓路径：`tests/nomos_c0/test_python_codegen_expressions_v1.py`）：真实导入、反例、规则编辑及隔离进程。
- 世界组合测试（研究仓路径：`tests/nomos_c0/test_python_codegen_world_v1.py`）：独立 Start、当前准入、原子失败、采样/接收和隔离运行。

编译器开发入口：

候选语义的生成路径为`ControllerPlan.evaluations -> EvaluationEmitter -> Python`。
生成产物的`CANDIDATE_EVALUATION_PLANS`保存可检查摘要；Runtime直接执行已生成函数。
候选计划节点粒度为完整受检表达式；查询内部另有支配共享和
集合块证明（研究仓路径：`docs/design_notes/COLLECTION_BLOCK_PROOFS_V1.md`），共同消除重复正文、遍历与深检。
跨规则共享及一般循环融合仍需各自的依赖、错误顺序与预算证明。

生成CLI可用`--optimization-report build/optimization.md`输出Markdown报告。
Python API使用`from nomos_c0.optimization_report import OptimizationReport`创建收集器，
传给`emit_world_module(..., report=report)`或`emit_expression_module(..., report=report)`后，
可检查`report.functions`／`report.remarks`或调用`report.render()`。
每次生成使用新的收集器；报告开关不改变生成代码。
YAML标量锚点与解码后表达式坐标分开显示，折叠文本不伪装为精确字符定位。
内联不增加作者配置：每个叶正文最多24个节点，每个生成函数最多增加96个正文节点。
内联仍生成原正文的预算访问和来源；除零、空序列选择等失败不被提前执行或省略。
变量和字面量直接作为操作数使用，不生成额外复制局部变量，其预算访问保留。
真正逃逸的记录／集合保留实际构造与检查；内部临时记录由专门的字段／参数分析选择性消除，
保留字段求值及失败先后，不凭“内部值”一词任意删除。

```python
from nomos_c0.python_codegen import emit_expression_module

python_source = emit_expression_module(checked_expression)
```

`checked_expression` 来自现行 `compile_value_expression`；生成期间不运行查询正文。
模块可导入后调用 `evaluate`，record 值通过模块的 `construct(name, fields)` 创建。
每份产物自带一致的名义值定义，返回值不再包成旧 K0/C0 载体。

## 生成一个真实世界

沿用 warming 的现有声明（研究仓路径：`docs/author_language/reactions_g2/warming.lib.yaml`）：

```bash
mkdir -p build/python-codegen
PYTHONPATH=src .venv/bin/python -m nomos_c0.python_codegen \
  docs/author_language/reactions_g2/warming.lib.yaml \
  docs/author_language/reactions_g2/warming.source.yaml \
  build/python-codegen/warming.py
```

命令只生成 `.py`，不开局、不绑定本局 Assets。也可在编译期调用
`emit_world_module(compile_author_world(lib, source))`。
将产物所在目录加入 Python 导入路径后：

```python
import warming
from pathlib import Path
from nomos_runtime.documents import read_data

assets = read_data(Path("docs/author_language/reactions_g2/warming.assets.yaml"))
session = warming.start(assets)
gate = dict(session.symbols)["gate"]
result = session.act("traveler", "touch", {"gate": gate})
assert result.feedback is False
assert session.read("traveler")["energy"] == 2
assert session.reports("traveler", "tell.notice")["values"] == [True]
```

上例的文档读取器仅负责 YAML；隔离测试改用标准库 JSON 加载同一份数据，
Run 时只留下生成文件和 `nomos_runtime`，阻断 C0/K0 后仍得到相同的三项发生和私有报告。
现有 warming 内容是 non-canon 能力样本。

生成文件包含 `_action_*_admit/execute`、`_reaction_*`、`_disclosure_*` 及专用表达式函数。
例如扣费成为实际 Python 减法再提交候选字段修改；Reaction 条件成为实际分支。
运行库按编译好的来源订阅分发函数，不持有或解释规则 AST。
模块的 `PROGRAM` 可反复 Start；每局拥有独立身份、状态和报告。

`read/reports` 是按席位的本地读取；`history/acquisitions/inspect_state` 是受信诊断接口。
这片仍采用现行的受信单线程手动席位控制，Python 进程本身不作为不可信代码沙箱。
`prepare` 不运行世界正文；`submit` 重验当前资格和费用。合法结果 `False` 仍扣费并发布。
因果波次共享前态，重叠实际字段写入拒绝；任一后继缺陷使状态、发生和报告整根回滚，Session fatal。

## 已有与下一步

首片支持常量、输入、算术/比较、短路条件、record 字段/构造、variant 构造、
optional、集合字面量/成员判断，以及传递的纯查询调用。
随后加入筛选、量词、排名及集合/序列操作，共47项纯值/查询规范化操作；
`known/entity_field/local_view/relation` 在世界生成中另行支持，合计51项。
中间集合的结构预算与最终命名类型绑定分开；临时结果无需先声明类型，正式边界仍严格检查。
边界保留严格 bool/int 区分、值范围、结构容量、逻辑步数/深度和作者位置诊断。
预算检查计量声明的逻辑工作，不需要运行时遍历 IR。

名义类型证明沿已检查输入的字段、集合元素及`match`分支绑定传递。
循环／量词／排名中的纯查询不再重走同一元素的整棵记录；嵌套与同名绑定按实际生成局部变量隔离。
计算产生的集合、算术窄化及构造值仍在原有边界检查；证明不赋予Actor自身读取权限，
查询返回值和逻辑步骤／深度检查保留。参见元素证明交付（研究仓路径：`docs/closure_notes/CHECKED_ELEMENT_PROOFS_V1.md`）。

普通生成产物使用 Python 标准库、`nomos_runtime`及其Pyrsistent依赖；
选择认知时另需 `nomos_cognition`。独立部署应安装声明的运行依赖。
隔离进程阻断整个 `nomos_c0` 和
`nomos_kernel` 后仍可运行。共享桌面入口已切换；整体旧链退役以
执行账（研究仓路径：`docs/coordination/PYTHON_RUNTIME_AND_AVALON_PLAY_GOAL_V1.md`）逐项证据为准。

世界片已生成局内名义 Ref、`known`、受控实体字段读取、五种命名输入、
本人资源扣费、直接目标字段效果、有限无环 Reaction 和前/后态私有交付。
声明的 nominal 子类保留自己的身份与字段。报告接收者为空时不求值正文。

`when/then/else` resolution 编成实际 `if/else`，只执行被选中的结果、效果与交付。
prepare不提前求值世界分支；submit按当前前态重新选择。
嵌套的 `for/in/effects` 编成实际循环，具有独立局部绑定，空组不产生效果。
组内所有右值、后续筛选及结果读取同一前态，不按书写次序改成就地更新。
重复实际字段写入（包含组与费用重叠）整根回滚；每个发生分别限制组展开工作量。

可直接生成现有模块化通行声明（研究仓路径：`docs/author_language/modules_g7/passage.lib.yaml`）：

```bash
PYTHONPATH=src .venv/bin/python -m nomos_c0.python_codegen \
  docs/author_language/modules_g7/workshop.lib.yaml \
  docs/author_language/modules_g7/workshop.source.yaml \
  build/python-codegen/passage.py
```

它读取同一通路的真实 `passable`，发布 `Moved` 或 `Blocked`；两条分支都是真实付费行动。
无需改写原有规则。成组写入与分支交付的更多例子见具名测试（研究仓路径：`tests/nomos_c0/test_python_codegen_effect_groups_v1.py`）。
本批交付记录（研究仓路径：`docs/closure_notes/PYTHON_CODEGEN_BRANCHES_AND_GROUPS_V1.md`）列出语义与证据。

## 有限选择与完整输入

现行输入声明直接生成域检查和绑定代码，例如：

```yaml
inputs:
  order:
    type: PersonOrder
    choose: {sequence: team, length: 'size(team)', repetition: forbid}
  team:
    type: People
    choose: {subset: 'filter(known(Person), p => p.awake)', min: 1, max: limit}
  limit: {type: Count, enter: typed}
```

编译器按依赖顺序绑定 `limit → team → order`，不要求作者按执行顺序写声明。
每项先计算当前域和人数边界，再核对不可变的输入值；所有约束在完整绑定后检查。
prepare 不发布效果；submit 重新读取当前状态，已失效的成员、人数或顺序拒绝且零写入。
Set 用 `frozenset`，Sequence 用 `tuple`；不同局引用、错 sort 和可变载体仍拒绝。

`exists/forall/exactly_one` 生成短路循环，分别在见证、反例、第二匹配出现时停止。
只有部分谓词的 `InvalidValue` 可延后；没有决定性结果时报告原错误，预算错误立即传播。
`min_by/max_by` 每个候选的排名键只计算一次；空容器返回 None，Sequence 平局保留首项，
Set 的最优项平局要求作者提供可区分的 tie key，否则报告 `AmbiguousSelection`。
`distinct/union/difference` 和 `at/append/concat/index_of/take/drop` 也生成直接 Python。

完整数量分配使用普通 record 输入加纯查询约束。现有波多黎各 `valid_allocation`
无需改写即可生成实际函数，核对成员唯一、容量及总数守恒；合法分配一次 Action 原子写入。
这不引入另一套 allocation 执行器，也不声称波多黎各整局已迁移。
测试和当前限制见本片交付（研究仓路径：`docs/closure_notes/PYTHON_CODEGEN_FINITE_SELECTION_V1.md`）。

## 当前可见与实际获知

信息组合的范围和验证见交付（研究仓路径：`docs/closure_notes/PYTHON_CODEGEN_INFORMATION_V1.md`）。

`projections` 每次按当前状态重算；`information` 在 Start 时按接收资格实际交付一次。
两者都生成实际 Python 函数。静态 `contexts` 参数与 `opening_domain` 绑定每局引用，
全部 `require_opening` 先通过才开始交付；开局失败不会返回部分就绪的 Session。

现有换身份样例（研究仓路径：`docs/author_language/information_c/swap.lib.yaml`）可直接生成：

```bash
PYTHONPATH=src .venv/bin/python -m nomos_c0.python_codegen \
  docs/author_language/information_c/swap.lib.yaml \
  docs/author_language/information_c/swap.source.yaml \
  build/python-codegen/swap.py
```

原作者规则中的 `reports(identity)` 决定本人有无换身份能力，`projected(roster)` 提供当前目标池。
编译器装配这些依赖；世界中的身份真正交换后，各人的开局角色报告仍保留旧内容。
同类的阿瓦隆候选信息与花火手牌样例也能生成，尚无 Action 的纯信息世界可以正常 Start。

运行接口分别为：

```python
session.project("a", "Roster")    # 当前投影：available + value
session.report("a", "OwnRole")    # 开局报告：acquired + value
session.reports("a", "Swap.budget")  # 运行交付：acquired + values
```

这些值使用生成模块的原始不可变载体，和其他生成表达式/行动接口一致。
空报告是“已取得空内容”，与未取得分开；重读不重复交付。
行动按原声明用 `reports/projected` 读取本人信息，单表达式内只采样一次，跨表达式和新状态重算。
submit重新核对当前投影/目标身份，过时准备不授予永久访问权。

`reference: projected` 的实体仅在当前投影或已收到报告授予引用后才可指认。
静态参数中的全量目录不自动开放给玩家。取得引用只赋予指认资格，字段读取仍按 view/public 检查。
报告嵌套record、variant、optional、Set/Sequence中的引用由生成的专用函数提取。
当前投影消失可撤去该依据；实际报告保留当时内容与引用。后继失败回滚费用、交付及身份依据。
`known(actor, sort)`供调用方核对本人当前可指认域；`opening_acquisitions()`与`acquisitions()`是受信诊断接口，
分别查看开局与运行交付，不向其他Actor提供全知日志。

## 可写共享状态

`contexts` 可声明类型化共享字段，Source选实例，Assets给初值：

```yaml
contexts:
  Counter:
    parameters: {members: Players, increment: Count}
    state:
      fields: {count: Count, factor: Count}
      public: [count]
```

绑定此context的行动可在准入中读取count，结算正文可按声明读取factor并写`set(count, ...)`。
编译器分别生成本地绑定与世界绑定，秘密字段不能用于玩家输入/where/费用。
`world_parameters` 只进入世界结算绑定；普通参数保持只读。
context参数和字段不会进入发生记录的参与者列表，参与者仍是实际actor、形参和命名输入。

共享字段与实体字段使用同一候选快照与字段修改事务。所有右值读本次发生的共同前态，
Action后的Event重绑定当前共享值；普通同波Event共读前态，分离字段可合并，重叠字段fatal回滚。
类型错误、展开预算或后继缺陷同样撤销费用、人物/物件/共享状态、报告和发生记录。
`read_context(actor, name)`只返回public字段；`inspect_contexts()`是受信诊断。
public共享字段中的引用授予当前指认依据，秘密字段中的引用不授予；撤回后提交重验。

共享存储使用内部ContextKey，不是人物/物件、没有额外局内个体身份。
两次Start和两个同类context实例隔离；所有开局字段必须匹配声明，通过require_opening后才交付开局信息。
require_opening只检查开局，不是持续不变量。

完整的作者样例（研究仓路径：`docs/author_language/shared_state_python/README.md`）可直接生成并运行。
同一Lib/Assets只改Source的increment，真实计数从`1→2→4`变为`1→3→6`；
开局报告仍是1，旁边的独立context仍是7。
范围及验证见本片交付（研究仓路径：`docs/closure_notes/PYTHON_CODEGEN_SHARED_STATE_V1.md`）。

## 多步选择与世界终局

现有请求/回复（研究仓路径：`docs/author_language/process_d/request.lib.yaml`）、
检查后选择（研究仓路径：`docs/author_language/process_d/reveal.lib.yaml`）与
阈值终局（研究仓路径：`docs/author_language/process_d/terminal.lib.yaml`）声明可以原样生成：

```bash
PYTHONPATH=src .venv/bin/python -m nomos_c0.python_codegen \
  docs/author_language/process_d/request.lib.yaml \
  docs/author_language/process_d/request.source.yaml \
  build/python-codegen/request.py
```

用同名Assets开局后，实际控制接口为：

```python
session.act("a", "Ask", {"recipient": dict(session.symbols)["b"]})
opportunity = session.requests("b")[0]
question = session.decision_reports("b", opportunity)["question"]
session.reply("b", opportunity, {"answer": "refuse"})
reply = session.reports("a", "Ask.reply.response")["values"][0]
assert reply.answer == "refuse"
```

每个选择点生成实际准入/执行函数，`next`生成Python赋值；运行设施保存已发生步骤及当前位置，
不会自行选择答案。prepare接受`request=opportunity`，submit重验当前请求、本人资格和输入。
过时/伪造/跨局/错席请求拒绝；本次内部缺陷回滚本次提交，已发布前缀与其费用保留。

`from: begin.question`只读本过程该访问中的实际交付。多个请求和循环访问互不串报告，
循环重入按前端计算的重置点清理本轮来源；公开历史报告仍保留。
分支汇合仅保留所有路径共有的捕获。前人私有捕获可用于世界后果，不自动变成本人的已知引用或输入。

`ending(actor)`给出active/draining/closed及本人获准的不可变结算值。
终局when/value/to各生成实际函数，只在开局或整根因果闭包完成后调用：
途中满足又撤回不会触发，最终Event满足则按其后态结束。
`action/freeze`关闭后保留待处理前缀，拒绝更多行动；
`processes/complete_existing`锁定当时已有过程，只允许其真实选择继续，全部完成后才计算最终值。
触发锁存不因后来条件变假而撤回；过程finish、没有选项或耗尽预算均不替代世界终局。

开局结束使用OpeningBasis，不伪造Action；运行结束用CheckpointBasis关联实际root/tip。
`inspect_processes/inspect_terminal`是受信诊断，不是玩家私态读取、跨进程认证或存档协议。
过程位置、终局、实体/共享值、报告与发生记录共同提交或回滚。
`SessionLimits.processes`限制整局发起次数，完成记录仍保留；到限拒绝新发起，已有回应不受此容量阻断。
它是显式资源预算，当前无GC、时钟或自动结束。

阶段/窗口、epoch和调度已由后续片接入；现行游戏/CLI/T0尚未切换。
新ABI须重新生成产物，无旧签名fallback。验证见控制迁移交付（研究仓路径：`docs/closure_notes/PYTHON_CODEGEN_CONTROL_V1.md`）。

## 阶段约束与多人回应

原阶段（研究仓路径：`docs/author_language/process_d/stage.lib.yaml`）与
窗口（研究仓路径：`docs/author_language/process_d/window.lib.yaml`）声明直接生成，作者文件无须改变：

```bash
PYTHONPATH=src .venv/bin/python -m nomos_c0.python_codegen \
  docs/author_language/process_d/window.lib.yaml \
  docs/author_language/process_d/window.source.yaml \
  build/python-codegen/window.py
```

`stage.actors`在发起时捕获实际参与者，持有至过程完成；这些人可继续本过程选择，
其他行动暂不可提交，未参与的人照常行动。同一实际人物的多个名称只占一个位置。
已存在的其他请求只是暂时受阻，解除阶段后可继续同一有效访问。

`complete_when`生成实际Python，只在真正进入finish时读取本次费用/效果后的候选状态，
遵守当前选择者的字段权限，不读取刚交付的报告。false返回StageIncomplete、零写入且可重试；
类型/表达式/报告或后继错误仍使当前根fatal回滚。prepare不提前运行世界正文，submit才求值。
阶段义务不改变字段类型范围，因此临时超额可保留，归还后再完成。

`window.participants`使用已捕获的非空、互异人物名单；空名单或重复成员在进入窗口时正常拒绝。
`independent`用Set让剩余成员各答一次，`declared`用Sequence按序答一次。
回应次序不借宿主遍历顺序决定；尚未回应者持有的prepare在别人回应后仍有效，提交时重验当前条件。
部分回应保留本轮basis和当前位置，最后一项实际回应才进入声明的后继点。
窗口只保留捕获前缀，不把某人的choice/voter作为其他人的输入；信息共享由实际报告或公开字段声明。

发生与过程步骤都记录next_point/advanced，后续review的supports覆盖本轮所有实际回应。
循环再次开启窗口会重置配额和本轮报告来源，旧句柄不能答新一轮。
阶段/配额/来源与字段、费用、报告、终局共同提交；部分回复的后继故障只回滚本次根，
已提交的其他回复保留。终局排空也等全员及后续review真实完成。

验证和可读运行例见阶段/窗口交付（研究仓路径：`docs/closure_notes/PYTHON_CODEGEN_WINDOWS_V1.md`）。

## 事实保证与公开约束

`information`和`disclosures`里的`assure`/`assure_constraints`均进入生成函数。例如：

```yaml
facts:
  ActualHeat:
    parameters: {sensor: SensorRef, hot: Bool}
    holds: sensor.hot == hot
constraints:
  HeatDiagnosis:
    parameters: {sensor: SensorRef, hot: Bool}
    variables: {cause: FaultCause}
    holds: hot == (cause != FaultCause.none)
    realize: {cause: sensor.cause}
```

`ActualHeat`保证报告中的hot确实等于采样时的热状态。
`HeatDiagnosis`私下检查cause，使接收者知道公开关系成立，但不会交付cause的实际值。
`assure`的实参只能从content纯取值；公开约束的holds必须是纯值公式，realize才读取世界。
类型与信息边界仍在现行前端检查。

结构化`cardinality/allocation`也生成holds和实际classification检查。
单满足人数或角色多重集仍不够，私有实现还须与声明的分类关系一致。
配对不出现在收据中，多重集仍保留重复角色槽；两种隐藏配对可产生相同的公开保证。

正文、事实判断、约束实现和分类检查使用同一before/after采样快照。
空受众不计算正文与保证；无资格的开局查看者也不触发检查。
Start违规时不返回半局；运行交付违规时费用、效果、报告、发生、过程与终局整根回滚并fatal。
普通未声明保证的消息仍可表达错误内容，不会自动变成知识保证。

```python
session.checked_facts("b", "inspect.signal")
session.checked_constraints("b", "inspect.signal")
```

接口返回acquired和本人当时取得的公开条目，包含签名、参数、source/slot/occurrence/sample；
约束另有变量名/名义类型及holds文本。参数使用生成后端的原始不可变值，外层字典为独立拷贝。
历史读取不运行正文或谓词，世界后来变化不会改写旧保证；holds文本只作声明元数据，不用于运行期eval。
接口仅从本Session实际接收者日志取值，不接收外部构造的receipt；跨进程认证/恢复另行设计。

现有故障诊断（研究仓路径：`docs/author_language/communication/fault.lib.yaml`）可原样生成：

```bash
PYTHONPATH=src .venv/bin/python -m nomos_c0.python_codegen \
  docs/author_language/communication/fault.lib.yaml \
  docs/author_language/communication/fault.source.yaml \
  build/python-codegen/fault.py
```

同一报告可同时携带事实与约束；相同约束正文按签名生成一次，由多个真实来源调用。
生成产物依赖标准库、nomos_runtime及其声明依赖，阻断C0/K0/nomos_cognition也可核验并读取保证。
本片未迁移local_constraints归一化、局部传播或心智自动更新。
交付与具名证据（研究仓路径：`docs/closure_notes/PYTHON_CODEGEN_ASSURANCES_V1.md`）。

## 携带关系与付费尝试

沿用已有[custody规则](../author_abilities/examples/custody.lib.yaml)：

```yaml
resolve:
  attempt: custody.transfer(item, giver, person)
  success: {result: 'ReceiveOutcome.Received()'}
  failure: {result: 'ReceiveOutcome.Unavailable()'}
```

`holder`、`held_by`和`position`生成直接读取/比较；有持有者时位置取其当前位置，
否则取物件的ground字段。携带不改变个体身份，也不把地面位置伪装成第二份实时位置。
实体字段读出值里的引用仍核对当前身份域，即使它只参与Bool判断；
该检查同样覆盖普通字段及record/collection内嵌引用，不因字段可见而自动认识持有者。
`take/drop/offer/transfer`分别生成实际Python条件和修改：

- take要求无人持有且同地；drop要求实际持有者，放下写本次前态的当前位置。
- offer要求实际持有者、不同接收者及同地；再次提议替换接收者和来源，不先转移物件。
- transfer由接收者选择，重新检查当前持有者/同地/最新提议；成功清除提议，
  将提议的实际occurrence ref加入supports；与普通过程组合时也保留原过程依据。

准入条件/费用在submit重验；不再符合者零写拒绝。若准入仍成立但尝试条件为假，
照常扣费、发布Action并运行作者failure分支。它与拒绝是不同的结果。
所有费用、持有者、地面位置、内部提议、报告、过程和来源在同一根事务发布或回滚。

内部`ProposalKey`不是世界实体/作者字段；开局提议为空，Assets不能伪造提议或发生来源。
原始`set`不能改携带管理字段，编译器和Draft都检查；合法开局仍由精确声明字段绑定holder/ground。
可信诊断`inspect_relations()`返回不可变提议的分离字典；玩家只能经作者投影/交付获取信息。
这些是占有/携带关系；法律所有权、抢夺、转售、存档与动态形成继续由各自合同决定。

```bash
PYTHONPATH=src .venv/bin/python -m nomos_c0.python_codegen \
  src/nomos_c0/author_abilities/examples/custody.lib.yaml \
  src/nomos_c0/author_abilities/examples/custody.source.yaml \
  build/python-codegen/custody.py
```

生成后用原`custody.assets.yaml`调用`start`；先由keeper执行OfferTransfer、再由traveler执行TryReceive，
第二条Action的supports包含第一条Action ref。没有提议时则返回Unavailable、消耗1energy并发布。
内部执行回调和Draft统一接收Session分配的实际发生位置；旧内部签名不作兼容。
交付与具名证据（研究仓路径：`docs/closure_notes/PYTHON_CODEGEN_CARRYING_V1.md`）。

## Variant匹配

原[结构化查询](../author_abilities/examples/structured_expressions.lib.yaml)无需改写即可生成：

```yaml
reply_score:
  parameters: {answer: Reply}
  returns: Score
  expression: match(answer, Total(value) => value.score, Pass() => 0)
```

前端要求每个case恰好出现一次，核对所有分支的名称、返回类型和读取权限。
`Total(value)`绑定整个Total记录；没有binder时忽略载荷，嵌套同名binder只遮蔽本分支。
生成器只求值一次subject，以精确记录类型的identity guard生成扁平Python match，
只执行选中的正文；不用类模式解构放宽名义匹配。大量case也不会增加人工if链的AST深度。

分支复用局部绑定设施：作者名称映射到生成变量，不覆盖Python内置名或运行上下文；
经分支记录取得的人物引用不继承控制者私有读权。分支内的纯查询在编译期照常收集，
求值仍遵守源位置、逻辑步数/深度和结构预算。
构造Variant、读取case字段、有限循环、命名Variant输入、行动/因果与私有报告可组合；
分支运行错误仍由既有事务边界处理。

当前原M1的motion_start/motion_end纯查询也已对Arrived/Blocked/Collision三类结果直接生成并验证。
匹配交付（研究仓路径：`docs/closure_notes/PYTHON_CODEGEN_MATCH_V1.md`）记录具名测试和隔离运行。
47项纯值操作加4项世界操作覆盖清单51项规范化节点；独立纯引用接口、完整心智读取及整体迁移门继续按清单核验。

## Object形成

已有`resolve.form`由world生成实际字段表达式，使用与效果/结果相同的前态。
每个形成物件取得新的本局Reference和独立状态；开局个体的`formed_by`为None，
新生个体记录实际生成它的Action或Event ref。
发生记录的`products`只包含本次实际生成物件；后继`{formed: Tool}`按名义子类型筛选这个集合。
未生成分支发布空产品，不分配占位身份；多个产品按sort稳定分配，保持同sort内的声明顺序。

事务共享身份分配器，普通同波规则仍读取共同前态。
各自after交付读取自己的字段后态，身份域仍是发生前已有个体；下一波才见新生身份及合并状态。
产品捕获不混入祖先或上一批物件。
公开身份按当前阶段个体计算；受限身份通过投影或实际报告取得，形成不自动授予玩家知识。
`opening_domain`始终只指开局名单，当前`known`和一次性开局报告各自保持职责。

原泛型Law可以继续修改新生子类型；携带物件初始化空私有提议，之后使用同一提议/接受规则。
稳定终局检查也读取已形成的候选。类型/容量/后继错误连同身份、状态、报告、过程和来源整根回滚；
阶段完成false仍正常零写拒绝，下次成功可使用未消耗的身份位置。
字段初始化仍在当前规则求值，实际分配及容量检查在阶段完成准入通过后执行。

确定性制作样例（研究仓路径：`docs/author_language/formation_python/README.md`）提供Lib/Source/Assets与运行命令。
它使用已有语法；原含种子骰的formation_workshop现也可原样生成，见下方随机机制。
`SessionLimits.objects_per_type`沿用精确Object sort的显式容量，默认64，包含开局和已发布新生物件。
`inspect_individuals()`返回受信的不可变身份/生成者记录，`inspect_individual(ref)`返回独立状态拷贝；
玩家引用仍由`known/project/reports`提供。

本批内部Action/Reaction执行函数和Draft显式接收事务分配器；已有生成文件应重新生成，无旧签名回退。
交付与具名反例（研究仓路径：`docs/closure_notes/PYTHON_CODEGEN_FORMATION_V1.md`）。

## Actor形成与手动控制

原[actor_workshop三声明](../author_abilities/examples/actor_workshop.source.yaml)可直接生成，
运行指南（研究仓路径：`docs/author_language/actor_formation_python/README.md`）提供命令及简短手动链。
`Source.actor_kinds`选择未来可形成的Person sort；Program同时保留开局人物与封闭的Actor类型集合。
同一`form`及后继`{formed: Creature}`机制生成真实人物并捕获本次实际子类型，
Actor/Object混合时先Object组、再Actor组，各按sort稳定分配。

`session.actor_controllers()`返回开局名称和新生人物的会话签发句柄。
`ActorControl`只选择控制者，不是作者值或世界Reference；控制库存也不是玩家观察。
公开身份/本人身份、当前投影和真实交付继续决定各Actor的可指认域。
新生人物可以使用已有泛型能力、接收实际报告、读取本人投影、参与公开chooser过程/阶段、
接受携带转交及取得终局结算。开局报告仅在Start交付，不在出生时重放。

提交凭据在会话中保存实际人物、能力、选择和过程绑定；即便修改凭据的显示Actor或能力，
也不能把它转交给别人。控制句柄复制、伪造、改标签、跨Session、以引用代控制均拒绝。
错误控制者不会消费合法凭据；同一人的过时准入则按当前世界重新检查。

`SessionLimits.actors_per_type=64`单独限制每个精确Person sort的开局/新生人数，
不按父sort重复统计，也不占用Object容量。形成沿用共同前态与实际发生来源；
人物、物件、费用、报告、过程/终局同事务发布，失败不会登记幽灵人物或控制权。
句柄在已发布人物的受信控制访问中签发并保持稳定，无须事先提供开局名字。

当前前端对过程决策仍要求public可指认的chooser（包括同人后续决策），
projected chooser在Compile明确拒绝，保留为后续语言复核项；本片未放宽这条作者合同。
手动控制与独立AI配置分开；可选时间、活动和调度见后文，独立策略也已生成。
Program构造及形成容量内部签名统一更新，现有世界产物重新生成，无旧签名fallback。
交付与边界（研究仓路径：`docs/closure_notes/PYTHON_CODEGEN_ACTOR_FORMATION_V1.md`）。

## 显式种子随机

已有`draw/then`生成输入求值、展开预算检查、`draft.random.sample(...)`或`draft.random.shuffle(...)`调用，
结果按声明的名义类型绑定为当前规则的局部变量；后续if/效果/结果仍是直接Python。
`Source.random: {mechanism: replayable_seed}`选择机制，`streams`可声明独立流；
Assets单独提供主seed与精确的额外流seed，不把开局数据嵌入Program。

骰子沿用SHA256有界拒绝采样，洗牌为Fisher–Yates；同种子/相同行动序列得到同样的实际样本。
空/单元素Sequence不掷骰，重复值和名义引用保留；超1000元素洗牌有界报错。
每次骰子或洗牌消耗的展开工作，与该发生的效果/形成共用节点预算。
stream可以是Source固定文本或封闭enum，开放运行时文本在Compile拒绝。

prepare不采样，submit按当前流状态执行；未选分支不推进流。
真实掷点保存在`Occurrence.draws`，包括作者路径、流、序号、前seed、面数与点数。
`inspect_random()`是受信诊断；Actor只取得规则明确写入状态或交付的结果，
种子及临时binder不进入其视图/发生参与者。

随机状态使用内部`RandomKey`进入同一候选字段事务。
后继Event可以读取根行动之后的流；普通同波共享前态，同流实际采样冲突则整根回滚，
不同流可合并；不把它们隐式串行化。显式ordered settlement现由下方机制执行。
阶段完成拒绝不消耗种子/点数，晚期缺陷连同费用、身份、报告、过程和终局共同回滚。

原random_workshop、formation_workshop三文件可原样生成；
运行指南（研究仓路径：`docs/author_language/random_python/README.md`）提供简短重放与真实产品链。
Program内部签名统一加入选定流，旧世界产物须重新生成，无旧签名回退。
交付与反例（研究仓路径：`docs/closure_notes/PYTHON_CODEGEN_RANDOMNESS_V1.md`）。

## 作者显式有序结算

沿用`Source.settlement`，Lib规则和Assets无需改写：

```yaml
settlement:
  default: wave
  ordered:
    gain:
      - {reaction: bonus, required: true}
      - {reaction: scale, required: false}
      - {reaction: report, required: true}
```

编译器核对该实际trigger的全部直接订阅各出现一次，生成`OrderedSettlement/OrderedStep`静态接线。
步骤仍调用已生成的Reaction函数，运行设施只调度函数，不解释表达式或规则IR。
required表示必须激活并产生真实Event；结果为False也算实际发生。
optional的条件为False可跳过，条件求值错误仍是整根缺陷。

每一步重新绑定当前候选，核验既有类型和携带不变量，交付按本步前/后态采样。
一步产生的整个子闭包先完成，再进入下一父步骤；终局只在整个根闭包稳定后检查。
不同trigger的cursor同时取下一步时，仍属于同一共读前态阶段；
即便各自声明有序，同阶段重叠实际写入也拒绝，不偷偷变成逐trigger串行。
同一Event source的不同实际发生各有独立cursor，不共享进度。

`Occurrence.predecessor`保留实际因果前驱；`Occurrence.order`记录政策名、声明中的ordinal、
前一项实际激活的同政策Event ref。跳过项不造占位发生；previous_completed不等同子闭包末尾。
随机流、形成、报告、过程位置与终局仍在同一次事务中发布；任一步失败全根回滚并保持fatal。
携带尝试仍要求实际控制Actor，Event中的同类请求在Compile拒绝，未借有序政策扩大许可。

现有ordering声明（研究仓路径：`docs/author_language/settlement_g3/ordering.source.yaml`）可原样生成：
同样的Gain/Bonus/Scale/Report，ordered得到8并交付8，wave得到4但报告采样3。
只反转Source顺序也会得到4并保留实际发生和被跳过步骤的来源差别。
运行指南（研究仓路径：`docs/author_language/settlement_python/README.md`）与
交付/反例（研究仓路径：`docs/closure_notes/PYTHON_CODEGEN_SETTLEMENT_V1.md`）。
内部Program统一携带政策，所有本地世界产物重新生成，无旧构造签名回退。

## 时间、活动与周期

原reading/periodic_workshop三文件可直接生成，见运行示例（研究仓路径：`docs/author_language/temporal_python/README.md`）。
`Source.time`显式选event_jump，Assets精确提供`time: {at: 0}`；未选择时没有隐含时钟。
开始保存真实参与者、原结果及固定参数，时长读取开始前态；完成正文读取到期时的当前状态。
`advance(to)`停在不超过to的最近到期点，无到期时可只推进时钟并记录区间。
同刻依Source.time.due_order排序，每个实际根先完成整个因果闭包，后根再读当前候选。
取消使用本人实际实例句柄、当前本地依赖与费用，发布真实Action及取消依据；不会取消同源的其他实例。
周期开局只建立计划，实际到期发布Event并从本次due时刻续期，正常False结果仍续期。
终局在稳定根检查，正式关闭后停止同刻剩余项并清除计划；排空阶段继续处理时间和已有过程。
整次advance失败共同回滚时间/身份/随机/字段/报告/来源。
`Occurrence.at/due/scheduled/cancelled`及独立推进/取消记录保存来源；时钟推进不伪造世界行动。
内部Program统一携带TimeDefinition，所有本地世界产物重新生成；无旧签名fallback。

## 速度与行动债务

沿用Source.time.scheduling及Lib.schedules，原scheduled_workshop三文件可直接生成，
见运行指南（研究仓路径：`docs/author_language/scheduling_python/README.md`）。
本人speed/eligible及当前行动time_cost均生成为直接Python函数；公共运行库只调度这些已生成函数。
债务随时间按速度减少，行动后增加成本，保留负余债；同刻按优先级、实际形成次序选择。
人物与due等时先交人物，之后再实际结算due；取消自己的活动可在此阶段使用其独立成本。
等待记录defer而不制造世界Action，至下次实际时间/世界变化解除排除。
新生人物即时核对速度/资格，自初债开始；普通过程费用可读当前访问的实际报告。
Occurrence.time_cost与调度审计记录实际费用/Action ref；身份、随机、报告、时间、债务、终局仍保持原子边界。
未选调度时time_cost不隐含建立时钟/债务；选调度时advance明确拒绝，统一走next_opportunity。
内部Draft、TimeDefinition和ActionDefinition签名同步更新，所有本地世界产物重新生成，无兼容回退。

## Action 时期凭据

能力可声明`epoch: round`，也可声明其他已检查的本地纯表达式。
同一准入函数返回`ActionAdmission(participants, ActionEpoch(type_name, value))`，
准备时封存，提交时在当前本地读域重新求值；变值返回`StaleEpoch`，不扣费、不消费随机或分配身份。
同值允许其他Actor完成当前轮次的行动，不使用每次提交递增的全局revision替代作者声明。
普通guard、费用、控制权和过程资格仍重新核验；epoch相同不承诺准入。
实际Action在`Occurrence.epoch`记录接受的值，参与者和Event记录不混入这个元数据。
epoch值由生成的名义校验器检查，支持原有record/集合/引用/optional等类型；
它不能依赖新选择或越过本地读取权限。未声明时为None，不隐含时间或时期。
内部准入返回与提交接口同步更新，本地世界产物全部重新生成，无旧dict返回兼容。
见时期指南（研究仓路径：`docs/author_language/epochs_python/README.md`）。

## 本地选项与输入

生成Session提供两个只读入口：

```python
session.available_abilities("traveler")  # ('touch',)
form = session.choice_form("traveler", "touch")
gate = next(field for field in form.fields if field.name == "gate")
choice = next(iter(gate.pool))  # 此warming样例只有一个gate
form = session.choice_form("traveler", "touch", {"gate": choice})
assert form.complete
session.act("traveler", "touch", {"gate": choice})
```

每个Action自带直接Python选项函数，与正式准入复用编译期生成逻辑。
InputField包含name/type_name/kind/dependencies/ready和当前pool/数量/重复策略；
ChoiceForm.values只返回已绑定的输入与derive值，不返回共享环境、他人私态或过程捕获。
未满足依赖的字段ready=False；选择完整后校验跨字段约束，集合可一次提交而不逐元素发布。
本地条件明确为假则菜单排除，依赖新输入的条件暂缓；输入完整不等于已获结算承诺。
当前阶段/过程请求/调度资格/终局继续使用正式控制门，菜单读取不推进世界或采样。
内部ActionDefinition统一新增choices回调，取消明确不参与普通菜单；本地世界产物重新生成，无签名兼容。
见输入接口指南（研究仓路径：`docs/author_language/choices_python/README.md`）。

## 独立策略与play

同一Lib/Source之外可选择独立AI文件，由`--ai`生成供值/评分函数：

```bash
PYTHONPATH=src .venv/bin/python -m nomos_c0.python_codegen \
  src/nomos_c0/author_abilities/examples/avalon.lib.yaml \
  src/nomos_c0/author_abilities/examples/avalon.source.yaml \
  build/python-codegen/avalon.py \
  --ai src/nomos_c0/author_abilities/examples/avalon.ai.yaml
```

产物包含无Assets的PROGRAM与独立CONTROLLERS；start默认使用本次选中的策略库，
也可显式用PROGRAM.start创建手动Session。策略必须绑定同一实际Program。
候选生成/评分不执行世界正文、不消费随机；最终提议独立封存实际选择、过程绑定和时期，submit_proposal再重验。
它不占用普通准备凭据登记；调用者丢弃提议或普通准备凭据后，对应控制登记可回收。
菜单的生成资格函数只检查当前本地guard，具体输入域由选定能力的表单核验，避免一项错域阻断整份菜单。
StrategyProposal保留能力、总分和具名评分项；proposal_details返回独立的本地输入/评分说明。
candidate预算耗尽报错而不选半途赢家，平局按作者wait/canonical处理；canonical使用本局引用的稳定sort/ordinal。
策略额外views不改变正式Source的准入读域；cognition视图只读本人已选模型的当前结果。

player_turn使用session.drive_play停在玩家真实机会；等待只有控制记录。
tabletop使用session.table_control(player).drive，按固定席位提交电脑实际Action。
共同意向由每位参与者的真实本地投影核对，玩家可以修改；各自锁定仍由作者Law结算。
coordination_offer/coordinate使用实例绑定的当前控制凭据，过时/复制/改写拒绝；
coordination_state和resume_coordination把工程预算暂停与世界终局分开。
所选play缺少电脑策略时，自动化明确拒绝；手动世界运行仍可单独使用。
见完整使用指南（研究仓路径：`docs/author_language/strategies_python/README.md`）。

## 个人修订与条件推导

`emit_world_module(program, cognition=plan, controllers=controllers)`接受同Program的独立认知计划；
当AI已选择该计划时可仅传controllers。显式世界计划与AI计划不一致时Compile拒绝。
CLI使用`--cognition`，实际条件、判断、prior和推导展开均生成Python函数；
`nomos_cognition`保留纯修订/连接算法，旧K0收据/owner注册/表达式解释不进入Run。
稳定闭包后的认知候选与世界一起提交；同刻advance任一根失败，整次推进共同回滚。
预算不足公开未完成视图；读和评分只读，不进行认知结算。
见短对照及合同（研究仓路径：`docs/author_language/cognition_python/README.md`）。

## 工具与生成产物

T0已直接消费生成的`.py`，使用独立Assets和witness，运行时无需编译器或旧K0。
见[T0指南](../../nomos_t0/README.md)。
`session.values(actor)`提供当前本人引用域内的名义值编解码；
`decode(type_name, wire)`生成不可变记录/集合，`encode(type_name, value)`返回独立字典/列表。
Variant保留原声明tag和fields，Set输出稳定排序；类型、范围、容量及实际引用仍核验。
省略actor的`session.values()`是受信工具视图；桌面输入应传实际控制人物。
自定义reference回调只在声明的ref槽执行，不能使错局、错类型或未取得身份通过检查。
codec是当次读域快照，不是准备/准入凭据；后续操作重新取得，submit始终核对当前状态。

`nomos_runtime.artifacts.load_world(path)`在上下文中导入受信生成模块并核对PROGRAM/CONTROLLERS/DISPLAY绑定，
退出清理临时模块登记。它执行本地Python代码，调用方须选择受信产物。
YAML/JSON文档读取与`!table`展开抽到`nomos_runtime.documents/document_tables`，
C0的作者位置索引与T0数据读取共享同一解析实现；旧表格模块已删除，无转发入口。

## 玩家显示与输入提示

CLI可传`--presentation`，将已有呈现声明的读回和提示表达式编成实际Python函数。
生成产物的`DISPLAY.open(session, seat)`返回固定本人视图：
`snapshot()`包含面板、人物标记、数量棋盘、授权变化采样点与规则书；
`form(ability, choices)`提供当前输入域、数量分配和依赖已满足的预览。
未指定呈现文件的tabletop在Compile自动生成默认显示，非tabletop的DISPLAY为None。
读取帧共用授权缓存与输出预算，实际身份、终局揭示和本人认知均从同一生成Session取得。
不在Run解释C0类型/表达式，也不将显示提示当作准入承诺。
见生成显示指南（研究仓路径：`docs/author_language/presentation_python/README.md`）。
生成后端与已退役原生后端的历史同内容短链计量见运行对照（研究仓路径：`docs/evidence/python-codegen-runtime-v1/README.md`）。

## 当前交付与后续

local/finite均已生成绑定，见两种分析及短例（研究仓路径：`docs/author_language/analysis_python/README.md`）。
T0、共享桌面控制、浏览器消费与可移动可玩包均已使用生成产物。
遇到已选且未实现的机制在生成阶段明确拒绝，不生成“少一半规则”的产物。
发生/到期容量和结构/逻辑预算用于有限失败诊断；GC和恢复协议另行设计。
51项规范化操作、实际值/读取接口与消费者行为证据见
迁移清单（研究仓路径：`docs/coordination/PYTHON_CODEGEN_SCOPE_V1.yaml`）。
当前返回点为独立浏览器试玩及最终审计，见Goal（研究仓路径：`docs/coordination/PYTHON_RUNTIME_AND_AVALON_PLAY_GOAL_V1.md`）。

## 同进程作者源码复用

`AuthorPrograms`除复用生成Program，也在显式作用域内复用不可变Lib／Source装配快照。每次load仍核对文件文本摘要和解析后的imports路径／顺序，包含符号链接目标；相同大小或mtime不代表命中。变化或读取失败回到正常装配和诊断，不能返回旧规则；context_parameters每次在独立数据副本上校验。close释放快照，不持久化缓存，Session仍逐局独立。

入口路径每次load重新解析一次，快照复核沿用本次已经解析的入口；各import路径仍单独重新解析，不跨load保存解析结果。优化只移除同一次读取内重复的入口解析，不省略任何文件摘要或来源核对。
