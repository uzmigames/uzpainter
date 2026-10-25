"""Stored generator and filter effects expose their procedural through `get_source()` (phase3.1
item 2.6). The pins are synthetic test references, not Painter parity evidence."""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.export.conftest import export_tests as export_tests
from tests.python.conftest import Run
from tests.python.recorded_probe import ENVELOPE, recorded_readbacks
from tests.python.test_pyapi_native import ok
from tools.parity.schemas import REPO_ROOT


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


@pytest.fixture
def observations_project(run: Run, export_tests: Path, tmp_path: Path) -> None:  # noqa: F811
    """The effects layout with every procedural reference pinned in the reserved observation family
    (decision 362) and no observation namespace: nothing binds them."""
    ok(
        run("""
create(128)
project.save_as(WORK + "/observations.uzp")
project.close()
result = True
""")
    )
    process = subprocess.run(
        [str(export_tests), "procedural-observations", str(tmp_path / "observations.uzp")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr


@pytest.mark.parametrize("api", ["run", "facade"])
def test_reserved_observation_sources_have_no_legacy_reading(
    api: str, request: pytest.FixtureRequest, observations_project: None
) -> None:
    """Phase3.1 item 2.6g: a host fill source, a generator and a Filter pinned in the reserved
    observation family, without a binding, refuse the three getters and a valid no-op
    `set_parameters` with UnsupportedProcedural, leaving the revision unchanged: no pin,
    parameters or outputs are fabricated (the observed getters are item 2.6h)."""
    execute: Run = request.getfixturevalue(api)
    script = """
uzpainter.project.open(WORK + "/observations.uzp")
host = ls.get_root_layer_nodes(ts.get_active_stack())[0]
generator, filter_, empty = host.content_effects()

def refusals(handle, parameters):
    revision = uzpainter.project.revision()
    errors = [
        raises(handle.get_parameters),
        raises(lambda: handle.resource_id if FACADE else handle.resource_id()),
        raises(lambda: handle.image_outputs),
        raises(handle.set_parameters, parameters),
    ]
    return {"errors": errors, "unchanged": uzpainter.project.revision() == revision}

result = {
    "filter": refusals(filter_.get_source(), {"radius": 2.0}),
    "generator": refusals(generator.get_source(), {"amount": 0.25}),
    "host": refusals(host.get_source(ts.ChannelType.BaseColor), {"amount": 0.5}),
}
uzpainter.project.close()
"""
    outcome = ok(execute(f"FACADE = {api == 'facade'!r}\n" + script))
    for source, observed in outcome.items():
        assert observed["unchanged"] is True, source
        for error in observed["errors"]:
            assert error is not None and error.startswith("UnsupportedProcedural:"), (source, error)
            assert "reserved observation family" in error, (source, error)


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


REPLAYED_FUNCTIONS = ("substance_source", "substance_read", "substance_edit")
FILTER_STEPS = (19, 20, 21, 22, 23, 24)


def test_filter_restrictions_replay_the_recorded_probe_operations(
    facade: Run, effects_project: None
) -> None:
    """Steps 19-24 of `tier0/api-probes/source-substance-booleans-filter`, executed through the
    facade with the recorder's own `substance_read`/`substance_edit` (only the recorded node step
    is resolved to the fixture's filter), compared with both recordings, then again after reopen.
    No trace is recorded: these six operations cover the filter error path only (decision 112)."""
    path = ENVELOPE / "manifests/tier0/api-probes/source-substance-booleans-filter.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    steps = [s for s in manifest["instruction_sequence"]["steps"] if s["step"] in FILTER_STEPS]
    filter_step = next(
        s["step"]
        for s in manifest["instruction_sequence"]["steps"]
        if s["call"] == "substance_painter.layerstack.insert_filter_effect"
    )
    assert [s["step"] for s in steps] == list(FILTER_STEPS)
    assert {s["args"]["node_step"] for s in steps} == {filter_step}
    assert all(s["args"].get("effect") is True for s in steps)
    recordings = recorded_readbacks("source-substance-booleans-filter")
    expected = [
        {f"s{step}": recording[f"s{step}/{call}"] for step, call in calls(steps)}
        for recording in recordings
    ]
    assert len(expected) == 2 and expected[0] == expected[1]
    protocol = (REPO_ROOT / "tools/parity/recorder/painter_probes.py").read_text(encoding="utf-8")
    functions = {
        node.name: ast.get_source_segment(protocol, node)
        for node in ast.parse(protocol).body
        if isinstance(node, ast.FunctionDef) and node.name in REPLAYED_FUNCTIONS
    }
    assert set(functions) == set(REPLAYED_FUNCTIONS) and all(functions.values())
    script = (
        """
import enum
from typing import Any
import substance_painter

def describe(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, enum.Enum):
        return value.name
    if isinstance(value, (tuple, list)):
        return [describe(v) for v in value]
    if isinstance(value, dict):
        return {key: describe(v) for key, v in value.items()}
    return value.name

def fresh(step):
    # The only adaptation: the recorded filter step is the fixture's filter effect.
    assert int(step) == FILTER_STEP
    return ls.get_root_layer_nodes(ts.get_active_stack())[0].content_effects()[1]

def channel_arg(args):
    raise AssertionError("an effect source takes no channel")
"""
        + "\n\n".join(str(functions[name]) for name in REPLAYED_FUNCTIONS)
        + f"\nFILTER_STEP = {filter_step}\nsteps = {steps!r}\n"
        + """
def replay():
    observed = {}
    for step in steps:
        call, args = step["call"], dict(step["args"])
        read = "roundtrip" not in args
        try:
            value = substance_read(call, args) if read else substance_edit(call, args)
            observed["s" + str(step["step"])] = {"value": describe(value)}
        except Exception as error:
            observed["s" + str(step["step"])] = {
                "raised": {"type": type(error).__name__, "message": str(error)}
            }
    return observed

uzpainter.project.open(WORK + "/effects.uzp")
filter_source = fresh(FILTER_STEP).get_source()
before = (uzpainter.project.revision(), filter_source.get_parameters())
first = replay()
assert (uzpainter.project.revision(), filter_source.get_parameters()) == before
uzpainter.project.save()
uzpainter.project.close()
uzpainter.project.open(WORK + "/effects.uzp")
filter_source = fresh(FILTER_STEP).get_source()
reopened_before = (uzpainter.project.revision(), filter_source.get_parameters())
second = replay()
assert (uzpainter.project.revision(), filter_source.get_parameters()) == reopened_before
uzpainter.project.close()
result = [first, second]
"""
    )
    first, second = ok(facade(script))
    assert first == expected[0], {"expected": expected[0], "actual": first}
    assert second == expected[1], {"expected": expected[1], "actual": second}


def calls(steps: list[dict[str, Any]]) -> list[tuple[int, str]]:
    return [(int(s["step"]), str(s["call"]).rsplit(".", 1)[1]) for s in steps]
