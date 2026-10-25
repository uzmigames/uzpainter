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
    return _pin(result)


def _pin(result: dict[str, Any]) -> dict[str, Any]:
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


BOOLEANS_FILTER_NAME = "source-substance-booleans-filter"
# Public starter-asset query already recorded by the layer-node-kinds probe (P22-B).
FILTER_SEARCH = "s:starterassets u:filter n:Blur="
EFFECT_GETTERS = ("get_parameters", "resource_id", "image_outputs", "active_output", "resolution")
# Integer and boolean values for the source's first Togglebutton, chosen in Painter.
TOGGLES: tuple[bool | int, ...] = (1, True, 0, False)


def booleans_filter_request() -> dict[str, Any]:
    """Booleans as integers and the FilterEffectNode resolution restriction (python-doc)."""
    sequence = start("plane", resolution=128)
    sequence.channels((("User0", "L32F"),))
    node = sequence.fill(["User0"])
    args = {"node_step": node, "channel": "User0"}
    sequence.add(ps.SET_SOURCE, **args, resource_url=RESOURCE_URL)
    blur = sequence.add(
        ps.INSERT_FILTER, inside_step=node, node_stack="Content", search=FILTER_SEARCH
    )
    sequence.add(PREFIX + "get_parameters", **args)
    for toggle in TOGGLES:
        sequence.add(PREFIX + "set_parameters", **args, roundtrip=False, toggle=toggle, probe=True)
        sequence.add(PREFIX + "get_parameters", **args)
    effect = {"node_step": blur, "effect": True}
    for getter in EFFECT_GETTERS:
        sequence.add(PREFIX + getter, **effect)
    for mode in ("Custom", "Auto"):
        sequence.add(PREFIX + "resolution", **effect, roundtrip=False, mode=mode, probe=True)
        sequence.add(PREFIX + "resolution", **effect)
    result = manifest(
        Golden(
            BOOLEANS_FILTER_NAME,
            "tier0/api-probes/" + BOOLEANS_FILTER_NAME,
            "SourceSubstance booleans and FilterEffectNode restriction: the fill source's first "
            "Togglebutton property set to 1, True, 0 and False with get_parameters after each, "
            "then a starter Blur filter's source getters and Custom128/Auto resolution "
            "assignments, repeated after save/reopen. The parameter is chosen in Painter; no "
            "asset parameter name, default or value is authored.",
            "plane",
            ["plane"],
            sequence,
        ),
        {"plane": PLANE_SHA256},
    )
    result["golden_id"] = "tier0/api-probes/" + BOOLEANS_FILTER_NAME
    return _pin(result)
