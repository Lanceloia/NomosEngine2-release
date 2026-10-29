"""Session-issued seat authority, separate from world identities and acquired knowledge."""

from dataclasses import dataclass

from .errors import AdmissionError


@dataclass(frozen=True, eq=False, slots=True)
class ActorControl:
    label: str

    def __str__(self):
        return self.label


def require_writer(session, reference, authority=None):
    owner = session._subject_actors.get(reference)
    if owner is not None and authority is not owner._permit:
        raise AdmissionError("SubjectOwnsActor", "use the Actor's bound participation")
