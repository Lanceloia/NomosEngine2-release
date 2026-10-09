# 发行重建记录

状态：B00已独立安装并执行狼人杀Action；B01开始，尚无发行接受。

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
| B01 | K0动态opening隔离、pre_due纯查询重入与原子边界 | in_progress |
| B02 | 精确owner字段写路径，不能被同类型参与者洗掉 | pending |
| B03 | 纯定义按键更新词法作用域、Action/Event分类解析 | pending |
| B04 | 输出首错顺序、候选/控制预算故障分类 | pending |
| B05 | IR执行计划与生成后端统一组织，删除替代旧路径 | pending |
| B06 | wheel独立环境、两个作者消费者、预设性能门及一次整局集成 | pending |
| B07 | 中文说明/导航、诚实演示与贡献、CI、陌生读者验证 | pending |

六项已证明缺陷未闭合时不能通过发行门。源代码提取只是起点，不是重构已经完成。
详细规范和区别例保留在研究仓库的`RELEASE_SELECTED_SEMANTIC_CONTRACT_V1.md`与
`RELEASE_CORRECTNESS_AUDIT_V1.md`；本仓库的现行维护规范将在B05/B07收束。

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
测量Compile/Start/Run分开，四组fresh Session AB/BA：配对中位回退≤5%，且至少三组
回退≤5%；噪声比最大/最小>1.10时最多追加四组，仍不稳记inconclusive。
必要正确性代价需明确取舍，不改阈值，不删除保障来伪造提速。
