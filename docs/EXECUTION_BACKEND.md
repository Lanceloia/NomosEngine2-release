# 编译执行后端

状态：B05 writer语义短门通过；等待发行集成、性能门及最终独立复核。

## 分工

三类执行计划分别保留语义责任：

| 文件 | 责任 |
| --- | --- |
| `invariant_execution_v1.py` | checked admission IR 的短路、引用、量词作用域与有限专用化 |
| `nominal_validation_execution_v1.py` | 有序字段/名义类型检查、当前 nested validator、variant 与 invariant |
| `validation_contract_execution_v1.py` | 封存依赖的当前属性 identity、短路和资格边界 |
| `_execution_emission.py` | 编译期常量绑定、局部名、AST片段和Python发射 |

共同发射工具不认识场景、规则或验证语义，不决定权限/阶段，不缓存值或校验成功。
常量按identity绑定但不比较、不去重；作者字段名仍是字符串字面量，不注入代码。
函数直接使用生成namespace，没有运行期dispatcher或helper转发层。
nominal的invariant后绑定仍修改函数实际使用的同一个namespace。

生成器对未专用化的操作调用同一checked IR求值器，这是单一语言合同的执行策略，
不是旧schema/alias/版本fallback。三处旧的bind/compile/exec机械代码已删除，
没有保留另一套发射路径作为兼容。

## 验证

Python3.14.4。七个具名模块168 passed（1.72秒），相关Ruff通过。

```bash
python -m pytest -q \
  tests/nomos_c0/test_execution_emission.py \
  tests/nomos_c0/test_invariant_execution_v1.py \
  tests/nomos_c0/test_nominal_validation_block_v1.py \
  tests/nomos_c0/test_specialized_nominal_validation_v1.py \
  tests/nomos_c0/test_validation_contract_execution_v1.py \
  tests/nomos_c0/test_runtime_reference_execution_v1.py \
  tests/nomos_c0/test_quantifier_collection_execution_v1.py
```

新工具反例覆盖identity绑定不触发原生eq、命名不碰撞、后绑定与原生异常。
现有语义门覆盖首错、读取顺序、短路、实时metadata与嵌套回调。
这只是组织重构，不宣称提速；正常配对与最终整局仍由B06核定。
