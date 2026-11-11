"""A material fill's BaseColor, BaseMetalness, SpecularRoughness, Normal and Height
(`phase3.3_procedural-families` item 2.16), over authored snapshots; no Painter value is used.

`uzp-export-tests snapshot-material-channels` records an authored decision-413 capture of one
material at the project's 128 px texture set (both views of five outputs, and a colour parameter
read in Raw on the split sources and in sRGB on the material source, schema `/5`), and inserts its
material fill alone over the empty stack without the support check. The support check refuses
the fill's channels other than Height until their same-session golden is admitted (decision 431):
binding the material with `set_material_source` and every edit of the fill raise
`NotYetSupported` naming item 2.16, before any change. The native API reads the colour back as the
seam's tagged value, and the material context records its sRGB space. The project is exported by
`uzp-export-tests material-export`, which evaluates without the support check, through the CPU
tile store and a DX12 engine: every file is byte-equal between the two lanes and equal to the
channel rules computed here from the authored views:

- Height: tz16(float32(2 x - 1)) of the L32F view (decision 416);
- BaseMetalness, SpecularRoughness: float32(c / 255) with c = ((k >> 4) 255 + 2047) >> 12 of each
  16-bit code k = round(65535 x), some views one float32 ulp off their code;
- BaseColor: one strictly increasing export per sRGB8 code round(255 v) of the binary16 view;
- Normal: (tz16 r, tz16(1 - g), tz16 b) of the RGB32F view.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import OpenEXR
import pytest

from tests.export.conftest import export_tests as export_tests
from tests.python.conftest import Run
from tests.python.conftest import pyapi_runner as pyapi_runner
from tests.python.conftest import run as run
from tests.python.test_pyapi_native import ok

URL = "resource://starter_assets/authored/coloured?version=1.sbsar"
SIZE = 128
TEXELS = SIZE * SIZE
CHANNELS = {
    "BaseColor": ("basecolor", "RGB"),
    "BaseMetalness": ("basemetalness", "L"),
    "SpecularRoughness": ("specularroughness", "L"),
    "Normal": ("normal", "RGB"),
    "Height": ("height", "L"),
}

SCRIPT = """
project.open(WORK + "/coloured.uzp")
stack = ts.get_active_stack()
r = {{}}
r["set"] = ts.all_texture_sets()[0].name()
r["formats"] = {{c.name: stack.get_channel(c).format().name for c in stack.all_channels()}}
fill = ls.get_node_by_uid({uid})
m = fill.get_material_source()
r["active"] = sorted(c.name for c in fill.active_channels)
r["tint"] = m.get_parameters()["tint"]
r["spaces"] = m._material_context()["material"]["colour_spaces"]
revision = project.revision()
r["colour"] = raises(m.set_parameters, {{"tint": r["tint"]}})
other = ls.insert_fill(top(stack))
r["bind"] = raises(other.set_material_source, {url!r})
ls.delete_node(other)
revision = project.revision()
r["opacity"] = raises(fill.set_opacity, 0.5, CT.BaseColor)
r["mode"] = raises(fill.set_blending_mode, ls.BlendingMode.Multiply, CT.SpecularRoughness)
r["mask"] = raises(fill.add_mask, ls.MaskBackground.White)
r["unchanged"] = project.revision() == revision
project.close()
result = r
"""


def export_config(directory: Path, texture_set: str) -> dict[str, Any]:
    maps = [
        {
            "fileName": name,
            "channels": [
                {"destChannel": c, "srcChannel": c, "srcMapType": "documentMap", "srcMapName": name}
                for c in layout
            ],
        }
        for name, layout in CHANNELS.values()
    ]
    return {
        "exportPath": directory.as_posix(),
        "exportShaderParams": False,
        "defaultExportPreset": "uzp_material",
        "exportPresets": [{"name": "uzp_material", "maps": maps}],
        "exportList": [{"rootPath": texture_set}],
        "exportParameters": [
            {
                "parameters": {
                    "fileFormat": "exr",
                    "bitDepth": "32f",
                    "dithering": False,
                    "paddingAlgorithm": "passthrough",
                }
            }
        ],
    }


def exported(export_tests: Path, project: Path, config: Path, backend: str) -> dict[str, Path]:  # noqa: F811
    proc = subprocess.run(
        [str(export_tests), "material-export", str(project), str(config), backend],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    if proc.returncode == 77:
        pytest.skip("gpu_unavailable: no DX12 device")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout.strip().splitlines()[-1])
    return {Path(f["relativePath"]).stem: Path(f["path"]) for f in report["files"]}


def pixels(path: Path) -> np.ndarray:
    with OpenEXR.File(str(path), separate_channels=True) as image:
        channels = image.channels()
        names = [n for n in ("R", "G", "B") if n in channels] or list(channels)
        planes = [np.asarray(channels[n].pixels, dtype=np.float32).reshape(-1) for n in names]
    return np.stack(planes, axis=-1)


def tz16(values: np.ndarray) -> np.ndarray:
    single = values.astype(np.float32)
    half = single.astype(np.float16)
    over = np.abs(half.astype(np.float32)) > np.abs(single)
    return np.where(over, np.nextafter(half, np.float16(0)), half).astype(np.float32)


def authored(output: str) -> np.ndarray:
    """The fixture's authored RGB32F view of `output` (snapshot_source_test.cpp), per texel."""
    texel = np.arange(TEXELS, dtype=np.int64)
    if output in ("metallic", "roughness"):
        k = (texel * (4099 if output == "metallic" else 61) + 7) % 65536
        grey = (k / 65535).astype(np.float32)
        if output == "roughness":
            off = (texel % 3 == 1) & (k < 65535)
            grey = np.where(off, np.nextafter(grey, np.float32(1)), grey).astype(np.float32)
        return np.stack([grey] * 3, axis=-1)
    i = texel[:, None] * 3 + np.arange(3)[None, :]
    if output == "basecolor":
        return (((i * 37 + 11) % 1025).astype(np.float32) / np.float32(1024)).astype(np.float32)
    return ((i * 7919 + 3) % 99991).astype(np.float32) / np.float32(99991)


def test_material_channel_rules_on_both_lanes(
    run: Run,  # noqa: F811
    export_tests: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    created = run(
        f'create({SIZE})\nproject.save_as(WORK + "/coloured.uzp")\nproject.close()\nresult = True'
    )
    assert created["status"] == "ok", created
    project = tmp_path / "coloured.uzp"
    native = subprocess.run(
        [str(export_tests), "snapshot-material-channels", str(project)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert native.returncode == 0, native.stdout + native.stderr
    uid = int(native.stdout.strip().rsplit("fill ", 1)[1])
    r: dict[str, Any] = ok(run(SCRIPT.format(url=URL, uid=uid)))
    assert {name: r["formats"][name] for name in CHANNELS} == {
        "BaseColor": "sRGB8",
        "BaseMetalness": "L8",
        "SpecularRoughness": "L8",
        "Normal": "RGB16F",
        "Height": "L16F",
    }
    assert r["active"] == sorted(CHANNELS)
    # The native API reads the colour as the seam's tagged value in the capture's space, and the
    # material context records the space the material source reads it in.
    assert r["tint"] == {
        "type": "color",
        "working_space": "Raw",
        "components": [0.25, 0.5, 0.75],
        "alpha": None,
    }
    assert r["spaces"] == {"tint": "sRGB"}
    assert r["colour"].startswith("NotYetSupported")
    # A second material fill is refused (its channels would compose over the first); the native
    # fixture checks that the fill alone is refused pending its same-session golden.
    for refusal in ("bind", "opacity", "mode", "mask"):
        assert r[refusal].startswith("NotYetSupported"), (refusal, r[refusal])
        assert "phase3.3_procedural-families item 2.16" in r[refusal], (refusal, r[refusal])
    assert r["unchanged"]

    lanes = {}
    for backend in ("cpu", "dx12"):
        out = tmp_path / f"out-{backend}"
        out.mkdir()
        config = tmp_path / f"config-{backend}.json"
        config.write_text(json.dumps(export_config(out, r["set"])), encoding="utf-8")
        lanes[backend] = exported(export_tests, project, config, backend)
    names = {name for name, _ in CHANNELS.values()}
    assert set(lanes["cpu"]) == set(lanes["dx12"]) == names
    for name in names:
        assert lanes["cpu"][name].read_bytes() == lanes["dx12"][name].read_bytes(), name

    files = lanes["cpu"]
    height = pixels(files["height"])[..., 0]
    x = authored("height")[..., 0]
    np.testing.assert_array_equal(height, tz16(np.float32(2) * x - np.float32(1)))
    normal = pixels(files["normal"])
    view = authored("normal")
    expected = np.stack(
        [tz16(view[..., 0]), tz16(np.float32(1) - view[..., 1]), tz16(view[..., 2])], axis=-1
    )
    np.testing.assert_array_equal(normal, expected)
    for name, output in (("basemetalness", "metallic"), ("specularroughness", "roughness")):
        k = np.round(authored(output)[..., 0].astype(np.float64) * 65535).astype(np.int64)
        codes = ((k >> 4) * 255 + 2047) >> 12
        np.testing.assert_array_equal(
            pixels(files[name])[..., 0], (codes / 255).astype(np.float32), err_msg=name
        )
    colour = pixels(files["basecolor"]).astype(np.float64).ravel()
    codes = np.floor(authored("basecolor").astype(np.float64) * 255 + 0.5).astype(np.int64).ravel()
    pairs = np.unique(np.stack([codes, colour], axis=1), axis=0)
    assert np.unique(pairs[:, 0]).size == pairs.shape[0], "one BaseColor export per code"
    assert np.all(np.diff(pairs[:, 1]) > 0), "BaseColor exports increase with the code"
    assert pairs.shape[0] == 256
