"""Scoped author compilation and generated-artifact loading with content-keyed reuse."""

import hashlib
import json
from contextlib import ExitStack
from pathlib import Path

from nomos_c0.author_abilities.assembly import read_author_modules
from nomos_c0.author_abilities.frontend import compile_author_world
from nomos_runtime.artifacts import load_world
from nomos_runtime.expressions import ValueBindingError, ValueBudget, ValueLimits
from nomos_runtime.values import check_wire

from .world import emit_world_module


class AuthorPrograms:
    """Keep generated nominal carriers loaded while their local consumers are alive."""

    def __init__(self):
        self._stack, self._programs, self._closed = ExitStack(), {}, False
        self._sources = {}

    def __enter__(self):
        if self._closed:
            raise ValueError("author program loader is closed")
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self._programs.clear()
        self._sources.clear()
        self._stack.close()
        self._closed = True

    def _compile(self, library, selected, *, source_context=None):
        return compile_author_world(
            library.to_data(), selected, context=library.context(), source_context=source_context
        )

    def _read(self, path):
        entry = Path(path).resolve()
        cached = self._sources.get(entry)
        if cached is not None:
            # Match current content and the resolved import preorder, including symlinks.
            pending = [entry]
            try:
                for index, part in enumerate(cached.parts):
                    if not pending:
                        break
                    current = pending.pop()
                    # The entry was resolved at the start of this read. Imported
                    # paths still need fresh resolution to detect retargeted links.
                    if index:
                        current = current.resolve()
                    if current != Path(part.file):
                        break
                    text = Path(part.file).read_text(encoding="utf-8")
                    if hashlib.sha256(text.encode("utf-8")).hexdigest() != part.digest:
                        break
                    pending.extend(
                        Path(part.file).parent / item
                        for item in reversed(part.data.get("imports", ()))
                    )
                else:
                    if not pending:
                        return cached
            except (OSError, ValueError):
                # Reassembly retains the normal missing-file and invalid-text diagnostics.
                pass
        assembled = read_author_modules(entry)
        self._sources[entry] = assembled
        return assembled

    def load(self, lib, source, *, build_dir, context_parameters=None):
        if self._closed:
            raise ValueError("author program loader is closed")
        library, selection = self._read(lib), self._read(source)
        selected = selection.to_data()
        if context_parameters is not None:
            if type(context_parameters) is not dict:
                raise ValueError("context parameters require named selected contexts")
            for name, values in context_parameters.items():
                context = selected.get("contexts", {}).get(name)
                if (
                    context is None
                    or type(values) is not dict
                    or set(values) - context.get("with", {}).keys()
                ):
                    raise ValueError("only declared fixed context parameters may be overridden")
                for field, value in values.items():
                    try:
                        check_wire(field, value, ValueBudget(ValueLimits()))
                    except ValueBindingError as error:
                        raise ValueError(f"context_parameters.{name}.{field}: {error}") from error
                context["with"].update(values)
        identities = [(p.file, p.digest) for p in (*library.parts, *selection.parts)]
        key = hashlib.sha256(
            json.dumps([identities, selected], sort_keys=True).encode()
        ).hexdigest()
        if key not in self._programs:
            checked = self._compile(library, selected, source_context=selection.context())
            code = emit_world_module(checked).encode()
            directory = Path(build_dir)
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / ("world-" + hashlib.sha256(code).hexdigest() + ".py")
            try:
                with path.open("xb") as stream:
                    stream.write(code)
            except FileExistsError:
                if path.read_bytes() != code:
                    raise ValueError("generated artifact path contains different bytes") from None
            module = self._stack.enter_context(load_world(path))
            self._programs[key] = module.PROGRAM
        return self._programs[key]
