"""Feedback policies read saved choice values and acquired messages, never live owners."""

from dataclasses import dataclass, replace

from nomos_c0.author_contract_v1 import C0LawError

from .effects import EffectCompiler
from .expression_syntax import _identifier
from .frontend import row


@dataclass(frozen=True)
class FeedbackRelation:
    key: object
    link: object
    roots: object
    depth: int


@dataclass(frozen=True)
class FeedbackReceipt:
    name: str
    kind: str
    channel: str
    source: str
    type_name: str
    matches: tuple
    collection_type: str | None
    item: str | None
    until: str | None
    predicate: object
    boundary: bool
    relation: FeedbackRelation | None


@dataclass(frozen=True)
class FeedbackPlan:
    name: str
    ability: str
    inputs: tuple
    receipts: tuple
    outcomes: tuple
    when: object
    personal: bool


def compile_feedback(profile, declaration, candidates, abilities, table, pure, channels, terminal):
    if type(declaration) is not dict or len(declaration) > 32:
        raise C0LawError("feedback requires at most 32 named policies")
    plans = {p.name: p for p in abilities}
    result = []
    for name, body in declaration.items():
        path = "semantics." + profile.name + ".feedback." + str(name)
        if not _identifier(name):
            raise C0LawError(path + ": named feedback policy required")
        row(body, {"definition", "receipts", "outcomes"}, {"point", "when", "personal"}, path=path)
        definitions = body["definition"]
        definitions = [definitions] if type(definitions) is str else definitions
        if (
            type(definitions) is not list
            or not definitions
            or len(definitions) > 32
            or any(not _identifier(item) for item in definitions)
            or len(set(definitions)) != len(definitions)
        ):
            raise C0LawError(path + ": distinct selected feedback definitions required")
        matches = [
            c
            for c in candidates
            if plans[c.ability].definition in definitions
            and ("begin" if plans[c.ability].process is None else plans[c.ability].process.point)
            == body.get("point", "begin")
        ]
        if {plans[c.ability].definition for c in matches} != set(definitions):
            raise C0LawError(path + ": feedback requires a selected candidate definition/point")
        personal = body.get("personal", False)
        if type(personal) is not bool:
            raise C0LawError(path + ": personal must be boolean")
        ports = body["receipts"]
        if type(ports) is not dict or not 1 <= len(ports) <= 8:
            raise C0LawError(path + ": one to eight acquired receipt ports required")
        for candidate in matches:
            plan, meaning = plans[candidate.ability], candidate.meaning
            if personal and meaning.target is None:
                raise C0LawError(path + ": personal feedback requires a semantic target")
            inputs = tuple((i.name, i.type_name) for i in plan.inputs.inputs if i.kind != "derive")
            correlation = {key: kind for key, kind, _ in meaning.correlation}
            captured = {key: kind for key, kind, _ in meaning.capture}
            bindings = dict(inputs)
            if set(bindings) & (set(correlation) | set(captured)):
                raise C0LawError(path + ": saved names overlap choice inputs")
            bindings.update(correlation)
            bindings.update(captured)
            signatures = {}
            for alias, port in ports.items():
                if not _identifier(alias) or alias in bindings:
                    raise C0LawError(path + ": receipt names must be distinct from saved inputs")
                location = path + ".receipts." + alias
                if isinstance(port, dict) and "terminal" in port:
                    row(port, {"terminal"}, {"boundary"}, path=location)
                    if terminal is None or port["terminal"] != terminal.name:
                        raise C0LawError(path + ": unknown selected terminal")
                    kind = terminal.value.result.name
                    signatures[alias] = ("terminal", "terminal", terminal.name, kind)
                else:
                    if isinstance(port, dict) and "collect" in port:
                        row(port, {"channel", "collect", "where"}, {"related"}, path=location)
                        row(port["collect"], {"type", "item", "until"}, path=location + ".collect")
                    else:
                        row(port, {"channel", "match"}, {"boundary"}, path=location)
                    channel = port["channel"]
                    if type(channel) is not str or ("reports", channel) not in channels:
                        raise C0LawError(path + ": unknown acquired receipt channel")
                    kind, source, _ = channels["reports", channel]
                    signatures[alias] = ("delivery", channel, source, kind)
                if "collect" in port:
                    collection = port["collect"]
                    type_name, item, until = (collection[k] for k in ("type", "item", "until"))
                    if type(type_name) is not str or type_name not in dict(table.definitions):
                        raise C0LawError(location + ": declared sequence type required")
                    result_type = table[type_name]
                    if result_type.kind != "sequence" or result_type.element.name != kind:
                        raise C0LawError(
                            location + ": sequence must contain the channel value type"
                        )
                    if not _identifier(item) or item in bindings or item in ports:
                        raise C0LawError(location + ": distinct collection item required")
                    if (
                        type(until) is not str
                        or until not in ports
                        or type(ports[until]) is not dict
                        or "collect" in ports[until]
                    ):
                        raise C0LawError(location + ": collection requires a unique receipt anchor")
                    bindings[alias] = type_name
                else:
                    bindings[alias] = kind
                if type(port.get("boundary", False)) is not bool:
                    raise C0LawError(location + ": boundary must be boolean")
                if port.get("boundary", False) and not any(
                    type(p) is dict
                    and type(p.get("collect")) is dict
                    and p["collect"].get("until") == alias
                    for p in ports.values()
                ):
                    raise C0LawError(location + ": boundary must close a receipt collection")
            boundaries = {alias for alias, port in ports.items() if port.get("boundary", False)}
            branch = EffectCompiler(
                table, bindings, library=pure, entities=pure.entities, actor=None
            )

            def expression(text, kind, location, compiler=branch, *, match=False):
                checked = compiler.expression(text, kind, location, context="actor")
                if checked.summary.owner_reads or checked.summary.reference_domains:
                    raise C0LawError(
                        path + ": feedback may only read saved values, not live owners"
                    )
                used = {r.root for r in checked.summary.reads}
                if not match and used & boundaries:
                    raise C0LawError(path + ": completion-only boundaries cannot supply outcomes")
                return replace(checked, inputs=tuple(i for i in checked.inputs if i[0] in used))

            receipts = []
            for alias, port in ports.items():
                if signatures[alias][0] == "terminal":
                    receipts.append(
                        FeedbackReceipt(
                            alias,
                            *signatures[alias],
                            (),
                            None,
                            None,
                            None,
                            None,
                            port.get("boundary", False),
                            None,
                        )
                    )
                    continue
                if "collect" in port:
                    collection = port["collect"]
                    saved = {**dict(inputs), **correlation, **captured}
                    item = collection["item"]
                    compiler = EffectCompiler(
                        table,
                        {**saved, alias: collection["type"], item: signatures[alias][3]},
                        library=pure,
                        entities=pure.entities,
                        actor=None,
                    )
                    predicate = expression(
                        port["where"], "Bool", path + ".receipts." + alias + ".where", compiler
                    )
                    relation = None
                    if "related" in port:
                        spec = port["related"]
                        location = path + ".receipts." + alias + ".related"
                        row(spec, {"key", "link", "roots", "depth"}, path=location)
                        if type(spec["depth"]) is not int or not 1 <= spec["depth"] <= 16:
                            raise C0LawError(location + ": depth must be an integer from 1 to 16")
                        projection = EffectCompiler(
                            table,
                            {item: signatures[alias][3]},
                            library=pure,
                            entities=pure.entities,
                            actor=None,
                        )
                        saved_compiler = EffectCompiler(
                            table,
                            saved,
                            library=pure,
                            entities=pure.entities,
                            actor=None,
                        )
                        key = expression(spec["key"], None, location + ".key", projection)
                        if key.result.kind in {"optional", "unit"} or key.result.name not in dict(
                            table.definitions
                        ):
                            raise C0LawError(location + ": declared nonoptional key type required")
                        link = expression(spec["link"], None, location + ".link", projection)
                        roots = expression(spec["roots"], None, location + ".roots", saved_compiler)
                        link_kind = (
                            link.result.element if link.result.kind == "optional" else link.result
                        )
                        if (
                            link_kind.type_id != key.result.type_id
                            or roots.result.kind not in {"set", "sequence"}
                            or roots.result.element.type_id != key.result.type_id
                        ):
                            raise C0LawError(
                                location
                                + ": declared key, matching link and root element types required"
                            )
                        relation = FeedbackRelation(key, link, roots, spec["depth"])
                    receipts.append(
                        FeedbackReceipt(
                            alias,
                            *signatures[alias],
                            (),
                            collection["type"],
                            item,
                            collection["until"],
                            predicate,
                            False,
                            relation,
                        )
                    )
                    continue
                match = port["match"]
                if type(match) is not dict or set(match) != set(correlation):
                    raise C0LawError(
                        path + ": receipt match must cover exact trial correlation keys"
                    )
                checked_matches = []
                for key, kind in correlation.items():
                    checked = expression(match[key], kind, path + ".match." + key, match=True)
                    if {r.root for r in checked.summary.reads} - {alias}:
                        raise C0LawError(path + ": receipt match reads only its acquired port")
                    checked_matches.append((key, kind, checked))
                receipts.append(
                    FeedbackReceipt(
                        alias,
                        *signatures[alias],
                        tuple(checked_matches),
                        None,
                        None,
                        None,
                        None,
                        port.get("boundary", False),
                        None,
                    )
                )
            outcomes = body["outcomes"]
            if (
                type(outcomes) is not dict
                or not outcomes
                or not set(outcomes) <= set(profile.outcomes)
            ):
                raise C0LawError(path + ": observed outcome axes must belong to the profile")
            checked_outcomes = []
            for axis, text in outcomes.items():
                checked = expression(text, None, path + ".outcomes." + axis)
                if checked.result.kind != "int":
                    raise C0LawError(path + ": integer feedback outcomes required")
                checked_outcomes.append((axis, checked))
            result.append(
                FeedbackPlan(
                    name,
                    candidate.ability,
                    inputs,
                    tuple(receipts),
                    tuple(checked_outcomes),
                    expression(body.get("when", "True"), "Bool", path + ".when"),
                    personal,
                )
            )
    return tuple(result)


def fingerprints(plans):
    return tuple(
        (
            p.name,
            p.ability,
            p.inputs,
            p.personal,
            p.when.read_key,
            tuple((axis, expr.read_key) for axis, expr in p.outcomes),
            tuple(
                (
                    r.name,
                    r.kind,
                    r.channel,
                    r.source,
                    r.type_name,
                    tuple((key, kind, expr.read_key) for key, kind, expr in r.matches),
                    r.collection_type,
                    r.item,
                    r.until,
                    None if r.predicate is None else r.predicate.read_key,
                    r.boundary,
                )
                + (
                    ()
                    if r.relation is None
                    else (
                        (
                            "related",
                            r.relation.key.read_key,
                            r.relation.link.read_key,
                            r.relation.roots.read_key,
                            r.relation.depth,
                        ),
                    )
                )
                for r in p.receipts
            ),
        )
        for p in plans
    )
