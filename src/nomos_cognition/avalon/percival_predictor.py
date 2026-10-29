"""Typed overlapping team events computed from one local joint posterior."""

from itertools import combinations

from .inputs import observation
from .percival import PercivalModel
from .predictor import GROUP, RedMerlin


class PercivalTeam:
    ports = {**RedMerlin.ports, "team_size": "int"}
    subject_shape = GROUP
    prediction_kind = "event"

    @staticmethod
    def build(artifact):
        return PercivalModel.from_data(artifact)

    @staticmethod
    def predict(model, values):
        roster, observed = observation(values)
        size = values["team_size"]
        if type(size) is not int or size not in (2, 3):
            raise ValueError("Percival team model selects two- or three-member missions")
        belief = model.predict(observed)
        return tuple(
            (frozenset(roster[i] for i in team), belief.all_good(team))
            for team in combinations(range(5), size)
        )
