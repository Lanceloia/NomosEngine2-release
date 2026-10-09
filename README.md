# NomosEngine2

让作者写世界规则，而不是为每一种玩家选择手写剧情树。
规则、能力绑定和开局数据经过编译，得到可以真实行动、结算和读回的世界。
长期目标是支援RPG/TRPG沙盒；当前以狼人杀与有限冰宫冒险检验编译器及运行内核。

**状态：发行基线重建中，尚非验收完成的发布版。**
六项审计缺陷已修复并独立复核；两个世界已从 wheel 独立运行。
性能短门因噪声暂无法判定，最终集成与发行接受仍待完成。
不要把本目录整洁当作正确性证明。进度与来源见[重建记录](docs/RECONSTRUCTION.md)。

## 运行

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m nomos_examples werewolf
```

输入当前编号、`seat B`换席或`quit`；每轮自动显示本地视图，不接受`view`。
该终端由同一受信控制者切换席位，不提供多人登录身份认证。
M1作者bundle随安装包分发，入口不依赖仓库工作目录：

```bash
.venv/bin/python -m nomos_examples everflame
```

M1的规则、区域和开局路径见[作者地图](docs/AUTHORING.md#m1-文件地图)；
这个玩家呈现入口接受`view`重看本人已授权信息。
当前只实际验证Python 3.14.4；`>=3.11`是语言版本要求，不代表全部平台已测。
仅本地仓库，尚未创建新的GitHub远端或发布包。

## 代码地图

| 路径 | 职责 |
| --- | --- |
| `src/nomos_c0/` | 文件前端、名义类型与checked IR、绑定及可玩Session控制 |
| `engine/kernel/src/nomos_kernel/` | 当前态准入、owner贡献、因果/due、隔离与原子发布 |
| `src/nomos_t0/` | 对同一编译Program实际执行有限行动见证，不另模拟世界 |
| `src/nomos_c0/examples/` | 编译器区别案例与狼人杀作者声明 |
| `src/nomos_examples/everflame/` | 随安装包分发的M1有限改编规则、控制与开局 |
| `tests/`、`engine/kernel/tests/` | 中性短合同测试；不以整局代替底层能力测试 |
| `tools/` | 正常计时、画像与作者审计；不属于玩家知识入口 |

## 改一条规则，会发生什么

```bash
.venv/bin/python tools/release_rule_edit_demo.py
```

此命令在内存中只给女巫救人分支增加 `actor.name != scene.pending_attack`。
Assets 和十步行动见证不改，两次重新编译并使用同一真实 C0/K0 管线：
演示开局的B是女巫，普通终端默认B是村民；它们是两份明确不同的Assets。

| 同一见证 | 原规则 | 禁止自救 |
| --- | --- | --- |
| 第1–9步 | 发布12条 Action/Event 来源 | 相同发布前缀 |
| 第10步 B 救自己 | 成功、目标达成 | K0 not-admitted，不发布 |

工具不是新的规则执行器，不修改文件，不把结局写进 Source。
`--json` 显示完整发生依据。想亲手编辑作者文件，见[规则编辑](docs/AUTHORING.md)。

## 从哪里读

- [架构与代码](docs/CODE_MAP.md)：从作者声明到真实发布的路径。
- [选定语义](docs/SEMANTICS.md)：维护哪些合同、明确不承诺什么。
- [C0](src/nomos_c0/README.md)、[K0](engine/kernel/README.md)、[T0](src/nomos_t0/README.md)：各层入口。
- [测试与测量](docs/TESTING.md)：具名短门、安装门和性能返回条件。
- [重建记录](docs/RECONSTRUCTION.md)：已修缺陷、未知项与尚欠返回门。

## 长期方向

希望作者描述世界规律、人物能力和开局，剧情成为实际选择与结算留下的历史，
而不是预先覆盖所有分支的树。未来可由 LLM 提议行动、生成可检查的资产或担任叙事 DM，
但权威状态和规则准入仍交给受检内核；LLM 不直接改私态或宣布结局。
当前尚无这条 LLM 管线，也不是完整 TRPG 主持人。

## 归属与权利

Owner负责项目愿景、问题定义、语义裁决与亲自验收；后期主要代码由Codex及协作者
实现或审阅。不能据本项目认领所有代码都是Owner手写。
原创引擎材料保留权利；M1改编作者资产另有CC BY-SA 4.0条款，
二者不能混成一份授权。详见[权利说明](RIGHTS.md)。
