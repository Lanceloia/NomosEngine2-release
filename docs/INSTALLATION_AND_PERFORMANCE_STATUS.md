# 安装与性能返回记录

状态：两个wheel消费者和Law编辑已运行；B05/B06技术范围独立接受，陌生读者已试跑。
性能短门已按Owner新预算接受，整局门尚欠；旧门的inconclusive原样保留。
本记录不宣称发行已接受。

## 安装

Python 3.14.4、PyYAML 6.0.3。wheel 环境独立于 checkout，工作目录为 `/tmp`，
清除 PYTHONPATH/PYTHONHOME、使用 `-I`，smoke 检查所有 nomos 模块 origin 在安装环境。

| 实际世界 | Compile | Start | Run | 发布 |
| --- | --- | --- | --- | --- |
| 六席狼人杀 | 0.963秒 | 0.005秒 | 0.004秒 | A投票，1条发生，100模块origin |
| 有限M1 | 37.062秒 | 0.167秒 | 0.044秒 | 等待Action，1条发生，101模块origin |

两个入口都只提交短动作，不据此宣称整局完成或此表是稳定性能统计。
候选`89dfc8a`又从干净git archive导出构建wheel并独立安装：狼人杀
Compile0.881/Start0.004/Run0.004秒，M1 Compile36.720/Start0.161/Run0.056秒，
同样核真实发布及100/101模块origin；没有复用旧build目录。
writer命令：`release_install_smoke.py werewolf`及`everflame`，实际报告保存在运行机临时目录；
数字为单次正常执行，不是 profiler 数字。

作者资源从旧 package 路径迁入安装包 `nomos_examples/everflame`，不保留旧导出或路径回退。
最初 wheel 漏装 `source/regions`，已补 package-data 并用覆盖全部资源的短测试防回归。

M1旧 `carry_from_ritual` 声明漏了 `victim.site`，原来被同型 Person 字段并集掩盖。
新精确写权检查正确拒绝；核 Law、参与者与玩家文案后只补这项明确许可。
未放宽C0、未扩大其他Person权限、未修改Law/Source/Assets。
静态短门遍历197个Action模板；它不替代真实Compile或运行。

## 规则编辑

安装后的 `release_rule_edit_demo.py` 使用同一Assets和十步T0见证，
只在内存给救人分支增加 `actor.name != scene.pending_attack`。
原版10步达成目标，编辑版完成9步后在第10步K0拒绝。
12条完整发生前缀（含来源/形成/参与者/包络）相同。没有修改安装文件或宿主结局。

## 性能

以下为旧门历史，新预算及重判见本文最后一节；现行门见[测试指南](TESTING.md)。
同解释器、输入bytes、Program复用、fresh Session、
串行AB/BA；计时外核状态/来源/控制历史。未改变阈值。

| 样本 | 配对比值中位数 candidate/baseline | noise max/min | 判定 |
| --- | --- | --- | --- |
| M1两次真实等待与推进，8对 | 0.9900 | >1.10 | inconclusive |
| Parcel32个独立局聚合，8对 | 0.9987 | >1.10 | inconclusive |

中位数接近1不能覆盖噪声门。所有8对的状态及来源比较通过，仍不称性能通过或稳定收益。
依据预设流程未进入成对整局，后续需在更稳定的测量条件下复验，或明确接受代价。
首次Parcel脚本错误把document直接传给Start，改为相同数据后才获得有效样本；
该失败不记性能结果。完整原始对照JSON由工具`--output`保留。

### 复验前锁定条件

2026-10-10再次测量前约定：只运行一轮相同脚本，父进程及两版worker固定在CPU6，
不修改核心、作者输入、样本工作量、AB/BA顺序、GC方式、计时范围或判定阈值。
先等已启动的Web虚拟玩家浏览器操作结束，不同时运行pytest、构建或长应用路线。
亲和性只用于减少调度迁移，不等于独占CPU，也不保证Windows宿主无负载。
本轮不挑选最快样本、不混入上轮成绩、不延长到超过原定四加四对。
若短门通过，在同一轮执行预定的一次成对整局；否则仍记未通过，不反复重跑取最好结果。

```bash
taskset -c 6 /tmp/nomosengine2-release-dev/bin/python tools/release_runtime_gate.py \
  --baseline /mnt/d/nomosengine2-runtime-frozen \
  --candidate /mnt/d/nomosengine2-release \
  --bundle src/nomos_examples/everflame/world.bundle.yaml \
  --resources src/nomos_c0/examples \
  --output /tmp/ne2-release-affinity-gate.json --full
```

此处是实施前的测量协议，不是通过记录；前两轮inconclusive结果继续保留。

计时前最后入口核查发现四个早期catalog仍随包分发，已删除旧schema适配闭包；
具体写集和有效反例迁移见[唯一入口清理](CURRENT_ENTRY_HARD_CUT.md)。
五个具名模块60 passed（5.09秒），相关Ruff及diff检查通过；
增补后的21个CI具名模块串行222 passed（33.20秒）。后续独立复核与实际测量见下节。

### 亲和性轮结果与一次聚合长度修正

候选`e84a00b`/冻结`83c2d9642`，两树干净；预设CPU6轮已正常结束，exit2。
M1四对比值为0.9644、1.0340、0.9896、1.0198，中位1.0047，按原门passed。
Parcel32局八对为0.9998、1.1585、0.8942、0.9652、1.1195、1.1101、1.0158、0.9708；
中位1.0078，max/min约1.296，inconclusive。整局未运行。
计时后独立核两版所有M1短样本time200、49条发生；两条wait及来源/状态摘要一致。
原始报告`/tmp/ne2-release-affinity-gate.json`，不将旧轮与本轮拼接取优。

最后入口清理经Gauss独立61 passed/no material finding接受。
从`e435558`干净Git导出重建wheel，仓库外两消费者真实发布：
狼人杀Compile0.916/Start0.005/Run0.004秒，98个origin；M1 Compile36.929/Start0.171/Run0.057秒，
99个origin。旧catalog与导出不可导入；改Law演示仍为共同12条前缀后第10步拒绝。
`e84a00b`仅修测试/记录，对该wheel的核心与作者资产无差分。

实施前锁定最后一次测量工具修正：Parcel从32固定增至256个fresh Session，
维持同Program、同输入、每局相同工作量断言、原GC与计时边界；仅增加聚合长度，
不预言噪声必然降低。CPU时间作为诊断，门仍使用wall时间。
保持5%、max/min1.10及最多四加四对，所有样本保留，不调量至通过。
为保持工具原来的“同轮短门全过才进整局”出口，不建立跨轮成绩fallback，
这一新轮仍执行M1原短样本，独立保留前轮passed而不择优；核心/作者资产不变。
新轮若仍不稳定就停止测量并报告缺口，不继续扩大重复数。

```bash
taskset -c 6 /tmp/nomosengine2-release-dev/bin/python tools/release_runtime_gate.py \
  --baseline /mnt/d/nomosengine2-runtime-frozen \
  --candidate /mnt/d/nomosengine2-release \
  --bundle src/nomos_examples/everflame/world.bundle.yaml \
  --resources src/nomos_c0/examples --parcel-sessions-per-pair 256 \
  --output /tmp/ne2-release-aggregate-gate.json --full
```

这仍是实施前协议，不是最终性能通过记录。

测量工具`eabf133`由Gauss独立单模块9 passed（0.79秒）；发现既有CLI可用
`--sample short --full`遗漏Parcel短门。已在创建worker前拒绝任何缺一种短门的
`--full`配置，补两个实际CLI反例；不改变预定完整命令、运行时或门槛。

短门：安装/精确M1声明6 passed；测量判定7 passed。
候选CI的19个明确模块本地串行209 passed（31.12秒），相关Ruff及diff检查通过。
根README、权利、docs、C0/T0/Kernel导航的相对链接存在性检查无失效路径；未验证全部锚点。
Gauss对exact`89dfc8a6f306ddec1ab7211f15e7b3d5e77a1fe4`独立复核无material finding：
B05七模块加安装/测量两模块串行181 passed（17.22秒），show/diff检查通过。
没有独立重跑wheel、性能或整局，不授总发行/性能接受。
干净上下文读者独立跑通狼人杀投票/换席及规则编辑演示，正确转述动机、能力、限制及归因；
发现`view`文档错误和两份开局未说明，已只改文档。默认狼人杀内部字段呈现仍较生硬，
不称已完成面向普通玩家的引导或整局体验。

## 最后完整聚合轮与测量工具清理

2026-10-10，候选`eb8c2e8`/冻结`83c2d9642`，CPU6亲和性、Python3.14.4、
PyYAML6.0.3，固定Parcel256个fresh Session。两组各八对完整结束：

| 样本 | candidate/baseline中位 | noise max/min | 预算内样本 | 原门判定 |
| --- | --- | --- | --- | --- |
| M1短链 | 1.007130 | 1.381085 | 5/8 | inconclusive |
| Parcel256 | 0.956492 | 1.316666 | 8/8 | inconclusive |

每对状态、发生来源与控制历史相等，Parcel每侧都有完整256个摘要；正确性相等不等于
性能通过。两组仍超原噪声门，整局没有执行，不拼接前轮成绩、不反复重测取优。
工具曾失去进程句柄，最初误判中断；随后按完整持久JSON校正，进程实际继续并结束。
报告在运行机`/mnt/d/nomosengine2-release-evidence/aggregate-gate.json`，SHA256：
`a7ea2eed4dd54c2bfdbb5ceed46d91531391865b132c02f59052d09ab096fd3b`。
这是外部测量证据路径，不是本仓库的安装或运行依赖。此前临时环境/报告已不可访问，
其历史结果保留，但不声称原始临时文件目前仍在。

Owner反馈大批测量影响电脑响应，当前不再自动启动长压测。轻量审阅发现worker的
旧report、Parcel的offer/snapshot/scene/receiver及full分支的frame/resident/snapshot
会跨下一次测量存活。清理仅在计时及语义检查外释放这些引用；没有改变输入、
GC策略、Run步骤、报告内容或5%/10%阈值，没有修改K0/C0或作者资产。

具名测量模块与新增生命周期模块：14 passed（4.61秒）；Ruff通过。
新模块用弱引用和中性假对象直接调用实际worker，覆盖下一次collect前report释放、
Parcel跨局/跨命令视图释放及full跨命令视图释放，不进行世界编译或性能计时。
Gauss对代码精确`b7b658ab7531a85473b4009bb07464cc81c7c5d6`独立复跑两模块：
14 passed（4.90秒），Ruff/show检查通过，no finding。
这证明测量对象生命周期修正，不证明噪声的实际成因或性能提速；整局门仍未通过。

## Owner批准的发行预算与旧证据重判

2026-10-10，Owner明确批准：配对中位数允许10%回退，八对中至少六对≤1.10；
波动保留诊断但不单独阻止发行、不追加测量。状态、来源及行动/控制摘要要求不变。
一次必要成对整局也使用10%预算。新工程预算不宣称测量稳定、没有回退或性能提速。

使用实际工具的`--assess-report`只读取最后完整聚合轮，逐对重核比较字段和AB/BA，
按原始Run时长重算比值，不启worker或真实编译。原报告SHA256仍为
`a7ea2eed4dd54c2bfdbb5ceed46d91531391865b132c02f59052d09ab096fd3b`，未覆盖或删除。

| 样本 | 配对中位 | 10%预算内 | 新预算结论 | 原门结论 |
| --- | --- | --- | --- | --- |
| M1短链 | 1.007130 | 6/8 | passed | inconclusive |
| Parcel256 | 0.956492 | 8/8 | passed | inconclusive |

重判报告在运行机`/mnt/d/nomosengine2-release-evidence/approved-short-assessment-2026-10-10.json`。
它明确所测core是`eb8c2e8`与`83c2d9642`，不是新一轮测量。此后的工具/文档修改
不改变K0/C0核心和作者资产；原报告未跑整局，因此本次不授整局或总发行接受。
独立复核初版发现重判只核每对双方计数相同、未绑定报告和build的固定工作量；
真实原证据的每侧256局无此缺陷。`1609b93`补报告/build/逐对计数一致性和裁短负例。
两具名测量模块writer29 passed（4.98秒），包含预算、缺对/非法数值、只读重判、
原文件保护、固定工作量、固定八对及整局10%出口的中性短反例；Ruff/diff通过。
Gauss对`1609b93`独立29 passed（4.60秒），真实原报告的两端各自错误计数都被拒绝。
复核另发现测试夹具共享build字典，随后改成两份独立声明并分别测两端；
最终测量模块writer27 passed（0.76秒），生命周期模块未修改。没有运行新的世界或性能样本。
