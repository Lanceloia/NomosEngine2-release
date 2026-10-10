# 显式 Actor 成员候选

适用当前 C0 Program 合同，不新增 K0 类型、世界事实或知识缓存。

```yaml
for_each_participants:
  victim: {selected_members: true, as: person}
label: [{const: 'Observe nearby person'}]
payload: {victim: {ref: person}}
availability:
  ref: resident_current_presence
  when: victim.site == actor.site
```

`person` 是本 Action 的已选闭合成员键，不是目标 owner 视图。成员只来自作者已有
参与者声明，不重复抄名单；动态 Actor family 不接受这种枚举。使用者须明确选择
`selected_members: true`，不能与旧观察集合混用，也不从同形字段猜对象身份。

一般候选从 Actor 自身已取得的集合中生成；此方式适用于作者明确允许由当前状态
筛选的有限互动，例如同区可察觉人物的付费检查。声明成员不证明他们在场、活着、
同意合作或已经被观察。可用性条件仍须由显式 candidate_inputs 读取所选人物当前
字段；标签和 payload 不能借此读取目标私态。没有可用性条件的声明意味着作者主动
公开这些尝试入口，不提供自动的知识安全保证。

C0 编译和独立 Bind 都核对完整成员域、标量别名、所选 payload 与权限；候选生成不
写 owner 或 occurrence。组合工作量仍受 offer 上限约束。提交后 K0 再检查实际参与者、
当前状态和 Law；候选存在不保证准入。IR 中 `collection=None / identity_field=None`
明确表示已选成员键枚举，不是空集合、缺失绑定或兼容旧版的旁路。

短门：`tests/nomos_c0/test_selected_member_candidates_v1.py`，包括独立重新布局／Bind、
无伪知识、当前状态筛选、K0 拒绝不写入、字面 opt-in 与伪成员／别名／身份／family。
