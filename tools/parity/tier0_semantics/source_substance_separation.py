"""Separating recordings of the decision-412 starter material (decision 413, P413-C/D/E).

The P413-A fit left three things unseparated (`phase3.2_source-substance-presets-inputs` item
2.4): every masked configuration it reached had constant outputs, so one value per recording
could not tell the mask arithmetic apart, and its r2 differed from r1 by one binary16 ulp; the
split BaseColor fill had one constant; and P413-B's iterated `output_mapping` raised on every
split fill where the decision-413 capture read the property's class. These requests separate
them:

- **P413-C.** The material fill in the preset-bitmap state (non-constant outputs) masked by each
  output, under the default and the swapped mapping, with r1, r2 and r3 (two reopens), so the
  mask arithmetic can be fitted and the reopen value seen to be stable or not.
- **P413-D.** The split source alone, on BaseColor (its default active output and the other one)
  and on Height, in the preset-colour and preset-bitmap states, so the split channel store can
  be fitted on more than one value.
- **P413-E.** `output_mapping` read on split sources and on a material source as the property's
  class, by iteration, by length and by subscription, each a step of its own.

As in P413-A, nothing about the asset is authored beyond its URL: the preset, input and outputs
are chosen in Painter by index (decision 412 §1).
"""

from __future__ import annotations

from typing import Any

from tools.parity.recorder import vocabulary as ps
from tools.parity.tier0_semantics.corpus import Sequence, start
from tools.parity.tier0_semantics.source_substance_channels import (
    BITMAP,
    COLOUR,
    MASK_FIRST,
    MASK_SECOND,
    PRESET,
    SWAP,
    Edit,
    _check,
    _export,
    _golden,
    _material_reads,
)
from tools.parity.tier0_semantics.source_substance_presets import (
    PREFIX,
    RESOURCE_URL,
    SET_MATERIAL_SOURCE,
)

MASKED_PREFIX = "source-substance-masked-"
SPLIT_PREFIX = "source-substance-split-"
ACCESS_NAME = "source-substance-mapping-access"
REOPEN_COUNT = {"name": "recorder.reopen_count", "value": 2, "applied_by": "recorder_api"}

PRESET_COLOUR: tuple[Edit, ...] = (PRESET, COLOUR)
PRESET_BITMAP: tuple[Edit, ...] = (PRESET, COLOUR, BITMAP)
# P413-C: the mask output (by index in `image_outputs`: 0 `normal`, 1 `height`, decision 413)
# and whether the mapping is swapped, on the preset-bitmap state.
MASKED: dict[str, tuple[Edit, ...]] = {
    "by-normal": (*PRESET_BITMAP, MASK_FIRST),
    "by-height": (*PRESET_BITMAP, MASK_SECOND),
    "by-normal-swap": (*PRESET_BITMAP, SWAP, MASK_FIRST),
    "by-height-swap": (*PRESET_BITMAP, SWAP, MASK_SECOND),
}
OTHER_OUTPUT: Edit = ("active_output", {"roundtrip": "output_index", "output_index": 1})
# P413-D: the split channel, the source's edits, and an active-output edit if any.
SPLIT: dict[str, tuple[str, tuple[Edit, ...]]] = {
    "basecolor-colour": ("BaseColor", PRESET_COLOUR),
    "basecolor-bitmap": ("BaseColor", PRESET_BITMAP),
    "basecolor-second-colour": ("BaseColor", (*PRESET_COLOUR, OTHER_OUTPUT)),
    "basecolor-second-bitmap": ("BaseColor", (*PRESET_BITMAP, OTHER_OUTPUT)),
    "height-colour": ("Height", PRESET_COLOUR),
    "height-bitmap": ("Height", PRESET_BITMAP),
}
# P413-E: split fills (active channels, channels given the resource), then the material fill.
ACCESS_FILLS: tuple[tuple[str, ...], ...] = (("BaseColor",), ("Height",), ("User0", "User1"))
ACCESSES = ("class", "iterate", "len")
MATERIAL_KEYS = ("Height", "Normal", "BaseColor")


def _start(resource_url: str) -> Sequence:
    _check(resource_url)
    sequence = start("plane", resolution=128)
    return sequence


def _material(sequence: Sequence, resource_url: str) -> int:
    material = sequence.add(ps.INSERT_FILL, position="top")  # step 2
    sequence.add(SET_MATERIAL_SOURCE, node_step=material, resource_url=resource_url)
    grey = sequence.add(ps.IMPORT_RESOURCE, input="grey-a", usage="TEXTURE")
    if grey != 4:
        raise AssertionError("the bitmap edit names the import as step 4")
    return material


def masked_request(name: str, resource_url: str = RESOURCE_URL) -> dict[str, Any]:
    """P413-C: the material fill alone in the preset-bitmap state, masked, two reopens."""
    sequence = _start(resource_url)
    material = _material(sequence, resource_url)
    for call, edit in MASKED[name]:
        sequence.add(PREFIX + call, node_step=material, material=True, **edit)
    _material_reads(sequence, material)
    _export(sequence)
    edits = ", ".join(call for call, _ in MASKED[name])
    result = _golden(
        MASKED_PREFIX + name,
        "P413-C (decision 413): the decision-412 starter material alone as a fill's material "
        "source with the effective edits (" + edits + ") applied as state steps: the first "
        "preset, the first image input set to the working colour and then to the grey-a bitmap "
        "(non-constant outputs), and the mask output set to an output chosen in Painter by "
        "index; its active channels, parameters, output mapping, mask output and first input "
        "source, then the BaseColor, Height and Normal channels as OpenEXR 32f with "
        "passthrough padding, repeated after each of two save/reopen cycles (r2, r3).",
        sequence,
        grey=True,
    )
    result["applied_settings"].append(dict(REOPEN_COUNT))
    return result


def split_request(name: str, resource_url: str = RESOURCE_URL) -> dict[str, Any]:
    """P413-D: the split source alone on one channel, edited to a non-default state."""
    channel, edits = SPLIT[name]
    sequence = _start(resource_url)
    split = sequence.fill([channel])  # step 2
    sequence.add(ps.SET_SOURCE, node_step=split, channel=channel, resource_url=resource_url)
    grey = sequence.add(ps.IMPORT_RESOURCE, input="grey-a", usage="TEXTURE")
    for call, edit in edits:
        if "resource_step" in edit:
            edit = {**edit, "resource_step": grey}
        sequence.add(PREFIX + call, node_step=split, channel=channel, **edit)
    sequence.add(ps.GET_ACTIVE_CHANNELS, node_step=split)
    for getter in ("active_output", "get_parameters"):
        sequence.add(PREFIX + getter, node_step=split, channel=channel)
    sequence.add(PREFIX + "get_source", node_step=split, channel=channel, input_index=0)
    _export(sequence)
    names = ", ".join(call for call, _ in edits)
    return _golden(
        SPLIT_PREFIX + name,
        "P413-D (decision 413): the decision-412 starter material alone as the split source of "
        "a fill that activates " + channel + " only, with the edits (" + names + ") applied "
        "as state steps (the preset, the first image input and any active output chosen in "
        "Painter by index; the input set to the working colour, then to the grey-a bitmap); "
        "its active channels, active output, parameters and first input source, then the "
        "BaseColor, Height and Normal channels as OpenEXR 32f with passthrough padding, "
        "repeated after save/reopen.",
        sequence,
        grey=True,
    )


def access_request(resource_url: str = RESOURCE_URL) -> dict[str, Any]:
    """P413-E: `output_mapping` by class, iteration, length and subscription, step by step."""
    sequence = _start(resource_url)
    sequence.channels((("User0", "L32F"), ("User1", "RGB32F")))
    fills: list[tuple[int, tuple[str, ...]]] = []
    for active in ACCESS_FILLS:
        node = sequence.fill(list(active))
        for channel in active:
            sequence.add(ps.SET_SOURCE, node_step=node, channel=channel, resource_url=resource_url)
        fills.append((node, active))
    material = sequence.add(ps.INSERT_FILL, position="top")
    sequence.add(SET_MATERIAL_SOURCE, node_step=material, resource_url=resource_url)
    getter = PREFIX + "output_mapping"
    for node, active in fills:
        for channel in active:
            for access in ACCESSES:
                sequence.add(getter, node_step=node, channel=channel, access=access)
            sequence.add(getter, node_step=node, channel=channel, access="item", key=channel)
    for access in ACCESSES:
        sequence.add(getter, node_step=material, material=True, access=access)
    for key in MATERIAL_KEYS:
        sequence.add(getter, node_step=material, material=True, access="item", key=key)
    return _golden(
        ACCESS_NAME,
        "P413-E (decision 413): the decision-412 starter material as the split source of fills "
        "that activate BaseColor, Height, and User0 L32F with User1 RGB32F (every active channel "
        "sourced), and as a fill's material source; output_mapping read on each source as the "
        "property's class, by iteration, by length and by subscription (the source's own "
        "channel; Height, Normal and BaseColor on the material source), one step each, "
        "repeated after save/reopen.",
        sequence,
        grey=False,
    )


def requests(resource_url: str = RESOURCE_URL) -> dict[str, dict[str, Any]]:
    """Every P413-C, P413-D and P413-E request by name."""
    result = {MASKED_PREFIX + name: masked_request(name, resource_url) for name in MASKED}
    result.update({SPLIT_PREFIX + name: split_request(name, resource_url) for name in SPLIT})
    result[ACCESS_NAME] = access_request(resource_url)
    return result
