r"""Painter's own `glTF PBR Metal Roughness` export on the three pilots (phase3.1 item 3.1).

    python -m tools.parity.recorder.script_run manifest --pilot wand-gltf|sash-gltf|tunic-gltf \
        --assets-root <Assets3D> --out parity/envelopes/<envelope>/requests/phase3/tier1/<id>.json

Each request is the pilot's admitted Tier 1 golden of the current envelope, its authored part
unchanged except for the export: every input (pinned by SHA-256, resolved in Assets3D or by hash
in the private store, decision 144), the create and the sync stay byte for byte. Then:

- **Wand v1 and Sash v5** (pipeline-script jobs): the script's own `painter_export.py` stays, and a
  closing `export_project_textures` with an authored configuration follows it on the same document
  (the Wand float route, decision 283). The script's PNG 16 maps must equal the pilot golden's,
  which proves the document is the same.
- **Tunic v10** (a native job runs exactly one closing configuration): the authored configuration
  replaces the five-map Blender configuration.

The configuration (`parity/fixtures/tier1/<pilot>-gltf/export-config.json`) names Painter's
predefined preset by the URL R-314 observed (`export-preset-generator://gltf`, decision 314), the
pilot's one texture set, and the pilot's own export parameters (PNG 16, its size, `infinite`
padding, no dithering), as R-314's `gltf-pipeline` probe did. Painter writes glTF scene files
beside the textures; the recorder keeps them as `exported_sidecar` blobs, never as maps.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

from tools.parity.recorder.job import sha256_file
from tools.parity.recorder.script_run import CONFIG_EXPORT, pipeline_job_from_manifest
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT, Schema, load_json, validation_errors
from tools.parity.verdict import resolve_golden

GLTF_URL = "export-preset-generator://gltf"  # R-314's observed predefined URL (decision 314)
CONFIG_ID = "gltf-export-config"


def fixture(pilot: str) -> str:
    return f"parity/fixtures/tier1/{pilot}-gltf/export-config.json"


# pilot -> (the admitted base golden, the glTF golden id, the domain)
PILOT_GOLDENS: dict[str, tuple[str, str, str]] = {
    "wand-v1": ("phase1/tier1/wand-v1", "phase3/tier1/wand-v1-gltf", "tier1/pilot/wand-v1-gltf"),
    "sash-v5": (
        "phase2/tier1/sash-v5-current",
        "phase3/tier1/sash-v5-gltf",
        "tier1/pilot/sash-v5-gltf",
    ),
    "tunic-v10": (
        "phase2/tier1/tunic-v10-current",
        "phase3/tier1/tunic-v10-gltf",
        "tier1/pilot/tunic-v10-gltf",
    ),
}

DESCRIPTION = (
    "Painter's own glTF PBR Metal Roughness export of the Tier 1 pilot {base} "
    "(phase3.1_unreal-gltf-pbr-preset item 3.1). Every input, the create and the sync are the "
    "admitted {base} golden's, byte for byte, run with the same recorder adaptations. {export} "
    "The authored configuration export-config.json names Painter's predefined preset by the URL "
    "R-314 observed (export-preset-generator://gltf, decision 314) for the texture set {root}, "
    "with the pilot's own export parameters: PNG 16, sizeLog2 {size}, infinite padding, no "
    "dithering, no shader parameters. The glTF scene files Painter writes beside the textures "
    "are kept as sidecars, never as maps. Recordings: r1 (same session), r1-repeat (same "
    "session, every export again) and r2 (after save, close and reopen, every export again). "
    "No packing or value is presumed."
)
SCRIPT_EXPORT = (
    "The pinned painter_export.py runs unchanged, then the recorder exports the configuration "
    "on the same document into a fresh directory of its own; the script's PNG 16 maps must equal "
    "the {base} golden's byte for byte."
)
NATIVE_EXPORT = (
    "The configuration replaces the five-map export configuration as the native job's one "
    "closing export."
)


def gltf_manifest(pilot: str, assets_root: Path, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """The glTF request of `pilot` (the module's docstring), refused unless its base golden is
    admitted under the current envelope and the request loads as a pipeline job."""
    base_id, golden_id, domain = PILOT_GOLDENS[pilot]
    resolved = resolve_golden(base_id, repo_root)
    if resolved is None or resolved.stale:
        raise RecorderError(f"{golden_id}: {base_id} is not admitted under the current envelope")
    manifest = copy.deepcopy(dict(load_json(resolved.manifest_path)))
    manifest["private_records"] = []
    path = fixture(pilot)
    config = load_json(repo_root / path)
    root = config["exportList"][0]["rootPath"]
    size = config["exportParameters"][0]["parameters"]["sizeLog2"]
    steps = manifest["instruction_sequence"]["steps"]
    item = {
        "input_id": CONFIG_ID,
        "kind": "recipe_json",
        "path": path,
        "sha256": sha256_file(repo_root / path),
        "provenance": {
            "origin": "uzmigames_authored",
            "licence": "Apache-2.0",
            "note": "Painter's predefined glTF preset on the pilot's texture set, with the "
            "pilot's export parameters (phase3.1_unreal-gltf-pbr-preset item 3.1).",
        },
    }
    if steps[-1]["call"] == CONFIG_EXPORT:  # the native job's one closing export, replaced
        replaced = steps[-1]["args"]["config"]
        manifest["inputs"] = [i for i in manifest["inputs"] if i["input_id"] != replaced]
        steps[-1] = {
            "step": steps[-1]["step"],
            "call": CONFIG_EXPORT,
            "args": {"config": CONFIG_ID},
        }
        export = NATIVE_EXPORT
    else:
        steps.append({"step": len(steps) + 1, "call": CONFIG_EXPORT, "args": {"config": CONFIG_ID}})
        export = SCRIPT_EXPORT.format(base=base_id)
    manifest["inputs"] = [*manifest["inputs"], item]
    manifest.update(
        golden_id=golden_id,
        domain=domain,
        description=DESCRIPTION.format(base=base_id, export=export, root=root, size=size),
    )
    problems = validation_errors(manifest, Schema.GOLDEN_PUBLIC)
    if problems:
        raise RecorderError(f"the {golden_id} manifest is invalid: {problems}")
    pipeline_job_from_manifest(manifest, assets_root, repo_root=repo_root)
    return manifest


PILOTS: dict[str, Callable[[Path], dict[str, Any]]] = {
    f"{pilot.split('-')[0]}-gltf": partial(gltf_manifest, pilot) for pilot in PILOT_GOLDENS
}
