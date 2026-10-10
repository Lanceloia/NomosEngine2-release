# 修改规则，改变准入

同一六人开局、同一条十步见证，只增加「女巫不能救自己」的条件：
前九步来源不变，第十步从成功变为 K0 拒绝。这里展示的是准入变化，
其他维度见[实验矩阵](SHOWCASE_MATRIX.md)。

## 运行

按根 [README](../README.md) 安装，从仓库根执行：

```bash
.venv/bin/python tools/release_rule_edit_demo.py
.venv/bin/python tools/release_rule_edit_demo.py --json
```

Windows 使用 `.venv\Scripts\python.exe`。工具在内存编辑规则，不修改作者文件。
它使用 B 为女巫的独立实验开局；普通交互示例的 B 是村民。

| 核对项 | 原规则 | 禁止自救 |
| --- | --- | --- |
| 前九步 | 12 条真实 Action/Event | 完整前缀相同 |
| 第十步 B 救自己 | 成功发布并使用解药 | K0 拒绝，不发布本次行动 |
| T0 目标 | 达成 | 本条见证未达成 |

对照工具退出 0，表示预期差异已经核对；直接检查改后的见证则退出 3。
候选仍然存在，不把它描述成「按钮自动消失」或「发布后回滚」。
菜单条件与最终准入分开声明，这项实验没有闭合二者的自动联动。

## 亲手修改

在共享 Lib 的 `action.witch_intervene` 中定位 `save_choice`，
在救人分支的 `victim_exists` 后增加：

```yaml
- not_self: actor.name != scene.pending_attack
```

完整路径、命令与撤回方法见[作者指南](AUTHORING.md)。
规则、Assets 和见证分别是世界规律、开局和外部请求，不混为一份剧情程序。

## 查看证据

[逐步报告](showcase/self-heal-predicates-v1/result.json)保存真实运行，
[采集摘要](showcase/self-heal-predicates-v1/manifest.json)标明代码与输入版本。
保存报告是历史采集，不冒充当前提交重新运行；当前行为可用上面命令核对。

采集新证据时必须使用尚不存在的目录：

```bash
.venv/bin/python tools/release_rule_edit_demo.py --record /tmp/ne2-self-heal-new
```

`--record` 要求引擎从本 checkout 安装，防止错误归因；普通运行可使用独立 wheel。
报告校验只检查声明、记录与摘要一致，不提供认证签名或跨局身份。

继续阅读：[代码地图](CODE_MAP.md)、[语义边界](SEMANTICS.md)、[验证说明](VERIFICATION.md)。
