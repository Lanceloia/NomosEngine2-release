# NomosEngine2

**把游戏规则编译为可运行、可检查的世界，让玩家、AI策略与验证工具共用同一套结算。**

项目源于TRPG：玩家会提出预写剧情之外的尝试，世界应当怎样回应？NE2把人物、行动和规则写成声明，由C0生成Python程序，运行时负责行动准入、原子结算与许可信息交付。

[中文项目主页](https://lanceloia.github.io/NomosEngine2-release/) · [现行展示源码](https://github.com/Lanceloia/NomosEngine2-release/tree/showcase-current) · [历史发行](https://github.com/Lanceloia/NomosEngine2-release/tree/showcase-2026-10-11)

## 从哪里开始

| 想了解什么 | 入口 |
| --- | --- |
| 项目解决什么问题 | [中文主页：规则创作、策略学习与运行证据](https://lanceloia.github.io/NomosEngine2-release/) |
| 实际修改一条规则 | [现行源码与安装步骤](https://github.com/Lanceloia/NomosEngine2-release/tree/showcase-current#五分钟看一个规则修改) |
| 同一次行动为何产生不同后果 | [女巫自救对照记录](docs/homepage-v2/evidence/self-save.json) |
| 神经策略训练后的变化 | [固定样本配对测量](docs/homepage-v2/evidence/training-summary.json) |
| 检查编译器、运行时和T0 | [源码阅读地图](https://github.com/Lanceloia/NomosEngine2-release/tree/showcase-current#顺着代码读) |

## 现行执行路径

```text
Lib + Source → C0检查 → Python Program
Program + 开局数据 → Runtime Session → 行动、结算、信息交付
同一Program + 行动见证 → T0 → 实际结果与失败位置
```

狼人杀例子只修改女巫自救开关：允许时存活并消耗解药；禁止时同一请求被拒绝、诊断快照保持，改选不救后天亮死亡。演示同时保留原始字段、实际行动来源和逐步计时。

阿瓦隆学习实验将本人许可观测与合法候选接入神经投票策略。最终模型在固定30配置配对测量中由10胜变为12胜，新增3胜、丢失1胜；对应任务通关由15次变为17次。样本从600配置中分层抽取，包含历史训练配置，完整摘要在上方证据入口。

## 源码版本

**阅读当前实现，请切到[showcase-current](https://github.com/Lanceloia/NomosEngine2-release/tree/showcase-current)。** 该分支包含2026年10月29日的C0、Python Runtime、认知与T0源码，附固定演示、具名测试和独立安装复验记录。

```bash
git clone --branch showcase-current --single-branch https://github.com/Lanceloia/NomosEngine2-release.git
cd NomosEngine2-release
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -I showcase.py --output build/first-demo
```

上述运行命令面向Linux／WSL。打开生成的build/first-demo/report.html即可核对三条路线。

main保留10月11日历史代码并承载项目主页；[当时的说明](docs/README_20261011.md)与原标签可用于追溯。现行分支的[源码清单与复验结果](https://github.com/Lanceloia/NomosEngine2-release/tree/showcase-current/docs)记录本次展示版本。
