"""Compiler-owned nominal classes, editable only during backend assembly."""

from dataclasses import _FIELD, Field, _DataclassParams, dataclass
from types import MappingProxyType, new_class


class _FrozenAnnotations(dict):
    """Keep Python's annotation-dict protocol without offering write methods."""

    def _deny(self, *args, **kwargs):
        raise TypeError("compiled nominal annotations are read-only")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _deny


class _SealedNominalType(type):
    def __setattr__(cls, name, value):
        if cls.__dict__.get("_c0_sealed", False):
            raise TypeError("compiled nominal type is read-only; compile a new Program")
        super().__setattr__(name, value)

    def __delattr__(cls, name):
        if cls.__dict__.get("_c0_sealed", False):
            raise TypeError("compiled nominal type is read-only; compile a new Program")
        super().__delattr__(name)


class _FrozenField(Field):
    __slots__ = ()

    def __setattr__(self, name, value):
        raise TypeError("compiled nominal field is read-only")

    def __delattr__(self, name):
        raise TypeError("compiled nominal field is read-only")


class _FrozenParameters(_DataclassParams):
    __slots__ = ()

    def __setattr__(self, name, value):
        raise TypeError("compiled nominal parameters are read-only")

    def __delattr__(self, name):
        raise TypeError("compiled nominal parameters are read-only")


def make_nominal_record(name, declarations, *, namespace):
    def populate(target):
        target.update(namespace)
        target["__module__"] = __name__
        target["__annotations__"] = dict(declarations)

    carrier = new_class(name, (), {"metaclass": _SealedNominalType}, populate)
    return dataclass(carrier, frozen=True, slots=True)


def seal_nominal_record(carrier):
    """Publish detached reflection metadata after all validators are installed.

    Low-level type/object setters and private function mutation are not supported
    author APIs. This is artifact finalization, not a hostile-Python sandbox.
    """
    if type(carrier) is not _SealedNominalType or carrier.__dict__.get("_c0_sealed", False):
        raise TypeError("nominal record is not an open compiler assembly")
    if (
        carrier.__bases__ != (object,)
        or not carrier.__dataclass_params__.frozen
        or any(
            item._field_type is _FIELD and not item.init
            for item in carrier.__dataclass_fields__.values()
        )
    ):
        raise TypeError("nominal assembly is not a complete frozen record")
    fields = {}
    for name, original in carrier.__dataclass_fields__.items():
        frozen = object.__new__(_FrozenField)
        for slot in Field.__slots__:
            value = getattr(original, slot)
            if slot == "metadata":
                value = MappingProxyType(dict(value))
            object.__setattr__(frozen, slot, value)
        fields[name] = frozen
    parameters = object.__new__(_FrozenParameters)
    for slot in _DataclassParams.__slots__:
        object.__setattr__(parameters, slot, getattr(carrier.__dataclass_params__, slot))
    carrier.__annotations__ = _FrozenAnnotations(carrier.__annotations__)
    carrier.__dataclass_fields__ = MappingProxyType(fields)
    carrier.__dataclass_params__ = parameters
    carrier._c0_sealed = True
    return carrier


def is_sealed_nominal_record(carrier):
    return type(carrier) is _SealedNominalType and carrier.__dict__.get("_c0_sealed", False)
