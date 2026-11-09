"""AO_Mixed on UV-islanded texture sets (decision 418), on the owner's machine with the private
oracle store (skipped without it).

The production export (`uzp-export-tests export`, `WriteExport` over the set's coverage) writes
AO_Mixed under `infinite` padding on the authored bevelled cube, whose UV islands leave part of
the tile uncovered. Every covered texel equals Painter's r1 and r2; the uncovered texels are the
export's padding (EXC-013), not compared here.

- `ao-mixed-islands-ocio`: OCIO, the default template's channels and no AO channel, grey A as the
  AO mesh map, PNG 16 and PNG 8 (steps 4 and 6).
- `export-presets-gltf-predefined-ocio` (R-314): OCIO, an L16 AO channel with one fill of the
  transposed hue-grid grey (16-bit) at opacity 1; Painter's AO_Mixed is the R of its
  occlusionRoughnessMetallic file (PNG 16, probe step 49).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from tests.export.encoders_tier0 import (
    OCIO_CONFIG_SHA256,
    _add_template_channels,
    _mesh_of,
    write_export,
)
from tests.export.tier0 import export_spec, needs_store
from tools.parity import coverage as cov
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.decode import decode
from tools.parity.fit.oracle import Golden, load
from tools.parity.recorder.job import Step, export_step
from tools.parity.store.store import locate

SET = "uzp_bevelled_cube"
EXPORT = "substance_painter.export.export_project_textures"


def _golden(stem: str) -> Golden:
    needs_store()
    root = manifest_root(current_envelope()) / "tier0" / "semantics"
    return load(locate(), root / f"{stem}.json")


def _covered(golden: Golden) -> npt.NDArray[np.bool_]:
    mask = cov.coverage(cov.obj_triangles(_mesh_of(golden.manifest), SET), 256, 256)
    assert 0 < int(mask.sum()) < mask.size  # UV islands: part of the tile is uncovered
    return mask


def _spec(golden: Golden, spec_dir: Path) -> dict[str, Any]:
    """The cube's spec as an OCIO project with Painter's substance config and the default
    template's channels (no template was named); the fill keeps its AO source only (the other
    channels' sources are not exported here)."""
    manifest = golden.manifest
    steps = [
        s
        for s in manifest["instruction_sequence"]["steps"]
        if not s["call"].endswith("set_source") or s["args"].get("channel") == "AO"
    ]
    sequence = dict(manifest["instruction_sequence"], steps=steps)
    spec = export_spec(dict(manifest, instruction_sequence=sequence), SET, spec_dir)
    spec["mesh"] = str(_mesh_of(golden.manifest))
    _add_template_channels(spec)
    spec["color_management"] = "ocio"
    spec["config_hash"] = OCIO_CONFIG_SHA256
    return spec


def _ao_mixed(exe: Path, spec: dict[str, Any], args: dict[str, Any], work: Path) -> np.ndarray:
    """The written AO_Mixed file's values (height, width)."""
    config = export_step(Step(0, EXPORT, args)).config(work / "out", [SET])
    result = write_export(exe, spec, work / "spec", config, work / "run")
    assert "error" not in result, result
    [written] = [f for f in result["written"] if "AO_Mixed" in f["relativePath"]]
    values: np.ndarray = decode(Path(written["path"]).read_bytes()).values
    return values.reshape(256, 256, -1)[..., 0]


@pytest.mark.parametrize(("step", "bits"), [(4, 16), (6, 8)])
def test_ao_mixed_without_an_ao_channel_on_islands(
    export_tests: Path, tmp_path: Path, step: int, bits: int
) -> None:
    golden = _golden("ao-mixed-islands-ocio")
    covered = _covered(golden)
    raw = next(s for s in golden.manifest["instruction_sequence"]["steps"] if s["step"] == step)
    args = dict(raw["args"], maps=["virtualMap/AO_Mixed:L"])
    assert args["padding"] == "infinite" and args["bit_depth"] == bits
    ours = _ao_mixed(export_tests, _spec(golden, tmp_path / "spec"), args, tmp_path)
    for recording in ("r1", "r2"):
        theirs = golden.map(recording, f"{SET}/AO_Mixed/step{step}").values[..., 0]
        differ = int(np.count_nonzero((ours != theirs) & covered))
        assert differ == 0, f"step {step} {recording}: {differ} covered texels differ"


def test_ao_mixed_of_an_ocio_fill_on_islands(export_tests: Path, tmp_path: Path) -> None:
    golden = _golden("export-presets-gltf-predefined-ocio")
    covered = _covered(golden)
    args = {
        "maps": ["virtualMap/AO_Mixed:L"],
        "file_format": "png",
        "bit_depth": 16,
        "padding": "infinite",
        "dithering": False,
    }
    ours = _ao_mixed(export_tests, _spec(golden, tmp_path / "spec"), args, tmp_path)
    for recording in ("r1", "r2"):
        [orm] = [k for k in golden.maps(recording) if k.endswith("occlusionRoughnessMetallic.png")]
        theirs = golden.map(recording, orm).values[..., 0]
        differ = int(np.count_nonzero((ours != theirs) & covered))
        assert differ == 0, f"{recording}: {differ} covered texels differ"
