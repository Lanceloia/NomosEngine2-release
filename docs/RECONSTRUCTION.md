# 发行重建记录

状态：B01–B04独立接受；B05已集成；两个wheel消费者和Law编辑已运行。
性能短门已按Owner新预算接受、最终整局尚欠；候选技术范围与陌生读者核对已完成，
尚无总发行接受。旧噪声硬门的inconclusive记录保留。

## 来源与边界

- 上游研究仓库：`/mnt/d/nomosengine2`，提取提交`4d2164c2d`。
- 审计快照：`5a2318c72b7f3658bb99e9e93a7f5c6787e6b199`，Gauss独立复现六项finding。
- 冻结对照：`83c2d964213d1865b6070434b53f7fdf408f32f8`，不修改。
- 只提取C0/T0、K0、核心短测试、当前作者样例和少量测量工具。
- 不复制历史ZIP、角色/队列路由、私有机器配置、旧Showcase或Web。
- 本仓库自持安装，不得导入研究树或冻结树作为运行回退。

## 成组施工

| 批次 | 目标 | 状态 |
| --- | --- | --- |
| B00 | 新仓库独立安装/Compile/Start/submit，记录真实origins | baseline_verified |
| B01 | K0动态opening隔离、pre_due纯查询重入与原子边界 | reviewed |
| B02 | 精确owner字段写路径，不能被同类型参与者洗掉 | reviewed |
| B03 | 纯定义按键更新词法作用域、Action/Event分类解析 | reviewed |
| B04 | 输出首错顺序、候选/控制预算故障分类 | reviewed |
| B05 | IR执行计划与生成后端统一组织，删除替代旧路径 | independently_reviewed |
| B06 | wheel独立环境、两个作者消费者、工程性能门及一次整局集成 | installed_consumers_verified；短门按新预算接受，整局待验 |
| B07 | 中文说明/导航、诚实演示与贡献、CI、陌生读者验证 | 陌生读者已试跑并修文档；CI本地门通过，远端未跑 |

六项必修缺陷的修复已写入本仓库，K0/C0已独立复核；后续发行门仍欠。
最终入口核查又发现初次提取带入旧独立catalog；已按
[唯一入口清理](CURRENT_ENTRY_HARD_CUT.md)删除适配闭包并保留有效K0反例，独立61项及
wheel入口核对已通过。最后完整性能轮按旧门两组均inconclusive，
Owner随后批准10%/六对预算，已有八对数据重判短门通过，整局待验；
测量工具生命周期清理只跑短假对象反例，不改变原返回门，详见返回记录。
源代码提取和短门绿色不是重构已经完成。
本仓库的维护摘要见[语义](SEMANTICS.md)、[测试](TESTING.md)、[作者编辑](AUTHORING.md)。
上游完整审计历史使用`RELEASE_SELECTED_SEMANTIC_CONTRACT_V1.md`与
`RELEASE_CORRECTNESS_AUDIT_V1.md`，不作为运行或安装依赖。

修复证据：[K0事务](KERNEL_TRANSACTION_REPAIR.md)、
[精确写权](OWNER_WRITE_AUTHORITY.md)、[C0语义](C0_SEMANTIC_REPAIR.md)。
本批安装/迁移/性能待验：[返回记录](INSTALLATION_AND_PERFORMANCE_STATUS.md)。

## B00证据

独立环境`/tmp/nomosengine2-release-dev`使用Python 3.14.4、PyYAML 6.0.3；
在`/tmp`清除PYTHONPATH/PYTHONHOME并用`python -I`验证：六席Source成功Compile、
Assets成功Start，A提交当前投票offer后得到真实Action ref 1和本人投票记录。
已加载的`nomos_*`模块均来自本仓库，不从研究树或冻结树导入。

具名program_phases/source_bundle/causal_declaration_hard_cut/kernel_import_boundary
四模块：59 passed（9.91秒）。M1 bundle也已Compile/Start；第一次短行动脚本
因猜错entry名退出，不能记作M1运行通过，真实M1集成仍在B06。

初始提取基线仍含审计确认的六项缺陷。B01新增短反例在原基线上9 failed、1 passed，
用于证明缺陷存在，而非把初始仓库当作正确发行版。

## 测试

每次pytest显式选具体模块或nodeid；不默认全目录、不开多个独立pytest进程。
短门优先，长M1路线只在最终集成/性能门运行。测试未知、未测不能写成通过。
测量Compile/Start/Run分开，固定八对fresh Session AB/BA：配对中位回退≤10%，
且至少六对回退≤10%；噪声只诊断，不追加测量。旧门结果保留，重判另存带版本报告。
必要正确性代价需明确取舍，不改阈值，不删除保障来伪造提速。
