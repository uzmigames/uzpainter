"""Offline process/ownership/lifecycle boundaries; no Painter, network or lock writes."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tools.parity.recorder import launcher as launcher_module
from tools.parity.recorder import project_configuration_survey as ownership
from tools.parity.recorder import raw_capability_capture as capture
from tools.parity.recorder.probes import ProbeSession, finish_probe
from tools.parity.recorder.session import HttpTransport, PainterSession, UnseenBuild
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control


@pytest.fixture
def request_data(tmp_path: Path) -> capture.Request:
    manifest = tmp_path / "authored.json"
    manifest.write_text(json.dumps(control.request("normalization-png16")), encoding="utf-8")
    exe = tmp_path / "authored.exe"
    exe.write_bytes(b"not-executable")
    return capture.Request("normalization-png16", manifest, exe, tmp_path / "capture")


def boundaries(monkeypatch: pytest.MonkeyPatch, request: capture.Request, failure: str = "") -> Any:
    state = SimpleNamespace(
        running=False,
        opened=False,
        uuid="own-created",
        marker={},
        calls=[],
        lock_owned=True,
        pid=71,
        started="own-start",
        closes=0,
    )

    class Launcher:
        pid = 71

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def start(self, environment: Any) -> None:
            assert environment == {"OCIO": "approved", "PAINTER_ACE_CONFIG": None}
            state.calls.append("start")
            state.running = True

        def stop(self) -> None:
            state.calls.append("stop")
            state.running = False

        def end_process(self) -> None:
            state.calls.append("terminate")
            state.running = False

    class Lock:
        token: str | None = None

        def __init__(self, evidence: Any, *, owner: str, task: str) -> None:
            assert owner == "Astra/uzpainter-raw-capability"
            assert task == "Codex/Raw: one authored capability capture"

        def acquire(self) -> None:
            state.calls.append("lock")
            self.token = "private-token"

        def verify(self) -> None:
            if failure == "after_ready" and not state.lock_owned:
                assert (
                    '"event":"capture_ready"'
                    in request.output_prefix.with_suffix(".events.jsonl").read_text()
                )
            ownership.require_owned(state.lock_owned, "lock changed")

        def release(self) -> None:
            state.calls.append("release")
            self.token = None

    def remote(raw: Any, code: str) -> Any:
        if failure == "marker_ipc" and "OWN_PROJECT_CREATION" in code:
            raise OSError("private marker IPC failure")
        project = SimpleNamespace(get_uuid=lambda: state.uuid, is_open=lambda: state.opened)
        os_module = SimpleNamespace(getpid=lambda: 99 if failure == "remote_pid" else state.pid)
        return eval(
            code,
            {
                "__import__": lambda name, **kw: os_module if name == "os" else project,
                "uzp_recorder": {"OWN_PROJECT_CREATION": state.marker},
            },
        )

    def session_call(session: capture.RawSession, operation: str, **args: Any) -> Any:
        session.owned.verify()
        state.calls.append(operation)
        if operation == "apply_step":
            state.opened = True
            state.marker = {} if failure == "marker" else {"uuid": "own-created", "pending": True}
            if failure == "create_swap":
                state.uuid = "foreign"
        elif operation == "close_project":
            state.closes += 1
            state.opened = False
        elif operation == "open_project":
            state.opened = True
            if failure == "reopen_uuid":
                state.uuid = "foreign"
        return {}

    def record(session: capture.RawSession, job: Any, work: Path, inbox: Path) -> Path:
        state.session = session
        assert not job.exports and not job.lifecycle
        state.calls.append("capture")
        try:
            session.call("apply_step", step=1, call=ownership.CREATE)
            if failure == "capture":
                raise ValueError("PRIVATE_CAPTURE_FAILURE")
            session.call("save_as", path=str(work / "own.spp"))
            session.call("close_project")
            session.call("open_project", path=str(work / "own.spp"))
            if failure in {"project_swap", "lock_loss", "process_start"}:
                if failure == "project_swap":
                    state.uuid = "foreign"
                elif failure == "lock_loss":
                    state.lock_owned = False
                else:
                    state.started = "foreign-start"
                session.call("template_capture")
        finally:
            failures = finish_probe(session)
        if failures:
            raise ValueError("recorder cleanup refused")
        run = inbox / "run"
        run.mkdir()
        (run / "manifest.json").write_text(
            json.dumps(
                {
                    "private_records": [
                        {"record_id": "golden-record"},
                        {"record_id": "oracle-environment"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        (run / "READY").write_bytes(b"")
        if failure == "after_ready":
            state.lock_owned = False
        return run

    def host() -> ownership.Host:
        processes = (
            [{"pid": state.pid, "name": "Painter.exe", "started": state.started}]
            if state.running
            else []
        )
        return ownership.Host(32 * ownership.GIB, 64 * ownership.GIB, processes)

    monkeypatch.setattr(capture, "PainterLauncher", Launcher)
    monkeypatch.setattr(launcher_module, "PainterLauncher", Launcher)
    monkeypatch.setattr(ownership, "Lock", Lock)
    monkeypatch.setattr(ownership, "host_state", host)
    monkeypatch.setattr(capture, "endpoint_answers", lambda: False)
    monkeypatch.setattr(
        capture,
        "launch_environment",
        lambda *args: {"OCIO": "approved", "PAINTER_ACE_CONFIG": None},
    )
    monkeypatch.setattr(capture.BoundedTransport, "run", remote)
    monkeypatch.setattr(ProbeSession, "call", session_call)
    monkeypatch.setattr(ProbeSession, "verify_identity", lambda self: self.owned.verify())
    monkeypatch.setattr(ProbeSession, "wait_closed", lambda self, **kw: None)
    monkeypatch.setattr(capture, "record_probe_golden", record)
    monkeypatch.setattr(capture, "work_root", lambda: request.output_prefix.parent)
    monkeypatch.setattr(capture, "inbox_root", lambda: request.output_prefix.parent)
    return state


def test_single_capture_private_outputs_and_owned_cleanup(
    request_data: capture.Request,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = boundaries(monkeypatch, request_data)
    result = capture.capture(request_data)
    assert result["status"] == "complete" and result["captures"] == 1
    assert not state.running and not state.opened
    assert state.calls.count("capture") == 1 and state.calls[-2:] == ["stop", "release"]
    report = json.loads(request_data.output_prefix.with_suffix(".report.json").read_bytes())
    assert report["exports"] == report["admissions"] == 0 and len(report["private_records"]) == 2
    assert "run" not in result and "PRIVATE" not in json.dumps(result)
    original = request_data.output_prefix.with_suffix(".report.json").read_bytes()
    with pytest.raises(FileExistsError):
        capture.capture(request_data)
    assert request_data.output_prefix.with_suffix(".report.json").read_bytes() == original


@pytest.mark.parametrize("mutation", ["wrong_state", "export", "changed_step"])
def test_wrong_request_refuses_before_lock_or_launch(
    request_data: capture.Request,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    state = boundaries(monkeypatch, request_data)
    if mutation == "wrong_state":
        request_data = replace(request_data, state="calibration-float")
    else:
        document = control.request(request_data.state, exports=mutation == "export")
        if mutation == "changed_step":
            document["instruction_sequence"]["steps"].pop()
        request_data.manifest.write_text(json.dumps(document), encoding="utf-8")
    assert capture.capture(request_data)["status"] == "refused"
    assert not {"lock", "start", "capture"}.intersection(state.calls)


@pytest.mark.parametrize("failure", ["existing", "builder", "memory", "commit", "endpoint"])
def test_host_refusal_before_lock(
    request_data: capture.Request,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    state = boundaries(monkeypatch, request_data)
    host = ownership.Host(32 * ownership.GIB, 64 * ownership.GIB, [])
    if failure in {"existing", "builder"}:
        host.processes.append(
            {
                "pid": 5,
                "name": "Painter.exe" if failure == "existing" else "zig.exe",
                "started": "foreign",
            }
        )
    elif failure == "memory":
        host = replace(host, physical_free=ownership.GIB)
    elif failure == "commit":
        host = replace(host, commit_free=ownership.GIB)
    else:
        monkeypatch.setattr(capture, "endpoint_answers", lambda: True)
    monkeypatch.setattr(ownership, "host_state", lambda: host)
    assert capture.capture(request_data)["status"] == "refused"
    assert "lock" not in state.calls and "start" not in state.calls


def test_capture_failure_closes_only_owned_project(
    request_data: capture.Request,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = boundaries(monkeypatch, request_data, "capture")
    assert capture.capture(request_data)["status"] == "refused"
    assert not state.running and not state.opened and state.closes == 1
    assert state.calls[-2:] == ["stop", "release"]


@pytest.mark.parametrize(
    "failure",
    [
        "remote_pid",
        "marker",
        "marker_ipc",
        "create_swap",
        "reopen_uuid",
        "project_swap",
        "lock_loss",
        "process_start",
    ],
)
def test_ownership_loss_sticky_even_through_recorder_cleanup(
    request_data: capture.Request,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    state = boundaries(monkeypatch, request_data, failure)
    assert capture.capture(request_data)["status"] == "refused"
    assert state.running and not {"stop", "terminate", "release"}.intersection(state.calls)
    if failure != "remote_pid":
        before = list(state.calls)
        assert len(finish_probe(state.session)) == 3
        assert state.calls == before


def test_other_reopen_path_refuses_and_preserves_ownership(
    request_data: capture.Request,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = boundaries(monkeypatch, request_data)
    lock = ownership.Lock(
        Mock(), owner=capture.OWNER, task="Codex/Raw: one authored capability capture"
    )
    launcher = launcher_module.PainterLauncher(request_data.painter_exe)
    state.running = True
    owned = capture.GuardedTransport(capture.BoundedTransport(), launcher, lock, "own-start")
    session = capture.RawSession.attached(owned, "authored-build")
    session.call("apply_step", call=ownership.CREATE)
    session.call("save_as", path=str(request_data.output_prefix.parent / "own.spp"))
    session.call("close_project")
    with pytest.raises(ownership.OwnershipLost):
        session.call("open_project", path=str(request_data.output_prefix.parent / "foreign.spp"))
    assert owned.lost and not state.opened


def test_expired_deadline_never_calls_http(monkeypatch: pytest.MonkeyPatch) -> None:
    http = Mock()
    monkeypatch.setattr(HttpTransport, "run", http)
    transport = capture.BoundedTransport()
    transport.deadline = 0
    with pytest.raises(ValueError, match="deadline"):
        transport.run("authored")
    http.assert_not_called()


def test_request_build_refuses_other_envelope_before_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned = Mock(spec=capture.GuardedTransport)
    session = capture.RawSession.attached(owned, "authored-build")
    identity = SimpleNamespace(build_id="other-build")
    monkeypatch.setattr(PainterSession, "read_identity", lambda self: identity)
    call = Mock()
    monkeypatch.setattr(session, "call", call)
    with pytest.raises(UnseenBuild):
        session.connect()
    call.assert_not_called()
    owned.run.assert_not_called()


def test_ready_location_survives_postcapture_ownership_loss(
    request_data: capture.Request, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = boundaries(monkeypatch, request_data, "after_ready")
    result = capture.capture(request_data)
    report = json.loads(request_data.output_prefix.with_suffix(".report.json").read_bytes())
    events = [
        json.loads(line)
        for line in request_data.output_prefix.with_suffix(".events.jsonl").read_text().splitlines()
    ]
    ready = next(event for event in events if event["event"] == "capture_ready")
    assert result["status"] == "refused" and result["captures"] == report["captures"] == 1
    assert ready["run"] == report["run"] and (Path(report["run"]) / "READY").is_file()
    assert ready["captures"] == 1 and report["admissions"] == report["exports"] == 0
    assert state.calls.count("capture") == 1
    assert state.running and not {"stop", "terminate", "release"}.intersection(state.calls)
    assert "run" not in result
