# NomosEngine2

**面向规则驱动沙盒的创作工具链：声明世界规则，让行动产生故事。**

沙盒中的玩家可能做出作者没有预料的选择。我们的目标是让作者声明实体、能力、
物件状态和世界规律，由共同的执行内核检查行动并结算后果，让故事成为实际行动留下的历史，
玩家的选择与世界规律共同生成运行历史。TRPG 是重要灵感和验证场景，工具链面向不同形态的沙盒创作。

当前工程重点是声明式作者语言、编译器、规则执行内核和行动见证验证工具。
狼人杀检验规则编辑，M1 冰宫冒险检验观察、资源、行动和时间的共同运行。

## 从这里开始

| 你有多少时间 | 推荐入口 |
| --- | --- |
| 约三分钟：先了解项目 | [中文项目介绍与讲稿](docs/showcase/introduction/README.md) |
| 想核对规则改动是否真的有效 | [三个可复现实验](docs/PROJECT_TOUR.md#先看三个实验)，安装命令见下文 |
| 想体验规则组合成的冒险 | [M1 桌面演示](docs/M1_WEB.md)，当前需要本地运行 |
| 想检查系统与编译实现 | [代码地图](docs/CODE_MAP.md)、[设计取舍](docs/DESIGN.md) |

首次阅读：[中文项目导览](docs/PROJECT_TOUR.md)把三个实验、作者文件和实际执行路径串起来；
[代码地图](docs/CODE_MAP.md)用于继续检查实现。
全部使用与维护文档见[文档导航](docs/README.md)。

先看[约三分钟中文项目介绍](docs/showcase/introduction/film-v1/introduction.mp4)：
有旁白和字幕，讲清动机、方法、当前成果与未来愿景；[讲解页面与讲稿](docs/showcase/introduction/README.md)可选章核对。

## 用一组实验理解项目

| 你可以检查什么 | 代表例子 | 当前证据 |
| --- | --- | --- |
| 作者能否编辑世界 | [扩人数、换女巫](docs/showcase/world-edits/README.md) | 已保存声明差异、本地选项与真实行动来源 |
| 作者能否编辑规则 | 禁止自救、全票一致换多数票 | 两种实验均有保存报告：准入变化与后态变化 |
| 规则如何共同产生故事 | M1 的永焰、寒冷、观察与营救 | 已有真实整局，局部因果对照待整理 |

这些证据分别说明世界、规律与故事的关系，合起来展示作者编辑怎样影响实际运行。
见[展示命题与证据矩阵](docs/SHOWCASE_MATRIX.md)，其中分开列出已证实、待研究与未来愿景。

[观看约 90 秒执行回放](docs/showcase/recording/capture-v1/demo.webm)：真实临时文件编辑与重跑结果，
新增条件与第十步拒绝高亮，最后展示换职业、扩人数。
[分章回放及原始证据](docs/showcase/recording/README.md)可暂停核对；视频中的阅读停留不计为运行耗时。
[中文旁白与字幕版](docs/showcase/recording/narrated-v1/experiment.mp4)保留同一录像，不另跑世界。

### 已保存的规则编辑实验

同一个六人开局、同一条十步行动见证，只给女巫救人分支增加：

```yaml
- not_self: actor.name != scene.pending_attack
```

| 同一行动见证 | 原规则 | 加入「不能自救」 |
| --- | --- | --- |
| 前九步 | 发布 12 条 Action/Event | 完整来源前缀相同 |
| 第十步：女巫 B 救自己 | 成功，目标达成 | K0 拒绝，不发布这次行动 |

这份对照展示当前态准入变化：「救人」候选仍会出现，新增限制在提交时由 K0 检查并拒绝。
候选由 Source 的菜单声明生成，实际准入由 Law 决定。
工具只在内存改一条规则，原文件不变；
两次重新编译、开局和实际回放，不由演示脚本写入结局。

另一个[共同袭击规则对照](docs/showcase/wolf-vote/README.md)保持相同开局和十次选择，
只把全票一致换为多数票：两版所有行动都获准，前者无人死亡，后者 F 死亡。
它展示规则对实际世界后果的影响。

[编辑人物实验](docs/showcase/world-edits/README.md)保持规则不变：女巫 B → E 后，通知、
选项和救人来源一起转到 E；六席扩到八席后，新增 G/H 各有独立视图，G 能真实投票。
实验页列出参与者、职业与药水开局的同步编辑方法。

## 安装与复现

从仓库根执行（Windows 可将 `.venv/bin/python` 换成 `.venv\Scripts\python.exe`）：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python tools/release_rule_edit_demo.py
.venv/bin/python tools/release_wolf_vote_demo.py
.venv/bin/python tools/release_world_edit_demo.py
```

输出应包括 `unchanged_published_prefix: 12`，原版 `goal_status: met`，
编辑版 `stop_reason: k0_not_admitted`、`requested_step: 10`。
上述命令的全新安装实测与未验证项见[验证说明](docs/VERIFICATION.md)。
`--json` 显示完整发生来源；[规则编辑实验](docs/SHOWCASE.md)提供演示顺序和本次原始证据。
要亲手编辑文件，按[作者指南](docs/AUTHORING.md)操作。
领域字段类型在 Lib 中[提前声明、按名引用](docs/C0_LIB_TYPE_ALIASES_V1.md)，包括单次使用的类型；范围仍由编译与运行检查。
演示开局 B 是女巫；下列普通交互开局 B 是村民，不混为同一个开局。

```bash
.venv/bin/python -m nomos_examples werewolf
.venv/bin/python -m nomos_examples everflame
```

狼人杀输入当前编号、`seat B` 换席或 `quit`；每轮自动显示本地视图，不接受 `view`。
冰宫入口接受 `view` 重看本人已授权信息。资源随安装包分发，不依赖仓库工作目录。
换席由同一受信控制者操作，可以分别查看各席位的本地信息与行动。

M1 的图形试玩入口见[桌面 Web 启动说明](docs/M1_WEB.md)：独立应用自持前后端，
消费本仓库世界资产与运行时，一条 `npm start` 提供页面和会话服务。

## 实现方法

```text
规则库 / 端口 / 世界声明 ── C0 编译器 ── 规则 Program
规则 Program + 开局 Assets ── Start ── K0 Session
玩家或 NPC 的行动提议 ── 当前态准入与原子结算 ── 实际发生 / 本地读回

T0：用同一个 Program 和 Assets 实际执行有限行动见证，检查目标是否达成。
```

Source 声明世界中允许的行为和规则；见证是独立验证输入。
T0 报告这条行动见证的实际运行结果和目标检查。

## 代码地图

| 路径 | 职责 |
| --- | --- |
| `src/nomos_c0/` | 作者文件前端、名义类型、语义 IR、绑定与 Session 控制 |
| `engine/kernel/src/nomos_kernel/` | 当前态准入、owner 贡献、因果/due 与原子发布 |
| `src/nomos_t0/` | 对同一编译产物运行有限行动见证，不另模拟世界 |
| `src/nomos_c0/examples/` | 狼人杀规则和编译器区别案例 |
| `src/nomos_examples/everflame/` | 冰宫冒险的规则、区域、控制与开局 |
| `tests/`、`engine/kernel/tests/` | 具名短合同测试，不以整局代替底层测试 |
| `tools/` | 规则编辑实验、安装检查、画像和测量 |

[代码导览](docs/CODE_MAP.md)沿一条实际规则定位关键实现；
[选定语义](docs/SEMANTICS.md)说明合同与排除项；
[测试指南](docs/TESTING.md)提供具名测试入口。
各层入口：[C0](src/nomos_c0/README.md)、[K0](engine/kernel/README.md)、[T0](src/nomos_t0/README.md)。

## 当前与未来

**当前是可安装、可复现的本地发行基线，尚未公开发布。**
两个世界已从 wheel 独立运行。已有同输入冰宫整局为 43 项行动、1180 条发生，
基线/候选 Run 为 45.056/45.106 秒，状态与来源摘要一致。
这组记录用于核对同输入下的运行状态与来源一致性。
已执行验证与证据可访问范围见[验证说明](docs/VERIFICATION.md)，
关键工程取舍和反例见[设计说明](docs/DESIGN.md)。

本轮验证环境是 Python 3.14.4 / Linux，包声明的语言版本要求为 `>=3.11`。
长期希望让作者通过可复用规则和库创造不同的沙盒世界。
LLM DM 可以作为未来的上游工具，提议行动、草拟可检查资产、讲述已经发生的故事；
内核负责规则准入与权威状态。存档、多人和更丰富的世界建模是后续研究方向。
研究历史保留在原研究仓库，本目录侧重可复现的实现和维护文档。

## 归属与权利

项目发起者负责项目愿景、问题定义、语义裁决与亲自验收；后期主要代码由 Codex 及协作者
实现或审阅。具体设计、实验和代码路径见上方导览。
原创引擎材料保留权利；M1 改编作者资产另有 CC BY-SA 4.0 条款，二者不能混成一份授权。
详见[权利说明](RIGHTS.md)。
