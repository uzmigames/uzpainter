"""Authored controls distinguishing fresh baking initialization from later resolution edits."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder import vocabulary as ps
from tools.parity.schemas import REPO_ROOT

CONTROLS = (
    ("plane-512", 512, None),
    ("plane-2048", 2048, None),
    ("plane-256-resize-1024", 256, (1024, 1024)),
    ("plane-1024-resize-256", 1024, (256, 256)),
    ("plane-256-resize-256x1024", 256, (256, 1024)),
)


def requests(root: Path = REPO_ROOT) -> dict[Path, dict[str, Any]]:
    """Keep the official baseline's authored captures, with no private record references."""
    base = manifest_root(current_envelope(root), root)
    baseline = json.loads(
        (base / "tier0/defaults-templates/baking-defaults.json").read_text(encoding="utf-8")
    )
    result = {}
    for suffix, size, resized in CONTROLS:
        manifest = copy.deepcopy(baseline)
        name = f"baking-defaults-{suffix}"
        manifest["golden_id"] = f"tier0/defaults-templates/{name}"
        manifest["description"] = (
            f"Baking initialization control: fresh authored plane at {size} px"
            + (
                f", then set_resolutions(width={resized[0]}, height={resized[1]})"
                if resized
                else ""
            )
            + "; capture every baking parameter and state only after these steps. "
            "r1 after setup, r2 after save/reopen, r3 after repeating setup on another fresh "
            "project. No bake or baking-parameter mutation; no value predicted. Compare "
            "against fresh resolution controls to distinguish initial from current resolution."
        )
        steps = manifest["instruction_sequence"]["steps"]
        steps[0]["args"] = {"mesh": "plane", "default_texture_resolution": size}
        if resized:
            steps.insert(
                1, {"call": ps.SET_RESOLUTIONS, "args": {"width": resized[0], "height": resized[1]}}
            )
        for index, step in enumerate(steps, 1):
            step["step"] = index
        manifest["private_records"] = []
        manifest["expectations"] = []
        manifest["applied_settings"] = [
            {
                "name": "project.default_texture_resolution",
                "value": size,
                "applied_by": "recorder_api",
            }
        ]
        result[base.parent / "requests/tier0/defaults-templates" / f"{name}.json"] = manifest
    return result
