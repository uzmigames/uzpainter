"""Readbacks of an admitted Tier 0 API probe, read from the private store (skips without it)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import Status, locate, resolve_oracle

ENVELOPE = REPO_ROOT / "parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7"


def recorded_readbacks(name: str) -> list[dict[str, dict[str, Any]]]:
    """Per recording, `output_id -> {"value": ...}` or `{"raised": {type, message}}`."""
    path = ENVELOPE / "manifests/tier0/api-probes" / f"{name}.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    reference = next(r for r in manifest["private_records"] if r["record_id"] == "golden-record")
    resolved = resolve_oracle(locate(), reference)
    if resolved.status != Status.AVAILABLE or resolved.path is None:
        pytest.skip(f"oracle_unavailable: {resolved.reason}")
    record = json.loads(resolved.path.read_text(encoding="utf-8"))
    return [
        {
            output["output_id"]: {"raised": output["raised"]}
            if "raised" in output
            else {"value": output.get("value")}
            for output in recording["outputs"]
            if output["kind"] == "api_readback"
        }
        for recording in record["recordings"]
    ]
