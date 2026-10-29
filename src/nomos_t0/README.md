# T0：运行迹见证检查

作者可以先叙述希望发生的故事，再寻找允许这些行动与后果成立的规则。
T0的长期路线是从创作样例整理约束、提出规则候选并通过真实运行检验。
当前工具检查一条有限的命名输入见证，直接运行C0生成的Python产物。

```text
Lib / Source / 可选AI与认知声明 -> C0 -> world.py
world.py / Assets / witness -> T0 -> 实际发生前缀与结构化结果
```

## 运行

```bash
mkdir -p build/python-codegen
.venv/bin/python -m nomos_c0.python_codegen \
  src/nomos_c0/author_abilities/examples/avalon.lib.yaml \
  src/nomos_c0/author_abilities/examples/avalon.source.yaml \
  build/python-codegen/avalon.py
.venv/bin/python -m nomos_t0 \
  build/python-codegen/avalon.py \
  src/nomos_t0/examples/current/avalon.yaml \
  --assets src/nomos_c0/author_abilities/examples/avalon.assets.yaml --json
```

编译和运行是两个阶段。T0只需要受信生成模块、运行库、开局与见证文件；
`--assets`必须显式提供，支持YAML/JSON、注释和`!table`。另一份开局可使用同一模块。
生成时用`--ai`/`--cognition`选择独立配置；strategy步骤使用该模块实际携带的CONTROLLERS。
运行时不重新读取Lib/Source，也不重新编译AI。

```yaml
schema: nomos.witness
budget: 1
steps:
- actor: traveler
  action: TryPass
  inputs: {route: {object: ritual_door}}
  expect_result: {tag: Blocked}
expect:
- {actor: {name: traveler, fields: {position: threshold, energy: 2}}}
```

该短例使用[passage声明](../nomos_c0/author_abilities/examples/passage.lib.yaml)，
正常受阻仍发布一次有成本的Action。

## 输入与控制

`inputs`按生成的名义编解码函数绑定，支持记录、Variant、Optional、集合和序列。
`{actor: a}` / `{object: book}`绑定当前开局身份；实际人物的引用权限继续核对。
新生控制或引用使用`{formed: {source: 实际形成来源, ordinal: 1}}`：
按该Source形成的实际同类人物或物件排序选择；形成库存本身不授予行动者知识。
这些标记仅在声明为ref的槽解析，普通记录中的同名字段按其声明类型处理。

`{pick: {key: route_name}}`从当前有限member域选择唯一匹配，空字典可匹配任意当前成员。
工具使用生成表单解析真实依赖和derive；可绑定的后序明确输入也参与候选约束检查。
零项报不可选，多项报歧义；工具不搜索未来pick、不代换其他行动。
最后的完整输入仍经过正式prepare/submit。

| 步骤 | 实际含义 |
| --- | --- |
| `actor/action/inputs` | 准备并提交命名能力；正常False/Blocked仍发布并付费 |
| `request: {process, point, ordinal?}` | 选择当前真实过程请求，再提交该点输入 |
| `next: {status, actor?}` | 核对生成运行库的调度结果，保存实际机会凭据 |
| `defer: actor` | 使用工具已取得的机会交还控制，只产生控制记录 |
| `strategy: actor` | 提交此刻本人实际策略提案 |
| `advance: 时间/null` | 无人物调度时显式推进到时刻/下一到期 |
| `cancel: {actor, activity, ordinal?}` | 选择本人实际活动凭据，做付费取消 |

每步都使用当前Session事实，出错立即停止；其他人物行动与时间推进显式写在见证中。
T0是受信多席工具，见证与规则分开保存。

## 断言与报告

`expect.actor.fields`只允许人物自己的可读字段；记录可按部分字段匹配，Set按名义集合相等比较。
`expect.ending`核对当前终局状态及本人可得结果；`expect.published`核对选定Source的实际发生数量。
结果的记录/Variant可用部分字段匹配，例如`expect_result: {tag: Blocked}`。

报告含`stage`、`stop_reason`、`goal_status`、`steps_completed`、`requested_step`、`published`、`detail`。
发生前缀来自真实Session.history，保留原始Action/Event家族、Source、因果前驱及活动形成来源；
Action另外保留实际行动者，控制等待不伪装成世界发生。
结果断言失败时，该步已发布的Action仍保留；晚期结算缺陷按实际事务整根回滚。
工具只报告这条见证的首次未成立处，不据此推断整个世界无解或猜测源码缺哪条规则。

退出码：0=见证与断言成立，2=输入/产物/开局/目标不受支持，3=本条见证未成立，4=结算缺陷。
`goal_status`为`met`、`not_met_within_bound`或`unknown`；前缀已满足目标不代表后缀成立。
预算耗尽、世界提前关闭、候选歧义、零写拒绝、付费失败与fatal缺陷分别报告。

API：[check_witness](witness.py)接受`CompiledProgram, assets, case, controllers=...`。
具名门：命名输入（研究仓路径：`tests/nomos_t0/test_named_witness_v1.py`）、
三消费者（研究仓路径：`tests/nomos_t0/test_three_consumer_witness_v1.py`）、
隔离产物（研究仓路径：`tests/nomos_t0/test_generated_artifact_witness_v1.py`）。
