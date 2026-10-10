"""Transactions, operation records and name addressing (phase1.2_docmodel-transactions, 3.1-3.7).

`uzp-core-transaction-tests.exe` (`tests/uzp_core/transaction_test.cpp`,
`zig build uzp-core-transaction-tests`) holds the native cases; these tests run each of them and
check that the native `request_hash` equals the SHA-256 of Python's `canonical_json`
(`tools/parity/recorder/job.py`) of `{"tool": ..., "arguments": ...}`, whatever the key order.
No GPU is involved: everything runs on the hosted CPU lane.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder.job import canonical_json

REPO_ROOT = Path(__file__).resolve().parents[2]

NATIVE_CASES = (
    "snapshot_immutability",  # 3.1
    "failed_mutation",  # 3.2
    "composite_failure",  # 3.3
    "transaction_atomicity",  # 3.4
    "change_sets",  # 2.3
    "commit_sink_and_checkpoints",  # 2.1, 2.5
    "decision_table",  # 3.5
    "document_idempotency",  # 3.5
    "request_hash_key_order",  # 3.6
    "name_addressing",  # 3.7
)


@pytest.fixture(scope="session")
def transaction_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-core-transaction-tests.exe` of a fresh `zig build uzp-core-transaction-tests`."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-core-transaction-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("uzp-core-transaction-tests")
    build = subprocess.run(
        [zig, "build", "uzp-core-transaction-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-core-transaction-tests.exe"


def run(exe: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([str(exe), *args], capture_output=True, timeout=120, check=False)


@pytest.mark.parametrize("case", NATIVE_CASES)
def test_native_case(transaction_tests: Path, case: str) -> None:
    proc = run(transaction_tests, "run", case)
    assert proc.returncode == 0, proc.stdout.decode() + proc.stderr.decode()
    assert f"PASS {case}".encode() in proc.stdout


def test_native_case_list_is_complete(transaction_tests: Path) -> None:
    proc = run(transaction_tests, "run")
    assert proc.returncode == 0, proc.stdout.decode()
    ran = [line.split()[1] for line in proc.stdout.decode().splitlines() if line.startswith("PASS")]
    assert tuple(ran) == NATIVE_CASES


ARGUMENTS: list[dict[str, Any]] = [
    {},
    {"name": "M_piping", "position": {"set": 1, "stack": 3}, "type": "FillLayer"},
    {"opacity": 0.1, "scale": [1.0, 1e-05, 1e16], "label": "ünïcode ✓", "tags": None, "on": True},
    {"z": {"b": [3, {"y": 1, "x": 2}], "a": "\u0007 control"}, "a": -9223372036854775808},
]


@pytest.mark.parametrize("arguments", ARGUMENTS)
def test_request_hash_matches_python(
    transaction_tests: Path, tmp_path: Path, arguments: dict[str, Any]
) -> None:
    """3.6: the native hash is Python's, and does not depend on the order keys were written in."""
    request = {"tool": "layer_insert", "arguments": arguments}
    expected = hashlib.sha256(canonical_json(request)).hexdigest()
    for order in (arguments, dict(reversed(list(arguments.items())))):
        path = tmp_path / "arguments.json"
        path.write_text(json.dumps(order, ensure_ascii=False), encoding="utf-8")
        proc = run(transaction_tests, "request-hash", "layer_insert", str(path))
        assert proc.returncode == 0, proc.stderr.decode()
        assert proc.stdout.decode() == expected
