"""The settling cases of `docs/architecture/02-runtime-topology.md` §7 that no child task
covers, end to end through the supervisor's stdio MCP session, and the per-call overhead against
the single-process `run` path (task phase2.4_supervisor-worker items 2.1, 2.2, 3.1, 3.5-3.7;
decisions 150, 151).

The other §7 cases are the children's MCP tests, tagged with `settling` (test_supervisor_mcp.py,
test_supervisor_admission.py, test_supervisor_jobs.py, test_supervisor_gpu.py). The supervisors
start on `UZP_SUPERVISOR_BACKEND`; without it the CPU lane uses `--test-gpu-unavailable` with
`--test-faults` (Debug build, decisions 120 and 151).
"""

from __future__ import annotations

import itertools
import shutil
import sqlite3
import statistics
import time
from pathlib import Path
from typing import Any

import pytest

from tests.supervisor.conftest import (
    BACKEND,
    GPU_UNAVAILABLE_ARGS,
    INSERT_FILL,
    Mcp,
    Settling,
    make_project,
    run_script,
    wait_until_gone,
)
from tests.supervisor.test_supervisor_jobs import EXPORT_CONFIG

BASE = (*GPU_UNAVAILABLE_ARGS, "--gpu-backend", BACKEND, "--allow-python", "--test-faults")


def opened(
    painter: Path, tmp_path: Path, sessions: list[Mcp], *args: str, **kwargs: Any
) -> tuple[Mcp, Path, int]:
    project = kwargs.pop("project", None) or make_project(painter, tmp_path)
    session = Mcp(painter, tmp_path, *args, **kwargs)
    sessions.append(session)
    revision = session.call("project_open", {"path": str(project), "wait": True})["result"][
        "revision"
    ]
    assert isinstance(revision, int)
    return session, project, revision


def revision_of(session: Mcp) -> int:
    revision = session.call("project_inspect")["result"]["revision"]
    assert isinstance(revision, int)
    return revision


def mutate(session: Mcp, name: str, key: str, expected: int, **extra: Any) -> dict[str, Any]:
    return session.call(
        "test_mutation",
        {"name": name, "idempotency_key": key, "expected_revision": expected, **extra},
    )


def operation_rows(project: Path, key: str) -> int:
    """The project file's operation rows of `key`, read with SQLite directly."""
    with sqlite3.connect(project) as db:
        count = db.execute(
            "SELECT count(*) FROM operation WHERE idempotency_key = ?", (key,)
        ).fetchone()[0]
    db.close()
    assert isinstance(count, int)
    return count


@pytest.mark.parametrize(
    ("fault", "mode"),
    [
        pytest.param(
            "kill_during_save",
            "incremental",
            marks=pytest.mark.settling("worker_killed_during_save"),
        ),
        pytest.param(
            "kill_during_compaction",
            "full",
            marks=pytest.mark.settling("worker_killed_during_compaction"),
        ),
    ],
)
def test_worker_killed_during_a_save(
    painter: Path, tmp_path: Path, sessions: list[Mcp], fault: str, mode: str
) -> None:
    """3.1: the worker ends inside a save, at the first page write of its checkpoint commit or
    while `VACUUM INTO` writes the compacted copy (decision 151). The save is answered
    `interrupted`, the session stays alive, the relaunched worker holds the last committed
    revision, and the store is the one before the torn commit or the one with the committed
    checkpoint and no compaction leftovers."""
    session, project, revision = opened(painter, tmp_path, sessions, *BASE)
    assert session.call("project_save", {})["result"]["named"] == revision
    assert mutate(session, "A", "k-1", revision)["committed_revision"] == revision + 1
    old = session.status()["worker_pid"]

    assert session.call("test_fault", {"fault": fault})["result"] == {"armed": fault}
    killed = session.call("project_save", {"mode": mode})
    error = killed["error"]
    assert error["code"] == "interrupted", killed
    assert error["details"]["cause"] == "terminated"
    assert error["details"]["committed_revision"] == revision + 1
    assert wait_until_gone(old)

    assert revision_of(session) == revision + 1
    status = session.status()
    (recovery,) = status["recoveries"]
    assert recovery["old_pid"] == old and recovery["exit_code"] == 77
    assert recovery["revision"] == revision + 1 and recovery["recovery_ms"] > 0
    for leftover in ("compact", "vacuum"):
        assert not Path(f"{project}.{leftover}").exists()
    assert operation_rows(project, "k-1") == 1

    # The checkpoint the killed save named: none after the torn commit (rolled back from the hot
    # journal), the current revision once the commit was durable and the compaction died.
    named = revision if fault == "kill_during_save" else revision + 1
    assert mutate(session, "B", "k-2", revision + 1)["committed_revision"] == revision + 2
    saved = session.call("project_save", {"mode": mode})["result"]
    assert saved == {"current": revision + 2, "named": revision + 2, "previous": named}
    assert revision_of(session) == revision + 2
    assert len(session.status()["recoveries"]) == 1


@pytest.mark.settling("client_disconnect_reconnect")
def test_client_disconnect_and_reconnect(
    painter: Path, tmp_path: Path, sessions: list[Mcp], settling: Settling
) -> None:
    """3.5: on stdio a disconnect ends the session: the client closes stdin while a long mutating
    job runs before its commit point; the supervisor ends its worker, which commits nothing
    further. A new session on the same ledger reopens the project, its retry of the same key and
    precondition commits once and a second retry returns the stored outcome; the lease is the
    new session's and the old job is terminal. HTTP reconnects to a running supervisor are
    phase2.5's (decision 150)."""
    first, project, revision = opened(painter, tmp_path, sessions, *BASE)
    assert mutate(first, "A", "k-1", revision)["committed_revision"] == revision + 1
    job = {
        "name": "J",
        "steps": 40,
        "step_ms": 100,
        "commit_at": 30,
        "wait": True,
        "idempotency_key": "k-2",
        "expected_revision": revision + 1,
    }
    first.send("tools/call", {"name": "test_job", "arguments": job})
    status = first.status()
    while not status["running"]:
        status = first.status()
    job_id = status["running"][status["project_uuid"]]
    assert status["lease"]["holder"] == f"stdio:{first.process.pid}"
    worker = status["worker_pid"]

    assert first.process.stdin is not None
    first.process.stdin.close()
    assert first.process.wait(120) == 0, first.log()
    assert wait_until_gone(worker)
    assert operation_rows(project, "k-2") == 0  # nothing committed after the disconnect

    started = time.perf_counter()
    second, _, reopened = opened(
        painter, tmp_path, sessions, *BASE, project=project, ledger=first.ledger
    )
    settling.metric("reconnect_ms", (time.perf_counter() - started) * 1000)
    assert reopened == revision + 1
    # The old job is terminal and committed nothing: `interrupted` when the pipe closed first,
    # `cancelled` before its commit point when the ended wait's cancel reached the worker first.
    old = second.call("job_status", {"job_id": job_id})["result"]
    assert old["status"] in ("interrupted", "cancelled"), old
    assert old["committed"] is None and not (old.get("resolution") or {}).get("committed"), old
    lease = second.status()["lease"]
    assert lease is None or lease["holder"] != f"stdio:{first.process.pid}"

    retried = second.call("test_job", job)
    assert retried["receipt"]["status"] == "succeeded", retried
    assert retried["committed_revision"] == revision + 2
    again = second.call("test_job", job)
    assert again["receipt"]["admission"] == "stored_outcome", again
    assert again["committed_revision"] == revision + 2
    assert revision_of(second) == revision + 2
    assert operation_rows(project, "k-2") == 1
    assert second.status()["lease"]["holder"] == f"stdio:{second.process.pid}"
    assert second.call("job_status", {"job_id": job_id})["result"]["status"] == old["status"]
    assert second.close() == 0


@pytest.mark.settling("failure_comparison")
def test_single_call_script_and_transaction_failures(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """3.6, 02 §5: a failed single call commits nothing and writes no operation row; a script
    whose third API call raises keeps its two committed calls and reports them with the last
    committed revision and the traceback; a native `Transaction` that raises commits nothing."""
    session, project, revision = opened(painter, tmp_path, sessions, *BASE)

    single = mutate(session, "F", "k-single", revision, fail=True)
    assert single["error"]["code"] == "call_failed", single
    assert single["error"]["details"]["type"] == "ValueError"
    assert revision_of(session) == revision
    assert operation_rows(project, "k-single") == 0

    calls = (
        "from uzpainter import layerstack as ls, textureset as ts\n"
        "top = lambda: ls.InsertPosition.from_textureset_stack(ts.get_active_stack())\n"
        "{body}"
        "    ls.insert_fill(top())\n"
        "    ls.insert_fill(top())\n"
        "    ls.get_node_by_uid(987654321)\n"
    )
    script = session.call(
        "run_python",
        {
            "code": calls.format(body="if True:\n"),
            "idempotency_key": "k-script",
            "expected_revision": revision,
        },
    )
    error = script["error"]
    assert error["code"] == "script_failed", script
    details = error["details"]
    assert details["error"]["type"] == "ValueError"
    assert 'File "<run_python>", line 6' in details["error"]["traceback"]
    assert [call["status"] for call in details["committed"]] == ["committed", "committed"]
    assert [call["revision"] for call in details["committed"]] == [revision + 1, revision + 2]
    assert all(len(call["created"]) == 1 for call in details["committed"])
    assert details["last_committed_revision"] == revision + 2
    assert revision_of(session) == revision + 2

    transaction = session.call(
        "run_python",
        {
            "code": "import uzpainter\n"
            + calls.format(body='with uzpainter.Transaction("two layers"):\n'),
            "idempotency_key": "k-transaction",
            "expected_revision": revision + 2,
        },
    )
    error = transaction["error"]
    assert error["code"] == "script_failed", transaction
    assert error["details"]["error"]["type"] == "ValueError"
    assert error["details"]["committed"] == []
    assert error["details"]["last_committed_revision"] is None
    assert revision_of(session) == revision + 2
    assert session.status()["recoveries"] == []


@pytest.mark.settling("python_disabled")
def test_python_disabled_through_mcp(painter: Path, tmp_path: Path, sessions: list[Mcp]) -> None:
    """3.7: without `--allow-python`, `run_python` is not listed and a call of it is rejected at
    the IPC boundary with `python_disabled`, while the other tools serve."""
    session, _, revision = opened(
        painter, tmp_path, sessions, *GPU_UNAVAILABLE_ARGS, "--gpu-backend", BACKEND
    )
    names = {tool["name"] for tool in session.request("tools/list", {})["tools"]}
    assert "run_python" not in names and "project_inspect" in names
    refused = session.call(
        "run_python", {"code": INSERT_FILL, "idempotency_key": "k-1", "expected_revision": revision}
    )
    assert refused["error"]["code"] == "python_disabled", refused
    assert revision_of(session) == revision
    status = session.status()
    assert status["python"] == "disabled" and status["recoveries"] == []


@pytest.mark.settling("gpu_backend_unavailable")
@pytest.mark.parametrize("backend", ["dx12", "vulkan"])
def test_unavailable_backend_through_mcp(
    painter: Path, tmp_path: Path, sessions: list[Mcp], backend: str
) -> None:
    """3.7: a worker without a device answers a GPU call `gpu_backend_unavailable` before
    mutating, while the CPU evaluator's export, a save and a mutation still run."""
    session, _, revision = opened(
        painter,
        tmp_path,
        sessions,
        "--gpu-backend",
        backend,
        "--test-gpu-unavailable",
        "--allow-python",
        "--test-faults",
    )
    assert session.status()["gpu_status"] == "unavailable"
    refused = session.call("evaluate_channel", {"channel": "BaseColor"})
    error = refused["error"]
    assert error["code"] == "gpu_backend_unavailable", refused
    assert error["details"]["backend"] == backend and error["details"]["reason"]
    assert revision_of(session) == revision
    export_dir = tmp_path / "export"
    exported = session.call(
        "export", {"config": {**EXPORT_CONFIG, "exportPath": export_dir.as_posix()}, "wait": True}
    )
    assert exported["receipt"]["status"] == "succeeded", exported
    assert (export_dir / "current.json").is_file()
    assert session.call("project_save", {})["result"]["named"] == revision
    assert mutate(session, "A", "k-1", revision)["committed_revision"] == revision + 1
    assert session.status()["recoveries"] == []


READ = "from uzpainter import project\nresult = project.revision()\n"
OVERHEAD_CALLS = 50
WARM_UP = 3


@pytest.mark.settling()
def test_per_call_overhead(
    painter: Path, tmp_path: Path, sessions: list[Mcp], settling: Settling
) -> None:
    """2.2: the same snippets (a read and a fill-layer insert) as `run_python` calls through the
    supervisor and executed in one single-process `run` script, on copies of one project at the
    same revision; the overhead is each MCP round trip minus the in-process median, recorded
    without a threshold (decision 150)."""
    project = make_project(painter, tmp_path)
    copy = tmp_path / "copy" / "plane.uzp"
    copy.parent.mkdir()
    shutil.copy(project, copy)
    snippets = {"read": READ, "mutation": INSERT_FILL}

    in_process = run_script(
        painter,
        tmp_path,
        f"""
        import time
        from uzpainter import project
        project.open({copy.as_posix()!r})
        snippets = {snippets!r}

        def once(code):
            exec(compile(code, "<run_python>", "exec"), {{"__name__": "__main__"}})

        result = {{}}
        for name, code in snippets.items():
            for _ in range({WARM_UP}):
                once(code)
            samples = []
            for _ in range({OVERHEAD_CALLS}):
                start = time.perf_counter()
                once(code)
                samples.append((time.perf_counter() - start) * 1000)
            result[name] = samples
        """,
        backend=BACKEND,
    )

    session, _, revision = opened(painter, tmp_path, sessions, *BASE, project=project)
    keys = itertools.count()

    def call(code: str) -> float:
        nonlocal revision
        start = time.perf_counter()
        reply = session.call(
            "run_python",
            {"code": code, "idempotency_key": f"k-{next(keys)}", "expected_revision": revision},
        )
        elapsed = (time.perf_counter() - start) * 1000
        assert "result" in reply, reply
        revision = reply["committed_revision"]
        return elapsed

    for name, code in snippets.items():
        for _ in range(WARM_UP):
            call(code)
        through_mcp = [call(code) for _ in range(OVERHEAD_CALLS)]
        run_median = statistics.median(in_process[name])
        overhead = [sample - run_median for sample in through_mcp]
        settling.overhead(
            {
                "backend": BACKEND,
                "snippet": name,
                "calls": OVERHEAD_CALLS,
                "mcp_median_ms": round(statistics.median(through_mcp), 3),
                "run_median_ms": round(run_median, 3),
                "overhead_median_ms": round(statistics.median(overhead), 3),
                "overhead_p90_ms": round(statistics.quantiles(overhead, n=10)[8], 3),
                "overhead_max_ms": round(max(overhead), 3),
                **Settling.stamp(),
            }
        )
    assert revision_of(session) == revision
