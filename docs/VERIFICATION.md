# 验证与已知边界

本页区分可在仓库内复现的实验、已经记录的本地测试，以及尚未验证的环境。
测试绿色不等于任意作者程序正确，配置了 CI 也不等于远端已经通过。

## 可复现的三项演示

按首页安装后运行：

```bash
.venv/bin/python tools/release_rule_edit_demo.py
.venv/bin/python tools/release_wolf_vote_demo.py
.venv/bin/python tools/release_world_edit_demo.py
```

| 实验 | 预期核对结果 |
| --- | --- |
| 禁止自救 | 前九步 12 条发生相同，第十步从成功变为 K0 拒绝 |
| 全票与多数票 | 十次行动都发布；全票无人死亡，多数票 F 死亡 |
| 换职业与扩人数 | 通知/选项/来源转到 E；G/H 有独立视图，G 实际投票 |

[证据目录](showcase/README.md)保留原始采集及输入。版本、路径与摘要记录当时的环境，
不冒充每次维护后重新采集；上述命令可检查当前代码行为。

## 已执行的独立安装检查

2026-10-10，在 Linux/WSL、Python 3.14.4、PyYAML 6.0.3：

- 全新虚拟环境按 README editable 安装，三个演示均退出 0。
- 发行提交 `03b86a8` 的干净 Git archive 构建 wheel，再安装到另一全新环境。
- 从仓库外目录清除 `PYTHONPATH/PYTHONHOME`，使用 `python -I` 运行两个安装 smoke：
  狼人杀与冰宫各真实发布一项 Action，已加载模块来源全部位于安装环境。
- 同一 wheel 环境中的三个演示均退出 0。
- 工具安装边界模块 writer 与独立 reviewer 各 6 passed；独立 reviewer 没有再安装 wheel。

安装验证检查资源、模块来源与实际提交，不是整局试玩。普通演示可使用 wheel；
`--record` 则要求从本 checkout 安装，以免把其他版本的结果署成本地 Git 版本。

## 组合与性能记录

已有一次同输入冰宫整局对照：43 项玩家行动、1180 条发生；基线/候选 Run 分别为
45.056/45.106 秒，终局状态与来源摘要一致。这是一次组合核对，不证明稳定提速。
完整[原始报告及版本说明](evidence/runtime-pair-2026-10-10/README.md)随发行材料提供；这组秒数不是可重复保证。
本页及安装验证没有重新跑整局，也没有重新进行性能测量。

如何运行具名合同、独立安装和新测量，见[测试指南](TESTING.md)。
原子性、权限与局部信息的检查入口见[设计取舍](DESIGN.md)。

## 尚未验证或未提供

当前只实际验证 Python 3.14.4/Linux；`>=3.11` 是包声明，不表示所有版本已测。
原生 Windows 尚未验证。2026-10-11 完成授权并首次推送至
[公开发行仓库](https://github.com/Lanceloia/NomosEngine2-release)。
[远端 CI](https://github.com/Lanceloia/NomosEngine2-release/actions/workflows/checked-baseline.yml)
按具体提交记录合同测试、wheel 安装和三个编辑实验；执行结果以对应 run 为准。
当前不提供多人登录认证、通用存档恢复、连续空间时间、LLM 训练或通用 DM。
完整支持范围以[语义说明](SEMANTICS.md)为准，不从单条演示外推。
