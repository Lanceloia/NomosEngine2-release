"""Read-only decision histories whose raw recall lives in the Subject's exact archive."""

from collections.abc import Sequence
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class AuditCapture:
    store: object
    decision: object
    report: object
    evaluations: tuple

    def record(self, value):
        return StoredSubjectDecision(
            self.store,
            DecisionRecord(
                self.decision,
                self.report,
                self.evaluations,
                replace(value, decision=None, planning=None),
            ),
        )


@dataclass(frozen=True)
class DecisionRecord:
    """Portable audit values; archive addresses do not grant world control."""

    decision: object
    report: object
    evaluations: tuple
    metadata: object

    def __post_init__(self):
        from nomos_cognition.storage.audit import DecisionEvidence

        from .decisions import PublishedChoice
        from .participation import SubjectDecision
        from .planning_appraisal import ActionEvaluation
        from .subject_planning import SubjectPlanningReport

        if (
            type(self.decision) is not DecisionEvidence
            or type(self.metadata) is not SubjectDecision
            or self.metadata.decision is not None
            or self.metadata.planning is not None
            or type(self.metadata.trial) is not PublishedChoice
            or type(self.evaluations) is not tuple
            or any(
                type(pair) is not tuple
                or len(pair) != 2
                or type(pair[0]) is not ActionEvaluation
                or pair[0].decision is not None
                or type(pair[1]) is not DecisionEvidence
                for pair in self.evaluations
            )
            or (
                self.report is not None
                and (type(self.report) is not SubjectPlanningReport or self.report.evaluations)
            )
            or (self.report is None and self.evaluations)
        ):
            raise ValueError("decision record needs detached complete audit metadata")

    def read(self, archive):
        from nomos_cognition.storage.audit import read_receipt

        with archive.read() as view:
            receipt = read_receipt(view, self.decision.receipt)
            candidate = next(
                (c for c in self.decision.candidates if c.key == self.metadata.selection), None
            )
            if (
                receipt.query.subject != archive.subject
                or receipt.query.context != self.metadata.context
                or receipt.version != self.metadata.memory_version
                or self.metadata.trial.profile != self.decision.model.domain
                or candidate is None
                or self.metadata.trial.semantics != candidate
            ):
                raise ValueError("decision metadata disagrees with its original evaluation")
            frames = {}
            decision = self.decision.read(view, frames)
            report = self.report
            if report is not None:
                if (
                    report.subject != archive.subject
                    or report.context != self.metadata.context
                    or report.memory_version != self.metadata.memory_version
                ):
                    raise ValueError("planning audit disagrees with its original Subject context")
                for value, evidence in self.evaluations:
                    evaluation_receipt = read_receipt(view, evidence.receipt)
                    if (
                        evaluation_receipt != receipt
                        or evidence.model != self.decision.model
                        or evidence.candidates != (value.candidate,)
                    ):
                        raise ValueError("planning evaluation disagrees with its original input")
                report = replace(
                    report,
                    evaluations=tuple(
                        replace(value, decision=evidence.read(view, frames))
                        for value, evidence in self.evaluations
                    ),
                )
        return replace(self.metadata, decision=decision, planning=report)


@dataclass(frozen=True)
class StoredSubjectDecision:
    store: object
    value: DecisionRecord

    def read(self):
        return self.value.read(self.store.archive)


def capture_audit(store, decision, report=None):
    evaluations = () if report is None else report.evaluations
    saved = store.capture((decision, *(value.decision for value in evaluations)))
    return AuditCapture(
        store,
        saved[0],
        None if report is None else replace(report, evaluations=()),
        tuple(
            (replace(value, decision=None), evidence)
            for value, evidence in zip(evaluations, saved[1:], strict=True)
        ),
    )


@dataclass(frozen=True, eq=False)
class DecisionHistory(Sequence):
    entries: Sequence

    def __len__(self):
        return len(self.entries)

    def __getitem__(self, index):
        if type(index) is slice:
            return DecisionHistory(self.entries[index])
        return self.entries[index].read()

    def __eq__(self, other):
        if type(other) is DecisionHistory:
            return self.entries is other.entries or (
                len(self.entries) == len(other.entries)
                and all(a == b for a, b in zip(self.entries, other.entries, strict=True))
            )
        return isinstance(other, Sequence) and tuple(self) == tuple(other)
