"""Output test (task 3.2): records validate against `golden-private.json`, manifests against
`golden-public.json`, and no record is written inside the repository tree."""

from __future__ import annotations

import copy
import hashlib
import json
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder.job import Job
from tools.parity.recorder.output import (
    INBOX_ENV,
    MANIFEST_FILE,
    READY_FILE,
    RECORD_FILE,
    WORK_ENV,
    inbox_root,
    slug,
    work_root,
    write_run,
)
from tools.parity.recorder.session import PainterSession, RecorderError
from tools.parity.recorder.texture import record_texture_golden
from tools.parity.schemas import REPO_ROOT, Schema, record_problems, validation_errors

MakeSession = Callable[[Any], PainterSession]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exported_blobs(run: Path) -> list[Path]:
    """The run's blobs that hold exports (the environment record's blob is JSON)."""
    blobs = sorted((run / "blobs").iterdir())
    return [b for b in blobs if b.read_bytes().startswith(b"\x89PNG")]


@pytest.fixture
def run(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> Path:
    return record_texture_golden(make_session(fake.FakeWorld()), sample_job, work, inbox)


def test_record_and_manifest_validate(run: Path) -> None:
    record = json.loads((run / RECORD_FILE).read_text(encoding="utf-8"))
    manifest = json.loads((run / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert record_problems(record) == []
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert record["golden_id"] == manifest["golden_id"]
    assert (run / READY_FILE).is_file()


def test_manifest_lists_every_private_hash(run: Path) -> None:
    record = json.loads((run / RECORD_FILE).read_text(encoding="utf-8"))
    refs = json.loads((run / MANIFEST_FILE).read_text(encoding="utf-8"))["private_records"]
    assert refs[0]["kind"] == "private_oracle_record"
    assert refs[0]["sha256"] == sha256(run / RECORD_FILE)
    assert refs[0]["size_bytes"] == (run / RECORD_FILE).stat().st_size
    exported = [
        (rec["recording_id"], o["blob"]["sha256"])
        for rec in record["recordings"]
        for o in rec["outputs"]
        if o["kind"] == "exported_map"
    ]
    assert refs[-1]["kind"] == "oracle_environment_record"
    assert [(r["record_id"].split("-", 1)[0], r["sha256"]) for r in refs[1:-1]] == exported
    for ref in refs[1:]:
        blob = run / "blobs" / ref["sha256"]
        assert sha256(blob) == ref["sha256"] and blob.stat().st_size == ref["size_bytes"]


def test_recorded_export_stays_private(run: Path, work: Path) -> None:
    """Spec scenario: the 16-bit PNG exists only in the private directories; the public manifest
    holds its SHA-256 and nothing else of it."""
    manifest_text = (run / MANIFEST_FILE).read_text(encoding="utf-8")
    for blob in exported_blobs(run):
        assert blob.name in manifest_text
        assert not blob.resolve().is_relative_to(REPO_ROOT)
    assert not run.resolve().is_relative_to(REPO_ROOT)
    assert not work.resolve().is_relative_to(REPO_ROOT)
    assert "\x89PNG" not in manifest_text and "IHDR" not in manifest_text


def test_inbox_inside_the_repository_is_refused(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path
) -> None:
    inside = REPO_ROOT / "parity" / "oracle-inbox-must-not-exist"
    with pytest.raises(RecorderError, match="inside the repository"):
        record_texture_golden(make_session(fake.FakeWorld()), sample_job, work, inside)
    assert not inside.exists()


def test_work_directory_inside_the_repository_is_refused(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, inbox: Path
) -> None:
    inside = REPO_ROOT / "parity" / "oracle-work-must-not-exist"
    with pytest.raises(RecorderError, match="inside the repository"):
        record_texture_golden(make_session(fake.FakeWorld()), sample_job, inside, inbox)
    assert not inside.exists()


def test_private_directories_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(INBOX_ENV, str(tmp_path / "in"))
    monkeypatch.setenv(WORK_ENV, str(tmp_path / "work"))
    assert inbox_root() == (tmp_path / "in").resolve()
    assert work_root() == (tmp_path / "work").resolve()
    monkeypatch.setenv(INBOX_ENV, str(REPO_ROOT / "tools"))
    with pytest.raises(RecorderError, match="inside the repository"):
        inbox_root()
    monkeypatch.delenv(INBOX_ENV)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    assert inbox_root() == (tmp_path / "appdata" / "UzPainter" / "oracle-inbox").resolve()


def test_invalid_record_is_not_written(run: Path, sample_job: Job, tmp_path: Path) -> None:
    record = json.loads((run / RECORD_FILE).read_text(encoding="utf-8"))
    blobs = exported_blobs(run)
    single = copy.deepcopy(record)
    single["recordings"] = single["recordings"][:1]
    target = tmp_path / "second-inbox"
    with pytest.raises(RecorderError, match="private record invalid"):
        write_run(target, single, blobs, sample_job.manifest, "s")
    stamped = copy.deepcopy(record)
    stamped["recordings"][0]["recorded_at"] = "2026-10-10T12:00:00"
    with pytest.raises(RecorderError, match="no UTC offset"):
        write_run(target, stamped, blobs, sample_job.manifest, "s")
    assert not target.exists()


def test_manifest_of_another_painter_build_is_refused(
    run: Path, sample_job: Job, tmp_path: Path
) -> None:
    record = json.loads((run / RECORD_FILE).read_text(encoding="utf-8"))
    manifest = copy.deepcopy(sample_job.manifest)
    manifest["software"]["painter"]["build_id"] = "12.1.0+js-api.0.0.1"
    target = tmp_path / "second-inbox"
    with pytest.raises(RecorderError, match="immutable per Painter build"):
        write_run(target, record, exported_blobs(run), manifest, "s")
    assert not target.exists()


def test_missing_blob_is_refused(run: Path, sample_job: Job, tmp_path: Path) -> None:
    record = json.loads((run / RECORD_FILE).read_text(encoding="utf-8"))
    target = tmp_path / "second-inbox"
    with pytest.raises(RecorderError, match="missing"):
        write_run(target, record, [], sample_job.manifest, "s")
    assert not target.exists()


@pytest.mark.parametrize(
    ("text", "expected"), [("r1", "r1"), ("Set A/BaseColor", "set-a-basecolor"), ("__", "output")]
)
def test_record_id_slug(text: str, expected: str) -> None:
    assert slug(text) == expected
