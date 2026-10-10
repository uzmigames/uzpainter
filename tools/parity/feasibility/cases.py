"""The evaluated cases of the study and their public manifests (`golden-public.json`).

One golden per (asset, fixture, parameter set): the evaluated subset of the
`05-procedural-content.md` §6 matrix is {sphere, rounded cube} x {1024} x the parameter sets
below x the seeds the sets name. Each instruction sequence (UzmiGames-authored, documented API
only) creates a throwaway project on the fixture mesh, assigns the six authored mesh maps, and:

- generator cases: a black SpecularRoughness fill under a white one whose black mask holds
  the generator, the channel set to L16, so the exported SpecularRoughness map is the
  generator's mask output at 16 bits;
- smart-material cases: the smart material inserted above a neutral Height fill, then
  BaseColor, SpecularRoughness, BaseMetalness, Height and Normal (the channels of Painter
  12.1's default project template) exported at 16 bits.

Parameter names come from the documented `Property` API (05 §3: names, ranges and labels are
public parameter semantics); the values are authored here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.parity.feasibility.fixtures import MAP_NAMES, fixture_files
from tools.parity.recorder.job import sha256_file
from tools.parity.schemas import REPO_ROOT

PAINTER_BUILD_ID = "12.1.0+js-api.1.1.20"
RESOLUTION = 1024
FIXTURE_DIR = REPO_ROOT / "parity" / "fixtures" / "feasibility"
MANIFEST_DIR = REPO_ROOT / "parity" / "manifests" / "phase0" / "procedural-feasibility"
GOLDEN_PREFIX = "phase0/procedural-feasibility"
FIXTURE_NAMES = ("sphere", "rounded-cube")

MESH_MAP_USAGE = {
    "position": "Position",
    "world_space_normal": "WorldSpaceNormal",
    "normal": "Normal",
    "ambient_occlusion": "AO",
    "curvature": "Curvature",
    "thickness": "Thickness",
}

LS = "substance_painter.layerstack."


@dataclass(frozen=True)
class Asset:
    asset_id: str  # UzPainter family id used in golden ids
    painter_name: str  # compatibility alias (05 §3): the resource's name in Painter
    usage: str  # resource.Usage member
    family: str


ASSETS = {
    "position": Asset("position", "Position", "GENERATOR", "mesh-map generators"),
    "metal-edge-wear": Asset(
        "metal-edge-wear", "Metal Edge Wear", "GENERATOR", "mesh-map generators"
    ),
    "leather-damaged": Asset(
        "leather-damaged", "Leather Damaged", "SMART_MATERIAL", "smart materials"
    ),
}

SMART_MATERIAL_MAPS = (
    "documentMap/basecolor:RGB",
    "documentMap/specularroughness:L",
    "documentMap/basemetalness:L",
    "documentMap/height:L",
    "documentMap/normal:RGB",
)


@dataclass(frozen=True)
class Case:
    asset: Asset
    fixture: str
    parameter_set: str
    parameters: tuple[tuple[str, Any], ...] = field(default=())

    @property
    def golden_id(self) -> str:
        return f"{GOLDEN_PREFIX}/{self.asset.asset_id}/{self.fixture}/{self.parameter_set}"

    @property
    def manifest_path(self) -> Path:
        name = f"{self.asset.asset_id}--{self.fixture}--{self.parameter_set}.json"
        return MANIFEST_DIR / name


# Parameter sets beyond the defaults: authored values at documented range ends, and another seed.
PARAMETER_SETS: dict[str, dict[str, tuple[tuple[str, Any], ...]]] = {
    "position": {
        # Right-to-left gradient alone, inverted: the axis switch and the invert toggle.
        "boundary-a": (
            ("position_direction_topbottom_opacity", 0.0),
            ("position_direction_rightleft_opacity", 1.0),
            ("position_invert", 1),
        ),
        # Top-to-bottom plus front-to-back (default Linear Dodge), contrast and balance at max.
        "boundary-b": (
            ("position_direction_frontback_opacity", 1.0),
            ("position_contrast", 1.0),
            ("position_balance", 1.0),
        ),
    },
    "metal-edge-wear": {
        "seed-1": (("$randomseed", 1),),
        # No grunge: the edge (curvature) term alone, at full wear level and contrast.
        "boundary-a": (
            ("Grunge_Amount", 0.0),
            ("Wear_Level", 1.0),
            ("Wear_Contrast", 1.0),
        ),
        # No curvature weight: the grunge term alone, at full grunge amount.
        "boundary-b": (
            ("Curvature_Weight", 0.0),
            ("Grunge_Amount", 1.0),
        ),
    },
    "leather-damaged": {},
}


def cases() -> list[Case]:
    found: list[Case] = []
    for asset_id, asset in ASSETS.items():
        sets = {"defaults": (), **PARAMETER_SETS[asset_id]}
        for fixture in FIXTURE_NAMES:
            for set_name, parameters in sets.items():
                found.append(Case(asset, fixture, set_name, parameters))
    return found


def relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def fixture_inputs(fixture: str) -> list[dict[str, Any]]:
    files = fixture_files(FIXTURE_DIR)
    provenance = {"origin": "uzmigames_authored", "licence": "Apache-2.0"}
    mesh = files[f"{fixture}/mesh"]
    inputs = [
        {
            "input_id": fixture,
            "kind": "mesh",
            "path": relative(mesh),
            "sha256": sha256_file(mesh),
            "provenance": provenance,
        }
    ]
    for map_name in MAP_NAMES:
        path = files[f"{fixture}/{map_name}"]
        inputs.append(
            {
                "input_id": f"{fixture}-{map_name.replace('_', '-')}",
                "kind": "image",
                "path": relative(path),
                "sha256": sha256_file(path),
                "provenance": provenance,
            }
        )
    return inputs


class Steps:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []

    def add(self, call: str, **args: Any) -> int:
        number = len(self.steps) + 1
        self.steps.append({"step": number, "call": call, "args": args})
        return number


def instruction_steps(case: Case) -> list[dict[str, Any]]:
    steps = Steps()
    steps.add(
        "substance_painter.project.create",
        mesh=case.fixture,
        normal_map_format="OpenGL",
        default_texture_resolution=RESOLUTION,
    )
    imported = {
        map_name: steps.add(
            "substance_painter.resource.import_project_resource",
            input=f"{case.fixture}-{map_name.replace('_', '-')}",
            usage="TEXTURE",
        )
        for map_name in MAP_NAMES
    }
    for map_name, step in imported.items():
        steps.add(
            "substance_painter.textureset.TextureSet.set_mesh_map_resource",
            usage=MESH_MAP_USAGE[map_name],
            resource_step=step,
        )
    resource = {"resource_name": case.asset.painter_name, "resource_usage": case.asset.usage}
    if case.asset.usage == "GENERATOR":
        steps.add(
            "substance_painter.textureset.Stack.edit_channel",
            channel="SpecularRoughness",
            format="L16",
        )
        base = steps.add(LS + "insert_fill", position="top")
        steps.add(
            LS + "FillLayerNode.active_channels", node_step=base, channels=["SpecularRoughness"]
        )
        steps.add(
            LS + "FillLayerNode.set_source",
            node_step=base,
            channel="SpecularRoughness",
            color=[0.0, 0.0, 0.0],
            color_space="Raw",
        )
        top = steps.add(LS + "insert_fill", above_step=base)
        steps.add(
            LS + "FillLayerNode.active_channels", node_step=top, channels=["SpecularRoughness"]
        )
        steps.add(
            LS + "FillLayerNode.set_source",
            node_step=top,
            channel="SpecularRoughness",
            color=[1.0, 1.0, 1.0],
            color_space="Raw",
        )
        steps.add(LS + "LayerNode.add_mask", node_step=top, background="Black")
        generator = steps.add(
            LS + "insert_generator_effect", inside_step=top, stack="Mask", **resource
        )
        for name, value in case.parameters:
            steps.add(
                "substance_painter.source.SourceSubstance.set_parameters",
                node_step=generator,
                parameter=name,
                value=value,
            )
        maps = ["documentMap/specularroughness:L"]
    else:
        base = steps.add(LS + "insert_fill", position="top")
        steps.add(LS + "FillLayerNode.active_channels", node_step=base, channels=["Height"])
        steps.add(
            LS + "FillLayerNode.set_source",
            node_step=base,
            channel="Height",
            color=[0.0, 0.0, 0.0],
            color_space="Raw",
        )
        steps.add(LS + "insert_smart_material", above_step=base, **resource)
        maps = list(SMART_MATERIAL_MAPS)
    steps.add(
        "substance_painter.export.export_project_textures",
        maps=maps,
        file_format="png",
        bit_depth=16,
        padding="passthrough",
        dithering=False,
    )
    return steps.steps


def manifest(case: Case) -> dict[str, Any]:
    parameters = ", ".join(f"{name} = {value}" for name, value in case.parameters) or "defaults"
    return {
        "schema": "uzpainter/parity/golden-public/1",
        "record_class": "public_manifest",
        "golden_id": case.golden_id,
        "tier": "2a",
        "domain": f"procedural_asset/{case.asset.asset_id}",
        "description": (
            f"Procedural feasibility (P0-FEAS-PROC): Painter's {case.asset.painter_name} "
            f"({case.asset.family}) on the authored {case.fixture} with its six authored mesh "
            f"maps, texture set {RESOLUTION} px, parameters: {parameters}. Exported at 16 bits; "
            "recorded twice (same session; after save and reopen)."
        ),
        "inputs": fixture_inputs(case.fixture),
        "instruction_sequence": {
            "author": "UzmiGames",
            "interface": "substance_painter_documented_python_api",
            "steps": instruction_steps(case),
        },
        "applied_settings": [
            {"name": "project.normal_map_format", "value": "OpenGL", "applied_by": "recorder_api"},
            {
                "name": "texture_set.resolution",
                "value": RESOLUTION,
                "unit": "px",
                "applied_by": "recorder_api",
            },
            {"name": "export.file_format", "value": "png", "applied_by": "recorder_api"},
            {"name": "export.bit_depth", "value": 16, "applied_by": "recorder_api"},
            {"name": "export.padding", "value": "passthrough", "applied_by": "recorder_api"},
            {"name": "export.dithering", "value": False, "applied_by": "recorder_api"},
        ],
        "expectations": [],
        "software": {
            "painter": {
                "product": "Adobe Substance 3D Painter",
                "version": "12.1.0",
                "build_id": PAINTER_BUILD_ID,
            },
            "uzpainter_build_hash": None,
        },
        "private_records": [],
    }


def write_manifests(selected: list[Case] | None = None) -> list[Path]:
    """Write each case's manifest; an existing manifest keeps its admitted private records."""
    written: list[Path] = []
    for case in selected or cases():
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
