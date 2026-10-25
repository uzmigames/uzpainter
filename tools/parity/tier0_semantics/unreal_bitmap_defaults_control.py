"""Authored R-322 bitmap defaults control; no observed defaults or exported pixels."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from tools.parity.envelope.registry import current_envelope
from tools.parity.recorder import vocabulary as ps
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import recording_requests as rr
from tools.parity.tier0_semantics import unreal_preset_control
from tools.parity.tier0_semantics.corpus import Golden, Sequence

GET_SOURCE = "substance_painter.layerstack.FillLayerNode.get_source"
GET_COLOR_SPACE = "substance_painter.source.SourceBitmap.get_color_space"
NAME = "source-bitmap-defaults-unreal-"


def request(ocio: bool = False) -> dict[str, Any]:
    """Reuse the exact authored setup, then read fresh sources and typed colour spaces."""
    original = unreal_preset_control.request(ocio)
    sequence = Sequence()
    for step in original.sequence.steps:
        if step["call"] == rr.PREDEFINED_PRESETS:
            break
        sequence.steps.append(deepcopy(step))
    else:
        raise ValueError("R-322 setup boundary is missing")

    inputs: list[str] = []
    sources: list[dict[str, Any]] = []
    for step in sequence.steps:
        args = step["args"]
        for key in ("mesh", "input"):
            if key in args and args[key] not in inputs:
                inputs.append(args[key])
        if step["call"] == ps.SET_SOURCE:
            sources.append({"node_step": args["node_step"], "channel": args["channel"]})
    for args in sources:
        sequence.add(GET_SOURCE, **args)
        sequence.add(GET_COLOR_SPACE, **args, typed=True)

    golden = Golden(
        NAME + ("ocio" if ocio else "legacy"),
        "tier0/api-probes/bitmap-defaults",
        "Default SourceBitmap colour spaces for the exact R-322 authored setup: same "
        "template, channels, bitmap imports, mesh maps, Normal blending and opacity 1.0. "
        "Read each source freshly, then its documented get_color_space with the existing "
        "typed class/name serializer. Repeat after Full save/reopen. No colour-space setter, "
        "preset lookup or export. Getter values and effective defaults remain private; "
        "this request authors no expected default and establishes no export parity.",
        original.mesh,
        inputs,
        sequence,
        deepcopy(original.settings),
        original.template,
    )
    hashes = {
        name: hashlib.sha256((REPO_ROOT / rr.fixture(name)[1]).read_bytes()).hexdigest()
        for name in inputs
    }
    result = rr.request_manifest(golden, hashes, current_envelope())
    result["golden_id"] = "tier0/api-probes/" + golden.name
    return result
