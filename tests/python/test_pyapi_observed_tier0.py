"""Compared replays of five admitted observed API-probe goldens (task phase1.24_python-api-facade
item 4.1; local run on the owner's machine, decision 028).

P21-A `phase1-create-mesh-maps`, P21-B `phase1-create-default-paths`, P21-C
`phase1-texture-throttling`, P21-D `phase1-shelves` and P21-E `phase1-layer-stack-events`
(decisions 110, 198 and 205) run through the facade with the recorder's own Painter-side code
(`observed_replay.replay_observed`). Every output, event list, state list and file list of both
recordings is compared field by field with the golden read from the private store at run time
(`compare_observed`). The outputs that cannot equal Painter's are in `EXCLUDED`, each with its
kind and owner; an excluded output must be recorded and must still differ. Where no private store
exists the test skips, naming why.
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

PAINT_LAYER = (
    "refused: a paint layer is a release gap, NotYetSupported before any change "
    "(phase4.1_nodes-paint-layers); this step and its LayerStacksModelDataChanged"
)
MASK_EFFECT = (
    "refused: {} effect is a release gap, NotYetSupported before any change "
    "(phase4.1_nodes-mask-effects); this step and its LayerStacksModelDataChanged"
)
ANCHOR = (
    "refused: an anchor point effect is a release gap, NotYetSupported before any change "
    "(phase4.1_nodes-instances-anchors); this step and its LayerStacksModelDataChanged"
)


def excluded(reason: str, *ids: str) -> dict[str, str]:
    return dict.fromkeys(ids, reason)


# Outputs that cannot equal Painter's, by probe: output key (`<output id>` for both recordings,
# `<condition> <output id>` for one) -> kind, reason and owner.
EXCLUDED: dict[str, dict[str, str]] = {
    "phase1-create-mesh-maps": {},
    "phase1-create-default-paths": {
        "s3/get_default_export_path": (
            "host path, pending evidence (decision 320; phase1.24_python-api-facade item 4.1): "
            "UzPainter returns this host's Documents/UzPainter/export; Painter returns its "
            "user's Painter export folder. The excluded path gives no parity credit"
        ),
    },
    "phase1-texture-throttling": {},
    "phase1-shelves": excluded(
        "host environment, permanent (decision 006): Painter's installed and user shelves "
        "(starter assets, fonts, the user's assets folder) are Adobe content UzPainter never ships",
        "s4/all",
        "s5/application_shelf",
        "s6/user_shelf",
    ),
    "phase1-layer-stack-events": {
        **excluded(PAINT_LAYER, "s14/insert_paint", "s14/events"),
        **excluded(
            MASK_EFFECT.format("a compare-mask"), "s16/insert_compare_mask_effect", "s16/events"
        ),
        **excluded(
            MASK_EFFECT.format("a colour-selection"),
            "s17/insert_color_selection_effect",
            "s17/events",
        ),
        **excluded(ANCHOR, "s18/insert_anchor_point_effect", "s18/events"),
        "after_save_reopen identity/reopen": (
            "found_by lists the nodes of the refused steps s14, s16-s18 (their owners above)"
        ),
        "s30/set_parameters": (
            "Painter-unstable (decision 205): Painter's TypeError text is its binding's overload "
            "message with the object's address, which differs between its two recordings; the "
            "facade raises TypeError too, with its own message"
        ),
    },
}


@pytest.mark.parametrize("probe", sorted(EXCLUDED))
def test_observed_probe_equals_painter(facade: Run, tmp_path: Path, probe: str) -> None:
    """Item 4.1: the API-probe golden is exact apart from the named exclusions, both
    recordings."""
    replayed, golden, job = replay_observed(facade, probe, tmp_path)
    if probe == "phase1-create-default-paths":
        for condition in ("same_session", "after_save_reopen"):
            output = replayed[condition]["outputs"]["s3/get_default_export_path"]
            assert "raised" not in output, output
            assert isinstance(output["value"], dict), output
            assert isinstance(output["value"].get("path"), str), output
            path = Path(output["value"]["path"])
            assert path.is_absolute() and path.parts[-2:] == ("UzPainter", "export"), output
    differences = compare_observed(replayed, golden, job, tmp_path, EXCLUDED[probe])
    save_trace(f"facade-observed/{probe}", golden, replayed, EXCLUDED[probe], differences)
    assert replayed["cleanup_failures"] == [], replayed["cleanup_failures"]
    assert differences == [], "\n".join(differences)
    symbols = observed_symbols(replayed, golden, EXCLUDED[probe])
    check_observed_trace(f"facade-observed/{probe}", golden["golden_id"], symbols)
