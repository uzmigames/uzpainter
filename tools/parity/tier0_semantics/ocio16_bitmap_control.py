"""Authored OCIO RGB16 input control; no oracle pixels or fitted transforms."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from python.uzpainter_facade.bitmap_defaults import (
    PAINTER_OCIO_CONFIG_SHA256,
    SpaceIdentity,
    native_tag,
)
from tools.parity.envelope.registry import current_envelope
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT, ExportStep, canonical_json
from tools.parity.recorder.probes import probe_job_from_manifest
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import recording_requests as rr
from tools.parity.tier0_semantics.corpus import FIXTURE_DIR, Golden, start
from tools.parity.tier0_semantics.fixtures import png16

NAME = "ocio16-bitmap-srgb-basecolor"
SET_SPACE = "substance_painter.source.SourceBitmap.set_color_space"
GET_SPACE = "substance_painter.source.SourceBitmap.get_color_space"
SET_PROJECTION = "substance_painter.layerstack.FillLayerNode.set_projection_parameters"
SET_MODE = "substance_painter.layerstack.FillLayerNode.set_projection_mode"
BITMAPS = ("field-a", "field-a-brg", "field-a-gbr", "srgb8-ramp")
FORMATS = (("png", 8), ("png", 16), ("exr", "32f"))
UV = {
    "filtering_mode": "Nearest",
    "uv_wrapping_mode": "Repeat",
    "scale_mode": "Factors",
    "scale": [1.0, 1.0],
    "rotation": 0.0,
    "offset": [0.0, 0.0],
}


def permuted_field(order: str) -> bytes:
    """Permute the public field-a definition, without decoding any captured image."""
    if order not in ("brg", "gbr"):
        raise ValueError("only the two cyclic field-a permutations are authored")
    indices = tuple("rgb".index(c) for c in order)

    def pixel(x: int, y: int) -> tuple[int, ...]:
        rgb = (x * 257, y * 257, x * 256 + y)
        return tuple(rgb[i] for i in indices)

    return png16(256, 256, 3, pixel)


def authored_files() -> dict[str, bytes]:
    return {
        f"{FIXTURE_DIR}/bitmaps/field-a-{order}.png": permuted_field(order)
        for order in ("brg", "gbr")
    }


STATES = (*BITMAPS, "uniform")
GET_SOURCE = "substance_painter.layerstack.FillLayerNode.get_source"


def request_name(source: str) -> str:
    if source not in STATES:
        raise ValueError("unrecorded OCIO16 control state")
    return NAME if source == "field-a" else f"{NAME}-{source}"


def request(source: str = "field-a") -> dict[str, Any]:
    name = request_name(source)
    s = start("plane", resolution=256)
    s.add("substance_painter.textureset.Stack.edit_channel", channel="BaseColor", format="sRGB8")
    resources = s.imports(source) if source != "uniform" else {}
    node = s.fill(["BaseColor"], position="top", texture_set="uzp_plane")
    s.blend(node, "BaseColor", "Normal", 1.0)
    s.add(SET_MODE, node_step=node, projection_mode="UV")
    s.add(SET_PROJECTION, node_step=node, **UV)
    if source == "uniform":
        s.add(
            ps.SET_SOURCE,
            node_step=node,
            channel="BaseColor",
            color=[0.0, 0.5, 1.0],
            color_space="Working",
        )
        s.add(GET_SOURCE, node_step=node, channel="BaseColor")
    else:
        s.add(ps.SET_SOURCE, node_step=node, channel="BaseColor", resource_step=resources[source])
        s.add(
            SET_SPACE,
            node_step=node,
            channel="BaseColor",
            color_space="sRGB",
            color_space_type="str",
        )
        s.add(GET_SPACE, node_step=node, channel="BaseColor", typed=True)
    for file_format, depth in FORMATS:
        s.add(
            EXPORT,
            maps=["documentMap/basecolor:RGB"],
            file_format=file_format,
            bit_depth=depth,
            padding="passthrough",
            dithering=False,
            key_by_step=True,
        )
    shared = ["plane"] + ([source] if source in ("field-a", "srgb8-ramp") else [])
    golden = Golden(
        name,
        "tier0/api-probes/ocio16-input",
        f"Isolated OCIO Substance-config input control: {source}, into BaseColor sRGB8 "
        "on the authored 256px full-UV plane. Bitmap inputs use the explicit literal "
        "configuration string sRGB, not a generic enum; the uniform uses Working (0, 0.5, 1). "
        "Nearest identity UV, Normal opacity 1. Setup runs once. Read the typed bitmap "
        "space (or uniform source) before PNG8, PNG16 and EXR32f capture exports, with no "
        "dithering or padding. Full save/reopen repeats that getter before exports, without "
        "any setter. Five independent controls total 15 exported maps per repetition. "
        "Measures the composite input-to-sRGB8 path, not a full-precision decoder; "
        "no fit, preset parity or capability promotion.",
        "plane",
        shared,
        s,
        [dict(rr.OCIO_SETTING)],
    )
    hashes = {
        key: hashlib.sha256((REPO_ROOT / rr.fixture(key)[1]).read_bytes()).hexdigest()
        for key in shared
    }
    result = rr.request_manifest(golden, hashes, current_envelope())
    result["golden_id"] = "tier0/api-probes/" + name
    for path, data in authored_files().items():
        if Path(path).stem != source:
            continue
        result["inputs"].append(
            {
                "input_id": source,
                "kind": "image",
                "path": path,
                "sha256": hashlib.sha256(data).hexdigest(),
                "provenance": {
                    "origin": "uzmigames_authored",
                    "licence": "Apache-2.0",
                    "note": "Generated by tools/parity/tier0_semantics/ocio16_bitmap_control.py.",
                },
            }
        )
    return result


def write_authored() -> None:
    """Write only durable public inputs and the current envelope's request."""
    for path, data in authored_files().items():
        (REPO_ROOT / path).write_bytes(data)
    for source in STATES:
        request_path = (
            rr.request_root(REPO_ROOT) / "tier0/api-probes" / f"{request_name(source)}.json"
        )
        request_path.write_text(json.dumps(request(source), indent=2) + "\n", encoding="utf-8")


NATIVE_BASELINES = ("srgb8-ramp", "uniform")
RGB16_CANDIDATES = ("field-a", "field-a-brg", "field-a-gbr")
RGB16_CANDIDATE_MODEL = "legacy-rgb16-to-srgb8-with-ocio-export"


@dataclass(frozen=True)
class NativeBaseline:
    source: str
    manifest: dict[str, Any]
    inputs: dict[str, Path]
    exports: tuple[ExportStep, ...]


def native_baseline(
    authored: dict[str, Any],
    source: str,
    *,
    configuration_sha256: str,
) -> NativeBaseline:
    """Translate only the frozen RGB8/uniform recipes; no oracle or default-space lookup."""
    if source not in NATIVE_BASELINES or configuration_sha256 != PAINTER_OCIO_CONFIG_SHA256:
        raise ValueError("native baseline source or OCIO profile is outside the authored domain")
    return _native_plan(authored, source)


def native_rgb16_candidate(
    authored: dict[str, Any],
    source: str,
    *,
    configuration_sha256: str,
) -> NativeBaseline:
    """Authored input to the test-only RGB16 hypothesis, never the ordinary export route."""
    if source not in RGB16_CANDIDATES or configuration_sha256 != PAINTER_OCIO_CONFIG_SHA256:
        raise ValueError("RGB16 candidate source or OCIO profile is outside the authored domain")
    return _native_plan(authored, source)


def _native_plan(authored: dict[str, Any], source: str) -> NativeBaseline:
    expected = request(source)
    for key in ("golden_id", "inputs", "instruction_sequence", "applied_settings", "software"):
        if canonical_json(authored.get(key)) != canonical_json(expected[key]):
            raise ValueError("native authored contract changed")
    if authored.get("private_records") != [] or authored.get("expectations") != []:
        raise ValueError("native plan requires an authored request, not oracle inputs")
    job = probe_job_from_manifest(authored)
    if len(job.exports) != 3 or len(job.probe_steps) != 1:
        raise ValueError("native capture contract changed")
    steps = []
    for original in authored["instruction_sequence"]["steps"]:
        step = deepcopy(original)
        call, args = step["call"], step["args"]
        if call in (GET_SPACE, GET_SOURCE, SET_SPACE, EXPORT):
            continue
        if call == "substance_painter.textureset.Stack.edit_channel":
            # The evaluator fixture declares channels; it does not replay stack edits.
            step["call"] = "substance_painter.textureset.Stack.add_channel"
        if call == ps.SET_SOURCE and "resource_step" in args:
            args["color_space"] = native_tag(SpaceIdentity("str", "sRGB"), "ocio")
        steps.append(step)
    converted = deepcopy(authored)
    converted["instruction_sequence"]["steps"] = steps
    return NativeBaseline(source, converted, dict(job.inputs), job.exports)


if __name__ == "__main__":
    write_authored()
