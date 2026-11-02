"""Scores the recorded joint-bend padding probe against its five frozen models (item 2.7).

The frozen predictions come from `padding_joint_bend.predictions()`; their model part (every
copy's taps and output bits per model) must hash to the freeze's SHA-256, or nothing is scored.
The recording is loaded as every kernel probe is (`padding_corpus.Probe`): the template's
RGB32F user channels (`validate_record`), every export keeping the covered source bit for bit,
and the four `infinite` exports (r1 and r2, each export twice) compared with each other. A copy
matches a model when T's 24 recorded components equal the model's prediction bit for bit in all
four. Stdout carries counts per model and stratum only.

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
from tools.parity.fit.padding_corpus import Probe

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


def main() -> int:
    found = frozen.predictions()
    text = json.dumps(model_part(found), sort_keys=True)
    if hashlib.sha256(text.encode()).hexdigest() != FROZEN_MODELS_SHA256:
        print(json.dumps({"refused": "the model predictions differ from the freeze"}))
        return 1
    probe = Probe("joint-bend")
    print(json.dumps({"ring": len(probe.points), "unstable_infinite": probe.unstable}))
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
