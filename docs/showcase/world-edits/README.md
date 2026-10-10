# 编辑人物，而不是增加写死的按钮

规则不变，能否把女巫换个人、再让新加入的人真实参与？这批实验回答两个问题：
**开局职业影响谁获得信息与行动机会；参与者声明影响哪些个体进入世界。**

本批复用现有狼人杀 Lib、Ports 和参与者模板，不增加 K0/C0 能力，不改普通交互开局。
演示工具先编辑声明，再 Compile／Start；局内结果只从实际运行读取。

## 换职业：B → E

同一六席 Source，两份开局只同步修改下列字段：

| 位置 | 原开局 | 编辑后 |
| --- | --- | --- |
| `scene.roles` 中 B／E 的职业 | 女巫／村民 | 村民／女巫 |
| `b.own_role`／`e.own_role` | 女巫／村民 | 村民／女巫 |
| `b.healing_available`／`e.healing_available` | 有／无解药 | 无／有解药 |

没有为 E 新写一条救人 Law，也没有把救人结果放进 Assets。
Scene 的权威职业分配、本人职业与药水开局必须保持一致；当前仍需明确同步，不能只修改一个字段。
Scene 角色表不在玩家的授权读回中，不是局内公开名单。

两版先执行[相同九次选择](actions.yaml)：白天平票进入夜间，A 放弃查验，C、D 都选择袭击 B。
接着查看 B、E 的**各自本地信息和当前选项**：

| 实际结果 | B 是女巫 | E 是女巫 |
| --- | --- | --- |
| 谁实际收到受害者通知 | B，目标 B | E，目标 B |
| 谁有 `Save victim`／`Do not heal` | B | E |
| 另一人知道受害者吗 | 本地视图没有该通知或隐藏目标 | 同样没有 |
| B 的原救人候选 | 存在 | 消失，不提交 |
| 选择当前女巫救人 | B 发布行动 | E 发布行动 |
| 实际来源 | `c0.six-seat.witch-b` | `c0.six-seat.witch-e` |
| 清晨 | B 存活，女巫的解药耗尽 | B 存活，女巫的解药耗尽 |

换人后继续向 B 查找原候选会找不到，**这不是提交后被 K0 拒绝**。
工具的 `B_candidate_check` 只是只读查找，不伪造一次请求、Action 或拒绝记录；
随后改由 E 选择实际存在的选项。两版各发布十项 Action、十四条发生记录。

这里不像[规则替换实验](../wolf-vote/README.md)那样要求前九步所有后态相同：
开局职业本来不同，通知也应投向不同人物。保持相同的是前九次选择及共同世界的受害者。

## 扩人数：六席 → 八席

复用上面的 B 女巫开局，增加两名村民 G、H；规则、端口和已有六人的开局保持不变。

```diff
 # Source 的 participants 域
- owners: [a, b, c, d, e, f]
+ owners: [a, b, c, d, e, f, g, h]
```

Assets 同步增加 G／H 的存活人物、职业分配及各自私有 opening。
模板由 Lib 提供，但新增实例名单由 Source 明确声明，不能仅在界面加按钮。

| 核对项 | 六席 | 八席 |
| --- | --- | --- |
| 席位与独立 Actor owner | A–F；六个 Actor owner | A–H；八个 Actor owner |
| 每人开局投票目标 | 六个 | 八个 |
| 本地人物视图 | 只含本人私有字段与授权公开字段 | G／H 也分别如此 |
| 真实投票 | A → F，Action ref 1 | A → H，ref 1；G → A，ref 2 |
| 新人物行动来源 | 不存在 G 的行动入口 | `c0.six-seat.vote-g` |
| H 的私有投票记录 | 无此人物 | 空；不会因 G 行动而获得其投票记录 |

投票真实写入 A、G 本人的记录与共同票表；没有跑完整八人游戏，也不证明任意人数或公平性。
来源中的 `six-seat` 是现行 Source 自选的命名前缀，不是人数计算依据；本批保留它以免把
改显示名称混入人数实验。

## 复现与亲手核对

按仓库 README 安装后，从仓库根执行：

```bash
.venv/bin/python tools/release_world_edit_demo.py
.venv/bin/python tools/release_world_edit_demo.py --json
.venv/bin/python tools/release_world_edit_demo.py --record /tmp/ne2-world-edits-new
```

Windows 使用 `.venv\Scripts\python.exe`。保存目录必须尚不存在。
保存时会输出两份 Source、B／E 女巫开局和八人开局，以及真实本地视图、选项、作者后态与来源。
这些 YAML 是实际送入编译／开局的结构化快照；可以直接用文件差异核对上述编辑，也可以
按[作者指南](../../AUTHORING.md)把同样的修改应用于示例后交互运行。

当前作者写法重新采集的[实际报告](evidence-predicates-v1/result.json)和
[采集摘要](evidence-predicates-v1/manifest.json)对应代码 `960435fe3`。
先看 [B 女巫](evidence-predicates-v1/witch-B.assets.yaml)／[E 女巫](evidence-predicates-v1/witch-E.assets.yaml)的六处字段差异，
再看[六席 Source](evidence-predicates-v1/six.source.yaml)／[八席 Source](evidence-predicates-v1/eight.source.yaml)与
[八席开局](evidence-predicates-v1/eight.assets.yaml)。快照排版不同于输入原文，但保持结构化内容；
摘要只识别内容，不是认证签名，也不保证直接篡改报告无法伪造。
报告保留主树采集路径；同步到发行仓库后仍是这一次采集，不冒称另一份独立试玩。
逐步报告与旧报告的结构化内容完全相同。旧 `15ecfccd9` 的
[报告](evidence/result.json)及摘要保持原始字节，不更新成新版本。

[工具](../../../tools/release_world_edit_demo.py)只按当前选项提交[外部选择](actions.yaml)。
`checkpoint()` 把 `read()`／`offers()` 与受信 `author_snapshot()` 分区保存，不拿私有审计值决定选项。
报告是供作者核查的多席位材料，不是单个玩家视图、多人登录或新增 T0 检查语言。
源码差异、编译生成能力、本地选项和真实发生共同构成证据，不以摘要文案代替执行。

## 范围与验收

这两项都是现有编译器测试组合的展示化，不新增职业或规则。
工具的开局转换不是新的作者生成器；角色／药水重复维护仍是已知易错点，不冒称已经解决。
两项实验均不改 Lib／Ports，不写入世界终态；既有禁自救和多数票报告保持原样。

具名短测试用一次四局实际执行覆盖正常对照，其他反例只核编辑结构或报告：

```bash
.venv/bin/python -m pytest -q tests/tools/test_release_world_edit_demo.py
```

本页属于[多实验展示矩阵](../../SHOWCASE_MATRIX.md)的 E1／E2；不凭这两项实验宣称完成 TRPG 沙盒。

### 本片记录

2026-10-10：采集代码 `15ecfccd9` 实际运行四个 Session；女巫两版各十项 Action／十四条发生，
六席样本一项真实投票，八席样本两项真实投票。原输入文件不改写，采集时没有未提交代码。
writer 的新工具与既有换职业／人数具名门初轮 16 项通过；独立 Euler 对上述代码快照复核，
新工具 12 项通过、Ruff 通过，无 finding。

后继静态测试只核保存摘要、声明差异和报告内容，不追加世界路线。
最终主树具名门 41 项通过（含旧自救与多数票证据回归）；发行仓库新工具模块 13 项通过。
报告与快照在两仓库一致，发行测试不改变原始采集版本。
技术通过不等于 Owner 已接受展示体验；不沿用历史玩家评分，不运行 M1／Web／性能门。
