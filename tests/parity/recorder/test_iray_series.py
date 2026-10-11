"""Iray reference series and the `ref_match` session environment (task
`phase0.7_render-reference-captures`; decisions 038, 039 and 046): a session-environment step
names its file by SHA-256 and the recorder stages the given file; `iray --launch` records one
reference per fresh Painter process, skips goldens that already hold the condition and goes on
after a refusal."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder import __main__ as cli
from tools.parity.recorder.iray import (
    K_TIMES_SAMPLES,
    SEPARATE_SESSION,
    record_iray_reference,
    reference_needed,
)
from tools.parity.recorder.job import Job, job_from_manifest
from tools.parity.recorder.session import PainterSession, RecorderError

HERE = Path(__file__).parent


def load_helpers() -> types.ModuleType:
    """The sibling `test_iray.py` (job builder and scripted operator), loaded by path."""
    name = "uzp_test_iray_helpers"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / "test_iray.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


helpers = load_helpers()
HDRI_BYTES = b"authored ref_match stand-in"
HDRI_SHA = hashlib.sha256(HDRI_BYTES).hexdigest()


def session_environment_job(tmp_path: Path, digest: str = HDRI_SHA) -> Job:
    base = helpers.make_iray_job(tmp_path)
    manifest = copy.deepcopy(base.manifest)
    (step,) = [
        s
        for s in manifest["instruction_sequence"]["steps"]
        if s["call"] == "substance_painter.display.set_environment_resource"
    ]
    step["args"] = {"session_environment": digest, "file_name": "RefMatch-Standin.exr"}
    manifest["inputs"] = [i for i in manifest["inputs"] if i["input_id"] != "env"]
    return job_from_manifest(manifest, repo_root=tmp_path / "repo")


def hdri(tmp_path: Path) -> Path:
    path = tmp_path / "outside" / "standin.exr"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(HDRI_BYTES)
    return path


def record_one(
    fake: types.ModuleType,
    job: Job,
    work: Path,
    inbox: Path,
    condition: str = SEPARATE_SESSION,
    session_files: tuple[Path, ...] = (),
    k: int | None = None,
) -> Path | None:
    samples = helpers.S * (k or 1)
    operator = helpers.ScriptedOperator(fake, work.parent / "panels", samples)
    session = PainterSession(fake.LocalTransport(fake.FakeWorld()), sleep=lambda seconds: None)
    return record_iray_reference(
        session, job, condition, operator, work, inbox, k, session_files=session_files
    )


def test_session_environment_is_staged_from_the_given_file(
    fake: types.ModuleType, tmp_path: Path, work: Path, inbox: Path
) -> None:
    job = session_environment_job(tmp_path)
    assert record_one(fake, job, work, inbox, session_files=(hdri(tmp_path),)) is None
    (staged,) = (work / "iray-staging").glob("*/*/staged.json")
    key = json.loads(staged.read_text(encoding="utf-8"))["key"]
    assert {"resource": f"session:{HDRI_SHA}", "sha256": HDRI_SHA} in key["resource_hashes"]
    assert key["render_state"]["environment_url"].endswith("/RefMatch-Standin")


def test_session_environment_without_its_file_is_refused(
    fake: types.ModuleType, tmp_path: Path, work: Path, inbox: Path
) -> None:
    job = session_environment_job(tmp_path)
    other = tmp_path / "other.exr"
    other.write_bytes(b"not the file")
    with pytest.raises(RecorderError, match="no --session-file has SHA-256"):
        record_one(fake, job, work, inbox, session_files=(other,))
    assert not (work / "iray-staging").exists()


def test_session_environment_must_name_a_hash(tmp_path: Path) -> None:
    with pytest.raises(RecorderError, match="must be a SHA-256"):
        session_environment_job(tmp_path, digest="not-a-hash")


def test_reference_needed_follows_the_staging(
    fake: types.ModuleType, tmp_path: Path, work: Path, inbox: Path
) -> None:
    job = helpers.make_iray_job(tmp_path)
    assert reference_needed(job, SEPARATE_SESSION, work)
    record_one(fake, job, work, inbox)
    assert reference_needed(job, SEPARATE_SESSION, work)
    record_one(fake, job, work, inbox)
    assert not reference_needed(job, SEPARATE_SESSION, work)
    assert reference_needed(job, K_TIMES_SAMPLES, work)
    admitted = copy.deepcopy(job.manifest)
    admitted["private_records"] = [{"record_id": "golden-record"}]
    assert not reference_needed(
        job_from_manifest(admitted, repo_root=tmp_path / "repo"), K_TIMES_SAMPLES, work
    )


class FakeLauncher:
    """Counts the Painter processes the series starts; each start is a new Painter session."""

    def __init__(self, fake: types.ModuleType) -> None:
        self.fake = fake
        self.events: list[str] = []
        self.transport: Any = None

    def start(self) -> None:
        self.events.append("start")
        self.transport = self.fake.LocalTransport(self.fake.FakeWorld())

    def stop(self, session: PainterSession | None = None) -> None:
        self.events.append("stop")

    def run(self, code: str) -> Any:
        """The remote endpoint of the Painter started last."""
        return self.transport.run(code)


def series_args(manifests: list[Path], **extra: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "manifests": manifests,
        "condition": SEPARATE_SESSION,
        "k": None,
        "launch": True,
        "painter_exe": None,
        "host": "localhost",
        "port": 60041,
        "operator": "console",
        "operator_id": "test-operator",
        "session_file": [],
    }
    return argparse.Namespace(**(values | extra))


def write_manifest(job: Job, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(job.manifest), encoding="utf-8")
    return path


def test_series_records_each_reference_in_a_fresh_painter(
    fake: types.ModuleType,
    tmp_path: Path,
    work: Path,
    inbox: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    good = helpers.make_iray_job(tmp_path)
    broken = copy.deepcopy(good.manifest)
    broken["golden_id"] = "tests/tier3/sphere-broken"
    (sample,) = [s for s in broken["applied_settings"] if s["name"] == "Iray Settings/Max Sample"]
    sample["value"] = helpers.S * 2  # Min Sample != Max Sample: refused before Painter is used
    directory = tmp_path / "manifests"
    first = write_manifest(good, directory / "a-good.json")
    second = write_manifest(job_from_manifest(broken, tmp_path / "repo"), directory / "b.json")
    launcher = FakeLauncher(fake)
    monkeypatch.setenv("UZP_ORACLE_WORK", str(work))
    monkeypatch.setenv("UZP_ORACLE_INBOX", str(inbox))
    monkeypatch.setattr(
        cli,
        "load_job",
        lambda path: job_from_manifest(
            json.loads(path.read_text(encoding="utf-8")), tmp_path / "repo"
        ),
    )
    monkeypatch.setattr(cli, "HttpTransport", lambda host, port: launcher)
    monkeypatch.setattr(
        cli,
        "make_operator",
        lambda kind: helpers.ScriptedOperator(fake, work.parent / "panels", helpers.S),
    )
    monkeypatch.setattr(PainterSession, "__init__", session_without_sleep(PainterSession.__init__))
    # The broken sheet is refused; the series goes on and still stops its Painter.
    assert cli.run_iray(series_args([directory]), launcher) == 2
    assert launcher.events == ["start", "stop"] * 2
    out = capsys.readouterr()
    assert f"{first}: reference staged" in out.out and f"{second}: refused" in out.err
    assert cli.run_iray(series_args([first]), launcher) == 0
    assert launcher.events == ["start", "stop"] * 3
    assert cli.run_iray(series_args([first]), launcher) == 0  # two sessions staged: skipped
    assert launcher.events == ["start", "stop"] * 3
    assert "already staged or admitted" in capsys.readouterr().out


def session_without_sleep(init: Any) -> Any:
    def wrapped(self: PainterSession, transport: Any, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("sleep", lambda seconds: None)
        init(self, transport, *args, **kwargs)

    return wrapped


def test_several_references_need_launch(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert cli.run_iray(series_args([a, b], launch=False)) == 2
    assert "need --launch" in capsys.readouterr().err
