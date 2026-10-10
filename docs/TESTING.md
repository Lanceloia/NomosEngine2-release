# 测试与测量

短测试检查语义合同；长游玩见证检查某个世界的组合。
两者不能互相替代，也不能把一条路线通过外推为所有作者输入正确。

## 日常具名测试

每次 pytest 显式列具体 `test_*.py` 或 nodeid，串行运行，不默认收集全目录。

```bash
.venv/bin/python -m pytest -q \
  tests/nomos_c0/test_program_phases_v1.py \
  tests/nomos_c0/test_owner_write_authority_v1.py \
  tests/nomos_c0/test_formation_namespace_v1.py
```

| 改动 | 优先具名模块 |
| --- | --- |
| 开局隔离 | `engine/kernel/tests/test_opening_validation_isolation.py` |
| pre-due 原子边界 | `engine/kernel/tests/test_pre_due_transaction_boundary.py` |
| 精确 owner 写权 | `tests/nomos_c0/test_owner_write_authority_v1.py` |
| Action/Event 名称 | `tests/nomos_c0/test_formation_namespace_v1.py` |
| 候选故障与控制预算 | `test_dynamic_offer_fault_isolation_v1.py`、`test_control_budget_v1.py` |
| 执行生成 | `tests/nomos_c0/test_execution_emission.py`及实际改动执行器 |
| 类型与一行字段 | `test_nominal_type_aliases_v1.py`、`test_compact_record_fields_v1.py` |
| 安装资源 | `tests/nomos_c0/test_bundled_examples_v1.py` |
| 演示安装边界 | `tests/tools/test_release_demo_install_boundaries.py` |
| 保存的自救实验 | `tests/nomos_c0/test_showcase_evidence_v1.py` |
| T0 结果 | `tests/nomos_t0/test_witness_v0.py` |

表中省略目录的 C0 测试均位于 `tests/nomos_c0/`。
按修改依赖追加相邻模块；Ruff 检查改动 Python，不每次跑整局。

## 独立安装

从干净提交导出后构建，避免旧 `build/lib` 或遗漏资源影响结果：

```bash
export_root=$(mktemp -d)
git archive HEAD | tar -x -C "$export_root"
.venv/bin/python -m build --wheel --outdir /tmp/ne2-wheels "$export_root"
python -m venv /tmp/ne2-installed
/tmp/ne2-installed/bin/python -m pip install /tmp/ne2-wheels/nomos_engine2-0.1.0-py3-none-any.whl
```

在仓库外目录，用上面环境运行：

```bash
cd /tmp
env -u PYTHONPATH -u PYTHONHOME /tmp/ne2-installed/bin/python -I \
  /path/to/checkout/tools/release_install_smoke.py werewolf
env -u PYTHONPATH -u PYTHONHOME /tmp/ne2-installed/bin/python -I \
  /path/to/checkout/tools/release_install_smoke.py everflame
```

将 `/path/to/checkout` 换成实际仓库位置，wheel 输出目录使用空目录。
smoke 使用已安装资源，检查所有已加载 `nomos_*` 模块来自安装环境，并提交真实 Action。
以上为 Linux/WSL 命令；不是原生 Windows 已通过的声明。

## 性能测量

[测量工具](../tools/release_runtime_gate.py)在独立进程中加载明确的 baseline/candidate，
使用同一作者输入，分别报告 Compile、Start、Run。Program 复用，每次新建 Session；
暖态结果不能当冷启动耗时，也不能当浏览器响应时间。

运行前用 `python tools/release_runtime_gate.py --help` 查看参数。
先过相关正确性短门，确有必要时才运行固定 AB/BA 配对或整局。
测量不启用 profiler 或跳过验证；状态、来源和控制摘要在计时外核对。
保留正常 GC，并记录负载噪声，不挑最好的一次或按结果追加样本。

工具当前短样本预算为固定八对：Run 中位比值不超过 1.10，且至少六对不超过 1.10。
这是工程回退预算，不是统计稳定性或提速承诺。报告里的 noise warning 仍需阅读。
语义不一致、脚本错误与耗时回退是不同结果，不能通过删保障改善成绩。
已记录测量的范围见[验证说明](VERIFICATION.md)。

## CI

[工作流](../.github/workflows/checked-baseline.yml)显式选具名模块、构建干净 wheel，
从独立环境运行两个真实消费者与三个展示工具，不默认跑整局和性能门。
使用 Python 3.14.4；工作流配置不等于已经在 GitHub 执行。
当前本地结果与未验证环境见[验证说明](VERIFICATION.md)。
