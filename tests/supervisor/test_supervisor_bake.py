"""MCP `bake_start` over the job ledger (phase3.3_baker-evidence-publication items 2.7, 3.3, 3.5 and
3.6; decision 355): the native bake job on the CPU baker (Embree), with Python disabled.

CPU only: the supervisors run `--gpu-backend vulkan` without `--allow-python`, so the worker has
no GPU device (`gpu_backend_unavailable` for GPU tools) while the CPU baker still bakes. Every
usage's parity is `pending-evidence`, so a bake that runs to its end is refused at its publication
(decision 001) and binds nothing; the receipts are in the job's error.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from tests.supervisor.conftest import BACKEND, Mcp, kill_pid, make_project, wait_until_gone

ARGS = ("--gpu-backend", BACKEND)
TERMINAL = ("succeeded", "failed", "cancelled", "interrupted")


def opened(painter: Path, tmp_path: Path, sessions: list[Mcp], log2: int) -> tuple[Mcp, int]:
    """A session (Python disabled) on the plane project, its bake set to `log2` (OutputSize) with
    the low mesh as its high mesh and absolute distances and no AO attenuation (the values the CPU
    baker implements); the revision after that."""
    project = make_project(painter, tmp_path)
    session = Mcp(painter, tmp_path, *ARGS)
    sessions.append(session)
    session.call("project_open", {"path": str(project), "wait": True})
    configured = session.call(
        "bake_configure",
        {
            "common": {"OutputSize": [log2, log2], "LowAsHigh": True, "RelativeScale": False},
            "per_baker": {"AO": {"Attenuation": "None", "MaxDistanceRelativeScale": False}},
        },
    )
    assert "error" not in configured, configured
    return session, revision_of(session)


def revision_of(session: Mcp) -> int:
    revision = session.call("project_inspect")["result"]["revision"]
    assert isinstance(revision, int)
    return revision


def status(session: Mcp, job_id: str) -> dict[str, Any]:
    result = session.call("job_status", {"job_id": job_id})["result"]
    assert isinstance(result, dict)
    return result


def until(session: Mcp, job_id: str, done: Any, timeout: float = 300.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        current = status(session, job_id)
        if done(current):
            return current
        assert time.monotonic() < deadline, f"job {job_id} stayed {current}: {session.log()}"
        time.sleep(0.05)


def ended(current: dict[str, Any]) -> bool:
    return current["status"] in TERMINAL


def start(session: Mcp, **arguments: Any) -> str:
    started = session.call("bake_start", arguments)
    assert "error" not in started, started
    assert started["result"]["status"] == "running"
    job_id = started["result"]["job_id"]
    assert isinstance(job_id, str)
    return job_id


def test_bake_start_refusals_and_a_bake_refused_at_publication(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.7, 3.6: the default configuration's bakers (Curvature, ID, ...) are refused before the
    bake starts; a GPU tool fails `gpu_backend_unavailable` on the worker without a device, while an
    AO bake runs on Embree to its publication, which decision 001 refuses: the job fails with each
    baker `refused`, names the receipt, and the revision does not move."""
    session, revision = opened(painter, tmp_path, sessions, 8)
    refused = session.call("bake_start", {"wait": True})
    assert refused["error"]["code"] == "capability_gap", refused
    assert "Curvature" in refused["error"]["message"]
    unknown = session.call("bake_start", {"sets": ["nope"], "usages": ["AO"], "wait": True})
    assert unknown["error"]["code"] == "invalid_arguments", unknown

    assert session.status()["gpu_status"] != "ready", "the CPU lane's backend has a device here"
    gpu = session.call("evaluate_channel", {"channel": "BaseColor"})
    assert gpu["error"]["code"] == "gpu_backend_unavailable", gpu
    assert gpu["error"]["details"]["backend"] == BACKEND

    baked = session.call("bake_start", {"usages": ["AO"], "wait": True})
    assert baked["error"]["code"] == "capability_gap", baked
    message = baked["error"]["message"]
    assert "pending-evidence (decision 001)" in message and "receipt " in message
    assert '"outcome":"refused"' in message and '"stopped":"before_publication"' in message
    assert baked["receipt"]["status"] == "failed"
    assert baked["receipt"]["job"]["committed"] is None
    assert revision_of(session) == revision
    assert session.close() == 0


def test_bake_start_cancelled_by_job_cancel(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """3.5: `bake_start` then `job_cancel` during the cast: the cancel is acknowledged at once, the
    job ends `cancelled`, stopped `before_commit`, nothing committed, the revision intact."""
    session, revision = opened(painter, tmp_path, sessions, 12)
    job_id = start(session, usages=["AO"])
    until(session, job_id, lambda current: current["progress"] > 0)
    acknowledged = session.call("job_cancel", {"job_id": job_id})["result"]
    assert acknowledged["cancel"] == "requested"
    assert acknowledged["worker"] == {"job_id": job_id, "acknowledged": True, "state": "running"}
    assert until(session, job_id, ended)["status"] == "cancelled"
    stopped = session.call("job_result", {"job_id": job_id})
    assert stopped["error"]["code"] == "cancelled"
    assert stopped["error"]["details"]["stopped"] == "before_commit"
    assert stopped["receipt"]["job"]["committed"] is None
    assert stopped["receipt"]["job"]["cancel_requested"] is True
    assert revision_of(session) == revision
    late = session.call("job_cancel", {"job_id": job_id})["result"]
    assert late["cancel"] == "already_ended" and late["status"] == "cancelled"
    assert session.close() == 0


def test_worker_killed_during_a_bake(painter: Path, tmp_path: Path, sessions: list[Mcp]) -> None:
    """3.3: the worker dies during a bake: the job is `interrupted`, resolved from the operation
    rows as not committed; no partial bake is bound and the last committed revision is intact."""
    session, revision = opened(painter, tmp_path, sessions, 12)
    job_id = start(session, usages=["AO"])
    until(session, job_id, lambda current: current["progress"] > 0)
    worker = session.status()["worker_pid"]
    kill_pid(worker)
    assert wait_until_gone(worker)
    interrupted = until(session, job_id, ended)
    assert interrupted["status"] == "interrupted"
    assert interrupted["resolution"] == {"committed": False, "source": "operation_row"}
    assert revision_of(session) == revision
    sets = session.call("set_list")["result"]["texture_sets"]
    assert all(not s.get("mesh_maps") for s in sets), sets
    assert session.close() == 0
