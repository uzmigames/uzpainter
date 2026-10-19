"""Public parity records whose file SHA-256 is an evidence identity (`tools/parity/tier1/compare.py`
hashes the manifest file, the runners hash the manifest or the fallback request, gate records
hash reports) keep their committed LF bytes on every checkout: `.gitattributes` pins `eol=lf`
for them, so a checkout with `core.autocrlf=true` yields the committed hash (SUP-009). The
writers emit LF on Windows too.

The checkout test clones HEAD, so it covers what is committed, not uncommitted edits."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools.parity.schemas import REPO_ROOT
from tools.parity.store.manifest import write_manifest
from tools.parity.tier1.compare import write_report

ENVELOPE = "parity/envelopes/painter-12.1.5_js-api.1.1.20"
WAND_MANIFEST = f"{ENVELOPE}/manifests/phase1/tier1/wand-v1.json"
WAND_REPORT = "parity/reports/phase1/tier1-wand-v1.json"
# The pinned records: every JSON file under these paths (`.gitattributes`).
EVIDENCE = (
    "parity/manifests",
    f"{ENVELOPE}/manifests",
    f"{ENVELOPE}/requests",
    "parity/envelopes/registry.json",
    "parity/exceptions.json",
    "parity/semantics",
    "parity/reports",
)


def git(*args: str, cwd: Path) -> bytes:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True).stdout


@pytest.fixture(scope="module")
def autocrlf_checkout(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A clone of HEAD whose pinned records are checked out with core.autocrlf=true, set on this
    clone only."""
    clone = tmp_path_factory.mktemp("autocrlf") / "repo"
    git(
        "-c",
        "core.longpaths=true",
        "clone",
        "--quiet",
        "--shared",
        "--no-checkout",
        str(REPO_ROOT),
        str(clone),
        cwd=REPO_ROOT,
    )
    git("config", "core.autocrlf", "true", cwd=clone)
    git("config", "core.longpaths", "true", cwd=clone)
    git("checkout", "--quiet", "HEAD", "--", ".gitattributes", *EVIDENCE, cwd=clone)
    return clone


def evidence_files(clone: Path) -> list[str]:
    listed = git("ls-files", "-z", "--", *EVIDENCE, cwd=clone).decode("utf-8").split("\0")
    return [path for path in listed if path.endswith(".json")]


def test_the_wand_manifest_keeps_its_committed_lf_hash_under_autocrlf(
    autocrlf_checkout: Path,
) -> None:
    committed = git("cat-file", "blob", f"HEAD:{WAND_MANIFEST}", cwd=autocrlf_checkout)
    checked_out = (autocrlf_checkout / WAND_MANIFEST).read_bytes()
    assert b"\r" not in committed
    assert checked_out == committed
    assert hashlib.sha256(checked_out).hexdigest() == hashlib.sha256(committed).hexdigest()


def test_every_pinned_record_keeps_its_committed_bytes_under_autocrlf(
    autocrlf_checkout: Path,
) -> None:
    files = evidence_files(autocrlf_checkout)
    assert WAND_MANIFEST in files
    changed = [
        path
        for path in files
        if (autocrlf_checkout / path).read_bytes()
        != git("cat-file", "blob", f"HEAD:{path}", cwd=autocrlf_checkout)
    ]
    assert changed == []
    # -z output: path, attribute, value, each NUL-terminated
    fields = subprocess.run(
        ["git", "check-attr", "-z", "--stdin", "eol"],
        cwd=autocrlf_checkout,
        input="\0".join(files).encode("utf-8") + b"\0",
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")[:-1]
    eol = {fields[i].decode("utf-8"): fields[i + 2] for i in range(0, len(fields), 3)}
    assert eol == dict.fromkeys(files, b"lf")


def _manifest(path: Path) -> None:
    write_manifest(path, json.loads((REPO_ROOT / WAND_MANIFEST).read_text(encoding="utf-8")))


def _report(path: Path) -> None:
    write_report(json.loads((REPO_ROOT / WAND_REPORT).read_text(encoding="utf-8")), path)


@pytest.mark.parametrize("write", [_manifest, _report], ids=["store-manifest", "tier1-report"])
def test_writers_emit_lf(write: Callable[[Path], Any], tmp_path: Path) -> None:
    target = tmp_path / "record.json"
    write(target)
    data = target.read_bytes()
    assert b"\r" not in data
    assert data.endswith(b"}\n")
