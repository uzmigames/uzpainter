"""Scores the recorded world-offset padding probe against its eight frozen models (item 2.7).

The frozen predictions come from `padding_world_offset.predictions()`. Their SHA-256 must be the
freeze's, and the committed compact predictions (`padding_world_offset_predictions.json`, LF
bytes) must hash to the freeze's and equal `compact()` of them, or nothing is scored. Nothing is
scored either unless the capture validates:
- each recording (exactly r1 same session and r2 after save and reopen) has one template capture
  of the one texture set at 512 x 512 whose user0..7 channels are RGB32F;
- its exported maps are exactly user0..7 at steps 45 and 46 (`infinite`) and 47 and 48
  (`passthrough`);
- every export keeps the covered source bit for bit (`padding_corpus.exports`, through `Probe`);
- the four `infinite` exports are identical on every ring texel;
- every predicted ring texel is a ring texel of the recording;
- the capture is of the frozen request (`identity_problems`): the request's exact bytes, the
  admitted manifest's authored part, the mesh, and the record's golden id, input hashes and
  instruction-sequence hash.

A texel matches a model when its 24 recorded components equal the model's predicted output bits
bit for bit in all four `infinite` exports. No fraction is decoded and no threshold is set. The
counts are reported separately for:
- the scored set (`padding_world_offset.stable`);
- the excluded set (every other ring texel of a copy);
- the whole ring of the copies;
- the discriminating texels, in all and split into scored and excluded ones;
- the translation mask's pairs (`padding_world_offset.translation_pairs`).
The verdict follows the freeze: exactly one model matching every scored texel is a candidate,
several are not separated, none means that no model fits. Stdout carries counts only.

    python -m tools.parity.fit.padding_world_offset_score
"""

from __future__ import annotations

import collections
import hashlib
import json
import sys
from collections.abc import Callable
from typing import Any

from tools.parity.fit import padding_world_offset as fit
from tools.parity.fit.padding_corpus import Probe, manifest_path
from tools.parity.fit.padding_joint_bend_score import record_problems
from tools.parity.recorder.job import canonical_json
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import load_oracle, locate
from tools.parity.tier0_semantics import padding_world_offset as wo
from tools.parity.tier0_semantics.recording_requests import preserved_request_paths

PROBE = "world-offset"
# The freeze (`parity/reports/phase1/padding-world-offset-freeze.md`).
FROZEN_PREDICTIONS_SHA256 = "cc51a73f414cc060b1ae3c0e1cb10347da36403bbe8f0308d9b360d56961cd58"
FROZEN_COMPACT_SHA256 = "a2d9b4730a8c69e204c9b7b104d9bddaac67b2961d0afa8187fe27112b938f42"
# The frozen request (exact bytes) and its mesh.
FROZEN_REQUEST_SHA256 = "4e2c2646f79cc51135791d4c6786dde8440a5666b183b68a3a7a6c364f5e3c3f"
FROZEN_MESH_SHA256 = "2c8eb824a50d6af3a0ed73f256327dc670bf3adfdc08cbeff6c8d02d826ab429"
GOLDEN = "export-padding-world-offset"
COMPACT_PATH = REPO_ROOT / "tools/parity/fit/padding_world_offset_predictions.json"
Recorded = Callable[[int, int], list[list[int]] | None]


def band(row: dict[str, Any]) -> str:
    """The freeze table's offset band of a copy (`padding_world_offset.table`)."""
    x, y, z = row["offset"]
    reach = max(abs(x), abs(y), abs(z) if abs(z) > 10 else 0.0)
    return "lt8" if reach < 8 else "8-63" if reach < 64 else "ge64"


def frozen_problems(found: dict[str, Any]) -> list[str]:
    """Whether the predictions and the committed compact predictions are the freeze's."""
    problems = []
    if fit.digest(found) != FROZEN_PREDICTIONS_SHA256:
        problems.append("the predictions differ from the freeze")
    data = COMPACT_PATH.read_bytes()  # exact bytes: the authored file is LF
    if hashlib.sha256(data).hexdigest() != FROZEN_COMPACT_SHA256:
        problems.append("the compact predictions differ from the freeze")
    elif json.loads(data) != json.loads(json.dumps(fit.compact(found))):
        problems.append("the compact predictions differ from the predictions")
    return problems


def identity_problems(
    request: bytes, manifest: dict[str, Any], record: dict[str, Any], found: dict[str, Any]
) -> list[str]:
    """Whether the capture is of the frozen request: the request's exact bytes hash to the
    freeze's; the admitted manifest is that request with private records added (inputs, mesh,
    instruction sequence, applied settings, identity fields); the record's golden id, input
    hashes and instruction-sequence hash are the request's; and the request's mesh is the
    frozen mesh the predictions were made on."""
    problems = []
    if hashlib.sha256(request).hexdigest() != FROZEN_REQUEST_SHA256:
        return ["the request differs from the freeze"]
    frozen = json.loads(request)
    authored = {k: v for k, v in manifest.items() if k != "private_records"}
    if authored != {k: v for k, v in frozen.items() if k != "private_records"}:
        problems.append("the admitted manifest differs from the frozen request")
    # Only `private_records` is added: the request's empty list, the manifest's filled one.
    if frozen.get("private_records") != [] or not manifest.get("private_records"):
        problems.append("the admitted manifest is not the request with private records added")
    meshes = [row for row in frozen["inputs"] if row["kind"] == "mesh"]
    if [row["sha256"] for row in meshes] != [FROZEN_MESH_SHA256] or found.get(
        "mesh_sha256"
    ) != FROZEN_MESH_SHA256:
        problems.append("the mesh differs from the freeze")
    key = record.get("key", {})
    if (
        record.get("golden_id") != frozen["golden_id"]
        or key.get("instruction_sequence_sha256")
        != hashlib.sha256(canonical_json(frozen["instruction_sequence"])).hexdigest()
        or key.get("inputs")
        != [{"input_id": r["input_id"], "sha256": r["sha256"]} for r in frozen["inputs"]]
    ):
        problems.append("the record is not of the frozen request")
    return problems


def score(found: dict[str, Any], recorded: Recorded) -> dict[str, Any]:
    """Per model, the matching texels of each set (`matches`) out of its size (`sizes`), the
    scored set's matches by role, band and shape, and the verdict. `recorded(x, y)` gives the
    four `infinite` exports' 24 component bits of ring texel (x, y), or None when it is not a
    ring texel (the score is then refused)."""
    sizes: collections.Counter[str] = collections.Counter()
    matches: dict[str, collections.Counter[str]] = {m: collections.Counter() for m in fit.MODELS}
    hit: dict[tuple[str, str], dict[str, bool]] = {}
    missing = 0
    for row in found["copies"]:
        column, line = row["slot"]
        for rel, texel in row["texels"].items():
            dx, dy = (int(v) for v in rel.split(","))
            bits = recorded(column + dx, line + dy)
            if bits is None:
                missing += 1
                continue
            scored = fit.stable(row, texel)
            sets = ["ring", "scored" if scored else "excluded"]
            if len({tuple(texel[m]["bits"]) for m in fit.MODELS}) > 1:
                sets += ["discriminating", f"{sets[1]}_discriminating"]
            if scored:
                sets += [
                    f"scored:role:{fit.kind(row)}",
                    f"scored:band:{band(row)}",
                    f"scored:shape:{row['shape']}",
                ]
            for s in sets:
                sizes[s] += 1
            hit[(row["copy"], rel)] = {}
            for m in fit.MODELS:
                ok = all(r == texel[m]["bits"] for r in bits)
                hit[(row["copy"], rel)][m] = ok
                for s in sets:
                    matches[m][s] += ok
    if missing:
        return {"refused": f"{missing} predicted ring texels are not ring texels of the recording"}
    base = {row["shape"]: row for row in found["copies"] if row["role"] == "base"}
    for row in found["copies"]:
        if row["role"] not in ("offset", "yz", "dup"):
            continue
        origin = base[row["shape"]]
        for rel, texel in row["texels"].items():
            same = origin["texels"].get(rel)
            if same is None or not fit.stable(row, texel) or not fit.stable(origin, same):
                continue
            if fit.signature(row, texel, "double")[0] != fit.signature(origin, same, "double")[0]:
                continue
            sizes["mask_pairs"] += 1
            for m in fit.MODELS:
                matches[m]["mask_pairs"] += (
                    hit[(row["copy"], rel)][m] and hit[(origin["copy"], rel)][m]
                )
    fitting = [m for m in fit.MODELS if matches[m]["scored"] == sizes["scored"]]
    verdict = (
        f"candidate:{fitting[0]}"
        if len(fitting) == 1
        else "not_separated:" + ",".join(fitting)
        if fitting
        else "none_fits"
    )
    return {
        "sizes": dict(sorted(sizes.items())),
        "matches": {m: dict(sorted(c.items())) for m, c in matches.items()},
        "verdict": verdict,
    }


def validate_capture(found: dict[str, Any]) -> list[str]:
    store = locate()
    if store is None:
        return ["store unavailable"]
    manifest = json.loads(manifest_path(PROBE).read_text("utf-8"))
    refs = [r for r in manifest["private_records"] if r["record_id"] == "golden-record"]
    if len(refs) != 1 or (raw := load_oracle(store, refs[0])) is None:
        return ["private record unavailable"]
    record = json.loads(raw)
    paths = [p for p in preserved_request_paths(REPO_ROOT, GOLDEN) if p.is_file()]
    if not paths:
        return ["the frozen request is missing"]
    problems = []
    for path in paths:  # every retained copy of the request must be the frozen one
        problems += identity_problems(path.read_bytes(), manifest, record, found)
    return problems + record_problems(record, wo.MATERIAL)


def main() -> int:
    found = fit.predictions()
    problems = frozen_problems(found)
    if not problems:
        problems = validate_capture(found)
    if problems:
        print(json.dumps({"refused": problems}))
        return 1
    probe = Probe(PROBE)
    print(json.dumps({"ring": len(probe.points), "unstable_infinite": probe.unstable}))
    if probe.unstable != 0 or len(probe.recorded) != 4:
        print(json.dumps({"refused": "the infinite exports differ or are incomplete"}))
        return 1

    def recorded(x: int, y: int) -> list[list[int]] | None:
        index = probe.index.get((x, y))
        if index is None:
            return None
        return [[int(b) for b in v[index].view("uint32")] for v in probe.recorded.values()]

    result = score(found, recorded)
    print(json.dumps(result, sort_keys=True))
    return 1 if "refused" in result else 0


if __name__ == "__main__":
    sys.exit(main())
