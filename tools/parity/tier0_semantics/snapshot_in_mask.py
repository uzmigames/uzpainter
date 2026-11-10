"""Tier 0 probe of Painter's mask-stack arithmetic over snapshot-served procedurals
(`phase3.3_procedural-families` item 2.15, decision 429 §5).

One golden on the destination of the 2.13/2.14 captures (`tests/python/capture_grunge_snapshots.py`,
store record `grunge-snapshots-project`): the authored plane at 256 px, OpenGL, Legacy, with the
same four authored 16-bit fixture bitmaps bound as its AO, Curvature, Position and World Space
Normal mesh maps. Each case is a white Raw fill on its own L32F User channel over a black Raw base
fill, under a mask whose effects use the grunges and generators that project holds snapshots of,
at their captured parameters, with the blend modes and opacities the Assets3D recipes give them
(hat: Normal 0.31, Multiply 1, LinearDodge 0.14, Normal 0.91, a bitmap Subtract 0.9). The User
channel therefore holds the mask value: 0 (1 - m) + 1 m. Exported as OpenEXR 32f, passthrough,
no dithering; recorded twice (r1; r2 after save and reopen).

No Painter value is written here. `python -m tools.parity.tier0_semantics.snapshot_in_mask` writes
the request under the current envelope's `requests/tier0/semantics/`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.parity.envelope.registry import current_envelope, envelope_directory
from tools.parity.proc_generators.requests import GENERATOR_URLS, LS, Steps
from tools.parity.proc_grunges.requests import GRUNGE_URLS
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT, sha256_file
from tools.parity.schemas import REPO_ROOT

NAME = "snapshot-in-mask"
GOLDEN_ID = f"tier0/semantics/{NAME}"
DOMAIN = "tier0/semantics/snapshot-in-mask"
RESOLUTION = 256
PLANE = "parity/fixtures/meshes/plane.obj"
BITMAPS = "parity/fixtures/tier0-semantics/bitmaps"
# The destination's mesh maps (capture_grunge_snapshots.MESH_MAPS): usage -> input id.
MESH_MAPS = {
    "AO": "grey-a",
    "Curvature": "half-steps-grey",
    "Position": "field-a",
    "WorldSpaceNormal": "field-b",
}
SEED = "$randomseed"


@dataclass(frozen=True)
class Effect:
    """One mask effect, bottom-up: a grunge fill (`grunge`), a generator (`generator`) or the
    bitmap `grey-a` as a Data fill (`bitmap`), each with its mono blend mode and opacity."""

    kind: str
    asset: str = ""
    parameters: tuple[tuple[str, Any], ...] = ()
    mode: str = "Normal"
    opacity: float = 1.0


@dataclass(frozen=True)
class Case:
    case_id: str
    background: str
    effects: tuple[Effect, ...]


def rock(mode: str = "Normal", opacity: float = 1.0) -> Effect:
    return Effect("grunge", "rock", (), mode, opacity)


def dirt_a(seed: int, mode: str = "Normal", opacity: float = 1.0) -> Effect:
    return Effect("grunge", "dirt-a", ((SEED, seed),), mode, opacity)


# Each grunge and generator at exactly a parameter set the 2.13/2.14 capture holds.
CASES: tuple[Case, ...] = (
    Case("grunge-normal-1", "Black", (rock(),)),
    Case("grunge-normal-031", "Black", (dirt_a(1, "Normal", 0.31),)),
    Case("grunge-multiply", "Black", (dirt_a(1), rock("Multiply"))),
    Case(
        "grunge-lineardodge-014",
        "Black",
        (dirt_a(2), Effect("grunge", "dirt-large", (), "LinearDodge", 0.14)),
    ),
    Case(
        "generator-normal-091",
        "Black",
        (Effect("generator", "Mask Builder - Legacy", (), "Normal", 0.91),),
    ),
    Case(
        "generator-then-multiply",
        "Black",
        (Effect("generator", "Metal Edge Wear"), rock("Multiply")),
    ),
    Case(
        "generator-then-subtract",
        "Black",
        (Effect("generator", "Dirt"), Effect("bitmap", "grey-a", (), "Subtract", 0.9)),
    ),
    Case(
        "generator-over-white-05",
        "White",
        (Effect("generator", "Dirt", ((SEED, 2),), "Normal", 0.5),),
    ),
)
# The separating golden (2026-11-10): each source of `CASES` alone, Normal at opacity 1 in a
# black mask, recorded in a fresh Painter session, so the mask holds the source itself.
SOURCES_NAME = "snapshot-in-mask-sources"
SOURCE_CASES: tuple[Case, ...] = (
    Case("dirt-a-seed-1", "Black", (dirt_a(1),)),
    Case("dirt-a-seed-2", "Black", (dirt_a(2),)),
    Case("dirt-large", "Black", (Effect("grunge", "dirt-large"),)),
    Case("rock", "Black", (rock(),)),
    Case("dirt", "Black", (Effect("generator", "Dirt"),)),
    Case("dirt-seed-2", "Black", (Effect("generator", "Dirt", ((SEED, 2),)),)),
    Case("metal-edge-wear", "Black", (Effect("generator", "Metal Edge Wear"),)),
    Case("mask-builder-legacy", "Black", (Effect("generator", "Mask Builder - Legacy"),)),
)
GOLDENS: dict[str, tuple[Case, ...]] = {NAME: CASES, SOURCES_NAME: SOURCE_CASES}


def user(k: int) -> str:
    return f"User{k}"


def instruction_steps(cases: tuple[Case, ...] = CASES) -> list[dict[str, Any]]:
    steps = Steps()
    steps.add(
        ps.CREATE, mesh="plane", normal_map_format="OpenGL", default_texture_resolution=RESOLUTION
    )
    imported: dict[str, int] = {}
    for usage, input_id in MESH_MAPS.items():
        imported[input_id] = steps.add(ps.IMPORT_RESOURCE, input=input_id, usage="TEXTURE")
        steps.add(ps.SET_MESH_MAP, usage=usage, resource_step=imported[input_id])
    channels = [user(k) for k in range(len(cases))]
    for channel in channels:
        steps.add(ps.ADD_CHANNEL, channel=channel, format="L32F")
    base = steps.add(LS + "insert_fill", position="top")
    steps.add(LS + "FillLayerNode.active_channels", node_step=base, channels=channels)
    for channel in channels:
        steps.add(
            LS + "FillLayerNode.set_source",
            node_step=base,
            channel=channel,
            color=[0.0, 0.0, 0.0],
            color_space="Raw",
        )
    below = base
    for k, case in enumerate(cases):
        fill = steps.add(LS + "insert_fill", above_step=below)
        below = fill
        steps.add(LS + "FillLayerNode.active_channels", node_step=fill, channels=[user(k)])
        steps.add(
            LS + "FillLayerNode.set_source",
            node_step=fill,
            channel=user(k),
            color=[1.0, 1.0, 1.0],
            color_space="Raw",
        )
        steps.add(ps.ADD_MASK, node_step=fill, background=case.background)
        under: int | None = None
        for effect in case.effects:
            place: dict[str, Any] = (
                {"inside_step": fill, "stack": "Mask"} if under is None else {"above_step": under}
            )
            if effect.kind == "generator":
                node = steps.add(
                    ps.INSERT_GENERATOR, **place, resource=GENERATOR_URLS[effect.asset]
                )
                for name, value in effect.parameters:
                    steps.add(ps.SET_PARAMETERS, node_step=node, parameter=name, value=value)
            else:
                node = steps.add(LS + "insert_fill", **place)
                if effect.kind == "grunge":
                    steps.add(
                        ps.SET_EFFECT_SOURCE,
                        node_step=node,
                        channel=None,
                        resource=GRUNGE_URLS[effect.asset],
                    )
                    for name, value in effect.parameters:
                        steps.add(
                            ps.SET_PARAMETERS,
                            node_step=node,
                            channel=None,
                            parameter=name,
                            value=value,
                        )
                else:
                    steps.add(
                        ps.SET_EFFECT_SOURCE,
                        node_step=node,
                        channel=None,
                        resource_step=imported[effect.asset],
                    )
            if effect.mode != "Normal":
                steps.add(
                    ps.SET_BLENDING_MODE, node_step=node, channel=None, blending_mode=effect.mode
                )
            if effect.opacity != 1.0:
                steps.add(ps.SET_OPACITY, node_step=node, channel=None, opacity=effect.opacity)
            under = node
    maps = [f"documentMap/user{k}:L" for k in range(len(cases))]
    steps.add(
        EXPORT,
        maps=maps,
        file_format="exr",
        bit_depth="32f",
        padding="passthrough",
        dithering=False,
    )
    return steps.steps


def effect_text(effect: Effect) -> str:
    values = ",".join(f"{n}={v}" for n, v in effect.parameters)
    return f"{effect.asset}{'(' + values + ')' if values else ''} {effect.mode} {effect.opacity:g}"


def description(cases: tuple[Case, ...] = CASES) -> str:
    listed = "; ".join(
        f"User{k} {c.background}: " + ", ".join(map(effect_text, c.effects))
        for k, c in enumerate(cases)
    )
    return (
        "Mask-stack arithmetic over snapshot-served procedurals "
        "(phase3.3_procedural-families 2.15, decision 429): plane "
        f"{RESOLUTION} px, OpenGL, Legacy, fixtures grey-a, half-steps-grey, field-a, "
        "field-b as AO, Curvature, Position, World Space Normal mesh maps. Each case: a "
        "white Raw fill on its own L32F User channel over a black Raw base, under a mask, "
        f"effects bottom-up (mono mode, opacity): {listed}. Grunges at the fill effect's "
        "default projection; grey-a in Painter's default colour space. EXR 32f, "
        "passthrough, no dithering; r1, r2 after reopen."
    )


def image_input(input_id: str, root: Path) -> dict[str, Any]:
    path = f"{BITMAPS}/{input_id}.png"
    return {
        "input_id": input_id,
        "kind": "image",
        "path": path,
        "sha256": sha256_file(root / path),
        "provenance": {
            "origin": "uzmigames_authored",
            "licence": "Apache-2.0",
            "note": "Generated by tools/parity/tier0_semantics/fixtures.py.",
        },
    }


def manifest(name: str = NAME, root: Path = REPO_ROOT) -> dict[str, Any]:
    cases = GOLDENS[name]
    envelope = current_envelope(root)
    inputs = [
        {
            "input_id": "plane",
            "kind": "mesh",
            "path": PLANE,
            "sha256": sha256_file(root / PLANE),
            "provenance": {"origin": "uzmigames_authored", "licence": "Apache-2.0"},
        },
        *(image_input(i, root) for i in MESH_MAPS.values()),
    ]
    return {
        "schema": "uzpainter/parity/golden-public/1",
        "record_class": "public_manifest",
        "golden_id": f"tier0/semantics/{name}",
        "tier": "0",
        "domain": DOMAIN,
        "description": description(cases),
        "inputs": inputs,
        "instruction_sequence": {
            "author": "UzmiGames",
            "interface": "substance_painter_documented_python_api",
            "steps": instruction_steps(cases),
        },
        "applied_settings": [
            {"name": "project.normal_map_format", "value": "OpenGL", "applied_by": "recorder_api"},
            {
                "name": "texture_set.resolution",
                "value": RESOLUTION,
                "unit": "px",
                "applied_by": "recorder_api",
            },
            {"name": "export.exr.bit_depth", "value": "32f", "applied_by": "recorder_api"},
            {"name": "export.padding", "value": "passthrough", "applied_by": "recorder_api"},
            {"name": "export.dithering", "value": False, "applied_by": "recorder_api"},
        ],
        "uncontrolled_settings": [],
        "expectations": [],
        "software": {
            "painter": {
                "product": "Adobe Substance 3D Painter",
                "version": envelope["painter_version"],
                "build_id": envelope["painter_build"],
            },
            "uzpainter_build_hash": None,
        },
        "private_records": [],
    }


def request_path(name: str = NAME, root: Path = REPO_ROOT) -> Path:
    directory = envelope_directory(current_envelope(root)["envelope_id"])
    return (
        root
        / "parity"
        / "envelopes"
        / directory
        / "requests"
        / "tier0"
        / "semantics"
        / f"{name}.json"
    )


def write(name: str = NAME, root: Path = REPO_ROOT) -> Path:
    """Write the request; an existing one must be byte-equal (requests are authored once)."""
    path = request_path(name, root)
    text = json.dumps(manifest(name, root), indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != text:
        raise ValueError(f"{path}: an authored request changed; name a new golden")
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


if __name__ == "__main__":
    for golden in GOLDENS:
        print(write(golden))
