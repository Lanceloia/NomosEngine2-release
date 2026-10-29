# M1 高级作者世界

本目录使用现行 `nomos.author` 工具链重建核心 M1。
当前已运行地图与移动首批：16 区域、10 条普通路径、14 条穿冰路线、4 条慢桥路径。
永焰持有/保护、原储能器、观察、解冻与居民本地答复/撤离已接入；
独立随机流/周期寒冷、仪式/声音/元素形成已真实运行并经技术复验；
局部冰息威胁、默认NPC自动推进与世界终局已接入；同初设两路及编辑门已实际通过。
当前M01–M14核心技术门返回；三消费者统一见证、安装与旧链退役继续建设。

```bash
.venv/bin/python -m nomos_c0.author_abilities \
  src/nomos_c0/author_abilities/examples/everflame/world --plan
.venv/bin/python -m nomos_c0.python_codegen \
  src/nomos_c0/author_abilities/examples/everflame/world.lib.yaml \
  src/nomos_c0/author_abilities/examples/everflame/world.source.yaml \
  build/python-codegen/everflame.py \
  --ai src/nomos_c0/author_abilities/examples/everflame/world.ai.yaml
.venv/bin/python -m nomos_runtime build/python-codegen/everflame.py \
  --assets src/nomos_c0/author_abilities/examples/everflame/world.assets.yaml
# Trusted author debugging: every actual seat, including newborn controllers.
.venv/bin/python -m nomos_runtime build/python-codegen/everflame.py \
  --assets src/nomos_c0/author_abilities/examples/everflame/world.assets.yaml --manual
```

| 文件 | 职责 |
| --- | --- |
| types.lib.yaml | 地点/路线值类型、人物类型、纯查询、共享状态与行动值机制 |
| movement.lib.yaml | 观察通路、直接尝试、穿冰与慢桥各一份泛型规则 |
| perception.lib.yaml | 同区存在投影、实际移动见证和观察后取得的详细记录 |
| everflame.lib.yaml | 原物拆卸、充能装填、解冻，以及放下/拾取/自愿转交 |
| residents.lib.yaml | 同地发话与真实听见/答复规则 |
| cold.lib.yaml | 独立具名流、周期暴露检定、减速/冻结与本人实际记录 |
| ritual.lib.yaml | 本地仪式贡献、实际中断/听见、献祭与独立元素形成 |
| threat.lib.yaml | 元素付费观察、真实目标记录、共享冰息骰与个人生命后态 |
| ending.lib.yaml | 玩家死亡/冻结/实际外岸终局与居民/仪式/资源摘要 |
| map.source.yaml | 具体路径、首撞点、恢复键与冰面区域表 |
| world.source.yaml | 本局开局人物、未来种类、规则选择与调度配置 |
| world.assets.yaml | 开局位置、速度、冰面、种子和本人已有的路线知识 |
| world.ai.yaml | 居民撤离、博科尔德仪式和元素行动的独立本地策略 |

输入域根据当前位置和本人记住的路线标识选取当前规则表。
观察更新本人的通路知识；穿冰失败实际撞停、支付行动值，并取得对应恢复路线。
已解冻地面直接抵达且不消耗骰子。普通直接尝试遇到冰面仍发布付费 Blocked 结果。
慢桥基础行动值20000，普通基础10000；移动成本按最大/当前速度比向上取整，
调度以100行动值/局内时间单位积累，不再次乘人物移动速度。

修改 `map.source.yaml` 的难度或成本直接影响结算，Assets 的知识只引用路线身份。
永焰和原储能器各有独立 Object 身份，携带位置随实际持有者变化；保护每次从当前位置、
充能及覆盖表重算。只有当前持有者的投影显示精确充能；同区只见目标标识。
观察吊灯后取得原储能器的安装/脉光线索，实际拆卸后才能装填。
一次装填把一充能从原储能器转入永焰，容量5；解冻花一充能，位置和耐力分别保留。
地面观察存本人当前地点的有限记忆；人物观察记录带有实际 Source/occurrence 来源。
看见同区人物离开时只记录本地最后看见位置，远处目的地留待新的观察。
转交需要送出方实际提议和接收方实际接受，双方都有局内行动代价。

居民按本人的邀请记录、撤离倾向与已知出口步提出真实行动。
Source明确选择 `player_turn`，引用固定的 `palace.player`；终局使用同一角色，Assets不可替换。
默认每次停在冒险者真实机会；其余人物各自按本地策略提交。
界面只展示冒险者本地内容；`--manual` 可调试所有受信席位，控制清单本身不提供玩家知识。
单次自动推进有预算，耗尽后可明确继续；预算不是冒险结束条件。
寒冷周期100，六条原人物种子1–6独立于冰面主流13；只有实际暴露者抽样。
失败减速，归零冻结，保护从当前持有位置/充能即时推导；不写入过时保护标志。
寒冷不直接扣生命/耐力，解冻恢复最大速度但不重置已发生的随机流。
两博科尔德使用本人实际开局祭品记录、听见记录与 ritual_drive 生成仪式提案；
世界再核指定活祭品仍在仪式圈且冻结，四次实际贡献完成仪式。
解冻或付双倍移动费用搬离祭品会中断，搬离保持祭品冻结；冻结通路仍是付费受阻结果。
仪式圈、门槛、通道可取得阶段声音，远处不交付，阶段不包含精确进度。
完成会献祭并形成一位冷免疫元素；真实形成后才取得独立身份/owner/控制/调度，
后继捕获实际 formed 集合并加入人口。新生元素凭自己的已知目的地行动，
世界检查实际路径/地面；成功后交换下一目的地，冻结地面保持付费Blocked。
元素另付行动代价观察指定目标，同地或声明的圈/门槛视线才取得本人目标记录。
可发射的有限扇区来自 `map.source.yaml`；冰息使用一颗主流d20，默认点数>=10造成1耐力伤害，
只作用于当前受影响区域中的存活人物。目标离开后仍可尝试，但发布付费Blocked且不抽样。
一次发射消耗本次瞄准；元素再观察才可重新瞄准，未观察或移动后的旧原点不产生冰息选项。
耐力首次归零保留存活但失能，再受伤才死亡；冻结、冷免疫、永焰保护与伤害分别结算。
本人 `last_damage` 保留实际点数/后态，来源在实际冰息Action中；攻击者不取得受害者私态清单。
冒险者死亡、冻结或实际到达外岸后，以稳定闭包的世界谓词结束。
结算只计当前存活且已在外岸的居民，另显示仪式状态和实际永焰/储能器余量；邀请/解冻不直接计营救。
完整 M1 的验收按冻结清单（研究仓路径：`docs/coordination/C0_THREE_CONSUMER_ACCEPTANCE_V1.md`）执行。
同一开局/种子的协调营救和默认未救离宫见真实路线（研究仓路径：`docs/closure_notes/C0_M1_TWO_ROUTES_G8_V1.md`）。
协调路线实际控制冒险者和一位居民，其余人物仍用本地策略；它验证合法合作，不把自动跟随当保证。

## 许可与归属

改编自 Pepijn 与 Willem-Jan 的 *Thawed Through the Everflame* 1.1（2025），
本目录的改编世界资产采用 CC BY-SA 4.0。
原页和中文工作稿（研究仓路径：`docs/reference_adventures/m1_thawed_through_the_everflame/rules.zh.md`）
保留原作依据；此许可不改变 NomosEngine2 其他文件的许可边界。
