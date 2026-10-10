"""P0-STORE acceptance gate (phase0.5_private-oracle-store, `docs/dag.md`).

One store and one throwaway git repository, both outside this repository, exercise the store
commands (`parity/STORE.md`) and the committed pre-commit guard (`parity/GUARD.md`) together on
the same commit: an authored sample makes the record → delete → fetch → verify round trip; a
stand-in for a recorded PNG and one for a recorded JSON readback, recorded into that store with
`record`, are rejected by `git commit`; the authored fixture image and expectation JSON
(`tests/parity/guard_data/`) are committed. Nothing here comes from Painter.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from tools.parity.schemas import REPO_ROOT, load_json
from tools.parity.store.cli import main as store_main
from tools.parity.store.manifest import load_manifest
from tools.parity.store.store import STORE_ENV

DATA = Path(__file__).parent / "guard_data"
AUTHORED_IMAGE = DATA / "authored-checker.png"
AUTHORED_EXPECTATION = DATA / "authored-expectation.json"
IMAGE_PATH = "parity/fixtures/images/authored-checker.png"
EXPECTATION_PATH = "parity/manifests/guard/srgb8-checker-decode.json"
HOOKS = REPO_ROOT / ".githooks"
# An authored sample: a 2x2 8-bit greyscale PGM written by this test, nothing recorded.
AUTHORED_SAMPLE = b"P5 2 2 255\n" + bytes([0, 64, 128, 255])
RECORDED_PNG_PATH = "parity/fixtures/images/basecolor.png"
READBACK_PATH = "notes/opacity-readback.json"


def _png(width: int, height: int, rgb: bytes) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    rows = b"".join(b"\0" + rgb[y * width * 3 : (y + 1) * width * 3] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No real store, no user or system git configuration, a fixed git identity."""
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "no-store"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT))
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Store Gate Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "store-gate-test@example.invalid")


def store_cli(store: Path, *args: str | Path) -> int:
    return store_main(["--store", str(store), *(str(a) for a in args)])


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    hooks = ["-c", f"core.hooksPath={HOOKS.as_posix()}"]
    return subprocess.run(
        ["git", "-C", str(repo), *hooks, *args], capture_output=True, text=True, check=False
    )


def stage(repo: Path, path: str, data: bytes) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    assert git(repo, "add", "--", path).returncode == 0


def test_p0_store_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / "store"
    assert store_cli(store, "init") == 0
    monkeypatch.setenv(STORE_ENV, str(store))

    # Round trip: record an authored sample, delete the local copy, fetch it by its manifest.
    manifest = tmp_path / "manifests" / "gate.json"
    manifest.parent.mkdir()
    document = load_json(AUTHORED_EXPECTATION)
    document["golden_id"] = "gate/store-round-trip"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    recorded = tmp_path / "recorded"
    recorded.mkdir()
    sample = recorded / "authored-sample.pgm"
    sample.write_bytes(AUTHORED_SAMPLE)
    record = ["--record-id", "authored-sample", "--kind", "exported_map", "--file", str(sample)]
    assert store_cli(store, "record", manifest, *record) == 0
    (ref,) = load_manifest(manifest)["private_records"]
    assert ref["sha256"] == hashlib.sha256(AUTHORED_SAMPLE).hexdigest()
    sample.unlink()
    assert store_cli(store, "fetch", manifest, "--out", tmp_path / "fetched") == 0
    fetched = tmp_path / "fetched" / "authored-sample.pgm"
    assert hashlib.sha256(fetched.read_bytes()).hexdigest() == ref["sha256"]
    assert store_cli(store, "verify", manifest) == 0
    assert store_cli(store, "verify") == 0

    # A machine without the store (hosted CI) gets oracle_unavailable for the same manifest.
    hosted = {k: v for k, v in os.environ.items() if k != STORE_ENV}
    hosted["LOCALAPPDATA"] = str(tmp_path / "hosted-appdata")
    unavailable = subprocess.run(
        [sys.executable, "-m", "tools.parity.store", "verify", str(manifest)],
        cwd=REPO_ROOT,
        env=hosted,
        capture_output=True,
        text=True,
        check=False,
    )
    assert unavailable.returncode == 1, unavailable.stderr
    assert "authored-sample" in unavailable.stdout and "oracle_unavailable" in unavailable.stdout

    # Stand-ins for a recorded PNG and a recorded JSON readback, recorded into the same store.
    pixels = bytes(
        (x * 37 + y * 11 + c * 5) % 256 for y in range(4) for x in range(4) for c in range(3)
    )
    png = recorded / "basecolor.png"
    png.write_bytes(_png(4, 4, pixels))
    readback = recorded / "opacity-readback.json"
    readback.write_bytes(
        b'{"call": "substance_painter.layerstack.Node.get_opacity", "value": 0.5}\n'
    )
    for record_id, kind, source in [
        ("basecolor", "exported_map", png),
        ("opacity-readback", "api_readback", readback),
    ]:
        record = ["--record-id", record_id, "--kind", kind, "--file", str(source)]
        assert store_cli(store, "record", manifest, *record) == 0

    # Same commit of the guard, run by the committed hook in a throwaway repository.
    repo = tmp_path / "repo"
    repo.mkdir()
    assert git(repo, "init", "-q").returncode == 0
    stage(repo, IMAGE_PATH, AUTHORED_IMAGE.read_bytes())
    stage(repo, EXPECTATION_PATH, AUTHORED_EXPECTATION.read_bytes())
    accepted = git(repo, "commit", "-q", "-m", "authored fixture image and expectation")
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr

    for path, source in [(RECORDED_PNG_PATH, png), (READBACK_PATH, readback)]:
        stage(repo, path, source.read_bytes())
        rejected = git(repo, "commit", "-q", "-m", f"recorded {path}")
        assert rejected.returncode != 0
        assert f"BLOCKED {path}: [store-hash]" in rejected.stdout + rejected.stderr
        assert git(repo, "rm", "-q", "--cached", "--", path).returncode == 0
    assert git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"
