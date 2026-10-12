"""Long jobs through `UzPainter.exe --mcp` and in the single-process `run` path
(python/uzpainter_supervisor/admission.py, src/supervisor/worker.cpp, src/python/jobs.h; task
phase2.3_supervisor-jobs items 3.1-3.5; decisions 140, 141).

CPU only: the supervisors run `--gpu-backend vulkan` with `--test-faults` (Debug build), so the
long typed `test_job` exists (N cancellable steps, one fill layer committed with its operation
row at step `commit_at`). Each supervisor writes its own ledger under the test's folder.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from tests.supervisor.conftest import (
    BACKEND,
    PLANE,
    Mcp,
    kill_pid,
    make_project,
    run_script,
    wait_until_gone,
)

BASE = ("--gpu-backend", BACKEND, "--allow-python", "--test-faults")
TERMINAL = ("succeeded", "failed", "cancelled", "interrupted")
# Painter's json_config of one 16-bit height PNG of the plane fixture (tests/python's export).
EXPORT_CONFIG: dict[str, Any] = {
    "exportShaderParams": False,
    "defaultExportPreset": "height",
    "exportPresets": [
        {
            "name": "height",
            "maps": [
                {
                    "fileName": "$textureSet_height",
                    "channels": [
                        {
                            "destChannel": "L",
                            "srcChannel": "L",
                            "srcMapType": "documentMap",
                            "srcMapName": "height",
                        }
                    ],
                    "parameters": {
                        "fileFormat": "png",
                        "bitDepth": "16",
                        "dithering": False,
                        "paddingAlgorithm": "infinite",
                    },
                }
            ],
        }
    ],
    "exportList": [{"rootPath": "uzp_plane"}],
}


def opened(
    painter: Path, tmp_path: Path, sessions: list[Mcp], **kwargs: Any
) -> tuple[Mcp, Path, int]:
    project = make_project(painter, tmp_path)
    session = Mcp(painter, tmp_path, *BASE, **kwargs)
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


def status(session: Mcp, job_id: str) -> dict[str, Any]:
    result = session.call("job_status", {"job_id": job_id})["result"]
    assert isinstance(result, dict)
    return result


def until(session: Mcp, job_id: str, done: Any, timeout: float = 120.0) -> dict[str, Any]:
    """The job's status once `done(status)` holds."""
    deadline = time.monotonic() + timeout
    while True:
        current = status(session, job_id)
        if done(current):
            return current
        assert time.monotonic() < deadline, f"job {job_id} stayed {current}: {session.log()}"
        time.sleep(0.05)


def ended(current: dict[str, Any]) -> bool:
    return current["status"] in TERMINAL


def start_job(session: Mcp, steps: int, step_ms: int, commit_at: int | None) -> str:
    arguments: dict[str, Any] = {"name": "Job", "steps": steps, "step_ms": step_ms}
    if commit_at is not None:
        arguments["commit_at"] = commit_at
    started = session.call("test_job", arguments)
    assert started["result"]["status"] == "running"
    job_id = started["result"]["job_id"]
    assert started["receipt"]["job_id"] == job_id and started["receipt"]["status"] == "running"
    assert isinstance(job_id, str)
    return job_id


def job_events(session: Mcp, token: str) -> list[dict[str, Any]]:
    return [
        message["params"]["_meta"]["uzpainter/job"]
        for message in session.notifications
        if message.get("method") == "notifications/progress"
        and message["params"]["progressToken"] == token
    ]


def test_long_jobs_return_at_once_or_stream_their_progress_with_wait(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """3.1, 2.1, 2.5: `project_open` and `export` with `wait=true` stream
    `{job_id, status, progress, message}` and return the terminal receipt; without `wait` a long
    call returns `{job_id, status: running}` at once, holds the project's slot (`busy`) and is
    followed with `job_status`, `job_result` and `job_list`; job ids are unique."""
    project = make_project(painter, tmp_path)
    session = Mcp(painter, tmp_path, *BASE)
    sessions.append(session)
    tools = {tool["name"]: tool for tool in session.request("tools/list", {})["tools"]}
    for name in ("project_open", "export", "test_job"):
        assert tools[name]["inputSchema"]["properties"]["wait"]["type"] == "boolean"
    assert "wait" not in tools["project_inspect"]["inputSchema"]["properties"]

    opening = session.call(
        "project_open", {"path": str(project), "wait": True}, meta={"progressToken": "open"}
    )
    revision = opening["result"]["revision"]
    receipt = opening["receipt"]
    assert receipt["status"] == "succeeded" and receipt["job"]["status"] == "succeeded"
    assert receipt["job"]["committed"] is None and receipt["job"]["stopped"] is None
    events = job_events(session, "open")
    assert [event["job_id"] for event in events] == [receipt["job_id"]] * len(events)
    assert events[0]["status"] == "running" and events[-1]["status"] == "succeeded"
    assert any(event["message"].startswith("opening ") for event in events)
    assert events[-1]["progress"] == 1.0

    export_dir = tmp_path / "export"
    exported = session.call(
        "export",
        {"config": {**EXPORT_CONFIG, "exportPath": export_dir.as_posix()}, "wait": True},
        meta={"progressToken": "export"},
    )
    assert "error" not in exported, exported
    job = exported["receipt"]["job"]
    assert exported["receipt"]["status"] == "succeeded"
    assert job["committed"]["generation"] == exported["result"]["generation"]
    assert job["committed"]["revision"] == revision and job["stopped"] is None
    assert (export_dir / "current.json").is_file()
    events = job_events(session, "export")
    progress = [event["progress"] for event in events]
    assert progress == sorted(progress) and progress[-1] == 1.0
    assert any(event["message"] == "evaluating uzp_plane_height.png" for event in events)
    assert events[-1]["status"] == "succeeded"

    job_id = start_job(session, steps=10, step_ms=100, commit_at=None)
    busy = session.call("test_job", {"name": "Other", "steps": 1})
    assert busy["error"]["code"] == "busy" and busy["error"]["details"] == {"job_id": job_id}
    running = until(session, job_id, lambda current: current["progress"] > 0)
    assert running["status"] == "running" and running["tool"] == "test_job"
    assert session.call("job_result", {"job_id": job_id})["error"]["code"] == "job_running"
    until(session, job_id, ended)
    result = session.call("job_result", {"job_id": job_id})
    assert result["receipt"]["status"] == "succeeded" and result["receipt"]["job"]["no_op"] is True
    assert result["result"]["status"] == "no_op" and revision_of(session) == revision

    listed = session.call("job_list")["result"]["jobs"]
    ids = [entry["job_id"] for entry in listed]
    assert len(ids) == len(set(ids)) >= 3
    assert {opening["receipt"]["job_id"], exported["receipt"]["job_id"], job_id} <= set(ids)
    assert session.call("job_status", {"job_id": "job-x"})["error"]["code"] == "unknown_job"
    assert session.close() == 0


def test_cancel_before_and_after_commit(painter: Path, tmp_path: Path, sessions: list[Mcp]) -> None:
    """3.2, 2.3, 2.6: a cancel is acknowledged at once; a job stopped before its commit point
    committed nothing; one stopped after it keeps its revision and says so; neither is a
    success. A success that changed nothing is `no_op`, distinct from a failure."""
    session, _, revision = opened(painter, tmp_path, sessions)

    before = start_job(session, steps=40, step_ms=50, commit_at=30)
    until(session, before, lambda current: current["progress"] > 0)
    acknowledged = session.call("job_cancel", {"job_id": before})["result"]
    assert acknowledged["cancel"] == "requested"
    assert acknowledged["worker"] == {"job_id": before, "acknowledged": True, "state": "running"}
    assert until(session, before, ended)["status"] == "cancelled"
    stopped = session.call("job_result", {"job_id": before})
    assert stopped["error"]["code"] == "cancelled"
    assert stopped["error"]["details"]["stopped"] == "before_commit"
    assert stopped["receipt"]["status"] == "cancelled"
    assert stopped["receipt"]["job"]["committed"] is None
    assert stopped["receipt"]["job"]["cancel_requested"] is True
    assert revision_of(session) == revision

    after = start_job(session, steps=40, step_ms=50, commit_at=2)
    committed = until(session, after, lambda current: current["committed"] is not None)
    assert committed["committed"] == {"revision": revision + 1}
    assert session.call("job_cancel", {"job_id": after})["result"]["cancel"] == "requested"
    until(session, after, ended)
    stopped = session.call("job_result", {"job_id": after})
    assert stopped["error"]["code"] == "cancelled"
    assert stopped["error"]["details"] == {
        "job_id": after,
        "stopped": "after_commit",
        "committed": {"revision": revision + 1},
        "committed_revision": revision + 1,
    }
    assert stopped["receipt"]["status"] == "cancelled"
    assert stopped["receipt"]["committed_revision"] == revision + 1
    assert revision_of(session) == revision + 1

    late = session.call("job_cancel", {"job_id": after})["result"]
    assert late["cancel"] == "already_ended" and late["status"] == "cancelled"
    assert late["job"]["stopped"] == "after_commit"

    # A no-op succeeds; a stale precondition fails, and neither changes the project.
    noop = session.call("test_job", {"name": "N", "steps": 1, "wait": True})
    assert noop["receipt"]["status"] == "succeeded" and noop["receipt"]["job"]["no_op"] is True
    stale = session.call(
        "test_job", {"name": "S", "steps": 1, "commit_at": 0, "expected_revision": 0, "wait": True}
    )
    assert stale["error"]["code"] == "stale_revision" and stale["receipt"]["status"] == "failed"
    done = session.call("test_job", {"name": "D", "steps": 2, "commit_at": 0, "wait": True})
    assert done["receipt"]["status"] == "succeeded" and done["receipt"]["job"]["no_op"] is False
    assert done["result"]["status"] == "committed"
    assert revision_of(session) == revision + 2
    assert session.close() == 0


@pytest.mark.settling("worker_killed_during_long_job")
def test_a_worker_killed_during_a_long_job_is_interrupted_and_resolved(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """3.3, 2.4: the worker dies during a long mutating job; the job is `interrupted` and its
    outcome is resolved from the operation rows the relaunched worker's reconciliation reads,
    after and before the commit point; the job never runs again."""
    session, _, revision = opened(painter, tmp_path, sessions)

    after = start_job(session, steps=100, step_ms=100, commit_at=2)
    until(session, after, lambda current: current["committed"] is not None)
    kill_pid(session.status()["worker_pid"])
    interrupted = until(session, after, ended)
    assert interrupted["status"] == "interrupted"
    assert interrupted["resolution"] == {
        "committed": True,
        "committed_revision": revision + 1,
        "source": "operation_row",
    }
    assert interrupted["committed_revision"] == revision + 1
    result = session.call("job_result", {"job_id": after})
    assert result["error"]["code"] == "interrupted"
    assert result["receipt"]["resolution"]["committed"] is True
    assert revision_of(session) == revision + 1

    before = start_job(session, steps=100, step_ms=100, commit_at=90)
    until(session, before, lambda current: current["progress"] > 0)
    old = session.status()["worker_pid"]
    kill_pid(old)
    assert wait_until_gone(old)
    interrupted = until(session, before, ended)
    assert interrupted["status"] == "interrupted"
    assert interrupted["resolution"] == {"committed": False, "source": "operation_row"}
    assert revision_of(session) == revision + 1
    assert len(session.status()["recoveries"]) == 2
    assert session.close() == 0


def test_terminal_states_are_read_from_the_ledger_after_a_restart(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """3.4: a restarted supervisor reads finished jobs from the ledger; a job a killed
    supervisor left running is `interrupted` with an unknown outcome, which the next
    reconciliation of its project resolves from its operation row."""
    session, project, revision = opened(painter, tmp_path, sessions)
    done = session.call("test_job", {"name": "A", "steps": 1, "commit_at": 0, "wait": True})
    done_id = done["receipt"]["job_id"]
    cancelled = start_job(session, steps=50, step_ms=50, commit_at=40)
    session.call("job_cancel", {"job_id": cancelled})
    until(session, cancelled, ended)
    assert session.close() == 0

    restarted = Mcp(painter, tmp_path, *BASE, ledger=session.ledger)
    sessions.append(restarted)
    assert restarted.call("job_result", {"job_id": done_id}) == done
    assert status(restarted, done_id)["status"] == "succeeded"
    assert status(restarted, cancelled)["status"] == "cancelled"
    listed = {entry["job_id"]: entry for entry in restarted.call("job_list")["result"]["jobs"]}
    assert listed[done_id]["committed_revision"] == revision + 1
    assert listed[cancelled]["job"]["stopped"] == "before_commit"

    restarted.call("project_open", {"path": str(project), "wait": True})
    orphan = start_job(restarted, steps=200, step_ms=100, commit_at=1)
    until(restarted, orphan, lambda current: current["committed"] is not None)
    worker = restarted.status()["worker_pid"]
    restarted.process.kill()
    restarted.process.wait(30)
    assert wait_until_gone(worker)

    third = Mcp(painter, tmp_path, *BASE, ledger=session.ledger)
    sessions.append(third)
    swept = status(third, orphan)
    assert swept["status"] == "interrupted"
    assert swept["resolution"] == {"committed": None, "source": "supervisor_ended"}
    third.call("project_open", {"path": str(project), "wait": True})
    assert revision_of(third) == revision + 2
    assert status(third, orphan)["resolution"] == {
        "committed": True,
        "committed_revision": revision + 2,
        "source": "operation_row",
    }
    assert third.close() == 0


def test_jobs_in_the_single_process_run_path(painter: Path, tmp_path: Path) -> None:
    """3.5, 2.5: `uzpainter.jobs` in `UzPainter.exe run`: an export's receipt names the
    generation it committed; a queued export cancelled stops before its commit point and is not
    a success; `list()` holds both with their messages."""
    config = json.dumps({**EXPORT_CONFIG, "exportPath": (tmp_path / "export").as_posix()})
    result = run_script(
        painter,
        tmp_path,
        f"""
        import json
        from uzpainter import application, export, jobs, project
        project.create({PLANE.as_posix()!r}, project.Settings(default_texture_resolution=256))
        config = json.loads({config!r})
        done = export.start(config)
        out = done.wait()
        with application.disable_engine_computations():
            queued = export.start(config)
            queued_status = queued.status
            acknowledged = queued.cancel()
        try:
            queued.wait()
            raised = None
        except Exception as error:
            raised = type(error).__name__
        result = {{
            "out": out,
            "done": done.receipt(),
            "message": done.message,
            "queued_status": queued_status,
            "acknowledged": acknowledged,
            "cancelled": queued.receipt(),
            "raised": raised,
            "listed": [[job.id, job.status] for job in jobs.list()],
        }}
        """,
    )
    done = result["done"]
    assert done["status"] == "succeeded" and done["kind"] == "export"
    assert done["committed"]["generation"] == result["out"]["generation"]
    assert done["stopped"] is None and done["cancel_requested"] is False
    assert done["no_op"] is False and done["progress"] == 1.0
    assert result["message"].startswith("published generation ")
    assert result["queued_status"] == "queued" and result["acknowledged"] is True
    cancelled = result["cancelled"]
    assert cancelled["status"] == "cancelled" and cancelled["stopped"] == "before_commit"
    assert cancelled["committed"] is None and cancelled["cancel_requested"] is True
    assert result["raised"] == "RuntimeError"
    assert result["listed"] == [[done["id"], "succeeded"], [cancelled["id"], "cancelled"]]
