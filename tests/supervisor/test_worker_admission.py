"""The worker's admission of mutating calls over the project store's operation rows, through
its pipe (src/supervisor/worker.cpp; task phase2.2_supervisor-admission-ledger items 2.3-2.5,
3.3, 3.4, 3.6; decision 138).

CPU only: the workers use `--test-gpu-unavailable`. `test_mutation` is the Debug-only
typed mutation under `--test-faults`: one transaction through `ProjectStore::Submit`, the path
the typed tools of phase2.6 take.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from tests.supervisor.conftest import INSERT_FILL, Pipe, make_project


def opened(painter: Path, tmp_path: Path, pipes: list[Pipe]) -> tuple[Pipe, Path, int]:
    """A worker holding a fresh plane project; the project and its revision."""
    project = make_project(painter, tmp_path)
    pipe = Pipe(
        painter,
        tmp_path,
        "--gpu-backend",
        "vulkan",
        "--test-gpu-unavailable",
        "--allow-python",
        "--test-faults",
    )
    pipes.append(pipe)
    revision = pipe.call("project_open", {"path": str(project)})["result"]["revision"]
    assert isinstance(revision, int)
    return pipe, project, revision


def mutate(pipe: Pipe, arguments: dict[str, Any], key: str, expected: int | None) -> dict[str, Any]:
    extra: dict[str, Any] = {"idempotency_key": key}
    if expected is not None:
        extra["expected_revision"] = expected
    return pipe.call("test_mutation", arguments, **extra)


def revision_of(pipe: Pipe) -> int:
    revision = pipe.call("project_inspect")["result"]["revision"]
    assert isinstance(revision, int)
    return revision


def operations(pipe: Pipe, after: int = 0) -> dict[str, Any]:
    result = pipe.request({"method": "worker/operations", "after": after})["result"]
    assert isinstance(result, dict)
    return result


def request_hash(tool: str, arguments: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON of the tool name and its arguments (item 2.3)."""
    text = json.dumps(
        {"arguments": arguments, "tool": tool},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_a_known_key_is_decided_before_the_precondition(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    """2.3, 2.4, 3.3: the stored outcome of a known key with the same request hash is returned
    without mutating even after the revision advanced, with or without its precondition; the key
    with other arguments is `idempotency_conflict`; an unknown key without a precondition is
    `outcome_unknown`. The rows carry the request hash of the tool name and arguments."""
    pipe, _, revision = opened(painter, tmp_path, pipes)
    first = mutate(pipe, {"name": "A"}, "k-1", revision)
    assert first["admission"] == "executed"
    assert first["committed_revision"] == revision + 1
    assert first["request_hash"] == request_hash("test_mutation", {"name": "A"})
    assert first["result"]["status"] == "committed"
    assert first["result"]["committed_revision"] == revision + 1
    assert mutate(pipe, {"name": "B"}, "k-2", revision + 1)["committed_revision"] == revision + 2

    for expected in (revision, None):
        replay = mutate(pipe, {"name": "A"}, "k-1", expected)
        assert replay["admission"] == "stored_outcome"
        assert replay["result"] == first["result"]
        assert replay["committed_revision"] == revision + 2
    conflict = mutate(pipe, {"name": "C"}, "k-1", revision)
    assert conflict["error"]["code"] == "idempotency_conflict"
    assert conflict["error"]["details"] == {"key": "k-1", "committed_revision": revision + 1}
    script = pipe.call(
        "run_python", {"code": INSERT_FILL}, idempotency_key="k-1", expected_revision=revision + 2
    )
    assert script["error"]["code"] == "idempotency_conflict"
    unknown = mutate(pipe, {"name": "D"}, "k-3", None)
    assert unknown["error"]["code"] == "outcome_unknown"
    assert unknown["error"]["details"] == {"key": "k-3", "committed_revision": revision + 2}
    assert revision_of(pipe) == revision + 2

    rows = operations(pipe, after=revision)
    assert rows["current_revision"] == revision + 2 and rows["unreadable"] == []
    assert [(row["idempotency_key"], row["committed_revision"]) for row in rows["operations"]] == [
        ("k-1", revision + 1),
        ("k-2", revision + 2),
    ]
    assert rows["operations"][0]["request_hash"] == first["request_hash"]
    assert rows["operations"][0]["outcome"] == first["result"]
    assert operations(pipe, after=revision + 1)["operations"][0]["idempotency_key"] == "k-2"


def test_a_failed_mutation_writes_no_row_and_its_retry_follows_the_unknown_key_rule(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    """3.4: a failed mutation commits nothing and writes no operation row; its retry executes
    again against the unchanged revision, and is `stale_revision` once the revision moved."""
    pipe, _, revision = opened(painter, tmp_path, pipes)
    failing = {"name": "F", "fail": True}
    failed = mutate(pipe, failing, "k-f", revision)
    assert failed["error"]["code"] == "call_failed"
    assert failed["error"]["details"]["outcome"]["status"] == "failed"
    assert revision_of(pipe) == revision
    assert "k-f" not in [row["idempotency_key"] for row in operations(pipe)["operations"]]
    again = mutate(pipe, failing, "k-f", revision)
    assert again["error"]["code"] == "call_failed"  # executed again, not refused
    assert revision_of(pipe) == revision
    assert mutate(pipe, {"name": "A"}, "k-a", revision)["committed_revision"] == revision + 1
    stale = mutate(pipe, failing, "k-f", revision)
    assert stale["error"]["code"] == "stale_revision"
    assert stale["error"]["details"] == {"expected": revision, "current": revision + 1}
    assert revision_of(pipe) == revision + 1


def test_an_unreadable_operation_record_is_outcome_unknown(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    """3.6: a key whose operation row does not decode is `outcome_unknown` and nothing runs;
    reconciliation lists it as unreadable."""
    pipe, project, revision = opened(painter, tmp_path, pipes)
    assert mutate(pipe, {"name": "A"}, "k-1", revision)["committed_revision"] == revision + 1
    pipe.call("project_close")
    with sqlite3.connect(project) as db:
        db.execute("UPDATE operation SET outcome = x'00' WHERE idempotency_key = 'k-1'")
    db.close()
    assert pipe.call("project_open", {"path": str(project)})["result"]["revision"] == revision + 1
    for expected in (revision, None):
        replay = mutate(pipe, {"name": "A"}, "k-1", expected)
        assert replay["error"]["code"] == "outcome_unknown"
        assert replay["error"]["details"] == {"key": "k-1", "committed_revision": revision + 1}
    assert revision_of(pipe) == revision + 1
    assert operations(pipe)["unreadable"] == ["k-1"]
