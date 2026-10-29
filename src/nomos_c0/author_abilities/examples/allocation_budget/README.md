# 中性预算分配样本

这是共享数量分配控件的短验证世界。两个席位各确认一次预算；玩家可分配也可保留，
另一席位通过独立 AI 文件构造完整值并提交同一规则。

`Budget(expenses, saved)`、`Expense(project, amount)` 和枚举项目键与人员样本结构不同，
仍由同一 `allocation` 组件生成数量行。修改 Source 项目表即可改变目标与容量。
规则在 `world.lib.yaml`，界面映射在 `world.presentation.yaml`，电脑选择在 `world.ai.yaml`。

从仓库根目录启动两个样本：

```bash
.venv/bin/python -m nomos_play --catalog src/nomos_c0/author_abilities/examples/allocation.games.yaml --port 8879
```

打开浏览器，选择“预算分配试验”和 A，点击“分配预算”。例如研究 2、设备 0、培训 1，
保留 3；确认后观看电脑的实际提交与终局。编辑本身只改变草稿。
