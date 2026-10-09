"""Only the selected owner-graph contract remains as an author entry."""

from importlib.util import find_spec

import pytest
from test_control_binding_v1 import _inputs
from test_world_binding_v1 import _compile

import nomos_c0
from nomos_c0.author_contract_v1 import C0LawError


@pytest.mark.parametrize(
    "module", ["scene_action_v1", "scene_due_v1", "scene_due_wave_v1", "scene_due_ordered_v1"]
)
def test_retired_catalogs_have_no_import_or_export(module):
    assert find_spec(f"nomos_c0.{module}") is None
    assert nomos_c0.__all__ == ("C0BindingError", "C0LawError")


@pytest.mark.parametrize(
    "schema",
    [
        "c0.source.scene_action.v1",
        "c0.source.scene_due.v1",
        "c0.source.scene_due_wave.v2",
        "c0.source.scene_due_ordered.v1",
    ],
)
def test_current_compiler_rejects_retired_source_contracts(schema):
    lib, ports, source, _ = _inputs()
    source["schema"] = schema
    with pytest.raises(C0LawError):
        _compile(lib, ports, source)
