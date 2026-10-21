"""Private oracle store and `uzpainter parity` commands (phase0.3_oracle-store-cli §3).

Every test uses a temporary store; `UZP_PARITY_STORE` is pointed at a temporary path for the
whole module so that the owner's real store is never touched.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools.parity.schemas import REPO_ROOT, SCHEMA_DIR, load_json
from tools.parity.store.cli import main
from tools.parity.store.manifest import load_manifest, record_file, record_run, verify
from tools.parity.store.store import (
    STORE_ENV,
    OracleStore,
    Status,
    StoreError,
    default_root,
    load_oracle,
    locate,
    resolve_oracle,
)
from tools.parity.verdict import Comparison, Outcome, evaluate

SAMPLES = SCHEMA_DIR / "samples"
PUBLIC_SAMPLE = SAMPLES / "public" / "tier0-blend-multiply.json"
PRIVATE_SAMPLE = SAMPLES / "private" / "exported-map-record.json"
# An authored sample: a 2x2 8-bit greyscale PGM written by this test, nothing recorded.
AUTHORED = b"P5 2 2 255\n" + bytes([0, 64, 128, 255])


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "env-store"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))


@pytest.fixture
def store(tmp_path: Path) -> OracleStore:
    return OracleStore.init(tmp_path / "store")


@pytest.fixture
def manifest_path(tmp_path: Path) -> Path:
    """The Tier 0 sample manifest before anything was recorded (no private records)."""
    document = load_json(PUBLIC_SAMPLE)
    document["private_records"] = []
    path = tmp_path / "manifests" / "blend-multiply.json"
    path.parent.mkdir()
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.fixture
def authored(tmp_path: Path) -> Path:
    path = tmp_path / "recorded" / "basecolor.pgm"
    path.parent.mkdir()
    path.write_bytes(AUTHORED)
    return path


def cli(store: OracleStore, *args: str | Path) -> int:
    return main(["--store", str(store.root), *(str(a) for a in args)])


def record_authored(store: OracleStore, manifest: Path, source: Path, record_id: str) -> int:
    return cli(
        store,
        "record",
        manifest,
        "--record-id",
        record_id,
        "--kind",
        "exported_map",
        "--file",
        source,
    )


# --- layout (2.1) ----------------------------------------------------------------------------


def test_default_root_prefers_the_environment_variable(tmp_path: Path) -> None:
    assert default_root({STORE_ENV: "D:/oracle", "LOCALAPPDATA": "C:/x"}) == Path("D:/oracle")
    assert default_root({"LOCALAPPDATA": "C:/x"}) == Path("C:/x/UzPainter/parity-store")
    assert default_root({}) is None


def test_store_layout_is_content_addressed_and_write_once(
    store: OracleStore, manifest_path: Path, authored: Path
) -> None:
    assert record_authored(store, manifest_path, authored, "basecolor-same-session") == 0
    digest = sha256(AUTHORED)
    blob = store.root / "blobs" / digest[:2] / digest
    assert blob.read_bytes() == AUTHORED
    assert not os.stat(blob).st_mode & stat.S_IWRITE
    assert store.index() == {digest}
    entry = store.root / "corpora/synthetic-sample-build/samples/tier0/blend-multiply-plane"
    document = load_json(entry / "basecolor-same-session.json")
    assert document["sha256"] == digest
    assert document["size_bytes"] == len(AUTHORED)
    assert store.check() == []


def test_an_input_is_stored_by_hash_with_its_pinned_path(
    store: OracleStore, authored: Path
) -> None:
    """Decision 144: an authored input a manifest pins resolves from the store by its hash."""
    digest = sha256(AUTHORED)
    assert cli(store, "input", authored, "--path", "_tmp/claude/mask.pgm") == 0
    assert cli(store, "input", authored, "--path", "_tmp/claude/mask.pgm") == 0  # idempotent
    entry = load_json(store.root / "inputs" / f"{digest}.json")
    assert entry == {
        "schema": "uzpainter/parity/store-input/1",
        "sha256": digest,
        "size_bytes": len(AUTHORED),
        "path": "_tmp/claude/mask.pgm",
    }
    resolution = store.resolve("mask", digest)
    assert resolution.status is Status.AVAILABLE and resolution.path is not None
    assert resolution.path.read_bytes() == AUTHORED
    assert store.index() == {digest} and store.check() == []
    os.chmod(resolution.path, stat.S_IREAD | stat.S_IWRITE)
    resolution.path.unlink()
    store.root.joinpath("index.json").write_text(
        json.dumps({"schema": "uzpainter/parity/store-index/1", "sha256": []}), encoding="utf-8"
    )
    assert any("names a missing blob" in problem for problem in store.check())


def test_init_is_idempotent_and_refuses_foreign_or_repository_folders(tmp_path: Path) -> None:
    root = tmp_path / "store"
    OracleStore.init(root)
    assert OracleStore.init(root).root == root
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(StoreError, match="not empty"):
        OracleStore.init(foreign)
    with pytest.raises(StoreError, match="inside the repository"):
        OracleStore.init(REPO_ROOT / "parity" / "store")


def test_fetch_refuses_a_destination_inside_the_repository(
    store: OracleStore, manifest_path: Path, authored: Path
) -> None:
    record_authored(store, manifest_path, authored, "basecolor-same-session")
    assert cli(store, "fetch", manifest_path, "--out", REPO_ROOT / "parity" / "fetched") == 1
    assert not (REPO_ROOT / "parity" / "fetched").exists()


def test_store_check_finds_a_corrupted_blob(
    store: OracleStore, manifest_path: Path, authored: Path
) -> None:
    record_authored(store, manifest_path, authored, "basecolor-same-session")
    blob = store.blob_path(sha256(AUTHORED))
    os.chmod(blob, stat.S_IREAD | stat.S_IWRITE)
    blob.write_bytes(b"tampered")
    assert any("fails its hash" in problem for problem in store.check())
    assert cli(store, "verify") == 1


# --- 3.1 / 4.1 round trip --------------------------------------------------------------------


def test_round_trip_record_remove_fetch_verify(
    store: OracleStore, manifest_path: Path, authored: Path, tmp_path: Path
) -> None:
    assert record_authored(store, manifest_path, authored, "basecolor-same-session") == 0
    manifest = load_manifest(manifest_path)
    (ref,) = manifest["private_records"]
    assert ref == {
        "record_id": "basecolor-same-session",
        "kind": "exported_map",
        "sha256": sha256(AUTHORED),
        "size_bytes": len(AUTHORED),
    }
    authored.unlink()

    out = tmp_path / "fetched"
    assert cli(store, "fetch", manifest_path, "--out", out) == 0
    fetched = out / "basecolor-same-session.pgm"
    assert sha256(fetched.read_bytes()) == ref["sha256"]
    assert cli(store, "verify", manifest_path) == 0
    assert cli(store, "verify") == 0


def test_verify_of_a_directory_leaves_out_the_gltf_consumer_fixture_only(
    store: OracleStore, manifest_path: Path, authored: Path, tmp_path: Path
) -> None:
    # `parity/manifests` also holds the glTF consumer fixture, which names no store blob.
    assert record_authored(store, manifest_path, authored, "basecolor-same-session") == 0
    tree = tmp_path / "manifests"
    (tree / "consumers" / "gltf").mkdir(parents=True)
    (tree / manifest_path.name).write_bytes(manifest_path.read_bytes())
    fixture = REPO_ROOT / "parity" / "manifests" / "consumers" / "gltf" / "wand-v1.json"
    (tree / "consumers" / "gltf" / "wand-v1.json").write_bytes(fixture.read_bytes())
    assert cli(store, "verify", tree) == 0
    # Any other JSON that is not a golden manifest is still refused.
    (tree / "stray.json").write_text('{"schema": "uzpainter/unknown/1"}', encoding="utf-8")
    assert cli(store, "verify", tree) == 1


def _inbox_run(tmp_path: Path, manifest_sample: dict[str, Any]) -> Path:
    """A recorder run as the oracle inbox holds it (`parity/STORE.md` §4)."""
    run = tmp_path / "inbox" / "samples__tier0__blend-multiply-plane" / "20261010T120000Z"
    (run / "blobs").mkdir(parents=True)
    record = load_json(PRIVATE_SAMPLE)
    refs: list[dict[str, Any]] = []
    for recording in record["recordings"]:
        data = AUTHORED + recording["recording_id"].encode()
        blob = recording["outputs"][0]["blob"]
        blob.update(sha256=sha256(data), size_bytes=len(data))
        (run / "blobs" / blob["sha256"]).write_bytes(data)
        record_id = f"{recording['recording_id']}-basecolor"
        refs.append(
            {
                "record_id": record_id,
                "kind": "exported_map",
                "sha256": blob["sha256"],
                "size_bytes": len(data),
            }
        )
    record_bytes = json.dumps(record).encode()
    (run / "record.json").write_bytes(record_bytes)
    manifest = copy.deepcopy(manifest_sample)
    manifest["private_records"] = [
        {
            "record_id": "golden-record",
            "kind": "private_oracle_record",
            "sha256": sha256(record_bytes),
            "size_bytes": len(record_bytes),
        },
        *refs,
    ]
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "READY").write_bytes(b"")
    return run


def test_round_trip_through_a_recorder_run(store: OracleStore, tmp_path: Path) -> None:
    run = _inbox_run(tmp_path, load_json(PUBLIC_SAMPLE))
    target = tmp_path / "manifests" / "blend-multiply.json"
    assert cli(store, "record", target, "--run", run) == 0
    manifest = load_manifest(target)
    assert [r["record_id"] for r in manifest["private_records"]] == [
        "golden-record",
        "r1-basecolor",
        "r2-basecolor",
    ]
    out = tmp_path / "fetched"
    assert cli(store, "fetch", target, "--out", out) == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "golden-record.json",
        "r1-basecolor.png",
        "r2-basecolor.png",
    ]
    for ref in manifest["private_records"]:
        fetched = next(out.glob(f"{ref['record_id']}.*"))
        assert sha256(fetched.read_bytes()) == ref["sha256"]
    assert cli(store, "verify", target) == 0
    # Ingesting the same run again changes nothing.
    assert record_run(store, target, run) == manifest


def test_recorder_run_without_ready_marker_is_refused(store: OracleStore, tmp_path: Path) -> None:
    run = _inbox_run(tmp_path, load_json(PUBLIC_SAMPLE))
    (run / "READY").unlink()
    with pytest.raises(StoreError, match="READY"):
        record_run(store, tmp_path / "target.json", run)
    assert store.index() == set()


def test_private_record_of_another_golden_is_refused(
    store: OracleStore, manifest_path: Path, tmp_path: Path
) -> None:
    record = load_json(PRIVATE_SAMPLE)
    record["golden_id"] = "samples/tier0/other"
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(StoreError, match="golden"):
        record_file(store, manifest_path, "golden-record", "private_oracle_record", path)


# --- 3.2 missing blob ------------------------------------------------------------------------


def test_missing_blob_reports_oracle_unavailable(
    store: OracleStore, capsys: pytest.CaptureFixture[str]
) -> None:
    # The sample manifest names synthetic hashes that are in no store.
    assert cli(store, "verify", PUBLIC_SAMPLE) == 1
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("  ")]
    assert len(lines) == len(load_json(PUBLIC_SAMPLE)["private_records"])
    assert all("oracle_unavailable" in line and "blob missing" in line for line in lines)
    results = verify(store, load_json(PUBLIC_SAMPLE))
    assert {r.status for r in results} == {Status.ORACLE_UNAVAILABLE}


def test_unreadable_or_mismatched_blob_reports_oracle_unavailable(
    store: OracleStore, manifest_path: Path, authored: Path, tmp_path: Path
) -> None:
    record_authored(store, manifest_path, authored, "basecolor-same-session")
    (ref,) = load_manifest(manifest_path)["private_records"]
    blob = store.blob_path(ref["sha256"])
    os.chmod(blob, stat.S_IREAD | stat.S_IWRITE)
    blob.write_bytes(AUTHORED[:-1] + b"\x00")
    assert resolve_oracle(store, ref).reason.startswith("blob fails its hash")
    assert load_oracle(store, ref) is None
    assert cli(store, "fetch", manifest_path, "--out", tmp_path / "fetched") == 1
    blob.unlink()
    blob.mkdir()  # a directory where the blob should be: unreadable
    assert resolve_oracle(store, ref).status is Status.ORACLE_UNAVAILABLE
    assert cli(store, "verify", manifest_path) == 1


def test_missing_oracle_makes_the_comparison_oracle_unavailable(store: OracleStore) -> None:
    (ref, *_) = load_json(PUBLIC_SAMPLE)["private_records"]
    oracle = load_oracle(store, ref)
    assert oracle is None
    verdict = evaluate(Comparison("0", "tier0/blend/multiply/BaseColor", oracle, [0.25]), [])
    assert verdict.outcome is Outcome.ORACLE_UNAVAILABLE


# --- 3.3 immutability ------------------------------------------------------------------------


def test_different_blob_under_an_existing_record_id_is_refused(
    store: OracleStore, manifest_path: Path, authored: Path, tmp_path: Path
) -> None:
    assert record_authored(store, manifest_path, authored, "basecolor-same-session") == 0
    before = manifest_path.read_bytes()
    other = tmp_path / "other.pgm"
    other.write_bytes(AUTHORED[:-1] + b"\x7f")
    assert record_authored(store, manifest_path, other, "basecolor-same-session") == 1
    assert manifest_path.read_bytes() == before
    assert store.index() == {sha256(AUTHORED)}
    # The store refuses it on its own too, e.g. from a manifest that never named the record.
    fresh = tmp_path / "fresh.json"
    document = load_json(manifest_path)
    document["private_records"] = []
    fresh.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(StoreError, match="refusing"):
        record_file(store, fresh, "basecolor-same-session", "exported_map", other)
    assert store.index() == {sha256(AUTHORED)}


def test_recording_the_same_blob_again_is_idempotent(
    store: OracleStore, manifest_path: Path, authored: Path
) -> None:
    assert record_authored(store, manifest_path, authored, "basecolor-same-session") == 0
    before = manifest_path.read_bytes()
    assert record_authored(store, manifest_path, authored, "basecolor-same-session") == 0
    assert manifest_path.read_bytes() == before


def test_records_are_kept_per_painter_build(
    store: OracleStore, manifest_path: Path, authored: Path, tmp_path: Path
) -> None:
    assert record_authored(store, manifest_path, authored, "basecolor-same-session") == 0
    document = load_json(manifest_path)
    document["software"]["painter"]["build_id"] = "synthetic-next-build"
    document["private_records"] = []
    next_build = tmp_path / "next-build.json"
    next_build.write_text(json.dumps(document), encoding="utf-8")
    other = tmp_path / "other.pgm"
    other.write_bytes(AUTHORED + b"\x01")
    assert record_authored(store, next_build, other, "basecolor-same-session") == 0
    corpora = sorted(p.name for p in (store.root / "corpora").iterdir())
    assert corpora == ["synthetic-next-build", "synthetic-sample-build"]


# --- 3.4 a machine without the store (decision 200) ------------------------------------------


def test_machine_without_store_reports_oracle_unavailable(tmp_path: Path) -> None:
    environment = {
        key: value for key, value in os.environ.items() if key not in {STORE_ENV, "LOCALAPPDATA"}
    }
    environment["LOCALAPPDATA"] = str(tmp_path / "no-store-appdata")
    assert locate(environment) is None
    completed = subprocess.run(
        [sys.executable, "-m", "tools.parity.store", "verify", str(PUBLIC_SAMPLE)],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1, completed.stderr
    lines = [line for line in completed.stdout.splitlines() if line.startswith("  ")]
    assert lines
    assert all("oracle_unavailable" in line for line in lines)
    ref = load_json(PUBLIC_SAMPLE)["private_records"][0]
    assert resolve_oracle(None, ref).status is Status.ORACLE_UNAVAILABLE
    verdict = evaluate(Comparison("0", "d", load_oracle(None, ref), [0.0]), [])
    assert verdict.outcome is Outcome.ORACLE_UNAVAILABLE


def test_store_inside_the_repository_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STORE_ENV, str(REPO_ROOT / "parity" / "store"))
    with pytest.raises(StoreError, match="inside the repository"):
        locate()
