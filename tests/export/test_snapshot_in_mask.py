"""Item 2.15 of `phase3.3_procedural-families` (decision 431): project-private snapshots inside
mask stacks.

The project is the private derived artifact of `tests/python/capture_snapshot_in_mask_session.py`:
UzPainter's own project on the authored plane at 256 px with four authored mesh maps, holding the
2.13/2.14 grunges and generators captured in the Painter session that also recorded the Tier 0
goldens `snapshot-in-mask-session` and `snapshot-in-mask-read`. It is resolved from the private
oracle store by hash and size; without it, or without the goldens, the tests skip as
`oracle_unavailable`. Messages name counts and hashes only.

- A fixed grunge snapshot (`grunge/rock`, `grunge/dirt-large`) as a mask fill effect's source is
  served, and the channel's CPU read-out equals every Painter recording of it on every texel.
- The 16-bit read on this path: the bitmap holding every 16-bit code once, as the only mask effect,
  reads out as the golden on all 65 536 texels, which is G(k) = 1 + (F(k) - 1).
- A seeded grunge snapshot as a mask source and a generator effect are refused before mutation.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tools.parity.fit.snapshot_in_mask import golden_maps, read_g
from tools.parity.store.store import OracleStore, Status, locate, resolve_oracle
from tools.parity.tier0_semantics.snapshot_in_mask import (
    BITMAPS,
    NAME,
    READ_NAME,
    SESSION_NAME,
    SOURCE_CASES,
    SOURCES_NAME,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
# The one-session capture of 2026-11-11 (Painter lock seq 2378/2379).
PROJECT_BLOB: dict[str, Any] = {
    "record_id": "snapshot-in-mask-session-project",
    "sha256": "24fdf328c0c7aef3902d1a384f3fa53dcb6382996ac27f33bc1da873db3b8942",
    "size_bytes": 1413120,
}
# The signatures `assets snapshot` reported for that capture.
ROCK = "2c598e07d7d63accb37edf033bbb9a09eeae999276099c1e9c53a7b392092d12"
DIRT_LARGE = "7be9fb4de842be5d4ca675993809c4c7c57a6b07d814d4dc937b00003127f9d3"
DIRT_A_SEED_1 = "a174cc25c82ae2baf3ca86592a925f71f00caa7719749b77b5316293ab995fd9"
DIRT = "408670191a3836e77a195e613bae7de7a7a0095261e94fa2ab5d1e933c2f2315"
TEXELS = 256 * 256


def effect(**fields: Any) -> dict[str, Any]:
    return {"mode": "Normal", "opacity": 1.0, **fields}


def black(*effects: dict[str, Any]) -> dict[str, Any]:
    return {"background": "Black", "effects": list(effects)}


def oracle_store() -> OracleStore:
    store = locate()
    if store is None:
        pytest.skip("oracle_unavailable: no private store on this machine")
    return store


def staged_project(store: OracleStore, tmp_path: Path) -> Path:
    resolved = resolve_oracle(store, PROJECT_BLOB)
    if resolved.status != Status.AVAILABLE or resolved.path is None:
        pytest.skip(f"oracle_unavailable: {resolved.reason}")
    target = tmp_path / "snapshot-in-mask.uzp"
    target.write_bytes(resolved.path.read_bytes())
    data = target.read_bytes()
    if (hashlib.sha256(data).hexdigest(), len(data)) != (
        PROJECT_BLOB["sha256"],
        PROJECT_BLOB["size_bytes"],
    ):
        pytest.fail("the copied capture project differs from its store record", pytrace=False)
    return target


def run_cases(
    binary: Path, project: Path, work: Path, cases: list[dict[str, Any]], refusals: list[Any]
) -> tuple[list[np.ndarray], list[str]]:
    spec = work / "cases.json"
    spec.write_text(json.dumps({"cases": cases, "refusals": refusals}), encoding="utf-8")
    proc = subprocess.run(
        [str(binary), "snapshot-in-mask", str(project), str(spec), str(work / "out")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = proc.stdout.splitlines()
    served = [line for line in lines if line.startswith("SERVED ")]
    assert len(served) == len(cases), proc.stdout
    rasters = [
        np.fromfile(work / "out" / f"user{k}.raw", dtype=np.float32) for k in range(len(cases))
    ]
    refused = [line.split(" ", 2)[2] for line in lines if line.startswith("REFUSED ")]
    assert len(refused) == len(refusals), proc.stdout
    return rasters, refused


def mismatches(ours: np.ndarray, theirs: np.ndarray) -> int:
    assert ours.shape == theirs.shape == (TEXELS,)
    return int((ours.view(np.uint32) != theirs.view(np.uint32)).sum())


def test_fixed_grunges_and_the_16_bit_read_equal_painter_in_a_mask(
    export_tests: Path, tmp_path: Path
) -> None:
    """`grunge/rock` and `grunge/dirt-large` as the only effect of a black mask at Normal 1 equal
    every recording of them in a mask, and the bitmap of every 16-bit code reads out as the
    `snapshot-in-mask-read` golden: G(k) = 1 + (F(k) - 1) on all 65 536 codes."""
    store = oracle_store()
    project = staged_project(store, tmp_path)
    try:
        session = golden_maps(store, SESSION_NAME)
        read = golden_maps(store, READ_NAME)
        earlier = golden_maps(store, NAME)
        sources = golden_maps(store, SOURCES_NAME)
    except (KeyError, FileNotFoundError, ValueError) as error:
        pytest.skip(f"oracle_unavailable: {error}")
    codes = REPO_ROOT / BITMAPS / "mask-codes.png"
    cases = [
        black(effect(signature_sha256=ROCK)),
        black(effect(signature_sha256=DIRT_LARGE)),
        black(effect(bitmap=str(codes))),
    ]
    rasters, _ = run_cases(export_tests, project, tmp_path, cases, [])
    index = {case.case_id: k for k, case in enumerate(SOURCE_CASES)}
    references = {
        "rock (this session)": (0, session, 0),
        "rock (2026-11-10)": (0, earlier, 0),
        "rock (fresh session)": (0, sources, index["rock"]),
        "dirt-large (fresh session)": (1, sources, index["dirt-large"]),
        "every code (this session)": (2, read, 0),
    }
    for label, (ours, maps, user) in references.items():
        for recording in ("r1", "r2"):
            off = mismatches(rasters[ours], maps[(recording, user)])
            assert off == 0, f"{label} {recording}: {off} texels differ"
    every = np.arange(TEXELS, dtype=np.int64)
    assert mismatches(read_g(every), read[("r1", 0)]) == 0


def test_seeded_snapshots_and_generator_effects_are_refused_in_a_mask(
    export_tests: Path, tmp_path: Path
) -> None:
    """A seeded grunge snapshot as a mask source is refused naming decision 431, and a generator
    effect as the generator release gap, both before mutation."""
    store = oracle_store()
    project = staged_project(store, tmp_path)
    refusals = [
        black(effect(signature_sha256=DIRT_A_SEED_1)),
        black(effect(signature_sha256=DIRT, generator=True)),
    ]
    served = [black(effect(signature_sha256=ROCK))]
    _, refused = run_cases(export_tests, project, tmp_path, served, refusals)
    assert "decision 431" in refused[0] and "grunge/rock" in refused[0], refused[0]
    assert "a generator effect" in refused[1], refused[1]
