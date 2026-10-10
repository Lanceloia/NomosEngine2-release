# 同样的选择，不同的世界后果

三名狼人分别选择 F、F、E：要求全票一致时，没有共同受害者；允许多数票时，
F 成为受害者，并在清晨真实死亡。**人物、开局和十次行动都不变，只替换一条规则引用。**

这与[禁止女巫自救](../../SHOWCASE.md)不同：两版都接受全部行动，差异不是
「提交被拒绝」，而是后续世界结算产生了不同状态。

## 只改什么

使用现有六席 Source 的 `select_target` 声明。Lib 已提供两种共同袭击规则，
本次在内存中选择另一条，不新增规则，不修改原文件：

```diff
- law: {ref: event.select_unanimous, args: {}}
+ law: {ref: event.select_majority, args: {}}
```

这是替换已有 Law 的实验，不是任意新 Law 创作、运行时热更新或自动证明所有规则组合。

## 共同开局与选择

[同一开局](opening.assets.yaml)：A 是预言家，B、E 是村民，C、D、F 是狼人，
六人均存活。它与普通交互示例的职业配置不同；两版实验使用同一份开局，不各自改角色。

[十次外部请求](actions.yaml)：白天六人投票形成 3–3 平票，无人出局；夜间 A 放弃查验，
C 选择袭击 F，D 选择袭击 F，F 选择袭击 E。原规则允许选择同伴。

这些请求是演示控制者的选择，不写入 Source，不要求游戏必须按这条剧情运行。
工具逐步查找当前真实选项并提交；选项缺失或 K0 不发布时直接报错，不能补造行动。

## 复现

先按仓库 README 安装，再从仓库根执行：

```bash
.venv/bin/python tools/release_wolf_vote_demo.py
```

Windows 使用 `.venv\Scripts\python.exe`。摘要应包含：

| 核对项 | 全票一致 | 多数票 |
| --- | --- | --- |
| 开局与前九步 | 七个 owner 的后态及完整发生记录相同 | 相同 |
| 十次行动 | 全部发布 | 全部发布 |
| 最终发生记录 | 13 条，其中 10 条 Action | 13 条，其中 10 条 Action |
| 清晨状态 | 无人死亡 | F 死亡 |
| 流程 | 第 2 轮白天，尚无胜方 | 第 2 轮白天，尚无胜方 |

第十步仍是同一人物提交同一选项与 payload；随后目标选择和清晨结算产生差异。
**发生数量相同不代表效果相同。** 不比较跨局个体身份，也不宣称这两局已经分出胜负。

查看逐步作者审计或保存新的报告：

```bash
.venv/bin/python tools/release_wolf_vote_demo.py --json
.venv/bin/python tools/release_wolf_vote_demo.py --record /tmp/ne2-wolf-vote-new
```

保存目录必须尚不存在。输出包括两份实际编译的 Source、逐步后态与发生来源、输入和代码摘要。
`files_modified: false` 表示原作者输入未被改写，不表示工具没有新建报告文件。
摘要识别采集内容，不是受信签名；绝对路径和版本号记录采集环境，不要求另一台机器相同。

## 为什么相信后果来自规则

[工具](../../../tools/release_wolf_vote_demo.py)分别 Compile 两个 Program、Start 两个独立 Session，
只向当前选项提交请求；后态来自 `author_snapshot()`，没有给 Scene 写入受害者或死亡。
报告核对共同开局、前九步全部后态和来源，以及十步相同的实际提交。

当前作者写法重新采集的[逐步报告](evidence-predicates-v1/result.json)、
[采集摘要](evidence-predicates-v1/manifest.json)与
[全票版](evidence-predicates-v1/unanimous.source.yaml)／[多数版](evidence-predicates-v1/majority.source.yaml)可直接核对。
Source 快照由工具序列化，排版与原文不同，但两份快照之间只有这一条 Law 引用不同。
本次采集代码为 `960435fe3`。逐步报告与旧报告的结构化内容完全相同；
旧 `52e61c7f3` 的[报告](evidence/result.json)和摘要保持原始字节，不更新成新版本。

这是受信作者审计，包含私有职业，不能直接交给局内玩家。
工具仅复用 T0 的发生记录序列化，不新增 T0 检查语言，也不替代其目标见证检查。
它不测 NPC 自主选择、连续空间、多人身份认证或完整 TRPG 沙盒。

具名短测试覆盖真实对照、唯一引用差异、错误绑定、缺失选项、报告错误及禁止覆盖已有采集：

```bash
.venv/bin/python -m pytest -q tests/tools/test_release_wolf_vote_demo.py
```

原来的女巫实验继续证明准入变化；这个例子补上「行动都合法，但规则改变真实后果」这一维度。
更完整的展示仍需要实例编辑与 M1 的短因果链，见[证据矩阵](../../SHOWCASE_MATRIX.md)。
