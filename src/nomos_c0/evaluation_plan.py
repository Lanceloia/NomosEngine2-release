"""Plan pure candidate computations before choosing their Python implementation."""

from dataclasses import dataclass, field

from .author_abilities.expressions import CheckedValueExpression
from .author_contract_v1 import C0LawError


@dataclass(frozen=True)
class EvaluationDependencies:
    inputs: tuple
    candidate_inputs: tuple
    views: tuple
    owner_reads: tuple
    reference_domains: tuple
    queries: tuple
    mode: str

    def computation_key(self):
        # Call-site paths locate diagnostics; the checked reads define the computation.
        return (
            self.inputs,
            self.candidate_inputs,
            self.views,
            self.owner_reads,
            self.reference_domains,
            tuple((query.definition, query.offset, query.arguments) for query in self.queries),
            self.mode,
        )


@dataclass(frozen=True)
class EvaluationNode:
    ordinal: int
    type_name: str
    lifetime: str
    dependencies: EvaluationDependencies
    sites: tuple


@dataclass(frozen=True)
class EvaluationSite:
    key: tuple
    node: int
    expression: CheckedValueExpression = field(repr=False)


@dataclass(frozen=True)
class CandidateEvaluationPlan:
    ability: str
    nodes: tuple[EvaluationNode, ...]
    sites: tuple[EvaluationSite, ...]

    def site(self, key):
        return next(site for site in self.sites if site.key == key)

    def manifest(self):
        return self.ability, tuple(
            (
                node.ordinal,
                node.lifetime,
                node.type_name,
                tuple((name, spec.type_name) for name, spec in node.dependencies.inputs),
                node.dependencies.candidate_inputs,
                tuple((name, view.kind, view.channel) for name, view in node.dependencies.views),
                tuple(
                    site.expression.source.path for site in self.sites if site.node == node.ordinal
                ),
            )
            for node in self.nodes
        )


def _views(node):
    names = (node.operand,) if node.operation == "local_view" else ()
    return tuple(
        dict.fromkeys((*names, *(name for child in node.children for name in _views(child))))
    )


def plan_candidate_evaluation(action, strategy, rule):
    """Intern equivalent pure roots, preserving every diagnostic and lazy use site."""
    if rule.meaning is None:
        raise C0LawError("candidate evaluation planning requires checked semantic meanings")
    candidate_inputs = {item.name for item in action.inputs.inputs}
    views = dict((*action.views, *strategy.views, *rule.views))
    expressions = []
    meaning = rule.meaning
    if rule.screen is not None:
        expressions.append((("screen",), rule.screen))
    if rule.diversify is not None:
        expressions.append((("diversify",), rule.diversify))
    for category, items in (
        ("feature", meaning.features),
        ("prior", meaning.prior),
        ("known", meaning.known),
        ("valuation", meaning.valuation),
    ):
        expressions.extend(((category, label), expression) for label, expression in items)
    if meaning.target is not None:
        expressions.append((("target",), meaning.target))
    for category, items in (("correlation", meaning.correlation), ("capture", meaning.capture)):
        expressions.extend(((category, label), expression) for label, _, expression in items)
    for index, explanation in enumerate(rule.explanations):
        expressions.extend(
            (("explanation", index, role), expression)
            for role, expression in (("when", explanation.when), ("value", explanation.value))
        )
    groups, sites = {}, []
    for key, expression in expressions:
        if type(expression) is not CheckedValueExpression or not expression.read_key:
            raise C0LawError("evaluation planning requires typed expressions with semantic keys")
        if expression.summary.context != "actor":
            raise C0LawError("candidate evaluation must retain the Actor-local read boundary")
        dependencies = EvaluationDependencies(
            expression.inputs,
            tuple(name for name, _ in expression.inputs if name in candidate_inputs),
            tuple((name, views[name]) for name in _views(expression.node)),
            expression.summary.owner_reads,
            expression.summary.reference_domains,
            expression.summary.dependencies,
            expression.summary.context,
        )
        identity = (
            expression.read_key,
            expression.result.type_id,
            expression.limits,
            dependencies.computation_key(),
        )
        if identity not in groups:
            groups[identity] = len(groups), dependencies, []
        ordinal, _, keys = groups[identity]
        keys.append(key)
        sites.append(EvaluationSite(key, ordinal, expression))
    nodes = tuple(
        EvaluationNode(
            ordinal,
            next(site.expression.result.name for site in sites if site.node == ordinal),
            "candidate" if dependencies.candidate_inputs else "batch",
            dependencies,
            tuple(keys),
        )
        for ordinal, dependencies, keys in groups.values()
    )
    return CandidateEvaluationPlan(action.name, nodes, tuple(sites))
