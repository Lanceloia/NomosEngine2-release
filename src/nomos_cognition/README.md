# 官方心智修订扩展

此包维护领域无关的不可变软判断、推导和分析算法。C0 检查作者的名义类型和配置，
生成类型化调用；`nomos_runtime` 从本人实际报告更新判断，并与世界事务共同提交。
领域库定义命题及评价含义，独立配置决定如何理解经历。

`preferences.py`提供独立的具名目标偏好值，不修改Subject人格或存档。
条件学习首轮（研究仓路径：`docs/guides/CONDITIONAL_PREFERENCE_LEARNING_V1.md`）将偏好与本人许可候选特征
输入同一神经网络，已核查训练及真实提交，但尚未证明人格差异的泛化或规则迁移。

`learning.py`提供机器学习数据接口（研究仓路径：`docs/guides/LEARNING_DATA_V1.md`）：
有版本的本地观察／候选帧、priority掩码、完整策略输出、独立结果标签与变长候选批量。
核心不依赖Torch／NumPy；阿瓦隆PPO已经实际消费。它是纯值边界，不认证观察权限、
签发行动票据或自动把训练标签写进Subject记忆；正式读取与执行仍由C0／Runtime负责。

`avalon.team_context`提供本人联合信念与合法队伍的8维候选摘要：坏人数分布及角色在队概率。
已明确支持原生local与既有graded两种当前学习帧；偏好表示V2（研究仓路径：`docs/guides/PREFERENCE_CONTEXT_V2.md`）
复用该投影，已检查编码区分度与真实提交，未达到正式训练的数据门。
它只消费既有本局帧，不读取终局或其他主体私信，也不规定选队；
神经表示对照（研究仓路径：`docs/design_notes/AVALON_TEAM_CONTEXT_REPRESENTATION_V1.md`）用该摘要扩展网络输入，核心仍不依赖Torch。

`memory.py`提供独立的纯记忆核心（研究仓路径：`docs/guides/COGNITIVE_MEMORY_CORE_V1.md`）：
主体／情境标签、不可变经历、带依据的经验修订与有预算召回。
它通过显式值调用，并由实际反馈端口（研究仓路径：`docs/guides/EXPERIENTIAL_FEEDBACK_V1.md`）接本人输入；
下述局内修订与它分别维护。
记忆核心保留原经历和新解释的差别。

版本化SQLite读取（研究仓路径：`docs/design_notes/MEMORY_VERSIONED_READS_V1.md`）复用同一回忆政策，
按索引获取相关记录，旧解释按精确修订展开；脱离Memory的Recall继续走完整输入核验。
校验树在同次调用内复用共享不可变值，完整校验字节保持；不缓存其他主体或后继修订。
正式实现现位于`storage/`，由主体冷热记忆（研究仓路径：`docs/design_notes/SUBJECT_COLD_MEMORY_V1.md`）
接入真实Subject：原始经历、当前样本／摘要及索引热驻留，样本／经验旧修订与决策解释冷读。
旧tools库入口已删除；临时存储不恢复Subject身份，遗忘、共享经验及跨进程恢复仍未启用。

`appraisal.py`提供经验驱动评价（研究仓路径：`docs/guides/EXPERIENTIAL_APPRAISAL_V1.md`）：
结构化反馈汇总、相似案例估计、人格／当前目标加权与实际选择。
候选名称不参与评分；一次召回供所有候选共用，共享依据不重复计权。
`AppraisalFrame`在精确Model／Recall上按需复用已完成的纯评价准备，
支持规划器逐个生成候选后再估值；只缓存实际访问的特征／目标，不先展开完整菜单。
每次调用仍核其预算和容量，未完成结果不入排名；新输入使用新frame。
一次性`assess`也使用同一实现，原公式及完整贡献保持，
见同帧合同（研究仓路径：`docs/design_notes/PLANNING_APPRAISAL_FRAME_V1.md`）。
候选可带Actor本地`valuation`系数：`assess`保持原结果预测与案例贡献，
`choose`再结合当前价值、人格和目标。`Score.valuation`保留逐轴转换，
原始反馈不随需求满足重写，见情境价值合同（研究仓路径：`docs/design_notes/CONTEXTUAL_VALUATION_V1.md`）。
适用性按评价维度及其声明条件建立局部索引，各维度的共同结果权重按适用组复用。
相同特征／个人目标的案例贡献及加权和在一次评价内共享，再分别加入各候选先验和已知维度。
相似度、已知结果优先及全部候选的实际评分保持；索引只活在一次评价中。
反馈批次用`revise_samples`按顺序检查修订，统一发布一份不可变Memory，保留完整样本历史。
Memory历史采用Pyrsistent向量和映射结构共享，追加只核新增记录，旧快照保持可读。
原始经历按Context和(Context,cue)派生不可变posting，召回在允许范围内选择较短流，
按实际追加顺序合并；多cue的重复访问计Work、同一来源只返回一次。
无关旧局／cue不再要求全表扫描，完整内容与证据关系保持；
原始检索合同见经历索引（研究仓路径：`docs/design_notes/RECALL_EPISODE_INDEX_V1.md`）。
当前Sample／Experience维护cue、共享结果及摘要引用的结构共享posting，
查询只遍历获准起点的完整依赖邻域，不物化全表；直接命中的摘要也闭合其样本依赖。
修改解释时移除当前索引中的旧边，原记录／版本仍保留；
旧cue计数和运行全扫描已由依赖索引（研究仓路径：`docs/design_notes/RECALL_DEPENDENCY_INDEX_V1.md`）替换。
大连接组仍须支付依赖成本，索引不把相关案例近似成无关或悄悄截断。
最新样本与经验的顺序由`current_samples/active`明确维护；
见存储组织与测量（研究仓路径：`docs/evidence/history-structures-v1/README.md`）。
`consolidate`沿同一Memory链复用[不可变分组索引](consolidation_index.py)，
只解码新增／修订样本，更新结果维度的和与计数，再重建受影响摘要。
索引按完整反馈词汇签名隔离，构造新Memory时重建；显式改写已有摘要也会触发对应组核对。
完整来源、组内顺序、版本和显式逻辑预算保持，见实测与限制（研究仓路径：`docs/evidence/incremental-consolidation-v1/README.md`）。
完整`recall`携带与原Memory及全部返回字段绑定的进程内计算证明；`assess`复用该快照中
已解码的样本及已核对的摘要，评分、Contribution和显式预算的失败位置保持。
手工构造／修改的Recall逐项检查；证明弱引用Memory，旧决定不会因此保留整份记忆索引。
见核验复用及测量（研究仓路径：`docs/evidence/appraisal-input-proofs-v1/README.md`）。
分阶段测量及边界见经验规模对照（研究仓路径：`docs/evidence/appraisal-scaling-v1/README.md`）。
C0已提供受检候选语义帧（研究仓路径：`docs/guides/AUTHOR_CANDIDATE_SEMANTICS_V1.md`），
可将同一纯算法的选择提交为真实Action；多依据反馈及进程内主体参与（研究仓路径：`docs/guides/COGNITIVE_PARTICIPATION_V1.md`）
已接通。主体生命周期和控制由Runtime维护，算法仍只处理纯值；领域策略由独立AI配置维护。
反馈Sample区分实际结果evidence和完成boundaries，二者都保留为可核对依据。
同一发布的多个消息保留各自身份，计权及召回依赖按共同publication关联；
结束点只在空观察时充当结果依据。见表达回应经验（研究仓路径：`docs/design_notes/EXPRESSION_EXPERIENCE_FEEDBACK_V1.md`）。
`exploration.py`提供显式种子的epsilon-greedy纯选择：在完整合法候选评分后探索，
保留原分数、基准、实际选择及总概率；主体使用方式（研究仓路径：`docs/guides/COGNITIVE_PARTICIPATION_V1.md#显式探索`）。
抽样不读取世界或消耗世界骰子，默认主体仍沿用最高分／作者tie政策。
当前阿瓦隆经验AI另用主观看法层（研究仓路径：`docs/guides/SUBJECTIVE_JUDGMENT_V1.md`）
复用`Frame / State`维护本人收件对应的身份线索、队伍印象及建议可靠性；
领域含义留在独立作者配置，核心修订器不包含角色名或游戏规则。

`prediction.py`维护纯预测结果和显式 provider 目录，`avalon/`是首个独立领域模型库。
它们与下列领域无关修订算法分开维护；模型接收受检值，世界读取及行动权限由C0和运行库管理。
模型策略指南（研究仓路径：`docs/guides/AUTHOR_LEARNED_POLICY_V1.md`）说明冻结权重、端口、实际刺杀及赛后快照。

`planning/`是独立的纯值规划原型（研究仓路径：`docs/guides/PURE_VALUE_PLANNING_V1.md`）：
从模式逐步绑定参数，用有限AND／OR搜索组合多步与观察分支，按同一计算累计工作与容量。
`planning/agenda.py`按根能力已花Work协调服务，组内优先确认结果及续完暂停计算，
每8次服务最老待办；同一任务的年龄／服务量跨分片保留，不重复排队。
`statistics()`汇总族／阶段实际扣费和待办，显式`profile=True`才记录物理时间，
见预算与调度合同（研究仓路径：`docs/design_notes/PLANNING_WORK_DISPATCH_V1.md`）。
T1／T2纯测试消费显式模型；Runtime后继已用生成T1模型（研究仓路径：`docs/guides/GENERATED_LOCAL_PLANNING_V1.md`）
连接真实单步与本地重规划；T2生成有限假设（研究仓路径：`docs/guides/SCENARIO_PLANNING_FEEDBACK_V1.md`）
另接实际私人报告与条件处置。纯包本身不读Session；后继已接局内Memory检索。
正式Subject单步规划（研究仓路径：`docs/guides/SUBJECT_PLANNING_V1.md`）进一步使用本局及已结束visit的真实经验，
`query_for_model`在完整候选出现前按声明特征词汇召回一次，原`assess/choose`按需评价；
旧局报告不重绑定为本局人物，个人target经验保持Context隔离。
A1提队（研究仓路径：`docs/author_language/planning_a1/README.md`）进一步使用类型化集合草稿逐成员构造，
最终提队由同一生成世界执行；正式桌面与旧AI尚未切换。
`ConstructDraft`后继支持结构化内容（研究仓路径：`docs/guides/STRUCTURED_PLANNING_CONSTRUCTION_V1.md`）
的追加式构造、封口与完成，已有Speak一次发布比较和条件两段内容。
`planning/guidance.py`将优先级与稳定探索交织，Runtime后继用
本人实际回忆（研究仓路径：`docs/guides/RECALL_GUIDED_PLANNING_V1.md`）在完整候选出现前排列行动和成员，
保留原utility与来源；它不是旧“先枚举再精评”的入口。

| 概念 | 含义 |
| --- | --- |
| `Term` | 有名义类型签名的封闭值，作为命题、评价目标或修订槽 |
| `Evidence` | 局、实际来源、接收者与 slot；发生和开局来源分别表示 |
| `Frame` | 一条规则在一个槽中、由一次真实经历得到的判断 |
| `State` | 当前有效 frame、消费记录、完整修订历史与 pending |
| `revise` | 按 `(rule, slot)` 替换最新判断，保留旧依据，拒绝重复消费 |
| `judgments` | 按完全相同的 typed 命题/目标聚合支持、反对与评价 |
| `Graph / Argument / PremiseGroup` | 无环派生关系及其共同条件、替代支持和局内依据 |
| `reasoning.evaluate` | 对有限前提做受预算完整重算，保留共享证据，不按路径加分 |
| `install_reasoning` | 发布当前完整图；相同图不重复累积，变化图保留历史 |
| `finite.solve` | 在声明的名义有限域与纯谓词上完整搜索，区分一致、无解与未完成 |
| `local.propagate` | 本人小集合的标签分配/人数界传播，保留依据，区分局部完成、冲突与预算未完成 |
| `Analysis / Ground / Conclusion` | 本人分析结果、实际样本与假设，保存条件化的必然/可能结论 |
| `install_analysis` | 在同一 State 中更新有限结果并保留旧分析 |
| `LocalAnalysis / LocalBound` | 本人的分类人数界、实际依据与时期前提；只发布登记集合的紧凑结果 |
| `install_local` | 原子更新局部快照，结果相同不追加历史 |
| `explanation.explain` | 将当前已提交依据、条件图及分析摘要投影为受预算说明；名义值编码由调用者提供 |

数字表示作者明确选择的软强度，不自动解释成概率。一个命题可以同时得到支持和反对。
`pending` 时对外提供空判断与未完成状态；历史和已处理依据仍被保留。

纯包不读取世界、认证来源、发布 Action 或决定模型权限。
不可变子图和分析在构造/wire解码时核验，State维护跨记录关系；更新不重复深检整份旧历史。
生成Session只在所选实际输入、引用库存和本人已知域不变且视图完整时复用判断，当前basis仍更新。
新证据、引用域变化与pending继续实际重算，未使用跨Session的持久推理缓存。
说明投影也不运行求解器、修订器或世界读取。完整图保留全部来源叶；显示预算耗尽时
返回 `explanation_complete=false`，不留下悬空图、不将已有判断改成未知。
`Session.explain_cognition(actor)` 取得本人的说明；桌面提供显示帧编码器，将引用替换为本人签发的句柄。
C0 指南（研究仓路径：`docs/guides/AUTHOR_COGNITION_V1.md`）给出配置、运行和权威分工。
经验按槽确定性修订，当前推导通过显式依赖维护；
推理指南（研究仓路径：`docs/guides/AUTHOR_REASONING_V1.md`）给出两级撤销、替代支持与真实作者样本。
有限推理指南（研究仓路径：`docs/guides/AUTHOR_FINITE_REASONING_V1.md`）给出实际保证输入、
名义域、模型、查询、显式假设与生成Session接入；阿瓦隆和故障使用同一纯后端。
自然语言与递归心理归因留给后续模型。

局部约束指南（研究仓路径：`docs/guides/AUTHOR_LOCAL_CONSTRAINTS_V1.md`）说明 C0 结构化保证、
实际本人输入与通用纯传播。局部心智指南（研究仓路径：`docs/guides/AUTHOR_LOCAL_COGNITION_V1.md`）
说明生成接入、历史复核与独立软策略。局部固定点与完整身份模型分别选用。
