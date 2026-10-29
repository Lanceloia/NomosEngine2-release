# NomosEngine2 现行源码展示

作者声明游戏规则，系统生成Python程序；玩家、AI策略与验证工具共用运行时准入、信息边界和结算。

[项目主页](https://lanceloia.github.io/NomosEngine2-release/) · [规则实验记录](docs/evidence/self-save.json) · [策略测量摘要](docs/evidence/training-summary.json)

## 五分钟看一个规则修改

同一开局中狼人夜袭女巫。只切换allow_self_save：允许时自救并消耗解药；禁止时同样请求在第6步被拒绝，诊断快照保持；改选不救后天亮死亡、解药保留。

Linux／WSL、Python3.11以上：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -I showcase.py --output build/first-demo
```

打开生成的build/first-demo/report.html；result.json保留各步结果、输入摘要和原始计时。输出目录需不存在，重跑时更换目录。

## 顺着代码读

| 问题 | 入口 |
| --- | --- |
| 哪条规则控制自救 | [规则声明](src/nomos_c0/author_abilities/examples/werewolf.lib.yaml)、[配置](demos/werewolf-self-save/allow.source.yaml) |
| 声明怎样变成执行程序 | [Python生成](src/nomos_c0/python_codegen/world.py) |
| 请求怎样核查与提交 | [运行时Session](src/nomos_runtime/world.py) |
| 谁能读取哪些信息 | [信息交付](src/nomos_runtime/information.py)、[报告读取](src/nomos_runtime/report_inputs.py) |
| 验证步骤怎样进入同一世界 | [T0见证](src/nomos_t0/witness.py) |
| 如何接入学习数据 | [学习接口](src/nomos_cognition/learning.py) |
| 本例怎样核对结果 | [演示脚本](showcase.py)、[具名测试](tests/showcase/test_self_save_demo.py) |

## 版本与验证

本分支是2026年10月29日现行核心源码与固定规则演示的展示快照。10月11日历史发行仍保留在main及原标签。训练测量数据与固定运行样例分别记录；本分支包含学习数据接口和认知源码，训练工具与缓存留在研究仓。

[源码清单](docs/source-manifest.json) · [复验结果](docs/validation.json)。原创与第三方素材权利见[RIGHTS](RIGHTS.md)。
