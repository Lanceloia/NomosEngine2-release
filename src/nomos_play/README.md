# Nomos 共享桌面

共享桌面消费 C0 生成的 Python 世界。玩家固定一席，电脑通过各自独立策略行动；
本人信息、公开棋局、选项、过程演出及终局均从同一生成 Session 取得。

## 代码分工

| 模块 | 职责 |
| --- | --- |
| [__main__.py](__main__.py) | 命令行参数、目录选择与服务启动 |
| [server.py](server.py) | 本地 HTTP 路由、静态资源、会话登记与资源关闭 |
| [package.py](package.py) | 生成产物的导出、校验和移动启动；仅启动服务时加载 HTTP 模块 |
| [catalog.py](catalog.py) | 游戏目录、生成产物懒加载与 Program 缓存 |
| [tabletop.py](tabletop.py) | 固定玩家视角、输入与电脑推进 |
| [streaming.py](streaming.py) | 在writer内封存已提交组的字节，在请求内发送线程输出；请求结束前回收线程 |
| [errors.py](errors.py) | 目录、桌面和 HTTP 直接共用的拒绝类型 |

导出、检查与目录读取不加载桌面控制器或 HTTP 服务。库调用直接导入对应模块；`__main__` 仅供 `python -m nomos_play` 启动。

世界操作与响应快照生成仍串行，JSON及流式网络发送不占用全局writer锁。
流式队列只传已编码字节，保持同请求帧顺序；发送失败不回滚或重放真实行动，socket写超时为5秒。
关闭服务逐项尝试关闭全部局与目录，最后用ExceptionGroup汇总清理错误。

## 编译与游玩

新的经验玩家入口（研究仓路径：`docs/guides/AVALON_EXPERIENTIAL_PLAY_V1.md`）位于独立目录配置，
同一批电脑玩家连续参与不同身份的新局，并在赛后显示真实回忆对选择的影响。
本地预览`http://127.0.0.1:8898/`；原8897三风格入口保留。

在项目根目录、安装开发环境后运行：

```bash
PYTHONPATH=src .venv/bin/python -m nomos_c0.python_codegen \
  src/nomos_c0/author_abilities/examples/avalon_cognition.lib.yaml \
  src/nomos_c0/author_abilities/examples/avalon_random.source.yaml \
  build/python-codegen/avalon-learned.py \
  --cognition src/nomos_c0/author_abilities/examples/avalon_local.cognition.yaml \
  --ai src/nomos_c0/author_abilities/examples/avalon_learned.ai.yaml \
  --presentation src/nomos_c0/author_abilities/examples/avalon_council.presentation.yaml

PYTHONPATH=src .venv/bin/python -m nomos_play build/python-codegen/avalon-learned.py \
  --assets src/nomos_c0/author_abilities/examples/avalon_random.assets.yaml --port 8860
```

打开命令打印的地址、选择席位。点击行动或牌面，选择本次输入并确认；
每次正式提交后，获准看到的变化逐组显示，再开放下一次决策。
桌面分为“对局”“线索与判断”“对局记录”；真实终局后开放“赛后复盘”。
作者强调的关键消息置于页面顶部，保留未读标记，读完后仍可在记录页查阅。
身份自称按实际发言显示，任务结算按实际报告显示；切页、已读与回看都保持本地只读。
记录页按提队分组，可组合搜索关键词、消息类型、涉及玩家、发言人与未读状态。
操作区可直接查看本次提队的记录，座位上的查看图标可检索该人物的相关记录。
建议／质疑理由附有说明；引用历史的理由可查看对应提队，筛选结果可批量标记已读。
入座后才发身份牌，每次新局重新洗牌；角色池仍为梅林、帕西瓦尔、忠臣、莫甘娜和刺客。
选席前即可打开“规则与流程”；入桌后本人信息在操作区上方，公开摘要保留当前局面。
本配置让每个席位根据本人线索与实际经历形成判断，公开发言也进入过程展示。
“我的判断”查看本人当前人数界与依据，“当前行动建议”分开显示信息依据、局势判断和行为取舍。
说明读取作者声明的建议快照，评分分项仍保留；换局面后清除旧建议。
播放、回看、刷新与个人笔记保持只读。当前选择可按需请求本人策略的评分建议。
阿瓦隆顶部显示五轮人数、失败门槛和完成结果，席位使用数字称呼；赞成／反对直接提交，可选发言单独展开。
“建议或质疑这支队伍”选择立场及当前合法理由：个人判断、失败任务重叠、验证新组合或采信他人。
实际收到的理由进入NPC判断，历史表现影响采信权重；发言之后仍可独立表决。
相近队伍的成功／失败经验按成员重叠迁移，保留百分位到汇总加权后再取整；
“相近队伍经验”显示实际加权贡献。成功经历影响选队偏好，可靠身份范围由本人信息另行约束。
终局复盘中的“赛后心理历程”可选择各席位，先看整局热力图，再展开记录明细。
身份线索图按判断维度切换，分别查看单人和组合的确定／待定／排除及人数范围；
评价图保留各次实际评价的正负分。点击图格可查看该检查点，并跳转当时消息或判断记录。
图表读取已保存的历史，不重跑策略；没有记录保持未知，后来的身份揭晓不回填早期判断。
刺客使用独立冻结模型选择刺杀目标；发布后，心理历程增加该次决策实际保存的梅林概率条。
前期行动沿用原策略；模型输入、训练和对照见学习策略指南（研究仓路径：`docs/guides/AUTHOR_LEARNED_POLICY_V1.md`）。
该功能由作者`recap: {cognition: true}`显式启用，只在真实终局后开放。
电脑行动可展开“当时的决策依据”，按信息、判断和取舍回看真实提交时的说明；评分分项单独折叠。
狼人共同意向使用独立协调机会，选中草稿保持未提交，实际锁定仍是正式行动。

生成其他世界时替换 Lib/Source/AI/呈现路径；Assets 独立提供。
构建可选 `--cognition` 把本人认知模型与读回接入同一世界。
默认 `python -m nomos_play` 使用本目录 `games.yaml`，其中生成文件需要预先构建。
目录包含阿瓦隆、狼人杀、璀璨宝石与波多黎各经济阶段，后者仍为现行经济首片。
自定义目录使用 `--catalog /path/to/games.yaml`，每项声明 `id/title/description/world/assets`，
相对路径以目录文件位置为准。目录公开介绍，选中后加载产物；实际入座时检查并创建本局初态，服务内复用精确 Program。
原作者前缀及运行时 `--lib/--source/--ai/--cognition` 参数已移除。

阿瓦隆三种风格共用同一Lib、Source、Assets和认知。使用上方生成命令，分别将AI/输出改为：

| 风格 | AI入口 | 输出 |
| --- | --- | --- |
| 均衡 | `avalon_learned.ai.yaml` | `build/python-codegen/avalon-learned.py` |
| 谨慎 | `avalon_learned_cautious.ai.yaml` | `build/python-codegen/avalon-learned-cautious.py` |
| 直率 | `avalon_learned_forthright.ai.yaml` | `build/python-codegen/avalon-learned-forthright.py` |

AI文件均在`src/nomos_c0/author_abilities/examples/`。三份生成后运行：

```bash
.venv/bin/python -m nomos_play --catalog src/nomos_play/avalon_styles.yaml --port 8897
```

生成文件与运行库需配套使用；更新生成函数合同后重新编译，不混用旧产物。

随机开局由[Source](../nomos_c0/author_abilities/examples/avalon_random.source.yaml)的
`opening.identities`声明，Assets省略各人的`role`并使用`random: {seed: fresh}`。
调试时可复制Assets，将`fresh`换成整数重放同一发牌；相同整数不受玩家座位或AI风格影响。
固定身份的`avalon.source.yaml`／`avalon.assets.yaml`保留为规则定向场景。

## 作者与桌面的接口

Lib/Source 声明规则、命名输入与控制机制；AI 和认知独立配置。
可选 presentation 声明标题、翻译、组件、规则书、面板、人物标记和输入预览。
生成器在 Compile 时完成读权/类型检查与接线，输出 `PROGRAM / CONTROLLERS / DISPLAY`。
未选呈现文件的桌游具有默认显示。

桌面通过 `CompiledDisplay` 取得许可读回和提示，通过当前 ChoiceForm 绑定输入；
`TableControl` 是唯一的电脑推进与共同决策控制实现。
真实提交由 Session 当前准入、效果、报告、终局和原子事务负责。
前端不查询其他席位私态，也不按游戏名称复制规则。
本人身份组件可通过已有 badge `description` 提供角色说明，显示在本人信息中。
复盘的每项确认附提交前已授权公开摘要，保留当时阶段、轮次和队伍等信息；
只读回看结束恢复整段已提交事件，终局人物表按桌边席位排列，普通历史表保持原顺序。
交付包见生成运行包（研究仓路径：`docs/guides/AUTHOR_GAME_PACKAGES_V1.md`）。

## 当前迁移状态

生成桌面/运行包的新入口已接入，旧K0及解释执行链已退役。
干净安装、隔离运行与阿瓦隆认知整合已验证；三批玩家修复已收束，最后86/86未达双88体验门。
本轮状态见Goal 证据账（研究仓路径：`docs/coordination/PYTHON_RUNTIME_AND_AVALON_PLAY_GOAL_V1.md`）。
正式发行仓库与现有 M1 Web 使用各自冻结版本。
后继四桌游交互整理（研究仓路径：`docs/closure_notes/TABLETOP_INTERACTION_PASS_V1.md`）为新的Owner任务，
补齐共享操作与复盘短门，不改写上述Goal评分。
随后阿瓦隆已完成知识消费、角色动机，以及独立风格与本人说明；技术验证和独立体验评分分别记录。
