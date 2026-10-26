"""Authored UI/process/lock mocks only; no Painter, Windows UI or external lock writes."""

from __future__ import annotations

import builtins
import hashlib
import json
import subprocess
import time
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tools.parity.recorder import project_configuration_survey as survey
from tools.parity.recorder.session import PAINTER_SIDE, bootstrap_code


@pytest.fixture
def request_data(tmp_path: Path) -> survey.Request:
    exe = tmp_path / "authored.exe"
    exe.write_bytes(b"not-executable")
    return survey.Request(exe, tmp_path / "new-survey")


def process(pid: int = 71, started: str = "authored-start") -> dict[str, Any]:
    return {"pid": pid, "started": started, "name": "Adobe Substance 3D Painter.exe"}


def host(*processes: dict[str, Any]) -> survey.Host:
    return survey.Host(32 * survey.GIB, 64 * survey.GIB, list(processes))


def install_boundaries(monkeypatch: pytest.MonkeyPatch, failure: str = "") -> Any:
    state = SimpleNamespace(
        running=False,
        opened=False,
        calls=[],
        process=process(),
        uuid="authored-project",
        dirty=True,
        closes=0,
        owns_lock=True,
        creation={},
    )

    class Launcher:
        pid = 71

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            assert kwargs == {"ready_timeout_s": 120, "stop_timeout_s": 15}

        def start(self, environment: dict[str, Any]) -> None:
            assert environment == {"OCIO": None, "PAINTER_ACE_CONFIG": None}
            state.calls.append("start")
            state.running = True

        def stop(self, session: Any = None) -> None:
            state.calls.append("stop")
            if session is not None:
                session.call("close_project")
            state.running = False

        def end_process(self) -> None:
            state.calls.append("end-own-process")
            state.running = False

    class Lock:
        token = None

        def __init__(self, evidence: Any) -> None:
            self.evidence = evidence

        def acquire(self) -> None:
            state.calls.append("acquire")
            if failure == "lock":
                raise ValueError("PRIVATE_LOCK_FAILURE")
            self.token = "private-token"

        def verify(self) -> None:
            assert self.token == "private-token"
            if not state.owns_lock:
                raise survey.OwnershipLost("lock changed")

        def release(self) -> None:
            state.calls.append("release")
            self.token = None

    class Transport:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs == {"timeout_s": 10}

        def run(self, code: str) -> Any:
            if "OWN_PROJECT_CREATION" in code and failure == "marker_unavailable":
                raise RuntimeError("authored marker unavailable")

            def close() -> None:
                state.closes += 1
                state.opened = False

            project = SimpleNamespace(
                get_uuid=lambda: state.uuid,
                is_open=lambda: state.opened,
                needs_saving=lambda: state.dirty,
                close=close,
            )
            os_module = SimpleNamespace(getpid=lambda: 99 if failure == "remote_pid" else 71)
            if failure == "project_swap" and ".close()" in code:
                state.uuid = "changed-project"
            return eval(
                code,
                {
                    "__import__": lambda name, **kwargs: os_module if name == "os" else project,
                    "uzp_recorder": {"OWN_PROJECT_CREATION": state.creation},
                },
            )

    class Session:
        def __init__(self, transport: Any) -> None:
            self.transport = transport

        def connect(self) -> Any:
            state.calls.append("bootstrap")
            self.transport.verify()
            if failure == "bootstrap":
                raise ValueError("PRIVATE_BOOTSTRAP_FAILURE")
            return SimpleNamespace(
                colour_management={"mode": "legacy", "OCIO": None, "PAINTER_ACE_CONFIG": None}
            )

        def call(self, operation: str, **kwargs: Any) -> Any:
            self.transport.verify()
            state.calls.append(operation)
            if operation == "apply_step":
                assert kwargs == {
                    "step": 1,
                    "call": survey.CREATE,
                    "args": {
                        "mesh": "plane",
                        "normal_map_format": "OpenGL",
                        "default_texture_resolution": 128,
                    },
                    "resolved": {"mesh": str(survey.PLANE)},
                }
                state.opened = True
                state.creation = {"uuid": state.uuid, "pending": True}
                if failure == "create_swap":
                    state.uuid = "foreign-after-create"
                if failure == "marker_missing":
                    state.creation = {}
            elif operation == "close_project":
                self.transport.run(
                    "__import__('substance_painter.project',fromlist=['close']).close()"
                )
            else:
                assert operation == "template_capture"
            return {}

        def wait_ready(self, **kwargs: Any) -> None:
            assert kwargs == {"timeout_s": 120}
            assert self.transport.project_uuid == "authored-project"
            if failure == "ready_swap":
                state.uuid = "foreign-while-ready"

        def wait_closed(self, **kwargs: Any) -> None:
            assert kwargs == {"timeout_s": 15} and not state.opened

        def state(self) -> Any:
            return SimpleNamespace(is_open=state.opened, file_path=None, ready=True)

        def verify_identity(self) -> None:
            self.transport.verify()

    class Ui:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs == {"pid": 71, "timeout_s": 10}
            if failure == "ui":
                raise ValueError("PRIVATE_UI_FAILURE")
            self.window = SimpleNamespace(handle=25, process_id=lambda: 71)

        def survey(self, window: Any) -> list[Any]:
            if failure == "lock_loss":
                state.owns_lock = False
            return [{"text": "PRIVATE_AUTHORED_LABEL"}]

        def print_window(self, handle: int) -> Any:
            def save(stream: Any, *, format: str) -> None:
                assert format == "PNG"
                stream.write(b"authored-image")
                if failure == "dirty":
                    state.dirty = False

            return SimpleNamespace(save=save), (0, 0)

    monkeypatch.setattr(survey, "PainterLauncher", Launcher)
    monkeypatch.setattr(survey, "Lock", Lock)
    monkeypatch.setattr(survey, "HttpTransport", Transport)
    monkeypatch.setattr(survey, "PainterSession", Session)
    monkeypatch.setattr(survey, "PainterUi", Ui)
    monkeypatch.setattr(
        survey, "host_state", lambda: host(state.process) if state.running else host()
    )
    monkeypatch.setattr(survey, "endpoint_answers", lambda: False)
    return state


def test_owned_plane_only_flow_preserves_outputs(
    request_data: survey.Request, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = install_boundaries(monkeypatch)
    result = survey.survey(request_data)
    assert result["status"] == "complete"
    assert state.calls == [
        "acquire",
        "start",
        "bootstrap",
        "apply_step",
        "template_capture",
        "close_project",
        "stop",
        "release",
    ]
    assert not state.running and not state.opened
    assert "PRIVATE" not in json.dumps(result)
    report = request_data.output_prefix.with_suffix(".report.json")
    before = report.read_bytes()
    with pytest.raises(FileExistsError):
        survey.survey(request_data)
    assert report.read_bytes() == before


@pytest.mark.parametrize("failure", ["lock", "bootstrap", "ui", "dirty"])
def test_failure_cleanup_never_contacts_foreign_endpoint(
    request_data: survey.Request, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    state = install_boundaries(monkeypatch, failure)
    result = survey.survey(request_data)
    assert result["status"] == "refused" and not state.running
    assert state.calls[-1] == "release"
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize(
    "failure",
    [
        "remote_pid",
        "project_swap",
        "lock_loss",
        "create_swap",
        "ready_swap",
        "marker_missing",
        "marker_unavailable",
    ],
)
def test_ownership_loss_preserves_process_and_owned_lock(
    request_data: survey.Request, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    state = install_boundaries(monkeypatch, failure)
    result = survey.survey(request_data)
    assert result["status"] == "refused" and state.running and state.closes == 0
    assert not {"stop", "end-own-process", "release"}.intersection(state.calls)
    report = json.loads(request_data.output_prefix.with_suffix(".report.json").read_bytes())
    assert report["preserved_process"] is True
    assert report["preserved_lock"] is (failure != "lock_loss")


@pytest.mark.parametrize(
    "failure", ["physical", "commit", "builder", "existing", "endpoint", "nan"]
)
def test_preflight_refuses_before_lock_or_launch(
    request_data: survey.Request, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    state = install_boundaries(monkeypatch)
    current = host()
    if failure == "physical":
        current = replace(current, physical_free=survey.GIB)
    elif failure == "commit":
        current = replace(current, commit_free=survey.GIB)
    elif failure == "builder":
        current = host({"pid": 3, "name": "clang++.exe", "started": "now"})
    elif failure == "existing":
        current = host(process(99))
    elif failure == "endpoint":
        monkeypatch.setattr(survey, "endpoint_answers", lambda: True)
    else:
        request_data = replace(request_data, min_free_memory_gib=float("nan"))
    monkeypatch.setattr(survey, "host_state", lambda: current)
    assert survey.survey(request_data)["status"] == "refused"
    assert "start" not in state.calls and "acquire" not in state.calls


@pytest.mark.parametrize("failure", ["pid", "started", "second", "lock", "project"])
def test_transport_rechecks_identity_before_every_command(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    raw = Mock()
    raw.run.side_effect = lambda code: 71 if "getpid" in code else "wrong-project"
    lock = Mock()
    current = host(process())
    if failure == "pid":
        current = host(process(99))
    elif failure == "started":
        current = host(process(started="reused-pid"))
    elif failure == "second":
        current = host(process(), process(99))
    elif failure == "lock":
        lock.verify.side_effect = ValueError("lost ownership")
    monkeypatch.setattr(survey, "host_state", lambda: current)
    owned = survey.OwnedTransport(raw, Mock(pid=71), lock, "authored-start")
    if failure == "project":
        owned.project_uuid = "authored-project"
    with pytest.raises(ValueError):
        owned.run("MUST_NOT_EXECUTE")
    assert all(call.args[0] != "MUST_NOT_EXECUTE" for call in raw.run.call_args_list)


@pytest.mark.parametrize("code", ["sensitive()", "sensitive()\nmarker = 1"])
def test_remote_request_rechecks_pid_after_prior_verification(
    monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    sensitive = Mock()

    def remote(source: str) -> Any:
        if source == "__import__('os').getpid()":
            return 71
        namespace = {
            "__import__": lambda name: SimpleNamespace(getpid=lambda: 99),
            "sensitive": sensitive,
        }
        if source.startswith("if "):
            exec(source, namespace)
            return None
        return eval(source, namespace)

    monkeypatch.setattr(survey, "host_state", lambda: host(process()))
    owned = survey.OwnedTransport(Mock(run=remote), Mock(pid=71), Mock(), "authored-start")
    with pytest.raises(survey.OwnershipLost, match="inside remote request"):
        owned.run(code)
    sensitive.assert_not_called()


def test_multiline_real_bootstrap_shape_keeps_future_import_in_inner_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace: dict[str, Any] = {}
    compile(bootstrap_code(PAINTER_SIDE.read_text(encoding="utf-8")), "<bootstrap>", "exec")

    def imported(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "os":
            return SimpleNamespace(getpid=lambda: 71)
        return builtins.__import__(name, *args, **kwargs)

    namespace["__builtins__"] = {**vars(builtins), "__import__": imported}

    def remote(source: str) -> Any:
        if source == "__import__('os').getpid()":
            return 71
        exec(source, namespace)
        return None

    monkeypatch.setattr(survey, "host_state", lambda: host(process()))
    owned = survey.OwnedTransport(Mock(run=remote), Mock(pid=71), Mock(), "authored-start")
    owned.run(bootstrap_code("from __future__ import annotations\nvalue = 'authored'\n"))
    assert namespace["uzp_recorder"]["value"] == "authored"
    assert namespace["uzp_recorder"]["session_id"] == namespace["uzp_recorder_session_id"]


def test_release_keeps_token_when_canonical_audit_failed(tmp_path: Path) -> None:
    with ExitStack() as stack:
        lock = survey.Lock(survey.Evidence(tmp_path / "release-audit", stack))
        lock.token = "owned-token"
        lock.command = Mock(  # type: ignore[method-assign]
            side_effect=[
                {
                    "occupied": True,
                    "owner": lock.owner,
                    "token_hash": hashlib.sha256(lock.token.encode()).hexdigest(),
                },
                {"released": "painter", "resource_committed": True, "canonical_committed": False},
            ]
        )
        with pytest.raises(ValueError, match="release incomplete"):
            lock.release()
        assert lock.token == "owned-token"


@pytest.mark.parametrize("custom_owner", [False, True])
def test_lock_uses_canonical_cli_stdin_and_retains_token_on_audit_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, custom_owner: bool
) -> None:
    token = "private-lock-token"
    owner = "Codex/authored-raw" if custom_owner else "Codex/uzpainter-project-config-survey"
    task = (
        "Authored Raw capability"
        if custom_owner
        else "Private authored Project Configuration UI selector survey"
    )
    state: dict[str, Any] = {"occupied": False}
    calls = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert token not in " ".join(command)
        args = json.loads(kwargs["input"])
        assert args[:3] == [str(survey.COLLAB), "--root", str(survey.COLLAB_ROOT)]
        action = args[4]
        calls.append(action)
        if action == "acquire":
            assert args[-4:] == ["--owner", owner, "--task", task]
            state.update(
                occupied=True,
                owner=owner,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
            )
            reply = {
                "owner": state["owner"],
                "token": token,
                "resource_committed": True,
                "canonical_committed": False,
            }
        elif action == "release":
            assert args[-4:] == ["--owner", state["owner"], "--token", token]
            state["occupied"] = False
            reply = {"released": "painter", "resource_committed": True, "canonical_committed": True}
        else:
            assert action == "status"
            reply = dict(state)
        return subprocess.CompletedProcess(command, 0, json.dumps(reply), "")

    monkeypatch.setattr(subprocess, "run", run)
    with ExitStack() as stack:
        evidence = survey.Evidence(tmp_path / "lock-evidence", stack)
        lock = (
            survey.Lock(evidence, owner=owner, task=task) if custom_owner else survey.Lock(evidence)
        )
        with pytest.raises(ValueError, match="audit"):
            lock.acquire()
        assert lock.token == token
        lock.release()
    assert calls == ["status", "acquire", "status", "release"]
    assert not state["occupied"]


class Widget:
    def __init__(self, label: str, kind: str, handle: int = 50) -> None:
        self.label, self.handle, self.visible = label, handle, True
        self.element_info = SimpleNamespace(control_type=kind, automation_id="observed-id")
        self.widgets: list[Widget] = []

    def process_id(self) -> int:
        return 71

    def is_visible(self) -> bool:
        return self.visible

    def is_enabled(self) -> bool:
        return True

    def window_text(self) -> str:
        return self.label

    def descendants(self) -> list[Widget]:
        return self.widgets


@pytest.mark.parametrize(
    "failure", ["", "ambiguous_menu", "foreground", "no_cancel", "ambiguous_dialog", "stale_pid"]
)
def test_configuration_reads_and_only_cancels(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    main = Widget("Painter", "Window", 25)
    dialog = Widget("Project Configuration", "Window")
    cancel = Widget("Cancel", "Button", 51)
    dialog.widgets = [] if failure == "no_cancel" else [cancel]
    main.children = lambda: [dialog]  # type: ignore[attr-defined]
    owned = Mock(launcher=Mock(pid=71))
    if failure == "stale_pid":
        owned.verify.side_effect = ValueError("stale process")
    ui = Mock(window=main, settle_s=0)
    ui.desktop.windows.return_value = (
        [dialog, Widget("Project Configuration", "Window", 52)]
        if failure == "ambiguous_dialog"
        else [dialog]
    )
    ui.menu_containers.return_value = [main]
    ui.survey.return_value = []
    clicked = []

    def menu(label: str) -> Widget:
        if failure == "ambiguous_menu" and label == "Project Configuration":
            raise ValueError("ambiguous menu")
        return Widget(label, "MenuItem")

    def click(widget: Widget, **kwargs: Any) -> None:
        if failure == "foreground":
            raise ValueError("covered by foreign window")
        clicked.append(widget.label)
        if widget is cancel:
            assert kwargs == {"owner": dialog.handle}
            dialog.visible = False

    ui.menu_item.side_effect = menu
    ui.click.side_effect = click
    ui.click_menu_item.side_effect = click
    evidence = Mock()
    if failure:
        with pytest.raises(ValueError):
            survey.configuration_survey(ui, owned, evidence)
    else:
        survey.configuration_survey(ui, owned, evidence)
        assert clicked == ["Edit", "Project Configuration", "Cancel"]
        assert not dialog.visible
    assert "OK" not in clicked and "Apply" not in clicked
    if failure == "stale_pid":
        assert not clicked
    if failure == "no_cancel":
        evidence.image.assert_called_once_with("configuration_image", ui, dialog.handle)


def test_cli_does_not_print_private_failure(
    request_data: survey.Request,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(survey, "survey", Mock(side_effect=ValueError("PRIVATE_TOKEN")))
    monkeypatch.setattr(
        "sys.argv",
        [
            "survey",
            "--painter-exe",
            str(request_data.painter_exe),
            "--output-prefix",
            str(request_data.output_prefix),
        ],
    )
    assert survey.main() == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"status": "refused"} and not captured.err
