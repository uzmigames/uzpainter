"""SourceSubstance presets, image inputs and multiple outputs (decision 412).

`phase3.2_source-substance-presets-inputs` owns `apply_preset`, the image-input
`get_source`/`set_source`/`reset_source`/`remove_source`, `output_mapping` and `mask_output`
(decision 393). Every earlier probe ran on a source with zero presets, zero image inputs and one
output, so this probe runs on a starter Substance material that has all three. The resource is
named by its exact versioned URL, found by the decision-412 survey
(`tools/parity/recorder/substance_survey.py`) in the same Painter session as the recording.

Nothing about the asset is authored beyond that identity: the preset, image input and outputs
are chosen in Painter by their index in the lists Painter returns, and the only authored values
are the fixture bitmap, one uniform colour and a preset name the asset does not have. Both
recordings run the probe steps: r1 in the same session, r2 after save and reopen.
"""

from __future__ import annotations

from typing import Any

from tools.parity.recorder import vocabulary as ps
from tools.parity.tier0_semantics.corpus import Golden, manifest, start
from tools.parity.tier0_semantics.source_substance_control import PLANE_SHA256, _pin

NAME = "source-substance-presets-inputs"
ANCHOR_NAME = "source-substance-input-anchor"
PREFIX = "substance_painter.source.SourceSubstance."
SET_MATERIAL_SOURCE = "substance_painter.layerstack.FillLayerNode.set_material_source"
INSERT_PAINT = "substance_painter.layerstack.insert_paint"
INSERT_ANCHOR = "substance_painter.layerstack.insert_anchor_point_effect"
GREY_A_SHA256 = "7661c90407bdedd40c6784206507fb58d39ec690996cb9d28bd18c9fed820902"
# The survey's choice (decision 412): the first starter material, in URL order, with presets,
# image inputs and several outputs. Resource identity only; no parameter, preset, input or output
# name is authored.
RESOURCE_URL = (
    "resource://starter_assets/inflate_shrinkwrap/inflate_shrinkwrap"
    "?version=a0b1718de23d379fb35250414e364bb8f8fbf50c.sbsar"
)
# Read once on the fresh source, in both contexts where they are defined.
GETTERS = (
    "get_parameters",
    "get_properties",
    "get_preset_list",
    "image_inputs",
    "image_outputs",
    "resource_id",
    "output_mapping",
    "mask_output",
    "active_output",
    "resolution",
)
# Read after every edit.
AFTER = ("get_parameters", "output_mapping", "mask_output")
# A name no starter asset has (python-doc: a preset that is not found does nothing).
MISSING_PRESET = "uzp-no-such-preset"
# An authored uniform colour for the image input (python-doc: a Color is a valid source).
INPUT_COLOR = [0.25, 0.5, 0.75]


def edits() -> list[tuple[str, dict[str, Any]]]:
    """The probe edits, in order, each followed by the `AFTER` readbacks and the input's source."""
    first_input = {"input_index": 0}
    first_output = {"output_index": 0}
    return [
        ("apply_preset", {"preset_index": 0}),
        ("apply_preset", {"preset_name": MISSING_PRESET}),
        ("set_source", {**first_input, "color": INPUT_COLOR, "color_space": "Working"}),
        ("set_source", {**first_input, "resource_step": 4}),
        ("reset_source", first_input),
        ("set_source", {**first_input, "resource_step": 4}),
        ("remove_source", first_input),
        ("output_mapping", {"roundtrip": True}),
        ("output_mapping", {"roundtrip": "swap"}),
        ("output_mapping", {"roundtrip": "output_index", "channel": "BaseColor", **first_output}),
        ("mask_output", {"roundtrip": True}),
        ("mask_output", {"roundtrip": "output_index", "output_index": 0}),
        ("mask_output", {"roundtrip": "output_index", "output_index": 1}),
    ]


def request(resource_url: str = RESOURCE_URL) -> dict[str, Any]:
    """Return the probe request; ProbeSession replays its probe steps after save and reopen."""
    if not resource_url.startswith("resource://starter_assets/") or "?version=" not in resource_url:
        raise ValueError("the probe names an exact versioned starter-asset URL")
    sequence = start("plane", resolution=128)
    material = sequence.add(ps.INSERT_FILL, position="top")  # step 2
    sequence.add(SET_MATERIAL_SOURCE, node_step=material, resource_url=resource_url)
    grey = sequence.add(ps.IMPORT_RESOURCE, input="grey-a", usage="TEXTURE")  # step 4
    split = sequence.add(ps.INSERT_FILL, position="top")
    sequence.add(ps.SET_ACTIVE_CHANNELS, node_step=split, channels=["BaseColor"])
    sequence.add(ps.SET_SOURCE, node_step=split, channel="BaseColor", resource_url=resource_url)
    if grey != 4:
        raise AssertionError("the edits name the import as step 4")
    args = {"node_step": material, "material": True}
    single = {"node_step": split, "channel": "BaseColor"}
    for getter in GETTERS:
        sequence.add(PREFIX + getter, **args)
    sequence.add(PREFIX + "get_source", **args, input_index=0)
    for getter in GETTERS:
        sequence.add(PREFIX + getter, **single)
    for call, edit in edits():
        sequence.add(PREFIX + call, **args, **edit, probe=True)
        for getter in AFTER:
            sequence.add(PREFIX + getter, **args)
        sequence.add(PREFIX + "get_source", **args, input_index=0)
    result = manifest(
        Golden(
            NAME,
            "tier0/api-probes/" + NAME,
            "SourceSubstance presets, image inputs and multiple outputs on one starter material "
            "(decision 412): a fill's material source and a split BaseColor source of the same "
            "resource, their getters, then apply_preset (first preset, and a missing name), the "
            "first image input set to a colour and to the grey-a bitmap, reset and removed, the "
            "output mapping assigned back, swapped and assigned the first output, and the mask "
            "output assigned back and assigned the first two outputs, with readbacks after each, "
            "repeated after save/reopen. The preset, input and outputs are chosen in Painter by "
            "index; no asset parameter, preset, input or output name is authored.",
            "plane",
            ["plane", "grey-a"],
            sequence,
        ),
        {"plane": PLANE_SHA256, "grey-a": GREY_A_SHA256},
    )
    result["golden_id"] = "tier0/api-probes/" + NAME
    return _pin(result)


def anchor_request(resource_url: str = RESOURCE_URL) -> dict[str, Any]:
    """The first image input set to an anchor point, then reset, repeated after save/reopen.

    Anchor point references are a release gap of their own (phase4.1_nodes-instances-anchors),
    so this observation is a separate golden: the main probe's replay does not depend on it.
    """
    if not resource_url.startswith("resource://starter_assets/") or "?version=" not in resource_url:
        raise ValueError("the probe names an exact versioned starter-asset URL")
    sequence = start("plane", resolution=128)
    paint = sequence.add(INSERT_PAINT, position="top")  # step 2
    anchor = sequence.add(INSERT_ANCHOR, inside_step=paint, node_stack="Content", name="uzp-anchor")
    material = sequence.add(ps.INSERT_FILL, position="top")
    sequence.add(SET_MATERIAL_SOURCE, node_step=material, resource_url=resource_url)
    args = {"node_step": material, "material": True}
    sequence.add(PREFIX + "image_inputs", **args)
    sequence.add(PREFIX + "get_source", **args, input_index=0)
    for call, edit in (
        ("set_source", {"input_index": 0, "anchor_step": anchor}),
        ("reset_source", {"input_index": 0}),
    ):
        sequence.add(PREFIX + call, **args, **edit, probe=True)
        sequence.add(PREFIX + "get_parameters", **args)
        sequence.add(PREFIX + "get_source", **args, input_index=0)
    result = manifest(
        Golden(
            ANCHOR_NAME,
            "tier0/api-probes/" + ANCHOR_NAME,
            "The decision-412 starter material's first image input (chosen in Painter) set to "
            "an anchor point inside a paint layer below the fill, then reset, with get_source "
            "and get_parameters after each, repeated after save/reopen. No asset parameter or "
            "input name is authored.",
            "plane",
            ["plane"],
            sequence,
        ),
        {"plane": PLANE_SHA256},
    )
    result["golden_id"] = "tier0/api-probes/" + ANCHOR_NAME
    return _pin(result)
