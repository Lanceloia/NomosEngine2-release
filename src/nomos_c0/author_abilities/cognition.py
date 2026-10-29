"""Compile independent typed revision models against one unchanged world Program."""

import hashlib
import json
from dataclasses import dataclass, replace

from nomos_c0.author_contract_v1 import C0BindingError, C0LawError

from .expression_syntax import ExpressionLimits, _identifier
from .expressions import compile_value_expression
from .local_views import compile_local_views
from .opening import OpeningSymbol, ParameterValue, value_node


@dataclass(frozen=True)
class RevisionRule:
    name: str
    channel: object
    item: str
    accept: object
    slot: object
    where: object
    proposition: object | None
    support: object | None
    opposition: object | None
    appraisal: object | None
    score: object | None


@dataclass(frozen=True)
class CognitionBinding:
    name: str
    digest: str
    selector: str
    target: str
    families: tuple
    actor: str
    actor_type: str
    parameters: tuple
    rules: tuple
    proposition_type: str
    appraisal_type: str
    slot_type: str
    view_type: str
    budget: int
    prior_type: str
    derivations: tuple
    inference_limits: object
    finite: object | None
    local: object | None

    def matches(self, actor, symbols):
        return actor.family in self.families and (
            self.selector == "kind"
            or any(s.symbol == self.target and s.reference == actor for s in symbols)
        )


@dataclass(frozen=True)
class CognitionPlan:
    program: object
    bindings: tuple


def _view_contract(table, name, prior_name, proposition, appraisal, finite, local):
    def record(plan, fields):
        if plan.kind != "record" or set(dict(plan.fields)) != fields:
            raise C0LawError("cognition view has an incompatible record contract")
        return dict(plan.fields)

    view = record(
        table[name],
        {"beliefs", "appraisals", "inferences", "complete"}
        | ({"analysis"} if finite else set())
        | ({"local"} if local else set()),
    )
    prior = record(table[prior_name], {"beliefs", "appraisals", "complete"})
    if any(prior[key].type_id != view[key].type_id for key in prior):
        raise C0LawError("cognition prior must have the same base judgments as its output")
    if view["complete"].kind != "bool":
        raise C0LawError("cognition view.complete requires Bool")
    if any(view[key].kind != "sequence" for key in ("beliefs", "appraisals", "inferences")):
        raise C0LawError("cognition judgments require named Sequence views")
    belief = record(view["beliefs"].element, {"proposition", "support", "opposition", "status"})
    rating = record(view["appraisals"].element, {"key", "score"})
    inference = record(
        view["inferences"].element,
        {"proposition", "polarity", "relation", "argument", "conditional"},
    )
    if (
        inference["proposition"].type_id != table[proposition].type_id
        or inference["polarity"].kind != "enum"
        or set(inference["polarity"].choices) != {"support", "opposition"}
        or inference["conditional"].kind != "bool"
        or any(inference[k].kind != "text" for k in ("relation", "argument"))
        or inference["argument"].minimum > 64
        or inference["argument"].maximum is not None
        and inference["argument"].maximum < 64
    ):
        raise C0LawError("cognition inferences require typed conditional literal identities")
    if belief["proposition"].type_id != table[proposition].type_id:
        raise C0LawError("cognition belief has the wrong proposition type")
    if rating["key"].type_id != table[appraisal].type_id:
        raise C0LawError("cognition appraisal has the wrong key type")
    if belief["status"].kind != "enum" or set(belief["status"].choices) != {
        "unknown",
        "supported",
        "opposed",
        "conflict",
    }:
        raise C0LawError("cognition belief status requires the four declared attitudes")
    for key in ("support", "opposition"):
        plan = belief[key]
        if plan.kind != "int" or plan.minimum not in (0, None) or plan.maximum is not None:
            raise C0LawError("aggregated belief strengths need unbounded nonnegative integers")
    if rating["score"].kind != "int" or (
        rating["score"].minimum is not None or rating["score"].maximum is not None
    ):
        raise C0LawError("aggregated appraisal scores need unbounded signed integers")


def compile_cognition(program, declaration, *, context=None):
    from .frontend import row
    from .program import AuthorProgram

    if type(program) is not AuthorProgram:
        raise C0LawError("cognition needs an AuthorProgram")
    row(declaration, {"schema", "models", "bindings"}, path="cognition")
    if declaration["schema"] != "nomos.author.cognition":
        raise C0LawError("cognition requires nomos.author.cognition")
    if type(declaration["models"]) is not dict or type(declaration["bindings"]) is not dict:
        raise C0LawError("cognition models and bindings require named declarations")
    table = program.table
    actors = dict(program.actors)
    symbols = tuple((name, OpeningSymbol(name, sort, "person")) for name, sort in program.actors)
    channels = channel_signatures_from_program(program)
    bindings, scopes = [], []
    for name, selection in declaration["bindings"].items():
        if not _identifier(name):
            raise C0LawError("cognition bindings need valid names")
        row(selection, {"definition"}, {"actor", "kind", "with", "views"}, path="bindings." + name)
        selectors = set(selection) & {"actor", "kind"}
        if not _identifier(name) or len(selectors) != 1:
            raise C0LawError("cognition binding needs one named actor/kind selector")
        selector = next(iter(selectors))
        target = selection[selector]
        if type(target) is not str:
            raise C0LawError("cognition selector needs a declared name")
        if selector == "actor":
            if target not in actors:
                raise C0LawError("cognition selects an unknown opening Actor")
            families = (actors[target],)
        else:
            schemas = dict(program.entities.entities)
            if target not in schemas or schemas[target].kind != "person":
                raise C0LawError("cognition kind must be a Person sort")
            families = tuple(
                sort for sort in program.actor_kinds if table.accepts_sort(target, sort)
            )
        if not families:
            raise C0LawError("cognition has no selected Actor kinds")
        for old_selector, old_target, old_families in scopes:
            if (
                selector == old_selector == "actor"
                and target == old_target
                or selector == old_selector == "kind"
                and set(families) & set(old_families)
                or selector == "actor"
                and old_selector == "kind"
                and actors[target] in old_families
                or selector == "kind"
                and old_selector == "actor"
                and actors[old_target] in families
            ):
                raise C0LawError("cognition models overlap on an Actor")
        scopes.append((selector, target, families))
        definition = selection["definition"]
        if not _identifier(definition):
            raise C0LawError("cognition definition needs a valid name")
        model = declaration["models"].get(definition)
        if type(model) is not dict:
            raise C0LawError("cognition binding names an unknown model")
        path = "models." + definition
        row(
            model,
            {
                "actor",
                "propositions",
                "appraisal_keys",
                "slots",
                "view",
                "prior_view",
                "evidence",
                "rules",
            },
            {"parameters", "budget", "steps", "derive", "inference_limits", "finite", "local"},
            path=path,
        )
        if "finite" in model and "local" in model:
            raise C0LawError("cognition selects one hard analysis backend")
        if type(model["actor"]) is not dict or len(model["actor"]) != 1:
            raise C0LawError("cognition needs one typed holder")
        actor, actor_type = next(iter(model["actor"].items()))
        names = (
            model["propositions"],
            model["appraisal_keys"],
            model["slots"],
            model["view"],
            model["prior_view"],
            actor_type,
        )
        if any(type(v) is not str or v not in dict(table.definitions) for v in names):
            raise C0LawError("cognition uses an undeclared named type")
        if (
            table[actor_type].kind != "ref"
            or not all(table.accepts_sort(table[actor_type].sort, sort) for sort in families)
            or actor == "prior"
            or not _identifier(actor)
        ):
            raise C0LawError("cognition holder has an incompatible Actor reference")
        _view_contract(
            table,
            model["view"],
            model["prior_view"],
            model["propositions"],
            model["appraisal_keys"],
            "finite" in model,
            "local" in model,
        )
        parameters, supplied = model.get("parameters", {}), selection.get("with", {})
        if (
            type(parameters) is not dict
            or type(supplied) is not dict
            or set(parameters) != set(supplied)
        ):
            raise C0LawError("cognition needs exact parameter bindings")
        if {actor, "prior"} & set(parameters):
            raise C0LawError("cognition parameters alias the holder or prior view")
        if any(
            not _identifier(key) or type(kind) is not str or kind not in dict(table.definitions)
            for key, kind in parameters.items()
        ):
            raise C0LawError("cognition parameters need declared named types")
        fixed = tuple(
            ParameterValue(key, kind, value_node(table, table[kind], supplied[key], symbols))
            for key, kind in parameters.items()
        )
        views = compile_local_views(
            model["evidence"],
            selection.get("views", {}),
            table,
            program.queries,
            program.entities,
            {},
            channels,
        )
        if any(view.kind != "reports" for _, view in views):
            raise C0LawError("this revision model consumes acquired evidence channels")
        view_map = dict(views)
        budget = model.get("budget", 128)
        if type(budget) is not int or budget < 1:
            raise C0LawError("cognition needs a positive per-root evidence budget")
        steps = model.get("steps", ExpressionLimits().steps)
        if type(steps) is not int or steps < 1:
            raise C0LawError("cognition needs a positive expression step budget")
        rows = model["rules"]
        if type(rows) is not dict or not rows and not ({"finite", "local"} & set(model)):
            raise C0LawError("cognition needs named revision rules")
        rules = []
        for rule_name, body in rows.items():
            if not _identifier(rule_name):
                raise C0LawError("cognition rules need valid names")
            location = path + ".rules." + rule_name
            row(
                body,
                {"on", "item", "slot", "policy"},
                {"accept", "where", "believe", "appraise"},
                path=location,
            )
            if (
                body["policy"] != "latest"
                or type(body["on"]) is not str
                or body["on"] not in view_map
            ):
                raise C0LawError(
                    "revision needs a named evidence channel and explicit latest policy"
                )
            item = body["item"]
            if not _identifier(item) or item in {actor, "prior", *parameters}:
                raise C0LawError("revision item aliases its environment")
            channel = view_map[body["on"]]
            base = {
                actor: actor_type,
                "prior": model["prior_view"],
                item: table[channel.type_name].element.name,
                **parameters,
            }

            def expression(text, returns):
                result = compile_value_expression(
                    text,
                    table,
                    base,
                    returns=returns,
                    library=program.queries,
                    entities=program.entities,
                    actor=actor,
                    context="actor",
                    path=location,
                    span=None if context is None else context.locate(location),
                    limits=ExpressionLimits(steps=steps),
                )
                if result.summary.owner_reads or result.summary.reference_domains:
                    raise C0LawError("cognition expressions use supplied evidence, not world reads")
                needed = {read.root for read in result.summary.reads}
                return replace(
                    result, inputs=tuple(entry for entry in result.inputs if entry[0] in needed)
                )

            belief, appraisal = body.get("believe"), body.get("appraise")
            if belief is None and appraisal is None:
                raise C0LawError("revision needs a belief or appraisal")
            if belief is not None:
                row(belief, {"proposition", "support", "opposition"}, path=location + ".believe")
            if appraisal is not None:
                row(appraisal, {"key", "score"}, path=location + ".appraise")
            integers = [
                None if belief is None else expression(belief[key], None)
                for key in ("support", "opposition")
            ]
            score = None if appraisal is None else expression(appraisal["score"], None)
            if any(expr is not None and expr.result.kind != "int" for expr in (*integers, score)):
                raise C0LawError("cognition strengths and scores need integer expressions")
            rules.append(
                RevisionRule(
                    rule_name,
                    channel,
                    item,
                    expression(body.get("accept", "True"), "Bool"),
                    expression(body["slot"], model["slots"]),
                    expression(body.get("where", "True"), "Bool"),
                    None
                    if belief is None
                    else expression(belief["proposition"], model["propositions"]),
                    *integers,
                    None
                    if appraisal is None
                    else expression(appraisal["key"], model["appraisal_keys"]),
                    score,
                )
            )
        from .cognition_derivation import compile_derivations

        derivations, inference_limits = compile_derivations(
            program,
            model,
            actor,
            parameters,
            path=path,
            steps=steps,
            context=context,
        )
        from .finite_model import compile_finite, semantic_keys

        finite = (
            None
            if "finite" not in model
            else compile_finite(
                program,
                model["finite"],
                view_map,
                {actor: actor_type, **parameters},
                model["propositions"],
                dict(table[model["view"]].fields)["analysis"].name,
                path=path + ".finite",
                steps=steps,
            )
        )
        from .local_model import compile_local
        from .local_model import semantic_keys as local_keys

        local = (
            None
            if "local" not in model
            else compile_local(
                program,
                model["local"],
                view_map,
                {actor: actor_type, **parameters},
                dict(table[model["view"]].fields)["local"].name,
                path=path + ".local",
                steps=steps,
            )
        )
        digest = hashlib.sha256(
            json.dumps(
                {
                    "program": program.name,
                    "selection": selection,
                    "model": model,
                    "entities": program.entities.fingerprint,
                    "rules": [
                        tuple(
                            None if e is None else e.read_key
                            for e in (
                                r.accept,
                                r.slot,
                                r.where,
                                r.proposition,
                                r.support,
                                r.opposition,
                                r.appraisal,
                                r.score,
                            )
                        )
                        for r in rules
                    ],
                    "derive": [
                        (
                            d.where.read_key,
                            d.conclusion.read_key,
                            tuple(e.read_key for e in d.constants),
                            tuple((n, e.read_key) for n, e in d.each),
                        )
                        for d in derivations
                    ],
                    "finite": semantic_keys(finite),
                    "local": local_keys(local),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        bindings.append(
            CognitionBinding(
                name,
                digest,
                selector,
                target,
                families,
                actor,
                table[actor_type].name,
                fixed,
                tuple(rules),
                table[model["propositions"]].name,
                table[model["appraisal_keys"]].name,
                table[model["slots"]].name,
                table[model["view"]].name,
                budget,
                table[model["prior_view"]].name,
                derivations,
                inference_limits,
                finite,
                local,
            )
        )
    return CognitionPlan(program, tuple(bindings))


def channel_signatures_from_program(program):
    """Use compiled source/slot identities, including opening and actual deliveries."""
    channels = {
        ("reports", plan.name): (
            plan.projection.value.result.name,
            "author." + program.name + ".opening-information",
            plan.name,
        )
        for plan in program.information
    }
    channels.update(
        (("projected", plan.name), (plan.value.result.name, "", "")) for plan in program.projections
    )
    for plan in (
        *program.abilities,
        *program.reactions,
        *(p.event for p in program.periodic),
        *(p.completion for p in program.activities),
        *(p.cancellation for p in program.activities if p.cancellation is not None),
    ):
        for leaf in plan.resolution.leaves():
            for call in leaf.deliveries:
                channel = plan.channel_name if hasattr(plan, "channel_name") else plan.name
                channels["reports", channel + "." + call.label] = (
                    call.definition.value.result.name,
                    plan.source,
                    call.label,
                )
    return channels


def read_cognition(program, path):
    from .assembly import read_author_modules

    document = read_author_modules(path)
    return compile_cognition(program, document.to_data(), context=document.context())


def require_cognition(program, plan):
    if type(plan) is not CognitionPlan or plan.program is not program:
        raise C0BindingError("cognition must bind the exact world Program")
