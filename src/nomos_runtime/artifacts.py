"""Load a trusted generated Python module without invoking an author compiler."""

import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .artifact_format import require_artifact_abi
from .candidates import ControllerLibrary
from .presentation import CompiledDisplay
from .world import CompiledProgram


class ArtifactError(ValueError):
    pass


@contextmanager
def load_world(path):
    """Keep nominal carriers importable for the lifetime of this local consumer."""
    path = Path(path)
    if path.suffix != ".py" or not path.is_file():
        raise ValueError("world artifact must be an existing generated .py file")
    name = "_nomos_world_" + uuid4().hex
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        # Generated products are selected by their actual bytes, not mtime-based pyc caches.
        try:
            source = path.read_bytes()
            require_artifact_abi(source)
            exec(compile(source, str(path), "exec"), module.__dict__)
        except Exception as error:
            raise ArtifactError(f"{path}: {type(error).__name__}: {error}") from error
        if type(getattr(module, "PROGRAM", None)) is not CompiledProgram:
            raise ValueError("world artifact needs a generated CompiledProgram")
        if not hasattr(module, "CONTROLLERS"):
            raise ValueError("world artifact must declare CONTROLLERS, possibly None")
        controllers = module.CONTROLLERS
        if controllers is not None and (
            type(controllers) is not ControllerLibrary or controllers.program is not module.PROGRAM
        ):
            raise ValueError("artifact controllers must bind its exact Program")
        if controllers is not None and controllers.planning is not None:
            from .scenario_planning import CompiledScenarioPlanning

            planning = controllers.planning
            if (
                type(planning) is not CompiledScenarioPlanning
                or planning.program is not module.PROGRAM
                or planning is not getattr(module, "PLANNING", None)
                or not planning.atomic
            ):
                raise ValueError("subject control must select this artifact's exact scenario plan")
        if not hasattr(module, "DISPLAY"):
            raise ValueError("world artifact must declare DISPLAY, possibly None")
        display = module.DISPLAY
        if display is not None and (
            type(display) is not CompiledDisplay or display.program is not module.PROGRAM
        ):
            raise ValueError("artifact display must bind its exact Program")
        from .artifact_binding import register

        register(module, source)
        yield module
    finally:
        sys.modules.pop(name, None)
