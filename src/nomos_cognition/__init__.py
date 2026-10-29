"""Domain-independent immutable judgments and evidence-scoped revision."""

from .state import Evidence, Frame, State, Term, revise

__all__ = ["Evidence", "Frame", "State", "Term", "revise"]
