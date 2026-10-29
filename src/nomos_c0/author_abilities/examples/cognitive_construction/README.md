# 本局观察引导组合构造

这是non-canon能力探针，不是新的产品世界。A从五个可用组件中选两个；
B可以真实报告对某个组件的观察，也可以实际移除组件。

`world.planning.yaml`按报告给成员排序；`world.ai.yaml`只定义组合含义、先验和真实结果反馈。
没有预存的完整组合。空／无关／相关观察保持同一参数域，最终与十项穷举参照核对。
移除组件后，旧票据失效，刷新后只构造当前合法组合；实际失败反馈也会保留。

运行：

```bash
.venv/bin/python -m tools.subject_construction_probe \
  --output /tmp/construction.json --markdown /tmp/construction.md
```

库导览与边界（研究仓路径：`docs/guides/COGNITIVE_LIBRARY_V1.md`）
区分本局报告引导与跨局抽象经验估值；本例没有自动归纳长期方法。
