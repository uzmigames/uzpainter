"""Scores the paired turn-exact padding probe against its four frozen recipes (item 2.7).

The frozen predictions come from `padding_turn_exact.predictions()`. The committed compact
predictions (`padding_turn_exact_predictions.json`, LF bytes) must hash to the freeze's before
the predictions are computed, and the predictions must then hash to the freeze's and equal the
compact form, or nothing is read from the store. Nothing is scored either unless each of the two
captures (`x90`, `oblique`) validates, on the exact manifest and record that `Probe` loads and
scores (`load_probe`; one read of each, after the generic `validate_record`):
- it is of its own frozen request (`identity_problems`): the request's exact bytes, the admitted
  manifest's authored part, the mesh, and the record's golden id, input hashes and
  instruction-sequence hash;
- each recording (exactly r1 same session and r2 after save and reopen) has one template capture
  of the one texture set at 512 x 512 whose user0..7 channels are RGB32F, and its exported maps
  are exactly user0..7 at steps 45 and 46 (`infinite`) and 47 and 48 (`passthrough`)
  (`padding_joint_bend_score.record_problems`);
- every export keeps the covered source bit for bit (`padding_corpus.exports`, through `Probe`);
- the four `infinite` exports are present and identical on every ring texel (`export_problems`);
- every predicted ring texel is a ring texel of both recordings.

A texel matches a recipe on a twin when its 24 recorded components equal the recipe's predicted
output bits bit for bit in all four `infinite` exports. No fraction is decoded, no threshold is
set, no subset is chosen after the capture, no texel gets a per-texel winner, no order is
searched and no rule the corpus refuted is brought back. On every texel of the frozen primary
mask (and, reported apart, of `tau_other`) and its declared strata (`padding_turn_exact.strata`):
- per recipe and twin, the matching texels, and the joint pattern (M match, X miss; x90 first);
- the observed twin difference (the recorded bits of a texel and its pair in the other twin
  differ), compared directly per recipe with its predicted twin difference (observed first).

**What it may claim.** The outcome names the recipes that match every primary texel on both
twins: one (`fits_both`), several (`not_separated`) or none (`none_fits`), which discriminates
these four controlled recipes only. `configuration` is `dependent` when some primary texel's
recorded bits differ between twins: Painter's output then depends on the fold configuration for
the same UVs, kernel values and developed geometry. That the support (taps and order) is the
same in both twins is model evidence from the frozen pipeline, never an observed Painter
internal. Stdout carries counts only. The plan stops after this one paired capture and score.

    python -m tools.parity.fit.padding_turn_exact_score
"""

from __future__ import annotations

import collections
import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.parity.fit import padding_turn_exact as fit
from tools.parity.fit.padding_corpus import Probe
from tools.parity.fit.padding_joint_bend_score import record_problems
from tools.parity.recorder.job import canonical_json
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import padding_turn_exact as te
from tools.parity.tier0_semantics.recording_requests import preserved_request_paths, request_dir

PROBES = {twin: te.GOLDENS[twin].removeprefix("export-padding-") for twin in te.TWINS}
# The freeze (`parity/reports/phase1/padding-turn-exact-freeze.md`).
FROZEN_PREDICTIONS_SHA256 = "2b6e2f25b629e9435dff9db0be2d95c2e98c580133b1bc242dca4e51be0b88e0"
FROZEN_COMPACT_SHA256 = "e1e2617eec57297ed1950915fd4295dbbaaa827ad00796642483049b249382f1"
# The frozen requests (exact bytes) and their meshes.
FROZEN_REQUEST_SHA256 = {
    "x90": "c9a659f8d9ee2566ff7c96ac166bea89888efca3caf8f81c01f022545062e3fa",
    "oblique": "17905604f89eb4ec8134bb3eb13d3a64ed240a4e1766d4dc98132a7d828be7d4",
}
FROZEN_MESH_SHA256 = {
    "x90": "b18c4f3e936f3186aff342e78491a1681b87251c11c201500997340cfe575d72",
    "oblique": "b5b079b78cf0ed6eddfb72dc8e59ddf0e9ba547aa677c80f1e9d9bc1fc0c84cf",
}
COMPACT_PATH = REPO_ROOT / "tools/parity/fit/padding_turn_exact_predictions.json"
Recorded = Callable[[int, int], list[list[int]] | None]


def compact_problems() -> list[str]:
    """Whether the committed compact predictions' exact bytes are the freeze's (checked before
    the predictions are computed)."""
    data = COMPACT_PATH.read_bytes()  # exact bytes: the authored file is LF
    if hashlib.sha256(data).hexdigest() != FROZEN_COMPACT_SHA256:
        return ["the compact predictions differ from the freeze"]
    return []


def frozen_problems(found: dict[str, Any]) -> list[str]:
    """Whether the predictions and the committed compact predictions are the freeze's."""
    problems = []
    if fit.digest(found) != FROZEN_PREDICTIONS_SHA256:
        problems.append("the predictions differ from the freeze")
    compact = compact_problems()
    if compact:
        problems += compact
    elif json.loads(COMPACT_PATH.read_bytes()) != json.loads(json.dumps(fit.compact(found))):
        problems.append("the compact predictions differ from the predictions")
    return problems


def identity_problems(
    twin: str,
    request: bytes,
    manifest: dict[str, Any],
    record: dict[str, Any],
    found: dict[str, Any],
) -> list[str]:
    """Whether the capture of `twin` is of its frozen request: the request's exact bytes hash to
    the freeze's; the admitted manifest is that request with private records added; the
    record's golden id, input hashes and instruction-sequence hash are the request's; and the
    request's mesh is the frozen mesh the predictions were made on."""
    if hashlib.sha256(request).hexdigest() != FROZEN_REQUEST_SHA256[twin]:
        return [f"{twin}: the request differs from the freeze"]
    problems = []
    frozen = json.loads(request)
    authored = {k: v for k, v in manifest.items() if k != "private_records"}
    if authored != {k: v for k, v in frozen.items() if k != "private_records"}:
        problems.append(f"{twin}: the admitted manifest differs from the frozen request")
    # Only `private_records` is added: the request's empty list, the manifest's filled one.
    if frozen.get("private_records") != [] or not manifest.get("private_records"):
        problems.append(
            f"{twin}: the admitted manifest is not the request with private records added"
        )
    meshes = [row["sha256"] for row in frozen["inputs"] if row["kind"] == "mesh"]
    if (
        meshes != [FROZEN_MESH_SHA256[twin]]
        or found.get("meshes", {}).get(twin, {}).get("mesh_sha256") != FROZEN_MESH_SHA256[twin]
    ):
        problems.append(f"{twin}: the mesh differs from the freeze")
    key = record.get("key", {})
    if (
        record.get("golden_id") != frozen["golden_id"]
        or key.get("instruction_sequence_sha256")
        != hashlib.sha256(canonical_json(frozen["instruction_sequence"])).hexdigest()
        or key.get("inputs")
        != [{"input_id": r["input_id"], "sha256": r["sha256"]} for r in frozen["inputs"]]
    ):
        problems.append(f"{twin}: the record is not of the frozen request")
    return problems


def capture_problems(
    twin: str,
    request: bytes,
    manifest: dict[str, Any],
    record: dict[str, Any],
    found: dict[str, Any],
) -> list[str]:
    """`identity_problems`, then the record's recordings, template precision and exports."""
    return identity_problems(twin, request, manifest, record, found) + [
        f"{twin}: {p}" for p in record_problems(record, te.MATERIAL)
    ]


def export_problems(twin: str, exports: int, unstable: int) -> list[str]:
    """The four `infinite` exports must be present and identical on every ring texel."""
    if exports != 4:
        return [f"{twin}: {exports} infinite exports, not 4"]
    if unstable:
        return [f"{twin}: the infinite exports differ on {unstable} ring texels"]
    return []


def request_paths(twin: str) -> list[Path]:
    """Every retained copy of the twin's request (its pending path before admission)."""
    name = te.GOLDENS[twin]
    paths = preserved_request_paths(REPO_ROOT, name) or [request_dir(REPO_ROOT) / f"{name}.json"]
    return [p for p in paths if p.is_file()]


def score(found: dict[str, Any], recorded: dict[str, Recorded]) -> dict[str, Any]:
    """Per recipe, the matching texels of each set and stratum per twin, the joint patterns and
    the twin-difference comparison (`matches`), out of the sizes (`sizes`); the outcome and the
    configuration finding on the primary mask. `recorded[twin](x, y)` gives the four `infinite`
    exports' 24 component bits of ring texel (x, y), or None when it is not a ring texel (the
    score is then refused)."""
    sets = fit.membership(found)
    rows = found["copies"]
    sizes: collections.Counter[str] = collections.Counter()
    matches: dict[str, collections.Counter[str]] = {
        r: collections.Counter() for r in found["recipes"]
    }
    missing = 0
    for key, texel in found["texels"].items():
        x, y = (int(v) for v in key.split(","))
        x90, oblique = recorded["x90"](x, y), recorded["oblique"](x, y)
        if x90 is None or oblique is None:
            missing += 1
            continue
        bits = {"x90": x90, "oblique": oblique}
        name = sets[key]
        if name not in ("primary", "tau_other"):
            sizes[name] += 1
            continue
        labels = [name, *(f"{name}:{s}" for s in fit.strata(rows[texel["copy"]]))]
        observed = bits["x90"] != bits["oblique"]
        for label in labels:
            sizes[label] += 1
            sizes[f"{label}:observed_twin_differs"] += observed
        for r in found["recipes"]:
            hit = {twin: all(v == texel[twin][r]["bits"] for v in bits[twin]) for twin in te.TWINS}
            predicted = texel["x90"][r]["bits"] != texel["oblique"][r]["bits"]
            joint = f"{'M' if hit['x90'] else 'X'}{'M' if hit['oblique'] else 'X'}"
            twins = f"{'D' if observed else 'A'}{'D' if predicted else 'A'}"
            for label in labels:
                for twin in te.TWINS:
                    matches[r][f"{label}:{twin}"] += hit[twin]
                matches[r][f"{label}:joint:{joint}"] += 1
                matches[r][f"{label}:twin:{twins}"] += 1
                matches[r][f"{label}:twin_agrees"] += observed == predicted
    if missing:
        return {"refused": f"{missing} predicted ring texels are not ring texels of a recording"}
    size = sizes["primary"]
    fitting = [r for r in found["recipes"] if matches[r]["primary:joint:MM"] == size]
    outcome = (
        f"fits_both:{fitting[0]}"
        if len(fitting) == 1
        else "not_separated:" + ",".join(fitting)
        if fitting
        else "none_fits"
    )
    return {
        "sizes": dict(sorted(sizes.items())),
        "matches": {r: dict(sorted(c.items())) for r, c in matches.items()},
        "outcome": outcome,
        "twin_difference_fits": [
            r for r in found["recipes"] if matches[r]["primary:twin_agrees"] == size
        ],
        "configuration": ("dependent" if sizes["primary:observed_twin_differs"] else "not_shown"),
        "claim": "configuration dependence only; support equality is model evidence",
    }


def load_probe(twin: str, found: dict[str, Any]) -> tuple[Probe | None, list[str]]:
    """The twin's `Probe`, validated on the exact manifest and record it loads (one read of
    each): `Probe` runs the generic `validate_record`, then `capture_problems` against every
    retained copy of the frozen request, before any export is read. None and the problems when
    the capture is refused."""
    paths = request_paths(twin)
    if not paths:
        return None, [f"{twin}: the frozen request is missing"]
    requests = [path.read_bytes() for path in paths]
    problems: list[str] = []

    def check(manifest: dict[str, Any], record: dict[str, Any]) -> list[str]:
        for request in requests:  # every retained copy of the request must be the frozen one
            problems.extend(capture_problems(twin, request, manifest, record, found))
        return problems

    try:
        probe = Probe(PROBES[twin], check)
    except (OSError, ValueError) as error:  # no store or record, the snapshot, covered source
        return None, problems or [f"{twin}: {error}"]
    return probe, export_problems(twin, len(probe.recorded), probe.unstable)


def main() -> int:
    problems = compact_problems()  # fail fast, before the predictions are computed
    if problems:
        print(json.dumps({"refused": problems}))
        return 1
    found = fit.predictions()
    problems = frozen_problems(found)
    probes: dict[str, Probe] = {}
    for twin in te.TWINS if not problems else ():
        probe, refused = load_probe(twin, found)
        problems += refused
        if probe is not None:
            probes[twin] = probe
    if problems:
        print(json.dumps({"refused": problems}))
        return 1
    print(json.dumps({twin: {"ring": len(p.points)} for twin, p in probes.items()}))

    def reader(probe: Probe) -> Recorded:
        def recorded(x: int, y: int) -> list[list[int]] | None:
            index = probe.index.get((x, y))
            if index is None:
                return None
            return [[int(b) for b in v[index].view("uint32")] for v in probe.recorded.values()]

        return recorded

    result = score(found, {twin: reader(p) for twin, p in probes.items()})
    print(json.dumps(result, sort_keys=True))
    return 1 if "refused" in result else 0


if __name__ == "__main__":
    sys.exit(main())
