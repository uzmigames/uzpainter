"""Repository guard (phase0.4_oracle-store-guard, `parity/GUARD.md`).

The "recorded" PNG and JSON readback are stand-ins this test writes outside the repository (in
a temporary folder) and records into a temporary store; nothing comes from Painter. The authored
fixture image and expectation JSON are committed under `tests/parity/guard_data/`. Each case
runs in a throwaway git repository with an isolated git configuration.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.parity.guard.cli import main
from tools.parity.guard.guard import (
    content_hashes,
    run_guard,
    staged_snapshot,
    worktree_snapshot,
)
from tools.parity.schemas import REPO_ROOT, SCHEMA_DIR, Schema, load_json, validation_errors
from tools.parity.store.store import STORE_ENV, OracleStore, sha256_file

DATA = Path(__file__).parent / "guard_data"
AUTHORED_IMAGE = DATA / "authored-checker.png"
AUTHORED_EXPECTATION = DATA / "authored-expectation.json"
IMAGE_PATH = "parity/fixtures/images/authored-checker.png"
EXPECTATION_PATH = "parity/manifests/guard/srgb8-checker-decode.json"
PRIVATE_SAMPLE = SCHEMA_DIR / "samples" / "private" / "api-readback-record.json"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "parity.yml"
HOOK = REPO_ROOT / ".githooks" / "pre-commit"


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


def _readback_record() -> dict[str, Any]:
    """A private record shaped like a recorder readback, re-labelled as a non-sample."""
    record: dict[str, Any] = copy.deepcopy(load_json(PRIVATE_SAMPLE))
    record["note"] = "Stand-in for a recorded readback, written by the guard test."
    record["golden_id"] = "tier0/api-probe-set-get"
    record["key"]["painter_build"]["build_id"] = "12.1.0-stand-in"
    return record


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No real store, no user or system git configuration, a fixed git identity."""
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "no-store"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Guard Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "guard-test@example.invalid")


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """The recorded stand-ins, outside the repository."""
    folder = tmp_path / "outside"
    folder.mkdir()
    pixels = bytes(
        (x * 37 + y * 11 + c * 5) % 256 for y in range(4) for x in range(4) for c in range(3)
    )
    (folder / "basecolor.png").write_bytes(_png(4, 4, pixels))
    (folder / "readback.json").write_text(
        json.dumps(_readback_record(), indent=2) + "\n", encoding="utf-8"
    )
    return folder


@pytest.fixture
def store(tmp_path: Path, outside: Path) -> OracleStore:
    """A store holding both recorded stand-ins; its index is all the guard reads."""
    oracle = OracleStore.init(tmp_path / "store")
    for name in ("basecolor.png", "readback.json"):
        oracle.put_blob(outside / name, sha256_file(outside / name)[0])
    return oracle


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    assert git(root, "init", "-q").returncode == 0
    return root


def put(repo: Path, path: str, data: bytes, stage: bool = True) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    if stage:
        assert git(repo, "add", "--", path).returncode == 0


def add_authored(repo: Path) -> None:
    put(repo, IMAGE_PATH, AUTHORED_IMAGE.read_bytes())
    put(repo, EXPECTATION_PATH, AUTHORED_EXPECTATION.read_bytes())


def blocked(repo: Path, index: frozenset[str] | None, staged: bool = True) -> dict[str, set[str]]:
    snapshot = staged_snapshot(repo) if staged else worktree_snapshot(repo)
    found: dict[str, set[str]] = {}
    for finding in run_guard(repo, snapshot, index):
        found.setdefault(finding.path, set()).add(finding.rule)
    return found


def index_of(store: OracleStore) -> frozenset[str]:
    return frozenset(store.index())


# --- 2.4 test data ---------------------------------------------------------------------------


def test_authored_expectation_validates_and_names_the_authored_image() -> None:
    manifest = load_json(AUTHORED_EXPECTATION)
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    (image,) = manifest["inputs"]
    assert image["path"] == IMAGE_PATH
    assert image["sha256"] == sha256_file(AUTHORED_IMAGE)[0]


def test_recorded_stand_ins_live_outside_the_repository(outside: Path, store: OracleStore) -> None:
    assert not outside.resolve().is_relative_to(REPO_ROOT)
    for name in ("basecolor.png", "readback.json"):
        assert sha256_file(outside / name)[0] in store.index()


# --- 3.1 recorded PNG ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", [IMAGE_PATH.replace("authored-checker", "basecolor"), "docs/img/basecolor.png", "x.bin"]
)
def test_staged_recorded_png_is_blocked(
    repo: Path, outside: Path, store: OracleStore, path: str
) -> None:
    put(repo, path, (outside / "basecolor.png").read_bytes())
    assert blocked(repo, index_of(store)) == {path: {"store-hash"}}


def test_pre_commit_cli_rejects_recorded_png_from_the_local_store(
    repo: Path,
    outside: Path,
    store: OracleStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(STORE_ENV, str(store.root))
    put(repo, "parity/fixtures/images/basecolor.png", (outside / "basecolor.png").read_bytes())
    assert main(["--repo", str(repo), "--staged"]) == 1
    output = capsys.readouterr().out
    assert f"store {store.root}" in output
    assert "BLOCKED parity/fixtures/images/basecolor.png: [store-hash]" in output


def test_pre_commit_hook_rejects_the_commit(
    repo: Path, outside: Path, store: OracleStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The committed hook, enabled with core.hooksPath, stops `git commit`."""
    monkeypatch.setenv(STORE_ENV, str(store.root))
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT))
    hooks = ["-c", f"core.hooksPath={HOOK.parent.as_posix()}"]
    add_authored(repo)
    accepted = git(repo, *hooks, "commit", "-q", "-m", "authored")
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    put(repo, "parity/fixtures/images/basecolor.png", (outside / "basecolor.png").read_bytes())
    rejected = git(repo, *hooks, "commit", "-q", "-m", "recorded")
    assert rejected.returncode != 0
    assert "[store-hash]" in rejected.stdout + rejected.stderr
    assert git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_hook_runs_the_guard_on_the_staged_files() -> None:
    text = HOOK.read_bytes()
    assert text.startswith(b"#!/bin/sh\n") and b"\r\n" not in text
    assert b"python -m tools.parity.guard --staged" in text
    attributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "/.githooks/** text eol=lf" in attributes


# --- 3.2 recorded JSON readback --------------------------------------------------------------


@pytest.mark.parametrize("path", ["parity/manifests/tier0/probe.json", "notes/readback.json"])
def test_recorded_readback_is_blocked_by_hash(
    repo: Path, outside: Path, store: OracleStore, path: str
) -> None:
    put(repo, path, (outside / "readback.json").read_bytes())
    assert "store-hash" in blocked(repo, index_of(store))[path]


def test_line_ending_converted_readback_still_matches_the_index(
    repo: Path, outside: Path, store: OracleStore
) -> None:
    crlf = (outside / "readback.json").read_bytes().replace(b"\n", b"\r\n")
    assert sha256_file(outside / "readback.json")[0] in content_hashes(crlf)
    put(repo, "notes/readback.txt", crlf)
    assert "store-hash" in blocked(repo, index_of(store))["notes/readback.txt"]


@pytest.mark.parametrize(
    "path",
    [
        "parity/manifests/tier0/probe.json",
        "parity/fixtures/tier0/probe.json",
        "parity/semantics/probe.json",
        "parity/manifests/tier0/probe.txt",
        "parity/schema/golden-public.json",
    ],
)
def test_reserialised_readback_fails_the_public_schema(
    repo: Path, outside: Path, store: OracleStore, path: str
) -> None:
    """Re-serialised: the hash no longer matches the index; the content still blocks it."""
    data = json.dumps(json.loads((outside / "readback.json").read_bytes()), separators=(",", ":"))
    assert not content_hashes(data.encode()) & index_of(store)
    put(repo, path, data.encode())
    rules = blocked(repo, index_of(store))[path]
    assert "store-hash" not in rules
    assert {"public-schema", "private-record"} <= rules


def test_bare_readback_value_under_parity_is_blocked(repo: Path) -> None:
    readback = {"call": "substance_painter.layerstack.Node.get_opacity", "value": 0.5}
    put(repo, "parity/manifests/tier0/opacity.json", json.dumps(readback).encode())
    assert blocked(repo, None) == {"parity/manifests/tier0/opacity.json": {"public-schema"}}


def test_readback_outside_parity_is_blocked_by_its_content(repo: Path) -> None:
    record = json.dumps({"captured": [_readback_record()]})
    put(repo, "tests/data/capture.json", record.encode())
    assert blocked(repo, None) == {"tests/data/capture.json": {"private-record"}}


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r,
        lambda r: {**r, "note": "Synthetic sample, honest."},
        lambda r: {**r, "note": "Synthetic sample, honest.", "golden_id": "samples/tier0/x"},
    ],
)
def test_readback_relabelled_as_synthetic_sample_is_blocked(repo: Path, change: Any) -> None:
    path = "parity/schema/samples/private/probe.json"
    put(repo, path, json.dumps(change(_readback_record())).encode())
    assert blocked(repo, None) == {path: {"public-schema"}}


def test_invalid_json_under_parity_is_blocked(repo: Path) -> None:
    put(repo, "parity/manifests/broken.json", b'{"schema": ')
    assert blocked(repo, None) == {"parity/manifests/broken.json": {"public-schema"}}


# --- 3.3 authored data passes ----------------------------------------------------------------


@pytest.mark.parametrize("staged", [True, False])
def test_authored_fixture_and_expectation_pass(
    repo: Path, store: OracleStore, staged: bool
) -> None:
    add_authored(repo)
    assert blocked(repo, index_of(store), staged=staged) == {}
    assert len(staged_snapshot(repo).checked) == 2


def test_a_json_fixture_declared_by_an_envelope_manifest_passes(repo: Path) -> None:
    """Goldens first recorded under a later envelope declare their authored inputs in the
    envelope's manifests (decision 087)."""
    recipe = b'{"exportPresets": [], "exportList": [{"rootPath": "s0"}]}\n'
    manifest = load_json(AUTHORED_EXPECTATION)
    manifest["inputs"].append(
        {
            "input_id": "probe",
            "kind": "recipe_json",
            "path": "parity/fixtures/tier0/probe-config.json",
            "sha256": hashlib.sha256(recipe).hexdigest(),
            "provenance": {"origin": "uzmigames_authored", "licence": "Apache-2.0"},
        }
    )
    envelope = "parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/tier0/probe.json"
    put(repo, envelope, json.dumps(manifest).encode())
    put(repo, "parity/fixtures/tier0/probe-config.json", recipe)
    put(repo, "parity/fixtures/tier0/stray.json", recipe + b" ")
    assert blocked(repo, None) == {"parity/fixtures/tier0/stray.json": {"public-schema"}}


def test_declared_json_fixture_passes_and_undeclared_one_is_blocked(repo: Path) -> None:
    fixture = b'{"description": "two uniform fills, authored"}\n'
    manifest = load_json(AUTHORED_EXPECTATION)
    manifest["inputs"].append(
        {
            "input_id": "fixture",
            "kind": "fixture_description",
            "path": "parity/fixtures/tier0/fills.json",
            "sha256": hashlib.sha256(fixture).hexdigest(),
            "provenance": {"origin": "uzmigames_authored", "licence": "Apache-2.0"},
        }
    )
    put(repo, EXPECTATION_PATH, json.dumps(manifest).encode())
    put(repo, "parity/fixtures/tier0/fills.json", fixture)
    put(repo, "parity/fixtures/tier0/other.json", fixture)
    assert blocked(repo, None) == {"parity/fixtures/tier0/other.json": {"public-schema"}}
    # Only the manifest is staged now; the fixture is still judged against it.
    assert git(repo, "commit", "-q", "-m", "fixtures").returncode == 0
    put(repo, "parity/fixtures/tier0/fills.json", fixture + b" ")
    assert blocked(repo, None) == {"parity/fixtures/tier0/fills.json": {"public-schema"}}


def test_repository_parity_data_passes_including_synthetic_private_samples() -> None:
    """The contract's synthetic private-shaped samples are allowed by path and synthetic marks;
    every other parity JSON validates against its public schema."""
    snapshot = worktree_snapshot(REPO_ROOT, ["parity/schema", "parity/exceptions.json"])
    assert any(p.startswith("parity/schema/samples/private/") for p in snapshot.checked)
    assert run_guard(REPO_ROOT, snapshot, None) == []


CENSUS_PATH = "parity/reports/phase1/store-census.json"


def _census() -> dict[str, Any]:
    return {
        "schema": "uzpainter/store-census/1",
        "task": "phase1.7_store-inspect-census",
        "date": "2026-10-10",
        "candidate_budget_fraction": 0.1,
        "procedure": {"one_parameter_edits": 20, "raster_plane_format": "sRGB8"},
        "projects": [
            {
                "id": "tunic_v10",
                "spp_bytes": 408723056,
                "dependencies": {
                    "files": 2,
                    "bytes": 35324928,
                    "not_measured": ["painter_baked_mesh_maps"],
                },
                "raster_plane": {"format": "sRGB8", "width": 4096},
                "ratio_to_spp": 0.09,
                "within_candidate_budget": True,
            }
        ],
    }


@pytest.mark.parametrize(
    ("change", "allowed"),
    [
        (lambda c: c, True),
        (lambda c: {**c, "schema": "uzpainter/store-census/2"}, False),
        (lambda c: {**c, "projects": []}, False),
        (lambda c: {**c, "projects": [{"spp_bytes": 1}]}, False),
        (lambda c: {**c, "source": "E:/Assets3D/18-Tunica-v10.spp"}, False),
        (lambda c: {**c, "projects": [{**c["projects"][0], "id": "../tunic"}]}, False),
        (lambda c: {**c, "projects": [{**c["projects"][0], "note": "free text"}]}, False),
    ],
)
def test_store_census_report_holds_numbers_and_identifiers_only(
    repo: Path, change: Any, allowed: bool
) -> None:
    put(repo, CENSUS_PATH, json.dumps(change(_census())).encode())
    assert blocked(repo, None) == ({} if allowed else {CENSUS_PATH: {"public-schema"}})


def test_repository_store_census_report_passes() -> None:
    assert (REPO_ROOT / CENSUS_PATH).is_file()
    snapshot = worktree_snapshot(REPO_ROOT, [CENSUS_PATH])
    assert snapshot.checked == (CENSUS_PATH,)
    assert run_guard(REPO_ROOT, snapshot, None) == []


# --- 3.4 CI ----------------------------------------------------------------------------------


def _hosted_runs() -> list[str]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return [step.get("run", "") for step in workflow["jobs"]["hosted"]["steps"]]


def test_hosted_ci_runs_the_guard_on_every_commit() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    assert {"push", "pull_request"} <= set(triggers)
    assert "python -m tools.parity.guard" in [run.strip() for run in _hosted_runs()]


def _guard_process(repo: Path) -> subprocess.CompletedProcess[str]:
    """`python -m tools.parity.guard` as the hosted job runs it: no store on the machine."""
    env = {k: v for k, v in os.environ.items() if k != STORE_ENV}
    env["LOCALAPPDATA"] = str(repo.parent / "hosted-localappdata")
    return subprocess.run(
        [sys.executable, "-m", "tools.parity.guard", "--repo", str(repo)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_ci_guard_fails_the_job_on_a_commit_with_a_blocked_file(repo: Path, outside: Path) -> None:
    add_authored(repo)
    assert git(repo, "commit", "-q", "-m", "authored").returncode == 0
    clean = _guard_process(repo)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "store-hash rule skipped" in clean.stdout

    data = json.dumps(json.loads((outside / "readback.json").read_bytes()))
    put(repo, "parity/manifests/tier0/probe.json", data.encode())
    assert git(repo, "commit", "-q", "-m", "readback").returncode == 0
    failed = _guard_process(repo)
    assert failed.returncode == 1, failed.stdout + failed.stderr
    assert "BLOCKED parity/manifests/tier0/probe.json: [public-schema]" in failed.stdout


# --- oracle envelopes (phase0.9_oracle-envelope, decision 037) ------------------------------


ENVELOPE_DIR = "parity/envelopes/painter-12.1.5+js-api.1.1.21/manifests"


def test_envelope_registry_and_candidate_manifests_pass(repo: Path) -> None:
    put(
        repo,
        "parity/envelopes/registry.json",
        (REPO_ROOT / "parity/envelopes/registry.json").read_bytes(),
    )
    put(repo, f"{ENVELOPE_DIR}/guard/srgb8-checker-decode.json", AUTHORED_EXPECTATION.read_bytes())
    drafts = {
        "schema": "uzpainter/parity/oracle-envelope-register-drafts/1",
        "study_id": "20261011t120000z",
        "envelope_id": "painter-12.1.0+js-api.1.1.20",
        "status": "prepared_unapproved",
        "owner_fields": ["approved_by", "approved_on"],
        "drafts": [],
    }
    put(
        repo,
        "parity/reports/phase0/oracle-envelope-register-drafts.json",
        json.dumps(drafts).encode(),
    )
    assert blocked(repo, None) == {}
    approved = {**drafts, "drafts": [{"exception_id": "EXC-009", "approved_by": "owner"}]}
    put(
        repo,
        "parity/reports/phase0/oracle-envelope-register-drafts.json",
        json.dumps(approved).encode(),
    )
    broken = {"schema": "uzpainter/parity/envelope-registry/1", "current": "painter-x"}
    put(repo, "parity/envelopes/registry.json", json.dumps(broken).encode())
    assert blocked(repo, None) == {
        "parity/reports/phase0/oracle-envelope-register-drafts.json": {"public-schema"},
        "parity/envelopes/registry.json": {"public-schema"},
    }


def test_private_record_or_store_blob_under_envelopes_is_blocked(
    repo: Path, outside: Path, store: OracleStore
) -> None:
    record = f"{ENVELOPE_DIR}/tier0/probe.json"
    blob = "parity/envelopes/painter-12.1.5+js-api.1.1.21/basecolor.png"
    put(repo, record, (outside / "readback.json").read_bytes())
    put(repo, blob, (outside / "basecolor.png").read_bytes())
    found = blocked(repo, index_of(store))
    assert {"store-hash", "private-record", "public-schema"} <= found[record]
    assert "store-hash" in found[blob]
