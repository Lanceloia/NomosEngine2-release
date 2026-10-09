# 安装与性能返回记录

状态：独立 wheel 的两个消费者及一条 Law 编辑已真实运行；性能未通过，整局门尚欠。
本记录不宣称发行已接受。

## 安装

Python 3.14.4、PyYAML 6.0.3。wheel 环境独立于 checkout，工作目录为 `/tmp`，
清除 PYTHONPATH/PYTHONHOME、使用 `-I`，smoke 检查所有 nomos 模块 origin 在安装环境。

| 实际世界 | Compile | Start | Run | 发布 |
| --- | --- | --- | --- | --- |
| 六席狼人杀 | 0.963秒 | 0.005秒 | 0.004秒 | A投票，1条发生，100模块origin |
| 有限M1 | 37.062秒 | 0.167秒 | 0.044秒 | 等待Action，1条发生，101模块origin |

两个入口都只提交短动作，不据此宣称整局完成或此表是稳定性能统计。
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

短门：安装/精确M1声明6 passed；测量判定7 passed。
候选CI的19个明确模块本地串行209 passed（31.12秒），相关Ruff及diff检查通过。
根README、权利、docs、C0/T0/Kernel导航的相对链接存在性检查无失效路径；未验证全部锚点。
独立最终技术复核和陌生人试玩仍欠，不把writer自测称独立接受。
