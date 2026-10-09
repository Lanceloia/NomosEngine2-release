# NomosEngine2

让作者写世界规则，而不是为每一种玩家选择手写剧情树。
规则、能力绑定和开局数据经过编译，得到可以真实行动、结算和读回的世界。
长期目标是支援RPG/TRPG沙盒；当前以狼人杀与有限冰宫冒险检验编译器及运行内核。

**状态：发行基线重建中，尚非验收完成的发布版。**
已有实现被提取为自持基线，但六项审计缺陷还未修复；性能及独立打包门尚未通过。
不要把本目录整洁当作正确性证明。进度与来源见[重建记录](docs/RECONSTRUCTION.md)。

## 运行

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m nomos_c0.owner_graph_play_v1 \
  --lib src/nomos_c0/examples/three_seat_werewolf_v0.lib.yaml \
  --ports src/nomos_c0/examples/three_seat_werewolf_v0.ports.yaml \
  --source src/nomos_c0/examples/six_seat_werewolf_v0.source.yaml \
  --assets src/nomos_c0/examples/six_seat_werewolf_v0.assets.yaml
```

该终端由同一受信控制者切换席位，不提供多人登录身份认证。
M1作者bundle已提取，安装资源入口仍在重建；暂用仓库内路径：

```bash
.venv/bin/python -m nomos_c0.owner_graph_play_v1 --player-view \
  --bundle packages/thawed_everflame_remaster/author/world.bundle.yaml
```

当前只实际验证Python 3.14.4；`>=3.11`是语言版本要求，不代表全部平台已测。
仅本地仓库，尚未创建新的GitHub远端或发布包。

## 代码地图

| 路径 | 职责 |
| --- | --- |
| `src/nomos_c0/` | 文件前端、名义类型与checked IR、绑定及可玩Session控制 |
| `engine/kernel/src/nomos_kernel/` | 当前态准入、owner贡献、因果/due、隔离与原子发布 |
| `src/nomos_t0/` | 对同一编译Program实际执行有限行动见证，不另模拟世界 |
| `src/nomos_c0/examples/` | 编译器区别案例与狼人杀作者声明 |
| `packages/thawed_everflame_remaster/author/` | M1有限改编的模块化规则、控制与开局 |
| `tests/`、`engine/kernel/tests/` | 中性短合同测试；不以整局代替底层能力测试 |
| `tools/` | 正常计时、画像与作者审计；不属于玩家知识入口 |

本轮将进一步统一生成后端的维护组织，保留必要优化，不保留旧合同兼容链。

## 归属与权利

Owner负责项目愿景、问题定义、语义裁决与亲自验收；后期主要代码由Codex及协作者
实现或审阅。不能据本项目认领所有代码都是Owner手写。
原创引擎材料保留权利；M1改编作者资产另有CC BY-SA 4.0条款，
二者不能混成一份授权。详见[权利说明](RIGHTS.md)。
