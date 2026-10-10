# 规则编辑演示

作者编辑的是世界声明；行动见证是独立验证输入，不是剧情程序。
先用 `python -m nomos_examples werewolf` 熟悉当前菜单、换席与自动显示的只读视图。
狼人杀不接受 `view` 命令；编号、`seat B` 和 `quit` 才是此入口的输入。

## 一条 Law 的前后对照

运行 `python tools/release_rule_edit_demo.py`，工具只在内存增加一个条件，
两次真实编译、开局和回放；文件不会被改写。
默认输出简短结果，`--json` 给完整发生、来源和形成依据。
演示使用独立的 `werewolf_witch_b.assets.yaml` 开局，B是女巫；普通六席终端默认B是村民。
不是同一开局自动改变了职业。

要手改，在 `src/nomos_c0/examples/three_seat_werewolf_v0.lib.yaml` 中定位
`lawdefs → action.witch_intervene → body.value.guard.require → save_choice`。
在其 `if.then.require` 的 `victim_exists` 后增加：

```yaml
- not_self: actor.name != scene.pending_attack
```

它只限制救人分支，不限制不用解药。相同 Assets/case 下，原版第10步救自己成功；
编辑版第10步仍有「救人」候选，但 K0 在准入时拒绝，不发布行动或执行效果。
当前 Source 的 `offers.when` 与 Lib 的 `guard.require` 分开声明，实验只改后者。
这证明准入变化，不证明公开限制能自动派生可用选项；这项联动仍须研究，
也不能简单把隐藏 guard 暴露给菜单。见[展示矩阵](SHOWCASE_MATRIX.md)。

```bash
python -m nomos_t0.author_check_v0 \
  --lib src/nomos_c0/examples/three_seat_werewolf_v0.lib.yaml \
  --ports src/nomos_c0/examples/three_seat_werewolf_v0.ports.yaml \
  --source src/nomos_c0/examples/six_seat_werewolf_v0.source.yaml \
  --assets src/nomos_t0/examples/werewolf_witch_b.assets.yaml \
  --case src/nomos_t0/examples/werewolf_self_heal_b.case.yaml
```

原版 exit 0，修改后目标未达成 exit 3。撤回实验条件后重新 Compile 才恢复原规则。
T0 的结果不是全部玩法不可达证明，也不保证指出唯一失败 guard。

## 修改人数与职业

六席 Source 的封闭实例列表控制有哪些 Actor/能力和席位，Assets 的玩家/角色表、
各人的私有职业与药水状态须满足同一开局合同。
扩为八席时同时增加两名实例及其合法 opening；不能只画两个菜单按钮。
换女巫时同步公开角色分配、对应私有 own_role 和药水字段。
相关开局不一致会在 Start 拒绝，而不是靠 host 修正。

注意历史文件名 `three_seat_*` 的 Lib/Ports 也被六席 Source 复用。
文件名不是世界大小或职业权限的权威。当前不提供图形化资产编辑器，
手工同步这些开局字段仍是已知易错点，不把它描述成一键扩人数。

共享 Lib 现在用 `type_aliases` 统一轮数、参与者名字、职业与票表的重复类型，
条件用可读表达式，布尔查询用语义谓词。范围修改应在对应类型定义处进行，
不逐字段复制；[类型与规则写法](C0_LIB_TYPE_ALIASES_V1.md)说明编译和校验边界。

## M1 文件地图

安装资源在 `src/nomos_examples/everflame/`：

| 路径 | 内容 |
| --- | --- |
| `model.lib.yaml` | 名义状态类型和端点签名 |
| `capabilities.ports.yaml` | 精确读写与有限参与者 |
| `opening.assets.yaml` | 冰宫开局、人物、资源与种子 |
| `source/rules/` | 可复用 Law 体 |
| `source/bindings/`、`source/participant_bindings.yaml` | 实际能力与参与者绑定 |
| `source/regions/` | 区域组合 |
| `source/control/` | 席位、投影、有限 Appraisal 与 GameForm |
| `world.bundle.yaml` | 唯一显式装配清单 |

M1 是原冒险的有限区域改编，不是完整几何或通用 TRPG。
原作与改编授权见[署名](../src/nomos_examples/M1_ATTRIBUTION.md)。
