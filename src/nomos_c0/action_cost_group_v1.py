"""Expand explicit cost groups without changing cost semantics or read authority."""

from copy import deepcopy

from .author_contract_v1 import C0LawError
from .author_document_v1 import DocumentPath
from .compile_budget_v1 import COMPILE_BUDGET
from .declarative_nominal_v0 import _name, _row

_MAX_COST_GROUPS = 64


def expand_action_cost_groups(
    form_row: dict[str, object],
) -> tuple[dict[str, object], dict[tuple[int, str], DocumentPath]]:
    """Return copied inline costs and grouped origins; Graph checks every expanded cost."""
    if type(form_row) is not dict:
        raise C0LawError("GameForm declaration is malformed")
    if "cost_groups" in form_row:
        raise C0LawError("cost_groups belongs to an action-value control seat")
    origins: dict[tuple[int, str], DocumentPath] = {}
    controlled = form_row.get("seats")
    if type(controlled) is not list:
        return deepcopy(form_row), origins

    # Leave declarations without groups to the existing Graph syntax checks.
    for raw_control in controlled:
        if type(raw_control) is dict and "cost_groups" in raw_control:
            if form_row.get("mode") != "action_value_event_jump":
                raise C0LawError("cost_groups requires action_value_event_jump mode")

    expanded = deepcopy(form_row)
    for control_index, raw_control in enumerate(controlled):
        if type(raw_control) is not dict or "cost_groups" not in raw_control:
            continue
        groups = raw_control["cost_groups"]
        if type(groups) is not list or len(groups) > _MAX_COST_GROUPS:
            raise C0LawError("cost_groups must be a finite list of at most 64 groups")
        if type(raw_control.get("costs")) is not dict:
            raise C0LawError("action-value cost_groups requires an explicit costs mapping")
        # YAML aliases must not leave expanded seats or cost expressions sharing state.
        control = deepcopy(raw_control)
        expanded["seats"][control_index] = control
        costs = {entry: deepcopy(value) for entry, value in raw_control["costs"].items()}
        control["costs"] = costs
        for group_index, raw_group in enumerate(groups):
            group = _row(raw_group, {"entries", "value"}, "action cost group")
            entries = group["entries"]
            if type(entries) is not list or not 1 <= len(entries) <= COMPILE_BUDGET.actions:
                raise C0LawError(
                    "action cost group entries needs "
                    f"1..{COMPILE_BUDGET.actions} explicit Action names"
                )
            names = tuple(_name(entry, "action cost group entry") for entry in entries)
            if len(set(names)) != len(names):
                raise C0LawError("action cost group entries contains duplicate names")
            for entry in names:
                if entry in costs:
                    raise C0LawError(f"action cost group collides with an existing cost: {entry}")
                costs[entry] = deepcopy(group["value"])
                origins[control_index, entry] = (
                    "game_form", "seats", control_index, "cost_groups", group_index, "value"
                )
        del control["cost_groups"]
    return expanded, origins
