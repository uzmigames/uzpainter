"""Requested Tier 0 goldens of Phase 1 (decision 100), prepared before the Painter session.

The recording plan of 2026-10-12 (R1-R8) merged with the phase1.16 request R-090
(`parity/reports/phase1/export-processing-encoders.md` section 5): one golden per recording, all
under `tier0/semantics/` (decision 099). Their manifests are requested goldens: they live under
the current envelope's `requests/` root with `private_records` empty, because every manifest
under `manifests/` must name its records (the Tier 0 gate, the refresh and the store verify read
them all). After the Painter session admits a golden (`python -m tools.parity.store record
<manifests path> --run <run>`), its name joins `ADMITTED`: its request file is deleted and the
generator plans its manifest under `manifests/` instead (`current.api_goldens` cannot take it,
because its inputs are the request fixtures).

Later decisions add requests the same way (`later_goldens`): decision 145's sRGB bitmap variants
(decision 156), decision 126's inferred template bases and decision 129's padding probes P-ramp
and P-tie (decision 157), and the other 21 inferred template bases (decision 168).

Colour management: every golden runs under Legacy (Painter started without `OCIO`) except the
two that name `OCIO` in `applied_settings` (`export-ocio-encode`, `export-presets-ocio`), which
run in a session started with Painter's `resources/ocio/substance/config.ocio`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT
from tools.parity.tier0_semantics import request_fixtures as rf
from tools.parity.tier0_semantics.corpus import (
    FIXTURE_DIR,
    FIXTURES,
    GOLDEN_PREFIX,
    MAPS_PER_EXPORT,
    Golden,
    Sequence,
    start,
    template_slug,
)
from tools.parity.tier0_semantics.fixtures import Config, grid

REQUESTS = "requests"
REQUEST_SEMANTICS_DIR = f"{REQUESTS}/tier0/semantics"
OCIO_SETTING = {
    "name": "OCIO",
    "value": "resources/ocio/substance/config.ocio",
    "applied_by": "environment_variable",
}
EXPORT_DOMAIN = "tier0/export/processing"

# Capture calls of texture jobs (recordings R5-R7): read again in every recording.
PREDEFINED_PRESETS = "substance_painter.export.list_predefined_export_presets"
RESOURCE_PRESETS = "substance_painter.export.list_resource_export_presets"
PREDEFINED_OUTPUT_MAPS = "substance_painter.export.PredefinedExportPreset.list_output_maps"
RESOURCE_OUTPUT_MAPS = "substance_painter.export.ResourceExportPreset.list_output_maps"
COLOUR_SPACES = "substance_painter.source.SourceBitmap.list_available_color_spaces"

Generate = Callable[[], bytes]


def probe_groups() -> dict[str, dict[str, Config]]:
    """Literal export configurations per golden: group -> probe id -> configuration."""
    return {
        "padding-islands": rf.alpha_probes(
            ("uzp_islands",),
            (
                {"paddingAlgorithm": "infinite"},
                {"paddingAlgorithm": "transparent", "dilationDistance": 2},
                {"paddingAlgorithm": "transparent", "dilationDistance": 4},
            ),
        ),
        "padding-bevelled-cube": rf.alpha_probes(
            ("uzp_bevelled_cube",),
            (
                {"paddingAlgorithm": "infinite"},
                {"paddingAlgorithm": "transparent", "dilationDistance": 2},
            ),
        ),
        "alpha-layouts": rf.alpha_probes(("s0", "s1"), ({"paddingAlgorithm": "infinite"},)),
        "resize": rf.resize_probes(),
        "colour-space": rf.colour_space_probes(),
        "presets-bevelled-cube": rf.preset_probes("uzp_bevelled_cube"),
    }


def probe_generator(group: str, probe: str) -> Generate:
    return lambda: rf.recipe(probe_groups()[group][probe])


# Authored inputs of the requests: id -> (kind, repository path, generator).
REQUEST_FIXTURES: dict[str, tuple[str, str, Generate]] = {
    "islands": ("mesh", f"{FIXTURE_DIR}/meshes/islands.obj", rf.islands),
    "seam": ("mesh", f"{FIXTURE_DIR}/meshes/seam.obj", rf.seam),
    "seam-side-mask": ("mask", f"{FIXTURE_DIR}/bitmaps/seam-side-mask.png", rf.seam_side_mask),
    "slow-ramp": ("image", f"{FIXTURE_DIR}/bitmaps/slow-ramp.png", rf.slow_ramp),
    "slow-ramp-grey": (
        "image",
        f"{FIXTURE_DIR}/bitmaps/slow-ramp-grey.png",
        lambda: rf.slow_ramp(grey=True),
    ),
    "impulse-texel": ("image", f"{FIXTURE_DIR}/bitmaps/impulse-texel.png", rf.impulse_texel),
    "half-steps": ("image", f"{FIXTURE_DIR}/bitmaps/half-steps.png", rf.half_steps),
    "half-steps-grey": (
        "image",
        f"{FIXTURE_DIR}/bitmaps/half-steps-grey.png",
        lambda: rf.half_steps(grey=True),
    ),
    "srgb8-ramp": ("image", f"{FIXTURE_DIR}/bitmaps/srgb8-ramp.png", rf.srgb8_ramp),
    "srgb8-grey-ramp": (
        "image",
        f"{FIXTURE_DIR}/bitmaps/srgb8-grey-ramp.png",
        rf.srgb8_grey_ramp,
    ),
    "tie": ("mesh", f"{FIXTURE_DIR}/meshes/tie.obj", rf.tie),
    # Decision 145's nine sets s0-s8 (decision 156: the 4x2 grid has eight).
    "grid3x3": ("mesh", f"{FIXTURE_DIR}/meshes/grid3x3.obj", lambda: grid(3, 3)),
}


def ramp_mesh_generator(mesh: str, phase: str) -> Generate:
    return lambda: rf.ramp_seam(mesh, phase)


def uv_ramp_generator(size: int) -> Generate:
    return lambda: rf.uv_ramp(size)


def renamed_ramp(size: int) -> str:
    """The UV ramp's id and file stem in the re-authored padding probes (decision 166): Painter
    read the suffix of `uv-ramp-1024` and `uv-ramp-2048` as a UDIM tile number (decision 160),
    so the size follows an `n`."""
    return f"uv-ramp-n{size}"


# Decision 129's padding probes: the P-ramp meshes and the float UV ramps.
for _mesh in rf.RAMP_MESHES:
    for _phase in rf.RAMP_PHASES:
        REQUEST_FIXTURES[f"seam-ramp-{_mesh}-{_phase}"] = (
            "mesh",
            f"{FIXTURE_DIR}/meshes/seam-ramp-{_mesh}-{_phase}.obj",
            ramp_mesh_generator(_mesh, _phase),
        )
for _size in (rf.RAMP_RESOLUTION, *rf.TIE_RESOLUTIONS):
    REQUEST_FIXTURES[f"uv-ramp-{_size}"] = (
        "image",
        f"{FIXTURE_DIR}/bitmaps/uv-ramp-{_size}.exr",
        uv_ramp_generator(_size),
    )
for _size in (rf.RAMP_RESOLUTION, *rf.TIE_RESOLUTIONS[1:]):
    REQUEST_FIXTURES[renamed_ramp(_size)] = (
        "image",
        f"{FIXTURE_DIR}/bitmaps/{renamed_ramp(_size)}.exr",
        uv_ramp_generator(_size),
    )
for _group, _probes in probe_groups().items():
    for _probe in _probes:
        REQUEST_FIXTURES[f"probe-{_group}-{_probe}"] = (
            "recipe_json",
            f"{FIXTURE_DIR}/export-probes/{_group}/{_probe}.json",
            probe_generator(_group, _probe),
        )

MESH_SETS = {
    "islands": ["uzp_islands"],
    "seam": ["uzp_seam"],
    "bevelled-cube": ["uzp_bevelled_cube"],
    "sphere": ["uzp_sphere"],
    "grid2x2": [f"s{i}" for i in range(4)],
    "grid4x2": [f"s{i}" for i in range(8)],
    "grid3x3": [f"s{i}" for i in range(9)],
    "plane": ["uzp_plane"],
    "tie": ["uzp_tie"],
    **{f"seam-ramp-{m}-{p}": ["uzp_seam"] for m in rf.RAMP_MESHES for p in rf.RAMP_PHASES},
}


def fixture(name: str) -> tuple[str, str, Generate | None]:
    return REQUEST_FIXTURES[name] if name in REQUEST_FIXTURES else FIXTURES[name]


# --- Sequence helpers ---------------------------------------------------------------------------


Container = tuple[str, str | int]
PNG16: Container = ("png", 16)
PNG8: Container = ("png", 8)
EXR16F: Container = ("exr", "16f")
EXR32F: Container = ("exr", "32f")


def export(
    s: Sequence,
    maps: list[str],
    container: Container,
    padding: str,
    *,
    dithering: bool = False,
    dilation: int | None = None,
    size_log2: int | None = None,
    repeat: bool = True,
) -> None:
    """Export steps over `maps` (at most 16 a step); with `repeat`, each step is done twice in a
    row in the same session (run-to-run noise, R-090; the recorder keys such maps by step)."""
    for first in range(0, len(maps), MAPS_PER_EXPORT):
        args: dict[str, Any] = {
            "maps": maps[first : first + MAPS_PER_EXPORT],
            "file_format": container[0],
            "bit_depth": container[1],
            "padding": padding,
            "dithering": dithering,
        }
        if dilation is not None:
            args["dilation"] = dilation
        if size_log2 is not None:
            args["size_log2"] = size_log2
        for _ in range(2 if repeat else 1):
            s.add(EXPORT, **args)


def fill_sources(
    s: Sequence, node: int, sources: dict[str, Any], res: dict[str, int], **space: str
) -> None:
    """Each channel's source (an imported fixture by id, or a uniform colour as a list), in
    Normal at opacity 1."""
    for channel, source in sources.items():
        if isinstance(source, list):
            s.add(ps.SET_SOURCE, node_step=node, channel=channel, color=source, **space)
        else:
            s.add(ps.SET_SOURCE, node_step=node, channel=channel, resource_step=res[source])
        s.blend(node, channel, "Normal", 1.0)


def fill(s: Sequence, sources: dict[str, Any], res: dict[str, int], **position: Any) -> int:
    node = s.fill(list(sources), **position)
    fill_sources(s, node, sources, res)
    return node


def projection(s: Sequence, node: int, filtering: str, wrap: str = "Repeat") -> None:
    s.add(
        ps.SET_PROJECTION,
        node_step=node,
        filtering_mode=filtering,
        uv_wrapping_mode=wrap,
        scale_mode="Factors",
        scale=[1.0, 1.0],
        rotation=0.0,
        offset=[0.0, 0.0],
    )


def masked(s: Sequence, node: int, mask_step: int) -> None:
    """A black mask on `node` whose fill effect is the imported bitmap `mask_step`."""
    s.add(ps.ADD_MASK, node_step=node, background="Black")
    effect = s.add(ps.INSERT_FILL, inside_step=node, stack="Mask")
    s.bitmap(effect, None, mask_step, effect=True)


def probes(s: Sequence, group: str) -> list[str]:
    inputs = [f"probe-{group}-{probe}" for probe in probe_groups()[group]]
    for input_id in inputs:
        s.add(ps.LIST_TEXTURES, config=input_id)
    return inputs


def grey_of(fmt: str, rgb: str, grey: str) -> str:
    """An L channel takes the grey fixture (decision 048)."""
    return grey if fmt.startswith("L") else rgb


# --- R1: padding (R-090 P5, P6, P9) ----------------------------------------------------------

DILATIONS = (0, 1, 2, 4, 8, 16, 64)
DILATED = ("color", "transparent", "diffusion")
PADDING_MAPS = [
    "documentMap/basecolor:RGB",
    "documentMap/specularroughness:L",
    "documentMap/height:L",
    "virtualMap/Normal_OpenGL:RGB",
    "documentMap/opacity:L",
    "documentMap/user0:RGB",
    "documentMap/user1:L",
]


def export_padding() -> Golden:
    s = start("islands")
    s.channels((("Opacity", "L8"), ("User0", "RGB16"), ("User1", "L32F")))
    res = s.imports("field-a", "grey-a", "height-ramps", "normal-a")
    sources = {
        "BaseColor": "field-a",
        "SpecularRoughness": "grey-a",
        "Height": "height-ramps",
        "Normal": "normal-a",
        "Opacity": "grey-a",
        "User0": "field-a",
        "User1": "grey-a",
    }
    fill(s, sources, res, position="top", texture_set="uzp_islands")
    export(s, PADDING_MAPS, PNG16, "passthrough")
    export(s, PADDING_MAPS, PNG16, "infinite")
    for algorithm in DILATED:
        for distance in DILATIONS:
            export(s, PADDING_MAPS, PNG16, algorithm, dilation=distance)
    for container in (PNG8, EXR32F):
        export(s, PADDING_MAPS, container, "infinite")
        for algorithm in DILATED:
            export(s, PADDING_MAPS, container, algorithm, dilation=4)
    inputs = probes(s, "padding-islands")
    return Golden(
        "export-padding",
        EXPORT_DOMAIN,
        "Export padding on separated UV islands (recording plan R1, R-090 P5/P6, decision 100): "
        "the authored islands mesh (four islands in one texture set: one on the tile's left "
        "border, gaps of 1 and 3 texels, one turned 30 degrees about 20 texels away). One fill: "
        "BaseColor and User0 (RGB16) field A, SpecularRoughness, Opacity (L8) and User1 (L32F) "
        "grey A, Height the height ramps, Normal normal-a. PNG 16: passthrough, infinite, and "
        "color, transparent and diffusion at dilation 0, 1, 2, 4, 8, 16, 64; PNG 8 and OpenEXR "
        "32f: infinite and the three at dilation 4; no dithering; every export step done twice "
        "in the session. Probes: L+A (specularroughness, opacity) and RGB+A (user0, opacity) "
        "under infinite and transparent 2 and 4, PNG 16 and OpenEXR 32f.",
        "islands",
        ["islands", "field-a", "grey-a", "height-ramps", "normal-a", *inputs],
        s,
    )


MESH_PADDING_MAPS = [
    "documentMap/basecolor:RGB",
    "documentMap/height:L",
    "virtualMap/Normal_OpenGL:RGB",
    "documentMap/user0:RGB",
]


def export_padding_mesh(mesh: str) -> Golden:
    s = start(mesh)
    s.channels((("Opacity", "L8"), ("User0", "RGB16")))
    res = s.imports("field-a", "grey-a")
    sources = {
        "BaseColor": "field-a",
        "SpecularRoughness": "grey-a",
        "Height": "field-a",
        "Opacity": "grey-a",
        "User0": "field-a",
    }
    (texture_set,) = MESH_SETS[mesh]
    fill(s, sources, res, position="top", texture_set=texture_set)
    for container in (PNG16, EXR32F):
        export(s, MESH_PADDING_MAPS, container, "infinite")
        export(s, MESH_PADDING_MAPS, container, "passthrough")
        for algorithm in DILATED:
            for distance in (0, 2, 8):
                export(s, MESH_PADDING_MAPS, container, algorithm, dilation=distance)
    inputs = probes(s, "padding-bevelled-cube") if mesh == "bevelled-cube" else []
    alpha = (
        " Probes: L+A and RGB+A (opacity as alpha) under infinite and transparent 2, PNG 16 and "
        "OpenEXR 32f."
        if inputs
        else ""
    )
    return Golden(
        f"export-padding-{mesh}",
        EXPORT_DOMAIN,
        f"Export padding on the authored {mesh} mesh (R-090 P5, decision 100): one fill, "
        "BaseColor, Height and User0 (RGB16) field A, SpecularRoughness and Opacity (L8) grey A. "
        "PNG 16 and OpenEXR 32f: infinite, passthrough, and color, transparent and diffusion at "
        "dilation 0, 2 and 8; no dithering; every export step done twice in the session." + alpha,
        mesh,
        [mesh, "field-a", "grey-a", *inputs],
        s,
    )


SEAM_SIDES = {"Height": ([0.25] * 3, [0.75] * 3), "User0": ([0.2, 0.4, 0.6], [0.9, 0.5, 0.1])}


def export_padding_seam(resolution: int, field: bool) -> Golden:
    s = start("seam", resolution=resolution)
    s.channels((("User0", "RGB16"), ("User1", "RGB16")))
    res = s.imports("field-a", "grey-a", "seam-side-mask")
    if field:
        fill(
            s, {"Height": "grey-a", "User0": "field-a"}, res, position="top", texture_set="uzp_seam"
        )
        maps = ["documentMap/height:L", "documentMap/user0:RGB"]
        what = "Height grey A and User0 (RGB16) field A"
    else:
        a_side = {channel: a for channel, (a, _) in SEAM_SIDES.items()}
        base = fill(s, {**a_side, "User1": "field-a"}, res, position="top", texture_set="uzp_seam")
        b_side = {channel: b for channel, (_, b) in SEAM_SIDES.items()}
        top = fill(s, b_side, res, above_step=base)
        masked(s, top, res["seam-side-mask"])
        maps = ["documentMap/height:L", "documentMap/user0:RGB", "documentMap/user1:RGB"]
        what = (
            "a uniform per side: Height 0.25 and User0 (0.2, 0.4, 0.6) on A, a fill above masked "
            "to B's side by the authored side mask with Height 0.75 and User0 (0.9, 0.5, 0.1); "
            "User1 (RGB16) field A"
        )
    for container in (PNG16, EXR32F):
        export(s, maps, container, "infinite")
    return Golden(
        f"export-padding-seam{'-field' if field else ''}-{resolution}",
        EXPORT_DOMAIN,
        f"The infinite padding ring across a UV seam (R-090 P9, decision 090's partial fit, "
        f"decision 100) at {resolution} px: the authored seam mesh (two quads sharing one 3D "
        "edge, island A at scale 0.375 on the tile's left border, island B at scale 0.25 turned "
        f"90 degrees); {what}. Infinite padding, PNG 16 and OpenEXR 32f, every export step done "
        "twice in the session.",
        "seam",
        ["seam", "field-a", "grey-a", "seam-side-mask"],
        s,
    )


def export_alpha_layouts() -> Golden:
    s = start("grid2x2")
    s.channels((("Opacity", "L8"), ("User0", "RGB16")))
    res = s.imports("field-a", "grey-a", "grey-b")
    sources = {"SpecularRoughness": "grey-a", "User0": "field-a", "Opacity": "grey-b"}
    fill(s, sources, res, position="top", texture_set="s0")
    inputs = probes(s, "alpha-layouts")
    return Golden(
        "export-alpha-layouts",
        EXPORT_DOMAIN,
        "Alpha layouts on full tiles (R-090 P6, decision 100): s0 one fill, SpecularRoughness "
        "grey A, User0 (RGB16) field A, Opacity (L8) grey B; s1-s3 the empty stack. Probes: "
        "$textureSet_la (L specularroughness, A opacity) and $textureSet_rgba (RGB user0, A "
        "opacity), infinite padding, PNG 16 and OpenEXR 32f.",
        "grid2x2",
        ["grid2x2", "field-a", "grey-a", "grey-b", *inputs],
        s,
    )


# --- R2: resize (R-090 P4, P8) ----------------------------------------------------------------

RESIZE_MAPS = [
    "documentMap/basecolor:RGB",
    "documentMap/user0:RGB",
    "documentMap/height:L",
    "virtualMap/Normal_OpenGL:RGB",
    "virtualMap/Normal_DirectX:RGB",
]
# Per texture set: (BaseColor, User0, filtering mode of the fill).
RESIZE_SETS: tuple[tuple[Any, str, str], ...] = (
    ("field-a", "pattern64", "Nearest"),
    ("field-a", "pattern64", "BilinearHQ"),
    ("impulse-texel", "impulse-texel", "Nearest"),
    ([0.8, 0.3, 0.1], "impulse-texel", "BilinearHQ"),
)


def export_resize() -> Golden:
    s = start("grid2x2")
    s.channels((("User0", "RGB16"),))
    s.add(ps.SET_RESOLUTIONS, width=256, height=128, texture_set="s1")
    res = s.imports("field-a", "pattern64", "impulse-texel", "height-ramps", "normal-a")
    for texture_set, (base, user, filtering) in zip(MESH_SETS["grid2x2"], RESIZE_SETS, strict=True):
        sources = {"BaseColor": base, "User0": user, "Height": "height-ramps", "Normal": "normal-a"}
        node = fill(s, sources, res, position="top", texture_set=texture_set)
        projection(s, node, filtering)
    for size in (6, 7, 9, 10):
        for container in (PNG16, EXR32F):
            export(s, RESIZE_MAPS, container, "infinite", size_log2=size)
    export(s, RESIZE_MAPS, PNG8, "infinite", size_log2=7)
    for size in (7, 9):
        export(s, RESIZE_MAPS, PNG16, "passthrough", size_log2=size)
    inputs = probes(s, "resize")
    return Golden(
        "export-resize",
        EXPORT_DOMAIN,
        "Export resize (recording plan R2, R-090 P4/P8, decision 100) on the 2x2 plane grid at "
        "256 px, s1 set to 256 x 128 per texture set: one fill per set with BaseColor, User0 "
        "(RGB16), Height (height ramps) and Normal (normal-a): s0 field A and the 64 px pattern, "
        "Nearest; s1 the same, BilinearHQ; s2 the impulse texel (one white texel at (100, 37)) "
        "on both, Nearest; s3 a uniform (0.8, 0.3, 0.1) and the impulse texel, BilinearHQ. "
        "sizeLog2 6, 7, 9, 10 (PNG 16 and OpenEXR 32f, infinite), PNG 8 at 7, passthrough at 7 "
        "and 9 (PNG 16); every export step done twice in the session. Probes: sizeLog2 as "
        "[9, 7], [7, 9], [8, 8], [8, 7], [7, 8], and sizeLog2 14 on s3's BaseColor (PNG 8).",
        "grid2x2",
        ["grid2x2", "field-a", "pattern64", "impulse-texel", "height-ramps", "normal-a", *inputs],
        s,
    )


# --- R3: dithering (R-090 P3) -------------------------------------------------------------------

DITHER_CHANNELS = (("User0", "RGB16"), ("User1", "L16F"), ("User2", "RGB32F"))
DITHER_FORMATS = (*DITHER_CHANNELS, ("BaseColor", "sRGB8"), ("Height", "L16F"))
DITHER_MAPS = [
    "documentMap/user0:RGB",
    "documentMap/user1:L",
    "documentMap/user2:RGB",
    "documentMap/basecolor:RGB",
    "documentMap/height:L",
    "virtualMap/Normal_OpenGL:RGB",
]


def export_dither() -> Golden:
    s = start("grid2x2")
    s.channels(DITHER_CHANNELS)
    res = s.imports("slow-ramp", "slow-ramp-grey", "height-ramps", "grey-a", "normal-a")
    channels = [c for c, _ in DITHER_FORMATS]
    sets = MESH_SETS["grid2x2"]
    fill(
        s,
        {c: grey_of(f, "slow-ramp", "slow-ramp-grey") for c, f in DITHER_FORMATS},
        res,
        position="top",
        texture_set=sets[0],
    )
    for texture_set, source, opacity in (
        (sets[1], "height-ramps", 0.05),
        (sets[2], "grey-a", 0.02),
    ):
        base = fill(
            s, {c: [0.5, 0.5, 0.5] for c in channels}, res, position="top", texture_set=texture_set
        )
        top = s.fill(channels, above_step=base)
        for channel in channels:
            s.bitmap(top, channel, res[source])
            s.blend(top, channel, "Normal", opacity)
    fill(s, {"Normal": "normal-a"}, res, position="top", texture_set=sets[3])
    export(s, DITHER_MAPS, PNG8, "infinite", dithering=True)
    export(s, DITHER_MAPS, PNG8, "infinite", dithering=False)
    export(s, DITHER_MAPS, PNG16, "infinite", dithering=True)
    export(s, DITHER_MAPS, PNG16, "infinite", dithering=False)
    export(s, DITHER_MAPS, EXR16F, "infinite", dithering=True)
    export(s, DITHER_MAPS, PNG8, "passthrough", dithering=True)
    return Golden(
        "export-dither",
        EXPORT_DOMAIN,
        "Export dithering (recording plan R3, R-090 P3, decision 100) on the 2x2 plane grid: "
        "s0 the authored slow ramps (a few 8-bit steps across the tile, and a staircase inside "
        "one step) on User0 (RGB16), User1 (L16F), User2 (RGB32F), BaseColor (sRGB8, the "
        "control) and Height (L16F); s1 the height ramps at opacity 0.05 over a uniform 0.5; "
        "s2 grey A at opacity 0.02 over a uniform 0.5; s3 normal-a on Normal. Dithering on and "
        "off at PNG 8 and PNG 16, on at OpenEXR 16f, on at PNG 8 with passthrough padding; "
        "every export step done twice in the session, so the same-session repeat and r2 "
        "classify whether dithering is deterministic.",
        "grid2x2",
        ["grid2x2", "slow-ramp", "slow-ramp-grey", "height-ramps", "grey-a", "normal-a"],
        s,
    )


# --- R4: bit depth and encoding (R-090 P1, P2, P7, P10) -------------------------------------

DEPTH_CHANNELS = (
    ("User0", "sRGB8"),
    ("User1", "RGB8"),
    ("User2", "L8"),
    ("User3", "RGB16"),
    ("User4", "L16"),
    ("User5", "RGB16F"),
    ("User6", "L16F"),
    ("User7", "RGB32F"),
    ("Opacity", "L32F"),
    ("Specular", "sRGB8"),
    ("Emissive", "sRGB8"),
)
# Every filled channel with its format (the project's own channels keep their template format;
# the letter decides L or RGB).
DEPTH_FORMATS = (
    *DEPTH_CHANNELS,
    ("BaseColor", "sRGB8"),
    ("SpecularRoughness", "L"),
    ("Height", "L16F"),
)
NOT_A_HALF = 0.1 + 2.0**-13
MESH_MAP_EXPORTS = [
    "meshMap/normal_base:RGB",
    "meshMap/ambient_occlusion:L",
    "meshMap/curvature:L",
    "meshMap/position:RGB",
]


def depth_maps() -> list[str]:
    maps = [
        f"documentMap/{channel.lower()}:{'L' if fmt.startswith('L') else 'RGB'}"
        for channel, fmt in DEPTH_FORMATS
    ]
    return [*maps, "documentMap/normal:RGB"]


def export_bit_depth() -> Golden:
    s = start("grid4x2")
    s.channels(DEPTH_CHANNELS)
    names = ["field-a", "grey-a", "grey-b", "half-steps", "half-steps-grey", "height-ramps"]
    res = s.imports(*names, "normal-a", "normal-a-8bit", "normal-b")
    for usage, source in (
        ("Normal", "normal-b"),
        ("AO", "grey-a"),
        ("Curvature", "grey-b"),
        ("Position", "field-a"),
    ):
        s.add(ps.SET_MESH_MAP, usage=usage, resource_step=res[source])
    sets = MESH_SETS["grid4x2"]
    channels = [c for c, _ in DEPTH_FORMATS]

    def per_format(rgb: Any, grey: Any) -> dict[str, Any]:
        return {c: grey if f.startswith("L") else rgb for c, f in DEPTH_FORMATS}

    fill(
        s,
        {**per_format("field-a", "grey-a"), "Normal": "normal-a"},
        res,
        position="top",
        texture_set=sets[0],
    )
    fill(s, per_format("half-steps", "half-steps-grey"), res, position="top", texture_set=sets[1])
    uniforms = {**per_format([0.8, 0.3, 0.1], [0.37] * 3), "Height": [NOT_A_HALF] * 3}
    fill(s, uniforms, res, position="top", texture_set=sets[2])
    node = s.fill(["Height"], position="top", texture_set=sets[3])
    s.bitmap(node, "Height", res["field-a"])
    s.blend(node, "Height", "Normal", 0.5)
    below = fill(s, {c: "height-ramps" for c in channels}, res, position="top", texture_set=sets[4])
    top = s.fill(channels, above_step=below)
    for channel in channels:
        s.bitmap(top, channel, res["height-ramps"])
        s.blend(top, channel, "LinearDodge", 1.0)
    node = s.fill(channels, position="top", texture_set=sets[5])
    for channel in channels:
        s.bitmap(node, channel, res["grey-a"])
        s.blend(node, channel, "SignedAddition", 1.0)
    fill(
        s,
        {**{c: [NOT_A_HALF] * 3 for c in channels}, "Normal": "normal-a-8bit"},
        res,
        position="top",
        texture_set=sets[6],
    )
    fill(
        s,
        {"BaseColor": "grey-a", "SpecularRoughness": "grey-a"},
        res,
        position="top",
        texture_set=sets[7],
    )
    maps = depth_maps()
    for container in (PNG8, PNG16, EXR16F, EXR32F):
        export(s, maps, container, "infinite")
    normals = ["virtualMap/Normal_OpenGL:RGB", "virtualMap/Normal_DirectX:RGB"]
    for container in (PNG8, PNG16, EXR16F):
        export(s, normals, container, "infinite")
    for container in (PNG8, PNG16, EXR16F, EXR32F):
        export(s, MESH_MAP_EXPORTS, container, "infinite")
    for container in (PNG16, EXR32F):
        export(s, MESH_MAP_EXPORTS, container, "passthrough")
    return Golden(
        "export-bit-depth",
        EXPORT_DOMAIN,
        "Bit depth and colour encoding of the export (recording plan R4, R-090 P1, P2, P7, P10, "
        "decision 100) on the 4x2 plane grid: one channel per format (User0 sRGB8, User1 RGB8, "
        "User2 L8, User3 RGB16, User4 L16, User5 RGB16F, User6 L16F, User7 RGB32F, Opacity "
        "L32F) and the sRGB8 material channels Specular and Emissive, with BaseColor, "
        "SpecularRoughness and Height; mesh maps normal-b (Normal), grey A (AO), grey B "
        "(Curvature), field A (Position). Per set (L channels take the grey fixture): s0 field "
        "A, Normal normal-a; s1 the half-step codes; s2 uniform (0.8, 0.3, 0.1) and 0.37, Height "
        "0.1 + 2^-13; s3 Height field A at 0.5; s4 the height ramps twice in LinearDodge (up to "
        "2); s5 grey A in SignedAddition onto the empty stack (down to -0.5); s6 uniform 0.1 + "
        "2^-13, Normal normal-a-8bit; s7 BaseColor and SpecularRoughness grey A (the rest "
        "empty). Every channel at PNG 8, PNG 16, OpenEXR 16f and 32f; Normal_OpenGL and "
        "Normal_DirectX at PNG 8, 16 and OpenEXR 16f; the four mesh maps at all four, and with "
        "passthrough at PNG 16 and OpenEXR 32f. Infinite padding, no dithering, every export "
        "step done twice in the session.",
        "grid4x2",
        ["grid4x2", *names, "normal-a", "normal-a-8bit", "normal-b"],
        s,
    )


# --- R5: OCIO colour encoding, with a Legacy twin ---------------------------------------------

OCIO_MAPS = [
    "documentMap/basecolor:RGB",
    "documentMap/specularroughness:L",
    "documentMap/basemetalness:L",
    "documentMap/height:L",
]
BASE_SRGB = [0.2, 0.5, 0.8]
# The wand stack's hammer-mark layer (Pipeline/painting stack-wand.json, I02): base [75, 70, 65]
# (0-255, sRGB), Height -0.003, BaseColor opacity 0.25, set as the sync script sets them.
WAND_BASE = [75 / 255, 70 / 255, 65 / 255]


def export_ocio_encode(ocio: bool) -> Golden:
    s = start("grid4x2")
    res = s.imports("srgb8-ramp", "grey-a")
    sets = MESH_SETS["grid4x2"]
    for texture_set, space in zip(sets[:3], ("sRGB", None, "Raw"), strict=True):
        node = s.fill(["BaseColor"], position="top", texture_set=texture_set)
        given = {} if space is None else {"color_space": space}
        s.add(ps.SET_SOURCE, node_step=node, channel="BaseColor", color=BASE_SRGB, **given)
    bitmaps: list[int] = []
    for texture_set, space in zip(sets[3:5], ("sRGB", "Raw"), strict=True):
        node = s.fill(["BaseColor"], position="top", texture_set=texture_set)
        s.add(
            ps.SET_SOURCE,
            node_step=node,
            channel="BaseColor",
            resource_step=res["srgb8-ramp"],
            color_space=space,
        )
        projection(s, node, "BilinearHQ", "RepeatNone")
        bitmaps.append(node)
    group = s.add(ps.INSERT_GROUP, position="top", texture_set=sets[5])
    child = s.fill(["BaseColor"], inside_step=group, stack="Substack")
    s.add(
        ps.SET_SOURCE,
        node_step=child,
        channel="BaseColor",
        resource_step=res["srgb8-ramp"],
        color_space="sRGB",
    )
    projection(s, child, "BilinearHQ", "RepeatNone")
    bitmaps.append(child)
    masked(s, group, res["grey-a"])
    channels = ["BaseColor", "SpecularRoughness", "BaseMetalness", "Height"]
    node = s.fill(channels, position="top", texture_set=sets[6])
    s.add(ps.SET_SOURCE, node_step=node, channel="BaseColor", color=WAND_BASE, color_space="sRGB")
    for channel, value in (("SpecularRoughness", 0.37), ("BaseMetalness", 0.8), ("Height", -0.003)):
        s.add(ps.SET_SOURCE, node_step=node, channel=channel, color=[value] * 3, color_space="Raw")
    s.add(ps.SET_OPACITY, node_step=node, opacity=0.25, channel="BaseColor")
    node = s.fill(channels[1:], position="top", texture_set=sets[7])
    for channel, value in (("SpecularRoughness", 0.37), ("BaseMetalness", 0.8), ("Height", 0.003)):
        s.add(ps.SET_SOURCE, node_step=node, channel=channel, color=[value] * 3)
    s.blend(node, "Height", "LinearDodge", 1.0)
    for bitmap in bitmaps:
        s.add(COLOUR_SPACES, node_step=bitmap, channel="BaseColor")
    export(s, OCIO_MAPS, PNG16, "infinite", repeat=False)
    export(s, OCIO_MAPS, PNG8, "infinite", repeat=False)
    export(s, ["documentMap/basecolor:RGB"], EXR32F, "infinite", repeat=False)
    export(s, ["virtualMap/Normal_OpenGL:RGB"], PNG16, "infinite", repeat=False)
    inputs = probes(s, "colour-space")
    mode = (
        "OCIO (Painter's substance config)" if ocio else "Legacy (the twin of export-ocio-encode)"
    )
    return Golden(
        "export-ocio-encode" + ("" if ocio else "-legacy"),
        "tier0/colour/ocio-encode",
        f"Colour encoding under {mode} (recording plan R5, decision 100), on a project created "
        "as the wand's painter_create.py creates it (no template, OpenGL, 256 px, the 4x2 plane "
        "grid): BaseColor uniform (0.2, 0.5, 0.8) as sRGB (s0), with no colour space (s1), as Raw "
        "(s2); the authored 8-bit sRGB ramp as a UV bitmap (BilinearHQ, no repeat) set to sRGB "
        "(s3), Raw (s4), and sRGB inside a group masked by grey A (s5); s6 the wand's hammer-mark "
        "layer as the sync script sets it (BaseColor (75, 70, 65)/255 sRGB at opacity 0.25, "
        "SpecularRoughness 0.37, BaseMetalness 0.8, Height -0.003, Raw); s7 the same scalars "
        "with no colour space, Height 0.003 in LinearDodge. Captures: each bitmap's available and "
        "current colour spaces. BaseColor, SpecularRoughness, BaseMetalness, Height at PNG 16 and "
        "PNG 8, BaseColor at OpenEXR 32f, Normal_OpenGL at PNG 16; probes with $colorSpace in "
        "the file names.",
        "grid4x2",
        ["grid4x2", "srgb8-ramp", "grey-a", *inputs],
        s,
        [OCIO_SETTING] if ocio else [],
    )


# --- R6/R7 with R8: export presets ----------------------------------------------------------

ALPHA_BLEND = "templates/PBR - Metallic Roughness Alpha-blend.spt"


def export_presets(ocio: bool) -> Golden:
    s = start("bevelled-cube", None if ocio else ALPHA_BLEND)
    res = s.imports("field-a", "grey-a", "grey-b", "height-ramps", "normal-a", "normal-b")
    s.add(ps.SET_MESH_MAP, usage="Normal", resource_step=res["normal-b"])
    s.add(ps.SET_MESH_MAP, usage="AO", resource_step=res["grey-a"])
    if ocio:
        sources = {
            "BaseColor": "field-a",
            "SpecularRoughness": "grey-a",
            "BaseMetalness": "grey-b",
            "Height": "height-ramps",
            "Normal": "normal-a",
        }
    else:
        sources = {
            "BaseColor": "field-a",
            "Roughness": "grey-a",
            "Metallic": "grey-b",
            "Height": "height-ramps",
            "Normal": "normal-a",
            "Opacity": "grey-a",
        }
    fill(s, sources, res, position="top", texture_set="uzp_bevelled_cube")
    s.add(PREDEFINED_PRESETS)
    s.add(RESOURCE_PRESETS)
    s.add(PREDEFINED_OUTPUT_MAPS, texture_set="uzp_bevelled_cube")
    for url in rf.STARTER_PRESETS.values():
        s.add(RESOURCE_OUTPUT_MAPS, preset=url)
    inputs = probes(s, "presets-bevelled-cube")
    template = (
        "no template (the pipeline's default OpenPBR channels BaseColor, SpecularRoughness, "
        "BaseMetalness, Height, Normal), under OCIO"
        if ocio
        else f"the shipped template {ALPHA_BLEND!r} (Roughness, Metallic, Opacity), under Legacy"
    )
    return Golden(
        "export-presets-" + ("ocio" if ocio else "legacy"),
        "tier0/export/presets",
        f"Export presets (recording plan R6/R7 with R8, decision 100) on the authored bevelled "
        f"cube at 256 px, OpenGL, {template}: normal-b bound as the Normal mesh map and grey A as "
        "AO; one fill with field A, grey A, grey B, the height ramps, normal-a (and grey A on "
        "Opacity). Captures: the predefined and resource export presets, every predefined "
        "preset's output maps on the set, and the output maps of the starter PBR Metallic "
        "Roughness and Blender (Principled BSDF) presets. Probes: each starter preset with its "
        "own parameters and with the pipeline's (PNG 16, infinite, no dithering); the Assets3D "
        "inline five-map preset (staff-v10 painter_export.py) at sizeLog2 8 and 7.",
        "bevelled-cube",
        [
            "bevelled-cube",
            "field-a",
            "grey-a",
            "grey-b",
            "height-ramps",
            "normal-a",
            "normal-b",
            *inputs,
        ],
        s,
        [OCIO_SETTING] if ocio else [],
        template=None if ocio else ALPHA_BLEND,
    )


# --- Decision 145: the sRGB bitmap uses still refused ------------------------------------------

SRGB_CHANNELS = (
    ("Emissive", "sRGB8"),
    ("User1", "RGB8"),
    ("User2", "L8"),
    ("User3", "RGB16"),
    ("User4", "L16"),
    ("User5", "RGB16F"),
    ("User7", "RGB32F"),
)
SRGB_MAPS = [
    "documentMap/basecolor:RGB",
    *(f"documentMap/{c.lower()}:{'L' if f.startswith('L') else 'RGB'}" for c, f in SRGB_CHANNELS),
]
# s1-s3: UV projection per set (filtering, scale, rotation, offset), wrap Repeat.
SRGB_RESAMPLING = (
    ("BilinearHQ", [2.0, 2.0], 30.0, [0.1, 0.2]),
    ("BilinearHQ", [0.5, 0.5], 0.0, [0.0, 0.0]),
    ("Nearest", [2.0, 2.0], 0.0, [0.0, 0.0]),
)
# s6-s8: the bitmap colour spaces outside the fitted Raw and sRGB (decision 156 names a Legacy
# space by its qualified member name).
SRGB_SPACES = ("Working", "LegacyColorSpace.Linear", "LegacyColorSpace.sRGB")


def srgb_bitmap_variants() -> Golden:
    s = start("grid3x3")
    s.channels(SRGB_CHANNELS)
    res = s.imports("srgb8-grey-ramp", "field-a", "srgb8-ramp", "grey-a")
    sets = MESH_SETS["grid3x3"]
    bitmaps: list[tuple[int, str | None]] = []

    def bitmap(node: int, channel: str, source: str, space: str) -> None:
        s.add(
            ps.SET_SOURCE,
            node_step=node,
            channel=channel,
            resource_step=res[source],
            color_space=space,
        )
        bitmaps.append((node, channel))

    node = s.fill(["BaseColor"], position="top", texture_set=sets[0])
    bitmap(node, "BaseColor", "srgb8-grey-ramp", "sRGB")
    for texture_set, (filtering, scale, rotation, offset) in zip(
        sets[1:4], SRGB_RESAMPLING, strict=True
    ):
        node = s.fill(["BaseColor", "Emissive"], position="top", texture_set=texture_set)
        bitmap(node, "BaseColor", "field-a", "sRGB")
        bitmap(node, "Emissive", "srgb8-ramp", "sRGB")
        s.add(
            ps.SET_PROJECTION,
            node_step=node,
            filtering_mode=filtering,
            uv_wrapping_mode="Repeat",
            scale_mode="Factors",
            scale=scale,
            rotation=rotation,
            offset=offset,
        )
    users = [(c, f) for c, f in SRGB_CHANNELS if c.startswith("User")]
    node = s.fill([c for c, _ in users], position="top", texture_set=sets[4])
    for channel, fmt in users:
        # Decision 160: Painter refused the sRGB bitmap space on User1 (RGB8); each user
        # channel's attempt is recorded (decision 166).
        source = grey_of(fmt, "field-a", "grey-a")
        s.add(ps.SET_SOURCE, node_step=node, channel=channel, resource_step=res[source])
        s.add(ps.SET_COLOR_SPACE, node_step=node, channel=channel, color_space="sRGB")
        bitmaps.append((node, channel))
    node = s.fill(["BaseColor"], position="top", texture_set=sets[5])
    s.add(ps.SET_SOURCE, node_step=node, channel="BaseColor", color=BASE_SRGB, color_space="sRGB")
    s.add(ps.ADD_MASK, node_step=node, background="Black")
    effect = s.add(ps.INSERT_FILL, inside_step=node, stack="Mask")
    s.bitmap(effect, None, res["grey-a"], effect=True)
    s.add(ps.SET_COLOR_SPACE, node_step=effect, channel=None, color_space="sRGB")
    bitmaps.append((effect, None))
    for texture_set, space in zip(sets[6:], SRGB_SPACES, strict=True):
        node = s.fill(["BaseColor"], position="top", texture_set=texture_set)
        bitmap(node, "BaseColor", "field-a", space)
    for bitmap_node, bitmap_channel in bitmaps:
        s.add(COLOUR_SPACES, node_step=bitmap_node, channel=bitmap_channel)
    for container in (PNG16, PNG8, EXR32F):
        export(s, SRGB_MAPS, container, "infinite")
    return Golden(
        "srgb-bitmap-variants-v2",
        "tier0/colour/srgb-bitmaps",
        "The sRGB bitmap uses decision 145 leaves refused (phase1.15_compositor-colour-fits item "
        "2.2, decisions 145, 156 and 166), under Legacy on the authored 3x3 plane grid (nine sets) "
        "at 256 px, Emissive added as sRGB8 and User1 RGB8, User2 L8, User3 RGB16, User4 L16, "
        "User5 RGB16F, User7 RGB32F. s0: the authored 8-bit grey ramp (column x holds code x) on "
        "BaseColor set to sRGB, default projection (1:1). s1-s3: field A (16-bit) on BaseColor "
        "and the 8-bit srgb8-ramp on Emissive, both set to sRGB, UV projection with wrap Repeat: "
        "BilinearHQ at scale (2, 2), rotation 30, offset (0.1, 0.2) (s1); BilinearHQ at scale "
        "(0.5, 0.5) (s2); Nearest at scale (2, 2) (s3). s4: User1, User3, User5 and User7 field A"
        " and the L channels User2 and User4 grey A (decision 048), each with set_color_space"
        "(sRGB) attempted (decision 166: Painter refused it on User1, decision 160; each "
        "channel's refusal is recorded). s5: "
        "BaseColor uniform (0.2, 0.5, 0.8) sRGB under a black mask whose fill effect's source is "
        "grey A, with set_color_space(sRGB) attempted on that source (decision 156: Painter's "
        "refusal, if it refuses, is recorded). s6-s8: field A on BaseColor set to Working, Legacy"
        " Linear and Legacy sRGB. Captures: get_color_space and list_available_color_spaces of "
        "every bitmap. BaseColor, Emissive and the six user channels at PNG 16, PNG 8 and OpenEXR"
        " 32f, infinite padding, no dithering, every export step done twice in the session.",
        "grid3x3",
        ["grid3x3", "srgb8-grey-ramp", "field-a", "srgb8-ramp", "grey-a"],
        s,
    )


# --- Decision 126: the linear bases of shipped templates ---------------------------------------

# One template per recorded PNG 16 code of an empty sRGB8 base: 48107 (Unreal Engine), 59397
# (the OpenPBR templates) and 14330 (the sRGB8 Specular templates).
INFERRED_BASE_TEMPLATES = (
    "templates/Unreal Engine.spt",
    "templates/OpenPBR - Anisotropy.spt",
    "templates/PBR - Specular Glossiness.spt",
)
# Decision 168: the shipped templates whose sRGB8 base no OpenEXR export shows yet (the empty
# BaseColor, or Specular for the sRGB8-Specular templates), one golden each.
REMAINING_BASE_TEMPLATES = (
    "templates/ASM - PBR Metallic Roughness.spt",
    "templates/ASM - PBR Metallic Roughness Anisotropy Angle.spt",
    "templates/ASM - PBR Metallic Roughness Coated.spt",
    "templates/ASM - PBR Metallic Roughness SSS.spt",
    "templates/ASM - PBR Metallic Roughness Sheen.spt",
    "templates/Blender.spt",
    "templates/Dota 2.spt",
    "templates/KeyShot.spt",
    "templates/Lens Studio.spt",
    "templates/Maxwell - Metallic Roughness.spt",
    "templates/Maxwell - Specular Glossiness.spt",
    "templates/Non-PBR - Specular Glossiness.spt",
    "templates/OpenPBR - Fuzz.spt",
    "templates/OpenPBR - Subsurface Scattering.spt",
    "templates/PBR - Metallic Roughness Alpha-test.spt",
    "templates/Roblox (MaterialVariant).spt",
    "templates/Roblox (SurfaceAppearance).spt",
    "templates/Spark AR Studio.spt",
    "templates/Unity HD Render Pipeline (Metallic Standard).spt",
    "templates/VrayMtl - Metallic Roughness.spt",
    "templates/VrayMtl - Specular Glossiness.spt",
)
TEMPLATE_BASE_MAPS = ["documentMap/basecolor:RGB", "documentMap/specular:RGB"]


def template_base(template: str) -> Golden:
    s = start("plane", template)
    export(s, TEMPLATE_BASE_MAPS, EXR32F, "infinite")
    export(s, TEMPLATE_BASE_MAPS, PNG16, "infinite")
    return Golden(
        f"export-template-base-{template_slug(template)}",
        "tier0/stack/base-values",
        "The linear value of an empty sRGB8 base (phase1.25_pilot-wand item 2.6, decision 126): "
        f"an empty project on the authored plane created with the shipped template {template}; "
        "BaseColor and Specular (Painter skips a map the template lacks) at OpenEXR 32f, and at "
        "PNG 16 as the control against the recorded base-values code; infinite padding, no "
        "dithering, every export step done twice in the session.",
        "plane",
        ["plane"],
        s,
        template=template,
    )


# --- Decision 129: padding probes P-ramp and P-tie ----------------------------------------------

USER0_MAP = ["documentMap/user0:RGB"]


def padding_probe(mesh: str, resolution: int, ramp: str) -> Sequence:
    """One fill with only User0 (RGB32F) active, the float UV ramp `ramp` at `resolution` as its
    source with the default projection (read back), Normal at opacity 1; User0 at OpenEXR 32f
    with infinite padding and with passthrough (the covered-texel control)."""
    s = start(mesh, resolution=resolution)
    s.channels((("User0", "RGB32F"),))
    res = s.imports(ramp)
    (texture_set,) = MESH_SETS[mesh]
    node = s.fill(["User0"], position="top", texture_set=texture_set)
    s.bitmap(node, "User0", res[ramp])
    s.blend(node, "User0", "Normal", 1.0)
    s.add(ps.GET_PROJECTION, node_step=node)
    export(s, USER0_MAP, EXR32F, "infinite")
    export(s, USER0_MAP, EXR32F, "passthrough")
    return s


RAMP_RATIOS = {"r1": "1", "r2": "2", "r15": "1.5"}
RAMP_SHIFTS = {"p0": "phase 0", "p25": "every UV shifted by +0.25/1024", "p75": "+0.75/1024"}
PROBE_TAIL = (
    "User0 added as RGB32F (the template capture of both recordings records its stored format; "
    "a record where it is not 32F is void); one fill with only User0 active, source the "
    "authored float32 UV ramp R = (x + 0.5)/N, G = (y + 0.5)/N, B = 0.5 at the document size, "
    "default projection (read back), Normal at opacity 1. User0 at OpenEXR 32f with infinite "
    "padding and with passthrough (every covered texel must equal the ramp bit for bit, or the "
    "probe is void), every export step done twice in the session."
)
# Decision 166: the re-authored probes' name suffix and the note on their ramp's file name.
V2 = "-v2"
RENAMED_RAMP_NOTE = (
    " Re-authored under a new name (decision 166): the ramp file is named uv-ramp-n<N>.exr, "
    "because Painter read the four-digit suffix of uv-ramp-1024 and uv-ramp-2048 as a UDIM "
    "tile and the first records were void (decision 160)."
)


def padding_ramp(mesh: str, phase: str, renamed: bool = False) -> Golden:
    name = f"seam-ramp-{mesh}-{phase}"
    resolution = rf.RAMP_RESOLUTION
    ramp = renamed_ramp(resolution) if renamed else f"uv-ramp-{resolution}"
    return Golden(
        f"export-padding-ramp-{mesh}-{phase}" + (V2 if renamed else ""),
        EXPORT_DOMAIN,
        "P-ramp of decision 129 (phase1.25_pilot-wand item 2.7: the ring across a UV seam), "
        f"exploratory: the seam mesh of scale ratio {RAMP_RATIOS[mesh]}, {RAMP_SHIFTS[phase]}, "
        "its OBJ the text decision 129 fixes by SHA-256; document resolution 1024. "
        + PROBE_TAIL
        + (RENAMED_RAMP_NOTE if renamed else ""),
        name,
        [name, ramp],
        padding_probe(name, resolution, ramp),
    )


def padding_tie(resolution: int, renamed: bool = False) -> Golden:
    ramp = renamed_ramp(resolution) if renamed else f"uv-ramp-{resolution}"
    return Golden(
        f"export-padding-tie-{resolution}" + (V2 if renamed else ""),
        EXPORT_DOMAIN,
        "P-tie of decision 129 (phase1.25_pilot-wand item 2.7: the propagation rule), "
        "exploratory: three axis-aligned UV islands of side 0.125 at (0.1875, 0.1875), "
        f"(0.6875, 0.1875) and (0.4375, 0.6875); document resolution {resolution}. "
        + PROBE_TAIL
        + (RENAMED_RAMP_NOTE if renamed else ""),
        "tie",
        ["tie", ramp],
        padding_probe("tie", resolution, ramp),
    )


def later_goldens() -> list[Golden]:
    """Requested goldens of later decisions (145, 126, 129, 168), in the order of the runbook,
    then the padding probes decision 160 voids under their new names (decision 166)."""
    return [
        srgb_bitmap_variants(),
        *(template_base(t) for t in INFERRED_BASE_TEMPLATES),
        *(template_base(t) for t in REMAINING_BASE_TEMPLATES),
        *(padding_ramp(m, p) for m in rf.RAMP_MESHES for p in rf.RAMP_PHASES),
        *(padding_tie(r) for r in rf.TIE_RESOLUTIONS),
        *(padding_ramp(m, p, renamed=True) for m in rf.RAMP_MESHES for p in rf.RAMP_PHASES),
        padding_tie(rf.TIE_RESOLUTIONS[1], renamed=True),
    ]


# Goldens that the Painter sessions of 2026-10-12 recorded and the store admitted (decisions
# 101, 160, 167, 172 and 180): their manifests live under the envelope's `manifests/`, and their
# requests are deleted.
ADMITTED = frozenset(
    {
        "export-bit-depth",
        "export-padding",
        "export-padding-bevelled-cube",
        "export-padding-sphere",
        "export-padding-seam-256",
        "export-padding-seam-field-256",
        "export-padding-seam-1024",
        "export-padding-seam-field-1024",
        "export-alpha-layouts",
        "export-resize",
        "export-dither",
        "export-ocio-encode-legacy",
        # Batch of decision 160 (Painter session of 2026-10-12, 21:00).
        "export-template-base-unreal-engine",
        "export-template-base-openpbr-anisotropy",
        "export-template-base-pbr-specular-glossiness",
        "export-padding-tie-512",
        "export-padding-tie-2048",
        *(
            f"export-padding-ramp-{m}-{p}"
            for m in ("r1", "r2", "r15")
            for p in ("p0", "p25", "p75")
        ),
        # Batch of decision 167 (Painter session of 2026-10-12, 21:27).
        "srgb-bitmap-variants-v2",
        *(
            f"export-padding-ramp-{m}-{p}-v2"
            for m in ("r1", "r2", "r15")
            for p in ("p0", "p25", "p75")
        ),
        "export-padding-tie-2048-v2",
        # Batch of decision 172 (Painter session of 2026-10-12, 21:42).
        *(f"export-template-base-{template_slug(t)}" for t in REMAINING_BASE_TEMPLATES),
        # Batch of decision 180 (Painter sessions of 2026-10-12, 22:00, OCIO then Legacy).
        "export-ocio-encode",
        "export-presets-ocio",
        "export-presets-legacy",
    }
)


def decision_100_goldens() -> list[Golden]:
    """Every golden of decision 100, in the order of the runbook (parity/RECORDER.md
    section 11)."""
    return [
        export_bit_depth(),
        export_padding(),
        export_padding_mesh("bevelled-cube"),
        export_padding_mesh("sphere"),
        *(export_padding_seam(r, field) for r in (256, 1024) for field in (False, True)),
        export_alpha_layouts(),
        export_resize(),
        export_dither(),
        export_presets(ocio=False),
        export_ocio_encode(ocio=False),
        export_ocio_encode(ocio=True),
        export_presets(ocio=True),
    ]


def all_goldens() -> list[Golden]:
    return [*decision_100_goldens(), *later_goldens()]


def requested_goldens() -> list[Golden]:
    """The requested goldens still waiting for their recording."""
    return [g for g in all_goldens() if g.name not in ADMITTED]


def admitted_goldens() -> list[Golden]:
    return [g for g in all_goldens() if g.name in ADMITTED]


def ocio_goldens() -> frozenset[str]:
    return frozenset(g.name for g in all_goldens() if OCIO_SETTING in g.settings)


# --- Manifests --------------------------------------------------------------------------------


def export_settings(golden: Golden) -> list[dict[str, Any]]:
    """The export parameters the steps apply, one entry per distinct value."""
    settings: list[dict[str, Any]] = []
    seen: set[tuple[str, Any]] = set()
    for step in golden.sequence.steps:
        if step["call"] != EXPORT:
            continue
        args = step["args"]
        for name, value in (
            (f"export.{args['file_format']}.bit_depth", args["bit_depth"]),
            ("export.padding", args["padding"]),
            ("export.dithering", args["dithering"]),
            ("export.dilation", args.get("dilation")),
            ("export.size_log2", args.get("size_log2")),
        ):
            if value is not None and (name, value) not in seen:
                seen.add((name, value))
                settings.append({"name": name, "value": value, "applied_by": "recorder_api"})
    return settings


def request_manifest(
    golden: Golden, hashes: dict[str, str], entry: dict[str, Any]
) -> dict[str, Any]:
    """The golden's public manifest under the envelope `entry`, private records empty."""
    create = golden.sequence.steps[0]["args"]
    settings: list[dict[str, Any]] = [
        {
            "name": "project.normal_map_format",
            "value": create["normal_map_format"],
            "applied_by": "recorder_api",
        },
        {
            "name": "texture_set.resolution",
            "value": create["default_texture_resolution"],
            "unit": "px",
            "applied_by": "recorder_api",
        },
    ]
    if golden.template is not None:
        settings.append(
            {"name": "project.template", "value": golden.template, "applied_by": "recorder_api"}
        )
    inputs = []
    for name in golden.inputs:
        kind, path, generate = fixture(name)
        provenance: dict[str, Any] = {"origin": "uzmigames_authored", "licence": "Apache-2.0"}
        if generate is not None:
            module = "request_fixtures.py" if name in REQUEST_FIXTURES else "fixtures.py"
            provenance["note"] = f"Generated by tools/parity/tier0_semantics/{module}."
        inputs.append(
            {
                "input_id": name,
                "kind": kind,
                "path": path,
                "sha256": hashes[name],
                "provenance": provenance,
            }
        )
    return {
        "schema": "uzpainter/parity/golden-public/1",
        "record_class": "public_manifest",
        "golden_id": f"{GOLDEN_PREFIX}/{golden.name}",
        "tier": "0",
        "domain": golden.domain,
        "description": golden.description,
        "inputs": inputs,
        "instruction_sequence": {
            "author": "UzmiGames",
            "interface": "substance_painter_documented_python_api",
            "steps": golden.sequence.steps,
        },
        "applied_settings": settings + export_settings(golden) + golden.settings,
        "expectations": [],
        "software": {
            "painter": {
                "product": "Adobe Substance 3D Painter",
                "version": str(entry["painter_version"]),
                "build_id": str(entry["painter_build"]),
            },
            "uzpainter_build_hash": None,
        },
        "private_records": [],
    }


def request_root(root: Path) -> Path:
    """The current envelope's root of requested goldens (a sibling of its `manifests/`)."""
    return manifest_root(current_envelope(root), root).parent / REQUESTS


def planned_requests(hashes: dict[str, str], root: Path) -> dict[Path, dict[str, Any]]:
    """Request path -> manifest of every requested golden, and manifest path -> manifest of every
    admitted one, under the current envelope."""
    entry = current_envelope(root)
    base = request_root(root) / "tier0" / "semantics"
    admitted = manifest_root(entry, root) / "tier0" / "semantics"
    planned = {
        base / f"{g.name}.json": request_manifest(g, hashes, entry) for g in requested_goldens()
    }
    planned |= {
        admitted / f"{g.name}.json": request_manifest(g, hashes, entry) for g in admitted_goldens()
    }
    return planned


def request_dir(root: Path) -> Path:
    return request_root(root) / "tier0" / "semantics"
