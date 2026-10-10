"""Tier 0 semantics goldens (`phase0.6_tier0-semantics-goldens`, tasks 3.1-3.4).

The manifests under `parity/manifests/tier0/semantics/` are the corpus: authored fixtures,
UzmiGames instruction sequences, and the SHA-256 of each private record. The store and guard
checks that need the owner's private store skip, saying so, on a machine without one (hosted
CI, decision 028); the local oracle run on the owner's machine is their evidence.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tools.parity.guard.guard import Snapshot, load_index, run_guard, worktree_snapshot
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import load_job
from tools.parity.schemas import REPO_ROOT, Schema, load_json, validation_errors
from tools.parity.store.manifest import verify
from tools.parity.store.store import Status, load_oracle, locate
from tools.parity.tier0_semantics.__main__ import problems
from tools.parity.tier0_semantics.corpus import (
    COVERAGE,
    FIXTURE_DIR,
    MANIFEST_DIR,
    OWNED_ELSEWHERE,
    TEMPLATES,
)

ARCHITECTURE = REPO_ROOT / "docs" / "architecture" / "04-layer-stack-and-compositing.md"
CHANNEL_FORMATS = {"sRGB8", "L8", "RGB8", "L16", "RGB16", "L16F", "RGB16F", "L32F", "RGB32F"}


def manifest_paths() -> list[Path]:
    return sorted((REPO_ROOT / MANIFEST_DIR).glob("*.json"))


def manifests() -> dict[str, dict[str, Any]]:
    return {path.stem: load_json(path) for path in manifest_paths()}


def needs_store() -> Any:
    store = locate()
    if store is None:
        pytest.skip("no private oracle store on this machine (hosted CI, decision 028)")
    return store


def test_committed_fixtures_and_manifests_match_the_corpus() -> None:
    assert problems() == []
    assert len(manifest_paths()) >= 20


@pytest.mark.parametrize("path", manifest_paths(), ids=lambda p: p.stem)
def test_manifest_validates_and_is_a_recorder_job(path: Path) -> None:
    manifest = load_json(path)
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    job = load_job(path)
    assert job.golden_id == f"tier0/semantics/{path.stem}"
    assert job.exports, "every golden exports at least one map"
    for export in job.exports:
        file_format, depth = export.parameters["fileFormat"], export.parameters["bitDepth"]
        assert (file_format, depth) in {("png", "16"), ("exr", "32f")}


@pytest.mark.parametrize("path", manifest_paths(), ids=lambda p: p.stem)
def test_manifest_lists_two_recordings(path: Path) -> None:
    """Task 3.1: the record and the exports of `r1` (same session) and `r2` (after reopen)."""
    records = load_json(path)["private_records"]
    kinds = {(r["record_id"].split("-", 1)[0], r["kind"]) for r in records}
    assert ("golden", "private_oracle_record") in kinds
    assert {("r1", "exported_map"), ("r2", "exported_map")} <= kinds
    r1 = sorted(r["record_id"][3:] for r in records if r["record_id"].startswith("r1-"))
    r2 = sorted(r["record_id"][3:] for r in records if r["record_id"].startswith("r2-"))
    assert r1 == r2, "both recordings carry the same outputs"


def section_9_items() -> list[str]:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    section = text.split("## 9.", 1)[1]
    sentence = section.split("\n", 1)[1].strip().split(". Each has", 1)[0]
    return [item.strip() for item in sentence.split(";")]


def test_every_section_9_item_maps_to_a_golden() -> None:
    """Task 3.3: each 04 section 9 item resolves to at least one golden of the corpus."""
    items = section_9_items()
    assert sorted(items) == sorted([*COVERAGE, *OWNED_ELSEWHERE])
    domains = {m["domain"] for m in manifests().values()}
    for item, covering in COVERAGE.items():
        assert covering and set(covering) <= domains, item


def test_quantisation_experiment_covers_every_channel_format() -> None:
    steps = manifests()["quantisation-thirds"]["instruction_sequence"]["steps"]
    formats = {s["args"]["format"] for s in steps if s["call"] == ps.ADD_CHANNEL}
    assert formats == CHANNEL_FORMATS
    opacities = {s["args"]["opacity"] for s in steps if s["call"] == ps.SET_OPACITY}
    assert opacities == {1.0 / 3.0}


def test_base_values_cover_the_default_and_every_shipped_template() -> None:
    corpus = manifests()
    templates = set()
    for name, manifest in corpus.items():
        if name.startswith("base-values-"):
            create = manifest["instruction_sequence"]["steps"][0]["args"]
            templates.add(create.get("template"))
    assert templates == {None, *TEMPLATES}


def test_blend_sweeps_cover_every_documented_mode_the_runtime_accepts() -> None:
    modes: set[str] = set()
    for name, manifest in manifests().items():
        if name.startswith("blend-"):
            modes |= {
                s["args"]["blending_mode"]
                for s in manifest["instruction_sequence"]["steps"]
                if s["call"] == ps.SET_BLENDING_MODE
            }
    listed = ARCHITECTURE.read_text(encoding="utf-8").split("are implemented as kernels: `", 1)[1]
    documented = {mode.strip() for mode in listed.split("`", 1)[0].split(",")}
    assert len(documented) == 32
    # PassThrough is a group mode that Painter 12.1.0 does not accept through the API (open
    # owner question, parity/TIER0-SEMANTICS.md section 1).
    assert modes == documented - {"PassThrough"}


def test_every_manifest_hash_resolves_in_the_store() -> None:
    """Task 3.2: `uzpainter parity verify` over the corpus (owner's machine)."""
    store = needs_store()
    for name, manifest in manifests().items():
        results = verify(store, manifest)
        assert results and all(r.status == Status.AVAILABLE for r in results), name


def test_repository_corpus_passes_the_guard() -> None:
    """Task 3.4: fixtures and manifests are authored inputs and public manifests only."""
    snapshot = worktree_snapshot(REPO_ROOT, (MANIFEST_DIR, FIXTURE_DIR))
    assert snapshot.checked
    store = locate()
    index = None if store is None else load_index(store.root / "index.json")
    assert [str(f) for f in run_guard(REPO_ROOT, snapshot, index)] == []


def test_a_recorded_export_placed_in_the_repository_is_rejected() -> None:
    """Task 3.4: a recorded 16-bit export staged under the fixtures is blocked by its hash."""
    store = needs_store()
    index = load_index(store.root / "index.json")
    ref = next(
        r for m in manifests().values() for r in m["private_records"] if r["kind"] == "exported_map"
    )
    data = load_oracle(store, ref)
    assert data is not None
    path = f"{FIXTURE_DIR}/bitmaps/recorded-export.png"
    snapshot = Snapshot((path,), (path,), lambda _: data)
    findings = run_guard(REPO_ROOT, snapshot, index)
    assert any(f.rule == "store-hash" for f in findings)
    assert re.search(r"[0-9a-f]{64}", str(findings[0]))
