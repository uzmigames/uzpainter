"""The export resize against recording R-090 P4 (`export-resize`; task
phase3.2_unreal-ue56-packed-preset item 2.9, decision 349), on the owner's machine with the private
oracle store (skipped without it).

- Upscale (sizeLog2 9 and 10, PNG 16 and OpenEXR 32f, passthrough at 9): the texture set evaluated
  at the file's size equals Painter's files on r1 and r2, for User0 (RGB16), Height (L16F), an sRGB8
  BaseColor and the virtual normals where the evaluator evaluates them (s0 and s2).
- Downscale (sizeLog2 7 at PNG 16, OpenEXR 32f and PNG 8, passthrough at 7, and the one-side
  probes [8, 7] and [7, 8]): the single-step mean of the set's evaluation, stored in the channel's
  format, equals Painter's files for User0 and Height.
- Every case still refused (a side below 128, a downscaled sRGB8 channel or virtual normal, a mixed
  resize, OpenEXR 16f, dithering with a resize) raises NotYetSupported before anything is written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.export.encoders_tier0 import (
    _add_template_channels,
    _mesh_of,
    working_colours,
    write_export,
)
from tests.export.tier0 import export_spec, needs_store
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.decode import decode
from tools.parity.fit.oracle import Golden, load
from tools.parity.recorder.job import Step, export_step
from tools.parity.store.store import locate

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBES = REPO_ROOT / "parity" / "fixtures" / "tier0-semantics" / "export-probes" / "resize"
NORMALS = ("Normal_OpenGL", "Normal_DirectX")


def _golden() -> Golden:
    needs_store()
    root = manifest_root(current_envelope()) / "tier0" / "semantics"
    return load(locate(), root / "export-resize.json")


def _spec(golden: Golden, texture_set: str, spec_dir: Path, colours: bool) -> dict[str, Any]:
    """The evaluator spec of `texture_set` (its `set_resolutions` step applied to the spec); with
    `colours`, its BaseColor alone with the working colours the facade stores."""
    manifest = golden.manifest
    sized = [
        s
        for s in manifest["instruction_sequence"]["steps"]
        if s["call"].endswith("set_resolutions")
    ]
    source = working_colours(manifest) if colours else manifest
    steps = [
        s
        for s in source["instruction_sequence"]["steps"]
        if not s["call"].endswith("set_resolutions")
    ]
    spec = export_spec(
        dict(source, instruction_sequence=dict(source["instruction_sequence"], steps=steps)),
        texture_set,
        spec_dir,
    )
    spec["mesh"] = str(_mesh_of(manifest))
    _add_template_channels(spec)
    for step in sized:
        if step["args"]["texture_set"] == texture_set:
            spec["resolution"] = [step["args"]["width"], step["args"]["height"]]
    return spec


def _step_config(
    golden: Golden, step: int, maps: tuple[str, ...], out: Path, texture_set: str, **overrides: Any
) -> dict[str, Any]:
    raw = next(s for s in golden.manifest["instruction_sequence"]["steps"] if s["step"] == step)
    args = dict(raw["args"], **overrides)
    args["maps"] = [m for m in args["maps"] if m.split("/")[1].split(":")[0] in maps]
    return export_step(Step(step, raw["call"], args)).config(out, [texture_set])


def _probe_config(name: str, maps: tuple[str, ...], out: Path, texture_set: str) -> dict[str, Any]:
    config: dict[str, Any] = json.loads((PROBES / f"{name}.json").read_text(encoding="utf-8"))
    config["exportPath"] = str(out)
    config["exportList"] = [{"rootPath": texture_set}]
    for preset in config["exportPresets"]:
        preset["maps"] = [
            m for m in preset["maps"] if m["fileName"].removeprefix("$textureSet_") in maps
        ]
    return config


def _written(
    exe: Path, spec: dict[str, Any], config: dict[str, Any], work: Path
) -> dict[str, Path]:
    result = write_export(exe, spec, work / "spec", config, work / "run")
    assert "error" not in result, result
    return {f["relativePath"]: Path(f["path"]) for f in result["written"]}


def _assert_painter(golden: Golden, files: dict[str, Path], texture_set: str, output: str) -> int:
    """Every written file equals Painter's r1 and r2 file of `output` (`step<n>` or `probe/s<n>`)
    in decoded values; returns the files compared."""
    for relative, path in files.items():
        name = relative.rsplit(".", 1)[0].removeprefix(f"{texture_set}_")
        oid = (
            f"{texture_set}/{name}/{output}"
            if output.startswith("step")
            else f"{output}/{relative}"
        )
        ours = decode(path.read_bytes()).values
        for recording in ("r1", "r2"):
            theirs = golden.map(recording, oid).values
            assert ours.shape == theirs.shape, (oid, ours.shape, theirs.shape)
            differ = int(np.count_nonzero(ours != theirs))
            assert differ == 0, f"{oid} {recording}: {differ} values differ"
    return len(files)


UPSCALE_STEPS = (77, 79, 81, 83, 89)
DOWNSCALE_STEPS = (73, 75, 85, 87)


@pytest.mark.parametrize("texture_set", ["s0", "s1", "s2", "s3"])
def test_upscale_is_the_set_evaluated_at_the_file_size(
    export_tests: Path, tmp_path: Path, texture_set: str
) -> None:
    golden = _golden()
    maps: tuple[str, ...] = ("user0", "height")
    if texture_set in ("s0", "s2"):  # the evaluator refuses s1's and s3's normals at any size
        maps += NORMALS
    compared = 0
    for step in UPSCALE_STEPS:
        work = tmp_path / str(step)
        spec = _spec(golden, texture_set, work / "spec", colours=False)
        files = _written(
            export_tests, spec, _step_config(golden, step, maps, work / "out", texture_set), work
        )
        compared += _assert_painter(golden, files, texture_set, f"step{step}")
        work = tmp_path / f"{step}-basecolor"
        spec = _spec(golden, texture_set, work / "spec", colours=True)
        files = _written(
            export_tests,
            spec,
            _step_config(golden, step, ("basecolor",), work / "out", texture_set),
            work,
        )
        compared += _assert_painter(golden, files, texture_set, f"step{step}")
    assert compared == len(UPSCALE_STEPS) * (len(maps) + 1)


@pytest.mark.parametrize("texture_set", ["s0", "s2", "s3"])
def test_downscale_is_the_single_step_mean_in_the_channel_format(
    export_tests: Path, tmp_path: Path, texture_set: str
) -> None:
    golden = _golden()
    maps = ("user0", "height")
    compared = 0
    for step in DOWNSCALE_STEPS:
        work = tmp_path / str(step)
        spec = _spec(golden, texture_set, work / "spec", colours=False)
        files = _written(
            export_tests, spec, _step_config(golden, step, maps, work / "out", texture_set), work
        )
        compared += _assert_painter(golden, files, texture_set, f"step{step}")
    # The one-side probes: [8, 7] halves the height, [7, 8] the width (2-texel means, ties up).
    for number, probe in ((94, "size-8x7"), (95, "size-7x8")):
        work = tmp_path / probe
        spec = _spec(golden, texture_set, work / "spec", colours=False)
        files = _written(
            export_tests, spec, _probe_config(probe, maps, work / "out", texture_set), work
        )
        compared += _assert_painter(golden, files, texture_set, f"probe/s{number}")
    assert compared == (len(DOWNSCALE_STEPS) + 2) * len(maps)


REFUSED = [
    # (texture set, step, maps, overrides, what the refusal says)
    # sizeLog2 6 (Painter writes 128 on a 256 set): the configuration refuses it (decision 090).
    ("s0", 69, ("user0",), {}, "sizeLog2 6 is outside the recorded texture sizes"),
    ("s1", 73, ("user0",), {}, "no side below 128"),  # 128 x 64: Painter writes 256 x 128
    ("s0", 73, ("basecolor",), {}, "RGB16 and L16F channels only"),
    ("s0", 73, ("Normal_OpenGL",), {}, "RGB16 and L16F channels only"),
    ("s0", 77, ("user0",), {"file_format": "exr", "bit_depth": "16f"}, "PNG 16 and OpenEXR 32f"),
    ("s0", 77, ("user0",), {"bit_depth": 8}, "PNG 16 and OpenEXR 32f"),
    ("s0", 73, ("user0",), {"dithering": True}, "dithering with a resize"),
]


@pytest.mark.parametrize(("texture_set", "step", "maps", "overrides", "reason"), REFUSED)
def test_unfitted_resizes_are_refused_before_writing(
    export_tests: Path,
    tmp_path: Path,
    texture_set: str,
    step: int,
    maps: tuple[str, ...],
    overrides: dict[str, Any],
    reason: str,
) -> None:
    golden = _golden()
    spec = _spec(golden, texture_set, tmp_path / "spec", colours=False)
    out = tmp_path / "out"
    config = _step_config(golden, step, maps, out, texture_set, **overrides)
    result = write_export(export_tests, spec, tmp_path / "spec", config, tmp_path / "run")
    assert result.get("error") == "NotYetSupported", result
    assert reason in result["message"] and "R-090" in result["message"], result["message"]
    assert not out.exists() or not any(out.rglob("*"))


def test_a_mixed_resize_is_refused_before_writing(export_tests: Path, tmp_path: Path) -> None:
    """[9, 7] on a 256 x 256 set doubles the width and halves the height: not recorded."""
    golden = _golden()
    spec = _spec(golden, "s0", tmp_path / "spec", colours=False)
    out = tmp_path / "out"
    result = write_export(
        export_tests,
        spec,
        tmp_path / "spec",
        _probe_config("size-9x7", ("user0",), out, "s0"),
        tmp_path / "run",
    )
    assert result.get("error") == "NotYetSupported", result
    assert "only halving sides or enlarging them by powers of two" in result["message"]
    assert not out.exists() or not any(out.rglob("*"))
