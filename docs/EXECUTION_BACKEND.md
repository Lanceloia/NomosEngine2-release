# 编译执行后端

C0 将已检查的 IR 编成专用 Python 执行计划。它优化的是规则的执行方式，
不把狼人杀或冰宫知识写进编译器，也不跳过运行时准入。

## 组织

| 文件 | 责任 |
| --- | --- |
| `invariant_execution_v1.py` | 准入 IR 的短路、引用、量词作用域和有限专用化 |
| `nominal_validation_execution_v1.py` | 有序字段、名义类型、variant 和不变量检查 |
| `validation_contract_execution_v1.py` | 当前属性 identity、封存依赖与验证资格 |
| `_execution_emission.py` | 编译期常量绑定、局部名称、AST 片段和 Python 发射 |

前三类计划各自保留语义责任；共同发射工具只处理生成代码的机械组织。
常量按 identity 绑定，不调用原生 equality 去重；作者字段名直接成为 AST 属性名，
不解析为代码模板、不做 Unicode 名称规范化。读取仍经过当前 getter/descriptor。
生成函数直接使用自己的 namespace，不经运行期万能 dispatcher。

## 正确性边界

- 专用化依赖封存的布局和类型元数据；不缓存世界当前值或准入成功。
- 未专用化操作仍使用同一 checked IR 求值器，不切换旧语言或另一套世界模拟器。
- 字段验证、不变量、分支读取顺序和首个错误仍属于语义合同。
- 生成代码相同不是全部正确性的证明；还需要来源、权限、异常和隔离反例。

例如，同一请求在菜单生成后可能已经过时。生成器可以预先确定字段读取路径，
但提交时仍须读取、校验当前值，不能复用上次的成功结果。

## 检查入口

从仓库根运行具名模块：

```bash
python -m pytest -q \
  tests/nomos_c0/test_execution_emission.py \
  tests/nomos_c0/test_invariant_execution_v1.py \
  tests/nomos_c0/test_nominal_validation_block_v1.py \
  tests/nomos_c0/test_validation_contract_execution_v1.py \
  tests/nomos_c0/test_runtime_reference_execution_v1.py \
  tests/nomos_c0/test_quantifier_collection_execution_v1.py
```

这些测试检查生成与执行合同；不是整局性能结论。测量方法见[测试指南](TESTING.md)。
