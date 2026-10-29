# C0：高级作者规则编译器

C0 将作者声明编成可直接执行的 Python 世界规则。作者书写世界允许发生的规则，独立见证交给 [T0](../nomos_t0/README.md)。

[Python 生成后端](python_codegen/README.md)将受检声明自动组合为可执行世界，减少作者接线。
桌面、终端及见证检查消费同一产物。旧K0与解释执行链已删除，当前范围与返回点见CURRENT（研究仓路径：`docs/CURRENT.md`）。

```text
Lib + Source -> 检查 / 语义 IR -> AuthorProgram 编译计划
编译计划 + 可选独立 AI / 认知 / 呈现声明 -> 生成 Python
生成 PROGRAM + Assets -> Start -> nomos_runtime.Session
当前选择 -> 生成规则 / 原子提交 -> 实际发生 / 结果 / 本人读回
```

现行语言、合同和小样本见[author_abilities](author_abilities/README.md)。
[狼人杀](author_abilities/examples/werewolf.lib.yaml)、[阿瓦隆](author_abilities/examples/avalon.lib.yaml)、
[M1 冰宫](author_abilities/examples/everflame/README.md)和[璀璨宝石基本规则](author_abilities/examples/splendor/README.md)使用同一编译链。

## 输入和入口

Lib 声明类型、实体、关系、查询、能力、过程和世界规律；Source 选择实例、参数、订阅、时间及控制机制；Assets 提供本局初态。模块通过显式 `imports` 装配。
策略及其控制绑定放在独立 AI 文件，世界不依赖它才成立。
表格数据使用共享表头（研究仓路径：`docs/guides/AUTHOR_DATA_TABLES_V1.md`），展开后继续受名义类型检查。

```bash
python -m nomos_c0.author_abilities src/nomos_c0/author_abilities/examples/werewolf --plan
python -m nomos_c0.author_abilities src/nomos_c0/author_abilities/examples/avalon --plan
python -m nomos_c0.author_abilities src/nomos_c0/author_abilities/examples/everflame/world --plan
```

`--plan` 显示已检查的能力/机制计划，不绑定 Assets。
先用[Python 生成器](python_codegen/README.md)构建，再用[运行库 CLI](../nomos_runtime/README.md)
或[桌面](../nomos_play/README.md)运行；M1 默认玩家控制，`--manual` 用于受信调试。
Program 不携带本局 Assets；多个 Start 各自形成独立身份、状态、报告和义务。
生成器可加`--optimization-report build/optimization.md`查看优化采用／保留原因及作者位置；
正文分析说明（研究仓路径：`docs/design_notes/COMPILER_ANALYSIS_AND_REMARKS_V1.md`）解释依赖、失败和资源界。

## 实现地图

| 层 | 入口 |
| --- | --- |
| 文件、表格与装配 | [author_document_v1](author_document_v1.py)、[共享表格读取](../nomos_runtime/document_tables.py)、[assembly](author_abilities/assembly.py) |
| 类型与值 | [value_types](author_abilities/value_types.py)、[values](author_abilities/values.py) |
| 编译字面量与固定值 | [literal_values](author_abilities/literal_values.py)、[opening](author_abilities/opening.py)、[constant_values](author_abilities/constant_values.py)、[constant_folding](author_abilities/constant_folding.py) |
| 纯表达式与实体读取 | [expressions](author_abilities/expressions.py)、[entity_reads](author_abilities/entity_reads.py) |
| Python 生成 | [python_codegen](python_codegen/README.md)；[共享事务设施](../nomos_runtime/world.py)，桌面/T0/CLI 已接入 |
| 编译分析与报告 | [expression_analysis](expression_analysis.py)缓存一次编译的正文摘要；[optimization_report](optimization_report.py)保存实际生成决策，不进入运行产物 |
| 查询物理选择 | [query_plan](query_plan.py)选择支配共享；[query_inline](query_inline.py)选择有体积上限的标量叶正文内联；参数／结果／预算检查保持 |
| 常量类型分派 | [variant_query_plan](variant_query_plan.py)识别直接match参数的literal case；生成器在检查全部参数后省掉这些case的函数调用，活动分支与原预算保持 |
| 相关扫描分组 | [grouped_latest_plan](grouped_latest_plan.py)按实际词法绑定及字段识别同键严格最新筛选；生成索引保留顺序、重复／并列及虚拟预算 |
| 命名输入与后果 | [inputs](author_abilities/inputs.py)、[frontend](author_abilities/frontend.py)、[effects](author_abilities/effects.py) |
| 分阶段执行 I/O 计划 | [execution_io](author_abilities/execution_io.py)记录字段/身份/信息及机制依赖；[program](author_abilities/program.py)规范化词法 context 输入 |
| 信息与过程 | [information](author_abilities/information.py)、[disclosures](author_abilities/disclosures.py)、[processes](author_abilities/processes.py) |
| 因果、时间、形成 | [reactions](author_abilities/reactions.py)、[activities](author_abilities/activities.py)、[periodic](author_abilities/periodic.py)、[formation](author_abilities/formation.py) |
| 机制与终局 | [settlements](author_abilities/settlements.py)、[scheduling](author_abilities/scheduling.py)、[strategies](author_abilities/strategies.py)、[play](author_abilities/play.py)；[生成过程](../nomos_runtime/processes.py)、[稳定终局](../nomos_runtime/terminals.py) |
| 编译计划与运行产物 | [program](author_abilities/program.py)、[生成器](python_codegen/world.py)、[运行 Session](../nomos_runtime/world.py) |

Compile 拒绝没有 Program，Start 拒绝不返回半局；非法/过时提交零写拒绝。
正常受阻由规则发布结果，准入后的结算缺陷整次回滚并保留 fatal 边界。
World 读取许可与 Actor 本地知识分开，策略提案仍由当前生成 Session 检查。
预算是有限运行诊断，游戏结束由作者终局谓词决定。

历史三消费者迁移的范围与实测见证据账（研究仓路径：`docs/coordination/C0_THREE_CONSUMER_EVIDENCE_V1.md`）。
旧OwnerGraph/Ports与配套消费者已按原路径封存于归档（研究仓路径：`archive/README.md`），安装只提供现行链。
