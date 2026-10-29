"""Actor-local input descriptions for generated controls, not admission promises."""

from dataclasses import dataclass

from .errors import AdmissionError, SettlementDefect


@dataclass(frozen=True)
class InputField:
    name: str
    type_name: str
    element_type: str
    kind: str
    dependencies: tuple
    ready: bool
    pool: frozenset | None = None
    minimum: int | None = None
    maximum: int | None = None
    length: int | None = None
    repetition: str = "forbid"


@dataclass(frozen=True)
class ChoiceForm:
    ability: str
    fields: tuple
    values: tuple
    complete: bool
    condition_pending: bool


def choice_form(session, actor, ability, choices, request):
    from .processes import request_binding
    from .scheduling import has_opportunity

    if session._busy or session._fatal:
        raise SettlementDefect("Session cannot construct choices during settlement or after fatal")
    reference = session._actor(actor)
    if not has_opportunity(session, reference):
        raise AdmissionError("NotAdmitted", "Actor has no current opportunity")
    binding = None if request is None else request_binding(session, actor, request)
    definition, reference, record = session._entry(actor, ability, binding)
    return definition.choices(session, reference, {} if choices is None else choices, record)


def available_abilities(session, actor):
    from .information import candidate_input_batch
    from .scheduling import has_opportunity

    if session._busy or session._fatal:
        raise SettlementDefect("Session cannot list choices during settlement or after fatal")
    reference = session._actor(actor)
    if not has_opportunity(session, reference):
        return ()
    with candidate_input_batch(session):
        return _available_abilities(session, actor, reference)


def _available_abilities(session, actor, reference):
    result = []
    for definition in session.program.actions.values():
        if (
            not session.references.accepts(definition.actor_sort, reference.sort)
            or definition.process is not None
            and definition.process.point != "begin"
        ):
            continue
        try:
            _, _, record = session._entry(actor, definition.name, None)
            if definition.eligible(session, reference, record) is False:
                continue
        except AdmissionError as error:
            if error.code in {
                "NotAdmitted",
                "StagePending",
                "ProcessPending",
                "WorldClosed",
                "WorldDraining",
            }:
                continue
            raise
        result.append(definition.name)
    return tuple(result)
