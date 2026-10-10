# C0：作者规则编译器

C0 把有限声明式世界编成 K0 可以准入、原子结算并记录来源的 Action/Event。
作者写规则及开局，不写一串预定剧情；独立行动见证由 [T0](../nomos_t0/README.md)实际执行。
现行 Source 只有 `c0.owner_graph.v6`，YAML 与 JSON 共用合同，无旧 schema 回退。

## 输入与阶段

| 输入 | 职责 |
| --- | --- |
| Lib | 具名字段类型、一行 `TypeName field_name` 声明、名义记录、owner/kind、Law、纯定义与端点类型 |
| Ports | 有限参数、精确字段读写许可及效果目标 |
| Source | 规则绑定、形成关系、候选、席位可见性和 GameForm |
| Assets | 一局人物、物件、位置、资源、时间与随机种子 |

```text
作者文件 → 名义声明与端口检查 → Source 检查 → 类型化 Program IR
                                           ↓ Bind
                                  无开局数据的规则 Program
                                           ↓ Start(Assets)
                                  独立的 K0 Session
                                           ↓
                         read / offers / submit / continue_form
```

Run 不重新读取源码；改规则后要重新 Compile。一个 Program 可启动多个独立 Session。
候选表示可尝试的行动，不保证最终准入；K0 仍检查当前身份、权限、状态和费用。
本人读回与世界 Law 的读域分开，作者审计不能当作玩家视图。

## 可运行输入

```bash
python -m nomos_examples werewolf
python -m nomos_examples everflame
```

狼人杀输入当前编号、`seat B` 或 `quit`；本地视图每轮自动显示，不接受 `view`。
M1玩家呈现入口还接受 `view` 重看已授权信息。
这不是多人登录认证。M1 使用安装包内的多文件 bundle，不依赖仓库工作目录。

规则编辑从[狼人杀文件](examples/THREE_SEAT_WEREWOLF.md)开始。
M1 清单见[world.bundle.yaml](../nomos_examples/everflame/world.bundle.yaml)，
片段按规则、绑定、区域、席位与控制拆分，但只装配一个世界。
清单显式、有序选择；重名及重复整体声明拒绝，不深合并或自动发现文件。

完整文件入口：

```bash
python -m nomos_c0.owner_graph_play_v1 \
  --lib src/nomos_c0/examples/three_seat_werewolf_v0.lib.yaml \
  --ports src/nomos_c0/examples/three_seat_werewolf_v0.ports.yaml \
  --source src/nomos_c0/examples/six_seat_werewolf_v0.source.yaml \
  --assets src/nomos_c0/examples/six_seat_werewolf_v0.assets.yaml
```

## 维护地图

| 层 | 实现入口 | 边界 |
| --- | --- | --- |
| 文件 | [author_document_v1](author_document_v1.py)、[source_bundle_v1](source_bundle_v1.py) | 冻结字节、来源、显式装配 |
| 声明 | [declarative_nominal_v0](declarative_nominal_v0.py)、[declarative_graph_ports_v0](declarative_graph_ports_v0.py) | 名义类型、端点、精确权限 |
| 前端 | [graph_frontend_v1](graph_frontend_v1.py) | 无 Assets、无地址的 IR |
| IR | [program_ir_v1](program_ir_v1.py)、[expression_ir_v1](expression_ir_v1.py) | 类型、阶段、来源、短路 |
| 绑定 | [program_binding_v1](program_binding_v1.py) | 与所选布局绑定，不重解析 Source |
| 开局 | [program_start_v1](program_start_v1.py) | 完整检查后一次建局 |
| 运行 | [program_runtime_v1](program_runtime_v1.py) | 当前态投影、提案、控制；世界写入交 K0 |
| 组合 | [owner_graph_v1](owner_graph_v1.py) | 组合阶段，不提供第二编译链 |
| 执行计划 | [invariant_execution_v1](invariant_execution_v1.py)及名义/合同校验执行器 | checked IR 的专用后端，不缓存世界当前值 |

共同生成组织见[后端说明](../../docs/EXECUTION_BACKEND.md)。
生成代码相等不是正确性的唯一证明，还须从合同构造独立反例。

## 常用声明

- `expr` 是受限文本表达式，不执行 Python；结构化表达式同样进入 checked IR。
- `exists`、`exactly_one`、`none_matching` 保留查询语义与短路；需要数量才计数。
- `unique_by` 检查唯一键，不去重或授予实体身份。
- 有限投影、按键更新/插入、纯定义与输出族减少重复，但不能扩大权限。
- Object/Actor 参与者解析本局真实实例；同 carrier 不代表同 owner 权限。
- 骰子在受检效果/开局构造中产生，读菜单与诊断不掷骰。
- 席位 read、offers、availability 与 presentation 有各自显式读域。
- GameForm 选择 manual/event-jump/action-value 控制；defer 不伪造世界 Action。

Assets 缺省仅为已声明 optional 补 `null`，不猜 `0`、`false` 或空集合。
形成、到场、交付、阅读分别有真实来源链，不自动产生知识。
精确写权及反例见[设计说明](../../docs/DESIGN.md#相同类型不代表相同权威)。

## 失败与范围

Compile/Bind 拒绝没有 Program；Start 拒绝不暴露半局。
K0 not-admitted 为零写、可继续拒绝；准入后结算缺陷整次回滚并 fatal。
候选单项故障可隔离报告；自动策略不能把故障当无需考虑的选项。
控制预算结束保留真实前缀，不等于全局不可达。

选定合同及限制见[语义说明](../../docs/SEMANTICS.md)，
短门与性能口径见[测试指南](../../docs/TESTING.md)。
当前不承诺任意作者语言、完整 UFO、独立 .py 世界发布、公开 save/load、
连续/分支时间、自动心智求解或恶意同进程 Python 沙箱。
原生端点是受信工程入口，不是普通作者文件的 Python 执行通道。
