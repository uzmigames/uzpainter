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
and P-tie (decision 157), the other 21 inferred template bases (decision 168), decision 174's
sRGB bitmap minification and decision 169's L8 material channels, decision 210's ring-sign probes
and a position-encoded seam probe (decision 216), decision 225's sRGB minification on random
content, decision 266's kernel-code padding probes, decision 272's tie-order sweeps and decision
293's Normal mesh-map combination probe, decision 314's glTF preset recording R-314, and
decision 317's subnormal float32 probe.

Colour management: every golden runs under Legacy (Painter started without `OCIO`) except the
three that name `OCIO` in `applied_settings` (`export-ocio-encode`, `export-presets-ocio`,
`export-presets-gltf-ocio`), which run in a session started with Painter's
`resources/ocio/substance/config.ocio`.
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
    BLEND_FAMILIES,
    FIXTURE_DIR,
    FIXTURES,
    GOLDEN_PREFIX,
    MAPS_PER_EXPORT,
    Golden,
    Sequence,
    start,
    template_slug,
)
from tools.parity.tier0_semantics.current import resample_minifying
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
        "presets-gltf-bevelled-cube": rf.gltf_preset_probes("uzp_bevelled_cube"),
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


def held_out_generator(size: int) -> Generate:
    return lambda: rf.held_out_pattern(size)


for _size in rf.HELD_OUT_SIZES:
    REQUEST_FIXTURES[f"pattern{_size}"] = (
        "image",
        f"{FIXTURE_DIR}/bitmaps/pattern{_size}.png",
        held_out_generator(_size),
    )


def srgb8_random_generator(size: int) -> Generate:
    return lambda: rf.srgb8_random(size)


for _size in rf.SRGB8_RANDOM_SIZES:
    REQUEST_FIXTURES[f"srgb8-random-{_size}"] = (
        "image",
        f"{FIXTURE_DIR}/bitmaps/srgb8-random-{_size}.png",
        srgb8_random_generator(_size),
    )


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
# Decision 210's ring-sign probes (decision 216): tie with its mesh box centred at the origin
# (half-extent 16) and r1-p0 scaled to a box of largest extent 34.
REQUEST_FIXTURES["tie-box16"] = (
    "mesh",
    f"{FIXTURE_DIR}/meshes/tie-box16.obj",
    lambda: rf.tie(rf.TIE_BOX16_CENTRES),
)
REQUEST_FIXTURES["seam-ramp-r1-p0-box17"] = (
    "mesh",
    f"{FIXTURE_DIR}/meshes/seam-ramp-r1-p0-box17.obj",
    lambda: rf.ramp_seam("r1", "p0", rf.RAMP_BOX17_EXTENT),
)


# Decision 266's kernel-code probes: per resolution the one-hot classes, the codes and a UV ramp;
# the kernel atlas per resolution and moved.
def kernel_onehot_generator(size: int, part: str) -> Generate:
    return lambda: rf.kernel_onehot(size, part)


def kernel_code_generator(size: int, name: str) -> Generate:
    return lambda: rf.kernel_code(size, name)


def kernel_atlas_generator(size: int, moved: bool) -> Generate:
    return lambda: rf.kernel_atlas(size, moved)


def kernel_bitmaps(size: int) -> list[str]:
    """The fixture ids of User0-User7 in a kernel-code probe at `size` px: the one-hot parts,
    the UV ramp, the codes. No image stem ends in a number from 1001 up (decision 166)."""
    onehot = [f"kernel-onehot-{part}-n{size}" for part in rf.KERNEL_ONEHOT]
    codes = [f"kernel-code-{name}-n{size}" for name in rf.KERNEL_CODES]
    ramp = "uv-ramp-512" if size == 512 else renamed_ramp(size)
    return [*onehot, ramp, *codes]


def kernel_atlas_mesh(size: int, moved: bool = False) -> str:
    return f"kernel-atlas-n{size}" + ("-moved" if moved else "")


for _size in rf.KERNEL_RESOLUTIONS:
    for _part in rf.KERNEL_ONEHOT:
        REQUEST_FIXTURES[f"kernel-onehot-{_part}-n{_size}"] = (
            "image",
            f"{FIXTURE_DIR}/bitmaps/kernel-onehot-{_part}-n{_size}.exr",
            kernel_onehot_generator(_size, _part),
        )
    for _name in rf.KERNEL_CODES:
        REQUEST_FIXTURES[f"kernel-code-{_name}-n{_size}"] = (
            "image",
            f"{FIXTURE_DIR}/bitmaps/kernel-code-{_name}-n{_size}.exr",
            kernel_code_generator(_size, _name),
        )
REQUEST_FIXTURES[renamed_ramp(256)] = (
    "image",
    f"{FIXTURE_DIR}/bitmaps/{renamed_ramp(256)}.exr",
    uv_ramp_generator(256),
)
for _size, _moved in [*((n, False) for n in rf.ATLAS_RESOLUTIONS), (1024, True)]:
    REQUEST_FIXTURES[kernel_atlas_mesh(_size, _moved)] = (
        "mesh",
        f"{FIXTURE_DIR}/meshes/{kernel_atlas_mesh(_size, _moved)}.obj",
        kernel_atlas_generator(_size, _moved),
    )


# Decision 272's tie-order sweep meshes: two families of copies, each under three mesh boxes.
def tie_sweep_generator(family: str, box: str) -> Generate:
    return lambda: rf.tie_sweep(family, box)


def tie_sweep_mesh(family: str, box: str) -> str:
    return f"tie-sweep-{family}-{box}"


for _family in rf.SWEEP_FAMILIES:
    for _box in rf.SWEEP_BOXES:
        REQUEST_FIXTURES[tie_sweep_mesh(_family, _box)] = (
            "mesh",
            f"{FIXTURE_DIR}/meshes/{tie_sweep_mesh(_family, _box)}.obj",
            tie_sweep_generator(_family, _box),
        )


# Decision 278's concave seam-gate meshes: copies of one ratio-1 seam pair folded by swept angles.
def concave_fold_generator(probe: str) -> Generate:
    return lambda: rf.concave_fold(probe)


def concave_fold_mesh(probe: str) -> str:
    return f"concave-fold-{probe}"


for _probe in rf.FOLD_PROBES:
    REQUEST_FIXTURES[concave_fold_mesh(_probe)] = (
        "mesh",
        f"{FIXTURE_DIR}/meshes/{concave_fold_mesh(_probe)}.obj",
        concave_fold_generator(_probe),
    )


# Decision 289's far-side hinge meshes: copies of one ratio-1 seam pair bent along hinges.
REQUEST_FIXTURES["tau-prism"] = (
    "mesh",
    f"{FIXTURE_DIR}/meshes/tau-prism.obj",
    rf.tau_prism,
)


def hinge_generator(probe: str) -> Generate:
    return lambda: rf.hinge_probe(probe)


def hinge_mesh(probe: str) -> str:
    return f"hinge-{probe}"


for _probe in rf.HINGE_PROBES:
    REQUEST_FIXTURES[hinge_mesh(_probe)] = (
        "mesh",
        f"{FIXTURE_DIR}/meshes/{hinge_mesh(_probe)}.obj",
        hinge_generator(_probe),
    )
REQUEST_FIXTURES["window-side"] = (
    "mesh",
    f"{FIXTURE_DIR}/meshes/window-side.obj",
    rf.window_side,
)
# Decision 298's corner-reach mesh: copies of one island corner whose seam edges meet at V.
REQUEST_FIXTURES["corner-reach"] = (
    "mesh",
    f"{FIXTURE_DIR}/meshes/corner-reach.obj",
    rf.corner_reach,
)
# Decision 293's Normal mesh-map combination probe: the twin-set mesh and its four bitmaps.
REQUEST_FIXTURES["normal-combine"] = (
    "mesh",
    f"{FIXTURE_DIR}/meshes/normal-combine.obj",
    rf.combine_mesh,
)
for _name, _kind, _generate in (
    ("mesh-map", "image", rf.combine_mesh_map),
    ("height", "image", rf.combine_height),
    ("channel", "image", rf.combine_channel),
    ("mask", "mask", rf.combine_mask),
):
    REQUEST_FIXTURES[f"normal-combine-{_name}"] = (
        _kind,
        f"{FIXTURE_DIR}/bitmaps/normal-combine-{_name}.png",
        _generate,
    )


# Decision 317's subnormal probe: the lower and upper layers' float32 bitmaps.
def subnormal_generator(layer: str) -> Generate:
    return lambda: rf.subnormal_bitmap(layer)


for _layer in rf.SUBNORMAL_LAYERS:
    REQUEST_FIXTURES[f"subnormal-{_layer}"] = (
        "image",
        f"{FIXTURE_DIR}/bitmaps/subnormal-{_layer}.exr",
        subnormal_generator(_layer),
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
    "tie-box16": ["uzp_tie"],
    "seam-ramp-r1-p0-box17": ["uzp_seam"],
    **{kernel_atlas_mesh(n): ["uzp_kernel_atlas"] for n in rf.ATLAS_RESOLUTIONS},
    kernel_atlas_mesh(1024, moved=True): ["uzp_kernel_atlas"],
    **{tie_sweep_mesh(f, b): ["uzp_tie_sweep"] for f in rf.SWEEP_FAMILIES for b in rf.SWEEP_BOXES},
    **{concave_fold_mesh(p): ["uzp_concave_fold"] for p in rf.FOLD_PROBES},
    **{hinge_mesh(p): ["uzp_hinge"] for p in rf.HINGE_PROBES},
    "tau-prism": ["uzp_tau_prism"],
    "window-side": ["uzp_window_side"],
    "corner-reach": ["uzp_corner"],
    "normal-combine": list(rf.COMBINE_SETS),
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


# --- Decision 314: the glTF PBR Metal Roughness preset (recording R-314) ------------------


def export_presets_gltf(ocio: bool) -> Golden:
    """Recording R-314 (phase3.1_unreal-gltf-pbr-preset item 2.1): Painter's files, dry run and
    `list_output_maps()` for its glTF PBR Metal Roughness preset, every channel the shipped preset
    reads filled with a distinct source."""
    s = start("bevelled-cube", None if ocio else ALPHA_BLEND)
    added = (("AO", "L16"), ("SpecularWeight", "L8"))
    s.channels(((("Opacity", "L8"), ("EmissionColor", "sRGB8")) if ocio else ()) + added)
    res = s.imports(
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
    s.add(ps.SET_MESH_MAP, usage="Normal", resource_step=res["normal-b"])
    s.add(ps.SET_MESH_MAP, usage="AO", resource_step=res["grey-a"])
    sources = {
        "BaseColor": "field-a",
        "SpecularRoughness" if ocio else "Roughness": "grey-a",
        "BaseMetalness" if ocio else "Metallic": "grey-b",
        "Height": "height-ramps",
        "Normal": "normal-a",
        "Opacity": "hue-grid-grey",
        "EmissionColor": "field-b",
        "AO": "hue-grid-transposed-grey",
        "SpecularWeight": "grey-173",
    }
    fill(s, sources, res, position="top", texture_set="uzp_bevelled_cube")
    s.add(PREDEFINED_PRESETS)
    s.add(RESOURCE_PRESETS)
    s.add(PREDEFINED_OUTPUT_MAPS, texture_set="uzp_bevelled_cube")
    s.add(RESOURCE_OUTPUT_MAPS, preset=rf.GLTF_PRESET)
    inputs = probes(s, "presets-gltf-bevelled-cube")
    template = (
        "no template (the pipeline's default OpenPBR channels) with Opacity, EmissionColor, AO "
        "and SpecularWeight added, under OCIO"
        if ocio
        else f"the shipped template {ALPHA_BLEND!r} with AO and SpecularWeight added, under Legacy"
    )
    return Golden(
        "export-presets-gltf-" + ("ocio" if ocio else "legacy"),
        "tier0/export/presets",
        f"Recording R-314 (decision 314, phase3.1_unreal-gltf-pbr-preset item 2.1) on the "
        f"authored bevelled cube at 256 px, OpenGL, {template}: normal-b bound as the Normal mesh "
        "map and grey A as AO; one fill with field A on BaseColor, grey A on roughness, grey B on "
        "metalness, the height ramps, normal-a, the hue-grid grey on Opacity, field B on "
        "EmissionColor, the transposed hue-grid grey on AO and grey 173 on SpecularWeight. "
        "Captures: the predefined and resource export presets, every predefined preset's output "
        "maps on the set, and the output maps of the starter glTF PBR Metal Roughness preset. "
        "Probes: that preset with its own parameters and with the pipeline's (PNG 16, infinite, no "
        "dithering). Confirms or corrects every map of the shipped gltf-pbr-metal-roughness preset "
        "(assets/export-presets/), its channels, its name, its parameters and its URL.",
        "bevelled-cube",
        [
            "bevelled-cube",
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
            *inputs,
        ],
        s,
        [OCIO_SETTING] if ocio else [],
    )


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


def specularweight_base_probes() -> list[Golden]:
    """Observe an existing empty channel, not the export planner's absent-channel skip.

    A missing preset channel is skipped; an existing SpecularWeight channel currently
    fails evaluation with missing_base_value. These requests establish neither a fallback
    for absent channels nor a base outside the captured template/format combinations.
    """
    probes = []
    for template in (None, ALPHA_BLEND):
        template_name = "default" if template is None else "alpha-blend"
        for channel_format in ("L8", "L16", "L32F"):
            s = start("plane", template)
            s.channels((("SpecularWeight", channel_format),))
            maps = ["documentMap/specularweight:L"]
            export(s, maps, EXR32F, "infinite")
            export(s, maps, PNG16, "infinite")
            probes.append(
                Golden(
                    f"specularweight-empty-base-{template_name}-{channel_format.lower()}",
                    "tier0/stack/base-values",
                    "SpecularWeight empty-channel base (phase3.2_uze-uzmat-preset items "
                    "2.7 and 3.4): an empty plane at 256 px under Legacy, "
                    + ("no template" if template is None else f"template {template}")
                    + f", with SpecularWeight freshly added as {channel_format}; no inserted "
                    "layers or assigned sources. Export documentMap/specularweight:L twice "
                    "as OpenEXR 32f "
                    "and twice as PNG 16, infinite padding, no dithering; recorder repeats "
                    "exports after save and reopen. An absent channel remains a skipped "
                    "preset map; an existing channel with no observed base currently raises "
                    "missing_base_value. This capture does not authorise a fallback for "
                    "absent channels or other templates/formats.",
                    "plane",
                    ["plane"],
                    s,
                    template=template,
                )
            )
    return probes


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


def padding_sign_probes() -> list[Golden]:
    """Decision 210 section 5's two ring-sign probes and the position-encoded seam probe
    decision 211 section 5 points to (decision 216), each a P-ramp/P-tie sequence."""
    tie_ramp = "uv-ramp-512"
    ramp = renamed_ramp(rf.RAMP_RESOLUTION)
    box = (
        "Decision 210's bounding-box reading of the ring sign (phase1.25_pilot-wand item 2.7), "
        "exploratory: "
    )
    return [
        Golden(
            "export-padding-tie-512-box16",
            EXPORT_DOMAIN,
            box + "P-tie-dyadic-box, the P-tie UV islands with the three 10 cm quads moved to x in "
            "[-16, -6], [-5, 5] and [6, 16] cm (z in [-5, 5]), so that the mesh's bounding box is "
            "centred at the origin with half-extent 16; document resolution 512. The reading "
            "predicts the fixed sign (+u, +v) on every ring texel. " + PROBE_TAIL,
            "tie-box16",
            ["tie-box16", tie_ramp],
            padding_probe("tie-box16", 512, tie_ramp),
        ),
        Golden(
            "export-padding-ramp-r1-p0-box17",
            EXPORT_DOMAIN,
            box + "P-ramp-17, the P-ramp seam mesh of scale ratio 1 at phase 0 with its world "
            "positions scaled by 1.7, so that the bounding box is x 0..34 by z 0..17 cm "
            "(half-extent 17), UVs unchanged; document resolution 1024. The reading predicts a "
            "mixed sign on the ring, which is fixed on export-padding-ramp-r1-p0-v2. " + PROBE_TAIL,
            "seam-ramp-r1-p0-box17",
            ["seam-ramp-r1-p0-box17", ramp],
            padding_probe("seam-ramp-r1-p0-box17", rf.RAMP_RESOLUTION, ramp),
        ),
        Golden(
            "export-padding-seam-ramp-1024",
            EXPORT_DOMAIN,
            "The seam ring's taps and weights (decision 211, phase1.25_pilot-wand item 2.7), "
            "exploratory: the authored seam mesh of export-padding-seam-field-1024 (island A at "
            "scale 0.375 on the tile's left border, island B at scale 0.25 turned 90 degrees; B "
            "as on export-padding-ramp-r15-p0-v2, A 64 texels further left), with the float UV "
            "ramp in place of the field so that every ring value reads as a position; document "
            "resolution 1024. " + PROBE_TAIL,
            "seam",
            ["seam", ramp],
            padding_probe("seam", rf.RAMP_RESOLUTION, ramp),
        ),
    ]


# --- Decision 266: kernel-code padding probes --------------------------------------------------

KERNEL_CHANNELS = tuple(f"User{i}" for i in range(8))
KERNEL_MAPS = [f"documentMap/user{i}:RGB" for i in range(8)]
KERNEL_TAIL = (
    "User0-User7 added as RGB32F (a record whose template capture shows one of them not 32F is "
    "void); one fill with the eight channels active, Normal at opacity 1, default projection "
    "(read back), sources the authored float32 kernel code at the document size: User0-User2 "
    "one-hot the nine classes x mod 3 + 3 (y mod 3) of the texel (column x, row y from the top), "
    "User3 the UV ramp R = (x + 0.5)/N, G = (y + 0.5)/N, B = 0.5, User4 and User5 the periodic "
    "codes d and e (k/256, one 17 x 13 texel tile each), User6 (d + e)/2 and User7 1 - d. The "
    "eight maps at OpenEXR 32f with infinite padding and with passthrough (every covered texel "
    "must equal its source bit for bit, or the probe is void), every export step done twice in "
    "the session."
)


def kernel_probe(mesh: str, resolution: int) -> Sequence:
    """Decision 129's probe sequence with the kernel code: User0-User7 RGB32F, one fill with
    the eight bitmaps, the eight maps at OpenEXR 32f, infinite and passthrough."""
    s = start(mesh, resolution=resolution)
    s.channels(tuple((channel, "RGB32F") for channel in KERNEL_CHANNELS))
    bitmaps = kernel_bitmaps(resolution)
    res = s.imports(*bitmaps)
    (texture_set,) = MESH_SETS[mesh]
    node = s.fill(list(KERNEL_CHANNELS), position="top", texture_set=texture_set)
    for channel, bitmap in zip(KERNEL_CHANNELS, bitmaps, strict=True):
        s.bitmap(node, channel, res[bitmap])
        s.blend(node, channel, "Normal", 1.0)
    s.add(ps.GET_PROJECTION, node_step=node)
    export(s, KERNEL_MAPS, EXR32F, "infinite")
    export(s, KERNEL_MAPS, EXR32F, "passthrough")
    return s


# Decision 266's thirteen probes: golden suffix -> (mesh, resolution, what it holds).
KERNEL_PROBES: dict[str, tuple[str, int, str]] = {
    "atlas-512": (
        kernel_atlas_mesh(512),
        512,
        "the kernel atlas (single texels, pairs, gaps, L, blocks, rows and columns, a diamond, "
        "UV seam pairs at scale ratios 1, 1.25, 1.5 and 2, turned 0, 30 and 90 degrees, flat "
        "and folded, two cube corners and four pole fans), its mesh box exactly [-256, 256] cm",
    ),
    "atlas-1024": (kernel_atlas_mesh(1024), 1024, "the kernel atlas, the same texels at 1024 px"),
    "atlas-2048": (kernel_atlas_mesh(2048), 2048, "the kernel atlas, the same texels at 2048 px"),
    "atlas-1024-moved": (
        kernel_atlas_mesh(1024, moved=True),
        1024,
        "the kernel atlas at 1024 px with its positions scaled by 1.7 and offset by "
        "(3.1, 0, -2.3) cm, so that the box-normalised positions round",
    ),
    "tie-512": ("tie", 512, "the P-tie mesh of export-padding-tie-512"),
    "tie-2048": ("tie", 2048, "the P-tie mesh of export-padding-tie-2048-v2"),
    **{
        f"ramp-{m}-{p}": (
            f"seam-ramp-{m}-{p}",
            rf.RAMP_RESOLUTION,
            f"the P-ramp mesh of export-padding-ramp-{m}-{p}-v2 (scale ratio {RAMP_RATIOS[m]}, "
            f"{RAMP_SHIFTS[p]})",
        )
        for m, p in (("r1", "p0"), ("r2", "p0"), ("r2", "p25"), ("r15", "p0"), ("r15", "p25"))
    },
    "sphere-256": ("sphere", 256, "the UV sphere of export-padding-sphere"),
    "bevelled-cube-256": (
        "bevelled-cube",
        256,
        "the bevelled cube of export-padding-bevelled-cube",
    ),
}


def padding_kernel_probes() -> list[Golden]:
    """Decision 266's kernel-code probes: each ring texel's taps and weights, one by one."""
    return [
        Golden(
            f"export-padding-kernel-{name}",
            EXPORT_DOMAIN,
            "Decision 266's kernel-code probe (phase1.25_pilot-wand item 2.7: the infinite ring "
            f"tap by tap), exploratory: {what}; document resolution {resolution}. " + KERNEL_TAIL,
            mesh,
            [mesh, *kernel_bitmaps(resolution)],
            kernel_probe(mesh, resolution),
        )
        for name, (mesh, resolution, what) in KERNEL_PROBES.items()
    ]


# --- Decision 272: tie-order sweep probes -----------------------------------------------------

TIE_SWEEP_FAMILIES = {
    "strips": (
        "304 straight 8- and 16-texel strips (rows and columns, one quad each) whose ring "
        "texels' two diagonals tie: strips straddling the binades of the normalised and world "
        "positions along x and along z, k-ulp translations (k = 0..15) across and along at three "
        "bases, a y control, uniform and per-axis scales, and every diagonal, vertex rotation "
        "and face order"
    ),
    "seams": (
        "79 ratio-2 seam pairs (A 8 x 8 texels, B 4 x 4 turned 90 degrees, as the P-ramp r2) "
        "and 69 two-triangle fan V-gaps (pole-4's spoke): four turns at six positions, folds of "
        "90 and atan(4/3) degrees, k-ulp translations across and along, scales and vertex orders"
    ),
}
TIE_SWEEP_BOXES = {
    "centred": "mesh box exactly [-256, 256] cm in x and z and [-64, 64] in y",
    "offcentre": (
        "every vertex of the centred mesh moved by (256, 0, 256) cm (box [0, 512]): the same "
        "normalised positions reached through other rounding"
    ),
    "box320": (
        "the centred mesh with its box anchors at +-320 cm, so that the normalised binades no "
        "longer sit on world binades"
    ),
}


def padding_tie_sweep_probes() -> list[Golden]:
    """Decision 272's tie-order sweeps: many copies of one tie configuration, their 3D swept."""
    resolution = rf.SWEEP_RESOLUTION
    return [
        Golden(
            f"export-padding-tie-sweep-{family}-{box}",
            EXPORT_DOMAIN,
            "Decision 272's tie-order sweep (phase1.25_pilot-wand item 2.7: which of two equal "
            f"1/d shares leads the infinite ring's lerp chain), exploratory: {what}; {where}; "
            f"each copy its own 3D piece and UV island; document resolution {resolution}. "
            + KERNEL_TAIL,
            tie_sweep_mesh(family, box),
            [tie_sweep_mesh(family, box), *kernel_bitmaps(resolution)],
            kernel_probe(tie_sweep_mesh(family, box), resolution),
        )
        for family, what in TIE_SWEEP_FAMILIES.items()
        for box, where in TIE_SWEEP_BOXES.items()
    ]


# --- Decision 278: concave seam-gate probes ---------------------------------------------------

CONCAVE_FOLD_PROBES = {
    "fold": (
        "194 copies of one seam pair (A and B 4 x 4 texels at 1 cm per texel, B its own UV "
        "island turned 90 degrees): B folded concave about the seam from 6 to 16 degrees in "
        "0.25 degree steps with both quad diagonals, flat and convex controls (6 to 45 "
        "degrees), copies tilted 90 degrees about x and obliquely, and copies scaled by 0.5, 2 "
        "and 4"
    ),
    "shape": (
        "366 copies of the seam pair with six B shapes (depth 1, 2 or 4 texels, far edge "
        "sheared along the seam) whose seam-triangle apex sits 0, 1 or 2 heights along the "
        "seam from its midpoint, each folded concave from 6 to 36 degrees in 0.5 degree steps"
    ),
    "fine": (
        "306 copies of the base seam pair folded concave and convex by 9.75 to 10.25 degrees in "
        "0.01 degree steps, 9.951 to 10.05 degrees in 0.001 degree steps, and 20 to 178 degrees"
    ),
}


def padding_concave_fold_probes() -> list[Golden]:
    """Decision 278's concave seam-gate probes: where a concave fold stops the far taps."""
    resolution = rf.SWEEP_RESOLUTION
    return [
        Golden(
            f"export-padding-concave-{probe}",
            EXPORT_DOMAIN,
            "Decision 278's concave seam-gate probe (phase1.25_pilot-wand item 2.7: from which "
            "concave fold of a seam edge the infinite ring takes no far taps), exploratory: "
            f"{what}; each copy its own 3D piece, mesh box exactly [-256, 256] cm in x and z and "
            f"[-64, 64] in y; document resolution {resolution}. " + KERNEL_TAIL,
            concave_fold_mesh(probe),
            [concave_fold_mesh(probe), *kernel_bitmaps(resolution)],
            kernel_probe(concave_fold_mesh(probe), resolution),
        )
        for probe, what in CONCAVE_FOLD_PROBES.items()
    ]


# --- Decision 289: far-side hinge probes -------------------------------------------------------

HINGE_PROBES = {
    "far": (
        "148 copies of one seam pair (A and B 4 x 4 texels at 1 cm per texel, B its own UV "
        "island turned 90 degrees, folded 6 degrees convex about the seam) whose B is bent along "
        "a hinge beyond the far triangle, swept convex and concave from 2 to 30 degrees: the "
        "far triangle 0.4375 and 0.125 texel deep, two hinges deep, a sliver far triangle "
        "touching the seam's end, and a far-triangle depth sweep from 0.0625 to 0.5625 texel"
    ),
    "vary": (
        "186 copies of the hinged seam pair, the far-side hinge swept convex and concave from 2 "
        "to 30 degrees: across a UV seam, under a 1.5 stretched UV, behind a concave and a "
        "flat seam fold, with A bent next to the seam, and A bent twice so own taps lie two "
        "faces away"
    ),
    "single": (
        "216 copies: decision 278's seam pair folded concave from 0.5 to 9.5 degrees with both "
        "quad diagonals and convex from 0.5 to 9.5 degrees; the hinged seam pair with the other "
        "diagonal and tilted 37 degrees about (1, 2, 3); and far-side hinges of 9 to 11 degrees "
        "on both sides of decision 278's gate (9.935 inside its bracket), behind a 6 and a 20 "
        "degree convex seam, one and two hinges deep, with the 2 to 30 degree sweep behind the "
        "20 degree seam"
    ),
}


def padding_hinge_probes() -> list[Golden]:
    """Decision 289's far-side hinge probes: how a far tap beyond a hinge is measured."""
    resolution = rf.SWEEP_RESOLUTION
    return [
        Golden(
            f"export-padding-hinge-{probe}",
            EXPORT_DOMAIN,
            "Decision 289's far-side hinge probe (phase1.25_pilot-wand item 2.7: whether the "
            "infinite ring measures a far tap beyond a hinge of the far island rigidly or "
            f"unfolded), exploratory: {what}; each copy its own 3D piece, mesh box exactly "
            f"[-256, 256] cm in x and z and [-64, 64] in y; document resolution {resolution}. "
            + KERNEL_TAIL,
            hinge_mesh(probe),
            [hinge_mesh(probe), *kernel_bitmaps(resolution)],
            kernel_probe(hinge_mesh(probe), resolution),
        )
        for probe, what in HINGE_PROBES.items()
    ]


def padding_tau_prism_probe() -> Golden:
    """Decision 342's pending tau-side gate discriminator, kept separate from admitted probes."""
    return Golden(
        "export-padding-tau-prism",
        EXPORT_DOMAIN,
        "Decision 342 tau-side development probe (phase1.25_pilot-wand item 2.7), exploratory: "
        "32 open faceted prism sectors with a longitudinal UV seam; tau-side hinges cycle "
        "8, 12, 9.9 and 10.25 degrees across the 0.985 normal gate, both signs, diagonals and "
        "0.1875/0.3125 texel facet depths; 40 narrow far-chart controls sweep total tau/far "
        "angle 8/9.9/10/10.25/12 degrees, both signs, and seam-triangle depth "
        "0.0625/0.125/0.1875/0.3125 texel, with one far tap at seam endpoints. "
        "Disjoint copies, fixed mesh box "
        "[-256,256] x [-64,64] x [-256,256] cm; document resolution 512. " + KERNEL_TAIL,
        "tau-prism",
        ["tau-prism", *kernel_bitmaps(512)],
        kernel_probe("tau-prism", 512),
    )


def padding_window_side_probe() -> Golden:
    """Decision 289's window-side probe for decision 291: Painter's side of the far window when
    the far point lies on a window boundary in exact arithmetic."""
    resolution = rf.SWEEP_RESOLUTION
    return Golden(
        "export-padding-window-side",
        EXPORT_DOMAIN,
        "Decision 289's window-side probe for decision 291 (phase1.25_pilot-wand item 2.7: on "
        "which side of decision 275's far window boundary Painter puts a far point that lies on "
        "the boundary in exact arithmetic), exploratory: 144 flat seam pairs (A and B 4 x 4 cm "
        "at 1 texel per cm, separate UV islands) whose oblique island is turned by a "
        "Pythagorean angle (3-4-5, 5-12-13, 8-15-17, 7-24-25, both ways round and both signs), "
        "so that two ring texels' far points lie exactly on a u and a v window boundary while "
        "the written float32 UVs are not dyadic; B turned at two sub-texel box offsets of A, "
        "and A turned; each in three diagonal and vertex orders; each copy its own 3D piece, "
        "mesh box exactly [-256, 256] cm in x and z and [-64, 64] in y; document resolution "
        f"{resolution}. " + KERNEL_TAIL,
        "window-side",
        ["window-side", *kernel_bitmaps(resolution)],
        kernel_probe("window-side", resolution),
    )


# --- Decision 298: the corner-reach probe ------------------------------------------------------


def padding_corner_reach_probe() -> Golden:
    """Decision 298's corner-reach probe for decision 294 (a): how far a seam edge of another
    planar face reaches a ring texel beyond its end at a UV corner of the island."""
    resolution = rf.SWEEP_RESOLUTION
    return Golden(
        "export-padding-corner-reach",
        EXPORT_DOMAIN,
        "Decision 298's corner-reach probe for decision 294 (a) (phase1.25_pilot-wand item 2.7: "
        "whether a seam edge of another planar face, reached past its end at a UV corner of the "
        "island, reaches the ring texel within 1.0 texel when the seam edge meeting it there is "
        "gated, 1.15 otherwise, and decision 285's 1.78 when the two are collinear), "
        f"exploratory: {len(rf.corner_copies())} copies of one island corner (two triangles at "
        "1 texel per cm hinged 6 degrees, so that its two seam edges lie on different planar "
        "faces; their far islands are their own UV islands), the corner bent 90, 30, 10, 2, 1, "
        "0.25, 0.05 and 0 degrees, the target ring texel beside the first edge at 0.90 to 1.30 "
        "texel from the corner, the first edge's far island folded 20 degrees concave (gated), "
        "20 degrees convex (open, past the gate's dot product), 6 degrees convex (open) or "
        "absent (no seam), with and without covered texels, and the hinge 0 (one planar face), "
        "2 and 20 degrees; each copy its own 3D piece, mesh box exactly [-256, 256] cm in x and "
        f"z and [-64, 64] in y; document resolution {resolution}. " + KERNEL_TAIL,
        "corner-reach",
        ["corner-reach", *kernel_bitmaps(resolution)],
        kernel_probe("corner-reach", resolution),
    )


# --- Decision 293: the Normal mesh-map combination probe --------------------------------------

COMBINE_EXR_MAPS = [
    "virtualMap/Normal_OpenGL:RGB",
    "documentMap/height:L",
    "documentMap/normal:RGB",
]
COMBINE_BITMAPS = (
    "normal-combine-mesh-map",
    "normal-combine-height",
    "normal-combine-channel",
    "normal-combine-mask",
)


def ao_mixed_grid_probe() -> Golden:
    """R-131 (decision 131): R-086 already covers the full code grid. Pin identity UV and
    Nearest, pair PNG 8 and EXR 32f on the same fill, and isolate filtering with BilinearHQ."""
    s = start("grid2x2")
    s.channels((("AO", "L16"),))
    res = s.imports("grey-a", "grey-b")
    s.add(ps.SET_MESH_MAP, usage="AO", resource_step=res["grey-a"])
    maps = [
        "virtualMap/AO_Mixed:L",
        "documentMap/ambientOcclusion:L",
        "meshMap/ambient_occlusion:L",
    ]
    for index, (filtering, opacity) in enumerate(
        (
            ("Nearest", 0.5),
            ("Nearest", 0.75),
            ("Nearest", 1.0),
            ("BilinearHQ", 0.5),
        )
    ):
        node = s.fill(["AO"], texture_set=f"s{index}")
        s.bitmap(node, "AO", res["grey-b"])
        projection(s, node, filtering, "RepeatNone")
        s.blend(node, "AO", "Normal", opacity)
    export(s, maps, PNG8, "passthrough")
    export(s, maps, EXR32F, "passthrough")
    return Golden(
        "ao-mixed-grid",
        "tier0/ao-mixed/operator",
        "R-131 (decision 131, phase3.2_unreal-ue56-packed-preset item 2.10): the full "
        "256 x 256 mesh-map/channel code grid already present in R-086, now with identity "
        "UV projection and filtering explicit. On grid2x2, four full-UV sets at 256 px "
        "under Legacy, "
        "grey-a binds AO mesh-map code x and grey-b supplies channel code y (both authored "
        "PNG 16, code8 * 257), every pair 0..255 once per set. Each set has one AO L16 fill "
        "in Normal: s0/s1/s2 use Nearest at opacity 0.5/0.75/1; s3 uses BilinearHQ at "
        "opacity 0.5 as the sole filtering "
        "control against s0; scale 1, rotation 0, offset 0, RepeatNone throughout. "
        "After all edits, "
        "AO_Mixed, the AO channel and AO mesh map are exported twice immediately as PNG 8 "
        "and twice immediately as OpenEXR 32f, passthrough, no dithering. The same document "
        "and each set's fill pair the formats and expose source readbacks; s0/s3 are separate "
        "fills, differing only in filtering. Channel exports are "
        "observations, not assumed exact pre-write AO_Mixed operands. Recorder repeats "
        "the exports after save/close/reopen (r2). No operator result is presumed.",
        "grid2x2",
        ["grid2x2", "grey-a", "grey-b"],
        s,
    )


def ao_mixed_stability_probes() -> list[Golden]:
    """Expose float operands and observe L16 after three consecutive save/reopen cycles."""
    floating = ao_mixed_grid_probe()
    floating.name = "ao-mixed-grid-l32f"
    for step in floating.sequence.steps:
        if step["call"] == ps.ADD_CHANNEL:
            step["args"]["format"] = "L32F"
    floating.description = floating.description.replace("AO L16 fill", "AO L32F fill") + (
        " Float32 channel control for decision 131: expose the stored AO operand at "
        "opacity 0.5/0.75/1 with the same Nearest/BilinearHQ controls."
    )
    reopened = ao_mixed_grid_probe()
    reopened.name = "ao-mixed-grid-l16-reopen3"
    reopened.settings = [
        {"name": "recorder.reopen_count", "value": 3, "applied_by": "recorder_api"}
    ]
    reopened.description += (
        " Decision 131 stability control: repeat the full recording after each of three "
        "consecutive Full save/close/reopen cycles (r2, r3, r4), retaining all outputs."
    )
    return [floating, reopened]


def padding_normal_combine_probe() -> Golden:
    """Decision 276 item 5's recording: the float32 form (item 4 (b)) and the order (item 4 (c))
    of Painter's gutter combination of a bound Normal mesh map with the padded mesh-free normal,
    from two texture sets that differ only in the binding."""
    s = start("normal-combine")
    res = s.imports(*COMBINE_BITMAPS)
    mesh_set, _ = rf.COMBINE_SETS
    s.add(
        ps.SET_MESH_MAP,
        usage="Normal",
        resource_step=res["normal-combine-mesh-map"],
        texture_set=mesh_set,
    )
    for texture_set in rf.COMBINE_SETS:
        fill(s, {"Height": "normal-combine-height"}, res, position="top", texture_set=texture_set)
        patch = fill(
            s, {"Normal": "normal-combine-channel"}, res, position="top", texture_set=texture_set
        )
        masked(s, patch, res["normal-combine-mask"])
    export(s, COMBINE_EXR_MAPS, EXR32F, "infinite")
    export(s, ["virtualMap/Normal_OpenGL:RGB"], PNG16, "infinite")
    return Golden(
        "export-padding-normal-combine",
        EXPORT_DOMAIN,
        "Decision 293's Normal mesh-map combination probe (decision 276 item 5, "
        "phase1.25_pilot-wand item 2.7: how Painter combines a bound Normal mesh map with the "
        "padded mesh-free normal outside the islands), exploratory, under Legacy at 256 px, "
        "OpenGL. The authored mesh has two texture sets with the same UV layout, uzp_nc_mesh and "
        "uzp_nc_free, each four 48 x 48 texel islands centred in the quadrants of the tile, "
        "their borders on texel boundaries; the authored 16-bit Normal mesh map (per quadrant "
        "its own smooth field of normals tilted 10 to 45 degrees) is bound on uzp_nc_mesh only. "
        "On both sets: one fill with only Height active, the authored Height bitmap (flat, but "
        "a u v ramp on the two right-hand islands, constant on their top and left 24 texels), "
        "Normal at opacity 1; above it one fill with only Normal active, the authored "
        "Normal-channel bitmap (tilted 20 to 35 degrees), Normal at opacity 1, under a black "
        "mask whose fill effect is the authored mask (1 on the two bottom quadrants, 0 "
        "elsewhere). So uzp_nc_mesh holds the mesh map alone, with the Height ramp, with the "
        "channel patch and with both, and uzp_nc_free the same islands without the mesh map. "
        "Normal_OpenGL, Height and the Normal channel at OpenEXR 32f, and Normal_OpenGL at "
        "PNG 16, with infinite padding, no dithering, every export step done twice in the "
        "session.",
        "normal-combine",
        ["normal-combine", *COMBINE_BITMAPS],
        s,
    )


# --- Decision 317: Painter's handling of subnormal float32 operands --------------------------

SUBNORMAL_MODES = tuple(m for family in BLEND_FAMILIES.values() for m in family if m != "Disable")
SUBNORMAL_OPACITIES = (1.0, 0.7)
SUBNORMAL_MAPS = [*KERNEL_MAPS, "meshMap/normal_base:RGB"]
# A slot's role: a blend (mode, opacity) of the upper layer over the lower one, or a control
# holding one layer alone ("src" the upper, "acc" the lower).
SubnormalRole = tuple[str, float] | str


def subnormal_slots() -> list[tuple[str, str, SubnormalRole]]:
    """Decision 317's 64 (texture set, channel, role) slots of the 4x2 grid, in the order s0
    User0..User7, s1 User0..: s0 User0 the upper layer alone, s0 User1 the lower layer alone,
    then each of the 30 modes at opacity 1 and 0.7, then on s7 User6 and User7 the two
    controls again."""
    roles: list[SubnormalRole] = ["src", "acc"]
    roles += [(mode, opacity) for mode in SUBNORMAL_MODES for opacity in SUBNORMAL_OPACITIES]
    roles += ["src", "acc"]
    sets = MESH_SETS["grid4x2"]
    return [(sets[i // 8], KERNEL_CHANNELS[i % 8], role) for i, role in enumerate(roles)]


def blend_subnormal() -> Golden:
    """Decision 317: what Painter does with subnormal float32 operands, read through the blend
    stack, a single-layer control and a bound mesh map."""
    s = start("grid4x2")
    s.channels(tuple((channel, "RGB32F") for channel in KERNEL_CHANNELS))
    res = s.imports("subnormal-acc", "subnormal-src")
    s.add(ps.SET_MESH_MAP, usage="Normal", resource_step=res["subnormal-src"])
    slots = subnormal_slots()
    for texture_set in MESH_SETS["grid4x2"]:
        own = [(channel, role) for name, channel, role in slots if name == texture_set]
        lower = s.fill([c for c, r in own if r != "src"], position="top", texture_set=texture_set)
        projection(s, lower, "Nearest")
        for channel, role in own:
            if role != "src":
                s.bitmap(lower, channel, res["subnormal-acc"])
                s.blend(lower, channel, "Normal", 1.0)
        upper = s.fill([c for c, r in own if r != "acc"], above_step=lower)
        projection(s, upper, "Nearest")
        for channel, role in own:
            if role != "acc":
                mode, opacity = role if isinstance(role, tuple) else ("Normal", 1.0)
                s.bitmap(upper, channel, res["subnormal-src"])
                s.blend(upper, channel, mode, opacity)
    export(s, SUBNORMAL_MAPS, EXR32F, "passthrough", repeat=False)
    return Golden(
        "blend-subnormal-f32",
        "tier0/blend/subnormal",
        "Decision 317's subnormal probe (decision 313's finding: the GPU flushes subnormal "
        "float32 operands, the CPU reference keeps them), exploratory, under Legacy at 256 px on "
        "the 4x2 plane grid, User0-User7 RGB32F on every set. Two authored float32 OpenEXR "
        "bitmaps, the lower layer's and the upper layer's: R holds every ordered pair of 16 "
        "values (+0, -0, subnormals 2^-149, 3 2^-149, 2^-127, the largest and their negatives, "
        "FLT_MIN, FLT_MIN + 1 ulp, 1.5 FLT_MIN, -FLT_MIN, 0.25, 0.5, 1, -0.25), one pair per "
        "16 x 16 texel block; G per texel decision 313's operand classes (a subnormal, a normal "
        "in [FLT_MIN, 2 FLT_MIN), a value k/2^24); B normal values locating the block. Per set "
        "a lower fill (the lower bitmap, Normal at opacity 1) and an upper fill above it (the "
        "upper bitmap), both with Nearest filtering at scale 1. Per channel, the upper fill's "
        "mode and opacity: every blend mode but Disable at opacity 1 and 0.7, in order; s0 "
        "User0 and s7 User6 the upper fill alone (Normal at 1 on the empty stack), s0 User1 and "
        "s7 User7 the lower fill alone. The upper bitmap is also bound as the Normal mesh map of "
        "every set (no layer stack between import and export). User0-User7 and normal_base at "
        "OpenEXR 32f, passthrough padding, one export step.",
        "grid4x2",
        ["grid4x2", "subnormal-acc", "subnormal-src"],
        s,
    )


# --- Decision 174 item 6: bilinear minification of an sRGB bitmap ------------------------------

SRGB_MINIFY_SOURCES = ("srgb8-ramp", "field-a")
SRGB_MINIFY_FILTERS = ("BilinearHQ", "BilinearSharp")
SRGB_MINIFY_SCALES = (2.0, 4.0)


def srgb_minification_sequence(sources: tuple[str, ...]) -> Sequence:
    """Per source, per filter, per scale one fill on the next set of the 4x2 grid, BaseColor
    only, the source set to sRGB and UV-projected with Repeat at rotation 0; BaseColor exported
    at PNG 16, PNG 8 and OpenEXR 32f with infinite padding."""
    s = start("grid4x2")
    res = s.imports(*sources)
    sets = iter(MESH_SETS["grid4x2"])
    for source in sources:
        for filtering in SRGB_MINIFY_FILTERS:
            for scale in SRGB_MINIFY_SCALES:
                node = s.fill(["BaseColor"], position="top", texture_set=next(sets))
                s.add(
                    ps.SET_SOURCE,
                    node_step=node,
                    channel="BaseColor",
                    resource_step=res[source],
                    color_space="sRGB",
                )
                s.add(
                    ps.SET_PROJECTION,
                    node_step=node,
                    filtering_mode=filtering,
                    uv_wrapping_mode="Repeat",
                    scale_mode="Factors",
                    scale=[scale, scale],
                    rotation=0.0,
                    offset=[0.0, 0.0],
                )
    for container in (PNG16, PNG8, EXR32F):
        export(s, ["documentMap/basecolor:RGB"], container, "infinite")
    return s


def srgb_bitmap_minification() -> Golden:
    return Golden(
        "srgb-bitmap-minification",
        "tier0/colour/srgb-bitmaps",
        "Bilinear minification of an sRGB bitmap (phase1.15_compositor-colour-fits item 2.5, "
        "decision 174 item 6), under Legacy on the authored 4x2 plane grid at 256 px. One fill "
        "per set with only BaseColor (sRGB8) active, its source a bitmap set to sRGB, UV "
        "projection with wrap Repeat, rotation 0, offset (0, 0): the 8-bit srgb8-ramp on s0-s3 "
        "and field A (16-bit) on s4-s7; per source BilinearHQ at scale (2, 2) and (4, 4), then "
        "BilinearSharp at (2, 2) and (4, 4). BaseColor at PNG 16, PNG 8 and OpenEXR 32f, "
        "infinite padding, no dithering, every export step done twice in the session.",
        "grid4x2",
        ["grid4x2", *SRGB_MINIFY_SOURCES],
        srgb_minification_sequence(SRGB_MINIFY_SOURCES),
    )


# --- Decisions 219 and 225: Painter's sRGB8 mip filter on random content ------------------------

SRGB_MIP_SOURCES = tuple(f"srgb8-random-{size}" for size in rf.SRGB8_RANDOM_SIZES)


def srgb_bitmap_minification_random() -> Golden:
    return Golden(
        "srgb-bitmap-minification-random",
        "tier0/colour/srgb-bitmaps",
        "Painter's sRGB8 mip filter (phase1.15_compositor-colour-fits item 2.7, decisions 219 and "
        "225): srgb-bitmap-minification's layout on random content, whose mip chain differs "
        "between the candidate filters, where the ramp's does not. Under Legacy on the authored "
        "4x2 plane grid at 256 px. One fill per set with only BaseColor (sRGB8) active, its "
        "source a bitmap set to sRGB, UV projection with wrap Repeat, rotation 0, offset (0, 0): "
        "the 8-bit random 256 px bitmap on s0-s3 and the 8-bit random 512 px bitmap on s4-s7; "
        "per source BilinearHQ at scale (2, 2) and (4, 4), then BilinearSharp at (2, 2) and "
        "(4, 4), so that 4 and 8 bitmap texels fall on a set texel. BaseColor at PNG 16, PNG 8 "
        "and OpenEXR 32f, infinite padding, no dithering, every export step done twice in the "
        "session.",
        "grid4x2",
        ["grid4x2", *SRGB_MIP_SOURCES],
        srgb_minification_sequence(SRGB_MIP_SOURCES),
    )


# --- Decision 169: the export of an L8 material channel ----------------------------------------

L8_MATERIAL = ("BaseColor", "Specular", "Emissive")


def export_l8_material() -> Golden:
    s = start("grid2x2")
    s.add(ps.EDIT_CHANNEL, channel="BaseColor", format="L8")
    s.channels(tuple((channel, "L8") for channel in L8_MATERIAL[1:]))
    res = s.imports("grey-a", "srgb8-grey-ramp")
    sets = MESH_SETS["grid2x2"]
    for texture_set, source in zip(sets, ("grey-a", "srgb8-grey-ramp", [0.37] * 3), strict=False):
        fill(s, {c: source for c in L8_MATERIAL}, res, position="top", texture_set=texture_set)
    for container in (PNG8, PNG16, EXR32F):
        for layout in ("RGB", "L"):
            export(
                s, [f"documentMap/{c.lower()}:{layout}" for c in L8_MATERIAL], container, "infinite"
            )
    return Golden(
        "export-l8-material",
        EXPORT_DOMAIN,
        "The export of an L8 material channel (decision 169, release gap l8-material-channel-png: "
        "Painter's PNG 16 of Dota 2's empty L8 Specular holds (14330, 2570, 14330)), under Legacy "
        "on the authored 2x2 plane grid at 256 px: BaseColor edited to L8, Specular and Emissive "
        "added as L8. One fill per set with the three channels, Normal at opacity 1: grey A "
        "(16-bit) on s0, the authored 8-bit grey ramp (column x holds code x) on s1, a uniform "
        "0.37 on s2; s3 the empty stack (the base). The three maps as RGB and as L at PNG 8, "
        "PNG 16 and OpenEXR 32f (the linear control), infinite padding, no dithering, every "
        "export step done twice in the session.",
        "grid2x2",
        ["grid2x2", "grey-a", "srgb8-grey-ramp"],
        s,
    )


# --- Decision 084 item 5: a fresh, never fitted recording of axis-aligned minification ---------

# Per size, per user channel (scale [u, v], rotation in degrees, offset [u, v]): rotations that
# are multiples of 90 degrees, isotropic and anisotropic footprints (the major axis on u and on
# v), irregular offsets and a zero-offset case; no scale or offset of the fitted goldens
# (decision 078's plans, resample-uv-minify, resample-uv-impulse) is reused.
HELD_OUT_CHANNELS: dict[int, tuple[Any, ...]] = {
    128: (
        ([3.37, 3.37], 0.0, [0.0419, 0.7213]),
        ([7.19, 7.19], 90.0, [0.5821, 0.0263]),
        ([14.63, 5.29], 0.0, [0.2087, 0.4651]),
        ([5.29, 14.63], 180.0, [0.6967, 0.3119]),
        ([29.41, 29.41], 270.0, [0.1153, 0.8429]),
        ([11.03, 2.71], 0.0, [0.0, 0.0]),
        ([41.17, 13.39], 90.0, [0.3571, 0.5987]),
        ([9.53, 9.53], 0.0, [0.0, 0.0]),
    ),
    32: (
        ([9.61, 9.61], 0.0, [0.0263, 0.5821]),
        ([18.37, 18.37], 270.0, [0.4651, 0.2087]),
        ([42.13, 11.87], 0.0, [0.8429, 0.1153]),
        ([11.87, 42.13], 90.0, [0.3119, 0.6967]),
        ([71.03, 71.03], 180.0, [0.5987, 0.3571]),
        ([25.73, 8.93], 0.0, [0.0, 0.0]),
        ([123.7, 35.11], 270.0, [0.7331, 0.4073]),
        ([33.97, 33.97], 0.0, [0.0, 0.0]),
    ),
}


def resample_held_out(size: int) -> Golden:
    plan = HELD_OUT_CHANNELS[size]
    golden = resample_minifying(f"resample-uv-heldout-{size}px", f"pattern{size}", plan)
    channels = "; ".join(
        f"{s[0]:.6g}x{s[1]:.6g}"
        + (f" at {r:g} degrees" if r else "")
        + f", offset {o[0]:g}/{o[1]:g}"
        for s, r, o in plan
    )
    golden.description = (
        "Held-out axis-aligned bilinear minification (decision 084 item 5: a fresh recording, "
        "never fitted, at new scales, offsets and bitmap sizes, inside the supported domain of "
        "rotations by multiples of 90 degrees, square power-of-two bitmaps and square sets). "
        "Per user "
        f"channel (User0-User{len(plan) - 1}) one fill projecting the authored {size}x{size} "
        f"pattern at scale {channels}; BilinearHQ with repeat (s0), BilinearSharp with repeat "
        "(s1), BilinearHQ without repeat (s2), BilinearSharp without repeat (s3). RGB16 channels."
    )
    return golden


def later_goldens() -> list[Golden]:
    """Requested goldens of later decisions (145, 126, 129, 168), in the order of the runbook,
    then the padding probes decision 160 voids under their new names (decision 166), then
    decision 174's sRGB minification and decision 169's L8 material channels, then decision
    216's ring-sign and seam probes, then decision 225's sRGB minification on random content,
    then decision 266's kernel-code padding probes, then decision 272's tie-order sweeps, then
    decision 278's concave seam-gate probes and decision 289's far-side hinge and
    window-side probes, then decision 293's Normal mesh-map combination probe, then decision
    298's corner-reach probe, then decision 314's glTF preset recording (Legacy, then OCIO),
    then decision 317's subnormal probe."""
    return [
        srgb_bitmap_variants(),
        *(template_base(t) for t in INFERRED_BASE_TEMPLATES),
        *(template_base(t) for t in REMAINING_BASE_TEMPLATES),
        *(padding_ramp(m, p) for m in rf.RAMP_MESHES for p in rf.RAMP_PHASES),
        *(padding_tie(r) for r in rf.TIE_RESOLUTIONS),
        *(padding_ramp(m, p, renamed=True) for m in rf.RAMP_MESHES for p in rf.RAMP_PHASES),
        padding_tie(rf.TIE_RESOLUTIONS[1], renamed=True),
        srgb_bitmap_minification(),
        export_l8_material(),
        *(resample_held_out(size) for size in rf.HELD_OUT_SIZES),
        *padding_sign_probes(),
        srgb_bitmap_minification_random(),
        *padding_kernel_probes(),
        *padding_tie_sweep_probes(),
        *padding_concave_fold_probes(),
        *padding_hinge_probes(),
        padding_tau_prism_probe(),
        padding_window_side_probe(),
        padding_normal_combine_probe(),
        padding_corner_reach_probe(),
        export_presets_gltf(ocio=False),
        export_presets_gltf(ocio=True),
        blend_subnormal(),
        ao_mixed_grid_probe(),
        *ao_mixed_stability_probes(),
        *specularweight_base_probes(),
    ]


# Goldens that the Painter sessions of 2026-10-12, 2026-10-13 and 2026-10-19 recorded and the
# store admitted (decisions 101, 160, 167, 172, 180, 198, 216, 266, 272 and 278): their manifests
# live under the envelope's `manifests/`, and their requests are deleted.
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
        # Batch of decision 198 (Painter sessions of 2026-10-13, 00:02, Legacy).
        "srgb-bitmap-minification",
        "export-l8-material",
        "resample-uv-heldout-128px",
        "resample-uv-heldout-32px",
        # Decision 216 (Painter session of 2026-10-13, 01:38, Legacy).
        "export-padding-seam-ramp-1024",
        "export-padding-tie-512-box16",
        "export-padding-ramp-r1-p0-box17",
        # Decision 266's kernel-code probes (Painter session of 2026-10-19, 09:58, Legacy).
        *(f"export-padding-kernel-{name}" for name in KERNEL_PROBES),
        # Decision 272's tie-order sweeps (Painter session of 2026-10-19, 11:23, Legacy).
        *(
            f"export-padding-tie-sweep-{family}-{box}"
            for family in rf.SWEEP_FAMILIES
            for box in rf.SWEEP_BOXES
        ),
        # Decision 278's concave seam-gate probes (Painter sessions of 2026-10-19, 12:41 and
        # 12:51, Legacy).
        *(f"export-padding-concave-{probe}" for probe in CONCAVE_FOLD_PROBES),
        # Cleanup-proven recordings of 2026-10-20; plugin failure is a separate API request.
        "export-padding-hinge-far",
        "export-padding-hinge-vary",
        "export-padding-hinge-single",
        "export-padding-window-side",
        "export-padding-corner-reach",
        "export-padding-normal-combine",
        "blend-subnormal-f32",
        "ao-mixed-grid",
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
