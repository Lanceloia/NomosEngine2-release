# 安装与性能返回记录

状态：两个wheel消费者和Law编辑已运行；B05/B06技术范围独立接受，陌生读者已试跑。
性能未通过，整局门尚欠。
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

预设门见[测试指南](TESTING.md)。同解释器、输入bytes、Program复用、fresh Session、
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
增补后的21个CI具名模块串行222 passed（33.20秒）。独立复核和最终轮仍待运行。

短门：安装/精确M1声明6 passed；测量判定7 passed。
候选CI的19个明确模块本地串行209 passed（31.12秒），相关Ruff及diff检查通过。
根README、权利、docs、C0/T0/Kernel导航的相对链接存在性检查无失效路径；未验证全部锚点。
Gauss对exact`89dfc8a6f306ddec1ab7211f15e7b3d5e77a1fe4`独立复核无material finding：
B05七模块加安装/测量两模块串行181 passed（17.22秒），show/diff检查通过。
没有独立重跑wheel、性能或整局，不授总发行/性能接受。
干净上下文读者独立跑通狼人杀投票/换席及规则编辑演示，正确转述动机、能力、限制及归因；
发现`view`文档错误和两份开局未说明，已只改文档。默认狼人杀内部字段呈现仍较生硬，
不称已完成面向普通玩家的引导或整局体验。
