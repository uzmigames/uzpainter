"""Compared replays of the admitted P22-A, P22-C and P22-B mesh-map alias API-probe goldens (task
phase1.24_python-api-facade item 4.1; decisions 111 and 180; local run on the owner's machine,
decision 028).

P22-A `phase1-mesh-map-update` replaces a resource bound as the AO mesh map and as a fill's
BaseColor source (`resource.update_layer_stack_resource`). P22-C `phase1-restored-values` reads
`project.needs_saving()` after edits that leave a saved value and restore it. P22-B
`p22b-mesh-map-alias-update` binds AO and Thickness to two names of the same bytes, then replaces
the AO name by itself and by another resource: only the AO mesh map is rebound. All three run
through the facade with the recorder's own Painter-side code (`observed_replay.replay_observed`).
Every output, event list and state list of both recordings is compared field by field with the
golden read from the private store at run time (`compare_observed`). The outputs that cannot
equal Painter's are in `EXCLUDED`, each with its reason and owner; an excluded output must be
recorded and must still differ. Where no private store exists the test skips, naming why.

One comparison rule applies to a copy of the golden (`comparable`), checked to still have a reason
to exist: in a `s<n>/files` output only the suffix of the project's lock, Painter's
`.painter_lock`, is mapped to UzPainter's `.lock` (decision 319 §9a). The lock's presence, base
name and phase stay compared.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from tests.python.conftest import Run
from tests.python.observed_replay import (
    check_observed_trace,
    compare_observed,
    observed_symbols,
    replay_observed,
    save_trace,
)
from tests.python.test_pyapi_facade_tier0 import UID_VALUE
from tests.python.test_pyapi_observed_host_tier0 import PAINTER_LOCK, map_lock

# Outputs that cannot equal Painter's, by probe: output key (`<output id>` for both recordings,
# `<condition> <output id>` for one) -> reason and owner.
EXCLUDED: dict[str, dict[str, str]] = {
    "phase1-mesh-map-update": {"s12/uid": UID_VALUE},
    "p22b-mesh-map-alias-update": {},
    "phase1-restored-values": {},
}
# The probes whose saves leave a project lock in a `files` output (decision 319 §9a).
LOCKED = {"phase1-restored-values"}


def comparable(probe: str, golden: dict[str, Any]) -> dict[str, Any]:
    """A copy of the golden with the project lock's suffix mapped (decision 319 §9a), checked to
    map a lock exactly where `LOCKED` says."""
    golden = copy.deepcopy(golden)
    locks = 0
    for recording in golden["recordings"]:
        for output in recording["outputs"]:
            value = output.get("value")
            if output["output_id"].endswith("/files") and isinstance(value, list):
                locks += sum(isinstance(n, str) and n.endswith(PAINTER_LOCK) for n in value)
                output["value"] = map_lock(value)
    assert bool(locks) == (probe in LOCKED), f"{probe}: {locks} project locks in the golden"
    return golden


@pytest.mark.parametrize("probe", sorted(EXCLUDED))
def test_observed_p22ac_probe_equals_painter(facade: Run, tmp_path: Path, probe: str) -> None:
    """Item 4.1: the API-probe golden is exact apart from the named exclusions, both
    recordings."""
    replayed, golden, job = replay_observed(facade, probe, tmp_path)
    golden = comparable(probe, golden)
    differences = compare_observed(replayed, golden, job, tmp_path, EXCLUDED[probe])
    save_trace(f"facade-observed/{probe}", golden, replayed, EXCLUDED[probe], differences)
    assert replayed["cleanup_failures"] == [], replayed["cleanup_failures"]
    assert differences == [], "\n".join(differences)
    symbols = observed_symbols(replayed, golden, EXCLUDED[probe])
    check_observed_trace(f"facade-observed/{probe}", golden["golden_id"], symbols)
