"""One independently authored no-plane host/Filter capture recipe (decision 362)."""

from __future__ import annotations

import hashlib
from typing import Any

from tools.parity.envelope.registry import current_envelope
from tools.parity.recorder import vocabulary as ps
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import recording_requests as rr
from tools.parity.tier0_semantics.corpus import Golden, start

NAME = "filter-observation-no-plane"
NODE = "substance_painter.layerstack.Node."
FILL = "substance_painter.layerstack.FillLayerNode."
LAYER = "substance_painter.layerstack.LayerNode."
SOURCE = "substance_painter.source.SourceSubstance."
CHANNEL = "User0"
HOST_QUERY = {
    "search": "s:starterassets u:substance",
    "require_unique": True,
    "resource_context": "starter_assets",
    "resource_name": "grunge_brushed/grunge_brushed",
}
FILTER_QUERY = {
    "search": "s:starterassets u:filter n:Blur=",
    "require_unique": True,
    "resource_selection": "gui_name",
    "resource_context": "starter_assets",
    "resource_gui_name": "Blur",
    "resource_usage": "FILTER",
}
UV = {
    "filtering_mode": "Nearest",
    "uv_wrapping_mode": "Repeat",
    "scale_mode": "Factors",
    "scale": [1.0, 1.0],
    "rotation": 0.0,
    "offset": [0.0, 0.0],
}
GEOMETRY = {"type": "Mesh", "inclusion_list": False, "items": []}


def request() -> dict[str, Any]:
    sequence = start("plane", resolution=256)
    sequence.channels(((CHANNEL, "L32F"),))
    host = sequence.fill([CHANNEL], position="top", texture_set="uzp_plane")
    sequence.add(LAYER + "set_geometry_mask", node_step=host, inclusion_list=False, meshes=[])
    sequence.add(FILL + "set_projection_mode", node_step=host, projection_mode="UV")
    sequence.add(FILL + "set_projection_parameters", node_step=host, **UV)
    sequence.add(ps.SET_SOURCE, node_step=host, channel=CHANNEL, **HOST_QUERY)
    effect = sequence.add(ps.INSERT_FILTER, inside_step=host, node_stack="Content", **FILTER_QUERY)
    sequence.add(ps.SET_FILTER_CHANNELS, node_step=effect, channels=[CHANNEL])
    for node, name in ((host, "Observation host"), (effect, "Observation filter")):
        sequence.add(NODE + "set_name", node_step=node, name=name)
        sequence.add(NODE + "set_visible", node_step=node, visible=True)
        sequence.blend(node, CHANNEL, "Normal", 1.0)
    for node in (host, effect):
        for getter in ("get_name", "is_visible"):
            sequence.add(NODE + getter, node_step=node)
        for getter in ("get_blending_mode", "get_opacity"):
            sequence.add(NODE + getter, node_step=node, channel=CHANNEL)
    sequence.add(LAYER + "get_geometry_mask", node_step=host)
    for getter in (
        "source_mode",
        "active_channels",
        "get_projection_mode",
        "get_projection_parameters",
    ):
        sequence.add(FILL + getter, node_step=host)
    sequence.add(ps.SET_FILTER_CHANNELS, node_step=effect)
    for getter in (
        "get_parameters",
        "resource_id",
        "image_outputs",
        "active_output",
        "resolution",
        "image_inputs",
    ):
        sequence.add(SOURCE + getter, node_step=host, channel=CHANNEL)
    for getter in ("get_parameters", "resource_id", "image_outputs", "image_inputs"):
        sequence.add(SOURCE + getter, node_step=effect, effect=True)
    golden = Golden(
        NAME,
        "tier0/api-probes/" + NAME,
        "Independent strict no-plane Filter observation control. Explicit neutral geometry "
        "and UV; symmetry is inapplicable in UV; fresh unique resources; "
        "paired typed getters, no raster or export.",
        "plane",
        ["plane"],
        sequence,
        [dict(rr.OCIO_SETTING)],
    )
    hashes = {
        "plane": hashlib.sha256((REPO_ROOT / rr.fixture("plane")[1]).read_bytes()).hexdigest()
    }
    result = rr.request_manifest(golden, hashes, current_envelope())
    result["golden_id"] = "tier0/api-probes/" + NAME
    return result
