"""Interactive trusted controls for an already generated world, with Actor-local reads."""

import json

from .documents import parse_data
from .errors import AdmissionError
from .expressions import ExpressionError, ValueBindingError
from .ordering import canonical

INPUT_ERRORS = (ValueError, AdmissionError, ExpressionError, ValueBindingError)


class CancelInput(Exception):
    pass


class OutputError(Exception):
    """A committed Action must never be reported as unsubmitted after output fails."""


class Terminal:
    def __init__(self, session, *, actor=None, manual=False, ask=None, write=None):
        self.session, self.program = session, session.program
        self.ask = input if ask is None else ask
        self.write = print if write is None else write
        self.manual = manual
        play = self.program.play
        self.playing = play is not None and not manual
        if self.playing and play.mechanism == "player_turn":
            if actor not in (None, play.player):
                raise ValueError("player_turn uses its declared player; use --manual for debugging")
            actor = play.player
        self.actor = actor or self.program.actors[0][0]
        session.actor_reference(self.actor)
        self.table = (
            session.table_control(self.actor)
            if self.playing and play.mechanism == "tabletop"
            else None
        )
        self.opportunity = None
        self.resume = False

    def prompt(self, text):
        value = self.ask(text).strip()
        if value.lower() in ("q", "cancel"):
            raise CancelInput()
        return value

    def encode(self, kind, value):
        codec = self.session.values(self.actor)

        def reference(ref):
            codec.references.require(ref, ref.sort)
            name = codec.names.get(ref)
            if name is not None:
                return name
            return {"individual": ref.ordinal, "sort": ref.sort}

        return codec.encode(kind, value, reference=reference)

    def show(self, kind, value):
        return json.dumps(self.encode(kind, value), ensure_ascii=False)

    def choose(self, ability, request=None):
        """Bind only current unresolved inputs; the Session checks the complete selection."""
        choices = {}
        while True:
            form = self.session.choice_form(self.actor, ability, choices, request=request)
            if form.complete:
                return choices
            field = next((field for field in form.fields if field.ready), None)
            if field is None:
                raise ValueError("current input dependencies have no ready field")
            pool = None if field.pool is None else sorted(field.pool, key=canonical)
            while True:
                try:
                    if pool is None:
                        raw = self.prompt(
                            f"  {field.name}: {field.type_name}，输入 YAML 值（q 取消）："
                        )
                        wire = parse_data("value: " + raw)["value"]
                        value = self.session.values(self.actor).decode(field.type_name, wire)
                    else:
                        self.write(f"  {field.name}: {field.type_name}")
                        for index, item in enumerate(pool, 1):
                            shown = self.encode(field.element_type, item)
                            self.write(
                                f"    {index}. "
                                + json.dumps(
                                    shown,
                                    ensure_ascii=False,
                                )
                            )
                        if field.kind == "member" and not pool:
                            raise CancelInput("当前输入域为空")
                        bounds = (
                            "一个编号"
                            if field.kind == "member"
                            else f"{field.minimum}–{field.maximum} 个"
                            if field.kind == "subset"
                            else f"{field.length} 个，重复政策 {field.repetition}"
                        )
                        raw = self.prompt(f"  输入编号（{bounds}；空格分隔，q 取消）：")
                        indexes = [int(item) for item in raw.split()]
                        if any(not 1 <= index <= len(pool) for index in indexes):
                            raise ValueError("编号不在当前输入域内")
                        selected = [pool[index - 1] for index in indexes]
                        if field.kind == "member":
                            if len(selected) != 1:
                                raise ValueError("请选择一个编号")
                            value = selected[0]
                        elif field.kind == "subset":
                            if len(set(selected)) != len(selected):
                                raise ValueError("子集不能重复选择")
                            value = frozenset(selected)
                        else:
                            value = tuple(selected)
                    candidate = {**choices, field.name: value}
                    self.session.choice_form(self.actor, ability, candidate, request=request)
                    choices = candidate
                    break
                except INPUT_ERRORS as error:
                    self.write("输入未通过：", error)

    def show_view(self):
        session, program, actor = self.session, self.program, self.actor
        if program.time is not None:
            self.write("局内时刻：", session.read_time())
        reference = session.actor_reference(actor)
        fields = dict(program.schemas[reference.sort].fields)
        self.write(
            "\n",
            str(actor),
            {name: self.show(fields[name], value) for name, value in session.read(actor).items()},
        )
        for context in program.contexts:
            if context.public:
                types = dict(context.fields)
                self.write(
                    context.name + ":",
                    {
                        name: self.show(types[name], value)
                        for name, value in session.read_context(actor, context.name).items()
                    },
                )
        for channel, kind in program.channels.items():
            history = session.reports(actor, channel)
            if history["acquired"]:
                self.write(channel + ":", [self.show(kind, value) for value in history["values"]])
        for name, definition in program.projections.items():
            if session.references.accepts(definition.viewer_sort, reference.sort):
                item = session.project(actor, name)
                self.write(
                    name + ":",
                    self.show(definition.type_name, item["value"])
                    if item["available"]
                    else "不可用",
                )
        for name, definition in program.information.items():
            item = session.report(actor, name)
            self.write(
                name + ":",
                self.show(definition.type_name, item["value"]) if item["acquired"] else "未取得",
            )
        ending = session.ending(actor)
        if ending["status"] == "closed":
            self.write("世界已结束。")
            if ending["available"]:
                self.write("最终结算：", self.show(program.terminal.result_type, ending["value"]))
            return None
        if ending["status"] == "draining":
            self.write("正在收束已有过程。")
        options = [(name, None, None) for name in session.available_abilities(actor)]
        for request in session.requests(actor):
            definition = program.processes[request.process][request.point]
            options.append((definition.name, request, None))
        options.extend((offer.name, None, offer) for offer in session.activity_offers(actor))
        for index, (name, request, offer) in enumerate(options, 1):
            label = (
                f"待选择 · {request.process}.{request.point} · {request.prompt}"
                if request
                else f"取消活动 · {name} · 到期 {offer.due_at}"
                if offer
                else name
            )
            self.write(f"{index}. {label}")
            if request:
                reports = session.decision_reports(actor, request)
                for alias, kind in program.actions[name].local_types:
                    self.write("  本次信息 · " + alias + ":", self.show(kind, reports[alias]))
        if not options:
            self.write("当前没有可发起的能力或待回应选择。")
        if program.time is not None:
            self.write(
                "wait 交还本次行动机会。"
                if program.time.schedules
                else "wait 等待下一到期，wait 时刻推进时间。"
            )
        if self.table is not None and self.table.coordination_offer() is not None:
            self.write("coordinate 让共同决策中的电脑重新考虑。")
        if self.table is not None and self.table.joint.has_paused():
            self.write("continue 恢复共同决策的电脑预算。")
        return options

    def show_result(self, ability, result):
        if result.status != "published":
            self.write("行动未发生：", result.code or result.status)
            return
        try:
            definition = self.program.actions.get(ability)
            if definition is None:
                definition = next(
                    item.cancel for item in self.program.time.activities if item.name == ability
                )
            self.write("实际结果：", self.show(definition.result_type, result.feedback))
            for channel, value in result.reports:
                self.write(channel + ":", self.show(self.program.channels[channel], value))
        except Exception as error:
            raise OutputError("行动已发布，结果显示失败；请重新读取当前局面") from error

    def drive(self):
        self.opportunity = None
        if self.playing:
            if self.table is not None:
                result = self.table.resume_coordination() if self.resume else self.table.drive()
            else:
                result = self.session.drive_play()
            self.resume = False
            self.opportunity = result.opportunity
            if result.actions or result.occurrences:
                self.write(
                    f"世界推进：{result.actions} 次人物行动，{result.occurrences} 条实际发生。"
                )
            if result.status not in ("ready", "waiting", "closed"):
                self.write("控制停点：", result.status, result.code or "")
                continuing = self.ask("continue 继续推进，q 退出：").strip() == "continue"
                if continuing and self.table is not None:
                    state = self.table.coordination_state()
                    self.resume = bool(state and state["paused"])
                return continuing
        elif self.program.time is not None and self.program.time.schedules:
            result = self.session.next_opportunity()
            self.opportunity = result.opportunity
            if self.opportunity is not None:
                self.actor = self.opportunity.actor
                self.write("当前行动机会：", str(self.actor))
            elif result.status == "due":
                self.write("到期事件已结算：", result.occurrences)
        return None

    def command(self, selection, options):
        session = self.session
        if selection.startswith("seat ") or selection == "controllers":
            if self.playing:
                self.write("受信多席控制请用 --manual 启动。")
                return
            controllers = session.actor_controllers()
            chosen = selection[5:].strip()
            if selection == "controllers":
                for index, controller in enumerate(controllers, 1):
                    self.write(f"{index}. {controller}")
            elif chosen in dict(self.program.actors):
                self.actor = chosen
            elif chosen.isdecimal() and 1 <= int(chosen) <= len(controllers):
                self.actor = controllers[int(chosen) - 1]
            else:
                self.write("可控人物：", ", ".join(str(c) for c in controllers))
        elif selection == "auto":
            decision = session.propose(self.actor)
            self.write("本地策略：", decision.status)
            if decision.proposal is not None:
                self.write(f"策略提案：{decision.proposal.ability} · {decision.proposal.score}")
                self.show_result(
                    decision.proposal.ability,
                    session.submit_proposal(self.actor, decision.proposal),
                )
        elif selection == "continue" and self.table is not None:
            result = self.table.resume_coordination()
            self.write("共同决策：", result.status, result.code or "")
        elif selection == "coordinate" and self.table is not None:
            offer = self.table.coordination_offer()
            if offer is None:
                raise ValueError("当前没有共同决策机会")
            result = self.table.coordinate(offer)
            self.write("共同决策：", result.status, result.code or "")
        elif selection == "wait" or selection.startswith("wait "):
            if self.program.time is None:
                raise ValueError("当前世界没有选择时间机制")
            if self.program.time.schedules:
                if selection != "wait" or self.opportunity is None:
                    raise ValueError("调度世界使用 wait 交还当前机会")
                self.write(
                    "控制结果：", session.defer_opportunity(self.actor, self.opportunity).status
                )
            else:
                result = session.advance(None if selection == "wait" else int(selection[5:]))
                self.write(f"时间推进：{result.status} · 实际时刻 {result.at}")
        else:
            if not selection.isdecimal() or not 1 <= int(selection) <= len(options):
                raise ValueError("请输入当前显示的编号")
            ability, request, offer = options[int(selection) - 1]
            if offer is not None:
                result = session.cancel_activity(self.actor, offer)
            else:
                choices = self.choose(ability, request)
                result = session.act(self.actor, ability, choices, request=request)
            self.show_result(ability, result)

    def run(self):
        while True:
            try:
                driven = self.drive()
                if driven is False:
                    return
                if driven is True:
                    continue
                options = self.show_view()
                if options is None:
                    return
                selected = self.ask("选择编号，seat 名字换席，q 退出：").strip()
                if selected.lower() in ("q", "quit"):
                    return
                try:
                    self.command(selected, options)
                except CancelInput:
                    self.write("已取消本次选择。")
                except INPUT_ERRORS as error:
                    self.write("本次选择未提交：", error)
            except EOFError:
                return
