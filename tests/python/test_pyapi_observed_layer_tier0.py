"""Compared replays of the five admitted P22-B layer-stack API-probe goldens (task
phase1.24_python-api-facade item 4.1; decision 296; local run on the owner's machine, decision 028).

`phase1-layer-navigation`, `phase1-layer-node-kinds`, `phase1-blending-modes-layer`,
`phase1-blending-modes-mask` and `phase1-levels-params` run through the facade with the recorder's
own Painter-side code (`observed_replay.replay_observed`). Every output, event list and state list
of both recordings is compared field by field with the golden read from the private store at run
time (`compare_observed`). The outputs that cannot equal Painter's are in `EXCLUDED`, each with its
reason and owner; an excluded output must be recorded and must still differ. Where no private store
exists the test skips, naming why.

`layerstack.EffectNode` is settled by the compared `EffectNode` readbacks of
`phase1-layer-navigation` (decision 296 §3 (b)): the trace cannot attribute an `isinstance` check.
The node kinds of `phase1-layer-node-kinds` stay pending (decision 296 §3 (c)): UzPainter refuses
the calls that create them, so their outputs are excluded with the owners of those release gaps.
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


def excluded(reason: str, *ids: str) -> dict[str, str]:
    return dict.fromkeys(ids, reason)


CONTENT_FILL = (
    "refused: a fill effect in a content stack is a release gap, NotYetSupported before any change "
    "(phase3.2_proc-filter-families, decision 081); step 19 and every output on its node"
)
DEFAULT_LAYER = (
    "Painter's default paint layer 'Layer 1', which UzPainter does not create yet "
    "(phase4.1_nodes-paint-layers item 2.8, decision 106): this output names it"
)
TRIPLANAR = (
    "refused: the Triplanar projection is a release gap, NotYetSupported before any change "
    "(phase3.4_smart-projections); the symmetry of a 3D projection follows it"
)
MASK_LEVELS = (
    "refused: a levels effect in a mask stack is a release gap, NotYetSupported before any change "
    "(phase4.2_remaining-nodes, decision 081); step 9 and every output on its node"
)
PAINT_EFFECT = (
    "refused: a paint effect is a release gap, NotYetSupported before any change "
    "(phase4.1_nodes-paint-layers; decision 296 §3 (c)); step 5 and every output on its node"
)
PROCEDURAL_EFFECT = (
    "refused: resource.search answers no Painter name and filter and generator effects are release "
    "gaps (decisions 113, 324; phase3.3_procedural-families; decision 296 §3 (c)); "
    "{} and every output on its node"
)
INSTANCE = (
    "refused: an instance layer is a release gap, NotYetSupported before any change "
    "(phase4.1_nodes-instances-anchors; decision 296 §3 (c)); step 17, every output on its node "
    "and the instances of its source"
)

# Outputs that cannot equal Painter's, by probe: output key (`<output id>` for both recordings,
# `<condition> <output id>` for one) -> reason and owner.
EXCLUDED: dict[str, dict[str, str]] = {
    "phase1-blending-modes-layer": {},
    "phase1-blending-modes-mask": {},
    "phase1-layer-navigation": {
        **excluded(
            CONTENT_FILL,
            "identity/s19",
            "same_session s19/insert_fill",
            "same_session s20/set_name",
            "same_session s21/active_channels",
            "same_session s22/set_source",
            "s29/get_parent",
            "s36/get_next_sibling",
            "s42/get_previous_sibling",
            "s43/get_previous_sibling",
            "s53/EffectNode",
            "s64/is_symmetry_enabled",
            "s65/set_projection_mode",
            "s66/set_symmetry_enabled",
            "s67/is_symmetry_enabled",
            "s68/set_symmetry_enabled",
            "s69/is_symmetry_enabled",
            "s74/get_material_source",
            "s76/reset_source",
            "s77/get_source",
            "s91/set_selected_nodes",
            "s92/get_selected_nodes",
            "after_save_reopen identity/reopen",
            "defaults/s19",
        ),
        **excluded(DEFAULT_LAYER, "s30/get_next_sibling", "same_session s88/get_selected_nodes"),
        **excluded(
            TRIPLANAR,
            "s61/set_projection_mode",
            "s62/set_symmetry_enabled",
            "s63/is_symmetry_enabled",
            "after_save_reopen s60/is_symmetry_enabled",
        ),
    },
    "phase1-layer-node-kinds": {
        **excluded(
            PAINT_EFFECT,
            "identity/s5",
            "same_session s5/insert_paint",
            "s9/get_type",
            "s13/EffectNode",
            "defaults/s5",
        ),
        **excluded(
            PROCEDURAL_EFFECT.format("step 6 (Blur filter)"),
            "identity/s6",
            "same_session s6/insert_filter_effect",
            "s10/get_type",
            "s14/EffectNode",
            "defaults/s6",
        ),
        "same_session s8/insert_generator_effect": PROCEDURAL_EFFECT.format(
            "step 8 (Painter's own search finds no generator: its ValueError)"
        ),
        **excluded(
            INSTANCE,
            "s17/instantiate",
            "s18/get_type",
            "s19/instance_source",
            "s20/instances",
            "after_save_reopen s16/instances",
            "s21/set_selection_type",
            "s22/get_selection_type",
            "s23/set_selection_type",
            "s24/get_selection_type",
        ),
        "after_save_reopen identity/reopen": (
            "found_by lists the nodes of the refused steps 5, 6 and 17 (their owners above)"
        ),
    },
    "phase1-levels-params": excluded(
        MASK_LEVELS,
        "identity/s9",
        "same_session s9/insert_levels_effect",
        "same_session s10/set_name",
        "s23/affected_channel",
        "s24/get_parameters",
        "s25/LevelsParamsMono",
        "s26/get_parameters",
        "s27/LevelsParamsRGB",
        "s28/get_parameters",
        "after_save_reopen identity/reopen",
        "defaults/s9",
    ),
}


@pytest.mark.parametrize("probe", sorted(EXCLUDED))
def test_observed_layer_probe_equals_painter(facade: Run, tmp_path: Path, probe: str) -> None:
    """Item 4.1: the P22-B layer-stack golden is exact apart from the named exclusions, both
    recordings."""
    replayed, golden, job = replay_observed(facade, probe, tmp_path)
    differences = compare_observed(replayed, golden, job, tmp_path, EXCLUDED[probe])
    save_trace(f"facade-observed/{probe}", golden, replayed, EXCLUDED[probe], differences)
    assert replayed["cleanup_failures"] == [], replayed["cleanup_failures"]
    assert differences == [], "\n".join(differences)
    symbols = observed_symbols(replayed, golden, EXCLUDED[probe])
    check_observed_trace(f"facade-observed/{probe}", golden["golden_id"], symbols)
