"""Reducible process graphs with explicit back edges and definite forward scopes."""

from collections.abc import Mapping

from nomos_c0.author_contract_v1 import C0LawError

from .expression_syntax import _identifier


def resolution_leaves(row, path):
    if not isinstance(row, Mapping):
        raise C0LawError(f"{path}: resolution must be a mapping")
    if "result" in row:
        return (row,)
    if set(row) == {"draw", "then"}:
        return resolution_leaves(row["then"], path + ".then")
    for keys, branches in (
        ({"when", "then", "else"}, ("then", "else")),
        ({"attempt", "success", "failure"}, ("success", "failure")),
    ):
        if set(row) == keys:
            return tuple(
                leaf for branch in branches for leaf in resolution_leaves(row[branch], path)
            )
    raise C0LawError(f"{path}: incomplete or unsupported process resolution")


def process_graph(declaration, path):
    decisions = declaration["decisions"]
    if (
        not isinstance(decisions, Mapping)
        or not decisions
        or any(not _identifier(name) or name in ("begin", "finish") for name in decisions)
    ):
        raise C0LawError(f"{path}.decisions: unique named decision points required")
    nodes = {"begin": declaration["begin"], **decisions}
    edges, exits = {}, set()
    for point, node in nodes.items():
        if not isinstance(node, Mapping) or "resolve" not in node:
            raise C0LawError(f"{path}.{point}: missing resolution")
        destinations = []
        for leaf in resolution_leaves(node["resolve"], f"{path}.{point}.resolve"):
            following = leaf.get("next")
            if type(following) is not str or following not in {*decisions, "finish"}:
                raise C0LawError(f"{path}.{point}.next: unknown or missing successor")
            if following == "finish":
                exits.add(point)
            else:
                destinations.append(following)
        edges[point] = tuple(dict.fromkeys(destinations))
    reached, pending = set(), ["begin"]
    while pending:
        point = pending.pop()
        if point not in reached:
            reached.add(point)
            pending.extend(edges[point])
    if reached != set(nodes):
        raise C0LawError(f"{path}: unreachable decision point")
    finishing = set(exits)
    while True:
        expanded = finishing | {p for p in nodes if set(edges[p]) & finishing}
        if expanded == finishing:
            break
        finishing = expanded
    if finishing != reached:
        raise C0LawError(
            f"UnsupportedFeature: {path}: process region has no structural finish path"
        )
    parents = {p: tuple(n for n in nodes if p in edges[n]) for p in nodes}
    dominators = {p: ({"begin"} if p == "begin" else set(nodes)) for p in nodes}
    while True:
        after = {
            p: {"begin"}
            if p == "begin"
            else {p} | set.intersection(*(dominators[n] for n in parents[p]))
            for p in nodes
        }
        if after == dominators:
            break
        dominators = after
    forward = {p: tuple(n for n in edges[p] if n not in dominators[p]) for p in nodes}
    from collections import deque

    degrees = {p: sum(p in forward[n] for n in nodes) for p in nodes}
    ready, ordered = deque(p for p in nodes if degrees[p] == 0), []
    while ready:
        point = ready.popleft()
        ordered.append(point)
        for following in forward[point]:
            degrees[following] -= 1
            if degrees[following] == 0:
                ready.append(following)
    if len(ordered) != len(nodes):
        raise C0LawError(f"UnsupportedFeature: {path}: irreducible process cycle")
    order = tuple(ordered)
    forward_parents = {p: tuple(n for n in order if p in forward[n]) for p in order}
    strict = {p: frozenset(dominators[p] - {p}) for p in nodes}
    resets = {p: tuple(n for n in nodes if p in dominators[n]) for p in nodes}
    return nodes, order, forward_parents, strict, resets
