"""Documented single-output SourceSubstance control; no copied asset defaults."""

from __future__ import annotations

from typing import Any

from tools.parity.envelope.registry import current_envelope
from tools.parity.recorder import vocabulary as ps
from tools.parity.tier0_semantics.corpus import Golden, manifest, start

# Resource identity from the approved procedural snapshot recording, not its parameters.
RESOURCE_URL = (
    "resource://starter_assets/grunge_brushed/grunge_brushed"
    "?version=b4e81c7b2005b2ec89569eb7106831557ec530a1.sbsar"
)
PREFIX = "substance_painter.source.SourceSubstance."
GETTERS = (
    "get_parameters",
    "get_properties",
    "get_preset_list",
    "image_inputs",
    "image_outputs",
    "resource_id",
    "active_output",
    "resolution",
)
NAME = "source-substance-single-output"
PLANE_SHA256 = "7d3c5f616c2abf4b06050434fa943d19dcb15ec998245a211d1d4ca7e95197fe"


def request() -> dict[str, Any]:
    """Return a standalone API request, replayed after save/reopen by ProbeSession."""
    sequence = start("plane", resolution=128)
    sequence.channels((("User0", "L32F"),))
    node = sequence.fill(["User0"])
    args = {"node_step": node, "channel": "User0"}
    sequence.add(ps.SET_SOURCE, **args, resource_url=RESOURCE_URL)
    for getter in GETTERS:
        sequence.add(PREFIX + getter, **args)
    for setter in ("set_parameters", "active_output", "resolution"):
        sequence.add(PREFIX + setter, **args, roundtrip=True, probe=True)
        for getter in GETTERS:
            sequence.add(PREFIX + getter, **args)
    for mode in ("Custom", "Auto"):
        sequence.add(PREFIX + "resolution", **args, roundtrip=False, mode=mode, probe=True)
        for getter in GETTERS:
            sequence.add(PREFIX + getter, **args)
    result = manifest(
        Golden(
            NAME,
            "tier0/api-probes/" + NAME,
            "Single-output SourceSubstance getters and effective-value roundtrips for "
            "parameters, active_output and resolution, plus Custom128 and Auto resolution "
            "assignment, repeated after save/reopen. "
            "No boolean edits, preset application, image-input edits, multioutput mapping "
            "or FilterEffect restriction coverage is claimed. No asset defaults are authored.",
            "plane",
            ["plane"],
            sequence,
        ),
        {"plane": PLANE_SHA256},
    )
    result["golden_id"] = "tier0/api-probes/" + NAME
    result["applied_settings"] = [
        {
            "name": "texture_set.resolution",
            "value": 128,
            "unit": "px",
            "applied_by": "recorder_api",
        }
    ]
    envelope = current_envelope()
    result["software"]["painter"].update(
        version=envelope["painter_version"], build_id=envelope["painter_build"]
    )
    return result
