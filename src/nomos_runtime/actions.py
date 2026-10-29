"""Compiled rule contracts and Session-issued Action values."""

from dataclasses import dataclass

from .controllers import ActorControl
from .records import ActionEpoch


@dataclass(frozen=True)
class ActionAdmission:
    participants: dict
    epoch: ActionEpoch | None


@dataclass(frozen=True)
class ActionResult:
    status: str
    feedback: object = None
    reports: tuple = ()
    code: str | None = None


@dataclass(frozen=True, eq=False)
class PreparedAction:
    actor: str | ActorControl
    ability: str


@dataclass(frozen=True)
class ActionDefinition:
    name: str
    source: str
    actor_sort: str
    admit: object
    execute: object
    process: object
    local_views: object
    time_cost: object
    choices: object
    eligible: object
    actor_parameter: str
    result_type: str
    local_types: tuple


@dataclass(frozen=True)
class ReactionDefinition:
    name: str
    source: str
    triggers: tuple
    execute: object


@dataclass(frozen=True)
class Delivery:
    channel: str
    sample: str
    project: object
    arguments: tuple
    type_name: str
