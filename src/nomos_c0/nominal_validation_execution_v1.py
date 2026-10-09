"""Bind ordered field checks without caching validation of current values."""

import ast

from nomos_kernel import K0OccurrenceRef, K0ProfileError
from nomos_kernel._actor_identity import _K0ActorRef
from nomos_kernel._dynamic_owner_abi import _K0IndividualRef

from .variant_types_v1 import validate_variant


def compile_nominal_field_validation(fields, fallback_factory):
    return _compile_nominal_validation(fields, fallback_factory)["execute"]


def compile_nominal_validation_block(carrier, fields, fallback_factory):
    """Fuse the nominal boundary and ordered checks; bind the invariant in assembly."""
    namespace = _compile_nominal_validation(fields, fallback_factory, carrier=carrier)

    def install_invariant(execute):
        namespace["invariant_execute"] = execute

    return namespace["execute"], install_invariant


def _compile_nominal_validation(fields, fallback_factory, *, carrier=None):
    namespace = {"K0ProfileError": K0ProfileError}
    lines = ["def execute(value):"]
    serial = 0

    def bind(value):
        name = f"constant_{len(namespace)}"
        namespace[name] = value
        return name

    def fresh():
        nonlocal serial
        serial += 1
        return f"item_{serial}"

    def write(indent, text):
        lines.append("    " * indent + text)

    def reject(indent, condition, message="declared nominal value is malformed"):
        write(indent, f"if {condition}:")
        write(indent + 1, f"raise K0ProfileError({message!r})")

    def emit(spec, current, indent, depth=0):
        if depth >= 8:
            write(indent, f"{bind(fallback_factory(spec))}({current})")
        elif spec.kind == "optional":
            write(indent, f"if {current} is not None:")
            emit(spec.item, current, indent + 1, depth + 1)
        elif spec.kind == "tuple":
            reject(
                indent,
                f"type({current}) is not tuple or len({current}) > {bind(spec.maximum)}",
                "declared collection is malformed or too large",
            )
            item = fresh()
            write(indent, f"for {item} in {current}:")
            emit(spec.item, item, indent + 1, depth + 1)
            write(indent, f"if {current}:")
            write(indent + 1, f"del {item}")
        elif spec.kind in ("str", "int"):
            carrier = "str" if spec.kind == "str" else "int"
            measured = f"len({current})" if spec.kind == "str" else current
            reject(
                indent,
                f"type({current}) is not {carrier} or not "
                f"{bind(spec.minimum)} <= {measured} <= {bind(spec.maximum)}",
            )
        elif spec.kind == "enum":
            choices = bind(frozenset(spec.choices))
            reject(indent, f"type({current}) is not str or {current} not in {choices}")
        elif spec.kind == "bool":
            reject(indent, f"type({current}) is not bool")
        elif spec.kind in ("ref", "individual_ref", "actor_ref"):
            carrier = bind(
                {
                    "ref": K0OccurrenceRef,
                    "individual_ref": _K0IndividualRef,
                    "actor_ref": _K0ActorRef,
                }[spec.kind]
            )
            reject(indent, f"type({current}) is not {carrier}")
            write(indent, f"{carrier}.__post_init__({current})")
        elif spec.kind in ("record", "variant"):
            reject(indent, f"type({current}) is not {bind(spec.annotation)}")
            # Keep the current callback and its operation-local receipt wrapper.
            write(indent, f"{current}.validate_for_k0()")
        else:
            write(indent, f"{bind(fallback_factory(spec))}({current})")

    if carrier is not None:
        from .composable_value_v1 import C0ValueStateError

        namespace.update(
            carrier=carrier,
            validate_variant=validate_variant,
            invariant_execute=None,
            C0ValueStateError=C0ValueStateError,
        )
        reject(1, "type(value) is not carrier", "generated record has a foreign nominal type")

    for field in fields:
        current = fresh()
        write(1, f"{current} = getattr(value, {field.name!r})")
        emit(field.value, current, 1)
        write(1, f"del {current}")
    if carrier is not None:
        cases = getattr(carrier, "__nomos_cases__", ())
        if type(cases) is tuple and not cases:
            # Skip only the unchanged empty declaration, not current native metadata.
            write(1, f"if getattr(carrier, '__nomos_cases__', ()) is not {bind(cases)}:")
            write(2, "validate_variant(value)")
        else:
            write(1, "validate_variant(value)")
        write(1, "if invariant_execute is not None:")
        write(2, "try:")
        write(3, "if not invariant_execute({'state': value}):")
        write(4, "raise K0ProfileError('declared state invariant is false')")
        write(2, "except C0ValueStateError as error:")
        write(3, "raise K0ProfileError('declared state invariant met malformed state') from error")
    write(1, "return None")
    # Field names are string literals; only compiler-selected templates form code.
    module = ast.parse("\n".join(lines))
    filename = (
        "<c0-nominal-field-validation>" if carrier is None else "<c0-nominal-validation-block>"
    )
    exec(compile(module, filename, "exec"), namespace)
    return namespace
