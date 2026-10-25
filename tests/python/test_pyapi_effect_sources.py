"""Stored generator and filter effects expose their procedural through `get_source()` (phase3.1
item 2.6). The pins are synthetic test references, not Painter parity evidence."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.export.conftest import export_tests as export_tests
from tests.python.conftest import Run
from tests.python.recorded_probe import recorded_readbacks
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
# Recorded in Painter (tier0/api-probes/source-substance-booleans-filter, r1 and r2).
unavailable = "ValueError: Resolution property is not available on a FilterEffectNode."
assert raises(getattr, filter_, "resolution") == unavailable
single = "EditionContextException: Only valid in single channel context"
assert raises(getattr, filter_, "active_output") == single
assert "active_output requires" in raises(getattr, generator, "active_output")
assert raises(getattr, generator, "image_outputs").startswith("UnsupportedProcedural:")

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
    # Painter's ValueError precedes every other check of a filter's resolution.
    assert errors["filter resolution"] == (
        "ValueError: Resolution property is not available on a FilterEffectNode."
    ), errors
    # No backend evaluates generator or filter effects yet: edits are refused, naming the owner.
    assert errors["generator parameters"].startswith("NotYetSupported:"), errors
    assert "phase3.2_proc-generator-families" in errors["generator parameters"], errors
    assert "phase3.2_proc-generator-families" in errors["generator resolution"], errors
    assert "phase3.2_proc-filter-families" in errors["filter parameters"], errors
    assert "active_output requires" in errors["active output"], errors


@pytest.mark.parametrize("api", ["run", "facade"])
def test_effect_source_transactions_roll_back_and_handles_go_stale(
    api: str, request: pytest.FixtureRequest, effects_project: None
) -> None:
    execute: Run = request.getfixturevalue(api)
    script = """
uzpainter.project.open(WORK + "/effects.uzp")
host = ls.get_root_layer_nodes(ts.get_active_stack())[0]
generator_node, filter_node, _ = host.content_effects()
generator, filter_ = generator_node.get_source(), filter_node.get_source()
parameters = {"amount": 0.25, "$randomseed": 3, "label": "a"}

def edit_in_transaction():
    with uzpainter.Transaction("supported rename with an unsupported effect edit"):
        host.set_name("renamed host")
        generator.set_parameters({"amount": 0.5})

revision = uzpainter.project.revision()
errors = {"transaction": raises(edit_in_transaction)}
assert errors["transaction"] is not None
assert uzpainter.project.revision() == revision
assert host.get_name() == "procedural host"
assert generator.get_parameters() == parameters

ls.delete_node(generator_node)
assert uzpainter.project.revision() == revision + 1
errors["stale read"] = raises(generator.get_parameters)
errors["stale edit"] = raises(generator.set_parameters, {"amount": 0.5})
errors["stale resolution"] = raises(getattr, generator, "resolution")
assert uzpainter.project.revision() == revision + 1
assert filter_.get_parameters() == {"radius": 2.0}
uzpainter.project.close()
result = errors
"""
    errors = ok(execute(script))
    # The whole transaction rolls back, including its supported rename.
    assert "phase3.2_proc-generator-families" in errors["transaction"], errors
    for name in ("stale read", "stale edit", "stale resolution"):
        assert errors[name] is not None and errors[name].startswith("ValueError:"), errors


@pytest.mark.parametrize("api", ["run", "facade"])
def test_filter_source_errors_equal_the_recorded_painter_errors(
    api: str, request: pytest.FixtureRequest, effects_project: None
) -> None:
    """Compared with `tier0/api-probes/source-substance-booleans-filter` (both recordings)."""
    recordings = recorded_readbacks("source-substance-booleans-filter")
    expected = [
        {
            "active_output": recording["s19/active_output"]["raised"],
            "resolution get": recording["s20/resolution"]["raised"],
            "resolution set": recording["s21/resolution"]["raised"],
        }
        for recording in recordings
    ]
    assert len(expected) == 2 and expected[0] == expected[1]
    execute: Run = request.getfixturevalue(api)
    script = """
if FACADE:
    modes, override = source.ResolutionMode, source.ResolutionOverride
else:
    modes, override = source._ResolutionMode, source._ResolutionOverride

def raised(call, *args):
    try:
        call(*args)
    except Exception as error:
        return {"type": type(error).__name__, "message": str(error)}
    return None

uzpainter.project.open(WORK + "/effects.uzp")
host = ls.get_root_layer_nodes(ts.get_active_stack())[0]
filter_ = host.content_effects()[1].get_source()
custom128 = override(modes.Custom if FACADE else modes.Manual, (128, 128), 0)
revision = uzpainter.project.revision()
result = {
    "active_output": raised(getattr, filter_, "active_output"),
    "resolution get": raised(getattr, filter_, "resolution"),
    "resolution set": raised(setattr, filter_, "resolution", custom128),
}
assert uzpainter.project.revision() == revision
uzpainter.project.close()
"""
    assert ok(execute(f"FACADE = {api == 'facade'!r}\n" + script)) == expected[0]
