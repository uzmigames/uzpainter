"""Channel exports and split contexts of the decision-412 starter material (decision 413).

Decision 413 names two recordings before `phase3.2_source-substance-presets-inputs` can commit a
fill of the probe's material:

- **P413-A.** For each material-fill configuration the `source-substance-presets-inputs` replay
  reaches, Painter's BaseColor, Height and Normal channel exports (OpenEXR 32f, passthrough
  padding) of the probe's own project: the material fill below the split BaseColor fill. Each
  golden applies, as state steps, the probe's edits that took effect up to that configuration (in
  r2 the probe starts from r1's end state, after save and reopen, and its bitmap `set_source`
  raises, so it changes nothing). Two isolated goldens record the material fill alone and the
  split BaseColor fill alone, so the composition of each fill can be fitted on its own.
- **P413-B.** `output_mapping`, `mask_output` and `active_output` read on split fills that activate
  one channel or several, of template and User types, in both recordings.

Nothing about the asset is authored beyond its URL: the preset, input and outputs are chosen in
Painter by index (decision 412 §1), and the only authored values are the probe's own (`grey-a`,
the working colour).
"""

from __future__ import annotations

from typing import Any

from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT
from tools.parity.tier0_semantics.corpus import Golden, Sequence, manifest, start
from tools.parity.tier0_semantics.source_substance_control import PLANE_SHA256, _pin
from tools.parity.tier0_semantics.source_substance_presets import (
    GREY_A_SHA256,
    INPUT_COLOR,
    PREFIX,
    RESOURCE_URL,
    SET_MATERIAL_SOURCE,
)

CHANNELS_PREFIX = "source-substance-channels-"
CONTEXTS_NAME = "source-substance-split-contexts"
MAPS = ["documentMap/basecolor:RGB", "documentMap/height:L", "documentMap/normal:RGB"]

Edit = tuple[str, dict[str, Any]]
PRESET: Edit = ("apply_preset", {"preset_index": 0})
COLOUR: Edit = ("set_source", {"input_index": 0, "color": INPUT_COLOR, "color_space": "Working"})
BITMAP: Edit = ("set_source", {"input_index": 0, "resource_step": 4})
RESET: Edit = ("reset_source", {"input_index": 0})
REMOVE: Edit = ("remove_source", {"input_index": 0})
ROUNDTRIP: Edit = ("output_mapping", {"roundtrip": True})
SWAP: Edit = ("output_mapping", {"roundtrip": "swap"})
BASECOLOR_FIRST: Edit = (
    "output_mapping",
    {"roundtrip": "output_index", "channel": "BaseColor", "output_index": 0},
)
MASK_FIRST: Edit = ("mask_output", {"roundtrip": "output_index", "output_index": 0})
MASK_SECOND: Edit = ("mask_output", {"roundtrip": "output_index", "output_index": 1})

# The probe's edits that took effect, in order (`mask_output` assigned back raises in both
# recordings; in r2 the bitmap `set_source` raises "resource not found", decision 412).
R1_EDITS: tuple[Edit, ...] = (
    PRESET,
    COLOUR,
    BITMAP,
    RESET,
    BITMAP,
    REMOVE,
    ROUNDTRIP,
    SWAP,
    BASECOLOR_FIRST,
    MASK_FIRST,
    MASK_SECOND,
)
R2_EDITS: tuple[Edit, ...] = (PRESET, COLOUR, RESET)

# Each configuration the replay reaches, as the number of edits applied: r1's prefixes, then all
# of r1 followed by r2's prefixes. A configuration equal to an earlier one by its readbacks is
# recorded again when another edit reached it (the bitmap set after a reset), not when the same
# edit repeats it (r2's second removal, swap and mask edits read back r1's end state).
STATES: dict[str, tuple[Edit, ...]] = {
    "defaults": (),
    "preset": R1_EDITS[:1],
    "preset-colour": R1_EDITS[:2],
    "preset-bitmap": R1_EDITS[:3],
    "preset-reset": R1_EDITS[:4],
    "preset-removed": R1_EDITS[:6],
    "mapping-swap": R1_EDITS[:8],
    "mapping-basecolor": R1_EDITS[:9],
    "mask-first": R1_EDITS[:10],
    "mask-second": R1_EDITS,
    "reopen-preset": R1_EDITS + R2_EDITS[:1],
    "reopen-colour": R1_EDITS + R2_EDITS[:2],
    "reopen-reset": R1_EDITS + R2_EDITS,
}


def _check(resource_url: str) -> None:
    if not resource_url.startswith("resource://starter_assets/") or "?version=" not in resource_url:
        raise ValueError("the probe names an exact versioned starter-asset URL")


def _export(sequence: Sequence) -> None:
    sequence.add(
        EXPORT,
        maps=list(MAPS),
        file_format="exr",
        bit_depth="32f",
        padding="passthrough",
        dithering=False,
    )


def _material_reads(sequence: Sequence, node: int) -> None:
    args = {"node_step": node, "material": True}
    sequence.add(ps.GET_ACTIVE_CHANNELS, node_step=node)
    for getter in ("get_parameters", "output_mapping", "mask_output"):
        sequence.add(PREFIX + getter, **args)
    sequence.add(PREFIX + "get_source", **args, input_index=0)


def _split_reads(sequence: Sequence, node: int) -> None:
    sequence.add(ps.GET_ACTIVE_CHANNELS, node_step=node)
    sequence.add(PREFIX + "active_output", node_step=node, channel="BaseColor")


def _golden(name: str, description: str, sequence: Sequence, grey: bool) -> dict[str, Any]:
    inputs = ["plane", "grey-a"] if grey else ["plane"]
    hashes = {"plane": PLANE_SHA256, "grey-a": GREY_A_SHA256}
    result = manifest(
        Golden(name, "tier0/api-probes/" + name, description, "plane", inputs, sequence),
        {key: hashes[key] for key in inputs},
    )
    result["golden_id"] = "tier0/api-probes/" + name
    return _pin(result)


def state_request(state: str, resource_url: str = RESOURCE_URL) -> dict[str, Any]:
    """P413-A: the probe's project in one configuration, read back and exported."""
    _check(resource_url)
    sequence = start("plane", resolution=128)
    material = sequence.add(ps.INSERT_FILL, position="top")  # step 2
    sequence.add(SET_MATERIAL_SOURCE, node_step=material, resource_url=resource_url)
    grey = sequence.add(ps.IMPORT_RESOURCE, input="grey-a", usage="TEXTURE")  # step 4
    if grey != 4:
        raise AssertionError("the bitmap edit names the import as step 4")
    split = sequence.add(ps.INSERT_FILL, position="top")
    sequence.add(ps.SET_ACTIVE_CHANNELS, node_step=split, channels=["BaseColor"])
    sequence.add(ps.SET_SOURCE, node_step=split, channel="BaseColor", resource_url=resource_url)
    for call, edit in STATES[state]:
        sequence.add(PREFIX + call, node_step=material, material=True, **edit)
    _material_reads(sequence, material)
    _split_reads(sequence, split)
    _export(sequence)
    edits = ", ".join(call for call, _ in STATES[state]) or "none"
    return _golden(
        CHANNELS_PREFIX + state,
        "P413-A (decision 413), configuration '" + state + "' of the "
        "source-substance-presets-inputs replay: that probe's project (the decision-412 starter "
        "material as a fill's material source below a split BaseColor fill of the same "
        "resource) with the probe's effective material edits up to it applied as state steps "
        "(" + edits + "; preset, input and outputs chosen in Painter by index), the material "
        "fill's active channels, parameters, output mapping, mask output and first input "
        "source, the split fill's active channels and active output, then the BaseColor, "
        "Height and Normal channels as OpenEXR 32f with passthrough padding, repeated after "
        "save/reopen.",
        sequence,
        grey=True,
    )


def material_only_request(resource_url: str = RESOURCE_URL) -> dict[str, Any]:
    """P413-A: the material fill alone, at the resource's defaults."""
    _check(resource_url)
    sequence = start("plane", resolution=128)
    material = sequence.add(ps.INSERT_FILL, position="top")
    sequence.add(SET_MATERIAL_SOURCE, node_step=material, resource_url=resource_url)
    _material_reads(sequence, material)
    _export(sequence)
    return _golden(
        CHANNELS_PREFIX + "material-only",
        "P413-A (decision 413): the decision-412 starter material alone as a fill's material "
        "source at its defaults, its active channels, parameters, output mapping, mask output "
        "and first input source, then the BaseColor, Height and Normal channels as OpenEXR 32f "
        "with passthrough padding, repeated after save/reopen.",
        sequence,
        grey=False,
    )


def split_only_request(resource_url: str = RESOURCE_URL) -> dict[str, Any]:
    """P413-A: the split BaseColor fill alone, at the resource's defaults."""
    _check(resource_url)
    sequence = start("plane", resolution=128)
    split = sequence.fill(["BaseColor"])
    sequence.add(ps.SET_SOURCE, node_step=split, channel="BaseColor", resource_url=resource_url)
    _split_reads(sequence, split)
    sequence.add(PREFIX + "get_parameters", node_step=split, channel="BaseColor")
    _export(sequence)
    return _golden(
        CHANNELS_PREFIX + "split-only",
        "P413-A (decision 413): the decision-412 starter material alone as the split source of a "
        "fill that activates BaseColor only, at its defaults, its active channels, active output "
        "and parameters, then the BaseColor, Height and Normal channels as OpenEXR 32f with "
        "passthrough padding, repeated after save/reopen.",
        sequence,
        grey=False,
    )


# P413-B: split fills by active channels and the channels given the resource as their source.
CONTEXT_FILLS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("BaseColor",), ("BaseColor",)),
    (("Height",), ("Height",)),
    (("User0",), ("User0",)),
    (("User1",), ("User1",)),
    (("BaseColor", "Height"), ("BaseColor",)),
    (("BaseColor", "Height"), ("BaseColor", "Height")),
    (("User0", "User1"), ("User0",)),
    (("User0", "User1"), ("User0", "User1")),
    (("BaseColor", "User0"), ("BaseColor", "User0")),
)
CONTEXT_GETTERS = ("output_mapping", "mask_output", "active_output")


def contexts_request(resource_url: str = RESOURCE_URL) -> dict[str, Any]:
    """P413-B: the split-context reads on fills of one and several active channels."""
    _check(resource_url)
    sequence = start("plane", resolution=128)
    sequence.channels((("User0", "L32F"), ("User1", "RGB32F")))
    fills: list[tuple[int, tuple[str, ...]]] = []
    for active, sourced in CONTEXT_FILLS:
        node = sequence.fill(list(active))
        for channel in sourced:
            sequence.add(ps.SET_SOURCE, node_step=node, channel=channel, resource_url=resource_url)
        fills.append((node, sourced))
    for node, sourced in fills:
        sequence.add(ps.GET_ACTIVE_CHANNELS, node_step=node)
        for channel in sourced:
            for getter in CONTEXT_GETTERS:
                sequence.add(PREFIX + getter, node_step=node, channel=channel)
    return _golden(
        CONTEXTS_NAME,
        "P413-B (decision 413): the decision-412 starter material as the split source of fills "
        "that activate one channel or several, of template (BaseColor, Height) and User (User0 "
        "L32F, User1 RGB32F) types, given to one or every active channel; output_mapping, "
        "mask_output and active_output read on each source, with each fill's active channels, "
        "repeated after save/reopen.",
        sequence,
        grey=False,
    )


def requests(resource_url: str = RESOURCE_URL) -> dict[str, dict[str, Any]]:
    """Every P413-A and P413-B request by name."""
    result = {CHANNELS_PREFIX + state: state_request(state, resource_url) for state in STATES}
    result[CHANNELS_PREFIX + "material-only"] = material_only_request(resource_url)
    result[CHANNELS_PREFIX + "split-only"] = split_only_request(resource_url)
    result[CONTEXTS_NAME] = contexts_request(resource_url)
    return result
