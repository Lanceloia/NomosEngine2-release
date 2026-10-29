"""Exact decision audit metadata with cold recall locators and read-time reconstruction."""

import json
from contextlib import closing
from dataclasses import dataclass, replace

from nomos_cognition.appraisal import AppraisalFrame, Decision, choose
from nomos_cognition.memory import Context, RecallQuery

from .archive import RevisionView, _unwire, _wire
from .reads import RecallReceipt, receipt_for
from .records import dumps


def _revision_ids(view, kind, references):
    values = tuple(view._revision_id(kind, key, revision) for key, revision in references)
    if any(value is None for value in values):
        raise ValueError("audit cites an unretained revision")
    return values


def _encode(view, receipt):
    query = receipt.query
    body = (
        query.subject,
        (query.context.domain, query.context.episode),
        tuple(sorted((c.domain, c.episode) for c in query.past)),
        tuple(sorted(query.cues)),
        receipt.version,
        tuple(view._source_id(s) for s in receipt.episodes),
        _revision_ids(view, "experience", receipt.experiences),
        tuple(view._source_id(s) for s in receipt.grounds),
        receipt.status,
        receipt.reason,
        receipt.work,
        _revision_ids(view, "sample", receipt.samples),
        receipt.digest,
    )
    return dumps(_wire(body))


def read_receipt(view, identity):
    row = view.db.execute("SELECT body FROM recall_receipts WHERE id=?", (identity,)).fetchone()
    if row is None:
        raise ValueError("missing decision recall receipt")
    body = _unwire(json.loads(row[0]))

    def revisions(kind, identities):
        result = []
        for identity in identities:
            row = view.db.execute(
                "SELECT key,revision FROM revisions WHERE kind=? AND id=?", (kind, identity)
            ).fetchone()
            if row is None:
                raise ValueError("missing exact audit revision")
            result.append(row)
        return tuple(result)

    return RecallReceipt(
        RecallQuery(
            body[0], Context(*body[1]), frozenset(Context(*c) for c in body[2]), frozenset(body[3])
        ),
        body[4],
        tuple(view._source(i) for i in body[5]),
        revisions("experience", body[6]),
        tuple(view._source(i) for i in body[7]),
        body[8],
        body[9],
        body[10],
        revisions("sample", body[11]),
        body[12],
    )


@dataclass(frozen=True)
class DecisionEvidence:
    receipt: int
    model: object
    candidates: tuple
    work: int
    personality: tuple
    goals: tuple
    scores: tuple
    status: str
    choice: str | None

    def read(self, view, frames):
        key = self.receipt, id(self.model)
        if key not in frames:
            recalled = view.explain(read_receipt(view, self.receipt))
            frames[key] = AppraisalFrame(self.model, recalled)
        assessment = frames[key].assess(self.candidates)
        decision = choose(assessment, personality=self.personality, goals=self.goals)
        if (decision.scores, decision.status, decision.choice) != (
            self.scores,
            self.status,
            self.choice,
        ):
            raise ValueError("decision audit differs from the originally published evaluation")
        return replace(decision, assessment=replace(assessment, work=self.work))


def save_decisions(archive, decisions):
    if any(type(d) is not Decision or d.assessment.status != "complete" for d in decisions):
        raise ValueError("only complete decisions can be archived")
    saved, recalls = [], {}
    with closing(archive._connect(create=True)) as db, db:
        view = RevisionView(db, archive.subject)
        for decision in decisions:
            recalled = decision.assessment.recalled
            if recalled.subject != archive.subject:
                raise ValueError("decision belongs to a different subject")
            identity = recalls.get(id(recalled))
            if identity is None:
                receipt = receipt_for(recalled)
                identity = db.execute(
                    "INSERT INTO recall_receipts(body) VALUES(?)", (_encode(view, receipt),)
                ).lastrowid
                recalls[id(recalled)] = identity
            saved.append(
                DecisionEvidence(
                    identity,
                    decision.assessment.model,
                    tuple(e.candidate for e in decision.assessment.estimates),
                    decision.assessment.work,
                    decision.personality,
                    decision.goals,
                    decision.scores,
                    decision.status,
                    decision.choice,
                )
            )
    return tuple(saved)
