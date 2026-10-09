# C0 语义修复

状态：B02–B04 technically_reviewed；整体发行门仍未通过。
本轮不修改冻结运行时，也不增加兼容分支。

## 名称与纯定义

- Action 与 Event 是不同入口命名空间；解析形成边时同时使用类别和名称。
  无关 Event 同名不能遮蔽 Action；同名 Action 触发同名 Event 也合法。
  不能把 Action 的来源重贴成 Event，前驱/source/type 仍核真实 K0 发布记录。
- `update_matching` 的行别名只作用于 `set` 的字段值。collection/matching
  仍处于调用方作用域，不能引用未形成的行别名；参数遮蔽、外部捕获仍拒绝。
  纯定义不能扩大调用方字段写许可。
- 准入输出是完整输出的有序子集：按声明顺序筛选，而不是遍历哈希集合。
  未选输出不求值；选定输出的首个错误与完整求值的声明顺序一致。

## 形成证明不规定写 owner 的数量

已删除 `EventFormationPort.result_owner`，不提供别名或旧构造兼容。
该字段没有语义消费者，原单贡献 owner 限制与形成来源无关。
形成证明继续核真实 source、event type、前驱、law、due scheduler 和所选机制。
效果写域与原子提交由 C0 端口/K0 结算核对，不能从形成证明反推写许可。

实际 Parcel due 正例：同一个 occurrence 更新 Scene 的到达记录和 Sender 的来源字段；
两项写入均可从当前 owner 读回，形成迹只记录一个 Event。
另有零 contribution 注册的 binding-only 反例，证明形成绑定不要求贡献 owner；
它**不是**零效果 Event 的整条运行证明。

当前可选形成注解仍是有限合同：一个 due 结果入口只声明一个 Action scheduler；
一般原生 causal profile 的 trigger event type 必须能唯一确认所声明来源。
多 scheduler 的形成边语法、共享 event type 下的 source-filter 证明尚未提供；
不将它们悄悄放宽为任意原生 profile 的来源证明，也不禁止未注解程序的合法 K0 运行。

## 候选故障与控制预算

动态 Actor 菜单按声明隔离 `C0ValueStateError`，fault 指向实际 entry/label；
本人 owner 读取/验证仍位于整体边界，不吞非法 owner。其他合法候选可正常提交，
菜单读取不写世界。自动 Appraisal 仍遇 fault 拒绝评分，不能推断为自动忽略坏选项。
静态菜单容量保障不变，没有截断菜单或绕过完整容量核对。

`C0ControlBudgetExceeded` 是可识别的控制停点，不是结算 fatal。
1024 次额度统计控制循环（包括 due 边界），不等于 1024 个 NPC Action。
本次调用已发布的前缀保留，下次 `continue_form` 可从真实当前态继续。
T0 单独报告 `control_budget_exhausted`，保留前缀和 `not_met_within_bound`；
不把它写成全局无解，也不提高预算来躲避报告问题。

## writer 证据

Python 3.14.4。下列具名模块串行：135 passed，9.17 秒。

```bash
python -m pytest -q \
  tests/nomos_c0/test_formation_namespace_v1.py \
  tests/nomos_c0/test_pure_keyed_update_scope_v1.py \
  tests/nomos_c0/test_admission_output_order_v1.py \
  tests/nomos_c0/test_formation_effect_cardinality_v1.py \
  tests/nomos_c0/test_pure_definition_v1.py \
  tests/nomos_c0/test_keyed_record_update_v1.py \
  tests/nomos_c0/test_event_formation_v2.py \
  tests/nomos_c0/test_event_formation_binding_v2.py \
  tests/nomos_c0/test_event_formation_ir_v2.py \
  tests/nomos_c0/test_program_phases_v1.py \
  tests/nomos_c0/test_due_output_destination_v1.py \
  tests/nomos_c0/test_owner_write_authority_v1.py
```

本轮相关 Ruff 通过；`PYTHONHASHSEED=1` 与 `731` 分别运行输出顺序模块，均 3 passed。
没有以测试数量宣称所有合法作者组合均已证明，没有重跑整局 M1。

候选与控制相邻短门：88 passed，19.18 秒。

```bash
python -m pytest -q \
  tests/nomos_c0/test_dynamic_offer_fault_isolation_v1.py \
  tests/nomos_c0/test_control_budget_v1.py \
  tests/nomos_c0/test_actor_formation_v1.py \
  tests/nomos_c0/test_selected_offer_projection_v1.py \
  tests/nomos_c0/test_appraisal_definition_v1.py \
  tests/nomos_c0/test_authored_graph_boundaries_v1.py \
  tests/nomos_t0/test_witness_v0.py
```

## 独立返回

Gauss对exact `cd0038ffd5e6c1c1d733422285002e2603adad6f`只读复核，
无material finding，独立22项新反例+3项相邻反例，show-check通过。
未跑整局、安装或性能，不将其余writer门计为独立通过。

```bash
python -m pytest -q \
  tests/nomos_c0/test_owner_write_authority_v1.py \
  tests/nomos_c0/test_formation_namespace_v1.py \
  tests/nomos_c0/test_pure_keyed_update_scope_v1.py \
  tests/nomos_c0/test_admission_output_order_v1.py \
  tests/nomos_c0/test_formation_effect_cardinality_v1.py \
  tests/nomos_c0/test_dynamic_offer_fault_isolation_v1.py \
  tests/nomos_c0/test_control_budget_v1.py
python -m pytest -q \
  tests/nomos_c0/test_due_output_destination_v1.py::test_shared_state_type_does_not_grant_another_root_write_permission \
  tests/nomos_c0/test_composable_action_v1.py::test_authored_law_publishes_both_owner_effects_with_one_k0_ref \
  tests/nomos_c0/test_event_formation_binding_v2.py::test_shared_result_source_preserves_distinct_formation_edges
```
