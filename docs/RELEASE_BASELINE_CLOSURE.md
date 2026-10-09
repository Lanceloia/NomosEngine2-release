# 本地发行基线收束

本轮完成的是有限作者合同下的可维护发行基线，不是完整UFO、任意语言、完整TRPG
或所有输入均无缺陷的证明。原研究仓库保留历史；本仓库不依赖它才能运行。

## 返回门证据

| 要求 | 当前证据 | 边界 |
| --- | --- | --- |
| 有限合同与排除项明确 | [语义](SEMANTICS.md)、[重建](RECONSTRUCTION.md) | 唯一Source v6；不承诺完整本体、公开恢复或恶意插件沙箱 |
| 实际K0/C0链与必修问题闭合 | [事务](KERNEL_TRANSACTION_REPAIR.md)、[写权](OWNER_WRITE_AUTHORITY.md)、[C0修复](C0_SEMANTIC_REPAIR.md) | 六项实证违约修复；独立89项及22+3项反例；未知项不冒称bug |
| IR与生成后端组织 | [执行后端](EXECUTION_BACKEND.md) | 三类计划共享机械发射，不为统一风格增加热转发；独立181项 |
| 唯一作者入口 | [hard-cut](CURRENT_ENTRY_HARD_CUT.md) | 删除四个旧catalog/适配闭包；独立61项，安装时旧模块不可导入 |
| 自持安装与两类真实消费者 | [安装记录](INSTALLATION_AND_PERFORMANCE_STATUS.md) | 干净Git导出wheel、仓库外cwd、隔离Python；狼人杀/M1实际发布 |
| 作者编辑真改变规则结果 | [作者说明](AUTHORING.md)及安装演示 | 同Assets/见证共同12条发生前缀后第10步分叉，不是宿主预写结局 |
| 工程性能预算 | 下表、[测量合同](TESTING.md) | Owner批准10%；旧门inconclusive保留，不声称稳定收益 |
| 文档、导航、归因与维护 | README、CODE_MAP、RIGHTS、具名CI | 陌生读者已实跑并修文档；CI只有本地证据，无远端绿色声明 |

原审计和修复的精确提交、命令与独立结果均在上述当前文件中，不复制研究归档到此。
核心/作者资产/打包声明相对已运行wheel基线没有后续运行语义修改；后继修改仅测量、
测试和说明。完整M1/Web、所有席位/世界组合均不是本次返回的外推结论。

## 最后一次成对整局

候选`c298b8f03908545c2347e508416beb5320737004`，对照
`83c2d964213d1865b6070434b53f7fdf408f32f8`。两树开始时干净；同一作者文件bytes、
Assets和种子，Python3.14.4/PyYAML6.0.3，正常GC，CPU6、nice15，串行各一个Session。
原八对短证据的core/作者输入与此轮相同；仅计时工具/测试/文档变化，不复跑短门。

| 阶段 | 冻结版 | 发行版 |
| --- | --- | --- |
| Compile | 33.627秒 | 36.276秒 |
| Start | 0.923秒 | 0.905秒 |
| Run | 45.056秒 | 45.106秒 |
| 玩家Action / 总发生 | 43 / 1180 | 43 / 1180 |
| 最终逻辑时间 | 4500 | 4500 |

Run比值1.001107，约0.11%回退，在10%预算内。完整行动与payload、状态/发生摘要、
行动值/Appraisal历史摘要一致；只归一化各局opaque scope，不删除来源或外局身份。
真实路线终局检查：仪式中断、居民alive/safe/已到外岸、有实际营救ref、GameForm结束。
正常结束后worker关闭，没有按噪声追加或选择最好的一次。

短门已有八对按新预算重判：M1中位1.007130、6/8合格；Parcel中位0.956492、8/8合格。
噪声仍记录，两组旧门inconclusive没有被覆写；不把新预算接受描述为旧门或统计稳定性证明。

原始整局报告在运行机`/mnt/d/nomosengine2-release-evidence/final-full-pair-2026-10-10.json`，
SHA256：`33b2a097b35002d2a15e712dc6245f7f081cc67935395ac374f0ef2021f300f8`。
同目录保留`run_final_full_pair.py`及log；脚本仅调用真实测量worker、核旧短门和
输入/代码未漂移、各执行一次full，不补世界结果。命令如下，不是默认测试入口：

```bash
nice -n 15 taskset -c 6 /usr/bin/python3.14 -I \
  /mnt/d/nomosengine2-release-evidence/run_final_full_pair.py
```

脚本拒绝覆盖已存在报告，避免失联误判后自动重测。上述运行机路径不作为安装依赖；
新机器可用仓库测量工具建立新对照，但不能声称复现了这次具体时长。
此报告和脚本不随wheel分发，不含额外世界规则或公开恢复身份。

## 最终核对

终态writer具名短门50 passed（16.85秒），Ruff/diff通过：

```bash
python3.14 -m pytest -q \
  tests/nomos_c0/test_release_runtime_gate_v1.py \
  tests/nomos_c0/test_release_runtime_gate_lifetime_v1.py \
  tests/nomos_c0/test_current_compile_entry_v1.py \
  tests/nomos_c0/test_bundled_examples_v1.py \
  engine/kernel/tests/test_same_wave_policy_v1.py
```

85项文档本地路径链接存在性检查通过，未核全部锚点；CI显式22模块名单存在、无重复，
含测量生命周期模块。没有运行远端CI，不把历史21模块222项称为新22模块全跑结果。
Gauss独立核`09ad7cf`及原始整局/重判证据，并跑两个具名中性测量模块：
30 passed（4.96秒），show检查通过；CI22模块存在且无重复、94项相对路径有效，
未核全部锚点。唯一P3 finding是重建说明两句旧“待验”状态，已同步，不涉及运行修改。
没有独立重跑安装或整局；安装沿用已记录的相同核心/资产证据，性能是writer实际配对，
reviewer核脚本与报告而非第二次计时。技术接受限这份证据下的本地有限返回门。
这项收束不再追加整局。
Web仍消费冻结版，本轮不切换其引擎或改写前端世界。没有新增公开远端或发布包。
