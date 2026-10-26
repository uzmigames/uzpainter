"""Public producer identities remain subject to every repository guard rule."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.parity.guard.guard import Snapshot, load_index, run_guard
from tools.parity.schemas import REPO_ROOT, SCHEMA_DIR, Schema, validation_errors
from tools.parity.store.store import OracleStore, sha256_file

POLICY_PATH = "parity/snapshot-producer-policy-v1.json"


def policy() -> dict[str, Any]:
    return {
        "schema": "uzpainter/parity/snapshot-producer-policy/1",
        "revision": 1,
        "producers": [
            {
                "protocol": "paired-scalar-rgb",
                "source_revision": "1" * 40,
                "bridge_sha256": "2" * 64,
                "painter_side_sha256": "3" * 64,
            }
        ],
    }


def rules(data: bytes, path: str = POLICY_PATH, index: frozenset[str] | None = None) -> set[str]:
    snapshot = Snapshot((path,), (path,), lambda _: data)
    return {finding.rule for finding in run_guard(REPO_ROOT, snapshot, index)}


def test_reviewed_policy_and_registered_schema_pass_guard() -> None:
    data = (REPO_ROOT / POLICY_PATH).read_bytes()
    assert validation_errors(json.loads(data), Schema.SNAPSHOT_PRODUCER_POLICY) == []
    assert rules(data) == set()
    name = Schema.SNAPSHOT_PRODUCER_POLICY.value
    assert rules((SCHEMA_DIR / name).read_bytes(), f"parity/schema/{name}") == set()


@pytest.mark.parametrize(
    "mutation",
    ["root-extra", "row-extra", "float", "bool", "zero", "overflow", "duplicate-pair"],
)
def test_policy_guard_refuses_invalid_contract(mutation: str) -> None:
    document = policy()
    if mutation == "root-extra":
        document["path"] = "private-capture"
    elif mutation == "row-extra":
        document["producers"][0]["path"] = "private-capture"
    elif mutation == "duplicate-pair":
        row = dict(document["producers"][0])
        row["source_revision"] = "4" * 40
        document["producers"].append(row)
    else:
        document["revision"] = {"float": 1.0, "bool": True, "zero": 0, "overflow": 1 << 63}[
            mutation
        ]
    assert rules(json.dumps(document).encode()) == {"public-schema"}


def test_policy_guard_parses_original_bytes_for_duplicate_keys() -> None:
    data = json.dumps(policy()).encode().replace(b'"revision": 1', b'"revision": 2, "revision": 1')
    assert rules(data) == {"public-schema"}


@pytest.mark.parametrize(
    "path",
    ["parity/snapshot-producer-policy-v2.json", "parity/other/snapshot-producer-policy-v1.json"],
)
def test_policy_guard_path_is_exact(path: str) -> None:
    assert rules(json.dumps(policy()).encode(), path) == {"public-schema"}


def test_valid_policy_still_blocked_when_bytes_are_in_private_store(tmp_path: Path) -> None:
    data = json.dumps(policy(), indent=2).encode() + b"\n"
    source = tmp_path / "synthetic-policy.json"
    source.write_bytes(data)
    store = OracleStore.init(tmp_path / "store")
    store.put_blob(source, sha256_file(source)[0])
    index = load_index(store.root / "index.json")
    assert rules(data, index=index) == {"store-hash"}
    assert rules(data.replace(b"\n", b"\r\n"), index=index) == {"store-hash"}
