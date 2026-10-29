"""Checked author plans consumed by code generation, never a running Session."""

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class AbilityPlan:
    name: str
    definition: str
    actor: str
    actor_type: str
    parameters: tuple
    inputs: object
    where: object
    costs: tuple
    resolution: object
    summary: object
    source: str
    views: tuple = ()
    process: object | None = None
    context: object | None = None
    epoch: object | None = None
    time_cost: object | None = None

    @property
    def channel_name(self):
        return self.name if self.process is None else f"{self.process.process}.{self.process.point}"

    @property
    def occurrence_parameters(self):
        from .context_state import context_types

        lexical = set() if self.context is None else set(context_types(self.context))
        return (
            *((name, kind) for name, kind in self.inputs.base if name not in lexical),
            *((item.name, item.type_name) for item in self.inputs.inputs),
        )


@dataclass(frozen=True)
class AuthorProgram:
    name: str
    table: object
    entities: object
    actors: tuple
    objects: tuple
    abilities: tuple[AbilityPlan, ...]
    contexts: tuple = ()
    projections: tuple = ()
    information: tuple = ()
    processes: tuple = ()
    terminal: object | None = None
    reactions: tuple = ()
    settlements: tuple = ()
    activities: tuple = ()
    time: object | None = None
    periodic: tuple = ()
    random: object | None = None
    actor_kinds: tuple = ()
    play: object | None = None
    queries: object | None = None
    opening: tuple = ()
    report_collections: tuple = ()
    execution_io: object = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        from .execution_io import compile_execution_io

        io = compile_execution_io(self)
        object.__setattr__(self, "abilities", context_input_plans(self, io))
        object.__setattr__(self, "execution_io", io)


def context_input_plans(program, io):
    """Bind only used lexical state fields into each checked Action's base inputs."""
    from .context_state import context_types

    result = []
    for plan in program.abilities:
        if plan.context is None or plan.context.state is None:
            result.append(plan)
            continue
        fields = set(dict(plan.context.state.fields))
        used = {u.read.root for u in io.rule(plan.name).values if u.context == plan.context.name}
        base = dict(plan.inputs.base) | context_types(plan.context, local=True)
        result.append(
            replace(
                plan,
                inputs=replace(
                    plan.inputs,
                    base=tuple(
                        sorted(
                            (name, kind)
                            for name, kind in base.items()
                            if name not in fields or name in used
                        )
                    ),
                ),
            )
        )
    return tuple(result)
