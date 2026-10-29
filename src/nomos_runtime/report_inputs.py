"""Select actor-local receipt inputs and batch only successful format checks."""

from .errors import AdmissionError
from .expressions import ValueBudget
from .input_proofs import InputProofBatch

_REPORT_INPUT_LIMIT = 256


def information_values(session, viewer, channel, source, receipts):
    if source == "author." + session.program.name + ".opening-information":
        selected = session._opening_receipts
    else:
        selected = receipts
    return tuple(
        receipt.value
        for receipt in selected
        if receipt.recipient == viewer and receipt.channel == channel and receipt.source == source
    )


def process_information_values(viewer, channel, source, receipts, record, point):
    if record is None:
        raise AdmissionError("WrongRequest", "scoped report requires a pending process")
    origins = dict(record.origins).get(point, ())
    return tuple(
        receipt.value
        for receipt in receipts
        if receipt.recipient == viewer
        and receipt.channel == channel
        and receipt.source == source
        and receipt.occurrence in origins
    )


def _bind(session, validator, viewer, channel, source, receipts):
    return validator(
        information_values(session, viewer, channel, source, receipts),
        ValueBudget(session.limits.value, session.references),
        (),
    )


class ReportInputBatch:
    def __init__(self):
        self.input_proofs = InputProofBatch()
        self.roots = None
        self.schemas = None
        self.values = {}

    def read(self, session, validator, viewer, channel, source, before, receipts, record):
        references = session.references
        roots = (
            session.program,
            session.program.name,
            session.program.validators,
            session.program.schemas,
            before,
            session._states,
            session._contexts,
            session._opening_receipts,
            receipts,
            references,
            references.schemas,
            references.symbols,
            references.references,
            references.allowed,
            session.limits,
            session.limits.value,
        )
        schemas = tuple(references.schemas.items())
        if (
            self.roots is None
            or any(current is not prior for current, prior in zip(roots, self.roots, strict=True))
            or schemas != self.schemas
        ):
            self.values.clear()
            self.roots, self.schemas = roots, schemas
        key = validator, viewer, channel, source, id(record)
        if key in self.values:
            return self.values[key][1]
        value = _bind(session, validator, viewer, channel, source, receipts)
        if len(self.values) < _REPORT_INPUT_LIMIT:
            self.values[key] = record, value
        return value


def checked_reports(session, validator, viewer, channel, source, before, receipts, record):
    batch = session._report_input_batch
    if batch is None:
        return _bind(session, validator, viewer, channel, source, receipts)
    return batch.read(session, validator, viewer, channel, source, before, receipts, record)
