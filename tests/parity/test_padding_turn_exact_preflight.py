"""Authored checks of the turn-exact padding preflight (`padding_turn_exact_preflight`),
independent of Painter recordings: the twins' geometry, the staged recipes on an exact sentinel,
the stage, coverage and verdict rules, the refusal to overwrite, and one small end-to-end run of
both twin meshes through the frozen reference and every recipe's complete selection."""

from __future__ import annotations

import types
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tools.parity.fit import padding_far32 as far32
from tools.parity.fit import padding_turn_exact_preflight as pf
from tools.parity.fit import padding_world_offset as fit
from tools.parity.tier0_semantics import padding_world_offset as wo

F32 = np.float32


def _squared_lengths(copy: wo.OffsetCopy) -> list[list[Fraction]]:
    out = []
    for ps, _ in copy.tris:
        q = [tuple(Fraction(c) for c in p) for p in ps]
        out.append(
            [sum(((a - b) ** 2 for a, b in zip(q[i], q[(i + 1) % 3], strict=True)), Fraction(0))
             for i in range(3)]
        )  # fmt: skip
    return out


def test_twins_keep_the_oblique_shapes_intrinsic_geometry() -> None:
    assert [s.name for s in pf.FLAT] == ["f37v", "f23v", "f53v"]
    for shape in pf.FLAT:
        twin = pf.twin(shape)
        assert twin.fold == (0, shape.fold[2], shape.fold[2])
        assert (twin.sign, twin.bend, twin.shift, twin.stretch) == (
            shape.sign,
            None,
            shape.shift,
            shape.stretch,
        )
        assert wo._band_depths(twin) == [(d, twin.fold) for d, _ in wo._band_depths(shape)]
        a, b = wo.OffsetCopy(twin, (40.0, 0.0, 0.0)), wo.OffsetCopy(shape, (40.0, 0.0, 0.0))
        assert [uv for _, uv in a.tris] == [uv for _, uv in b.tris]
        assert a.size == b.size
        # Every triangle's 3D edge lengths: the developed geometry is the oblique shape's.
        assert _squared_lengths(a) == _squared_lengths(b)


def test_oblique_copies_are_the_world_offset_flat_copies() -> None:
    def key(c: wo.OffsetCopy) -> tuple[Any, ...]:
        return (c.name, c.offset, c.turn, c.scale, c.role)

    mine = [key(c) for c in pf.copies(False)]
    assert mine == [key(c) for c in wo.copies() if c.shape in pf.FLAT]
    assert len(mine) == 123


def test_the_twin_meshes_share_slots_and_are_exact() -> None:
    exact, oblique = pf.copies(True), pf.copies(False)
    assert [s for _, s in pf.layout(exact)[0]] == [s for _, s in pf.layout(oblique)[0]]
    assert pf.layout(exact)[1] == pf.layout(oblique)[1]
    for found in (exact, oblique):
        faces = [line for line in pf.mesh(found).splitlines() if line.startswith(b"f ")]
        assert len(faces) == sum(len(c.tris) for c in found) + 2  # and the two box anchors


def _sentinel() -> tuple[dict[str, Any], Any, tuple[Any, ...]]:
    """Codex root's control: J's plane x = 0 and tau's y = 0 through the normalised origin, unit
    normals +ex and +ey, K coplanar with J, P = (0, 1/8, -1/4), q = (1/4, 0, 1/4); box scale 1."""
    p, q = (0.0, 0.125, -0.25), (0.25, 0.0, 0.25)

    def tri(normal: tuple[int, int, int], corner: tuple[float, float, float]) -> Any:
        return types.SimpleNamespace(
            normal=[F32(c) for c in normal],
            normalised=np.zeros((3, 3), F32),
            p=[(0.0, 0.0, 0.0), (0.0, 0.0, 1.0), corner],
            uv=np.zeros((3, 2), F32),
        )

    J, T = tri((1, 0, 0), (0.0, 1.0, 0.0)), tri((0, 1, 0), (1.0, 0.0, 0.0))
    K = tri((1, 0, 0), (0.0, 1.0, 0.0))
    ref = dict(fit.module("double").__dict__)

    def position32(uv: Any, normalised: Any, w: int, h: int, x: int, y: int, **_: Any) -> Any:
        return [F32(c) for c in (q if normalised is T.normalised else p)]

    ref["position32"] = position32
    ring = types.SimpleNamespace(
        tris=[J, T, K],
        width=512,
        height=512,
        box=(np.full(3, -1.0, F32), np.full(3, 1.0, F32)),
    )
    return ref, ring, ("turn", q, p, 0, 1, 2)


def test_the_exact_sentinel_is_exact_and_equal_at_every_stage() -> None:
    ref, ring, entry = _sentinel()
    assert far32.turns(ref, ring.tris[0], ring.tris[1])
    assert far32._scale(ref, ring) == 1.0
    keys = {}
    for recipe in pf.RECIPES:
        s = pf.staged(recipe, ref, ring, entry, (0, 0), (1, 0))
        assert s["distance"] == 0.625  # through the GPU square root for rod32n and inv32n
        k = pf.stage_keys(s)
        assert k["turn_exact"] and k["difference_exact"] and k["norm_exact"]
        assert k["normals_exact"] and k["trig_exact"] and k["rotation"] and k["origin_on_line"]
        assert k["origin"] == (0, 0, 0)
        keys[recipe] = k
        if recipe == "inv32n+own32":
            assert s["turned"] == (0, Fraction(-1, 4), Fraction(1, 4))
            assert s["difference"] == (0, Fraction(-3, 8), Fraction(1, 2))
        else:
            assert s["turned"] == (Fraction(-1, 8), 0, Fraction(-1, 4))
            assert s["difference"] == (Fraction(3, 8), 0, Fraction(1, 2))
    for a, b in pf.PAIRS:
        assert all(pf.stage_agree(st, keys[a], keys[b]) == "agree" for st in pf.STAGES[:5])


def test_an_inverse_turn_agrees_only_when_proved() -> None:
    ref, ring, entry = _sentinel()
    rod = pf.stage_keys(pf.staged("rod32n+own32", ref, ring, entry, (0, 0), (1, 0)))
    inv = pf.stage_keys(pf.staged("inv32n+own32", ref, ring, entry, (0, 0), (1, 0)))
    assert pf.stage_agree("turned", rod, inv) == "agree"
    assert pf.stage_agree("turned", rod, {**inv, "rotation": False}) == "unproved"
    assert pf.stage_agree("turned", rod, {**inv, "axis": rod["axis"]}) == "unproved"
    assert pf.stage_agree("turned", rod, {**inv, "turn_exact": False}) == "unproved"
    assert pf.stage_agree("turned", {**rod, "turn_exact": False}, inv) == "unproved"
    assert pf.stage_agree("turned", rod, {**inv, "frame": ()}) == "unproved"
    assert pf.stage_agree("turned", rod, {**rod, "turned": (0, 0, 0)}) == "differ"
    assert pf.stage_agree("norm", rod, {**inv, "norm": Fraction(1)}) == "differ"


def _tap(gates: tuple[str, ...], winner: int | None, ties: int = 1) -> dict[str, Any]:
    return {
        "gates": gates,
        "common": winner,
        "kind": "none" if winner is None else gates[winner],
        "ties": {r: tuple(range(ties)) for r in pf.RECIPES},
    }


def test_tap_status_stratifies_gates_branches_and_ties() -> None:
    turn = _tap(("turn", "turn"), 0)
    assert pf.tap_status(turn, turn) == "turn"
    assert pf.tap_status(turn, _tap(("turn", "flat"), 0)) == "gates_differ"
    assert pf.tap_status(turn, _tap(("turn", "turn"), None)) == "branch_within"
    assert pf.tap_status(turn, _tap(("turn", "turn"), 0, ties=2)) == "tie"
    assert pf.tap_status(turn, _tap(("turn", "turn"), 1)) == "branch_twins"
    assert pf.tap_status(_tap(("plain",), 0), _tap(("plain",), 0)) == "plain"


def _inv(twins: dict[str, int]) -> dict[str, Any]:
    return {"box_equal": True, "coverage": {"turn": 4}, "twins": twins}


def test_preconditions_need_every_own_stratum_and_never_pass_vacuously() -> None:
    good = {
        "developed_compared": 4,
        "developed_equal": 4,
        "own_same_tau:chains": 2,
        "own_same_tau:equal": 2,
        "own_other_tau:chains": 1,
        "own_other_tau:equal": 1,
    }
    universe = [(0, 0), (1, 0)]
    assert all(pf.preconditions(_inv(good), universe, 0).values())
    assert not pf.preconditions(_inv({**good, "own_other_tau:equal": 0}), universe, 0)["own"]
    vacuous = {"developed_compared": 4, "developed_equal": 4}
    assert not pf.preconditions(_inv(vacuous), universe, 0)["own"]
    assert not pf.preconditions(_inv({}), universe, 0)["developed"]
    assert not pf.preconditions(_inv(good), universe, 1)["support"]
    assert not pf.preconditions(_inv(good), universe, None)["support"]
    empty = pf.preconditions(_inv(good), [], 0)
    assert not empty["support"] and not empty["gates_and_branch"]
    mixed_coverage = {**_inv(good), "coverage": {"turn": 3, "tie": 1}}
    assert not pf.preconditions(mixed_coverage, universe, 0)["gates_and_branch"]


def _table(counts: dict[str, int]) -> dict[str, Any]:
    return {"exact": {"stages": {s: dict(counts) for s in pf.STAGES}}}


def test_verdict_tells_mixed_unknown_and_isolated_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    disc = {"pairs": {pf._pair(a, b): {"clean:exact": 1} for a, b in pf.PAIRS}}
    ok = dict.fromkeys(("box", "support", "gates_and_branch", "developed", "own"), True)
    # The candidates' downstream arithmetic differs: never isolated.
    assert pf.verdict(_table({}), disc, ok)["verdict"] == "mixed"
    monkeypatch.setattr(pf, "DOWNSTREAM", dict.fromkeys(pf.CANDIDATES, ("same", "same")))
    found = pf.verdict(_table({}), disc, ok)
    assert found["verdict"] == "turn_isolated" and found["discriminates"]
    assert pf.verdict(_table({}), disc, {**ok, "own": False})["verdict"] == "unknown"
    unproved = {f"{pf._pair(a, b)}:unproved": 1 for a, b in pf.PAIRS}
    assert pf.verdict(_table(unproved), disc, ok)["verdict"] == "unknown"
    differ = {f"{pf._pair(*pf.PAIRS[0])}:differ": 1}
    assert pf.verdict(_table(differ), disc, ok)["verdict"] == "mixed"


def test_meshes_are_never_written_over_an_existing_file(tmp_path: Path) -> None:
    existing = tmp_path / pf.OBJ_NAMES[False]
    existing.write_bytes(b"kept")
    with pytest.raises(FileExistsError):
        pf.write_meshes(tmp_path, {True: b"exact", False: b"oblique"})
    assert existing.read_bytes() == b"kept"
    assert not (tmp_path / pf.OBJ_NAMES[True]).exists()
    with pytest.raises(FileNotFoundError):
        pf.write_meshes(tmp_path / "missing", {True: b"exact", False: b"oblique"})
    assert not (tmp_path / "missing").exists()


def test_two_small_twin_meshes_through_every_recipe(tmp_path: Path) -> None:
    shape = pf.FLAT[0]
    found: dict[bool, dict[str, Any]] = {}
    selections: pf.Selections = {}
    for exact in (True, False):
        s = pf.twin(shape) if exact else shape
        cs = [
            wo.OffsetCopy(s, (54.0, 0.0, 0.0), role="base"),
            wo.OffsetCopy(s, (128.0, 0.0, -4.0), role="offset"),
        ]
        path = tmp_path / pf.OBJ_NAMES[exact]
        path.write_bytes(pf.mesh(cs))
        found[exact] = pf.analyse(path)
        for recipe in pf.RECIPES:
            selections[(exact, recipe)] = pf.selection((str(path), recipe))
    out = pf.report(found[True], found[False], selections)
    assert out["matched"] > 0
    assert (
        out["excluded"]["tau_other"]
        == out["matched"] - out["excluded"]["not_clean"] - (out["universes"]["tau_same"]["texels"])
    )
    for name in pf.UNIVERSES:
        assert out["universes"][name]["selection_inconsistent"] == 0
        assert out["universes"][name]["verdict"]["verdict"] in ("mixed", "unknown")
    assert out["universes"]["tau_same"]["verdict"]["preconditions"]["own"]
    u = out["universes"]["matched"]
    inv = u["invariants"]
    assert inv["box_equal"]
    exact = inv["exact"]
    n = exact["turned_entries"]
    assert n > 0
    for r in pf.CANDIDATES:
        for flag in ("normals_exact", "trig_exact", "rotation", "origin_on_line", "axial_kept"):
            assert exact[f"{flag}:{r}"] == n
    assert inv["oblique"]["trig_exact:rod32n+own32"] == 0
    # The copy at x 54 has its Cramer origin at the normalised centre: rod32n and inv32n agree
    # there at every entry stage (the turn is a signed permutation).
    assert exact["origin_zero"] > 0
    assert exact["origin_zero:all_stages:rod32n|inv32n"] == exact["origin_zero"]
    twins = inv["twins"]
    assert twins["developed_equal"] == twins["developed_compared"] > 0
    assert twins["own_same_tau:equal"] == twins["own_same_tau:chains"]
    assert u["stages"]["exact"]["equivalent"]["inputs"]
    assert u["stages"]["exact"]["equivalent"]["frame"]
