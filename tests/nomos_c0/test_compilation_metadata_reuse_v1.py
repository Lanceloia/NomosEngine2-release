"""Type metadata reuse is local to a single port construction, not a global cache."""

from collections import Counter
from dataclasses import dataclass
from types import SimpleNamespace

from test_local_computation_v1 import ports

from nomos_c0 import declarative_graph_ports_v0 as graph_ports
from nomos_c0 import seat_offers_v0 as offers


@dataclass(frozen=True)
class MetadataSample:
    first: int
    second: int


def _track(monkeypatch, module):
    calls = Counter()
    original = module.get_type_hints

    def resolve(carrier):
        calls[carrier] += 1
        return original(carrier)

    monkeypatch.setattr(module, "get_type_hints", resolve)
    return calls


def test_public_offer_ports_resolve_each_carrier_once_per_construction(monkeypatch):
    action = SimpleNamespace(
        value_ports=ports(),
        scene_owner=SimpleNamespace(view_type=MetadataSample),
        actor_owner=SimpleNamespace(view_type=MetadataSample),
    )
    paths = ("scene.first", "scene.second", "seat.first")
    calls = _track(monkeypatch, offers)
    first = offers._public_ports(action, paths, "scene", "seat")
    assert calls == {MetadataSample: 1}
    assert first.readable_paths == {"scene.first", "scene.second", "actor.first"}
    assert first.admission_readable_fields == {MetadataSample: {"first", "second"}}
    with monkeypatch.context() as patch:
        patch.setitem(MetadataSample.__annotations__, "second", str)
        second = offers._public_ports(action, paths, "scene", "seat")
        assert second == first
    assert calls == {MetadataSample: 2}


def test_value_ports_resolve_each_carrier_once_but_recheck_next_construction(monkeypatch):
    declaration = {
        "read": ["state.first", "state.second"],
        "fields": {"MetadataSample": ["first", "second"]},
        "write_paths": [],
        "construct": [],
        "collections": {},
        "outputs": {"value": "state.second"},
    }
    checked = SimpleNamespace(records=(("MetadataSample", MetadataSample),))
    checked.attributed_pure_definitions = lambda: ()
    calls = _track(monkeypatch, graph_ports)
    first = graph_ports._value_ports(declaration, checked, endpoint_roots={"state": MetadataSample})
    assert calls == {MetadataSample: 1}
    assert first.outputs == {"value": int}
    with monkeypatch.context() as patch:
        patch.setitem(MetadataSample.__annotations__, "second", str)
        second = graph_ports._value_ports(
            declaration, checked, endpoint_roots={"state": MetadataSample}
        )
        assert second.outputs == {"value": str}
    assert calls == {MetadataSample: 2}
