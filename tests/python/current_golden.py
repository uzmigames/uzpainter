"""Resolve acceptance manifests when a replay starts, without retaining an old envelope."""

from __future__ import annotations

from typing import Any

from tools.parity.verdict import resolve_golden


def current_manifest(golden_id: str) -> dict[str, Any]:
    resolved = resolve_golden(golden_id)
    assert resolved is not None, f"{golden_id}: missing from the current oracle envelope"
    assert not resolved.stale, f"{golden_id}: stale oracle envelope {resolved.envelope_id}"
    return resolved.manifest
