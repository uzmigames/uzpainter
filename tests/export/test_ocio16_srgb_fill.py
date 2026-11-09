"""A 16-bit sRGB colour bitmap on an sRGB8 channel under OCIO (decision 422), on the owner's machine
with the private oracle store (skipped without it).

The admitted controls `ocio16-bitmap-srgb-basecolor` (field-a, whose B holds every 16-bit code)
and its independent cyclic permutations `-field-a-brg` and `-field-a-gbr` fill BaseColor (sRGB8)
of the 256 px plane with one Normal fill at opacity 1, Nearest identity UV, under OCIO with
Painter's substance configuration, and export it as PNG 8, PNG 16 and OpenEXR 32f (steps 13 to
15). The production export (`WriteExport`) equals Painter's r1 and r2 on every texel, through
`OcioSrgb16Code` (src/evaluator/sources.h). The same fill at another opacity is refused: there the
value before the store is not identified.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.export.conftest import REPO_ROOT
from tests.export.encoders_tier0 import OCIO_CONFIG_SHA256, write_export
from tests.export.tier0 import export_spec, needs_store
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.decode import decode
from tools.parity.fit.oracle import Golden, load
from tools.parity.recorder.job import Step, export_step
from tools.parity.store.store import locate

SET = "uzp_plane"
EXPORT = "substance_painter.export.export_project_textures"
CONTROLS = (
    "ocio16-bitmap-srgb-basecolor",
    "ocio16-bitmap-srgb-basecolor-field-a-brg",
    "ocio16-bitmap-srgb-basecolor-field-a-gbr",
)


def _golden(name: str) -> Golden:
    needs_store()
    return load(locate(), manifest_root(current_envelope()) / f"tier0/api-probes/{name}.json")


def _spec(golden: Golden, spec_dir: Path) -> dict[str, Any]:
    """The control as an OCIO project of the default template, whose BaseColor is already the
    sRGB8 the control's `edit_channel` sets; its bitmap's `set_color_space` sRGB is written into the
    spec (those steps and the colour-space read are left out)."""
    sequence = golden.manifest["instruction_sequence"]
    steps = []
    for step in sequence["steps"]:
        if step["call"].endswith("Stack.edit_channel"):
            assert step["args"] == {"channel": "BaseColor", "format": "sRGB8"}
            continue
        if step["call"].endswith("SourceBitmap.set_color_space"):
            assert step["args"]["color_space"] == "sRGB"
            continue
        if step["call"].endswith("get_color_space"):
            continue
        steps.append(step)
    manifest = dict(golden.manifest, instruction_sequence=dict(sequence, steps=steps))
    spec = export_spec(manifest, SET, spec_dir)
    [layer] = spec["layers"]
    layer["sources"]["BaseColor"]["color_space"] = "sRGB"  # the left-out setter
    spec.update(
        template="default",
        mesh=str(
            REPO_ROOT / next(i["path"] for i in golden.manifest["inputs"] if i["kind"] == "mesh")
        ),
        color_management="ocio",
        config_hash=OCIO_CONFIG_SHA256,
    )
    return spec


def _export(exe: Path, spec: dict[str, Any], step: dict[str, Any], work: Path) -> dict[str, Any]:
    config = export_step(Step(0, EXPORT, step["args"])).config(work / "out", [SET])
    return write_export(exe, spec, work.parent / "spec", config, work / "run")


@pytest.mark.parametrize("name", CONTROLS)
def test_ocio16_srgb_fill_equals_painter(export_tests: Path, tmp_path: Path, name: str) -> None:
    golden = _golden(name)
    spec = _spec(golden, tmp_path / "spec")
    steps = [s for s in golden.manifest["instruction_sequence"]["steps"] if s["call"] == EXPORT]
    assert [s["step"] for s in steps] == [13, 14, 15]
    for step in steps:
        result = _export(export_tests, spec, step, tmp_path / f"step{step['step']}")
        assert "error" not in result, result
        [written] = result["written"]
        ours = np.asarray(decode(Path(written["path"]).read_bytes()).values)
        for recording in ("r1", "r2"):
            theirs = np.asarray(golden.map(recording, f"{SET}/basecolor/step{step['step']}").values)
            assert ours.shape == theirs.shape, (name, step["step"])
            differ = int(np.count_nonzero(ours != theirs))
            assert differ == 0, f"{name} step {step['step']} {recording}: {differ} samples differ"


def test_ocio16_srgb_fill_at_another_opacity_is_refused(export_tests: Path, tmp_path: Path) -> None:
    golden = _golden(CONTROLS[0])
    spec = _spec(golden, tmp_path / "spec")
    [layer] = spec["layers"]
    layer["blending"]["BaseColor"] = {**layer["blending"]["BaseColor"], "opacity": 0.5}
    step = next(s for s in golden.manifest["instruction_sequence"]["steps"] if s["step"] == 13)
    result = _export(export_tests, spec, step, tmp_path / "step13")
    assert "error" in result, result
    assert "one fill of its stack" in str(result) and "decision 422" in str(result), result
