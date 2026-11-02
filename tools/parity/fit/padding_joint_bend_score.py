"""Scores the recorded joint-bend padding probe against its five frozen models (item 2.7).

The frozen predictions come from `padding_joint_bend.predictions()`; their model part (every
copy's taps and output bits per model) must hash to the freeze's SHA-256, or nothing is scored.
Nothing is scored unless the capture validates (`validate_capture`):
- each recording (exactly r1 same session and r2 after save and reopen) has one template capture
  of the one texture set at 512 x 512 whose user0..7 channels are RGB32F (32-bit floating);
- its exported maps are exactly user0..7 at steps 45 and 46 (`infinite`) and 47 and 48
  (`passthrough`);
- every export keeps the covered source bit for bit (`padding_corpus.exports`, through `Probe`);
- the four `infinite` exports are identical on every ring texel.
A copy matches a model when T's 24 recorded components equal the model's prediction bit for bit.
Stdout carries counts per model and stratum only.

    python -m tools.parity.fit.padding_joint_bend_score
"""

from __future__ import annotations

import collections
import hashlib
import json
import re
import sys
from typing import Any

import numpy as np

from tools.parity.fit import padding_joint_bend as frozen
from tools.parity.fit.padding_corpus import STEPS, Probe, manifest_path
from tools.parity.store.store import load_oracle, locate
from tools.parity.tier0_semantics import padding_joint_bend as jb

# The model part of the freeze (`padding-joint-bend-freeze.md`): `model_part` of the output of
# 824d542f's helper (whose whole output hashed to 23de550c...8650), equal to today's.
FROZEN_MODELS_SHA256 = "5d8a35d285f65599e8a9bb591a619bca6f58dab3ffa63ef66b9eee4b9210bd57"


def model_part(found: dict[str, Any]) -> dict[str, Any]:
    """The freeze's canonical model predictions: per copy its name, T and each model's taps and
    bits (the 824d542f helper's output)."""
    return {
        "mesh_sha256": found["mesh_sha256"],
        "copies": [
            {
                "copy": row["copy"],
                "texel": row["texel"],
                **{
                    h: None if row[h] is None else {"taps": row[h]["taps"], "bits": row[h]["bits"]}
                    for h in frozen.HYPOTHESES
                },
            }
            for row in found["copies"]
        ],
    }


NAME = re.compile(
    r"(?P<gate>n|ge)-b(?P<bend>-?[0-9.]+)-a(?P<across>[0-9.]+)-d(?P<deficit>-?[0-9.]+)"
    r"-(?P<turn>none|r90|mirror)-s(?P<scale>[0-9.]+)-p(?P<phase>[0-9.]+)"
)


def strata(name: str, decisive: bool) -> list[str]:
    """The copy's strata: e1 kind, bend sign, deficit side, control kind, moved phase, and
    whether G is decisive in the models."""
    m = NAME.fullmatch(name)
    if m is None:
        raise ValueError(f"unexpected copy name {name}")
    out = [
        f"e1:{m['gate']}",
        f"bend:{'neg' if m['bend'].startswith('-') else 'pos'}",
        f"deficit:{'inside' if m['deficit'].startswith('-') else 'outside'}",
        f"control:{m['turn']}",
        f"decisive:{decisive}",
    ]
    if m["scale"] != "1":
        out.append("control:scaled")
    if m["phase"] != "0":
        out.append("phase:moved")
    return out


def validate_capture(material: str) -> list[str]:
    """The capture's problems (template precision, recordings, export groups); empty when
    valid."""
    store = locate()
    if store is None:
        return ["store unavailable"]
    manifest = json.loads(manifest_path("joint-bend").read_text("utf-8"))
    refs = [r for r in manifest["private_records"] if r["record_id"] == "golden-record"]
    if len(refs) != 1 or (raw := load_oracle(store, refs[0])) is None:
        return ["private record unavailable"]
    record = json.loads(raw)
    problems = []
    conditions = sorted((r["recording_id"], r["condition"]) for r in record["recordings"])
    if conditions != [("r1", "same_session"), ("r2", "after_save_reopen")]:
        problems.append(f"recordings {conditions}")
    for recording in record["recordings"]:
        rid = recording["recording_id"]
        templates = [o for o in recording["outputs"] if o["kind"] == "template_capture"]
        if len(templates) != 1:
            problems.append(f"{rid}: {len(templates)} template captures")
            continue
        sets = templates[0]["values"]["texture_sets"]
        if set(sets) != {material}:
            problems.append(f"{rid}: texture sets {sorted(sets)}")
            continue
        texture = sets[material]
        if texture["resolution"] != [512, 512] or set(texture["stacks"]) != {""}:
            problems.append(f"{rid}: resolution or stacks")
            continue
        channels = {key.lower(): value for key, value in texture["stacks"][""].items()}
        for i in range(8):
            c = channels.get(f"user{i}")
            if (
                c is None
                or c["format"] != "RGB32F"
                or c["bit_depth"] != 32
                or c["is_floating"] is not True
            ):
                problems.append(f"{rid}: user{i} not RGB32F")
        groups = collections.Counter(
            (o["export_settings"]["step"], o["export_settings"]["paddingAlgorithm"], o["map"])
            for o in recording["outputs"]
            if o["kind"] == "exported_map" and o["texture_set"] == material
        )
        expected = {(step, mode, f"user{i}") for step, mode in STEPS.items() for i in range(8)}
        if set(groups) != expected or any(n != 1 for n in groups.values()):
            problems.append(f"{rid}: export groups differ from steps 45-48 x user0..7")
    return problems


def main() -> int:
    found = frozen.predictions()
    text = json.dumps(model_part(found), sort_keys=True)
    if hashlib.sha256(text.encode()).hexdigest() != FROZEN_MODELS_SHA256:
        print(json.dumps({"refused": "the model predictions differ from the freeze"}))
        return 1
    problems = validate_capture(jb.MATERIAL)
    if problems:
        print(json.dumps({"refused": problems}))
        return 1
    probe = Probe("joint-bend")
    print(json.dumps({"ring": len(probe.points), "unstable_infinite": probe.unstable}))
    if probe.unstable or len(probe.recorded) != 4:
        print(json.dumps({"refused": "the infinite exports differ or are incomplete"}))
        return 1
    totals: dict[str, int] = collections.Counter()
    by: dict[str, dict[str, int]] = collections.defaultdict(collections.Counter)
    for row in found["copies"]:
        x, y = row["texel"]
        index = probe.index[(x, y)]
        recorded = [v[index].view(np.uint32).tolist() for v in probe.recorded.values()]
        for h in frozen.HYPOTHESES:
            bits = row[h]["bits"]
            hit = all(r == bits for r in recorded)
            key = h.removeprefix("baseline+")
            totals[key] += hit
            for s in strata(row["copy"], row["decisive"]):
                by[s][key] += hit
                by[s]["copies"] += 0 if h != "baseline" else 1
    print(json.dumps({"copies": len(found["copies"]), "matches": dict(totals)}, sort_keys=True))
    for s in sorted(by):
        print(json.dumps({"stratum": s, **by[s]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
