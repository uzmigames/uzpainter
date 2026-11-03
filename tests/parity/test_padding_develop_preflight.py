"""Authored checks of H1 (`padding_develop32`) and its preflight (`padding_develop_preflight`),
independent of Painter recordings: the frozen helpers, requests and predictions keep their
hashes; `devhook` redirects farhook's far distance only; the exact affine identity and its
inconclusive case; H1 equals `rod32n` where the turn is exact at the normalised centre; the stop
and reading rules; and one small run of both twin meshes through H1 and every frozen recipe."""

from __future__ import annotations

import hashlib
import types
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tools.parity.fit import padding_develop32 as dev
from tools.parity.fit import padding_develop_preflight as dp
from tools.parity.fit import padding_far32 as far32
from tools.parity.fit import padding_turn_exact as tefit
from tools.parity.fit import padding_turn_exact_preflight as pf
from tools.parity.fit import padding_turn_exact_score as scorer
from tools.parity.fit import padding_world_offset as fit
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import padding_turn_exact as te
from tools.parity.tier0_semantics import padding_world_offset as wo
from tools.parity.tier0_semantics import recording_requests as rr

F32 = np.float32
# `parity/reports/phase1/padding-turn-exact-freeze.md`, tool SHA-256 at freeze (LF bytes).
FROZEN_TOOLS = {
    "tools/parity/tier0_semantics/padding_turn_exact.py": (
        "93c32ce166aaeebc27a575565d8d4b2070df8ea094b3ddcf7f09b2a3812290f3"
    ),
    "tools/parity/tier0_semantics/padding_world_offset.py": (
        "eace51ab3013619b4ec124ccebb4b4488a04188c3794757219f2f9fda34ba800"
    ),
    "tools/parity/fit/padding_turn_exact.py": (
        "71824bdf4a2420b8043fb7eaf20c9fcbbdbb2403c5615b4a197ef6e288e471fa"
    ),
    "tools/parity/fit/padding_turn_exact_preflight.py": (
        "9f642dcf484769a26bc36d428c93a264db728712d0c82aea31eb886c09a738d2"
    ),
    "tools/parity/fit/padding_world_offset_residual.py": (
        "76af4358acc1b5f4c66bec3a7fd196ab7ae6f56bd5b6f3539919d2b06178ffea"
    ),
    "tools/parity/fit/padding_far32.py": (
        "7aef14fa1a7568a73cb52baee491504704eb4a92098cb95ef8b0af590204ec4f"
    ),
    "tools/parity/fit/padding_world_offset.py": (
        "4ea0a45135244a5afc96a476038e5b204e93cfc6fdc2e44cfc37c7084713facd"
    ),
}


def _lf(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_the_frozen_helpers_requests_and_predictions_keep_their_hashes() -> None:
    assert {p: _lf(REPO_ROOT / p) for p in FROZEN_TOOLS} == FROZEN_TOOLS
    assert scorer.compact_problems() == []
    for twin in te.TWINS:
        mesh = tefit.MESH_PATHS[twin].read_bytes()
        assert hashlib.sha256(mesh).hexdigest() == scorer.FROZEN_MESH_SHA256[twin]
        (request,) = scorer.request_paths(twin)
        assert (
            hashlib.sha256(request.read_bytes()).hexdigest() == (scorer.FROZEN_REQUEST_SHA256[twin])
        )


def test_devhook_redirects_farhook_only() -> None:
    assert dev.FAR32_IMPORT in far32.PATCHES["farhook"][-1][1]  # farhook itself is unchanged
    text = dev.module_text()
    assert text.count(dev.DEVELOP_IMPORT) == 1 and dev.FAR32_IMPORT not in text
    assert text.count(f"FAR_MODEL = '{dev.MODEL}'\n") == 1
    assert "_own32_mixed" in text
    m = dev.selection_module()
    assert m._far_distance is dev.far_distance and m.FAR_MODEL == dev.MODEL
    with pytest.raises(ValueError, match="unknown far model"):
        dev.far_distance("rod32n", m.__dict__, None, (0, 0, 0), (0, 0, 0), 0, 0, 0, (0, 0), (0, 0))


def _tri(p: list[tuple[float, float, float]], uv: list[tuple[float, float]]) -> Any:
    return types.SimpleNamespace(p=p, uv=np.asarray(uv, F32))


def _ring(j: Any) -> Any:
    """tau in z = 0, K in J's plane; J through the x axis (rational normals when J is)."""
    t = _tri([(0, 0, 0), (4, 0, 0), (0, 4, 0)], [(0, 0), (0.5, 0), (0, 0.5)])
    k = _tri([j.p[2], (4, 0, 0), (4, *j.p[2][1:])], [(0.5, 0.5), (1, 0.5), (1, 1)])
    return types.SimpleNamespace(
        tris=[j, t, k], width=8, height=8, box=(np.full(3, -8.0, F32), np.full(3, 8.0, F32))
    )


def test_the_exact_affine_identity_and_its_inconclusive_case() -> None:
    entry = ("turn", None, None, 0, 1, 2)
    oblique = _ring(_tri([(0, 0, 0), (4, 0, 0), (0, 3, 4)], [(0, 0), (0.5, 0), (0, 0.5)]))
    sim = dp.similarity_of(oblique)
    assert sim == ((Fraction(0),) * 3, Fraction(1, 8))
    weights = dp.barycentrics(oblique.tris[2], (2, 2), 8, 8)
    assert sum(weights) == 1 and any(w < 0 for w in weights)  # an extrapolated tap
    d = pf.developed(oblique, entry, (1, 1), (2, 2))
    assert d is not None and d > 0
    assert dp.developed_corners(oblique, entry, (1, 1), (2, 2)) == d
    assert dp.developed_corners(oblique, entry, (1, 1), (2, 2), sim) == d / 64
    assert dp.identity(oblique, entry, (1, 1), (2, 2), sim) == "equal"
    irrational = _ring(_tri([(0, 0, 0), (4, 0, 0), (0, 1, 1)], [(0, 0), (0.5, 0), (0, 0.5)]))
    jc, tc = (dp._corners(irrational.tris[i], None) for i in (0, 1))
    assert dp.exact_frame(jc, tc) is None
    assert dp.identity(irrational, entry, (1, 1), (2, 2), sim) == "inconclusive"


def test_a_rational_difference_is_reported_as_differ(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = ("turn", None, None, 0, 1, 2)
    oblique = _ring(_tri([(0, 0, 0), (4, 0, 0), (0, 3, 4)], [(0, 0), (0.5, 0), (0, 0.5)]))
    sim = dp.similarity_of(oblique)
    d = pf.developed(oblique, entry, (1, 1), (2, 2))
    assert d is not None
    monkeypatch.setattr(pf, "developed", lambda *_: d + Fraction(1, 2**80))
    assert dp.identity(oblique, entry, (1, 1), (2, 2), sim) == "differ"


def test_the_proof_status_voids_or_withholds_certification() -> None:
    assert dp.proof_status({"branches": 3, "equal": 3}) == "branches_equal"
    assert dp.proof_status({"branches": 3, "equal": 2, "differ": 1}) == "invalid"
    assert dp.proof_status({"branches": 3, "equal": 1, "differ": 1, "inconclusive": 1}) == (
        "invalid"
    )
    assert dp.proof_status({"branches": 3, "equal": 2, "inconclusive": 1}) == "uncertified"
    assert dp.proof_status({}) == "uncertified"


def _report(outcome: str, h1_bits: tuple[int, int]) -> dict[str, Any]:
    """`report` of one centre-lane primary texel: every frozen recipe predicts bits (0, 0), H1
    `h1_bits`; one exercised branch per twin with `outcome`."""

    def row(bits: int) -> dict[str, Any]:
        return {"taps": [[True, [2, 1]]], "count": 1, "decided": True, "bits": [bits]}

    found = {
        "copies": [{"lane": "centre"}],
        "mask": {"primary": ["1,1"]},
        "texels": {"1,1": {"copy": 0, **{tw: {r: row(0) for r in dp.RECIPES} for tw in te.TWINS}}},
    }
    h1 = {tw: {"1,1": row(b)} for tw, b in zip(te.TWINS, h1_bits, strict=True)}
    proofs = {tw: {"1,1": {"calls": 2, "branches": 1, outcome: 1}} for tw in te.TWINS}
    return dp.report(found, h1, proofs)


def test_an_invalid_proof_stops_and_voids_the_reading() -> None:
    out = _report("differ", (0, 1))
    assert out["proof"]["status"] == "invalid"
    assert out["proof"]["x90"]["primary:differ"] == 1
    assert out["stop"]["stop"] and out["stop"]["indistinguishable"] == []
    assert out["reading"].startswith("invalid:") and "void" in out["reading"]


def test_an_inconclusive_proof_certifies_nothing() -> None:
    out = _report("inconclusive", (0, 1))
    assert out["proof"]["status"] == "uncertified"
    assert not out["stop"]["stop"]
    assert out["reading"].endswith("proof uncertified: not certified")
    out = _report("inconclusive", (0, 0))
    assert out["stop"]["stop"] and out["stop"]["indistinguishable"] == list(dp.RECIPES)
    assert out["reading"].startswith("stop:") and "not certified" in out["reading"]


def test_the_report_counts_patterns_and_the_twin_reading() -> None:
    out = _report("equal", (0, 1))
    assert out["proof"]["status"] == "branches_equal"
    assert out["masks"] == {"primary": 1, "centre": 1, "slots": 1}
    for r in dp.RECIPES:
        assert out["bits"]["primary"][r] == {"x90": 0, "oblique": 1, "pattern:AD": 1}
    assert out["twins"]["primary"][dp.H1] == 1 and out["twins"]["primary"]["double"] == 0
    assert out["reading"] == "H1 predicts 1 primary twin differences; no score taken"
    out = _report("equal", (1, 1))
    assert out["twins"]["primary"][dp.H1] == 0
    text = out["reading"]
    assert "rejects only this complete, fixed H1" in text and "observed 31" in text
    assert text.endswith("not the double-development family")
    out = _report("equal", (0, 0))
    assert out["stop"]["indistinguishable"] == list(dp.RECIPES)
    assert out["reading"].startswith("stop: H1 is bit-indistinguishable")


def test_the_receipt_covers_the_consumed_inputs_and_detects_a_change() -> None:
    before = dp.receipt()
    code = before["code"]
    assert "tools/parity/fit/padding_develop32.py" in code
    assert "tools/parity/fit/padding_develop_preflight.py" in code
    assert set(FROZEN_TOOLS) <= set(code)
    assert len(before["meshes"]) == 2 and len(before["kernel"]) == len(
        rr.kernel_bitmaps(wo.RESOLUTION)
    )
    assert list(before["predictions"].values()) == [scorer.FROZEN_COMPACT_SHA256]
    assert dp.changed(before, dp.receipt()) == []
    after = {**before, "meshes": {**before["meshes"], "extra.obj": "0" * 64}}
    assert dp.changed(before, after) == ["meshes:extra.obj"]
    name = next(iter(before["kernel"]))
    after = {**before, "kernel": {**before["kernel"], name: "0" * 64}}
    assert dp.changed(before, after) == [f"kernel:{name}"]


def _meshes(tmp_path: Path) -> tuple[dict[bool, Path], list[Any]]:
    shape = pf.FLAT[0]
    paths: dict[bool, Path] = {}
    placed: list[Any] = []
    for exact in (True, False):
        s = pf.twin(shape) if exact else shape
        cs = [
            wo.OffsetCopy(s, (54.0, 0.0, 0.0), role="base"),
            wo.OffsetCopy(s, (128.0, 0.0, -4.0), role="offset"),
        ]
        paths[exact] = tmp_path / pf.OBJ_NAMES[exact]
        paths[exact].write_bytes(pf.mesh(cs))
        placed = te.layout(cs)[0]
    return paths, placed


def test_h1_and_the_preflight_on_two_small_twin_meshes(tmp_path: Path) -> None:
    paths, placed = _meshes(tmp_path)
    # Where the x90 twin's rod32n origin is the normalised centre, the turn is a signed
    # permutation, exact in float32, so turning K's corners first changes no bit.
    t = pf.traced(paths[True], fit.source())
    centre = 0
    for texel, taps in t.trace.items():
        for tap, entries in taps.items():
            for e in entries:
                if e[0] != "turn":
                    continue
                _, q, p, j, tau, k = e
                if not far32.turns(t.ref, t.ring.tris[j], t.ring.tris[tau]):
                    continue
                J, T = t.ring.tris[j], t.ring.tris[tau]
                origin = pf._frame32(t.ref, J, T, J.normalised[0], T.normalised[0])[5]
                if any(c != 0 for c in origin):
                    continue
                centre += 1
                args = (t.ref, t.ring, q, p, j, tau, k, texel, tap)
                assert dev.far_distance(dev.MODEL, *args) == far32.far_distance("rod32n", *args)
    assert centre > 0
    selections: pf.Selections = {
        (exact, r): pf.selection((str(paths[exact]), r))
        for exact in (True, False)
        for r in dp.RECIPES
    }
    owners = fit.owner_copy(placed)
    mask = sorted(tefit._key(x) for x in pf.selection_mask(selections) if x in owners)
    plain = {(e, r): tefit._plain(v) for (e, r), v in selections.items()}
    found = {
        "copies": [{"lane": "centre"}, {"lane": "other"}],
        "mask": {"primary": mask},
        "texels": {
            k: {
                "copy": owners[tefit._texel(k)],
                **{tw: {r: plain[(te.EXACT[tw], r)][k] for r in dp.RECIPES} for tw in te.TWINS},
            }
            for k in plain[(True, "double")]
            if tefit._texel(k) in owners
        },
    }
    jobs = {tw: dp.h1_job(str(paths[te.EXACT[tw]])) for tw in te.TWINS}
    h1 = {tw: job[0] for tw, job in jobs.items()}
    proofs = {tw: job[1] for tw, job in jobs.items()}
    # Recording the branches changes no value.
    assert h1["x90"] == tefit._plain(dev.selection(str(paths[True])))
    out = dp.report(found, h1, proofs)
    assert out["masks"]["primary"] == len(mask) > out["masks"]["centre"] > 0
    assert out["proof"]["status"] == "branches_equal"
    for tw in te.TWINS:
        proved = out["proof"][tw]
        assert proved["branches"] == proved["equal"] > 0 and proved["calls"] >= proved["branches"]
        assert "differ" not in proved and "inconclusive" not in proved
    for name in ("primary", "centre", "slots"):
        n = out["masks"][name]
        for r in dp.RECIPES:
            b = out["bits"][name][r]
            assert sum(v for key, v in b.items() if key.startswith("pattern:")) == n
    assert isinstance(out["stop"]["stop"], bool) and isinstance(out["reading"], str)
