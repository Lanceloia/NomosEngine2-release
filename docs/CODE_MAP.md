# 代码导览

建议先读根 README 和[语义说明](SEMANTICS.md)，不要从最大文件开始猜架构。
首次看项目可先读[实验导览](PROJECT_TOUR.md)，再沿下列路径检查实现。

## 沿一条救人规则读代码

1. **作者规则**：[狼人杀 Lib](../src/nomos_c0/examples/three_seat_werewolf_v0.lib.yaml)的
   `action.witch_intervene`。`save_choice` 内的条件决定救人是否被世界许可，
   不是演示工具决定是否成功。
2. **编译与绑定**：[compile_owner_graph](../src/nomos_c0/owner_graph_v1.py)
   检查世界声明并构建 Program；[行动绑定](../src/nomos_c0/composable_action_v1.py)
   把已检查的规则、参与者和输出接入 K0。
   按符号继续检查：`graph_frontend_v1.check_owner_graph()` →
   `composable_action_v1.compile_composable_action()` →
   `world_binding_v1.bind_world()` → 已绑定行动的 `build_spec()`。
   前端核声明，行动编译生成受检执行表示，世界绑定核对应关系，`build_spec()` 给 K0 注册执行端口。
3. **实际提交**：[Session](../src/nomos_c0/program_runtime_v1.py)将当前选项提交到
   [K0 原子会话](../engine/kernel/src/nomos_kernel/_atomic_inmemory_session.py)，
   后者的 `settle()` 重核当前态并发布实际发生。准入入口是
   [行动绑定](../src/nomos_c0/composable_action_v1.py)的 `_Admission.admit()`：
   `self.program.ir.condition(roots)` 为假时返回 `None`，K0 将它转为 `K0NotAdmitted`。
   `settle()` 在 `_settle_causal_waves()`、不变量与终局检查成功后，才一起替换
   `_states`、`_tape` 等权威字段；准入后异常进入 `K0SettlementDefect` 和 fatal。
   禁自救实验走的是前一个零写拒绝分支，不是后一个回滚分支。
4. **实验与证据**：[对照工具](../tools/release_rule_edit_demo.py)只改一条内存规则，
   [T0](../src/nomos_t0/witness_v0.py)从当前选项执行同一行动见证并记录来源。
   [T0 短测试](../tests/nomos_t0/test_witness_v0.py)检验有限见证报告的合同。

作者诊断由 `program_runtime_v1.py` 的 `author_guard_report()` 检查当前谓词，
`author_diagnostics_v1.py` 渲染命名 clause 和源码位置；交互入口加
`--author-diagnostics` 可在拒绝后显示，见[作者指南](AUTHORING.md#拒绝后如何定位)。
它不改变准入，也不是全部 K0 拒绝原因的历史证明。

作者指南使用历史文件名 `three_seat_*`，但本次六席人数由 Source 和 Assets 声明，
不由 Lib 文件名决定。先看[演示](SHOWCASE.md)，再跟踪上述路径即可。

```text
Lib + Ports + Source ── C0 Frontend ── Program IR ── Bind ── Program
                                                            │
Assets ───────────────────────────────────────────────── Start
                                                            │
                                                 K0 Session ← submit
                                                            │
                                       实际状态 / 来源 / 本人投影
                                                            │
                          终端 / 外部Web          T0有限见证报告
```

| 想了解 | 首读 | 再读 |
| --- | --- | --- |
| 编译阶段 | `src/nomos_c0/owner_graph_v1.py` | `graph_frontend_v1.py`、`program_binding_v1.py` |
| 类型与表达式 | `expression_ir_v1.py`、`composable_value_v1.py` | `nominal_fields_v1.py`、`guard_ir_v0.py` |
| 具名类型与紧凑字段 | `nominal_type_aliases_v1.py`、`nominal_field_declarations_v1.py` | `declarative_nominal_v0.py`及[作者说明](C0_LIB_TYPE_ALIASES_V1.md) |
| 生成优化 | `invariant_execution_v1.py` | `_execution_emission.py`及[维护边界](EXECUTION_BACKEND.md) |
| 开局/规则隔离 | `program_start_v1.py` | `engine/kernel/src/nomos_kernel/_owner_state_runtime.py` |
| 一次真实提交 | `program_runtime_v1.py`的submit | `_atomic_inmemory_session.py`的事务与因果闭包 |
| 候选与NPC | `private_actor_binding_v1.py`、`finite_appraisal_v1.py` | 明确的席位读域、实际 K0 重核 |
| 见证检查 | `src/nomos_t0/witness_v0.py` | `author_check_v0.py` |
| 应用入口 | `src/nomos_examples/__main__.py` | `owner_graph_play_v1.py` |

C0 源码下的相对文件名均指 `src/nomos_c0/`。
生成器仅共享代码发射机械组织；不得把领域规则塞进 compiler 或 helper。
命名类型、IR、执行计划、真实当前态验证各有职责，不以新增万能层掩盖重复权威。

关键取舍与对应反例见[设计说明](DESIGN.md)，
安装与测试入口见[测试指南](TESTING.md)。当前 Web 在独立仓库，消费冻结版；
此发行候选未自动替换其依赖，也不复制前端作为内核的一部分。
