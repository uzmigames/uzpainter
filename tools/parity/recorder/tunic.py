r"""Tunic v10 inputs: the migration golden request and the rebuild fixture (decision 194).

    python -m tools.parity.recorder.script_run manifest --pilot tunic --assets-root <Assets3D> \
        --out parity/envelopes/<envelope>/requests/phase2/tier1/tunic-v10.json [--store]
    python -m tools.parity.recorder.script_run manifest --pilot tunic-rebuild \
        --assets-root <Assets3D> --out tests/parity/tier1/tunic_v10/rebuild-fixture.json [--store]

Tunic v10 (Skeletal Mage `18-Tunica`) was painted interactively over v4..v10; no pipeline round
exists to replay. Its approved state is its Painter project, and its recipe is committed in the
piece's `report.json` (`painting_v10.painter_stack_recipe`, with the per-layer override
`source_recovery.layer_specific_masks.recipe_override_before_sync`: F03 binds
`M_piping_lining_v9`, the v9 piping, while C07 binds the v10 `M_piping`).

- `tunic`: the golden's request (`painter_project_migration`, `migration.py`): the project pinned by
  SHA-256 (the hash the piece manifest `manifests/v10.json` verifies) and the export configuration
  `parity/fixtures/tier1/tunic-v10/export-config.json` (Painter's shipped Blender preset, the one
  the delivered maps were written with: one texture set, 16-bit PNG, 4096 px, infinite padding,
  no dithering). Its one Assets3D input is git-ignored there, so `--store` keeps it.
- `tunic-rebuild`: what UzPainter rebuilds from: the recipe (the committed report), the working
  copy of the stack with the override applied to F03 only (derived, never a global filename
  replacement), every bitmap it binds by SHA-256 and by Painter resource version (the SHA-1 of the
  bytes, which is what a Painter resource URL's `version` holds), the Normal mesh map, the mesh
  and the double-sided state. Eight masks and the Normal map were recovered from the bitmaps packed
  in the piece's `.blend` (`image.packed_file.data`, the route the report records); each is
  resolved from the private store by its pin and checked against the report's SHA-256 and
  resource versions. The other nine masks exist nowhere but inside the Painter project (decision
  194): they are expected back at their original paths `_tmp/claude/<name>.png` (where the v9
  round wrote them, the packed v9 masks' file paths), and until every one is there the command is
  refused, listing them (`MissingInputs`). Nothing is regenerated or extracted from Painter.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.parity.recorder.job import sha256_bytes, sha256_file
from tools.parity.recorder.migration import EXPORT, INTERFACE, OPEN, migration_job_from_manifest
from tools.parity.recorder.script_run import (
    ASSETS3D_LICENCE,
    MissingInputs,
    assets3d_input,
    stack_bitmaps,
)
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT, Schema, validation_errors
from tools.parity.store.store import OracleStore, locate

GOLDEN_ID = "phase2/tier1/tunic-v10"
TUNIC = "Creatures/Undead/Skeletal Mage/Models3D/18-Tunica"
TUNIC_PROJECT = f"{TUNIC}/18-Tunica-v10.spp"
TUNIC_BLEND = f"{TUNIC}/18-Tunica-v10.blend"
TUNIC_REPORT = f"{TUNIC}/report.json"
TUNIC_PIECE_MANIFEST = f"{TUNIC}/manifests/v10.json"
TUNIC_MESH = f"{TUNIC}/Export/18-Tunica-v10.fbx"
EXPORT_CONFIG = "parity/fixtures/tier1/tunic-v10/export-config.json"
LOST_FOLDER = "_tmp/claude"  # where the v9 round wrote its masks (the packed v9 masks' paths)
RECIPE = ("painting_v10", "painter_stack_recipe")
OVERRIDE = (
    "painting_v10",
    "source_recovery",
    "layer_specific_masks",
    "recipe_override_before_sync",
)

# Bitmaps recovered from the `.blend`'s packed images (decision 194): name the stack binds ->
# (packed image, SHA-256). Each is checked against the report when the fixture is written.
RECOVERED: dict[str, tuple[str, str]] = {
    "M_band": (
        "Source_v10_M_band",
        "f12fd122cde2c56937c16564aa5b33bfef1d6ab49bbbe5038f56cd74945775ea",
    ),
    "M_embro": (
        "Source_v10_M_embro",
        "750c2facd9aca492bd1ac21b8f8ac1610ebe75803594ee66c33be25d4d1d3fb6",
    ),
    "M_hemband": (
        "Source_v10_M_hemband",
        "5b6559335b6f9bc49c50ba37097a618f00ed5c5069f1522cb7fededc20a2ab74",
    ),
    "M_hemline": (
        "Source_v10_M_hemline",
        "8591ee1ec691467cc291ff7bc4e7e7a2e676f09d43c96d88e48e77cbe72e0a9f",
    ),
    "M_laceholes": (
        "Source_v10_M_laceholes",
        "72a700679efa8b0ee214b5e01eecc140795f4e566d8e94712dba14a86afb30b5",
    ),
    "M_lacerings": (
        "Source_v10_M_lacerings",
        "3e04c6282e385bf3e8d637e6f03f5b27130c2bcbd7800ae95d72938ccbf896a1",
    ),
    "M_piping": (
        "Source_v10_M_piping",
        "822f926d65403df422df81cd5c9227cb2a1a2ef6c727c42f76d21b836f98a09c",
    ),
    "M_piping_lining_v9": (
        "Source_v9_M_piping",
        "9b2b306359a4ef6a1888c5eb33095a8f1fea1024130eae4d08d9c06a28aaf4d0",
    ),
}
NORMAL = (
    "Source_v6_HighNormal",
    "5815e0782be67818d31b1f99d108ecc4a0462bdeb18ba9bc1d9eb508eb44f55a",
)
VERSION = re.compile(r"version=['\"]?([0-9a-f]{40})")

TUNIC_DESCRIPTION = (
    "Tier 1 migration golden of the approved UzmiGames tunic 18-Tunica v10 of the Skeletal Mage "
    "(phase2.10 items 2.2, 3.1; decision 194). The tunic was painted interactively and has no "
    "pipeline round; its approved state is its Painter project, pinned here by SHA-256 (the hash "
    "the piece manifest verifies) and never read by UzPainter. The recorder copies it into its "
    "private work directory, checks the copy's hash and opens it in Painter through the documented "
    "API, reads back the project's state privately (the mesh it was last imported from, texture "
    "sets, resolution, mesh-map resources, channel formats, and every layer and effect with its "
    "sources, resource versions, per-channel blending and opacity, visibility and mask) and "
    "exports with an authored configuration: Painter's shipped Blender (Principled BSDF) preset, "
    "the one the delivered maps were written with, for the texture set DefaultMaterial as 16-bit "
    "PNG, sizeLog2 12, infinite padding, no dithering, no shader parameters (padding and "
    "dithering are the proposed migration configuration, not recovered facts). Recordings: r1 "
    "(same session: open, read back, export), r1-repeat (same session, export again) and r2 (after "
    "the copy is saved under a new name, closed and reopened: read back, export again). Recorded "
    "on Painter 12.1.5 under OCIO with Painter's substance configuration."
)

SETTINGS: tuple[tuple[str, Any, str], ...] = (
    ("OCIO", "resources/ocio/substance/config.ocio", "environment_variable"),
    ("export.file_format", "png", "recorder_api"),
    ("export.png.bit_depth", 16, "recorder_api"),
    ("export.size_log2", 12, "recorder_api"),
    ("export.padding", "infinite", "recorder_api"),
    ("export.dithering", False, "recorder_api"),
    ("export.shader_params", False, "recorder_api"),
)


def committed_project_pin(assets_root: Path) -> str:
    """The project's SHA-256 the piece manifest records as verified."""
    piece = json.loads((assets_root / TUNIC_PIECE_MANIFEST).read_bytes().decode("utf-8"))
    entry = piece["files"]["painter-v10"]
    if entry["path"] != TUNIC_PROJECT or entry["sha256"]["verification"] != "verified":
        raise RecorderError(f"{TUNIC_PIECE_MANIFEST} pins no verified {TUNIC_PROJECT}")
    return str(entry["sha256"]["value"])


def tunic_manifest(assets_root: Path, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """The Tunic v10 migration golden's request, hashing the project under `assets_root`;
    refused when the project is missing or is not the bytes the piece manifest verifies."""
    if not (assets_root / TUNIC_PROJECT).is_file():
        raise MissingInputs(GOLDEN_ID, [TUNIC_PROJECT])
    project = assets3d_input("tunic-v10-project", "painter_project", TUNIC_PROJECT, assets_root)
    pinned = committed_project_pin(assets_root)
    if project["sha256"] != pinned:
        raise RecorderError(
            f"{TUNIC_PROJECT} has sha256 {project['sha256']}, not the {pinned} that "
            f"{TUNIC_PIECE_MANIFEST} verifies: the approved project was saved again"
        )
    config = {
        "input_id": "tunic-v10-export-config",
        "kind": "recipe_json",
        "path": EXPORT_CONFIG,
        "sha256": sha256_file(repo_root / EXPORT_CONFIG),
        "provenance": {
            "origin": "uzmigames_authored",
            "licence": "Apache-2.0",
            "note": "The export configuration of the Tunic v10 migration golden (decision 194).",
        },
    }
    manifest: dict[str, Any] = {
        "schema": "uzpainter/parity/golden-public/1",
        "record_class": "public_manifest",
        "golden_id": GOLDEN_ID,
        "tier": "1",
        "domain": "tier1/pilot/tunic-v10",
        "description": TUNIC_DESCRIPTION,
        "inputs": [project, config],
        "instruction_sequence": {
            "author": "UzmiGames",
            "interface": INTERFACE,
            "steps": [
                {"step": 1, "call": OPEN, "args": {"project": project["input_id"]}},
                {"step": 2, "call": EXPORT, "args": {"config": config["input_id"]}},
            ],
        },
        "applied_settings": [
            {"name": name, "value": value, "applied_by": by} for name, value, by in SETTINGS
        ],
        "expectations": [],
        "software": {
            "painter": {
                "product": "Adobe Substance 3D Painter",
                "version": "12.1.5",
                "build_id": "12.1.5+js-api.1.1.20",
            },
            "uzpainter_build_hash": None,
        },
        "private_records": [],
    }
    problems = validation_errors(manifest, Schema.GOLDEN_PUBLIC)
    if problems:
        raise RecorderError(f"the {GOLDEN_ID} manifest is invalid: {problems}")
    migration_job_from_manifest(manifest, assets_root, repo_root=repo_root)
    return manifest


# --- The rebuild fixture -----------------------------------------------------------------------


def at(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        data = data[key]
    return data


def working_copy(report: dict[str, Any]) -> dict[str, Any]:
    """The recipe with the recorded per-layer override applied to its one layer, nowhere else."""
    stack: dict[str, Any] = json.loads(json.dumps(at(report, RECIPE)))
    override = at(report, OVERRIDE)
    layers = [layer for layer in stack["layers"] if layer["id"] == override["layer_id"]]
    if len(layers) != 1:
        raise RecorderError(f"the override names {override['layer_id']}, not one recipe layer")
    layers[0]["mask"] = override["mask"]
    return stack


def stack_bytes(stack: dict[str, Any]) -> bytes:
    return (json.dumps(stack, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def version_of(url: str) -> str:
    found = VERSION.search(url)
    if found is None:
        raise RecorderError(f"{url!r} names no resource version")
    return found.group(1)


def report_versions(report: dict[str, Any]) -> dict[str, tuple[str | None, str]]:
    """What the report records of each recovered bitmap: (SHA-256 or None, resource version)."""
    v10 = report["painting_v10"]
    recorded: dict[str, tuple[str | None, str]] = {
        r["mask"]: (r["sha256"], version_of(r["resource"])) for r in v10["mask_resources"]
    }
    bindings = v10["source_recovery"]["layer_specific_masks"]["bindings"]
    f03 = next(b for b in bindings if b["layer_id"] == at(report, OVERRIDE)["layer_id"])
    piping_v9 = v10["short_panel_recipe"]["input_mask_sha256"]["M_piping"]
    recorded[at(report, OVERRIDE)["mask"]] = (
        piping_v9,
        version_of(f03["recorded_original_resource"]),
    )
    normal = report["painting"]["effects_opacity_blending_state"]["mesh_maps"]
    recorded["Normal"] = (None, version_of(normal["MeshMapUsage.Normal"]))
    return recorded


def recovered_input(
    input_id: str,
    kind: str,
    packed: str,
    sha256: str,
    recorded: tuple[str | None, str],
    store: OracleStore | None,
) -> tuple[dict[str, Any] | None, str]:
    """A recovered bitmap resolved from the private store and checked against the report; None
    (and the place it was looked for) when the store does not hold it."""
    where = f"private store: {TUNIC_BLEND}#{packed} ({sha256})"
    data = store.load(sha256) if store is not None else None
    if data is None:
        return None, where
    expected_sha256, version = recorded
    sha1 = hashlib.sha1(data, usedforsecurity=False).hexdigest()
    if (expected_sha256 is not None and expected_sha256 != sha256) or sha1 != version:
        raise RecorderError(
            f"{packed}: sha256 {sha256} / version {sha1} disagree with the report's "
            f"{expected_sha256} / {version}"
        )
    return {
        "input_id": input_id,
        "kind": kind,
        "sha256": sha256,
        "painter_version": sha1,
        "recovered_from": {"assets3d_path": TUNIC_BLEND, "packed_image": packed},
        "provenance": {"origin": "uzmigames_authored", "licence": ASSETS3D_LICENCE},
    }, where


def tunic_rebuild(
    assets_root: Path, store: OracleStore | None = None, repo_root: Path = REPO_ROOT
) -> dict[str, Any]:
    """The Tunic v10 rebuild fixture; refused with `MissingInputs` naming every input that is
    neither at its Assets3D path nor (for a recovered bitmap) in the private store."""
    store = store if store is not None else locate()
    missing: list[str] = []
    for path in (TUNIC_REPORT, TUNIC_MESH):
        if not (assets_root / path).is_file():
            missing.append(path)
    if TUNIC_REPORT in missing:
        raise MissingInputs(GOLDEN_ID, missing)
    report = json.loads((assets_root / TUNIC_REPORT).read_bytes().decode("utf-8"))
    stack = working_copy(report)
    recorded = report_versions(report)
    inputs: list[dict[str, Any]] = [
        assets3d_input("tunic-report", "recipe_json", TUNIC_REPORT, assets_root)
    ]
    masks: dict[str, str] = {}
    for name in sorted(stack_bitmaps(stack)):
        input_id = f"mask-{name.lower()}"
        masks[name] = input_id
        if name in RECOVERED:
            packed, sha256 = RECOVERED[name]
            item, where = recovered_input(input_id, "mask", packed, sha256, recorded[name], store)
            if item is None:
                missing.append(where)
            else:
                inputs.append(item)
            continue
        path = f"{LOST_FOLDER}/{name}.png"
        if not (assets_root / path).is_file():
            missing.append(path)
            continue
        item = assets3d_input(input_id, "mask", path, assets_root)
        item["painter_version"] = hashlib.sha1(
            (assets_root / path).read_bytes(), usedforsecurity=False
        ).hexdigest()
        inputs.append(item)
    normal, where = recovered_input(
        "tunic-normal", "image", NORMAL[0], NORMAL[1], recorded["Normal"], store
    )
    if normal is None:
        missing.append(where)
    if missing:
        raise MissingInputs(GOLDEN_ID, missing)
    assert normal is not None
    inputs.append(normal)
    inputs.append(assets3d_input("tunic-mesh", "mesh", TUNIC_MESH, assets_root))
    by_id = {item["input_id"]: item for item in inputs}
    bindings = [
        {"node": group["key"], "kind": "group", "mask": group["mask"]}
        for group in stack["groups"]
        if group.get("mask")
    ] + [
        {"node": layer["id"], "kind": "fill", "mask": layer["mask"]}
        for layer in stack["layers"]
        if layer.get("mask")
    ]
    for binding in bindings:
        item = by_id[masks[binding["mask"]]]
        binding.update(
            input=item["input_id"], sha256=item["sha256"], painter_version=item["painter_version"]
        )
    double_sided = report["painting"]["effects_opacity_blending_state"]["doubleSided"]["value"]
    return {
        "schema": "uzpainter/pilot-rebuild-fixture/1",
        "golden_id": GOLDEN_ID,
        "inputs": inputs,
        "stack": {
            "recipe": "tunic-report",
            "selector": "/" + "/".join(RECIPE),
            "override": at(report, OVERRIDE),
            "sha256": sha256_bytes(stack_bytes(stack)),
        },
        "bindings": bindings,
        "mesh_maps": {"Normal": "tunic-normal"},
        "mesh": {
            "input": "tunic-mesh",
            "assumption": (
                "the delivered FBX of the same Blender object; the file the Painter project was "
                "created from is not recorded (checked against the golden's readback of "
                "last_imported_mesh_path and, finally, by the map comparison)"
            ),
        },
        "double_sided": {
            "value": bool(double_sided),
            "source": "/painting/effects_opacity_blending_state/doubleSided/value",
        },
        "export_config": {"path": EXPORT_CONFIG, "sha256": sha256_file(repo_root / EXPORT_CONFIG)},
    }


PILOTS: dict[str, Callable[[Path], dict[str, Any]]] = {
    "tunic": tunic_manifest,
    "tunic-rebuild": tunic_rebuild,
}
