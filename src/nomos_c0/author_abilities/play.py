"""Checked player-turn and tabletop control mechanisms."""

from collections.abc import Mapping
from dataclasses import dataclass

from nomos_c0.author_contract_v1 import C0LawError

from .literal_values import SymbolLiteral


@dataclass(frozen=True)
class PlayPlan:
    player: str
    mechanism: str = "player_turn"
    others: str = "local_strategy"


@dataclass(frozen=True)
class TabletopPlan:
    seats: tuple[str, ...]
    mechanism: str = "tabletop"
    others: str = "local_strategy"
    joint_decisions: tuple = ()


def compile_play(
    declaration, actors, table, time, contexts, *, formed_sorts=(), projections=(), abilities=()
):
    if declaration is None:
        return None
    if isinstance(declaration, Mapping) and declaration.get("mechanism") == "tabletop":
        if (
            set(declaration) - {"mechanism", "seats", "others", "joint_decisions"}
            or not {"mechanism", "seats", "others"} <= set(declaration)
            or declaration["others"] != "local_strategy"
            or not isinstance(declaration["seats"], Mapping)
            or set(declaration["seats"]) != {"kind"}
        ):
            raise C0LawError("tabletop requires seats.kind and local_strategy")
        kind = declaration["seats"]["kind"]
        sorts = {sort.name: sort for sort in table.sorts}
        if type(kind) is not str or kind not in sorts or sorts[kind].kind != "person":
            raise C0LawError("tabletop seats require a declared Person sort")
        if time is not None or formed_sorts:
            raise C0LawError("tabletop selects a fixed opening table without time scheduling")
        seats = tuple(sorted(a for a, sort in actors.items() if table.accepts_sort(kind, sort)))
        if not seats or set(seats) != set(actors):
            raise C0LawError("tabletop seats must cover every opening Actor")
        from .joint_decisions import compile_joint_decisions

        joint = compile_joint_decisions(
            declaration.get("joint_decisions", {}), seats, actors, table, projections, abilities
        )
        return TabletopPlan(seats, joint_decisions=joint)
    if (
        not isinstance(declaration, Mapping)
        or set(declaration) != {"mechanism", "player", "others"}
        or declaration["mechanism"] != "player_turn"
        or declaration["others"] != "local_strategy"
    ):
        raise C0LawError("Source.play requires player_turn, an opening player and local_strategy")
    if time is None or not time.schedules:
        raise C0LawError("player_turn requires an explicitly selected Actor schedule")
    player = declaration["player"]
    if isinstance(player, Mapping) and set(player) == {"context", "parameter"}:
        selected = next((p for p in contexts if p.name == player["context"]), None)
        parameter = (
            None
            if selected is None
            else next((p for p in selected.parameters if p.name == player["parameter"]), None)
        )
        if (
            selected is None
            or parameter is None
            or parameter.name not in selected.world_parameters
            or type(parameter.node) is not SymbolLiteral
            or table[parameter.type_name].kind != "ref"
        ):
            raise C0LawError("play.player requires a fixed world-only opening Actor reference")
        player = parameter.node.symbol
    if type(player) is not str or player not in actors:
        raise C0LawError("play.player requires an opening Actor or a fixed world role")

    return PlayPlan(player)
