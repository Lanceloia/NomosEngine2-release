# 代码导览

建议先读根 README 和[语义说明](SEMANTICS.md)，不要从最大文件开始猜架构。

## 沿一条救人规则读代码

1. **作者规则**：[狼人杀 Lib](../src/nomos_c0/examples/three_seat_werewolf_v0.lib.yaml)的
   `action.witch_intervene`。`save_choice` 内的条件决定救人是否被世界许可，
   不是演示工具决定是否成功。
2. **编译与绑定**：[compile_owner_graph](../src/nomos_c0/owner_graph_v1.py)
   检查世界声明并构建 Program；[行动绑定](../src/nomos_c0/composable_action_v1.py)
   把已检查的规则、参与者和输出接入 K0。
3. **实际提交**：[Session](../src/nomos_c0/program_runtime_v1.py)将当前选项提交到
   [K0 原子会话](../engine/kernel/src/nomos_kernel/_atomic_inmemory_session.py)，
   后者重核当前态并发布实际发生。
4. **实验与证据**：[对照工具](../tools/release_rule_edit_demo.py)只改一条内存规则，
   [T0](../src/nomos_t0/witness_v0.py)从当前选项执行同一行动见证并记录来源。
   [T0 短测试](../tests/nomos_t0/test_witness_v0.py)检验有限见证报告的合同。

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
| 生成优化 | `invariant_execution_v1.py` | `_execution_emission.py`及[维护边界](EXECUTION_BACKEND.md) |
| 开局/规则隔离 | `program_start_v1.py` | `engine/kernel/src/nomos_kernel/_owner_state_runtime.py` |
| 一次真实提交 | `program_runtime_v1.py`的submit | `_atomic_inmemory_session.py`的事务与因果闭包 |
| 候选与NPC | `private_actor_binding_v1.py`、`finite_appraisal_v1.py` | 明确的席位读域、实际 K0 重核 |
| 见证检查 | `src/nomos_t0/witness_v0.py` | `author_check_v0.py` |
| 应用入口 | `src/nomos_examples/__main__.py` | `owner_graph_play_v1.py` |

C0 源码下的相对文件名均指 `src/nomos_c0/`。
生成器仅共享代码发射机械组织；不得把领域规则塞进 compiler 或 helper。
命名类型、IR、执行计划、真实当前态验证各有职责，不以新增万能层掩盖重复权威。

六项缺陷及已修反例见[重建账](RECONSTRUCTION.md)，
安装与测试入口见[测试指南](TESTING.md)。当前 Web 在独立仓库，消费冻结版；
此发行候选未自动替换其依赖，也不复制前端作为内核的一部分。
