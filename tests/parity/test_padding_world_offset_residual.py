"""Authored checks of the world-offset residual diagnostic (`padding_world_offset_residual`),
independent of Painter recordings."""

from __future__ import annotations

import itertools
import json
import types
from pathlib import Path

import numpy as np
import pytest

from tools.parity.fit import padding_corpus as corpus
from tools.parity.fit import padding_world_offset as fit
from tools.parity.fit import padding_world_offset_residual as res
from tools.parity.fit import padding_world_offset_score as wscore
from tools.parity.fit.plane_transform_diagnostic import load_module
from tools.parity.schemas import REPO_ROOT

REF = load_module(REPO_ROOT / "tests/export/padding_reference.py", "test_world_offset_residual_ref")
F32 = np.float32


def test_levels_are_the_reference_levels_and_round_trip() -> None:
    assert res.LEVELS == REF.LEVELS
    for level, (_, top) in enumerate(res.LEVELS):
        for u in (0, 1, top // 2, top - 1, top):
            assert res.levels_of([F32(0)] * level + [res.fraction_of(level, u)])[level] == u


def test_raw_levels_round_to_the_reference_fractions() -> None:
    rng = np.random.default_rng(7)
    for _ in range(200):
        ds = [float(d) for d in rng.uniform(0.5, 2.5, int(rng.integers(2, 5)))]
        raw = res.raw_levels(ds)
        assert res.levels_of(REF.fractions(ds)) == [
            min(max(round(v), 0), res.LEVELS[i][1]) for i, v in enumerate(raw)
        ]


def test_float32_shares_agree_with_double_shares_away_from_a_boundary() -> None:
    checked = 0
    for ds in ([1.0, 1.0], [1.0, 2.0], [1.0, 2.0, 4.0], [1.0, 1.5, 2.0, 2.5], [1.0, 1.25, 3.0]):
        if any(abs(v - round(v)) >= 0.4 for v in res.raw_levels(ds)):
            continue  # within 0.1 bin of a rounding boundary
        assert res.fractions_f32(ds) == REF.fractions(ds)
        assert res.fractions_f32(ds, gpu=True) == REF.fractions(ds)
        checked += 1
    assert checked >= 2
    assert res.fractions_f32([1.0]) == []


def test_the_tracer_patches_the_frozen_reference_once() -> None:
    m = res.traced_module()
    assert m.FAR_MODEL == "double"
    assert m._far_distance is res.traced_far
    assert m._far_plain is res.traced_plain


def test_the_tracer_records_only_outside_flipped_windows() -> None:
    ring = types.SimpleNamespace(_flip=False)
    holder = res.TRACE
    res.TRACE = {}
    try:
        assert res.traced_plain(ring, (1, 2), (3, 4), 0.5) == 0.5
        ring._flip = True
        res.traced_plain(ring, (1, 2), (3, 4), 0.25)
        assert res.TRACE == {(1, 2): {(3, 4): [("plain", 0.5)]}}
    finally:
        res.TRACE = holder


def test_decoded_levels_reproduce_their_chain() -> None:
    values = np.asarray([[0.0, 1.0, 0.25], [1.0, 0.0, 0.5], [0.5, 0.5, 1.0]], F32)
    t = types.SimpleNamespace(
        chosen={(0, 0): [(1.0, False, (0, 0)), (1.0, True, (1, 0)), (1.0, False, (2, 0))]},
        source=np.zeros((1, 3, 24), F32),
        module=REF,
    )
    for c in range(3):
        t.source[0, :, c] = values[:, c]
    levels = [700, 100]
    fr = [res.fraction_of(i, u) for i, u in enumerate(levels)]
    bits = res.chain_bits(t, (0, 0), fr)  # type: ignore[arg-type]
    found = res.decode_all(t, (0, 0), bits, [698, 102], radius=3)  # type: ignore[arg-type]
    assert levels in found
    for combo in found:
        got = res.chain_bits(t, (0, 0), [res.fraction_of(i, u) for i, u in enumerate(combo)])  # type: ignore[arg-type]
        assert got == bits
    assert list(itertools.chain(*found))


def test_the_trace_reproduces_every_chosen_far_distance_of_the_reference() -> None:
    t = res.Traced()
    double = res.frozen_model("double")
    far = [texel for texel, taps in t.chosen.items() if any(c[1] for c in taps)]
    assert len(far) > 6000
    for texel in far:
        assert res.distances(t, texel, double) == [c[0] for c in t.chosen[texel]]


def test_predictions_other_than_the_freeze_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "full.json"
    other = {"mesh_sha256": "0" * 64, "reference": {}, "models": [], "copies": []}
    path.write_text(json.dumps(other), encoding="utf-8")
    with pytest.raises(ValueError, match="differ from the freeze"):
        res.load_frozen(path)


def test_a_capture_that_does_not_validate_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wscore, "validate_capture", lambda found: ["not the frozen request"])
    with pytest.raises(ValueError, match="not the frozen request"):
        res.load_capture({})
    monkeypatch.setattr(wscore, "validate_capture", lambda found: [])
    monkeypatch.setattr(
        res,
        "Probe",
        lambda name: types.SimpleNamespace(unstable=1, recorded={i: 0 for i in range(4)}),
    )
    with pytest.raises(ValueError, match="infinite exports differ"):
        res.load_capture({})
    monkeypatch.setattr(
        res, "Probe", lambda name: types.SimpleNamespace(unstable=0, recorded={0: 0})
    )
    with pytest.raises(ValueError, match="incomplete"):
        res.load_capture({})


def test_a_trace_that_differs_from_the_freeze_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    clean = dict.fromkeys(fit.MODELS, 0)
    monkeypatch.setattr(res, "check_frozen", lambda t, found: clean)
    res.require_frozen(None, {})  # type: ignore[arg-type]
    monkeypatch.setattr(res, "check_frozen", lambda t, found: {**clean, "pos32n": 1})
    with pytest.raises(ValueError, match="pos32n"):
        res.require_frozen(None, {})  # type: ignore[arg-type]


def test_main_refuses_before_any_analysis(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    def refuse(path: Path) -> dict[str, object]:
        raise ValueError("the predictions differ from the freeze")

    def unreachable(*args: object) -> object:
        raise AssertionError("analysis ran after a refusal")

    monkeypatch.setattr(res, "load_frozen", refuse)
    monkeypatch.setattr(res, "Traced", unreachable)
    monkeypatch.setattr(res, "characterize", unreachable)
    assert res.main(["--load", str(tmp_path / "full.json")]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "refused": "the predictions differ from the freeze"
    }
    monkeypatch.setattr(res, "load_frozen", lambda path: {})
    monkeypatch.setattr(res, "load_capture", lambda found: lambda texel: [])
    monkeypatch.setattr(res, "Traced", lambda: None)

    def diverges(t: object, found: object) -> None:
        raise ValueError("the trace differs from the freeze: {'inv32n': 2}")

    monkeypatch.setattr(res, "require_frozen", diverges)
    assert res.main(["--load", str(tmp_path / "full.json")]) == 1
    assert "trace differs" in capsys.readouterr().out


def test_chain_kinds() -> None:
    assert res.chain_kind([(1.0, True, (0, 0))]) == "copy"
    assert res.chain_kind([(1.0, False, (0, 0)), (1.0, False, (1, 0))]) == "own"
    assert res.chain_kind([(1.0, True, (0, 0)), (1.0, True, (1, 0))]) == "far"
    assert res.chain_kind([(1.0, True, (0, 0)), (1.0, False, (1, 0))]) == "mixed"


def test_corpus_policies_carry_every_knob_of_a_candidate() -> None:
    base = "baseline+island+farhook+farisland"
    assert res.corpus_policies(["pos32n", "fold32n+own32mix"]) == (
        "baseline",
        base,
        f"{base}+fmpos32n",
        f"{base}+fcfold32n+own32mix",
    )
    res.register_corpus_patches()
    assert "own32mix" in corpus.PATCHES and "fcfold32n" in corpus.PATCHES
    text = corpus.reference_text(None)
    for name in [*base.split("+")[1:], "fcfold32n", "own32mix"]:
        for old, new in corpus.PATCHES[name]:
            assert text.count(old) == 1, name
            text = text.replace(old, new)
    compile(text, "patched", "exec")
