"""Explicit catalog of pure learned providers and their value-port contracts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Prediction:
    model: str
    label: str
    subject_type: str
    probabilities: tuple
    basis: int


@dataclass(frozen=True)
class EventPrediction:
    """Separate probabilities of possibly overlapping, typed events."""

    model: str
    label: str
    subject_type: str
    probabilities: tuple
    basis: int


def provider(name):
    if name == "avalon.red_merlin.v1":
        from .avalon.predictor import RedMerlin

        return RedMerlin
    if name == "avalon.percival_team.v1":
        from .avalon.percival_predictor import PercivalTeam

        return PercivalTeam
    raise ValueError("unknown official prediction provider")
