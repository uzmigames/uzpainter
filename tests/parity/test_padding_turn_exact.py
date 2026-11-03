"""Authored checks of the paired turn-exact padding probe, independent of Painter recordings: the
generator's exactness (OBJs and requests), the frozen hashes and masks, and the scorer's
refusals and counts."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tools.parity.envelope.registry import current_envelope
from tools.parity.fit import padding_turn_exact as fit
from tools.parity.fit import padding_turn_exact_score as scorer
from tools.parity.fit.padding_corpus import STEPS
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import padding_turn_exact as te
from tools.parity.tier0_semantics import padding_world_offset as wo
from tools.parity.tier0_semantics import recording_requests as rr
from tools.parity.tier0_semantics.__main__ import manifest_text


@pytest.mark.parametrize("twin", te.TWINS)
def test_the_committed_mesh_and_request_are_the_generators(twin: str) -> None:
    data = (REPO_ROOT / rr.REQUEST_FIXTURES[te.MESHES[twin]][1]).read_bytes()
    assert data == te.mesh(twin)
    assert hashlib.sha256(data).hexdigest() == scorer.FROZEN_MESH_SHA256[twin]
    assert rr.MESH_SETS[te.MESHES[twin]] == [wo.MATERIAL]
    golden = te.request(twin)
    assert golden.name in [g.name for g in rr.requested_goldens()]
    assert golden.inputs == [te.MESHES[twin], *rr.kernel_bitmaps(te.RESOLUTION)]
    hashes = {
        name: hashlib.sha256((REPO_ROOT / rr.fixture(name)[1]).read_bytes()).hexdigest()
        for name in golden.inputs
    }
    planned = rr.request_manifest(golden, hashes, current_envelope(REPO_ROOT))
    (path,) = scorer.request_paths(twin)
    assert path == rr.request_dir(REPO_ROOT) / f"{golden.name}.json"
    request = path.read_bytes()
    assert request == manifest_text(planned).encode("utf-8")
    assert hashlib.sha256(request).hexdigest() == scorer.FROZEN_REQUEST_SHA256[twin]


def _obj(data: bytes) -> dict[str, list[str]]:
    """An OBJ's lines by kind (`v`, `vt`, `vn`, `f`, and `other` for the rest), in order."""
    out: dict[str, list[str]] = {"v": [], "vt": [], "vn": [], "f": [], "other": []}
    for line in data.decode("ascii").splitlines():
        kind = line.split(" ", 1)[0]
        out[kind if kind in out else "other"].append(line)
    return out


def test_the_twins_differ_only_in_the_far_fold_and_pair_slot_for_slot() -> None:
    rows = fit.copies()
    assert len(rows) == 123
    assert [r["lane"] for r in rows].count("centre") == 3
    x90, oblique = _obj(te.mesh("x90")), _obj(te.mesh("oblique"))
    # The comment (line 2) is the only other line that differs.
    assert [n for n, (a, b) in enumerate(zip(x90["other"], oblique["other"], strict=True))
            if a != b] == [1]  # fmt: skip
    # Shared: every UV line in order, the position count and each face's position and UV indices.
    assert x90["vt"] == oblique["vt"]
    assert len(x90["v"]) == len(oblique["v"])
    faces = {t: [[c.split("/") for c in f.split()[1:]] for f in o["f"]] for t, o in
             (("x90", x90), ("oblique", oblique))}  # fmt: skip
    assert [[c[:2] for c in f] for f in faces["x90"]] == [
        [c[:2] for c in f] for f in faces["oblique"]
    ]
    # The writer keeps one `vn` line per distinct normal text: the x90 twin's normals are the
    # signed coordinate axes, so it has fewer, and its faces' normal indices differ.
    assert len(x90["vn"]) == 5 < len(oblique["vn"])

    def face(o: dict[str, list[str]], f: list[list[str]]) -> tuple[list[str], str]:
        return [o["v"][int(c[0]) - 1] for c in f], o["vn"][int(f[0][2]) - 1]

    # Island A (each copy's first two triangles) and the two box anchors keep their positions and
    # normals; every island B triangle moves and turns.
    shared = [n < 2 for c in te.copies(True) for n in range(len(c.tris))] + [True, True]
    assert len(shared) == len(faces["x90"])
    for keep, a, b in zip(shared, faces["x90"], faces["oblique"], strict=True):
        pa, na = face(x90, a)
        pb, nb = face(oblique, b)
        assert (pa == pb and na == nb) if keep else (pa != pb and na != nb)
    placed = {t: te.layout(te.copies(te.EXACT[t])) for t in te.TWINS}
    assert [s for _, s in placed["x90"][0]] == [s for _, s in placed["oblique"][0]]
    assert placed["x90"][1] == placed["oblique"][1]
    assert [r["x90"].removeprefix(r["shape"]) for r in rows] == [
        r["oblique"].removeprefix(r["shape"]).replace("-o", "-x90-o", 1) for r in rows
    ]


def test_the_freeze_hashes_and_masks() -> None:
    data = scorer.COMPACT_PATH.read_bytes()
    assert b"\r" not in data
    assert hashlib.sha256(data).hexdigest() == scorer.FROZEN_COMPACT_SHA256
    frozen = json.loads(data)
    assert frozen["predictions_sha256"] == scorer.FROZEN_PREDICTIONS_SHA256
    assert {t: m["mesh_sha256"] for t, m in frozen["meshes"].items()} == scorer.FROZEN_MESH_SHA256
    assert frozen["reference"] == fit.FROZEN_REFERENCE and frozen["recipes"] == list(fit.RECIPES)
    mask = frozen["mask"]
    assert len(mask["primary"]) == 1722 and len(mask["tau_other"]) == 1658
    assert mask["not_clean"] == []
    assert {t: len(v) for t, v in mask["unmatched"].items()} == {"x90": 64, "oblique": 64}
    assert not set(mask["primary"]) & set(mask["tau_other"])
    assert [r["index"] for r in frozen["copies"]] == list(range(123))


def _found() -> dict[str, Any]:
    """Two copies of one slot each: a primary texel (only pos32n predicts a twin difference) and
    a tau_other texel."""

    def texel(copy_index: int, bits: dict[str, tuple[int, int]]) -> dict[str, Any]:
        return {
            "copy": copy_index,
            **{
                twin: {r: {"bits": [bits.get(r, (0, 0))[n]], "fractions": [1]} for r in fit.RECIPES}
                for n, twin in enumerate(te.TWINS)
            },
        }

    rows = [
        {"index": i, "band": "lt8", "kind": "offset", "shape": "s", "lane": lane}
        for i, lane in enumerate(("other", "centre"))
    ]
    return {
        "recipes": list(fit.RECIPES),
        "copies": rows,
        "mask": {
            "primary": ["1,1"],
            "tau_other": ["9,1"],
            "not_clean": [],
            "unmatched": {"x90": [], "oblique": []},
        },
        "texels": {"1,1": texel(0, {"pos32n+own32": (0, 5)}), "9,1": texel(1, {})},
    }


Exports = dict[str, dict[tuple[int, int], list[list[int]]]]


def _readers(recorded: Exports) -> dict[str, scorer.Recorded]:
    def reader(twin: str) -> scorer.Recorded:
        return lambda x, y: recorded[twin].get((x, y))

    return {twin: reader(twin) for twin in te.TWINS}


def test_the_scorer_counts_both_twins_and_the_observed_twin_difference() -> None:
    found = _found()
    recorded: Exports = {
        "x90": {(1, 1): [[0]] * 4, (9, 1): [[0]] * 4},
        "oblique": {(1, 1): [[5]] * 4, (9, 1): [[0]] * 4},
    }
    result = scorer.score(found, _readers(recorded))
    assert result["sizes"]["primary"] == 1 and result["sizes"]["tau_other"] == 1
    assert result["sizes"]["primary:observed_twin_differs"] == 1
    assert result["sizes"]["primary:lane:other"] == 1 and result["sizes"]["tau_other:lane:centre"]
    pos, double = result["matches"]["pos32n+own32"], result["matches"]["double"]
    assert pos["primary:joint:MM"] == 1 and pos["primary:twin:DD"] == 1
    assert double["primary:joint:MX"] == 1 and double["primary:twin:DA"] == 1
    assert result["outcome"] == "fits_both:pos32n+own32"
    assert result["twin_difference_fits"] == ["pos32n+own32"]
    assert result["configuration"] == "dependent"
    # One of four exports differing is a miss on that twin for every recipe.
    recorded["oblique"][(1, 1)] = [[5], [5], [5], [6]]
    result = scorer.score(found, _readers(recorded))
    assert result["outcome"] == "none_fits"
    # A predicted texel missing from either recording refuses the score.
    del recorded["oblique"][(9, 1)]
    result = scorer.score(found, _readers(recorded))
    assert "refused" in result


def _capture(twin: str) -> tuple[bytes, dict[str, Any], dict[str, Any], dict[str, Any]]:
    from tools.parity.recorder.job import canonical_json

    (path,) = scorer.request_paths(twin)
    request = path.read_bytes()
    frozen = json.loads(request)
    manifest = {**frozen, "private_records": [{"record_id": "golden-record"}]}
    channels = {
        f"User{i}": {"format": "RGB32F", "bit_depth": 32, "is_floating": True} for i in range(8)
    }
    outputs: list[dict[str, Any]] = [
        {
            "kind": "template_capture",
            "values": {
                "texture_sets": {te.MATERIAL: {"resolution": [512, 512], "stacks": {"": channels}}}
            },
        }
    ]
    outputs += [
        {
            "kind": "exported_map",
            "texture_set": te.MATERIAL,
            "map": f"user{i}",
            "export_settings": {"step": step, "paddingAlgorithm": mode},
        }
        for step, mode in STEPS.items()
        for i in range(8)
    ]
    record = {
        "golden_id": frozen["golden_id"],
        "key": {
            "instruction_sequence_sha256": hashlib.sha256(
                canonical_json(frozen["instruction_sequence"])
            ).hexdigest(),
            "inputs": [
                {"input_id": r["input_id"], "sha256": r["sha256"]} for r in frozen["inputs"]
            ],
        },
        "recordings": [
            {"recording_id": rid, "condition": cond, "outputs": copy.deepcopy(outputs)}
            for rid, cond in (("r1", "same_session"), ("r2", "after_save_reopen"))
        ],
    }
    found = {"meshes": {t: {"mesh_sha256": scorer.FROZEN_MESH_SHA256[t]} for t in te.TWINS}}
    return request, manifest, record, found


@pytest.mark.parametrize("twin", te.TWINS)
def test_the_scorer_accepts_only_a_valid_capture_of_the_frozen_request(twin: str) -> None:
    request, manifest, record, found = _capture(twin)
    assert scorer.capture_problems(twin, request, manifest, record, found) == []
    # Wrong request: other bytes, or the other twin's request.
    other = next(t for t in te.TWINS if t != twin)
    assert scorer.capture_problems(twin, request + b" ", manifest, record, found)[0] == (
        f"{twin}: the request differs from the freeze"
    )
    swapped = _capture(other)
    assert scorer.identity_problems(twin, swapped[0], manifest, record, found) == [
        f"{twin}: the request differs from the freeze"
    ]
    assert scorer.identity_problems(twin, request, swapped[1], swapped[2], found) == [
        f"{twin}: the admitted manifest differs from the frozen request",
        f"{twin}: the record is not of the frozen request",
    ]
    assert scorer.identity_problems(twin, request, manifest, record, {"meshes": {}}) == [
        f"{twin}: the mesh differs from the freeze"
    ]
    # Wrong template: a user channel that is not RGB32F.
    bad = copy.deepcopy(record)
    stack = bad["recordings"][0]["outputs"][0]["values"]["texture_sets"][te.MATERIAL]["stacks"][""]
    stack["User3"]["format"] = "RGB16F"
    assert scorer.capture_problems(twin, request, manifest, bad, found) == [
        f"{twin}: r1: user3 not RGB32F"
    ]
    # Missing export.
    bad = copy.deepcopy(record)
    bad["recordings"][1]["outputs"].pop()
    assert scorer.capture_problems(twin, request, manifest, bad, found) == [
        f"{twin}: r2: export groups differ from steps 45-48 x user0..7"
    ]
    # Unstable or incomplete infinite exports.
    assert scorer.export_problems(twin, 4, 0) == []
    assert scorer.export_problems(twin, 4, 3) == [
        f"{twin}: the infinite exports differ on 3 ring texels"
    ]
    assert scorer.export_problems(twin, 3, 0) == [f"{twin}: 3 infinite exports, not 4"]


def test_the_scorer_checks_the_snapshot_probe_loads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tools.parity.fit import padding_corpus as pc

    _, manifest, good, found = _capture("x90")
    bad = copy.deepcopy(good)
    sets = bad["recordings"][0]["outputs"][0]["values"]["texture_sets"]
    sets[te.MATERIAL]["stacks"][""]["User3"]["format"] = "RGB16F"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), "utf-8")
    # The store serves the bad record, then a good one: a swap after the first read.
    served = iter([json.dumps(bad), json.dumps(good)])
    validated: list[dict[str, Any]] = []
    monkeypatch.setattr(pc, "locate", lambda: object())
    monkeypatch.setattr(pc, "manifest_path", lambda probe: path)
    monkeypatch.setattr(pc, "load_oracle", lambda store, ref: next(served))
    monkeypatch.setattr(pc, "validate_record", lambda record, manifest: validated.append(record))
    probe, problems = scorer.load_probe("x90", found)
    assert probe is None and problems == ["x90: r1: user3 not RGB32F"]
    assert validated == [bad]  # the generic check ran on the same snapshot
    assert next(served) == json.dumps(good)  # one read only: no later record replaces it


def test_the_scorer_refuses_predictions_other_than_the_freeze() -> None:
    assert scorer.compact_problems() == []
    assert fit.digest(json.loads(scorer.COMPACT_PATH.read_bytes())) != (
        scorer.FROZEN_PREDICTIONS_SHA256
    )
    found = _found()
    found.update(reference="", pairing="", meshes={})
    found["copies"] = []
    assert scorer.frozen_problems(found) == [
        "the predictions differ from the freeze",
        "the compact predictions differ from the predictions",
    ]
