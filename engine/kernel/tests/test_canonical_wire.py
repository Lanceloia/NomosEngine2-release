import pytest
from nomos_kernel import K0ProfileError
from nomos_kernel._canonical_wire import (
    _canonical_wire,
    _read_wire_record,
    _wire_record,
)


class EqualitySpoof:
    def __eq__(self, other: object) -> bool:
        return True


def test_canonical_wire_accepts_only_closed_primitive_trees() -> None:
    value = (None, True, 3, "text", (("nested",),))
    assert _canonical_wire(value) == value
    assert _canonical_wire(value) is not value
    with pytest.raises(K0ProfileError):
        _canonical_wire(["mutable"])
    with pytest.raises(K0ProfileError):
        _canonical_wire((EqualitySpoof(),))


def test_wire_record_round_trip_is_exact() -> None:
    wire = _wire_record("record", (1, ("nested",)))
    assert wire == ("record", 1, ("nested",))
    assert _read_wire_record(wire, "record", 2) == (1, ("nested",))


@pytest.mark.parametrize(
    ("wire", "tag", "arity"),
    (
        (("other", 1), "record", 1),
        (("record", 1, 2), "record", 1),
        ((EqualitySpoof(), 1), "record", 1),
        (("record", 1), "record", True),
        (("record", 1), "record", -1),
    ),
)
def test_wire_record_rejects_foreign_shape(wire, tag, arity) -> None:
    with pytest.raises(K0ProfileError):
        _read_wire_record(wire, tag, arity)
