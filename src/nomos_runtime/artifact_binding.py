"""Content matching for trusted loaded products, not executable-code authentication."""

import ast
import hashlib
import importlib
import json
import marshal
import re
import sqlite3
import sys
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from fractions import Fraction
from pathlib import Path
from types import BuiltinFunctionType, CodeType, FunctionType
from weakref import WeakKeyDictionary

_LOADED = WeakKeyDictionary()
_ROOTS = ("nomos_runtime", "nomos_cognition")


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _code(value):
    value = value.replace(
        co_filename="<content>",
        co_consts=tuple(_code(c) if type(c) is CodeType else c for c in value.co_consts),
    )
    return value


def _live_code(module):
    result = {}
    seen = set()

    def walk(value, name):
        if id(value) in seen:
            return
        seen.add(id(value))
        if type(value) is FunctionType:
            result[name] = hashlib.sha256(marshal.dumps(_code(value.__code__))).hexdigest()
            if hasattr(value, "__wrapped__"):
                walk(value.__wrapped__, name + ".wrapped")
        elif isinstance(value, type) and value.__module__ == module.__name__:
            for key, member in sorted(vars(value).items()):
                if type(member) in (staticmethod, classmethod):
                    member = member.__func__
                if type(member) is property:
                    for part in ("fget", "fset", "fdel"):
                        walk(getattr(member, part), name + "." + key + "." + part)
                else:
                    walk(member, name + "." + key)

    for name, value in sorted(vars(module).items()):
        if getattr(value, "__module__", None) == module.__name__:
            walk(value, name)
        if not name.startswith("__"):
            try:
                result["constant:" + name] = _digest(_constant(value, module, set()))
            except ValueError:
                pass
    return tuple(sorted(result.items()))


def _constant(value, module, active):
    if value is None or type(value) in (bool, str):
        return value
    if type(value) is int:
        return ["int", format(value, "x")]
    if type(value) is float:
        return ["float", value.hex()]
    if type(value) is re.Pattern:
        return ["pattern", value.pattern, value.flags]
    if type(value) is BuiltinFunctionType:
        return ["native_function", value.__module__, value.__qualname__]
    if isinstance(value, type):
        return [
            "type",
            "<local>" if value.__module__ == module.__name__ else value.__module__,
            value.__qualname__,
        ]
    if id(value) in active:
        raise ValueError("cyclic module state")
    active.add(id(value))
    try:
        if type(value) in (tuple, list, frozenset, set):
            result = [_constant(v, module, active) for v in value]
            if type(value) in (frozenset, set):
                result.sort(key=lambda v: json.dumps(v, sort_keys=True))
            return [type(value).__name__, result]
        if type(value) is dict:
            pairs = [
                (_constant(k, module, active), _constant(v, module, active))
                for k, v in value.items()
            ]
            return ["dict", sorted(pairs, key=lambda p: json.dumps(p[0], sort_keys=True))]
        raise ValueError("not closed module data")
    finally:
        active.remove(id(value))


def _import_roots(source):
    """Collect imports in every statement scope without walking expression interiors."""
    imports = set()
    pending = [ast.parse(source)]
    while pending:
        node = pending.pop()
        if type(node) is ast.Import:
            imports.update(a.name.split(".")[0] for a in node.names)
        elif type(node) is ast.ImportFrom:
            imports.add((node.module or "").split(".")[0])
        elif not isinstance(node, ast.expr):
            # An import statement cannot occur inside an expression. Keep all
            # non-expression containers, including handlers and match cases.
            pending.extend(ast.iter_child_nodes(node))
    return frozenset(imports)


def register(module, source):
    """Called only by load_world, using the very bytes passed to compile/exec."""
    imports = _import_roots(source)
    _LOADED[module] = hashlib.sha256(source).hexdigest(), _live_code(module), imports


def _configuration(module):
    active = set()

    def encode(value):
        if value is None or type(value) in (bool, str):
            return value
        if type(value) is int:
            return ["int", format(value, "x")]
        if type(value) is Fraction:
            return ["fraction", format(value.numerator, "x"), format(value.denominator, "x")]
        if id(value) in active:
            # Program back-pointers are the only selected recursive configuration edge.
            if value is module.PROGRAM:
                return ["program"]
            raise ValueError("unsupported recursive product configuration")
        active.add(id(value))
        try:
            if isinstance(value, type):
                origin = "<world>" if value.__module__ == module.__name__ else value.__module__
                return ["type", origin, value.__qualname__]
            if type(value) is FunctionType:
                origin = sys.modules.get(value.__module__)
                if (
                    origin is None
                    or value.__globals__ is not vars(origin)
                    or not (origin is module or value.__module__.split(".")[0] in _ROOTS)
                ):
                    raise ValueError("unregistered product callback")
                return [
                    "function",
                    "<world>" if origin is module else origin.__name__,
                    hashlib.sha256(marshal.dumps(_code(value.__code__))).hexdigest(),
                    encode(value.__defaults__),
                    encode(value.__kwdefaults__),
                    tuple(encode(c.cell_contents) for c in value.__closure__ or ()),
                ]
            if isinstance(value, Mapping):
                pairs = [(encode(k), encode(v)) for k, v in value.items()]
                return ["mapping", sorted(pairs, key=lambda p: json.dumps(p[0], sort_keys=True))]
            if type(value) in (tuple, list, frozenset):
                items = [encode(v) for v in value]
                if type(value) is frozenset:
                    items.sort(key=lambda v: json.dumps(v, sort_keys=True))
                return [type(value).__name__, items]
            if is_dataclass(value):
                return [
                    encode(type(value)),
                    [(f.name, encode(getattr(value, f.name))) for f in fields(value) if f.init],
                ]
            if value is module.PROGRAM:
                return ["program", encode(vars(value))]
            raise ValueError("unsupported product configuration: " + type(value).__name__)
        finally:
            active.remove(id(value))

    return _digest(encode((module.PROGRAM, module.CONTROLLERS, getattr(module, "PLANNING", None))))


def content_binding(module):
    """Match loaded Python code plus readable dependency bytes in a trusted local process."""
    selected = _LOADED.get(module)
    if selected is None:
        raise ValueError("restart requires a product loaded by load_world")
    source, code, imports = selected
    if imports - {
        *_ROOTS,
        "dataclasses",
        "types",
        "fractions",
        "collections",
        "json",
        "time",
        "functools",
        "bisect",
    }:
        raise ValueError("product imports outside the supported restart dependency set")
    if _live_code(module) != code:
        raise ValueError("loaded product code changed")
    dependencies = []
    for root in _ROOTS:
        package = importlib.import_module(root)
        directory = Path(package.__file__).parent
        for path in sorted(directory.rglob("*.py")):
            relative = path.relative_to(directory)
            if path.name == "__main__.py":
                continue
            parts = list(relative.with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            name = ".".join((root, *parts))
            dependency = importlib.import_module(name)
            if Path(dependency.__file__).resolve() != path.resolve():
                raise ValueError("restart dependency origin changed")
            dependencies.append(
                (name, hashlib.sha256(path.read_bytes()).hexdigest(), _live_code(dependency))
            )
    import pyrsistent

    native = importlib.import_module(type(pyrsistent.pvector()).__module__)
    for path in sorted(Path(pyrsistent.__file__).parent.rglob("*.py")):
        dependencies.append(
            (
                "pyrsistent/" + str(path.relative_to(Path(pyrsistent.__file__).parent)),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    bisect = importlib.import_module("bisect")
    dependencies.append(
        (
            "bisect",
            hashlib.sha256(Path(bisect.__file__).read_bytes()).hexdigest(),
            _live_code(bisect),
        )
    )
    for dependency in (
        native,
        importlib.import_module("_sqlite3"),
        importlib.import_module("_bisect"),
    ):
        if (
            dependency.__name__ in sys.builtin_module_names
            and dependency.__spec__.origin == "built-in"
        ):
            # Statically linked extensions are covered by the interpreter image below.
            dependencies.append((dependency.__name__, "interpreter"))
            continue
        path = Path(dependency.__file__)
        dependencies.append((dependency.__name__, hashlib.sha256(path.read_bytes()).hexdigest()))
    return {
        "format": "nomos.subject.binding.v1",
        "product": source,
        "configuration": _configuration(module),
        "dependencies": _digest(dependencies),
        "python": sys.version,
        "abi": sys.implementation.cache_tag,
        "sqlite": sqlite3.sqlite_version,
        "interpreter": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
    }
