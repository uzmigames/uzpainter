"""Mocked native/store boundaries; never launches Painter, imports a fixture or builds binaries."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from tools.parity import filter_observation_fixture as fixture
from tools.parity import filter_observation_import as observation
from tools.parity.store.store import OracleStore


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def authored(tmp_path: Path) -> fixture.Request:
    source = tmp_path / "base.uzp"
    manifest = tmp_path / "manifest.json"
    export = tmp_path / "export.exe"
    pyapi = tmp_path / "pyapi.exe"
    for path, data in (
        (source, b"authored-base"),
        (manifest, b"{}"),
        (export, b"authored-export"),
        (pyapi, b"authored-pyapi"),
    ):
        path.write_bytes(data)
    return fixture.Request(
        source,
        digest(source.read_bytes()),
        manifest,
        export,
        digest(export.read_bytes()),
        pyapi,
        digest(pyapi.read_bytes()),
        tmp_path / "new-fixture",
    )


def mock_boundaries(
    monkeypatch: pytest.MonkeyPatch, request: fixture.Request, failure: str = ""
) -> tuple[list[str], Mock]:
    calls: list[str] = []
    store = Mock(spec=OracleStore)
    paths = fixture.outputs(request.output_prefix)

    def payload(
        given_store: OracleStore,
        manifest: dict[str, Any],
        base: dict[str, Any],
        *,
        texture_set: int,
        stack: int,
    ) -> dict[str, Any]:
        assert given_store is store and texture_set == 41 and stack == 73
        assert base["projection"]["texture_sets"][0]["id"] == 41
        calls.append("payload")
        if failure == "payload":
            raise ValueError("PRIVATE_SENTINEL_PAYLOAD")
        return {"authored": True, "readbacks": {"same_session": {}, "after_save_reopen": {}}}

    def native(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert kwargs["cwd"] == request.output_prefix.parent
        assert kwargs["timeout"] == 600 and kwargs["check"] is False
        stage = (
            "lifecycle"
            if command[0] == str(request.pyapi_binary)
            else ("base" if command[1] == "filter-observation-base" else "import")
        )
        calls.append(stage)
        kwargs["stdout"].write(b"PRIVATE_SENTINEL_NATIVE\n")
        kwargs["stderr"].write(b"PRIVATE_SENTINEL_STDERR\n")
        if failure == stage:
            return subprocess.CompletedProcess(command, 1)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 600)
        if stage == "base":
            assert paths["base"].read_bytes() == b""
            assert Path(command[2]) == paths["project"]
            paths["base"].write_text(
                json.dumps({"projection": {"texture_sets": [{"id": 41, "stacks": [{"id": 73}]}]}}),
                encoding="utf-8",
            )
        elif stage == "import":
            assert json.loads(paths["payload"].read_bytes())["authored"] is True
            paths["project"].write_bytes(b"authored-imported")
            if failure == "source_changed":
                request.project.write_bytes(b"changed-by-external-writer")
        else:
            script = paths["script"].read_text(encoding="utf-8")
            compile(script, str(paths["script"]), "exec")
            assert "tests." not in script and "sys.path" not in script
            assert str(paths["project"]) in script or repr(str(paths["project"])) in script
            result = {"status": "ok", "result": failure != "bad_report"}
            kwargs["stdout"].write(("UZP_JSON:" + json.dumps(result) + "\n").encode())
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(observation, "admitted_payload", payload)
    monkeypatch.setattr(subprocess, "run", native)
    return calls, store


def test_complete_flow_is_owned_private_and_uses_admitted_payload(
    authored: fixture.Request, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, store = mock_boundaries(monkeypatch, authored)
    result = fixture.create_fixture(authored, store)
    paths = fixture.outputs(authored.output_prefix)
    assert calls == ["base", "payload", "import", "lifecycle"]
    assert result["status"] == "complete" and result["observations"] == 2
    assert result["project_sha256"] == digest(b"authored-imported")
    assert authored.project.read_bytes() == b"authored-base"
    private = json.loads(paths["report"].read_bytes())
    assert private["source_unchanged"] is True
    assert set(private["reserved_outputs"]) == set(paths)
    assert "PRIVATE_SENTINEL" not in json.dumps(result)
    assert "PRIVATE_SENTINEL_NATIVE" in paths["base_stdout"].read_text()


@pytest.mark.parametrize(
    "failure", ["base", "payload", "import", "lifecycle", "bad_report", "timeout", "source_changed"]
)
def test_failures_keep_diagnostics_and_never_reuse_outputs(
    authored: fixture.Request, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    _, store = mock_boundaries(monkeypatch, authored, failure)
    result = fixture.create_fixture(authored, store)
    paths = fixture.outputs(authored.output_prefix)
    assert result["status"] == "refused"
    assert "PRIVATE_SENTINEL" not in json.dumps(result)
    private = json.loads(paths["report"].read_bytes())
    assert private["source_unchanged"] is (failure != "source_changed")
    if failure != "source_changed":
        assert authored.project.read_bytes() == b"authored-base"
    before = {key: path.read_bytes() for key, path in paths.items()}
    with pytest.raises(ValueError):
        fixture.create_fixture(authored, store)
    assert before == {key: path.read_bytes() for key, path in paths.items()}


@pytest.mark.parametrize("failure", ["hash", "binary_hash", "wal", "lock", "existing", "sidecar"])
def test_preflight_refuses_without_native_or_overwrite(
    authored: fixture.Request, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    paths = fixture.outputs(authored.output_prefix)
    if failure == "hash":
        authored = replace(authored, project_sha256="0" * 64)
    elif failure == "binary_hash":
        authored = replace(authored, export_sha256="0" * 64)
    elif failure in ("wal", "lock"):
        Path(str(authored.project) + ("-wal" if failure == "wal" else ".lock")).write_bytes(b"held")
    elif failure == "existing":
        paths["payload"].write_bytes(b"keep")
    else:
        Path(str(paths["project"]) + "-wal").write_bytes(b"keep")
    native = Mock(side_effect=AssertionError("native must not run"))
    monkeypatch.setattr(subprocess, "run", native)
    with pytest.raises(ValueError):
        fixture.create_fixture(authored, Mock(spec=OracleStore))
    assert not native.called and authored.project.read_bytes() == b"authored-base"
    assert not paths["report"].exists()
    if failure == "existing":
        assert paths["payload"].read_bytes() == b"keep"


def test_cli_sanitizes_preflight_failure(
    authored: fixture.Request, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ["fixture"]
    for name, value in vars(authored).items():
        arguments.extend(["--" + name.replace("_", "-"), str(value)])
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(fixture, "locate", lambda: None)
    assert fixture.main() == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"status": "refused", "observations": 0}
    assert captured.err == ""
