# 唯一作者入口清理

最终返回核查发现初次提取仍带入四个早期catalog：`scene_action_v1`、`scene_due_v1`、
`scene_due_wave_v1`、`scene_due_ordered_v1`。它们接收独立旧Source schema；
wave/ordered还删除字段并转换schema后调用due catalog。这不是现行v6失败后的fallback，
但仍是可导入、随wheel分发的第二作者入口，不符合发行基线的唯一合同。

## 删除范围

删除四个模块、包顶层catalog导出、六份旧due示例及两份旧schema测试。
没有留下alias、schema adapter、可选兼容开关或隐藏的旧编译器。
`compile_owner_graph`、`compile_source_bundle`、现行IR/绑定、
scheduled Scene Event及K0时间/同波/有序微步结算均不依赖这条原型闭包，予以保留。
本次不收窄所选v6能力；删除旧原型不意味着删除内核结算能力。

## 有效反例去向

| 原风险 | 当前验证 |
| --- | --- |
| 未选合并的同owner多写不能丢效果 | K0 `test_same_wave_policy_v1.py`，整次Action回滚且fatal |
| 显式策略须保留两个Event及其效果/来源 | 同模块，独立原生策略与三条真实发生 |
| 策略拒绝或合并后违反owner不变量 | 同模块，检查具体原因、状态/历史/cursor零半提交 |
| 策略错绑source/law端口 | 同模块，Session创建前拒绝 |
| 同刻due重读候选态、逆序失败原子回滚 | 现行 `test_authored_read_due_v1.py` |
| 时间跃迁、来源与有序到期 | K0 `test_event_jump_inmemory.py` |
| 当前Compile/Start/运行边界 | `test_program_phases_v1.py` |

这些短门不再依赖旧schema。旧catalog自身的格式/字段适配测试随已删除合同退役；
不把“删掉红测试”当作修复当前合同。
新增 `test_current_compile_entry_v1.py` 核旧模块不可导入、旧schema被现行编译器拒绝。
CI明确列入两个新增模块；不默认全目录收集。

Python3.14.4下以上五个具名模块串行60 passed（5.09秒），相关Ruff与diff检查通过。
新同波正例最初误把三条发生的fixture预算设成2，先失败再修为3；
三个拒绝反例另核具体cause，防止错误预算让负例假通过。没有修改K0。
此为writer自测，待同一精确候选的独立复核；不是只凭静态闭包分析放行。
Gauss初轮独立60 passed并发现两处证据不足：wave实际旧schema为`c0.source.scene_due.v2`，
不是模块名对应的猜测；错绑负例需分别改sources和law_keys。已修正这两项测试，
不修改核心、现行编译合同或作者资产，待最终精确复验。
结果与精确快照另见[返回记录](INSTALLATION_AND_PERFORMANCE_STATUS.md)。
