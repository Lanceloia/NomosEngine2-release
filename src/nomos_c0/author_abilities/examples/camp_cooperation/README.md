# 营地协作实验

三人在营地中求助、采集和交换物资。这个non-canon样例用来检验：
真实回应能否改变以后对同一人的选择、既有经验能否评价第一次出现的合法候选，
以及新获知的情境如何改变旧经历的参与方式。

## 规则与文件

| 文件 | 内容 |
| --- | --- |
| [world.lib.yaml](world.lib.yaml) | 人物、请求／答复、采集、多人分享和实际回应事件 |
| [world.source.yaml](world.source.yaml) | 三个开局人物及所选规则、报告接线 |
| [world.assets.yaml](world.assets.yaml) | A没有物资，B也没有，C有两份；各人40精力 |
| [world.ai.yaml](world.ai.yaml) | 独立候选语义、回应反馈与人物策略范围 |

- 求助消耗1精力，可向另一人请求一份物资；拥有代币时还可提出付一枚代币交换。
- 接收者取得请求，可接受或拒绝；接受需要自己确实有物资。
  答复消耗1精力，物资和代币转移、请求完成状态、实际报告原子发布。
- 采集消耗2精力，得到一份物资和一枚代币，从而出现新的交换候选。
  等待答复期间也能采集；等待只限制再次求助。
- 人物可把物资一次分享给多人，随后发布计数Event；这条规则也用于多owner测量。
- 人物可花1精力向指定观察者展示库存，只交付“当时有／无物资”的真实记录。
  收到记录后，观察者能区分尚未知晓、上次看见为空、上次看见有物资。
  发起人也取得本人展示给谁、展示了什么的记录，用于评价重复信息。
- 人物身份及请求编号／等待状态公开；物资、代币、精力保存在本人的视图。
  请求仅交给指定接收者，详细答复仅交给求助者；公共活动记录另由Event发布。

AI定义`provision / fellowship / effort / closure`四个评价维度。
补给指标为`2×物资+代币`的净变化：采集增加3，求助成功获得2或付费后的1，拒绝增加0；
人际体验由作者主观解释，精力成本和处理请求的进展分别记录。
求助的实际回应形成针对同一人物、同一局内情境的经验；
相似候选可复用这些案例，不同人物的个人经历分别匹配。
响应倾向由本人的人格／目标权重影响，物资许可仍由世界规则检查。
`valuation`单独表达当前价值：两份物资满足本例储备需求，新增补给价值归零；
相同库存状态已向同一人展示时，再次展示的主观互助价值归零。
这些系数保留原始结果估计、实际反馈和全部案例。

本人的公开活动收件也可形成弱印象：最近看见对方帮助／拒绝别人，
分别给求助的人际先验加1／减1。物资是否还在、对本人是否愿意帮助，仍待实际接触。
同一人的亲身答复出现后，旁观加分停止参与，由原经验估计器使用本人的真实反馈。
`support_impression`及候选说明保留公开记录、亲身记录、原始信号与采用方式；
查询只读已有报告，普通重复阅读不增加记忆或样本。

## 运行对照

在仓库根目录执行：

```bash
.venv/bin/python -m tools.camp_cooperation \
  --output .playtest-artifacts/camp.json.gz
```

教学控制器先安排两次向B求助。B尚无物资，实际拒绝并消耗精力；
A收到答复后，对B的求助评分从`1`降到`-1/3`。
在同一当前候选帧中移除经验，稳定同分策略仍会选B；保留真实经验则选C，
控制器实际提交这个评分选择，C按自己的权重接受。

接着教学控制器安排B采集并提供两次帮助，A对B的补给收获估计由`2/3`升到`6/5`。
A此时已有充足物资，该候选的当前价值系数为0，总分为精力成本`-1`。
A采集得到第一枚代币后，首次出现的“付代币向B交换”候选取得四份求助经历的贡献，
相似度均为`1/2`，补给估计为`1`；这些案例此前都没有交换输入。
最后对C的同一个回应帧使用两组人格权重，分别选出接受和拒绝，实际提交愿意帮助的选择。

这条路线共15次真实Action，另有6次回应Event；A保留6份实际反馈样本。
报告区分`specified_lesson`教学安排、`scored_request`评分选择与`scored_response`评分答复，
并保存候选特征、逐维估计、完整贡献和实际发生来源。
实验使用现行纯记忆／评价算法和正式候选提交端口，控制器只组织这些调用。

## 情境与经验对照

```bash
.venv/bin/python -m tools.camp_context \
  --output .playtest-artifacts/camp-context.json.gz
```

A先收到B两次拒绝。B随后采集；补货本身、仅向C展示，都保持A原来的判断。
B向A实际展示后，A才取得新的库存线索：旧案例的物资收益估计暂停参与，
人际评价仍然保留。A由评分选择再次向B求助并实际获得帮助，形成新情境的成功案例。
之后依次展示空库存、暗中补货、再次展示，检查判断随本人收件更新。

这条路线共12次Action和3次回应Event。报告保留每阶段的实际收件、候选解释、
分维度贡献与评分，以及每次真实提交。展示表示上次所见；库存随后可变化，
拥有物资的人仍可自行拒绝求助。

同一份回应评价还对照三组偏好：普通权重拒绝、重视互助时接受、
重视互助但当前更需保留物资时拒绝。三个结果分别在独立开局中真实发布。
当前价值、可读对照与完整报告（研究仓路径：`docs/evidence/camp-valuation-v1/README.md`）
逐项说明“收到什么→哪些经历参与→评分变化→实际行动”。

## 连续自主选择

此节四组统计属于情境价值版本的冻结证据；后继旁观规则的独立对照见下一节，
不把旧路线计数作为新配置的实跑结果。

```bash
.venv/bin/python -m tools.camp_autonomy \
  --seeds 0 7 --turns 36 \
  --output .playtest-artifacts/camp-autonomy.json.gz \
  --markdown .playtest-artifacts/camp-autonomy.md
```

三人各绑定正式`Subject`，在轮流获得的机会中自行选择请求、答复、采集或展示。
每个主体按本人收件更新记忆；工具只组织机会和有界停止，并保存同帧空经验对照。
主体显式采用保留价值0，没有值得做的事时返回`no_interest`；新请求可以唤起新的判断。
到达观测上限或三人本轮都暂停时，同步并中断参与，原世界保留。

四组36次机会内，当前配置执行16–20次行动后暂停，三人均补足物资、没有待答复请求，
重复同值展示为0；这些路线主要靠各自采集。另有全候选的自愿帮助短例。
当前结果与逐步中文记录（研究仓路径：`docs/evidence/camp-valuation-v1/README.md`）
和首批重复行为（研究仓路径：`docs/evidence/camp-autonomy-v1/README.md`）分别保存。

## 旁观后再亲身接触

```bash
.venv/bin/python -m tools.camp_observation \
  --output .playtest-artifacts/camp-observation.json.gz \
  --markdown .playtest-artifacts/camp-observation.md
```

两条路线中B开局都有一份物资，C先请求帮助。B实际接受／拒绝后，A收到对应公开记录，
尚无本人求助反馈；同一人格和目标下，A实际分别选择B／C。
前一条路线继续让A亲自被B拒绝，A随后实际改向C求助。
工具指定B/C的教学行动，A采用完整候选及正式Subject提交。
逐步对照和来源（研究仓路径：`docs/evidence/camp-observation-v1/README.md`）保留这两种经验的区别。

## 手动体验

```bash
.venv/bin/python -m nomos_c0.python_codegen \
  src/nomos_c0/author_abilities/examples/camp_cooperation/world.lib.yaml \
  src/nomos_c0/author_abilities/examples/camp_cooperation/world.source.yaml \
  build/camp.py \
  --ai src/nomos_c0/author_abilities/examples/camp_cooperation/world.ai.yaml
.venv/bin/python -m nomos_runtime build/camp.py \
  --assets src/nomos_c0/author_abilities/examples/camp_cooperation/world.assets.yaml --manual
```

可切席操作求助和答复，输入`q`退出。实验验收关注上述对照，前端和完整冒险留给独立任务。
规则、AI与教学路线分别编辑；修改人格权重即可对照同一事实下的不同回应。

源码负载测量（研究仓路径：`docs/evidence/nomos-source-workloads-v1/README.md`）
记录人数／历史增长的实际结算与评价成本；验证记录（研究仓路径：`docs/closure_notes/NOMOS_SOURCE_WORKLOADS_AND_CAMP_V1.md`）
列出收件隔离、错误读取、原子转账和重复答复的短门。
