# 测试与测量

测试回答合同是否成立；长游玩见证回答某个世界的组合是否运行。
两者不能互相替代，也不能把短绿色测试扩写为所有作者输入都正确。

## 日常短门

每次 pytest 显式列具体 `test_*.py` 或 nodeid，串行运行。
根 conftest 拒绝目录级/默认收集和第二个独立进程；不绕过或删除锁。

```bash
.venv/bin/python -m pytest -q \
  tests/nomos_c0/test_program_phases_v1.py \
  tests/nomos_c0/test_owner_write_authority_v1.py \
  tests/nomos_c0/test_formation_namespace_v1.py
```

| 改动 | 优先具名模块 |
| --- | --- |
| K0 opening 隔离 | `engine/kernel/tests/test_opening_validation_isolation.py` |
| K0 pre-due 原子边界 | `engine/kernel/tests/test_pre_due_transaction_boundary.py` |
| owner 精确写权 | `tests/nomos_c0/test_owner_write_authority_v1.py` |
| Action/Event 命名空间 | `tests/nomos_c0/test_formation_namespace_v1.py` |
| 候选故障 | `tests/nomos_c0/test_dynamic_offer_fault_isolation_v1.py` |
| 控制预算 | `tests/nomos_c0/test_control_budget_v1.py` |
| 后端生成 | `tests/nomos_c0/test_execution_emission.py`及实际改动执行器模块 |
| 安装资源 | `tests/nomos_c0/test_bundled_examples_v1.py` |
| T0 结果 | `tests/nomos_t0/test_witness_v0.py` |

模块名以实际文件为准。相邻门按修改依赖追加，不每次跑整个世界或全目录。
Ruff 检查改动文件；最终集成才运行已约定的具名合并门。

## 独立安装

```bash
python -m build --wheel --outdir /tmp/ne2-wheels
python -m venv /tmp/ne2-installed
/tmp/ne2-installed/bin/python -m pip install /tmp/ne2-wheels/nomos_engine2-0.1.0-py3-none-any.whl
cd /tmp
env -u PYTHONPATH -u PYTHONHOME /tmp/ne2-installed/bin/python -I \
  /path/to/checkout/tools/release_install_smoke.py werewolf
env -u PYTHONPATH -u PYTHONHOME /tmp/ne2-installed/bin/python -I \
  /path/to/checkout/tools/release_install_smoke.py everflame
```

smoke 使用已安装资源，检查所有 `nomos_*` origin 位于安装环境并提交真实 Action。
这是应用安装验证，不是用 M1 长路线替代底层单元测试。
发行构建必须从干净提交导出，不能依赖旧 `build/lib` 或工作树遗漏的资源。

## 性能门

工具：[release_runtime_gate.py](../tools/release_runtime_gate.py)。
两个隔离进程分别加载明确的 baseline/candidate core，使用同一作者文件字节。
复用 Program、每次新建 Session；这是进程内暖态门，不是冷启动门。

Compile、Start、Run 分开报告；不启用 profiler、mock 或运行时验证跳过。
短 M1 用真实两个等待和 NPC/due 推进；Parcel 用256个独立 Session 聚合
真实 dispatch→因果→defer→due→confirm，是一个组合样本，不分别归因各层成本。
重复数由`--parcel-sessions-per-pair`在计时前固定，双方完全相同，不按耗时自适应。
首轮32局结果保留于返回记录；256局是一项配对样本，不是256项独立配对。
附带的Parcel进程CPU时间只用于诊断，不替代wall时间或降低性能阈值。
AB/BA 按顺序执行，四对中位比值≤1.05且至少三对≤1.05才通过。
配对比值 max/min>1.10 则最多追加四对；追加按全部八对中位及至少六对合格判定，
仍有噪声记 inconclusive，不能算通过。不看结果后改阈值。

计时外核状态、来源、控制/行动值/Appraisal 与完整行动输入；只归一化本局 opaque scope。
GC 每个聚合样本前 collect，Run 保持正常自动 GC。完整 M1 日志不在测量中写终端。
只有短门都过才进入一次成对整局；整局>5%回退需要定位，不单次证明稳定收益。
短门未过 exit 2；整局回退 exit 3；脚本/语义错误不是性能结果。

稳定回退只安排一批针对性修正；必要正确性代价需明确取舍，不无限优化或移除保障。

## CI状态

已添加单job具名串行短门及wheel应用验证，不默认跑整局或性能门。
使用[checkout](https://github.com/actions/checkout)及
[setup-python](https://github.com/actions/setup-python)官方入口，显式Python 3.14.4。
这份仓库尚无远端，工作流配置不等于GitHub上已经通过；本地命令与远端结果分别记录。
