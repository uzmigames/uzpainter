"""CPU-only transport checks: private process output never enters public failures."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.python.conftest import JSON_PREFIX, runner

SECRET = "PRIVATE-OBSERVATION-SENTINEL"


@pytest.mark.parametrize(
    "stdout,code,reason",
    [
        (SECRET, 7, "missing report"),
        (JSON_PREFIX + "{" + SECRET, 0, "invalid report JSON"),
        (JSON_PREFIX + json.dumps([SECRET]), 0, "invalid report shape"),
        (JSON_PREFIX + json.dumps({"status": SECRET}), 0, "invalid report shape"),
        (JSON_PREFIX + json.dumps({"status": "ok"}), 0, "invalid report shape"),
        (
            JSON_PREFIX + json.dumps({"status": "failed", "error": SECRET}),
            1,
            "invalid report shape",
        ),
        (JSON_PREFIX + json.dumps({"status": "ok", "result": SECRET}), 1, "report exit mismatch"),
    ],
)
def test_private_transport_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stdout: str, code: int, reason: str
) -> None:
    def process(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], code, stdout, SECRET)

    monkeypatch.setattr(subprocess, "run", process)
    run = runner(Path("unused.exe"), tmp_path, "", private_diagnostics=tmp_path)
    with pytest.raises(pytest.fail.Exception) as caught:
        run("result = None")
    assert str(caught.value) == f"{reason} (details kept privately)"
    assert SECRET not in str(caught.value)
    assert caught.value.pytrace is False
    assert caught.value.__context__ is None
    diagnostic = json.loads((tmp_path / "private-runner-diagnostics.json").read_text())
    assert diagnostic == {"stdout": stdout, "stderr": SECRET, "returncode": code}


def test_private_timeout_preserves_byte_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def timeout(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(
            [SECRET], 600, output=SECRET.encode(), stderr=SECRET.encode()
        )

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(pytest.fail.Exception) as caught:
        runner(Path("unused.exe"), tmp_path, "", private_diagnostics=tmp_path)("pass")
    assert str(caught.value) == "runner timeout (details kept privately)"
    assert caught.value.pytrace is False
    assert caught.value.__context__ is None
    diagnostic = json.loads((tmp_path / "private-runner-diagnostics.json").read_text())
    assert diagnostic == {"stdout": SECRET, "stderr": SECRET}


@pytest.mark.parametrize("private", [False, True])
def test_success_keeps_report_and_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, private: bool
) -> None:
    report = {"status": "ok", "result": {"observed": SECRET}}
    commands: list[list[str]] = []

    def process(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert kwargs["timeout"] == 600
        return subprocess.CompletedProcess([], 0, JSON_PREFIX + json.dumps(report), SECRET)

    monkeypatch.setattr(subprocess, "run", process)
    result = runner(
        Path("unused.exe"),
        tmp_path,
        "# prelude\n",
        private_diagnostics=tmp_path if private else None,
    )("result = None")
    assert result == report
    assert commands == [
        ["unused.exe", str(tmp_path / "script.py"), "--test-gpu-unavailable", str(tmp_path)]
    ]
    assert (tmp_path / "script.py").read_text() == "# prelude\nresult = None"
    assert not (tmp_path / "private-runner-diagnostics.json").exists()


def test_private_diagnostic_write_failure_stays_sanitized(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def process(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 7, SECRET, SECRET)

    monkeypatch.setattr(subprocess, "run", process)
    with pytest.raises(pytest.fail.Exception) as caught:
        runner(Path("unused.exe"), tmp_path, "", private_diagnostics=tmp_path / "missing")("pass")
    assert str(caught.value) == "missing report (private diagnostic write failed)"
    assert caught.value.pytrace is False
    assert caught.value.__context__ is None
    assert not (tmp_path / "missing").exists()


def test_private_execution_failure_stays_sanitized(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise OSError(SECRET)

    monkeypatch.setattr(subprocess, "run", unavailable)
    with pytest.raises(pytest.fail.Exception) as caught:
        runner(Path("unused.exe"), tmp_path, "", private_diagnostics=tmp_path)("pass")
    assert str(caught.value) == "runner unavailable (details kept privately)"
    assert caught.value.pytrace is False
    assert caught.value.__context__ is None
    diagnostic = json.loads((tmp_path / "private-runner-diagnostics.json").read_text())
    assert diagnostic == {"error": SECRET}


def test_private_script_failure_returns_report_for_private_replay_handling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = {"status": "failed", "error": {"type": "ValueError", "message": SECRET}}

    def process(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 1, JSON_PREFIX + json.dumps(report), SECRET)

    monkeypatch.setattr(subprocess, "run", process)
    result = runner(Path("unused.exe"), tmp_path, "", private_diagnostics=tmp_path)("pass")
    assert result == report
    assert not (tmp_path / "private-runner-diagnostics.json").exists()
