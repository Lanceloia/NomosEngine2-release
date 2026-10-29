"""Pure red-side Merlin provider; input is values, never a world or Session."""

from .inputs import observation
from .model import Model
from .observations import ROLES

PERSON = "person"
GROUP = ("set", PERSON)
ROLE = ("enum", ROLES)


class RedMerlin:
    subject_shape = PERSON
    prediction_kind = "categorical"
    ports = {
        "observer": PERSON,
        "population": ("sequence", {"roster": GROUP, "cast": ("sequence", ROLE)}),
        "identity": ("sequence", {"subject": PERSON, "role": ROLE}),
        "peers": ("sequence", GROUP),
        "suspects": ("sequence", GROUP),
        "pairs": ("sequence", {"subjects": GROUP, "labels": ("sequence", ROLE)}),
        "approvals": (
            "sequence",
            {
                "epoch": "int",
                "leader": PERSON,
                "team": GROUP,
                "approve": GROUP,
            },
        ),
        "epoch": "int",
        "leader": PERSON,
        "team": GROUP,
        "quests": ("sequence", {"epoch": "int", "team": GROUP, "fails": "int"}),
        "claims": ("sequence", {"speaker": PERSON, "role": ROLE}),
        "advice": ("sequence", {"speaker": PERSON, "team": GROUP, "approve": "bool"}),
    }

    @staticmethod
    def build(artifact):
        return Model.from_data(artifact)

    @staticmethod
    def predict(model, values):
        roster, observed = observation(values)
        belief = model.predict(observed)
        return tuple((ref, belief.marginal(index, "merlin")) for index, ref in enumerate(roster))
