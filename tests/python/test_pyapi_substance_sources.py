"""Synthetic project snapshots exercise source edits; these are not Painter parity evidence."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np
import OpenEXR
import pytest

from tests.export.conftest import export_tests as export_tests
from tests.python.conftest import Run
from tests.python.recorded_probe import recorded_readbacks
from tests.python.test_pyapi_native import EXPORT_CONFIG, ok


def test_own_asset_resource_ids_roundtrip_without_url_form_decoding(facade: Run) -> None:
    assert (
        ok(
            facade("""
from substance_painter import resource
native = uzpainter.resource.ResourceID
for version in ("1", "1.2.3-rc.1+build.7"):
    url = "resource://uzasset/snapshot/authored-test?version=" + version
    for cls in (native, resource.ResourceID):
        identity = cls.from_url(url)
        assert identity.context == "uzasset"
        assert identity.name == "snapshot/authored-test"
        assert identity.version == version
        assert identity.url() == url
        assert native.from_url(identity.url()).url() == url
        assert resource.ResourceID.from_url(identity.url()).url() == url
        assert cls("uzasset", "snapshot/authored-test", version).url() == url
for url in ("resource://uzasset/snapshot/authored-test",
            "resource://uzasset/snapshot/authored-test?version=",
            "resource://uzasset/snapshot/authored-test?version=1 2",
            "resource://uzasset/snapshot/authored-test?version=1&other=2",
            "resource://uzasset/snapshot?version=1",
            "resource://uzasset/snapshot/../authored-test?version=1"):
    for cls in (native, resource.ResourceID):
        assert raises(cls.from_url, url) is not None, url
for cls in (native, resource.ResourceID):
    assert raises(cls("uzasset", "snapshot/authored-test", "1 2").url) is not None
invalid = "resource://project/image?version=1"
assert raises(native.from_url, invalid) is not None
result = True
""")
        )
        is True
    )


@pytest.fixture
def snapshot_project(run: Run, export_tests: Path, tmp_path: Path) -> None:  # noqa: F811
    ok(
        run("""
for name in ("snapshot", "foreign"):
    create(128)
    project.save_as(WORK + "/" + name + ".uzp")
    project.close()
result = True
""")
    )
    process = subprocess.run(
        [str(export_tests), "snapshot-source", str(tmp_path / "snapshot.uzp"), "7"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr


@pytest.mark.parametrize("api", ["run", "facade"])
def test_substance_snapshot_edits_export_and_reopen(
    api: str, request: pytest.FixtureRequest, snapshot_project: None, tmp_path: Path
) -> None:
    execute: Run = request.getfixturevalue(api)
    config = json.loads(EXPORT_CONFIG)
    output = config["exportPresets"][0]["maps"][0]
    output["fileName"] = "$textureSet_scalar"
    output["channels"][0]["srcMapName"] = "user0"
    output["parameters"].update(fileFormat="exr", bitDepth="32f", paddingAlgorithm="passthrough")
    script = """
uzpainter.project.open(WORK + "/snapshot.uzp")
node = ls.get_root_layer_nodes(ts.get_active_stack())[0]
value = node.get_source(CT.User0)
assert isinstance(value, source.SourceSubstance)
identity = value.resource_id if FACADE else value.resource_id()
assert identity.url() == "resource://uzasset/snapshot/authored-test?version=1"
assert uzpainter.resource.ResourceID.from_url(identity.url()).url() == identity.url()
invalid_url = "resource://project/image?version=1"
assert raises(uzpainter.resource.ResourceID.from_url, invalid_url) is not None
assert value.active_output == "scalar"
assert value.get_parameters() == {"amount": 0.5, "$randomseed": 7}
# The original snapshot was recorded without metadata: its outputs are unknown, not guessed.
assert raises(getattr, value, "image_outputs").startswith("UnsupportedProcedural:")
copied = value.get_parameters()
copied["amount"] = 0.75
assert value.get_parameters()["amount"] == 0.5
value.set_parameters({"amount": 0.5})
assert value.get_parameters()["$randomseed"] == 7
if FACADE:
    assert raises(getattr, value, "resolution").startswith("UnsupportedProcedural:")
    modes, override = source.ResolutionMode, source.ResolutionOverride
    custom = modes.Custom
else:
    assert value.resolution is None
    modes, override = source._ResolutionMode, source._ResolutionOverride
    custom = modes.Manual
for mode in (custom, modes.Auto):
    value.resolution = override(mode, (128, 128), 0)
    read = value.resolution
    assert read.mode == mode and tuple(read.value) == (128, 128) and read.log2_offset == 0
value.active_output = "scalar"
files = []
def capture(name):
    config["exportPath"] = WORK + "/" + name
    result = uzpainter.export.export_project_textures(config)
    files.append(result["files"][0]["path"])
capture("original")
value.set_parameters({"amount": 0.625})
assert node.get_source(CT.User0).get_parameters() == {"amount": 0.625, "$randomseed": 7}
outputs = value.image_outputs
assert outputs == ["scalar", "aux"]
outputs.append("changed")
assert value.image_outputs == ["scalar", "aux"]
capture("alternate")
uzpainter.project.save()
uzpainter.project.close()
uzpainter.project.open(WORK + "/snapshot.uzp")
node = ls.get_root_layer_nodes(ts.get_active_stack())[0]
value = node.get_source(CT.User0)
assert value.get_parameters() == {"amount": 0.625, "$randomseed": 7}
assert value.resolution.mode == modes.Auto
assert value.image_outputs == ["scalar", "aux"]
capture("reopened")
value.set_parameters({"amount": 0.5})
capture("reverted")
# The same handle never keeps the alternate snapshot's metadata after reverting the signature.
assert raises(getattr, value, "image_outputs").startswith("UnsupportedProcedural:")
def invalid_transaction():
    with uzpainter.Transaction("invalid procedural final state"):
        value.set_parameters({"amount": 0.625})
        value.set_parameters({"amount": 0.75})
revision = uzpainter.project.revision()
assert raises(invalid_transaction) is not None
assert uzpainter.project.revision() == revision
assert value.get_parameters() == {"amount": 0.5, "$randomseed": 7}
capture("rolled-back")
with uzpainter.Transaction("temporary unsupported procedural state"):
    value.set_parameters({"amount": 0.75})
    value.set_parameters({"amount": 0.5})
assert value.get_parameters()["amount"] == 0.5
errors = []
for parameters in ({"amount": 0.75}, {"unknown": 0.5}, {"amount": True},
                   {"amount": 1}, {"amount": "0.5"}, {"amount": float("nan")},
                   {"amount": float("inf")}, {"$randomseed": 7.0}, {"$randomseed": True}):
    revision = uzpainter.project.revision()
    error = raises(value.set_parameters, parameters)
    assert error is not None, parameters
    errors.append(error)
    assert uzpainter.project.revision() == revision
    assert value.get_parameters() == {"amount": 0.5, "$randomseed": 7}
for name, replacement in (("active_output", "missing"),
                          ("resolution", override(custom, (256, 256), 0))):
    revision = uzpainter.project.revision()
    assert raises(setattr, value, name, replacement) is not None
    assert uzpainter.project.revision() == revision
    assert value.active_output == "scalar"
    assert tuple(value.resolution.value) == (128, 128)
capture("refused")
node.set_source(CT.User0, cm.Color(0.25, 0.25, 0.25, "Raw"))
assert raises(value.get_parameters) is not None
assert raises(getattr, value, "image_outputs").startswith("ValueError:")
assert raises(value.set_parameters, {"amount": 0.5}) is not None
uzpainter.project.close()
uzpainter.project.open(WORK + "/snapshot-imported.uzp")
node = ls.get_root_layer_nodes(ts.get_active_stack())[0]
value = node.get_source(CT.User0)
ls.delete_node(node)
assert raises(value.get_parameters) is not None
assert raises(setattr, value, "active_output", "scalar") is not None
uzpainter.project.close()
result = files
"""
    files = ok(
        execute(
            f"FACADE = {api == 'facade'!r}\nconfig = json.loads({json.dumps(config)!r})\n" + script
        )
    )
    original = np.frombuffer((tmp_path / "snapshot-expected.raw").read_bytes(), dtype=np.uint32)
    alternate = np.frombuffer((tmp_path / "snapshot-alternate.raw").read_bytes(), dtype=np.uint32)
    assert not np.array_equal(original, alternate)
    # User0's base is 1; the calibrated float32 compositor subtracts then adds that base.
    base = np.float32(1.0)
    original_readout = (original.view(np.float32) - base + base).view(np.uint32)
    alternate_readout = (alternate.view(np.float32) - base + base).view(np.uint32)
    assert not np.array_equal(alternate_readout, alternate)
    for image_path, expected in zip(
        files,
        (
            original_readout,
            alternate_readout,
            alternate_readout,
            original_readout,
            original_readout,
            original_readout,
        ),
        strict=True,
    ):
        with OpenEXR.File(image_path, separate_channels=True) as image:
            channels = image.channels()
            assert len(channels) == 1
            actual = next(iter(channels.values())).pixels.view(np.uint32).ravel()
            np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize("api", ["run", "facade"])
def test_boolean_refusal_equals_the_recorded_painter_error(
    api: str, request: pytest.FixtureRequest, snapshot_project: None
) -> None:
    """Compared with `tier0/api-probes/source-substance-booleans-filter`: a bool for an integer
    parameter raises Painter's TypeError and leaves the value unchanged (both recordings). The
    recorded property name stays private; only the message's template is compared."""
    recordings = recorded_readbacks("source-substance-booleans-filter")

    def template(error: dict[str, str]) -> dict[str, str]:
        return {
            **error,
            "message": re.sub(r"property '[^']*'", "property '<name>'", error["message"]),
        }

    expected = []
    for recording in recordings:
        for step, before in (("s10", "s9"), ("s14", "s13")):
            assert (
                recording[f"s{int(step[1:]) + 1}/get_parameters"]
                == recording[f"{before}/get_parameters"]
            )
            expected.append(template(recording[f"{step}/set_parameters"]["raised"]))
    assert len(expected) == 4 and all(entry == expected[0] for entry in expected)
    execute: Run = request.getfixturevalue(api)
    script = """
uzpainter.project.open(WORK + "/snapshot.uzp")
value = ls.get_root_layer_nodes(ts.get_active_stack())[0].get_source(CT.User0)
before, revision = value.get_parameters(), uzpainter.project.revision()
result = []
for flag in (True, False):
    try:
        value.set_parameters({"$randomseed": flag})
        result.append(None)
    except Exception as error:
        result.append({"type": type(error).__name__, "message": str(error)})
assert value.get_parameters() == before and uzpainter.project.revision() == revision
uzpainter.project.close()
"""
    observed = ok(execute(script))
    assert [template(entry) for entry in observed] == expected[:2]
