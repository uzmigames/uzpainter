"""The supervisor through its stdio MCP session (src/supervisor/supervisor.h,
python/uzpainter_supervisor/; task phase2.1_supervisor-ipc-worker items 2.1, 2.2, 2.4, 2.8, 2.10,
3.1, 3.2, 3.5).

CPU only: the supervisors run `--gpu-backend vulkan` (no device before Phase 3), with
`--test-faults` (the Debug build has the hooks, decision 120). The device-fault and stall cases
are in test_supervisor_gpu.py.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.supervisor.conftest import (
    BACKEND,
    INSERT_FILL,
    PLANE,
    Mcp,
    Pipe,
    kill_pid,
    make_project,
    pid_alive,
    wait_until_gone,
)

BASE = ("--gpu-backend", BACKEND, "--allow-python", "--test-faults")


def opened_session(
    painter: Path, tmp_path: Path, sessions: list[Mcp], env: dict[str, str] | None = None
) -> tuple[Mcp, int]:
    """A supervisor with the plane project open and one committed mutation; its revision."""
    project = make_project(painter, tmp_path)
    session = Mcp(painter, tmp_path, *BASE, env=env)
    sessions.append(session)
    revision = session.call("project_open", {"path": str(project), "wait": True})["result"][
        "revision"
    ]
    reply = session.call(
        "run_python", {"code": INSERT_FILL, "idempotency_key": "k-1", "expected_revision": revision}
    )
    assert reply["committed_revision"] == revision + 1, reply
    return session, revision + 1


def test_tools_are_forwarded_and_stdout_carries_protocol_frames_only(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.1, 2.2: the supervisor serves MCP on stdio and forwards the worker's tools; logs stay on
    stderr."""
    session = Mcp(painter, tmp_path, "--gpu-backend", "vulkan")
    sessions.append(session)
    tools = {tool["name"]: tool for tool in session.request("tools/list", {})["tools"]}
    assert set(tools) == {
        "supervisor_status",
        "wait_idle",
        "project_open",
        "project_close",
        "project_save",
        "project_inspect",
        "evaluate_channel",
        "snapshot_layer_tree",
        "diff_snapshots",
        "isolate_layer",
        "material_views",
        "region_stats",
        "display_get",
        "display_set",
        "shader_get",
        "shader_set",
        "camera_get",
        "camera_set",
        "export",
        "export_presets_list",
        "capture",
        "job_status",
        "job_result",
        "job_cancel",
        "job_list",
        # phase2.6's typed families and the supervisor's own (decisions 164, 165).
        "status",
        "capabilities",
        "batch",
        "project_create",
        "project_save_as",
        "project_recipe",
        "project_revert",
        "set_list",
        "set_resolution",
        "set_rename",
        "set_channels",
        "set_mesh_maps",
        "resource_import",
        "resource_list",
        "resource_search",
        "resource_replace",
        "assets_search",
        "layer_list",
        "layer_insert",
        "layer_set",
        "layer_delete",
        "layer_instantiate",
        "effect_insert",
        "effect_set",
        "mask_set",
        "source_set",
        "fill_set",
        "procedural_set",
        "anchor_list",
        "smart_material_insert",
        "smart_mask_insert",
        "smart_export",
        "sync_stack",
        "apply_smart",
        "bake_inspect",
        "bake_configure",
        "bake_set_mesh_inputs",
        "bake_start",
        "bake_capture_preset",
        "bake_apply_preset",
        "mesh_reload",
        "mesh_certificate",
    }
    assert tools["project_open"]["inputSchema"]["required"] == ["path"]
    assert tools["isolate_layer"]["inputSchema"]["required"] == ["uid", "channels", "path"]
    # The Diagnostics tools are reads (decision 136): admitted without a lease, key or precondition.
    for name in (
        "snapshot_layer_tree",
        "diff_snapshots",
        "isolate_layer",
        "material_views",
        "region_stats",
    ):
        assert tools[name]["annotations"]["readOnlyHint"] is True, name
        assert "idempotency_key" not in tools[name]["inputSchema"]["properties"], name
    inspected = session.call("project_inspect")
    assert inspected["result"] == {"open": False}
    assert inspected["receipt"]["project"] is None and inspected["receipt"]["job_id"] is None
    assert session.call("run_python", {"code": "1"})["error"]["code"] == "python_disabled"
    status = session.status()
    assert status["gpu_backend"] == "vulkan" and status["gpu_status"] == "unavailable"
    assert status["python"] == "disabled" and status["recoveries"] == []
    assert pid_alive(status["worker_pid"]) and status["worker_pid"] != session.process.pid
    assert session.stdout_is_protocol_only()
    assert "uzpainter supervisor: INFO" in session.log()
    assert session.close() == 0
    assert wait_until_gone(status["worker_pid"])


@pytest.mark.parametrize(
    ("override", "args", "message"),
    [
        (
            {"protocol": "uzp-ipc/0"},
            (),
            "protocol: requested 'uzp-ipc/1', worker reported 'uzp-ipc/0'",
        ),
        ({"gpu_backend": "dx12"}, (), "gpu_backend: requested 'vulkan', worker reported 'dx12'"),
        ({"python": "allowed"}, (), "python: requested 'disabled', worker reported 'allowed'"),
        (
            {"python": "disabled"},
            ("--allow-python",),
            "python: requested 'allowed', worker reported 'disabled'",
        ),
    ],
)
def test_handshake_mismatch_is_a_fatal_supervisor_error(
    painter: Path, tmp_path: Path, override: dict[str, Any], args: tuple[str, ...], message: str
) -> None:
    """2.4, 3.1: the supervisor admits no call to a worker whose handshake differs from what it
    requested and exits with status 4; the worker is ended."""
    session = Mcp(
        painter,
        tmp_path,
        "--gpu-backend",
        "vulkan",
        "--test-faults",
        *args,
        env={"UZP_TEST_HANDSHAKE": json.dumps(override)},
        initialize=False,
    )
    code = session.process.wait(120)
    session.close()
    log = session.log()
    assert code == 4, log
    assert "fatal supervisor error: worker handshake mismatch: " + message in log
    assert session.stdout_lines == []


def test_supervisor_usage_errors(painter: Path, tmp_path: Path) -> None:
    """2.1: the supervisor's command line; phase2.5's HTTP mode refuses a non-loopback bind
    without --allow-remote, and a --roots entry needs its kind."""
    for args in (
        ["--gpu-backend", "metal"],
        ["--mcp-http", "0.0.0.0:9000"],
        ["--token", "t"],
        ["--roots", "C:/"],
        ["--gpu-deadline-ms", "0"],
        ["--bogus"],
    ):
        process = subprocess.run(
            [str(painter), "--mcp", *args],
            capture_output=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        assert process.returncode == 2, (args, process.stderr)
        assert process.stdout == b""


def recovery_after(session: Mcp, count: int) -> dict[str, Any]:
    status = session.status()
    assert len(status["recoveries"]) == count, status
    recovery = status["recoveries"][-1]
    assert isinstance(recovery, dict)
    return recovery


@pytest.mark.settling("worker_killed_from_outside")
def test_worker_killed_from_outside(painter: Path, tmp_path: Path, sessions: list[Mcp]) -> None:
    """2.8, 3.2: TerminateProcess on the worker leaves the session alive; the next call is held
    until the relaunched worker has reopened the project at its last committed revision."""
    session, revision = opened_session(painter, tmp_path, sessions)
    before = session.status()
    kill_pid(before["worker_pid"])
    # A call racing the kill may reach the dying worker and is then answered `interrupted`
    # (test_native_fault_...); this one is sent once the supervisor has seen the death.
    assert wait_until_gone(before["worker_pid"])
    deadline = time.monotonic() + 120
    while not session.status()["recoveries"] and time.monotonic() < deadline:
        time.sleep(0.05)
    inspected = session.call("project_inspect")
    assert (
        inspected["result"]["revision"] == revision and inspected["committed_revision"] == revision
    )
    recovery = recovery_after(session, 1)
    assert recovery["cause"] == "terminated" and recovery["exit_code"] == 1
    assert recovery["minidump"] is None  # a process terminated from outside writes none
    assert (
        recovery["old_pid"] == before["worker_pid"] and recovery["new_pid"] != recovery["old_pid"]
    )
    assert recovery["revision"] == revision and recovery["recovery_ms"] > 0
    after = session.status()
    assert after["generation"] == before["generation"] + 1
    assert (after["gpu_backend"], after["python"]) == (BACKEND, "allowed")
    assert session.stdout_is_protocol_only()


@pytest.mark.parametrize(
    ("fault", "cause"),
    [
        pytest.param("abort", "abort", marks=pytest.mark.settling("native_abort")),
        pytest.param("seh", "native_fault", marks=pytest.mark.settling("native_access_violation")),
    ],
)
def test_native_fault_writes_a_minidump_and_relaunches(
    painter: Path, tmp_path: Path, sessions: list[Mcp], fault: str, cause: str
) -> None:
    """2.8, 3.2: abort() and an access violation in the worker: the call in flight is answered
    `interrupted` with the last committed revision and never re-sent; the crash handler's
    minidump is recorded; the same backend and Python policy are relaunched."""
    session, revision = opened_session(painter, tmp_path, sessions)
    old = session.status()["worker_pid"]
    reply = session.call("test_fault", {"fault": fault})
    error = reply["error"]
    assert error["code"] == "interrupted"
    assert error["details"]["cause"] == cause and error["details"]["committed_revision"] == revision
    recovery = recovery_after(session, 1)
    assert recovery["cause"] == cause and recovery["old_pid"] == old
    dump = Path(recovery["minidump"])
    assert dump.name == "crash.dmp" and dump.stat().st_size > 0
    report = json.loads((dump.parent / "crash.json").read_text(encoding="utf-8", errors="replace"))
    assert report  # the crash handler's structured report beside the dump
    assert session.call("project_inspect")["result"]["revision"] == revision
    assert session.status()["python"] == "allowed"
    # The relaunched worker serves mutations on from the reopened revision.
    reply = session.call(
        "run_python", {"code": INSERT_FILL, "idempotency_key": "k-2", "expected_revision": revision}
    )
    assert reply["committed_revision"] == revision + 1


def test_lost_acknowledgement_reports_the_durable_revision(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.8: a worker that commits and dies before its reply: the call is answered `interrupted`
    with the committed revision read back from the reopened file, and is not re-run."""
    session, revision = opened_session(painter, tmp_path, sessions)
    assert session.call("test_fault", {"fault": "kill_before_reply"})["result"] == {
        "armed": "kill_before_reply"
    }
    reply = session.call(
        "run_python", {"code": INSERT_FILL, "idempotency_key": "k-2", "expected_revision": revision}
    )
    assert reply["error"]["code"] == "interrupted"
    assert reply["error"]["details"]["committed_revision"] == revision + 1
    assert session.call("project_inspect")["result"]["revision"] == revision + 1


def lost_reply_after(session: Mcp, revision: int, code: str) -> dict[str, Any]:
    """Runs `code` as a mutation whose reply is lost (`kill_before_reply`); its `interrupted`
    error."""
    assert "result" in session.call("test_fault", {"fault": "kill_before_reply"})
    reply = session.call(
        "run_python", {"code": code, "idempotency_key": "k-2", "expected_revision": revision}
    )
    error = reply["error"]
    assert error["code"] == "interrupted", reply
    assert isinstance(error, dict)
    return error


def test_lost_reply_after_save_as_recovers_the_new_file(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.8: the script saves A as B, commits to B and loses its reply: the supervisor reopens B,
    which the worker reported before the reply was lost, at B's committed revision."""
    session, revision = opened_session(painter, tmp_path, sessions)
    a = Path(session.status()["project"])
    b = tmp_path / "saved-as" / "b.uzp"
    code = f"from uzpainter import project\nproject.save_as({b.as_posix()!r})\n" + INSERT_FILL
    error = lost_reply_after(session, revision, code)
    assert error["details"]["committed_revision"] == revision + 1
    status = session.status()
    assert Path(status["project"]) == b and status["revision"] == revision + 1
    inspected = session.call("project_inspect")["result"]
    assert Path(inspected["path"]) == b and inspected["revision"] == revision + 1
    assert Path(status["recoveries"][-1]["project"]) == b
    assert a != b


def test_lost_reply_after_switching_projects_recovers_the_new_project(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.8: the script closes A, opens B, commits to B and loses its reply: the supervisor
    reopens B at its committed revision, not A at A's."""
    other = tmp_path / "other"
    other.mkdir()
    b = make_project(painter, other)
    session, revision = opened_session(painter, tmp_path, sessions)
    a = Path(session.status()["project"])
    b_revision = run_revision(session, b)
    code = (
        f"from uzpainter import project\nproject.close()\nproject.open({b.as_posix()!r})\n"
        + INSERT_FILL
    )
    error = lost_reply_after(session, revision, code)
    assert error["details"]["committed_revision"] == b_revision + 1
    status = session.status()
    assert Path(status["project"]) == b and status["revision"] == b_revision + 1
    inspected = session.call("project_inspect")["result"]
    assert Path(inspected["path"]) == b and inspected["revision"] == b_revision + 1
    assert a != b


def test_lost_reply_of_an_untitled_project_recovers_it_untitled(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.8: a script creates an untitled project, commits to it and loses its reply: the
    supervisor reopens its temporary store as the same untitled project at its revision."""
    session = Mcp(painter, tmp_path, *BASE)
    sessions.append(session)
    assert "result" in session.call("test_fault", {"fault": "kill_before_reply"})
    code = (
        "from uzpainter import project\n"
        f"project.create({PLANE.as_posix()!r}, project.Settings(default_texture_resolution=256))\n"
        + INSERT_FILL
    )
    reply = session.call(
        "run_python", {"code": code, "idempotency_key": "k-1", "expected_revision": 0}
    )
    error = reply["error"]
    assert error["code"] == "interrupted", reply
    assert error["details"]["committed_revision"] == 2  # create, then the fill
    status = session.status()
    assert status["untitled"] is True and status["revision"] == 2
    assert Path(status["project"]).name == "Untitled.uzp"
    inspected = session.call("project_inspect")["result"]
    assert inspected["open"] and inspected["path"] is None and inspected["revision"] == 2
    still_untitled = session.call(
        "run_python",
        {
            "code": "from uzpainter import project\nresult = project.file_path()",
            "idempotency_key": "k-2",
            "expected_revision": 2,
        },
    )
    assert still_untitled["result"]["result"] is None


def test_lost_reply_after_a_relative_save_as_keeps_the_path_it_resolved_to(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.8: `save_as` with a relative path, then a change of directory: the durable store is the
    file the call resolved to, not one under the final working directory."""
    session, revision = opened_session(painter, tmp_path, sessions)
    first = tmp_path / "first"
    later = tmp_path / "later"
    first.mkdir()
    later.mkdir()
    code = (
        "import os\nfrom uzpainter import project\n"
        f"os.chdir({first.as_posix()!r})\n"
        "project.save_as('relative.uzp')\n"
        f"os.chdir({later.as_posix()!r})\n" + INSERT_FILL
    )
    error = lost_reply_after(session, revision, code)
    assert error["details"]["committed_revision"] == revision + 1
    status = session.status()
    assert Path(status["project"]) == first / "relative.uzp"
    assert not (later / "relative.uzp").exists()
    assert session.call("project_inspect")["result"]["revision"] == revision + 1


def test_lost_reply_after_opening_a_bundle_directory_recovers_its_imported_file(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.8: opening a bundle directory imports it into `<dir>.uzp`; after a lost reply the
    supervisor reopens that imported file, not the bundle (whose import target now exists)."""
    source = make_project(painter, tmp_path)
    bundle = tmp_path / "bundle"
    exported = subprocess.run(
        [str(painter), "export-bundle", str(source), str(bundle)],
        capture_output=True,
        timeout=300,
        check=False,
    )
    assert exported.returncode == 0, exported.stdout + exported.stderr
    session = Mcp(painter, tmp_path, *BASE)
    sessions.append(session)
    opened = session.call("project_open", {"path": str(bundle), "wait": True})["result"]
    imported = tmp_path / "bundle.uzp"
    assert Path(opened["path"]) == imported
    revision = opened["revision"]
    error = lost_reply_after(session, revision, INSERT_FILL)
    assert error["details"]["committed_revision"] == revision + 1
    status = session.status()
    assert Path(status["project"]) == imported and status["revision"] == revision + 1
    recovery = status["recoveries"][-1]
    assert Path(recovery["project"]) == imported and recovery["revision"] == revision + 1
    inspected = session.call("project_inspect")["result"]
    assert inspected["open"] and inspected["revision"] == revision + 1


def run_revision(session: Mcp, path: Path) -> int:
    """The revision of the project file `path`, read through the session's worker without
    disturbing what it holds (opened and closed inside one script that reopens the original)."""
    current = session.status()["project"]
    code = (
        "from uzpainter import project\n"
        "project.close()\n"
        f"project.open({path.as_posix()!r})\n"
        "result = project.revision()\n"
        "project.close()\n"
        f"project.open({current!r})\n"
    )
    status_before = session.status()
    reply = session.call(
        "run_python",
        {"code": code, "idempotency_key": "k-read", "expected_revision": status_before["revision"]},
    )
    revision = reply["result"]["result"]
    assert isinstance(revision, int)
    return revision


CAMERA = {
    "position": [0.0, 1.0, 40.0],
    "rotation": [0.0, 0.0, 0.0],
    "projection_type": "Perspective",
    "field_of_view": 40.0,
    "focal_length": 50.0,
    "focus_distance": 40.0,
    "aperture": 0.0,
    "orthographic_height": 2.5,
}


def test_display_shader_and_camera_tools_hold_the_fixed_pipeline(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """phase2.1_preview-display-presets item 2.6: the worker's `display_*`, `shader_*` and
    `camera_*` tools read the state, accept the fixed pipeline's values and refuse every other
    value before any change, naming decision 038."""
    session, revision = opened_session(painter, tmp_path, sessions)
    state = session.call("display_get")["result"]
    assert state["name"] == "common" and state["parity"] is False
    assert state["display"]["view"] == "Default - sRGB" and state["shader"]["shader"] == "open-pbr"

    def mutate(name: str, arguments: dict[str, Any], key: str) -> dict[str, Any]:
        return session.call(
            name, {**arguments, "idempotency_key": key, "expected_revision": revision}
        )

    refused = [
        mutate("display_set", {"exposure": 1.0}, "k-exposure"),
        mutate("display_set", {"rotation": 0.0, "shadows": True}, "k-shadows"),
        mutate("display_set", {"color_lut": "a" * 64}, "k-lut"),
        mutate("shader_set", {"parameters": {"coat_enabled": True}}, "k-shader"),
        mutate("camera_set", {"camera": {**CAMERA, "aperture": 1.0}}, "k-camera-bad"),
    ]
    for reply in refused:
        assert reply["error"]["code"] == "call_failed", reply
        assert reply["error"]["details"]["type"] == "UnsupportedInUzPainter", reply
    assert session.call("project_inspect")["result"]["revision"] == revision
    assert "decision 038" in refused[0]["error"]["message"]
    assert "shadows (preset 'common')" in refused[1]["error"]["message"]
    assert "the colour LUT" in refused[2]["error"]["message"]
    assert "'coat_enabled'" in refused[3]["error"]["message"]
    assert session.call("shader_get")["result"]["parameters"]["coat_enabled"] is False
    assert session.call("camera_get")["result"] == {"camera": None, "blender": None}

    blender = {
        "location": [0.0, -40.0, 1.0],
        "rotation_euler_degrees": [90.0, 0.0, 0.0],
        "type": "PERSP",
        "angle_degrees": 40.0,
        "lens_mm": 50.0,
        "ortho_scale": 2.5,
        "focus_distance": 40.0,
        "aperture_radius": 0.0,
    }
    reply = mutate("camera_set", {"blender": blender}, "k-camera")
    assert reply["committed_revision"] == revision + 1, reply
    assert reply["result"]["status"] == "committed", reply
    assert session.call("camera_get")["result"] == {"camera": CAMERA, "blender": blender}
    # The setters run the admitted request: a retry of the key returns its stored outcome.
    retry = mutate("camera_set", {"blender": blender}, "k-camera")
    assert retry["result"] == reply["result"] and retry["receipt"]["admission"] == "stored_outcome"
    assert retry["committed_revision"] == revision + 1, retry
    accepted = session.call(
        "display_set",
        {
            "exposure": 0.0,
            "background": [89, 89, 89],
            "idempotency_key": "k-same",
            "expected_revision": revision + 1,
        },
    )
    assert accepted["committed_revision"] == revision + 1, accepted
    assert accepted["result"]["status"] == "no_op", accepted
    assert session.call("display_get")["result"]["name"] == "common"


def test_long_jobs_of_a_python_session_are_not_busy_with_themselves(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """With `--allow-python` the bindings' job check (`Session::running_job`) sees every native
    job, and a long tool runs as one: the job a tool runs in does not count itself, so
    `project_save_as` and `export` succeed, and so do `project_save` and `project_revert`. A job a
    script queued (engine computations disabled, so it stays queued) still makes `save`,
    `save_as` and `close` busy, from Python and through MCP."""
    session, revision = opened_session(painter, tmp_path, sessions)
    path = tmp_path / "saved" / "as.uzp"
    saved = session.call("project_save_as", {"path": str(path), "wait": True})
    assert "error" not in saved, saved
    assert Path(saved["result"]["path"]) == path and path.is_file()
    assert Path(session.status()["project"]) == path
    config = {
        "exportPath": str(tmp_path / "out"),
        "exportShaderParams": False,
        "defaultExportPreset": "rough",
        "exportPresets": [
            {
                "name": "rough",
                "maps": [
                    {
                        "fileName": "rough",
                        "channels": [
                            {
                                "destChannel": "L",
                                "srcChannel": "L",
                                "srcMapType": "documentMap",
                                "srcMapName": "roughness",
                            }
                        ],
                    }
                ],
            }
        ],
        "exportList": [{"rootPath": "uzp_plane"}],
        "exportParameters": [
            {
                "parameters": {
                    "fileFormat": "png",
                    "bitDepth": "8",
                    "dithering": False,
                    "paddingAlgorithm": "passthrough",
                }
            }
        ],
    }
    exported = session.call("export", {"config": config, "wait": True})
    assert "error" not in exported, exported
    assert session.call("project_save", {})["result"]["named"] == revision
    reverted = session.call("project_revert", {"revision": revision - 1})
    assert reverted["result"]["status"] == "committed", reverted
    revision += 1

    other = tmp_path / "saved" / "other.uzp"
    queue = f"""
from uzpainter import application, export, project
application.enable_engine_computations(False)
job = export.start({config!r})
refused = []
for call in (project.save, lambda: project.save_as({other.as_posix()!r}), project.close):
    try:
        call()
        refused.append(None)
    except Exception as error:
        refused.append(type(error).__name__ + ": " + str(error))
result = {{"job": job.id, "status": job.status, "refused": refused}}
"""
    queued = session.call(
        "run_python", {"code": queue, "idempotency_key": "k-queue", "expected_revision": revision}
    )
    assert "error" not in queued, queued
    job = queued["result"]["result"]["job"]
    assert queued["result"]["result"]["status"] == "queued", queued
    assert queued["result"]["result"]["refused"] == [
        f"BusyError: {call} is refused while job {job} is running"
        for call in ("save()", "save_as()", "close()")
    ], queued
    assert not other.exists()
    busy = session.call("project_save", {})
    assert busy["error"]["code"] == "busy" and busy["error"]["details"]["job_id"] == job, busy
    release = f"""
from uzpainter import application, jobs
cancelled = [j.cancel() for j in jobs.list() if j.id == {job!r}]
application.enable_engine_computations(True)
result = {{"cancelled": cancelled, "busy": jobs.busy()}}
"""
    released = session.call(
        "run_python",
        {"code": release, "idempotency_key": "k-release", "expected_revision": revision},
    )
    assert released["result"]["result"] == {"cancelled": [True], "busy": None}, released
    assert "result" in session.call("project_save", {})


def test_shader_set_stores_double_sided_as_a_non_parity_state(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """Decision 196 option (b), amendment of 2026-10-19, through MCP: `shader_set` refuses a
    non-boolean `double_sided` (`invalid_arguments {type: ValueError}`, as decision 242 made an
    invalid export configuration) and a set with any other non-default identifier
    before any change, stores true as project state merged into the stored parameters, and
    `shader_get` and `display_get` read it back, after save and reopen too. The state is then a
    non-parity state, which a Tier 3 comparison rejects as render evidence."""
    from tools.parity.verdict import Comparison, Outcome, evaluate

    session = Mcp(painter, tmp_path, "--gpu-backend", BACKEND)
    sessions.append(session)
    project = make_project(painter, tmp_path)
    revision = session.call("project_open", {"path": str(project), "wait": True})["result"][
        "revision"
    ]
    malformed = session.call("shader_set", {"parameters": {"double_sided": 1}})
    assert malformed["error"]["code"] == "invalid_arguments", malformed
    assert malformed["error"]["details"]["type"] == "ValueError", malformed
    assert "'double_sided' must be a boolean" in malformed["error"]["message"]
    mixed = session.call(
        "shader_set", {"parameters": {"double_sided": True, "thin_film_enabled": True}}
    )
    assert mixed["error"]["details"]["type"] == "UnsupportedInUzPainter", mixed
    assert "'thin_film_enabled'" in mixed["error"]["message"]
    assert session.call("project_inspect")["result"]["revision"] == revision
    defaults = session.call("shader_get")["result"]["parameters"]
    assert defaults["double_sided"] is False

    stored = session.call("shader_set", {"parameters": {"double_sided": True}})
    assert stored["result"]["status"] == "committed", stored
    assert stored["committed_revision"] == revision + 1, stored
    merged = session.call("shader_set", {"parameters": {"specular_ior": 1.5}})
    assert merged["result"]["status"] == "no_op", merged
    on = {**defaults, "double_sided": True}
    assert session.call("shader_get")["result"] == {"shader": "open-pbr", "parameters": on}
    state = session.call("display_get")["result"]
    assert state["shader"]["parameters"] == on and state["parity"] is False

    path = tmp_path / "saved" / "double-sided.uzp"
    assert "error" not in session.call("project_save_as", {"path": str(path), "wait": True})
    assert "error" not in session.call("project_close")
    session.call("project_open", {"path": str(path), "wait": True})
    assert session.call("shader_get")["result"]["parameters"] == on
    reopened = session.call("display_get")["result"]
    assert reopened["parity"] is False

    evidence = Comparison(
        "3",
        "tier3/analytic/sphere-constant-material",
        [0.5],
        [0.5],
        candidate_display_state=reopened,
    )
    verdict = evaluate(evidence, [])
    assert verdict.outcome is Outcome.FAIL
    assert verdict.reason.startswith("rejected as render evidence")


def test_mutating_tools_publish_their_key_and_precondition(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.5, phase2.2 item 2.8: the MCP schema of a mutating tool takes `idempotency_key` and
    `expected_revision`; both may be omitted (the supervisor then generates the key and resolves
    the precondition, returned in the receipt); GPU-free reads do not take them."""
    session = Mcp(painter, tmp_path, *BASE)
    sessions.append(session)
    tools = {tool["name"]: tool for tool in session.request("tools/list", {})["tools"]}
    schema = tools["run_python"]["inputSchema"]
    assert schema["required"] == []
    assert set(schema["properties"]) == {
        "code",
        "path",
        "args",
        "idempotency_key",
        "expected_revision",
    }
    validator = Draft202012Validator(schema)
    call = {"code": "result = 1", "idempotency_key": "k-1", "expected_revision": 0}
    assert list(validator.iter_errors(call)) == []
    assert list(validator.iter_errors({"code": "result = 1"})) == []
    assert list(validator.iter_errors({"path": "script.py"})) == []
    assert list(validator.iter_errors({"code": "1", "path": "script.py"}))  # code or path
    assert list(validator.iter_errors({}))
    assert list(validator.iter_errors({"code": "1", "expected_revision": "0"}))
    reply = session.call("run_python", call)
    assert reply["result"]["result"] == 1
    generated = session.call("run_python", {"code": "result = 2"})
    assert generated["result"]["result"] == 2
    assert generated["receipt"]["key_source"] == "supervisor"
    assert generated["receipt"]["idempotency_key"].startswith("sup-")
    assert generated["receipt"]["expected_revision"] == 0
    assert "idempotency_key" not in tools["project_open"]["inputSchema"]["properties"]
    assert tools["run_python"]["annotations"]["readOnlyHint"] is False
    assert tools["project_inspect"]["annotations"]["readOnlyHint"] is True


def test_a_worker_dying_during_the_reopen_is_replaced(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.8: the relaunched worker dies while it reopens the project; the supervisor races the
    reopen against its end, launches another and recovers on the last committed revision."""
    counter = tmp_path / "kill-on-open.txt"
    session, revision = opened_session(
        painter, tmp_path, sessions, env={"UZP_TEST_KILL_ON_OPEN": str(counter)}
    )
    counter.write_text("1", encoding="utf-8")
    old = session.status()["worker_pid"]
    kill_pid(old)
    assert wait_until_gone(old)
    inspected = session.call("project_inspect")
    if "error" in inspected:  # the call raced the kill and reached the dying worker
        assert inspected["error"]["code"] == "interrupted"
        inspected = session.call("project_inspect")
    assert inspected["result"]["revision"] == revision
    recovery = recovery_after(session, 1)
    assert recovery["attempts"] == 2 and recovery["revision"] == revision
    (failed,) = recovery["failed_attempts"]
    assert failed["exit_code"] == 77 and failed["cause"] == "terminated"
    assert counter.read_text(encoding="utf-8") == "0"


def test_recovery_gives_up_after_bounded_attempts(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.8: when every relaunched worker dies during the reopen, the supervisor stops after three
    launches with a fatal error instead of waiting or looping."""
    counter = tmp_path / "kill-on-open.txt"
    session, _ = opened_session(
        painter, tmp_path, sessions, env={"UZP_TEST_KILL_ON_OPEN": str(counter)}
    )
    counter.write_text("99", encoding="utf-8")
    kill_pid(session.status()["worker_pid"])
    assert session.process.wait(120) == 4
    assert "recovery failed: 3 relaunched workers ended before they reopened" in session.log()
    assert counter.read_text(encoding="utf-8") == "96"


def test_calls_arriving_during_a_relaunch_wait_for_it(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.8: pending calls wait for the relaunch and are then forwarded once."""
    session, revision = opened_session(painter, tmp_path, sessions)
    old = session.status()["worker_pid"]
    kill_pid(old)
    time.sleep(0.05)  # inside the relaunch window
    reply = session.call(
        "run_python", {"code": INSERT_FILL, "idempotency_key": "k-2", "expected_revision": revision}
    )
    assert reply["committed_revision"] == revision + 1, reply
    assert recovery_after(session, 1)["old_pid"] == old


def test_supervisor_killed_ends_its_worker(
    painter: Path, tmp_path: Path, sessions: list[Mcp], pipes: list[Pipe]
) -> None:
    """2.10, 3.5: the worker exits once its supervisor dies, and the project file holds the last
    committed revision."""
    session, revision = opened_session(painter, tmp_path, sessions)
    status = session.status()
    kill_pid(session.process.pid)
    assert wait_until_gone(status["worker_pid"], 30)
    pipe = Pipe(painter, tmp_path, "--gpu-backend", "vulkan")
    pipes.append(pipe)
    assert pipe.call("project_open", {"path": status["project"]})["result"]["revision"] == revision
