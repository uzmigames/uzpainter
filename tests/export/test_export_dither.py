"""Export dithering at PNG 8 against recording R-090 P3 (`export-dither`; task
phase3.2_unreal-ue56-packed-preset item 2.9, decision 349), on the owner's machine with the private
oracle store (skipped without it).

- Dithering changes nothing at PNG 8 on an RGB16 channel (User0) and an sRGB8 BaseColor: every
  texel of r1 and r2, under infinite and passthrough padding, on the four sets. UzPainter's files
  with dithering on equal Painter's.
- On a float channel (User1 L16F, User2 RGB32F, Height L16F) and a virtual normal it changes up to
  one code, deterministically but not fitted, and in OpenEXR no recording compares it with off:
  each is refused (NotYetSupported) before anything is written.
"""

from __future__ import annotations

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

# PNG 8 with dithering on: infinite padding (100) and passthrough padding (110).
DITHER_STEPS = (100, 110)
UNCHANGED = ("user0", "basecolor")


def _golden() -> Golden:
    needs_store()
    root = manifest_root(current_envelope()) / "tier0" / "semantics"
    return load(locate(), root / "export-dither.json")


def _spec(
    golden: Golden, texture_set: str, spec_dir: Path, colours: bool = False
) -> dict[str, Any]:
    """The evaluator spec of `texture_set`; with `colours`, its BaseColor alone with the working
    colours the facade stores, otherwise its User0 alone (the other channels' sources dropped:
    they are not exported here)."""
    manifest = golden.manifest
    if colours:
        manifest = working_colours(manifest)
    else:
        steps = [
            s
            for s in manifest["instruction_sequence"]["steps"]
            if not s["call"].endswith("set_source") or s["args"].get("channel") in (None, "User0")
        ]
        manifest = dict(
            manifest, instruction_sequence=dict(manifest["instruction_sequence"], steps=steps)
        )
    spec = export_spec(manifest, texture_set, spec_dir)
    spec["mesh"] = str(_mesh_of(golden.manifest))
    _add_template_channels(spec)
    return spec


def _config(
    golden: Golden, step: int, maps: tuple[str, ...], out: Path, texture_set: str
) -> dict[str, Any]:
    raw = next(s for s in golden.manifest["instruction_sequence"]["steps"] if s["step"] == step)
    args = dict(raw["args"])
    args["maps"] = [m for m in args["maps"] if m.split("/")[1].split(":")[0] in maps]
    return export_step(Step(step, raw["call"], args)).config(out, [texture_set])


@pytest.mark.parametrize("texture_set", ["s0", "s1", "s2", "s3"])
def test_dithering_at_png8_leaves_rgb16_and_srgb8_unchanged(
    export_tests: Path, tmp_path: Path, texture_set: str
) -> None:
    golden = _golden()
    compared = 0
    for step, map_name in ((s, m) for s in DITHER_STEPS for m in UNCHANGED):
        work = tmp_path / f"{step}-{map_name}"
        spec = _spec(golden, texture_set, work / "spec", colours=map_name == "basecolor")
        config = _config(golden, step, (map_name,), work / "out", texture_set)
        result = write_export(export_tests, spec, work / "spec", config, work / "run")
        assert "error" not in result, result
        for f in result["written"]:
            name = f["relativePath"].rsplit(".", 1)[0].removeprefix(f"{texture_set}_")
            ours = decode(Path(f["path"]).read_bytes()).values
            for recording in ("r1", "r2"):
                theirs = golden.map(recording, f"{texture_set}/{name}/step{step}").values
                assert ours.shape == theirs.shape
                differ = int(np.count_nonzero(ours != theirs))
                assert differ == 0, (
                    f"{texture_set} {name} step {step} {recording}: {differ} values differ"
                )
            compared += 1
    assert compared == len(DITHER_STEPS) * len(UNCHANGED)


REFUSED = [
    (100, "user1", "dithering at PNG 8 bits of a source other than"),
    (100, "user2", "dithering at PNG 8 bits of a source other than"),
    (100, "height", "dithering at PNG 8 bits of a source other than"),
    (100, "Normal_OpenGL", "dithering at PNG 8 bits of a source other than"),
    (108, "user0", "dithering in OpenEXR"),
]


@pytest.mark.parametrize(("step", "map_name", "reason"), REFUSED)
def test_unfitted_dithering_is_refused_before_writing(
    export_tests: Path, tmp_path: Path, step: int, map_name: str, reason: str
) -> None:
    golden = _golden()
    spec = _spec(golden, "s0", tmp_path / "spec")
    out = tmp_path / "out"
    config = _config(golden, step, (map_name,), out, "s0")
    result = write_export(export_tests, spec, tmp_path / "spec", config, tmp_path / "run")
    assert result.get("error") == "NotYetSupported", result
    assert reason in result["message"] and "decisions 103 and 349" in result["message"]
    assert not out.exists() or not any(out.rglob("*"))
