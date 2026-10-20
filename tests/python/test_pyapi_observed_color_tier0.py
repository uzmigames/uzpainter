"""Compared replay of the admitted P22-B colour-management API-probe golden (task
phase1.24_python-api-facade item 4.1; decision 296; local run on the owner's machine, decision 028).

`phase1-color-srgb-value` runs through the facade with the recorder's own Painter-side code
(`observed_replay.replay_observed`): `Color.sRGB` and `Color.value` of the uniform colours of a
fill's BaseColor and Height, `Color.sRGB` assigned on each and set back with
`SourceUniformColor.set_color`, and colours built with no colour space and with GenericColorSpace
sRGB, Working and Raw. Every output, event list and state list of both recordings is compared field
by field with the golden read from the private store at run time (`compare_observed`). The outputs
that cannot equal Painter's would be in `EXCLUDED`, each with its reason and owner; an excluded
output must be recorded and must still differ. Where no private store exists the test skips, naming
why.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.python.conftest import Run
from tests.python.observed_replay import (
    check_observed_trace,
    compare_observed,
    observed_symbols,
    replay_observed,
    save_trace,
)

# Outputs that cannot equal Painter's, by probe: output key (`<output id>` for both recordings,
# `<condition> <output id>` for one) -> reason and owner.
EXCLUDED: dict[str, dict[str, str]] = {
    "phase1-color-srgb-value": {},
}


@pytest.mark.parametrize("probe", sorted(EXCLUDED))
def test_observed_color_probe_equals_painter(facade: Run, tmp_path: Path, probe: str) -> None:
    """Item 4.1: the P22-B colour-management golden is exact apart from the named exclusions, both
    recordings."""
    replayed, golden, job = replay_observed(facade, probe, tmp_path)
    differences = compare_observed(replayed, golden, job, tmp_path, EXCLUDED[probe])
    save_trace(f"facade-observed/{probe}", golden, replayed, EXCLUDED[probe], differences)
    assert replayed["cleanup_failures"] == [], replayed["cleanup_failures"]
    assert differences == [], "\n".join(differences)
    symbols = observed_symbols(replayed, golden, EXCLUDED[probe])
    check_observed_trace(f"facade-observed/{probe}", golden["golden_id"], symbols)
