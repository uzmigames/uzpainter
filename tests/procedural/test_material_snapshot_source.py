"""Material fills served from a project-private multi-output capture (decision 413), native half.

`uzp-export-tests snapshot-material` (tests/export/snapshot_source_test.cpp) records authored
synthetic snapshots of one resource in five states into a plane project and checks the document
rules (Height only, `tz16(float32(2 x - 1))`, the mask rule, the signature states, the codec).
This driver then runs the native `uzpainter` API over that project: `set_material_source` by the
observed URL, the material handle's getters and its multiple output members, presets and image
inputs, refusals before any change, save/reopen, and a Height export. Authored values only; no
Painter parity is established here.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import OpenEXR

from tests.export.conftest import export_tests as export_tests
from tests.python.conftest import Run
from tests.python.conftest import pyapi_runner as pyapi_runner
from tests.python.conftest import run as run
from tests.python.test_pyapi_native import EXPORT_CONFIG, ok

URL = "resource://starter_assets/authored/material?version=1.sbsar"
GREY_A = Path(__file__).resolve().parents[2] / "parity/fixtures/tier0-semantics/bitmaps/grey-a.png"

SCRIPT = """
URL = {url!r}
project.open(WORK + "/material.uzp")
stack = ts.get_active_stack()
fill = ls.insert_fill(top(stack))
r = {{}}
r["not_material"] = raises(fill.get_material_source)
r["unknown_url"] = raises(fill.set_material_source, URL + "x")
fill.set_material_source(URL)
r["mode"] = fill.source_mode().name
r["active"] = sorted(c.name for c in fill.active_channels)
m = fill.get_material_source()
r["params"] = m.get_parameters()
r["outputs"] = m.image_outputs
r["inputs"] = m.image_inputs
r["presets"] = m.get_preset_list()
r["url"] = m.resource_id().url()
r["mapping"] = m._output_mapping()
r["mask"] = m._mask_output()
r["default_mask"] = m._material_context()["material"]["mask_output"]
r["input_sources"] = sorted(m._input_sources())
r["active_output"] = raises(lambda: m.active_output)
r["set_active_output"] = raises(setattr, m, "active_output", "height")
r["set_parameters"] = raises(m.set_parameters, {{"amount": 0.75}})
r["resolution"] = m.resolution
r["unplugged"] = m._input_source("curvature")
r["unknown_input"] = raises(m._input_source, "nope")
revision = project.revision()
r["missing_preset"] = raises(m.apply_preset, "uzp-no-such-preset")
r["flat"] = raises(m.apply_preset, "Flat")
r["unchanged"] = project.revision() == revision
m.apply_preset("Bumpy")
r["preset_params"] = m.get_parameters()
m._set_input_colour("curvature", [0.25, 0.5, 0.75])
r["colour"] = m._input_source("curvature")
grey = [h for h in resource.list_project_resources() if h.name == "grey-a"][0]
m._set_input_bitmap("curvature", grey, "Data")
r["bitmap"] = m._input_source("curvature")
r["bitmap_is_file_hash"] = m._input_source("curvature")["bitmap_sha256"] == grey.version
m._reset_input("curvature")
r["reset"] = m._input_source("curvature")
m._remove_input("curvature")
r["removed"] = m._input_source("curvature")
revision = project.revision()
r["unrecorded_colour"] = raises(m._set_input_colour, "curvature", [0.5, 0.5, 0.5])
r["mask_other"] = raises(m._set_mask_output, "normal")
r["mask_unlisted"] = raises(m._set_mask_output, "channels_Alpha")
r["mapping_unlisted"] = raises(m._set_output_mapping, "BaseColor", "nope")
r["unchanged_after_refusals"] = project.revision() == revision
m._set_mask_output("height")
r["mask_own"] = m._mask_output()
m._set_output_mapping("BaseColor", "normal")
r["mapping_basecolor"] = m._output_mapping()
uid = fill.uid()
project.save()
project.close()
project.open(WORK + "/material.uzp")
m = ls.get_node_by_uid(uid).get_material_source()
r["reopened"] = [m._input_source("curvature"), m._mask_output(), m._output_mapping()]
r["reopened"].append(m.get_parameters())
config = json.loads({config!r})
config["exportPath"] = WORK + "/export"
output = export.export_project_textures(config)
r["file"] = output["files"][0]["path"]
r["receipt"] = output["receipt"]
project.close()
result = r
"""


def ramp(state: int, output: str) -> np.ndarray:
    """The native fixture's authored raster of `state` and `output`, as float32."""
    i = np.arange(128 * 128, dtype=np.int64)
    values = (i * 37 + state * 1009 + (4099 if output == "normal" else 0)) % 8192
    return (values.astype(np.float32) / np.float32(8192)).reshape(128, 128)


def tz16(values: np.ndarray) -> np.ndarray:
    single = values.astype(np.float32)
    half = single.astype(np.float16)
    over = np.abs(half.astype(np.float32)) > np.abs(single)
    return np.where(over, np.nextafter(half, np.float16(0)), half).astype(np.float32)


def test_material_source_through_the_native_api(
    run: Run,  # noqa: F811
    export_tests: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    ok(
        run(
            "create(128)\n"
            f"resource.import_project_resource({GREY_A.as_posix()!r}, resource.Usage.TEXTURE)\n"
            'project.save_as(WORK + "/material.uzp")\nproject.close()\nresult = True'
        )
    )
    native = subprocess.run(
        [str(export_tests), "snapshot-material", str(tmp_path / "material.uzp")],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert native.returncode == 0, native.stdout + native.stderr
    assert "snapshot material:" in native.stdout
    config = json.loads(EXPORT_CONFIG)
    parameters = config["exportPresets"][0]["maps"][0]["parameters"]
    parameters.update(fileFormat="exr", bitDepth="32f", paddingAlgorithm="passthrough")
    r: dict[str, Any] = ok(run(SCRIPT.format(url=URL, config=json.dumps(config))))
    assert r["not_material"].startswith("RuntimeError")
    assert (
        r["unknown_url"].startswith("NotYetSupported")
        and "no recorded default state" in r["unknown_url"]
    )
    assert r["mode"] == "Material" and r["active"] == ["Height"]
    assert r["params"] == {"$randomseed": 0, "amount": 0.5}
    assert r["outputs"] == ["normal", "height"] and r["inputs"] == ["curvature"]
    assert r["presets"] == ["Bumpy", "Flat"] and r["url"] == URL
    assert r["mapping"] == {"Height": "height", "Normal": "normal"}
    assert r["mask"] is None and r["default_mask"] == "channels_Alpha"
    assert r["input_sources"] == ["curvature"]
    assert r["active_output"] == "EditionContextException: Only valid in single channel context"
    assert r["set_active_output"] == "EditionContextException: Only valid in single channel context"
    assert r["set_parameters"].startswith("NotYetSupported")
    assert r["resolution"] is None
    assert r["unplugged"] is None and r["unknown_input"].startswith("NotYetSupported")
    assert r["missing_preset"] == (
        "ValueError: Preset name 'uzp-no-such-preset' not found in preset list "
        "(case sensitive search)."
    )
    assert r["flat"].startswith("NotYetSupported") and r["unchanged"]
    assert r["preset_params"] == {"$randomseed": 0, "amount": 0.75}
    assert r["colour"] == {"working_colour": [0.25, 0.5, 0.75]}
    assert r["bitmap"]["colour_space"] == "Data" and r["bitmap_is_file_hash"]
    assert r["reset"] is None and r["removed"] == {"working_colour": [0.0, 0.0, 0.0]}
    assert r["unrecorded_colour"].startswith("NotYetSupported")
    assert r["mask_other"].startswith("NotYetSupported")
    assert "phase3.3_procedural-families item 2.7" in r["mask_other"]
    assert r["mask_unlisted"].startswith("NotYetSupported")
    assert r["mapping_unlisted"].startswith("NotYetSupported")
    assert r["unchanged_after_refusals"]
    assert r["mask_own"] == "height"
    assert r["mapping_basecolor"] == {"BaseColor": "normal", "Height": "height", "Normal": "normal"}
    assert r["reopened"] == [
        {"working_colour": [0.0, 0.0, 0.0]},
        "height",
        {"BaseColor": "normal", "Height": "height", "Normal": "normal"},
        {"$randomseed": 0, "amount": 0.75},
    ]
    # The removed state is the fixture's fifth snapshot (index 4): Height is tz16(2 x - 1) of it.
    with OpenEXR.File(r["file"], separate_channels=True) as image:
        (channel,) = image.channels().values()
        actual = np.asarray(channel.pixels, dtype=np.float32)
    x = ramp(4, "height")
    np.testing.assert_array_equal(actual, tz16(np.float32(2) * x - np.float32(1)))
    receipt = json.loads(Path(r["receipt"]).read_text(encoding="utf-8"))
    assert len(receipt["procedural_snapshots"]) == 1
