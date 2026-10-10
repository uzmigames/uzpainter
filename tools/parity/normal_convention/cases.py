"""Goldens of the normal-convention fixture and their public manifests (P0-NORMAL).

Each golden is one Painter project created from a low mesh of `fixtures.py`, its Normal mesh map
baked from the matching high mesh through the documented baking API, and the baked map exported
at 16 bits (`meshMap/normal_base`). The recorder records it twice (same session; after save and
reopen). The project settings vary per golden:

| Golden | Pair | Normal map format | Tangent space |
|---|---|---|---|
| `plane-dome/opengl` | plane-dome | OpenGL | project default |
| `plane-dome/directx` | plane-dome | DirectX | project default |
| `hemisphere/per-fragment` | hemisphere | OpenGL | `PerFragment` |
| `hemisphere/per-vertex` | hemisphere | OpenGL | `PerVertex` |
| `hemisphere/project-default` | hemisphere | OpenGL | project default (not set) |

The bake backend Painter uses cannot be read or set through the documented API, so every
manifest lists it under `uncontrolled_settings`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.parity.normal_convention.fixtures import (
    FIXTURE_DIR_NAME,
    OUTPUT_SIZE_LOG2,
    RESOLUTION,
    fixture_files,
    pairs,
)
from tools.parity.recorder.job import sha256_file
from tools.parity.schemas import REPO_ROOT

FIXTURE_DIR = REPO_ROOT / "parity" / "fixtures" / FIXTURE_DIR_NAME
MANIFEST_DIR = REPO_ROOT / "parity" / "manifests" / "phase0" / "normal-convention"
PAINTER = {"product": "Adobe Substance 3D Painter", "version": "12.1.0"}
PAINTER_BUILD_ID = "12.1.0+js-api.1.1.20"
BAKED_MAP = "normal_base"
UNCONTROLLED = ["preferences.bake_backend"]
BAKING_SET = "substance_painter.baking.BakingParameters.set"


@dataclass(frozen=True)
class Case:
    pair: str
    variant: str
    normal_map_format: str
    tangent_space_mode: str | None

    @property
    def golden_id(self) -> str:
        return f"phase0/normal-convention/{self.pair}/{self.variant}"

    @property
    def manifest_path(self) -> Path:
        return MANIFEST_DIR / f"{self.pair}--{self.variant}.json"


CASES = (
    Case("plane-dome", "opengl", "OpenGL", None),
    Case("plane-dome", "directx", "DirectX", None),
    Case("hemisphere", "per-fragment", "OpenGL", "PerFragment"),
    Case("hemisphere", "per-vertex", "OpenGL", "PerVertex"),
    Case("hemisphere", "project-default", "OpenGL", None),
)


def relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def inputs(case: Case) -> list[dict[str, Any]]:
    files = fixture_files(FIXTURE_DIR)
    provenance = {"origin": "uzmigames_authored", "licence": "Apache-2.0"}
    return [
        {
            "input_id": f"{case.pair}-{part}",
            "kind": "mesh",
            "path": relative(files[f"{case.pair}/{part}"]),
            "sha256": sha256_file(files[f"{case.pair}/{part}"]),
            "provenance": provenance,
        }
        for part in ("low", "high")
    ]


def instruction_steps(case: Case) -> list[dict[str, Any]]:
    create: dict[str, Any] = {
        "mesh": f"{case.pair}-low",
        "normal_map_format": case.normal_map_format,
        "default_texture_resolution": RESOLUTION,
    }
    if case.tangent_space_mode is not None:
        create["tangent_space_mode"] = case.tangent_space_mode
    common: dict[str, Any] = {"OutputSize": [OUTPUT_SIZE_LOG2, OUTPUT_SIZE_LOG2]}
    common.update(pairs()[case.pair].common)
    calls: list[tuple[str, dict[str, Any]]] = [("substance_painter.project.create", create)]
    calls += [(BAKING_SET, {"parameter": key, "value": value}) for key, value in common.items()]
    calls += [
        (BAKING_SET, {"parameter": "HipolyMesh", "input": f"{case.pair}-high"}),
        ("substance_painter.baking.BakingParameters.set_enabled_bakers", {"usages": ["Normal"]}),
        ("substance_painter.baking.bake_async", {}),
        (
            "substance_painter.export.export_project_textures",
            {
                "maps": [f"meshMap/{BAKED_MAP}:RGB"],
                "file_format": "png",
                "bit_depth": 16,
                "padding": "passthrough",
                "dithering": False,
            },
        ),
    ]
    return [{"step": i, "call": call, "args": args} for i, (call, args) in enumerate(calls, 1)]


def expectations(case: Case) -> list[dict[str, Any]]:
    """Public expectation of the green channel's direction (plane-dome goldens only)."""
    if case.pair != "plane-dome":
        return []
    sign = 1 if case.normal_map_format == "OpenGL" else -1
    return [
        {
            "expectation_id": "green-follows-plus-v",
            "quantity": (
                "Sign of (green - 1/2) on texels whose high-poly normal leans towards +v "
                "(the cap triangles on the -Z side of the plane)"
            ),
            "value": sign,
            "derivation": "public_documentation",
            "source_id": "A-PYDOC",
            "locator": (
                "substance_painter.project.NormalMapFormat: OpenGL and DirectX tangent space "
                "(green +v for OpenGL, -v for DirectX)"
            ),
        }
    ]


def manifest(case: Case) -> dict[str, Any]:
    tangent = case.tangent_space_mode or "the project default (not set)"
    applied: list[dict[str, Any]] = [
        {
            "name": "project.normal_map_format",
            "value": case.normal_map_format,
            "applied_by": "recorder_api",
        },
    ]
    if case.tangent_space_mode is not None:
        applied.append(
            {
                "name": "project.tangent_space_mode",
                "value": case.tangent_space_mode,
                "applied_by": "recorder_api",
            }
        )
    applied += [
        {
            "name": "texture_set.resolution",
            "value": RESOLUTION,
            "unit": "px",
            "applied_by": "recorder_api",
        },
        {
            "name": "baking.common.OutputSize",
            "value": OUTPUT_SIZE_LOG2,
            "unit": "log2 px",
            "applied_by": "recorder_api",
        },
        *(
            {"name": f"baking.common.{key}", "value": value, "applied_by": "recorder_api"}
            for key, value in pairs()[case.pair].common.items()
        ),
        {"name": "baking.enabled_bakers", "value": "Normal", "applied_by": "recorder_api"},
        {"name": "export.file_format", "value": "png", "applied_by": "recorder_api"},
        {"name": "export.bit_depth", "value": 16, "applied_by": "recorder_api"},
        {"name": "export.padding", "value": "passthrough", "applied_by": "recorder_api"},
        {"name": "export.dithering", "value": False, "applied_by": "recorder_api"},
    ]
    return {
        "schema": "uzpainter/parity/golden-public/1",
        "record_class": "public_manifest",
        "golden_id": case.golden_id,
        "tier": "2b",
        "domain": "bake_map/normal",
        "description": (
            f"Normal-convention fixture (P0-NORMAL): the {case.pair} low/high pair, Normal mesh "
            f"map baked by Painter at {RESOLUTION} px with the {case.normal_map_format} normal "
            f"map format and tangent space {tangent}, other baking parameters at their "
            "defaults; the baked map exported at 16 bits; recorded twice (same session; after "
            "save and reopen)."
        ),
        "inputs": inputs(case),
        "instruction_sequence": {
            "author": "UzmiGames",
            "interface": "substance_painter_documented_python_api",
            "steps": instruction_steps(case),
        },
        "applied_settings": applied,
        "uncontrolled_settings": list(UNCONTROLLED),
        "expectations": expectations(case),
        "software": {
            "painter": {**PAINTER, "build_id": PAINTER_BUILD_ID},
            "uzpainter_build_hash": None,
        },
        "private_records": [],
    }


def write_manifests() -> list[Path]:
    """Write each case's manifest; an existing manifest keeps its admitted private records."""
    written: list[Path] = []
    for case in CASES:
        document = manifest(case)
        path = case.manifest_path
        if path.exists():
            previous = json.loads(path.read_text(encoding="utf-8"))
            if (
                previous["instruction_sequence"] != document["instruction_sequence"]
                and previous["private_records"]
            ):
                raise ValueError(f"{path}: instruction sequence changed after recording")
            document["private_records"] = previous["private_records"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
        written.append(path)
    return written
