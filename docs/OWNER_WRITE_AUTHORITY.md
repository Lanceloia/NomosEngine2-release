# 精确owner写权限

状态：B02 technically_reviewed；整体发行门仍未通过。

## 唯一合同

`value.write_paths`原样进入`C0ValuePorts.writable_paths`、符号IR与Bind，
所有既有owner效果必须有精确`root.field`授权。相同carrier、相同字段名、相同实体
均不授予另一个逻辑root写权。Action编译与独立Bind、因果Event、scheduled due、
Actor domain、effects/output families消费同一集合，不从Source效果反推授权。

`writable_fields`仍供纯值copy/update检查字段修改；构造一个record不等于获得
替换owner状态的权限。`scene.items[].value`也不自动许可`scene.items`整体替换。
只读投影和private条件明确清空写权限。空集表示没有owner写权，没有旧行为fallback。

## 证据与限制

新短反例涵盖同carrier的actor/peer正反例、真实只写一位owner、
原生入口不能回退到字段并集、符号IR被改写权限后的独立Bind拒绝，及嵌套字段不能
冒充容器替换授权。既有原生测试明确补齐自身权限，不扩大实际作者Lib的权限。

14个具名相邻模块301 passed（18.24秒）；修改实现及测试Ruff通过。
未跑长M1，不以此宣称所有真实作者资产已重新Compile。
独立Bind只核效果与封存许可一致，不声称能抵抗同时篡改完整IR与许可的受信进程。

Gauss对成组exact `cd0038ffd5e6c1c1d733422285002e2603adad6f`独立复核，
无material finding；七个新模块22 passed（6.69秒），三个相邻nodeid3 passed（1.50秒）。
完整命令见[C0语义修复](C0_SEMANTIC_REPAIR.md)；301项为writer证据，未冒称独立复跑。
