"""Strict replay of admitted SourceSubstance probes over the metadata /3 capture (decision 361).

The project is a private derived artifact like the legacy /2 one
(`test_snapshot_capture_replay.py`), captured again with the /3 bridge: explicit toggle 0 and
toggle 1 snapshots whose metadata keeps the typed effective parameters and the observed
ResourceID, with the initial signature bound by `assets bind-snapshot` (fill uid 6, User0). It is
resolved from the private oracle store by hash and size, verified after the copy and only then
opened; without it the test skips as `oracle_unavailable`. The legacy module's replay (recorder
serializers by AST, recording 1, save/close/reopen, recording 2) runs unchanged. Here no known
difference is allowed: every step, `resource_id` and parameter types included, must equal its
recording. Messages name only the condition, step, call and digests.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.python.conftest import Run
from tests.python.test_snapshot_capture_replay import (
    PROBES,
    digest,
    expected,
    private_dir,
    replay,
    typed,
)
from tools.parity.store.store import Status, locate, resolve_oracle

# Public references of the private /3 capture, hashes only (2026-10-25, Painter lock seq
# 1276/1277, UzPainter's own Legacy Painter; UzPainter.exe built at fba92c2e). The signatures are
# the /2 capture's: signatures encode by value. Receipts and requests stay private.
# `request_sha256` hashes the request file given to `assets snapshot` (the command keeps a
# canonical copy beside its receipt, whose bytes differ).
CAPTURE: dict[str, Any] = {
    "exe_sha256": "50548db113b4abd4a2c319c52cb797b9d24d455b455584ab6fa1c038a43c34cf",
    "bridge_sha256": "61e0afa69d53518900039a2b9bdbd4b048d2068259c72266e202ee33972a7be9",
    "painter_side_sha256": "625323d83cb6e7ff7878518861412dbf5c7f7cf0872435f154da1303870bd44d",
    "toggle_0": {
        "signature_sha256": "fe9a975644a85ede1e1f5f3a127b08f040f795ad6b3cd6f7a52c5b350185bf4b",
        "request_sha256": "cf647c2c69d210039036bdf65e124bb7edf73f89ee02f7b66a2b0e9262c09a78",
        "receipt_sha256": "bb3d49acbc8c818ad28cbe1036b1e7ec8c4cd25e805d42e47ad97c73c80cb745",
    },
    "toggle_1": {
        "signature_sha256": "190f21cad9c59752e66165ceeb64dcac63a64dc49783135da0aecc59138f9501",
        "request_sha256": "4cb69ff87970a007753e7b2de216952d7f056c64bb15b83adf3a8b37222aff53",
        "receipt_sha256": "4907e84f8d555064f4eed9d2f41b8e40a6b78260ba95f92cc13f6de725deeb68",
    },
    # The bound initial state: toggle 0, fill uid 6, User0, the receipt's nominal override.
    "bind_request_sha256": "f0c3126bd180db8ec09a009a0ec089ea0a95474498ea02bb21768d567cb927d8",
}
PROJECT_BLOB: dict[str, Any] = {
    "record_id": "source-substance-0-1-v3-project",
    "sha256": "3ef6845efbe8d38e910839a4eef346bbe5bdfa3f21ac08dac9a6fa2ef859f16f",
    "size_bytes": 225280,
}


@pytest.fixture
def captured_project(tmp_path: Path) -> Path:
    resolved = resolve_oracle(locate(), PROJECT_BLOB)
    if resolved.status != Status.AVAILABLE or resolved.path is None:
        pytest.skip(f"oracle_unavailable: {resolved.reason}")
    target = tmp_path / "captured.uzp"
    shutil.copyfile(resolved.path, target)
    size = target.stat().st_size
    sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
    if (sha256, size) != (PROJECT_BLOB["sha256"], PROJECT_BLOB["size_bytes"]):
        pytest.fail(f"copied project differs: sha256 {sha256}, size {size}", pytrace=False)
    return target


@pytest.mark.parametrize("name", sorted(PROBES))
def test_recorded_source_steps_replay_exactly(
    private_facade: Run, captured_project: Path, name: str
) -> None:
    observed, steps = replay(private_facade, name)
    calls = {f"s{s['step']}": str(s["call"]).rsplit(".", 2)[-2:] for s in steps}
    mismatches: list[str] = []
    details: dict[str, Any] = {}
    pairs = zip(expected(name, steps), observed, strict=True)
    for condition, (recorded, actual) in enumerate(pairs):
        for key in calls:
            want, got = typed(recorded[key]), typed(actual[key])
            if want != got:
                mismatches.append(
                    f"r{condition + 1} {key} {'.'.join(calls[key])}: "
                    f"recorded {digest(recorded[key])} != replayed {digest(actual[key])}"
                )
                details[f"r{condition + 1}/{key}"] = {"recorded": want, "replayed": got}
    if details:
        text = json.dumps(details, indent=1)
        (private_dir() / f"replay-v3-differences-{name}.json").write_text(text, encoding="utf-8")
    status = "equal" if not mismatches else "different"
    print(f"full comparison: {status} ({len(mismatches)} differing steps)")
    if mismatches:
        summary = [f"{len(mismatches)} replay differences:", *mismatches]
        pytest.fail("\n".join(summary), pytrace=False)
