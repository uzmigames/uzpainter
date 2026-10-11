"""Tier 0 goldens of the current envelope (`phase0.7_tier0-semantics-ui-cases`, items 3.1-3.3).

The UI cases (`tier0/semantics-ui/`): the height-to-normal method of each texture set and the
group `Passthrough` mode, set through Painter's UI and named in each manifest's settings sheet
(decisions 029, 047); and the documented-API recordings Phase 1 analyses requested
(`tier0/semantics/resample-uv-minify`, `-impulse`, `group-coverage-order`; decision 048). Store
and guard checks that need the owner's private store skip, saying so, without one (decision 028).
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.guard.guard import Snapshot, load_index, run_guard, worktree_snapshot
from tools.parity.recorder.job import load_job
from tools.parity.recorder.texture_sheet import texture_sheet
from tools.parity.schemas import REPO_ROOT, Schema, load_json, validation_errors
from tools.parity.store.manifest import verify
from tools.parity.store.store import Status, load_oracle, locate
from tools.parity.tier0_semantics import fixtures
from tools.parity.tier0_semantics.corpus import FIXTURE_DIR, MESH_SETS
from tools.parity.tier0_semantics.current import (
    AMPLITUDES,
    GROUP_MASKS,
    HEIGHT_METHODS,
    PASSTHROUGH,
    SEMANTICS_DIR,
    UI_DIR,
    api_goldens,
    ui_goldens,
)

ENVELOPE_ROOT = manifest_root(current_envelope())


def ui_paths() -> list[Path]:
    return sorted((ENVELOPE_ROOT / UI_DIR).glob("*.json"))


def api_paths() -> list[Path]:
    return [ENVELOPE_ROOT / SEMANTICS_DIR / f"{g.name}.json" for g in api_goldens()]


def needs_store() -> Any:
    store = locate()
    if store is None:
        pytest.skip("no private oracle store on this machine (hosted CI, decision 028)")
    return store


def test_the_ui_corpus_is_committed() -> None:
    assert [p.stem for p in ui_paths()] == sorted(g.name for g in ui_goldens())
    assert all(p.is_file() for p in api_paths())


@pytest.mark.parametrize("path", [*ui_paths(), *api_paths()], ids=lambda p: p.stem)
def test_manifest_validates_and_lists_two_recordings(path: Path) -> None:
    """Item 3.1: schema, the current envelope's build, and `r1`/`r2` of every exported map."""
    manifest = load_json(path)
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest["software"]["painter"]["build_id"] == current_envelope()["painter_build"]
    records = manifest["private_records"]
    assert any(r["kind"] == "private_oracle_record" for r in records)
    r1 = sorted(r["record_id"][3:] for r in records if r["record_id"].startswith("r1-"))
    r2 = sorted(r["record_id"][3:] for r in records if r["record_id"].startswith("r2-"))
    assert r1 and r1 == r2, "both recordings carry the same outputs"
    kinds = {r["kind"] for r in records}
    assert "exported_map" in kinds
    if path.parent.name == Path(UI_DIR).name:
        assert "settings_panel_evidence" in kinds, "each UI value has private panel evidence"


@pytest.mark.parametrize("path", ui_paths(), ids=lambda p: p.stem)
def test_every_ui_set_value_is_named_in_the_settings_sheet(path: Path) -> None:
    """Item 3.1: each UI-set setting is in `applied_settings` (`operator_settings_sheet`)."""
    job = load_job(path)
    sheet = texture_sheet(job)
    assert sheet, "a UI-case golden names its UI-set values"
    if path.stem.startswith("height-normal-"):
        method = HEIGHT_METHODS[path.stem.split("-")[2]]
        create = job.state_steps[0].args["mesh"]
        assert sorted(str(e.texture_set) for e in sheet) == sorted(MESH_SETS[create])
        assert {e.value for e in sheet} == {method}
        if path.stem.endswith("-plane-strength"):
            assert len(AMPLITUDES) == len(MESH_SETS["grid4x2"]) == 8
    else:
        groups = [s.step for s in job.state_steps if s.call.endswith("insert_group")]
        passthrough = groups[: len(GROUP_MASKS)]
        assert {(e.node_step, e.channel) for e in sheet} == {
            (g, c) for g in passthrough for c in ("User0", "User1", "User2")
        }
        assert {e.value for e in sheet} == {PASSTHROUGH}


def test_every_manifest_hash_resolves_in_the_store() -> None:
    """Item 3.2: `uzpainter parity verify` over every manifest (owner's machine)."""
    store = needs_store()
    for path in [*ui_paths(), *api_paths()]:
        results = verify(store, load_json(path))
        assert results and all(r.status == Status.AVAILABLE for r in results), path.stem


def stored_record(store: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    ref = next(r for r in manifest["private_records"] if r["kind"] == "private_oracle_record")
    data = load_oracle(store, ref)
    assert data is not None
    record: dict[str, Any] = json.loads(data)
    return record


@pytest.mark.parametrize("path", ui_paths(), ids=lambda p: p.stem)
def test_stored_records_hold_the_verified_sheet_in_both_recordings(path: Path) -> None:
    """Item 4.1: every UI-set value was verified when applied (r1) and after the reopen (r2);
    a layer's mode also through the documented `Node.get_blending_mode`."""
    store = needs_store()
    manifest = load_json(path)
    sheet = texture_sheet(load_job(path))
    record = stored_record(store, manifest)
    assert [r["condition"] for r in record["recordings"]] == ["same_session", "after_save_reopen"]
    for recording in record["recordings"]:
        outputs = recording["outputs"]
        (entries,) = [o["entries"] for o in outputs if o["kind"] == "operator_recorded_settings"]
        assert {(e["panel"], e["setting"], e["value"]) for e in entries} == {
            (e.panel, e.name.split("/", 1)[1], e.value) for e in sheet
        }
        assert sum(o["kind"] == "settings_panel_evidence" for o in outputs) == len(sheet)
        modes = {
            (o["args"]["node_step"], o["args"]["channel"]): o["value"]
            for o in outputs
            if o["kind"] == "api_readback" and o["call"].endswith("get_blending_mode")
        }
        for entry in sheet:
            if entry.node_step is not None:
                assert modes[(entry.node_step, entry.channel)] == entry.value


def test_the_ui_corpus_passes_the_guard() -> None:
    """Item 3.3: only manifests and authored fixtures are committed."""
    snapshot = worktree_snapshot(
        REPO_ROOT,
        (
            (ENVELOPE_ROOT / UI_DIR).relative_to(REPO_ROOT).as_posix(),
            (ENVELOPE_ROOT / SEMANTICS_DIR).relative_to(REPO_ROOT).as_posix(),
            FIXTURE_DIR,
        ),
    )
    assert snapshot.checked
    store = locate()
    index = None if store is None else load_index(store.root / "index.json")
    assert [str(f) for f in run_guard(REPO_ROOT, snapshot, index)] == []


@pytest.mark.parametrize("kind", ["settings_panel_evidence", "exported_map"])
def test_a_panel_image_or_export_placed_in_the_repository_is_rejected(kind: str) -> None:
    """Item 3.3: a stored panel image or export staged in the repository is blocked by hash."""
    store = needs_store()
    index = load_index(store.root / "index.json")
    ref = next(r for p in ui_paths() for r in load_json(p)["private_records"] if r["kind"] == kind)
    data = load_oracle(store, ref)
    assert data is not None
    path = f"{FIXTURE_DIR}/bitmaps/recorded-{kind}.png"
    findings = run_guard(REPO_ROOT, Snapshot((path,), (path,), lambda _: data), index)
    assert any(f.rule == "store-hash" for f in findings)


def png_rows(data: bytes) -> list[list[tuple[int, int, int]]]:
    """Rows of a filter-0 RGB16 PNG written by `fixtures.png16`."""
    chunks: dict[str, bytes] = {}
    offset = 8
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        name = data[offset + 4 : offset + 8].decode("ascii")
        chunks[name] = chunks.get(name, b"") + data[offset + 8 : offset + 8 + length]
        offset += length + 12
    width, height = struct.unpack(">II", chunks["IHDR"][:8])
    raw = zlib.decompress(chunks["IDAT"])
    stride = 1 + width * 6
    return [
        [
            struct.unpack(">HHH", raw[y * stride + 1 + x * 6 : y * stride + 7 + x * 6])
            for x in range(width)
        ]
        for y in range(height)
    ]


def test_impulse_fixture_matches_the_request() -> None:
    """compositor-resample-gaps.md section 3: R impulses on 0, G impulses on 16384, B step."""
    rows = png_rows((REPO_ROOT / FIXTURE_DIR / "bitmaps" / "impulse64.png").read_bytes())
    assert len(rows) == len(rows[0]) == 64
    for y, row in enumerate(rows):
        for x, (r, g, b) in enumerate(row):
            hit = (x, y) in fixtures.IMPULSE_TEXELS
            assert (r, g, b) == (65535 if hit else 0, 49152 if hit else 16384, 65535 * (x < 32))
