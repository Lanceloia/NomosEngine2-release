"""Check local candidate meanings independently of world effects and ranking."""

import hashlib
import json
from dataclasses import asdict, dataclass, replace

from nomos_c0.author_contract_v1 import C0LawError

from .expression_syntax import _identifier


@dataclass(frozen=True)
class SemanticProfile:
    name: str
    digest: str
    features: tuple
    outcomes: tuple
    feedback: tuple = ()
    applicability: tuple = ()
    appraisal: tuple = ()


@dataclass(frozen=True)
class ActionMeaning:
    features: tuple
    prior: tuple
    known: tuple
    target_type: str | None
    target: object
    correlation: tuple
    capture: tuple
    valuation: tuple
    projections: tuple = ()


@dataclass(frozen=True)
class PartialProjection:
    input: str
    binder: str
    features: tuple
    offsets: tuple = ()


def bind_profile(profile, candidates, parameters, views, abilities, tie, consideration):
    """Include checked pure dependencies and bound inputs, not just profile spelling."""
    plans = {plan.name: plan for plan in abilities}

    def bindings(items, used=None):
        return tuple(
            (p.name, p.type_name, asdict(p.node)) for p in items if used is None or p.name in used
        )

    meanings = []
    for rule in candidates:
        plan = plans[rule.ability]
        meaning = rule.meaning
        expressions = [
            expr
            for _, expr in (*meaning.features, *meaning.prior, *meaning.known, *meaning.valuation)
        ]
        expressions.extend(expr for _, _, expr in (*meaning.correlation, *meaning.capture))
        expressions.extend(
            expr for projection in meaning.projections for _, expr in projection.features
        )
        if meaning.target is not None:
            expressions.append(meaning.target)
        expressions.extend(expr for e in rule.explanations for expr in (e.when, e.value))
        if rule.screen is not None:
            expressions.append(rule.screen)
        if rule.diversify is not None:
            expressions.append(rule.diversify)
        used = {
            read.root
            for expr in (*expressions, *(expr for _, expr in (*rule.supplied, *rule.choices)))
            for read in expr.summary.reads
        }
        local_context = (
            ()
            if plan.context is None
            else tuple(
                p for p in plan.context.parameters if p.name not in plan.context.world_parameters
            )
        )
        meanings.append(
            (
                rule.ability,
                tuple(expr.read_key for expr in expressions),
                tuple((key, expr.read_key) for key, expr in rule.supplied),
                tuple((key, expr.read_key) for key, expr in rule.choices),
                tuple((e.category, e.label, e.type_name) for e in rule.explanations),
                bindings(plan.parameters, used),
                bindings(local_context, used),
            )
        )
    from .feedback import fingerprints

    payload = (
        profile.digest,
        meanings,
        bindings(parameters),
        tuple((key, asdict(view)) for key, view in views),
        fingerprints(profile.feedback),
        tie,
        consideration,
    )
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return replace(profile, digest=digest)


def select_profile(name, profiles, rows):
    from .frontend import row

    if type(profiles) is not dict or type(name) is not str or name not in profiles:
        raise C0LawError("semantics requires a selected named profile")
    path, body = "semantics." + name, profiles[name]
    row(
        body,
        {"features", "outcomes", "meanings"},
        {"feedback", "applicability", "appraisal"},
        path=path,
    )
    for key in ("features", "outcomes"):
        names = body[key]
        if (
            type(names) is not list
            or not 1 <= len(names) <= 64
            or any(not _identifier(item) for item in names)
            or len(set(names)) != len(names)
        ):
            raise C0LawError(path + ": distinct bounded feature/outcome names required")
    applicability = body.get("applicability", {})
    if type(applicability) is not dict or not set(applicability) <= set(body["outcomes"]):
        raise C0LawError(path + ": applicability requires declared outcome axes")
    for names in applicability.values():
        if (
            type(names) is not list
            or not names
            or any(type(n) is not str or n not in body["features"] for n in names)
            or len(set(names)) != len(names)
        ):
            raise C0LawError(path + ": applicability requires distinct declared feature names")
    appraisal = body.get("appraisal", {})
    if type(appraisal) is not dict or len(appraisal) > 32:
        raise C0LawError(path + ": appraisal requires at most 32 named trait declarations")
    trait_names, traits = set(), []
    for trait, directions in appraisal.items():
        row(directions, set(), {"seek", "avoid"}, path=path + ".appraisal." + str(trait))
        seek, avoid = directions.get("seek", []), directions.get("avoid", [])
        if (
            not _identifier(trait)
            or trait in trait_names
            or trait in body["outcomes"]
            or type(seek) is not list
            or type(avoid) is not list
            or not (seek or avoid)
            or any(
                type(name) is not str or name not in body["features"]
                for name in (*seek, *avoid)
            )
            or len(set((*seek, *avoid))) != len((*seek, *avoid))
        ):
            raise C0LawError(
                path + ": appraisal traits require distinct declared seek/avoid features"
            )
        trait_names.add(trait)
        traits.append((trait, tuple(sorted(seek)), tuple(sorted(avoid))))
    selected = [
        item["definition"] + ("" if item.get("point", "begin") == "begin" else "." + item["point"])
        for item in rows
        if type(item) is dict
        and type(item.get("definition")) is str
        and type(item.get("point", "begin")) is str
    ]
    if (
        len(selected) != len(rows)
        or len(set(selected)) != len(selected)
        or type(body["meanings"]) is not dict
        or set(body["meanings"]) != set(selected)
    ):
        raise C0LawError(
            path + ": exactly one meaning for every selected definition/point required"
        )
    digest = hashlib.sha256(
        json.dumps([name, body], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return (
        SemanticProfile(
            name,
            digest,
            tuple(body["features"]),
            tuple(body["outcomes"]),
            applicability=tuple(
                sorted((axis, tuple(sorted(names))) for axis, names in applicability.items())
            ),
            appraisal=tuple(sorted(traits)),
        ),
        body["meanings"],
    )


def compile_meaning(branch, profile, declaration, location, plan):
    from .frontend import row

    row(
        declaration,
        {"features", "prior"},
        {"known", "target", "correlate", "capture", "valuation"},
        path=location,
    )

    def vector(key, names, *, complete=False, returns=None):
        terms = declaration.get(key, {})
        if (
            type(terms) is not dict
            or not set(terms) <= set(names)
            or complete
            and set(terms) != set(names)
            or key == "features"
            and not terms
        ):
            raise C0LawError(location + ": semantic vector disagrees with declared dimensions")
        result = []
        for name, text in terms.items():
            checked = branch.expression(
                text, returns, location + "." + key + "." + name, context="actor"
            )
            if returns is None and checked.result.kind != "int":
                raise C0LawError(location + ": integer semantic vector expressions required")
            result.append((name, checked))
        return tuple(result)

    def nominal(selected, path):
        row(selected, {"type", "value"}, path=path)
        kind = selected["type"]
        if type(kind) is not str or kind not in dict(branch.table.definitions):
            raise C0LawError(location + ": declared nominal target type required")
        return kind, branch.expression(selected["value"], kind, path + ".value", context="actor")

    target_type, target = (
        nominal(declaration["target"], location + ".target")
        if "target" in declaration
        else (None, None)
    )
    correlation = declaration.get("correlate", {})
    captured = declaration.get("capture", {})
    if (
        type(correlation) is not dict
        or len(correlation) > 16
        or any(not _identifier(name) for name in correlation)
    ):
        raise C0LawError(location + ": bounded named correlation terms required")
    if (
        type(captured) is not dict
        or len(captured) > 16
        or set(captured) & set(correlation)
        or any(not _identifier(name) for name in captured)
    ):
        raise C0LawError(location + ": bounded disjoint named capture terms required")
    feature_terms = declaration["features"]
    projection_specs = {}
    normalized_features = {}
    for name, value in feature_terms.items():
        if type(value) is dict:
            from .frontend import row

            row(value, {"sum_by"}, {"offset"}, path=location + ".features." + name)
            spec = value["sum_by"]
            row(spec, {"over", "each", "value"}, path=location + ".features." + name + ".sum_by")
            field, binder = spec["over"], spec["each"]
            offset = value.get("offset", 0)
            source = next((item for item in plan.inputs.inputs if item.name == field), None)
            if (
                source is None
                or source.kind != "subset"
                or type(binder) is not str
                or not _identifier(binder)
                or binder in branch.bindings
                or type(offset) is not int
                or offset < 0
            ):
                raise C0LawError(
                    location + ": sum_by experience feature needs a subset input and binder"
                )
            element = branch.table[source.type_name].element
            from .effects import EffectCompiler

            member_branch = EffectCompiler(
                branch.table,
                {**branch.bindings, binder: element.name},
                library=branch.library,
                entities=branch.entities,
                actor=branch.actor,
                context=branch.context,
                local_views=branch.local_views,
            )
            contribution = member_branch.expression(
                spec["value"], None, location + ".features." + name + ".sum_by.value",
                context="actor",
            )
            from nomos_c0.integer_ranges import IntegerRanges

            interval = IntegerRanges().range(contribution.node)
            if interval is None or interval.minimum is None or interval.minimum < 0:
                raise C0LawError(
                    location + ": partial feature contribution must be provably nonnegative"
                )
            roots = {read.root for read in contribution.summary.reads}
            input_names = {item.name for item in plan.inputs.inputs}
            if roots & (input_names - {field}):
                raise C0LawError(
                    location + ": partial contribution cannot read another candidate input"
                )
            projection_specs.setdefault((field, binder), []).append(
                (name, offset, contribution)
            )
            expression = f"sum_by({field}, {binder} => {spec['value']})"
            normalized_features[name] = (
                expression if offset == 0 else f"{offset} + {expression}"
            )
        else:
            normalized_features[name] = value

    if projection_specs:
        projected = {
            name
            for features in projection_specs.values()
            for name, _, _ in features
        }
        if len(projection_specs) != 1 or projected != set(profile.features):
            raise C0LawError(
                location
                + ": partial patterns require one subset and a complete projected feature vector"
            )
    declaration_for_vector = dict(declaration)
    declaration_for_vector["features"] = normalized_features
    original_declaration = declaration
    declaration = declaration_for_vector
    feature_vector = vector("features", profile.features)
    declaration = original_declaration
    return ActionMeaning(
        feature_vector,
        vector("prior", profile.outcomes, complete=True),
        vector("known", profile.outcomes, returns="Bool"),
        target_type,
        target,
        tuple(
            (name, *nominal(value, location + ".correlate." + name))
            for name, value in correlation.items()
        ),
        tuple(
            (name, *nominal(value, location + ".capture." + name))
            for name, value in captured.items()
        ),
        vector("valuation", profile.outcomes),
        tuple(
            PartialProjection(
                field,
                binder,
                tuple((name, expression) for name, _, expression in features),
                tuple((name, offset) for name, offset, _ in features),
            )
            for (field, binder), features in sorted(projection_specs.items())
        ),
    )
