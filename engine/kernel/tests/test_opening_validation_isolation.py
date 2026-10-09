"""Opening validators cannot modify inputs or retain authoritative state."""

from __future__ import annotations

import pytest
import test_dynamic_actor_v1 as actors
import test_dynamic_individual_owner_v1 as objects
from nomos_kernel import K0ProfileError
from nomos_kernel._atomic_inmemory_session import _K0InMemorySession
from nomos_kernel._dynamic_actor_abi import _K0OpeningActor
from nomos_kernel._dynamic_owner_abi import _K0OpeningIndividual
from nomos_kernel._state_image_abi import _K0OwnerState


def _start(kind, value):
    if kind == "static":
        profile = objects._session(opening=False)._profile
        return _K0InMemorySession.create(profile, (_K0OwnerState(objects.SCENE, value),))
    if kind == "actor":
        return actors._session(opening=(_K0OpeningActor("spark", value, 10),))
    profile = objects._session(opening=False)._profile
    return _K0InMemorySession.create(
        profile,
        (_K0OwnerState(objects.SCENE, objects._State(0)),),
        opening_individuals=(_K0OpeningIndividual("object", value),),
    )


def _view(kind, session):
    if kind == "static":
        return session.read_owner(objects.SCENE).view
    if kind == "actor":
        return session.read_actor(session.actors()[0].actor).view
    return session.read_individual(session.individuals()[0].individual).view


@pytest.mark.parametrize("kind", ["static", "object", "actor"])
@pytest.mark.parametrize("behavior", ["retain", "mutate", "mutate_then_reject"])
def test_dynamic_opening_validation_is_disposable_and_nonmutating(monkeypatch, kind, behavior):
    sample = actors if kind == "actor" else objects
    retained = []

    def validate(owner, state):
        if kind != "static" and owner.key == (
            actors.WORLD if kind == "actor" else objects.SCENE
        ):
            return
        retained.append(state)
        if behavior != "retain":
            object.__setattr__(state, "value", 9)
        if behavior == "mutate_then_reject":
            raise K0ProfileError("opening rejected by validator")

    monkeypatch.setattr(sample._Owner, "validate_opening_state", validate, raising=False)
    value = sample._State(1)
    if behavior == "retain":
        session = _start(kind, value)
        assert retained and all(state is not value for state in retained)
        object.__setattr__(retained[-1], "value", 9)
        assert _view(kind, session).value == 1
    else:
        with pytest.raises(K0ProfileError, match="changed|rejected"):
            _start(kind, value)
    assert value.value == 1
