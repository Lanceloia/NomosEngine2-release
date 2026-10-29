"""Selected replayable sampling: ordinary owner state and sourced Rule products."""

from dataclasses import dataclass, replace

from nomos_c0.author_contract_v1 import C0LawError

from .expression_syntax import _identifier

MAX_SIDES = 1000
MAX_STREAMS = 4096


@dataclass(frozen=True)
class RandomPlan:
    mechanism: str = "replayable_seed"
    streams: tuple[str, ...] = ("main",)


def slot_streams(slot, plan):
    if slot.stream is None:
        return ("main",)
    node = slot.stream.node
    if node.value_type.kind == "enum":
        if node.operation == "literal":
            return (node.operand,)
        return node.value_type.choices
    if (
        node.value_type.kind == "text"
        and not slot.stream.summary.owner_reads
        and not slot.stream.summary.reference_domains
        and {read.root for read in slot.stream.summary.reads} <= {p.name for p in plan.parameters}
    ):
        from .activities import local_dependencies
        from .fixed_values import evaluate_fixed

        fixed = local_dependencies(replace(slot.stream, actor=None))
        name = evaluate_fixed(fixed, plan.parameters, ()).value
        if _identifier(name):
            return (name,)
    raise C0LawError(
        f"{slot.stream.source.path}: random stream needs a Source-fixed key or finite enum"
    )


def draw_streams(plan):
    return tuple(
        dict.fromkeys(
            name
            for node in plan.resolution.walk()
            for slot in node.draws
            for name in slot_streams(slot, plan)
        )
    )


def compile_random(declaration, plans):
    needs_random = any(draw_streams(plan) for plan in plans)
    if declaration is None:
        if needs_random:
            raise C0LawError("draw requires Source.random with a selected mechanism")
        return None
    if (
        type(declaration) is not dict
        or not {"mechanism"} <= set(declaration) <= {"mechanism", "streams"}
        or declaration["mechanism"] != "replayable_seed"
    ):
        raise C0LawError("Source.random requires the replayable_seed mechanism")
    streams = declaration.get("streams", [])
    if (
        type(streams) is not list
        or len(streams) >= MAX_STREAMS
        or any(not _identifier(name) or name == "main" for name in streams)
        or len(set(streams)) != len(streams)
    ):
        raise C0LawError("Source.random.streams requires bounded unique non-main identifiers")
    selected = RandomPlan(streams=("main", *streams))
    if any(set(draw_streams(plan)) - set(selected.streams) for plan in plans):
        raise C0LawError("draw stream is absent from Source.random.streams")
    return selected
