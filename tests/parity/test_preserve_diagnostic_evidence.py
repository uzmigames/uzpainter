"""Authored evidence copies only; no native process, oracle or fixture capture."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

from tools.parity import preserve_diagnostic_evidence as evidence
from tools.parity.recorder.session import RecorderError


def test_files_roundtrip_with_pins_and_private_index(tmp_path: Path) -> None:
    sources = [tmp_path / "readback.json", tmp_path / "runner.json"]
    contents = [b'{"private":"authored"}', b'{"status":"ok"}']
    for path, data in zip(sources, contents, strict=True):
        path.write_bytes(data)
    hashes = [hashlib.sha256(data).hexdigest() for data in contents]
    output = tmp_path / "preserved.zip"
    report = evidence.preserve(sources, output, expected_sha256=hashes)
    assert report == {
        "status": "complete",
        "files": 2,
        "source_bytes": sum(map(len, contents)),
        "archive_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    with zipfile.ZipFile(output) as archive:
        index = json.loads(archive.read(evidence.INDEX))
        for entry, path, data, digest in zip(
            index["files"], sources, contents, hashes, strict=True
        ):
            assert archive.read(entry["member"]) == path.read_bytes() == data
            assert entry["sha256"] == digest and entry["size_bytes"] == len(data)
    assert all(str(path) not in json.dumps(report) for path in sources)


def test_directory_preserves_nested_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "evidence.bin").write_bytes(bytes(range(256)))
    output = tmp_path / "preserved.zip"
    assert evidence.preserve([source], output)["files"] == 1
    with zipfile.ZipFile(output) as archive:
        assert archive.read("source-0000/nested/evidence.bin") == bytes(range(256))


@pytest.mark.parametrize("refusal", ["existing", "wrong_hash", "inside_repo", "overlap", "parent"])
def test_refuses_before_writing(tmp_path: Path, refusal: str) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(b"original")
    output = tmp_path / "preserved.zip"
    repo = tmp_path / "repository"
    repo.mkdir()
    hashes = [hashlib.sha256(source.read_bytes()).hexdigest()]
    if refusal == "existing":
        output.write_bytes(b"keep")
    elif refusal == "wrong_hash":
        hashes = ["0" * 64]
    elif refusal == "inside_repo":
        output = repo / "private.zip"
    elif refusal == "overlap":
        output = source
    else:
        output = tmp_path / "missing" / "private.zip"
    with pytest.raises((ValueError, RecorderError)):
        evidence.preserve([source], output, expected_sha256=hashes, repo_root=repo)
    assert source.read_bytes() == b"original"
    if refusal == "existing":
        assert output.read_bytes() == b"keep"
    elif refusal != "overlap":
        assert not output.exists()


def test_changed_source_retains_partial_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(b"before")
    output = tmp_path / "preserved.zip"
    original = evidence.file_fingerprint
    calls = 0

    def changing(path: Path) -> tuple[str, int]:
        nonlocal calls
        result = original(path)
        calls += 1
        if calls == 1:
            source.write_bytes(b"after")
        return result

    monkeypatch.setattr(evidence, "file_fingerprint", changing)
    with pytest.raises(ValueError, match="source changed"):
        evidence.preserve([source], output)
    assert source.read_bytes() == b"after" and output.exists()
    with zipfile.ZipFile(output) as archive:
        assert evidence.INDEX not in archive.namelist()


def test_linked_source_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(b"authored")
    output = tmp_path / "preserved.zip"
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == source or original(path))
    with pytest.raises(ValueError, match="links"):
        evidence.preserve([source], output)
    assert not output.exists()


def test_cli_refusal_never_prints_private_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "preserve",
            "--source",
            str(tmp_path / "PRIVATE_SENTINEL"),
            "--output",
            str(tmp_path / "archive.zip"),
        ],
    )
    assert evidence.main() == 2
    output = capsys.readouterr()
    assert json.loads(output.out) == {"status": "refused"} and output.err == ""
