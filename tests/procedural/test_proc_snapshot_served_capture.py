"""Acceptance 4.1 of phase3.2_proc-snapshot-backend over a real capture: every snapshot of the
decision-413 capture project is served byte-equal to the Painter export it was recorded from.

The project is the private derived artifact of decision 413 (UzPainter's own plane project with the
multi-output capture of the decision-412 starter material: five states, two outputs, two channel
views, 20 snapshots), resolved from the private oracle store by hash and size. The Painter exports
are the five capture receipts `UzPainter.exe assets snapshot` left under
`%LOCALAPPDATA%/UzPainter/snapshot-recordings/`, found by the SHA-256 of their `capture.json`.
Without either the test skips as `oracle_unavailable`.

The `snapshot-served` case of `uzp-procedural-tests.exe` opens a copy of the project, loads its
snapshots through `SnapshotBackend::Load` and reports, per manifest entry, the SHA-256 of what
`SnapshotBackend.Stored` returns and of the float32 texels `Evaluate` gives. Independently, this
test decodes both EXR float32 exports of each capture (`tools.parity.fit.decode`), requires the
repeat to equal the first export bit for bit, and matches each export to the entry whose stored
signature equals the receipt's signature for that export. Both digests must equal the export's
float32 bytes (rows top first, channels interleaved). Messages name signature hashes only.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tools.parity.fit.decode import decode
from tools.parity.store.store import Status, locate, resolve_oracle

# The decision-413 capture (2026-11-08, Painter lock seq 2340/2341).
PROJECT_BLOB: dict[str, Any] = {
    "record_id": "source-substance-presets-inputs-project",
    "sha256": "b34c843e68c1823aad086df139daa279ce23ce4d3a28859915ed2c4a2e7122ed",
    "size_bytes": 237568,
}

# Its five capture receipts (`capture.json`), by state: SHA-256 and size.
RECEIPTS: dict[str, tuple[str, int]] = {
    "defaults": ("7c8673bdd7855d9f4d8d447941a4fad7182bb58ec2b873c79793e14c0af07343", 44625),
    "preset": ("ea30b53ea2ab1549fef49d1ca2d7f7ad7ea9283938b2c348838eb561a8754ad1", 44648),
    "preset-color": ("a0195f992f334ae1c51f5641ca14175f90ed1871a6456fa0ce3154758da76d93", 44906),
    "preset-bitmap": ("64681fa49ac93ef6d28f632f13b4efcffe092807375953f6613e6499b28eeb5f", 45498),
    "preset-removed": ("a1d15ca7c493f4589587d72253e81757c298557635ec3d6294eed7dff2f515d7", 44837),
}


def recordings_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "UzPainter" / "snapshot-recordings"


def find_receipts() -> dict[str, Path]:
    """The work directory of each receipt in `RECEIPTS`, found by its bytes."""
    wanted = {value: state for state, value in RECEIPTS.items()}
    found: dict[str, Path] = {}
    root = recordings_dir()
    if root.is_dir():
        for receipt in sorted(root.glob("*/capture.json")):
            data = receipt.read_bytes()
            state = wanted.get((hashlib.sha256(data).hexdigest(), len(data)))
            if state is not None:
                found[state] = receipt.parent
    return found


def staged_project(tmp_path: Path) -> Path:
    resolved = resolve_oracle(locate(), PROJECT_BLOB)
    if resolved.status != Status.AVAILABLE or resolved.path is None:
        pytest.skip(f"oracle_unavailable: {resolved.reason}")
    target = tmp_path / "captured.uzp"
    shutil.copyfile(resolved.path, target)
    data = target.read_bytes()
    if (hashlib.sha256(data).hexdigest(), len(data)) != (
        PROJECT_BLOB["sha256"],
        PROJECT_BLOB["size_bytes"],
    ):
        pytest.fail("the copied capture project differs from its store record", pytrace=False)
    return target


def export_float32(path: Path, channels: int) -> bytes:
    """The float32 samples of one EXR export, rows top first, channels interleaved."""
    decoded = decode(path.read_bytes())
    assert not decoded.integer and decoded.bits == 32, f"{path.name}: not a float32 export"
    values = decoded.values
    assert values.ndim == 3 and values.shape[-1] == channels, f"{path.name}: {values.shape}"
    samples = values.astype("<f4")
    assert np.array_equal(samples.astype(np.float64), values, equal_nan=True), path.name
    return samples.tobytes()


def served_rows(exe: Path, project: Path) -> list[dict[str, Any]]:
    proc = subprocess.run(
        [str(exe), "snapshot-served", str(project)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    failed = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
    assert proc.returncode == 0 and not failed, proc.stdout + proc.stderr
    prefix = "SERVED "
    return [
        json.loads(line[len(prefix) :])
        for line in proc.stdout.splitlines()
        if line.startswith(prefix)
    ]


def test_capture_served_byte_equal_to_painter_exports(
    procedural_tests: Path, tmp_path: Path
) -> None:
    """4.1: each of the 20 snapshots is served byte-equal to the Painter export of its signature."""
    project = staged_project(tmp_path)
    receipts = find_receipts()
    missing = sorted(set(RECEIPTS) - set(receipts))
    if missing:
        pytest.skip(f"oracle_unavailable: capture receipts not on this machine: {missing}")
    rows = served_rows(procedural_tests, project)
    keys = [row["signature_sha256"] for row in rows]
    assert len(rows) == 20 and len(set(keys)) == 20, keys
    uuids = {row["project_uuid"] for row in rows}
    assert len(uuids) == 1, "every snapshot names the project"

    matched: set[str] = set()
    for state, work in sorted(receipts.items()):
        receipt = json.loads((work / "capture.json").read_text(encoding="utf-8"))
        assert receipt["project_uuid"] in uuids, f"{state}: the receipt names another project"
        assert len(receipt["captures"]) == 4, state
        for capture in receipt["captures"]:
            signature = capture["signature"]
            channels = int(signature["output"]["channels"])
            first = export_float32(work / capture["file"], channels)
            repeat = export_float32(work / capture["repeat"], channels)
            assert first == repeat, f"{state}/{capture['file']}: the repeat export differs"
            served = [row for row in rows if row["signature"] == signature]
            assert len(served) == 1, (
                f"{state}/{capture['file']}: {len(served)} entries hold its signature"
            )
            row = served[0]
            key = row["signature_sha256"]
            expected = hashlib.sha256(first).hexdigest()
            resolution = int(signature["output"]["resolution"])
            assert (row["format"], row["resolution"], row["channels"]) == (
                "f32",
                resolution,
                channels,
            ), key
            assert row["evaluated"] == {
                "width": resolution,
                "height": resolution,
                "channels": channels,
                "sha256": expected,
            }, f"{key}: Evaluate differs from the Painter export"
            assert row["stored_sha256"] == expected, (
                f"{key}: Stored differs from the Painter export"
            )
            matched.add(key)
    assert matched == set(keys), sorted(set(keys) - matched)
