# 跨局类型特征探针

Non-canon探针：比较两局不同成员身份下，已有Subject经验是否按作者声明的`kind`特征影响完整候选评价。
第一局使用身份1／2，第二局使用另一组身份；仅`ordinary`／`signal`类型特征可比较。

AI配置声明完整组合的`signal_count`语义和一个保守先验。规划文件没有声明历史样本如何重排部分成员，
因此本例可以核验经验评价是否跨身份迁移，不能证明经验会改变成员构造顺序。

```bash
.venv/bin/python -m tools.subject_feature_transfer_probe \
  --output /tmp/subject-feature-transfer.json
```

探针只使用真实生成Program、Action、反馈及Subject；不是Avalon或狼人杀的内容，也不改变正式世界。
