"""R-322 authored Unreal preset controls; observed URL, no copied preset internals."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from tools.parity.recorder import vocabulary as ps
from tools.parity.tier0_semantics import request_fixtures as rf
from tools.parity.tier0_semantics.corpus import FIXTURE_DIR, Golden, start
from tools.parity.tier0_semantics.fixtures import Config

# R-314 padding Legacy, r2, documented list_resource_export_presets readback.
URL_EVIDENCE = "e729f2294b0d4acc019a2fa7b025c01df0821fa9dd9acf78ee00fcce4e4ce2fd"
PRESET = "resource://starter_assets/Unreal Engine (Packed)?version=8339356058946582545.spexp"
GROUP = "presets-unreal-packed-bevelled-cube"
MATERIAL = "uzp_bevelled_cube"
BITMAPS = (
    "field-a",
    "field-b",
    "grey-a",
    "grey-b",
    "grey-173",
    "height-ramps",
    "hue-grid-grey",
    "hue-grid-transposed-grey",
    "normal-a",
    "normal-b",
)


def probe_groups() -> dict[str, dict[str, Config]]:
    """Keep actual defaults separate from every explicit processing override."""
    base: Config = {
        "exportShaderParams": False,
        "defaultExportPreset": PRESET,
        "exportList": [{"rootPath": MATERIAL}],
    }
    parameters = {
        "unreal-padding": {"paddingAlgorithm": "infinite"},
        "unreal-png8": {**rf.PIPELINE_PARAMETERS, "bitDepth": "8"},
        "unreal-tga8": {**rf.PIPELINE_PARAMETERS, "fileFormat": "tga", "bitDepth": "8"},
        "unreal-pipeline": dict(rf.PIPELINE_PARAMETERS),
    }
    return {
        GROUP: {
            "unreal-own": base,
            **{
                name: {**base, "exportParameters": [{"parameters": values}]}
                for name, values in parameters.items()
            },
        }
    }


def input_fixtures() -> dict[str, tuple[str, str, Callable[[], bytes]]]:
    """Standalone registry entries; existing authored mesh/bitmaps remain shared."""
    return {
        f"probe-{group}-{name}": (
            "recipe_json",
            f"{FIXTURE_DIR}/export-probes/{group}/{name}.json",
            partial(rf.recipe, config),
        )
        for group, probes in probe_groups().items()
        for name, config in probes.items()
    }


def request(ocio: bool = False) -> Golden:
    from tools.parity.tier0_semantics import recording_requests as rr

    s = start("bevelled-cube", None if ocio else rr.ALPHA_BLEND)
    s.channels(
        ((("Opacity", "L8"), ("EmissionColor", "sRGB8")) if ocio else ())
        + (("AO", "L16"), ("SpecularWeight", "L8"))
    )
    resources = s.imports(*BITMAPS)
    s.add(ps.SET_MESH_MAP, usage="Normal", resource_step=resources["normal-b"])
    s.add(ps.SET_MESH_MAP, usage="AO", resource_step=resources["grey-a"])
    rr.fill(
        s,
        {
            "BaseColor": "field-a",
            "SpecularRoughness" if ocio else "Roughness": "grey-a",
            "BaseMetalness" if ocio else "Metallic": "grey-b",
            "Height": "height-ramps",
            "Normal": "normal-a",
            "Opacity": "hue-grid-grey",
            "EmissionColor": "field-b",
            "AO": "hue-grid-transposed-grey",
            "SpecularWeight": "grey-173",
        },
        resources,
        position="top",
        texture_set=MATERIAL,
    )
    s.add(rr.PREDEFINED_PRESETS)
    s.add(rr.RESOURCE_PRESETS)
    s.add(rr.RESOURCE_OUTPUT_MAPS, preset=PRESET)
    inputs = list(input_fixtures())
    for input_id in inputs:
        for _ in range(2):
            s.add(ps.LIST_TEXTURES, config=input_id)
    return Golden(
        "export-presets-unreal-packed-" + ("ocio" if ocio else "legacy"),
        "tier0/export/presets",
        "R-322 (decision 322), Unreal Engine (Packed), on the UzmiGames-authored bevelled "
        "cube, 256 px, OpenGL. Same distinct nine channel sources and Normal/AO mesh maps "
        "as R-314: field A BaseColor, grey A roughness, grey B metalness, height ramps, "
        "normal-a, hue-grid grey Opacity, field B EmissionColor, transposed hue-grid grey AO, "
        "grey173 SpecularWeight; normal-b Normal mesh and grey A AO mesh. "
        "Precondition: application shelf discovery completed before this recording, and "
        "the observed versioned URL is present. Capture preset lists, documented resource "
        "list_output_maps, dry-run lists, then exports. Probe own parameters unchanged "
        "(a refusal stays evidence of refusal); padding-only infinite leaves format, depth "
        "and dithering at actual defaults. Explicit PNG8 and TGA8 share infinite padding "
        "and disabled dithering; pipeline PNG16 uses the same processing. Repeat every "
        "probe in session and after Full save/reopen. Record actual format, depth, map "
        "names, channels, defaults and hashes; never infer them from shipped hypotheses. "
        "No UE import, DDS/cook, pilot acceptance or exact UzPainter parity is implied. "
        + (
            "Separate OCIO process with pipeline default OpenPBR channels plus added channels."
            if ocio
            else "Separate Legacy process with Alpha-blend template plus AO/SpecularWeight."
        ),
        "bevelled-cube",
        ["bevelled-cube", *BITMAPS, *inputs],
        s,
        [rr.OCIO_SETTING] if ocio else [],
    )
