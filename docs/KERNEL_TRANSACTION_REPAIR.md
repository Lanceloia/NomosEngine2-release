# K0开局与pre-due边界修复

状态：B01 technically_reviewed；本地有限发行返回见[收束](RELEASE_BASELINE_CLOSURE.md)。

## 合同与实现

- 静态owner、开局Object与Actor共用`_validate_opening_state`。可选opening hook
  只拿递归隔离的临时值；返回后按结构比较，改写输入即拒绝。权威state仍由既有candidate
  隔离/验证/发布。即使hook保留自己的输入也不能改调用者或Session。
- opening hook以当前实际属性检查，不能依赖可被Python Protocol缓存的旧结构判定。
  这不是旧合同兼容，也不允许不合法hook降级；非callable声明直接拒绝。
- `begin_pre_due`的到期组选择和Action-value投影均进入settling guard。
  有合法due边界后，投影缺陷或嵌套转移沿用fatal边界；时间、debt、phase和历史只在
  全部计算成功后发布。没有due仍是无写入、非fatal的有限拒绝。
- 不改身份、形成规则、时间模型或恢复合同，不修改冻结runtime。

## 验证

原提取基线上两组新反例9 failed、1 passed，确实复现原缺陷。
最终短门增加静态opening和显式不可调用hook覆盖，共89项：

```bash
python -m pytest -q \
  engine/kernel/tests/test_opening_validation_isolation.py \
  engine/kernel/tests/test_pre_due_transaction_boundary.py \
  engine/kernel/tests/test_transaction_state_snapshots.py \
  engine/kernel/tests/test_dynamic_individual_owner_v1.py \
  engine/kernel/tests/test_dynamic_actor_v1.py \
  engine/kernel/tests/test_event_jump_inmemory.py
```

修改的两个实现和两个新测试Ruff通过。未运行长M1路线；B06再作必要集成/性能门。
本片仅关闭F04/F05，不宣称其余审计缺陷或整体发行返回门已通过。

Gauss在初次exact `2354da24b29d4a83a867daebabded3cd1706f656`独立跑87项（1.57秒），
发现显式`None`被误认为缺失。现使用独立缺失sentinel，显式None/int均拒绝；
新增两个短反例。最终接受须以修正后的exact独立复核为准。

最终代码`1ff9e1127e715c3f28014ae808019f2d25f46c0b`：writer六模块89 passed
（1.60秒）；同一Gauss独立按上述命令复跑89 passed（1.53秒）、show-check通过，
无剩余finding。此次接受不包含同期C0工作树改动。
