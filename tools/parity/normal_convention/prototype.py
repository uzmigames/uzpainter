"""Run the tangent-frame prototype `uzp-normal-prototype.exe` (`src/prototype/`) on the fixtures.

The executable is built by `zig build normal-prototype`; `build_prototype` builds it into a given
prefix. `run_prototype` bakes one pair and returns its maps as decoded 16-bit code values.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.feasibility import png
from tools.parity.normal_convention.fixtures import RESOLUTION, fixture_files
from tools.parity.schemas import REPO_ROOT

Codes = npt.NDArray[np.int64]

EXECUTABLE = "uzp-normal-prototype.exe"
MODES = ("PerVertex", "PerFragment")
TRANSFORMS = ("inverse", "projection")
FORMATS = ("opengl", "directx")
# Ray distances of the prototype (file units): the frontal distance reaches every high triangle
# of the pair and no other surface lies within reach, so the hit is the analytic one.
DISTANCES = {"plane-dome": (0.5, 0.01), "hemisphere": (0.02, 0.02)}


class PrototypeError(RuntimeError):
    """The prototype could not be built or run."""


def build_prototype(prefix: Path) -> Path:
    """`zig build normal-prototype -Doptimize=ReleaseFast --prefix <prefix>`; returns the exe."""
    zig = shutil.which("zig")
    if zig is None:
        raise PrototypeError("zig is not on PATH; uzp-normal-prototype.exe cannot be built")
    result = subprocess.run(
        [zig, "build", "normal-prototype", "-Doptimize=ReleaseFast", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    if result.returncode != 0:
        raise PrototypeError(result.stdout + result.stderr)
    return prefix / "bin" / EXECUTABLE


@dataclass(frozen=True)
class PrototypeBake:
    """One pair baked by the prototype: maps by name, plus face ids and its summary."""

    maps: dict[str, Codes]  # "world", "<mode>-<transform>-<format>"
    low_face: Codes  # (h, w), -1 outside the UV triangles
    high_face: Codes  # (h, w), -1 where no ray hit
    summary: dict[str, Any]


def map_names() -> list[str]:
    return [f"{m}-{t}-{f}" for m in MODES for t in TRANSFORMS for f in FORMATS]


def run_prototype(executable: Path, pair: str, fixture_dir: Path, out_dir: Path) -> PrototypeBake:
    files = fixture_files(fixture_dir)
    height, depth = DISTANCES[pair]
    command = [
        str(executable),
        "--low",
        str(files[f"{pair}/low"]),
        "--high",
        str(files[f"{pair}/high"]),
        "--size",
        str(RESOLUTION),
        "--max-height",
        repr(height),
        "--max-depth",
        repr(depth),
        "--out-dir",
        str(out_dir),
        "--name",
        pair,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
    if result.returncode != 0:
        raise PrototypeError(f"{executable.name} {pair}: {result.stdout}{result.stderr}")
    maps = {"world": png.read(out_dir / f"{pair}-world.png").astype(np.int64)}
    for name in map_names():
        maps[name] = png.read(out_dir / f"{pair}-{name}.png").astype(np.int64)
    faces = png.read(out_dir / f"{pair}-faces.png").astype(np.int64)
    summary = json.loads((out_dir / f"{pair}-summary.json").read_text(encoding="utf-8"))
    return PrototypeBake(maps, faces[..., 0] - 1, faces[..., 1] - 1, summary)
