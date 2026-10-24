"""Stored generator and filter effects expose their procedural through `get_source()` (phase3.1
item 2.6). The pins are synthetic test references, not Painter parity evidence."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.export.conftest import export_tests as export_tests
from tests.python.conftest import Run
from tests.python.test_pyapi_native import ok


@pytest.fixture
def effects_project(run: Run, export_tests: Path, tmp_path: Path) -> None:  # noqa: F811
    ok(
        run("""
create(128)
project.save_as(WORK + "/effects.uzp")
project.close()
result = True
""")
    )
    process = subprocess.run(
        [str(export_tests), "procedural-effects", str(tmp_path / "effects.uzp")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr


@pytest.mark.parametrize("api", ["run", "facade"])
def test_effect_sources_read_and_refuse_edits_before_mutation(
    api: str, request: pytest.FixtureRequest, effects_project: None
) -> None:
    execute: Run = request.getfixturevalue(api)
    script = """
if FACADE:
    modes, override = source.ResolutionMode, source.ResolutionOverride
    custom = modes.Custom
else:
    modes, override = source._ResolutionMode, source._ResolutionOverride
    custom = modes.Manual

def sources():
    host = ls.get_root_layer_nodes(ts.get_active_stack())[0]
    generator, filter_, empty = host.content_effects()
    assert isinstance(generator, ls.GeneratorEffectNode)
    assert isinstance(filter_, ls.FilterEffectNode)
    assert isinstance(empty, ls.GeneratorEffectNode)
    assert empty.get_source() is None
    return generator.get_source(), filter_.get_source()

def identity(value):
    return (value.resource_id if FACADE else value.resource_id()).url()

def unchanged(call, *args):
    revision = uzpainter.project.revision()
    error = raises(call, *args)
    assert error is not None, args
    assert uzpainter.project.revision() == revision, error
    return error

uzpainter.project.open(WORK + "/effects.uzp")
generator, filter_ = sources()
assert isinstance(generator, source.SourceSubstance)
assert isinstance(filter_, source.SourceSubstance)
assert identity(generator) == "resource://uzasset/test-generator/ridge?version=2"
assert identity(filter_) == "resource://uzasset/test-filter/blur?version=1"
parameters = {"amount": 0.25, "$randomseed": 3, "label": "a"}
assert generator.get_parameters() == parameters
copied = generator.get_parameters()
copied["amount"] = 0.5
assert generator.get_parameters() == parameters
assert filter_.get_parameters() == {"radius": 2.0}
read = generator.resolution
assert read.mode == custom and tuple(read.value) == (256, 256) and read.log2_offset == 0
if FACADE:
    assert raises(getattr, filter_, "resolution").startswith("UnsupportedProcedural:")
else:
    assert filter_.resolution is None
assert "active_output requires" in raises(getattr, generator, "active_output")

errors = {}
errors["generator parameters"] = unchanged(generator.set_parameters, {"amount": 0.5})
larger = override(custom, (512, 512), 0)
errors["generator resolution"] = unchanged(setattr, generator, "resolution", larger)
errors["filter parameters"] = unchanged(filter_.set_parameters, {"radius": 3.0})
automatic = override(modes.Auto, (128, 128), 0)
errors["filter resolution"] = unchanged(setattr, filter_, "resolution", automatic)
errors["active output"] = unchanged(setattr, generator, "active_output", "mask")
assert generator.get_parameters() == parameters
assert filter_.get_parameters() == {"radius": 2.0}
assert tuple(generator.resolution.value) == (256, 256)

uzpainter.project.close()
uzpainter.project.open(WORK + "/effects.uzp")
generator, filter_ = sources()
assert generator.get_parameters() == parameters
assert filter_.get_parameters() == {"radius": 2.0}
uzpainter.project.close()
result = errors
"""
    errors = ok(execute(f"FACADE = {api == 'facade'!r}\n" + script))
    # The documented ValueError precedes every other check of a filter's resolution.
    assert errors["filter resolution"].startswith("ValueError:"), errors
    assert "FilterEffectNode" in errors["filter resolution"], errors
    # No backend evaluates generator or filter effects yet: edits are refused, naming the owner.
    assert errors["generator parameters"].startswith("NotYetSupported:"), errors
    assert "phase3.2_proc-generator-families" in errors["generator parameters"], errors
    assert "phase3.2_proc-generator-families" in errors["generator resolution"], errors
    assert "phase3.2_proc-filter-families" in errors["filter parameters"], errors
    assert "active_output requires" in errors["active output"], errors
