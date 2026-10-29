"""Immutable acquired guarantees, read only from a controller's actual receipt journal."""

from dataclasses import dataclass

from .errors import AdmissionError


class InformationViolation(Exception):
    def __init__(self, code, definition):
        self.code, self.definition = code, definition
        super().__init__(f"{code}: {definition}")


@dataclass(frozen=True)
class CheckedFact:
    fact: str
    signature: str
    arguments: tuple


@dataclass(frozen=True)
class CheckedConstraint:
    definition: str
    signature: str
    variables: tuple
    formula: str
    arguments: tuple


def acquired_receipts(session, actor, channel):
    controller = session._actor(actor)
    if type(channel) is not str:
        raise AdmissionError("UnknownInformation", "report channel is not selected")
    if channel in session.program.information:
        selected = session._opening_receipts
    elif channel in session.program.channels:
        selected = session._receipts
    else:
        raise AdmissionError("UnknownInformation", "report channel is not selected")
    return tuple(r for r in selected if r.channel == channel and r.recipient == controller)


def sample(receipt):
    return {
        "source": receipt.source,
        "slot": receipt.channel.split(".")[-1],
        "occurrence": receipt.occurrence,
        "sample": receipt.sample,
    }


def public_arguments(arguments):
    return {name: value for name, _, _, value in arguments}


def checked_facts(session, actor, channel):
    receipts = acquired_receipts(session, actor, channel)
    return {
        "acquired": bool(receipts),
        "claims": [
            {
                "fact": claim.fact,
                "signature": claim.signature,
                "arguments": public_arguments(claim.arguments),
                **sample(receipt),
            }
            for receipt in receipts
            for claim in receipt.guarantees
        ],
    }


def checked_constraints(session, actor, channel):
    receipts = acquired_receipts(session, actor, channel)
    return {
        "acquired": bool(receipts),
        "constraints": [
            {
                "constraint": instance.definition,
                "signature": instance.signature,
                "variables": {name: kind for name, kind, _ in instance.variables},
                "holds": instance.formula,
                "arguments": public_arguments(instance.arguments),
                **sample(receipt),
            }
            for receipt in receipts
            for instance in receipt.constraints
        ],
    }
