"""The Tier 0 semantics corpus: fixtures, instruction sequences and public manifests.

Each golden is one throwaway Painter project built by a UzmiGames instruction sequence over the
recorder vocabulary (documented API only, `parity/RECORDER.md` §2) and exported at 16 bit (PNG)
or float (OpenEXR, 32-bit). Goldens that compare several configurations use a grid mesh with one
texture set per configuration, so one project carries a whole sweep. Coverage of
`04-layer-stack-and-compositing.md` §9 is `COVERAGE` (item -> domains of the goldens).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT
from tools.parity.tier0_semantics import fixtures

PAINTER_BUILD = "12.1.0+js-api.1.1.20"
RESOLUTION = 256
FIXTURE_DIR = "parity/fixtures/tier0-semantics"
MANIFEST_DIR = "parity/manifests/tier0/semantics"
GOLDEN_PREFIX = "tier0/semantics"
PLANE_PATH = "parity/fixtures/meshes/plane.obj"
FILTER_SEARCH = "s:starterassets u:filter n:Blur="

# Project templates shipped with Painter 12.1.0, by shelf-relative identifier: the names the
# recorder's `project.create` `template` argument accepts, as listed by the
# phase0.6_tier0-defaults-templates manifest.
TEMPLATES = (
    "templates/ASM - PBR Metallic Roughness Anisotropy Angle.spt",
    "templates/ASM - PBR Metallic Roughness Coated.spt",
    "templates/ASM - PBR Metallic Roughness SSS.spt",
    "templates/ASM - PBR Metallic Roughness Sheen.spt",
    "templates/ASM - PBR Metallic Roughness.spt",
    "templates/Blender.spt",
    "templates/Dota 2.spt",
    "templates/KeyShot.spt",
    "templates/Lens Studio.spt",
    "templates/Maxwell - Metallic Roughness.spt",
    "templates/Maxwell - Specular Glossiness.spt",
    "templates/Non-PBR - Specular Glossiness.spt",
    "templates/OpenPBR - Anisotropy.spt",
    "templates/OpenPBR - Coat.spt",
    "templates/OpenPBR - Fuzz.spt",
    "templates/OpenPBR - Subsurface Scattering.spt",
    "templates/PBR - Metallic Roughness Alpha-blend.spt",
    "templates/PBR - Metallic Roughness Alpha-test.spt",
    "templates/PBR - Specular Glossiness.spt",
    "templates/Roblox (MaterialVariant).spt",
    "templates/Roblox (SurfaceAppearance).spt",
    "templates/Spark AR Studio.spt",
    "templates/Unity HD Render Pipeline (Metallic Standard).spt",
    "templates/Unreal Engine.spt",
    "templates/VrayMtl - Metallic Roughness.spt",
    "templates/VrayMtl - Specular Glossiness.spt",
)

USER = tuple(f"User{i}" for i in range(8))

# Authored inputs: id -> (kind, repository path, generator; None for an existing fixture).
FIXTURES: dict[str, tuple[str, str, Callable[[], bytes] | None]] = {
    "plane": ("mesh", PLANE_PATH, None),
    "grid2x2": ("mesh", f"{FIXTURE_DIR}/meshes/grid2x2.obj", lambda: fixtures.grid(2, 2)),
    "grid4x2": ("mesh", f"{FIXTURE_DIR}/meshes/grid4x2.obj", lambda: fixtures.grid(4, 2)),
    "grid6x4": ("mesh", f"{FIXTURE_DIR}/meshes/grid6x4.obj", lambda: fixtures.grid(6, 4)),
    "sphere": ("mesh", f"{FIXTURE_DIR}/meshes/sphere.obj", fixtures.sphere),
    "bevelled-cube": ("mesh", f"{FIXTURE_DIR}/meshes/bevelled-cube.obj", fixtures.bevelled_cube),
    "field-a": ("image", f"{FIXTURE_DIR}/bitmaps/field-a.png", fixtures.field_a),
    "field-b": ("image", f"{FIXTURE_DIR}/bitmaps/field-b.png", fixtures.field_b),
    "grey-a": ("image", f"{FIXTURE_DIR}/bitmaps/grey-a.png", fixtures.grey_a),
    "grey-b": ("image", f"{FIXTURE_DIR}/bitmaps/grey-b.png", fixtures.grey_b),
    "mask-codes": ("mask", f"{FIXTURE_DIR}/bitmaps/mask-codes.png", fixtures.mask_codes),
    "pattern64": ("image", f"{FIXTURE_DIR}/bitmaps/pattern64.png", fixtures.pattern64),
    "impulse64": ("image", f"{FIXTURE_DIR}/bitmaps/impulse64.png", fixtures.impulse64),
    "height-ramps": ("image", f"{FIXTURE_DIR}/bitmaps/height-ramps.png", fixtures.height_ramps),
    "hue-grid": ("image", f"{FIXTURE_DIR}/bitmaps/hue-grid.png", fixtures.hue_grid),
    "hue-grid-transposed": (
        "image",
        f"{FIXTURE_DIR}/bitmaps/hue-grid-transposed.png",
        lambda: fixtures.hue_grid(transposed=True),
    ),
    "hue-grid-grey": (
        "image",
        f"{FIXTURE_DIR}/bitmaps/hue-grid-grey.png",
        lambda: fixtures.hue_grid(grey=True),
    ),
    "hue-grid-transposed-grey": (
        "image",
        f"{FIXTURE_DIR}/bitmaps/hue-grid-transposed-grey.png",
        lambda: fixtures.hue_grid(transposed=True, grey=True),
    ),
    "normal-a": (
        "image",
        f"{FIXTURE_DIR}/bitmaps/normal-a.png",
        lambda: fixtures.normal_field("a"),
    ),
    "normal-b": (
        "image",
        f"{FIXTURE_DIR}/bitmaps/normal-b.png",
        lambda: fixtures.normal_field("b"),
    ),
    "normal-a-8bit": (
        "image",
        f"{FIXTURE_DIR}/bitmaps/normal-a-8bit.png",
        lambda: fixtures.normal_field("a", bits=8),
    ),
    # Recording requests R-091 and R-092 (decision 093): the grid whose file name holds two dots
    # (`$mesh` is the staged input's stem), the constant greys of AO_Mixed's isolation, and the
    # authored environment of the Iray procedure for the View_2D view-state probes.
    "grid2x2.dotted": (
        "mesh",
        f"{FIXTURE_DIR}/meshes/grid2x2.dotted.obj",
        lambda: fixtures.grid(2, 2),
    ),
    **{
        f"grey-{code:03d}": (
            "image",
            f"{FIXTURE_DIR}/bitmaps/grey-{code:03d}.png",
            (lambda c: lambda: fixtures.constant_grey(c))(code),
        )
        for code in fixtures.AO_CONSTANTS
    },
    "sky-patch": ("environment", "parity/fixtures/render-procedure/sky-patch.exr", None),
}


# The export probes' configurations (recording request R-085, decision 087): one authored
# `recipe_json` input per probe, `probe-<group>-<probe>`.
def probe_fixture(group: str, probe: str) -> Callable[[], bytes]:
    return lambda: fixtures.export_probe(group, probe)


for _group, _probes in fixtures.export_probes().items():
    for _probe in _probes:
        FIXTURES[f"probe-{_group}-{_probe}"] = (
            "recipe_json",
            f"{FIXTURE_DIR}/export-probes/{_group}/{_probe}.json",
            probe_fixture(_group, _probe),
        )

MESH_SETS = {
    "plane": ["uzp_plane"],
    "sphere": ["uzp_sphere"],
    "bevelled-cube": ["uzp_bevelled_cube"],
}
for _columns, _rows in ((2, 2), (4, 2), (6, 4)):
    MESH_SETS[f"grid{_columns}x{_rows}"] = [f"s{i}" for i in range(_columns * _rows)]

# 04 section 9 items, as worded there, -> domains of the goldens covering them. The coverage test
# reads the section and checks that every item is here or in `OWNED_ELSEWHERE`.
COVERAGE: dict[str, tuple[str, ...]] = {
    "Blend formulas and spaces": (
        "tier0/blend/modes",
        "tier0/blend/normal-channel",
        "tier0/blend/inputs",
        "tier0/blend/order",
        "tier0/colour/uniform-ramps",
    ),
    "quantisation points": ("tier0/quantisation/thirds", "tier0/colour/uniform-ramps"),
    "stack base values": ("tier0/stack/base-values",),
    "mask precision (8 vs 16 bit)": ("tier0/mask/precision",),
    "group `Normal`/`PassThrough` semantics with masks": ("tier0/group/masks",),
    "content-effect order": ("tier0/effects/order",),
    "levels clamp behaviour": ("tier0/levels/clamp",),
    "the `BilinearHQ` kernel": ("tier0/resample/uv",),
    "height→normal methods and strength scaling": ("tier0/height-normal/default-method",),
    "the `AO_Mixed` operator": ("tier0/ao-mixed/operator",),
}

# 04 section 9 items another Phase 0 task records (not part of this task's spec).
OWNED_ELSEWHERE = {
    "API readback rules (set→get, mask `None`, insertion errors)": "phase0.6_tier0-api-probes",
}

BLEND_FAMILIES = {
    "basic": (
        "Normal",
        "Replace",
        "Disable",
        "Multiply",
        "Divide",
        "InverseDivide",
        "Darken",
        "Lighten",
    ),
    "additive": (
        "LinearDodge",
        "Subtract",
        "InverseSubtract",
        "Difference",
        "Exclusion",
        "SignedAddition",
        "Screen",
        "LinearBurn",
    ),
    "contrast": (
        "Overlay",
        "ColorBurn",
        "ColorDodge",
        "SoftLight",
        "HardLight",
        "VividLight",
        "LinearLight",
        "PinLight",
    ),
    "component": (
        "Tint",
        "Saturation",
        "Color",
        "Value",
        "NormalMapCombine",
        "NormalMapDetail",
        "NormalMapInverseDetail",
    ),
}

# Blend sweep channels: (channel, format, top-layer opacity, colour or grey source).
BLEND_CHANNELS = (
    ("User0", "RGB16", 1.0, "rgb"),
    ("User1", "RGB16", 0.5, "rgb"),
    ("User2", "sRGB8", 1.0, "rgb"),
    ("User3", "sRGB8", 0.5, "rgb"),
    ("User4", "RGB8", 1.0, "rgb"),
    ("User5", "RGB16F", 1.0, "rgb"),
    ("User6", "L16", 1.0, "grey"),
    ("User7", "RGB32F", 0.25, "rgb"),
)

# Every ChannelFormat member on one channel (quantisation and base values).
FORMAT_CHANNELS = (
    ("User0", "sRGB8"),
    ("User1", "RGB8"),
    ("User2", "RGB16"),
    ("User3", "RGB16F"),
    ("User4", "RGB32F"),
    ("User5", "L8"),
    ("User6", "L16"),
    ("User7", "L16F"),
    ("Scattering", "L32F"),
)

# An instruction argument holds at most 16 scalars (golden-public.json).
MAPS_PER_EXPORT = 16
FLOAT_FORMATS = frozenset({"L16F", "RGB16F", "L32F", "RGB32F"})
DOCUMENT_MAPS = (
    "basecolor",
    "height",
    "specular",
    "opacity",
    "emissive",
    "displacement",
    "glossiness",
    "roughness",
    "anisotropylevel",
    "anisotropyangle",
    "transmissive",
    "scattering",
    "reflection",
    "ior",
    "metallic",
    "normal",
    "ambientOcclusion",
    "diffuse",
    "specularlevel",
    "blendingmask",
)


class Sequence:
    """Instruction steps numbered 1..n."""

    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []

    def add(self, call: str, **args: Any) -> int:
        self.steps.append({"step": len(self.steps) + 1, "call": call, "args": args})
        return len(self.steps)

    def channels(self, plan: tuple[tuple[str, str], ...]) -> None:
        for channel, channel_format in plan:
            self.add(ps.ADD_CHANNEL, channel=channel, format=channel_format)

    def imports(self, *inputs: str) -> dict[str, int]:
        return {name: self.add(ps.IMPORT_RESOURCE, input=name, usage="TEXTURE") for name in inputs}

    def fill(self, channels: list[str], **position: Any) -> int:
        node = self.add(ps.INSERT_FILL, **(position or {"position": "top"}))
        self.add(ps.SET_ACTIVE_CHANNELS, node_step=node, channels=channels)
        return node

    def bitmap(
        self, node: int, channel: str | None, resource_step: int, effect: bool = False
    ) -> None:
        call = ps.SET_EFFECT_SOURCE if effect else ps.SET_SOURCE
        self.add(call, node_step=node, channel=channel, resource_step=resource_step)

    def colour(self, node: int, channel: str, rgb: list[float], space: str = "Working") -> None:
        self.add(ps.SET_SOURCE, node_step=node, channel=channel, color=rgb, color_space=space)

    def blend(self, node: int, channel: str | None, mode: str, opacity: float) -> None:
        self.add(ps.SET_BLENDING_MODE, node_step=node, blending_mode=mode, channel=channel)
        self.add(ps.SET_OPACITY, node_step=node, opacity=opacity, channel=channel)

    def export(self, maps: list[str], floating: bool, png_depth: int = 16) -> None:
        for first in range(0, len(maps), MAPS_PER_EXPORT):
            self.export_step(maps[first : first + MAPS_PER_EXPORT], floating, png_depth)

    def export_step(self, maps: list[str], floating: bool, png_depth: int = 16) -> None:
        """OpenEXR 32f, or PNG at `png_depth` bits (16, or 8 for Painter's own 8-bit write)."""
        self.add(
            EXPORT,
            maps=maps,
            file_format="exr" if floating else "png",
            bit_depth="32f" if floating else png_depth,
            padding="infinite",
            dithering=False,
        )

    def export_channels(self, plan: tuple[tuple[str, str], ...]) -> None:
        """PNG 16 for integer formats, OpenEXR 32f for float formats; L or RGB by format."""
        for floating in (False, True):
            maps = [
                f"documentMap/{channel.lower()}:{'L' if fmt.startswith('L') else 'RGB'}"
                for channel, fmt in plan
                if (fmt in FLOAT_FORMATS) == floating
            ]
            self.export(maps, floating)


@dataclass
class Golden:
    name: str
    domain: str
    description: str
    mesh: str
    inputs: list[str]
    sequence: Sequence
    settings: list[dict[str, Any]] = field(default_factory=list)
    template: str | None = None


def start(
    mesh: str,
    template: str | None = None,
    normal_map_format: str = "OpenGL",
    resolution: int = RESOLUTION,
) -> Sequence:
    sequence = Sequence()
    args: dict[str, Any] = {
        "mesh": mesh,
        "normal_map_format": normal_map_format,
        "default_texture_resolution": resolution,
    }
    if template is not None:
        args["template"] = template
    sequence.add(ps.CREATE, **args)
    return sequence


def blend_modes(family: str, modes: tuple[str, ...]) -> Golden:
    s = start("grid4x2")
    plan = tuple((c, f) for c, f, _, _ in BLEND_CHANNELS)
    s.channels(plan)
    res = s.imports("field-a", "field-b", "grey-a", "grey-b")
    channels = [c for c, *_ in BLEND_CHANNELS]
    for texture_set, mode in zip(MESH_SETS["grid4x2"], modes, strict=False):
        lower = s.fill(channels, position="top", texture_set=texture_set)
        for channel, _, _, kind in BLEND_CHANNELS:
            s.bitmap(lower, channel, res["field-a" if kind == "rgb" else "grey-a"])
        upper = s.fill(channels, above_step=lower)
        for channel, _, opacity, kind in BLEND_CHANNELS:
            s.bitmap(upper, channel, res["field-b" if kind == "rgb" else "grey-b"])
            s.blend(upper, channel, mode, opacity)
    s.export_channels(plan)
    mapping = ", ".join(f"s{i} {m}" for i, m in enumerate(modes))
    return Golden(
        f"blend-{family}",
        "tier0/blend/modes",
        f"Blend-mode sweep ({family}): per texture set ({mapping}) a lower fill with the authored "
        "16-bit fields A (RGB) / grey A and an upper fill with fields B / grey B in the set's "
        "mode, on eight user channels covering the formats RGB16, sRGB8, RGB8, RGB16F, L16 and "
        "RGB32F at upper opacities 1, 0.5 and 0.25 (04 section 3). Sets without a mode keep the "
        "empty stack.",
        "grid4x2",
        ["grid4x2", "field-a", "field-b", "grey-a", "grey-b"],
        s,
    )


def blend_inputs() -> Golden:
    """Each input field alone, as Painter stores it: the calibration of the blend sweeps."""
    s = start("grid2x2")
    plan = tuple((c, f) for c, f, _, _ in BLEND_CHANNELS)
    s.channels(plan)
    res = s.imports("field-a", "field-b", "grey-a", "grey-b")
    channels = [c for c, *_ in BLEND_CHANNELS]
    for texture_set, (rgb, grey, opacity) in zip(
        MESH_SETS["grid2x2"],
        (("field-a", "grey-a", 1.0), ("field-b", "grey-b", 1.0), ("field-a", "grey-a", 0.5)),
        strict=False,
    ):
        node = s.fill(channels, position="top", texture_set=texture_set)
        for channel, _, _, kind in BLEND_CHANNELS:
            s.bitmap(node, channel, res[rgb if kind == "rgb" else grey])
            s.blend(node, channel, "Normal", opacity)
    s.export_channels(plan)
    return Golden(
        "blend-inputs",
        "tier0/blend/inputs",
        "Blend-sweep inputs alone on the blend channels: s0 fields A, s1 fields B, s2 fields A "
        "at opacity 0.5 over the base, s3 the empty stack.",
        "grid2x2",
        ["grid2x2", "field-a", "field-b", "grey-a", "grey-b"],
        s,
    )


def blend_normal_channel() -> Golden:
    s = start("grid2x2")
    res = s.imports("normal-a", "normal-b")
    for texture_set, mode in zip(
        MESH_SETS["grid2x2"],
        ("Normal", "NormalMapCombine", "NormalMapDetail", "NormalMapInverseDetail"),
        strict=True,
    ):
        lower = s.fill(["Normal"], position="top", texture_set=texture_set)
        s.bitmap(lower, "Normal", res["normal-a"])
        upper = s.fill(["Normal"], above_step=lower)
        s.bitmap(upper, "Normal", res["normal-b"])
        s.blend(upper, "Normal", mode, 1.0)
    s.export(["documentMap/normal:RGB"], floating=True)
    s.export(["virtualMap/Normal_OpenGL:RGB"], floating=False)
    return Golden(
        "blend-normal-channel",
        "tier0/blend/normal-channel",
        "Normal-map blend modes on the Normal channel: authored tangent-space fields A under B "
        "in Normal (s0), NormalMapCombine (s1), NormalMapDetail (s2) and NormalMapInverseDetail "
        "(s3); the Normal channel (OpenEXR 32f) and the Normal_OpenGL virtual map (PNG 16).",
        "grid2x2",
        ["grid2x2", "normal-a", "normal-b"],
        s,
    )


def blend_order() -> Golden:
    """Asymmetric three-layer stacks: the order of evaluation (04 section 2)."""
    s = start("grid2x2")
    plan = (("User0", "RGB16"), ("User1", "sRGB8"))
    s.channels(plan)
    res = s.imports("field-a", "field-b")
    channels = ["User0", "User1"]
    layers = {
        "A": ("field-a", "Normal", 1.0),
        "B": ("field-b", "Subtract", 0.8),
        "C": (None, "Divide", 0.6),
    }
    orders = ("ABC", "BAC", "ACB", "CBA")
    for texture_set, order in zip(MESH_SETS["grid2x2"], orders, strict=True):
        below: int | None = None
        for key in order:
            source, mode, opacity = layers[key]
            node = (
                s.fill(channels, position="top", texture_set=texture_set)
                if below is None
                else s.fill(channels, above_step=below)
            )
            for channel in channels:
                if source is None:
                    s.colour(node, channel, [0.6, 0.3, 0.9])
                else:
                    s.bitmap(node, channel, res[source])
                s.blend(node, channel, mode, opacity)
            below = node
    s.export_channels(plan)
    return Golden(
        "blend-order",
        "tier0/blend/order",
        "Evaluation order: three layers A (fields A, Normal, 1.0), B (fields B, Subtract, 0.8) "
        "and C (uniform working colour 0.6/0.3/0.9, Divide, 0.6) stacked bottom-up as ABC (s0), "
        "BAC (s1), ACB (s2) and CBA (s3) on RGB16 and sRGB8 channels.",
        "grid2x2",
        ["grid2x2", "field-a", "field-b"],
        s,
    )


THIRDS_COLOURS = (
    ([0.2, 0.7, 0.123], [0.9, 0.05, 0.5], [0.333, 0.1, 0.8]),
    ([1.0, 0.0, 0.5], [0.0, 1.0, 0.25], [0.5, 0.5, 1.0]),
    ([0.01, 0.02, 0.03], [0.99, 0.98, 0.97], [0.4, 0.6, 0.45]),
    ([0.75, 0.25, 0.6], [0.3, 0.85, 0.15], [0.05, 0.45, 0.95]),
)


def quantisation_thirds() -> Golden:
    s = start("grid2x2")
    s.channels(FORMAT_CHANNELS)
    channels = [c for c, _ in FORMAT_CHANNELS]
    for texture_set, colours in zip(MESH_SETS["grid2x2"], THIRDS_COLOURS, strict=True):
        below: int | None = None
        for rgb in colours:
            node = (
                s.fill(channels, position="top", texture_set=texture_set)
                if below is None
                else s.fill(channels, above_step=below)
            )
            for channel in channels:
                s.colour(node, channel, rgb)
                s.blend(node, channel, "Normal", 1.0 / 3.0)
            below = node
    s.export_channels(FORMAT_CHANNELS)
    return Golden(
        "quantisation-thirds",
        "tier0/quantisation/thirds",
        "Quantisation points (04 section 4): three uniform fills at opacity 1/3 in Normal mode, "
        "on one channel per ChannelFormat member (sRGB8, RGB8, RGB16, RGB16F, RGB32F, L8, L16, "
        "L16F, L32F), with a different colour triplet per texture set.",
        "grid2x2",
        ["grid2x2"],
        s,
    )


def ramp_values() -> list[float]:
    values = [k / 255.0 for k in range(256)]
    values += [(k + 0.5) / 255.0 for k in range(0, 256, 8)]
    return values


def colour_ramps(space: str) -> Golden:
    s = start("grid6x4")
    plan = tuple((USER[i], "RGB16" if i < 4 else "sRGB8") for i in range(8))
    s.channels(plan)
    values = ramp_values()
    for index, texture_set in enumerate(MESH_SETS["grid6x4"]):
        node = s.fill(list(USER), position="top", texture_set=texture_set)
        for k in range(4):
            start_at = index * 12 + k * 3
            rgb = [round(v, 12) for v in values[start_at : start_at + 3]]
            s.colour(node, USER[k], rgb, space)
            s.colour(node, USER[k + 4], rgb, space)
    s.export_channels(plan)
    return Golden(
        f"colour-ramps-{space.lower()}",
        "tier0/colour/uniform-ramps",
        f"Uniform-colour ramp in the documented colour space {space}: 288 values (k/255 for "
        "k = 0..255 and (k + 0.5)/255 for every eighth k), three per channel, spread over 24 "
        "texture sets, each value on an RGB16 channel (User0-3) and an sRGB8 channel (User4-7), "
        "for the transfer-function fit (04 section 4).",
        "grid6x4",
        ["grid6x4"],
        s,
    )


def base_values(template: str | None, name: str) -> Golden:
    s = start("plane", template)
    if template is not None:
        # A template's own channels only: adding one it already has is refused. Painter skips
        # the requested maps a template lacks and refuses an export that writes nothing, so
        # each export also carries the documented constant map `defaultMap/white`.
        maps = [f"documentMap/{m}:RGB" for m in DOCUMENT_MAPS]
        maps += [f"documentMap/user{i}:RGB" for i in range(8)]
        half = (len(maps) + 1) // 2
        for part in (maps[:half], maps[half:]):
            s.export_step([*part, "defaultMap/white:L"], floating=False)
        return Golden(
            f"base-values-{name}",
            "tier0/stack/base-values",
            "Stack base values (04 section 2 step 1): empty project on the authored plane "
            f"created with the shipped template {template}; every documented document map and "
            "user channel 0-7 requested with no layer in the stack (Painter writes the ones "
            "the template has), plus the constant white default map.",
            "plane",
            ["plane"],
            s,
            template=template,
        )
    s.channels(FORMAT_CHANNELS)
    users = {c.lower() for c, _ in FORMAT_CHANNELS}
    documents = [f"documentMap/{m}:RGB" for m in DOCUMENT_MAPS if m.lower() not in users]
    added = [
        f"documentMap/{c.lower()}:{'L' if f.startswith('L') else 'RGB'}"
        for c, f in FORMAT_CHANNELS
        if f not in FLOAT_FORMATS
    ]
    # Painter skips the maps a template lacks and refuses an export that writes nothing, so
    # every PNG export also carries channels this sequence added.
    half = (len(documents) + 1) // 2
    s.export_step(documents[:half] + added[:3], floating=False)
    s.export_step(documents[half:] + added[3:], floating=False)
    s.export_channels(tuple((c, f) for c, f in FORMAT_CHANNELS if f in FLOAT_FORMATS))
    return Golden(
        f"base-values-{name}",
        "tier0/stack/base-values",
        "Stack base values (04 section 2 step 1): empty project on the authored plane created "
        "with no template (Painter's default), one channel added per ChannelFormat member, "
        "every documented document map requested with no layer in the stack.",
        "plane",
        ["plane"],
        s,
        template=template,
    )


def mask_precision() -> Golden:
    s = start("grid2x2")
    plan = (
        ("User0", "RGB16"),
        ("User1", "L16"),
        ("User2", "RGB32F"),
        ("User3", "sRGB8"),
        ("User4", "L8"),
    )
    s.channels(plan)
    res = s.imports("mask-codes", "grey-b")
    channels = [c for c, _ in plan]
    variants = (
        ("White", 1.0, False),
        ("Black", 1.0, False),
        ("Black", 0.5, False),
        ("Black", 1.0, True),
    )
    for texture_set, (background, opacity, second) in zip(
        MESH_SETS["grid2x2"], variants, strict=True
    ):
        under = s.fill(channels, position="top", texture_set=texture_set)
        for channel in channels:
            s.colour(under, channel, [1.0, 1.0, 1.0])
        node = s.fill(channels, above_step=under)
        for channel in channels:
            s.colour(node, channel, [0.0, 0.0, 0.0])
        s.add(ps.ADD_MASK, node_step=node, background=background)
        effect = s.add(ps.INSERT_FILL, inside_step=node, stack="Mask")
        s.bitmap(effect, None, res["mask-codes"], effect=True)
        s.blend(effect, None, "Normal", opacity)
        if second:
            extra = s.add(ps.INSERT_FILL, above_step=effect)
            s.bitmap(extra, None, res["grey-b"], effect=True)
            s.blend(extra, None, "Multiply", 1.0)
    s.export_channels(plan)
    return Golden(
        "mask-precision",
        "tier0/mask/precision",
        "Mask precision (8 vs 16 bit): a black uniform fill over a white one, the black fill "
        "masked by a mask fill effect whose source is the authored grey bitmap holding every "
        "16-bit code once (output 1 - mask); s0 White background, "
        "s1 Black, s2 Black with the mask effect at opacity 0.5, s3 Black with a second mask "
        "effect (grey B, Multiply). Channels RGB16, L16, RGB32F, sRGB8 and L8.",
        "grid2x2",
        ["grid2x2", "mask-codes", "grey-b"],
        s,
    )


def group_masks() -> Golden:
    s = start("grid2x2")
    plan = (("User0", "RGB16"), ("User1", "sRGB8"), ("User2", "RGB32F"))
    s.channels(plan)
    res = s.imports("field-a", "field-b", "grey-a", "grey-b")
    channels = [c for c, _ in plan]
    # Painter 12.1.0's runtime BlendingMode has no PassThrough member although the python-doc
    # lists it, so the pass-through case is the group's default mode (read back as a default).
    variants = ((None, False), ("Normal", False), (None, True), ("Normal", True))
    for texture_set, (mode, masked) in zip(MESH_SETS["grid2x2"], variants, strict=True):
        base = s.fill(channels, position="top", texture_set=texture_set)
        for channel in channels:
            s.bitmap(base, channel, res["field-a"])
        group = s.add(ps.INSERT_GROUP, above_step=base)
        for channel in channels:
            if mode is not None:
                s.add(ps.SET_BLENDING_MODE, node_step=group, blending_mode=mode, channel=channel)
            s.add(ps.SET_OPACITY, node_step=group, opacity=0.75, channel=channel)
        child = s.fill(channels, inside_step=group, stack="Substack")
        for channel in channels:
            s.bitmap(child, channel, res["field-b"])
            s.blend(child, channel, "Multiply", 1.0)
        top = s.fill(channels, above_step=child)
        for channel in channels:
            s.colour(top, channel, [0.2, 0.9, 0.5])
            s.blend(top, channel, "Screen", 0.5)
        if masked:
            for node, source in ((group, "grey-a"), (child, "grey-b")):
                s.add(ps.ADD_MASK, node_step=node, background="Black")
                effect = s.add(ps.INSERT_FILL, inside_step=node, stack="Mask")
                s.bitmap(effect, None, res[source], effect=True)
    s.export_channels(plan)
    return Golden(
        "group-masks",
        "tier0/group/masks",
        "Group semantics: fields A at the root, above it a group at opacity 0.75 holding fields "
        "B (Multiply) under a uniform 0.2/0.9/0.5 fill (Screen, 0.5). s0 group in its default "
        "mode (Painter's pass-through default; the runtime BlendingMode has no PassThrough "
        "member to set), s1 group Normal, s2 and s3 the same with a mask on the group (grey A) "
        "and on the Multiply child (grey B). Channels RGB16, sRGB8 and RGB32F.",
        "grid2x2",
        ["grid2x2", "field-a", "field-b", "grey-a", "grey-b"],
        s,
    )


EFFECT_ORDERS = ("FLB", "FBL", "LFB", "LBF", "BFL", "BLF", "L", "B")


def effect_order() -> Golden:
    s = start("grid4x2")
    plan = (("User0", "RGB16"), ("User1", "sRGB8"))
    s.channels(plan)
    res = s.imports("field-a")
    channels = [c for c, _ in plan]
    for texture_set, order in zip(MESH_SETS["grid4x2"], EFFECT_ORDERS, strict=True):
        layer = s.fill(channels, position="top", texture_set=texture_set)
        for channel in channels:
            s.bitmap(layer, channel, res["field-a"])
        below: int | None = None
        for key in order:
            position = (
                {"inside_step": layer, "stack": "Content"}
                if below is None
                else {"above_step": below}
            )
            if key == "F":
                below = s.add(ps.INSERT_FILL, **position)
                s.add(ps.SET_EFFECT_CHANNELS, node_step=below, channels=channels)
                for channel in channels:
                    s.add(
                        ps.SET_EFFECT_SOURCE,
                        node_step=below,
                        channel=channel,
                        color=[0.8, 0.2, 0.4],
                        color_space="Working",
                    )
                    s.blend(below, channel, "Multiply", 0.7)
            elif key == "L":
                for channel in channels:
                    below = s.add(ps.INSERT_LEVELS, **position)
                    position = {"above_step": below}
                    s.add(ps.SET_LEVELS_CHANNEL, node_step=below, channel=channel)
                    s.add(
                        ps.SET_LEVELS,
                        node_step=below,
                        input_min=0.1,
                        input_max=0.8,
                        gamma=1.6,
                        output_min=0.05,
                        output_max=0.95,
                    )
            else:
                below = s.add(ps.INSERT_FILTER, filter_search=FILTER_SEARCH, **position)
                s.add(ps.SET_FILTER_CHANNELS, node_step=below, channels=channels)
    s.export_channels(plan)
    return Golden(
        "effect-order",
        "tier0/effects/order",
        "Content-effect order: a fill layer with fields A carrying, bottom-up in its content "
        "stack, a fill effect F (uniform 0.8/0.2/0.4, Multiply, 0.7), levels L (input 0.1-0.8, "
        "gamma 1.6, output 0.05-0.95, one effect per channel) and the starter-asset Blur filter B "
        f"(found by the documented resource search {FILTER_SEARCH!r}, default parameters), in the "
        f"orders {', '.join(f's{i} {o}' for i, o in enumerate(EFFECT_ORDERS))}. RGB16 and sRGB8.",
        "grid4x2",
        ["grid4x2", "field-a"],
        s,
    )


LEVELS_VARIANTS = (
    ({"input_min": 0.25, "input_max": 0.75, "clamp": False},),
    ({"input_min": 0.25, "input_max": 0.75, "clamp": True},),
    (
        {"output_min": -0.5, "output_max": 1.5, "clamp": False},
        {"input_min": -0.25, "input_max": 1.25, "gamma": 0.5, "clamp": False},
    ),
    (
        {"output_min": -0.5, "output_max": 1.5, "clamp": True},
        {"input_min": -0.25, "input_max": 1.25, "gamma": 0.5, "clamp": True},
    ),
)


def levels_clamp() -> Golden:
    s = start("grid2x2")
    plan = (("User0", "RGB32F"), ("User1", "RGB16F"), ("User2", "RGB16"), ("User3", "L16F"))
    s.channels(plan)
    res = s.imports("field-a", "grey-a")
    channels = [c for c, _ in plan]
    for texture_set, variant in zip(MESH_SETS["grid2x2"], LEVELS_VARIANTS, strict=True):
        layer = s.fill(channels, position="top", texture_set=texture_set)
        for channel, fmt in plan:
            s.bitmap(layer, channel, res["grey-a" if fmt.startswith("L") else "field-a"])
        below: int | None = None
        for params in variant:
            for channel in channels:
                position = (
                    {"inside_step": layer, "stack": "Content"}
                    if below is None
                    else {"above_step": below}
                )
                below = s.add(ps.INSERT_LEVELS, **position)
                s.add(ps.SET_LEVELS_CHANNEL, node_step=below, channel=channel)
                s.add(ps.SET_LEVELS, node_step=below, **params)
    s.export_channels(plan)
    return Golden(
        "levels-clamp",
        "tier0/levels/clamp",
        "Levels at and beyond the range ends on RGB32F, RGB16F, RGB16 and L16F channels over "
        "the authored ramps: s0 input 0.25-0.75 without clamp, s1 the same clamped, s2 output "
        "-0.5..1.5 then input -0.25..1.25 with gamma 0.5 without clamp, s3 the same clamped.",
        "grid2x2",
        ["grid2x2", "field-a", "grey-a"],
        s,
    )


RESAMPLE_CHANNELS = (
    ("pattern64", [1.0, 1.0], 0.0, [0.0, 0.0]),
    ("pattern64", [0.73, 0.73], 0.0, [0.0, 0.0]),
    ("pattern64", [1.37, 2.11], 0.0, [0.0, 0.0]),
    ("pattern64", [1.0, 1.0], 30.0, [0.0, 0.0]),
    ("pattern64", [1.0, 1.0], 0.0, [0.123, 0.456]),
    ("field-a", [1.0, 1.0], 0.0, [0.0, 0.0]),
    ("field-a", [3.3, 3.3], 0.0, [0.0, 0.0]),
    ("field-a", [1.0, 1.0], 0.0, [0.001953125, 0.0009765625]),
)
RESAMPLE_FILTERS = ("BilinearHQ", "BilinearSharp", "Nearest", "BilinearHQ")
RESAMPLE_WRAPS = ("Repeat", "Repeat", "Repeat", "RepeatNone")


def resample_uv() -> Golden:
    s = start("grid2x2")
    plan = tuple((channel, "RGB16") for channel in USER)
    s.channels(plan)
    res = s.imports("pattern64", "field-a")
    for texture_set, mode, wrap in zip(
        MESH_SETS["grid2x2"], RESAMPLE_FILTERS, RESAMPLE_WRAPS, strict=True
    ):
        below: int | None = None
        for channel, (source, scale, rotation, offset) in zip(USER, RESAMPLE_CHANNELS, strict=True):
            node = (
                s.fill([channel], position="top", texture_set=texture_set)
                if below is None
                else s.fill([channel], above_step=below)
            )
            s.bitmap(node, channel, res[source])
            s.add(
                ps.SET_PROJECTION,
                node_step=node,
                filtering_mode=mode,
                uv_wrapping_mode=wrap,
                scale_mode="Factors",
                scale=scale,
                rotation=rotation,
                offset=offset,
            )
            below = node
    s.export_channels(plan)
    return Golden(
        "resample-uv",
        "tier0/resample/uv",
        "UV-projection resampling of authored bitmaps (04 section 4): per user channel one fill "
        "with the 64x64 pattern (scales 1, 0.73, 1.37x2.11, rotation 30, offset 0.123/0.456) "
        "or the 256 fields A (scale 1, 3.3, sub-texel offset); filter BilinearHQ (s0), "
        "BilinearSharp (s1), Nearest (s2), BilinearHQ without repeat (s3). RGB16 channels.",
        "grid2x2",
        ["grid2x2", "pattern64", "field-a"],
        s,
    )


def height_normal(mesh: str, resolution: int = RESOLUTION) -> Golden:
    s = start(mesh, resolution=resolution)
    res = s.imports("height-ramps")
    sets = MESH_SETS[mesh]
    variants: tuple[tuple[float, bool], ...] = (
        ((1.0, False), (0.5, False), (0.25, False), (1.0, True))
        if mesh == "grid2x2"
        else ((1.0, False),)
    )
    for texture_set, (opacity, doubled) in zip(sets, variants, strict=True):
        node = s.fill(["Height"], position="top", texture_set=texture_set)
        s.bitmap(node, "Height", res["height-ramps"])
        s.blend(node, "Height", "Normal", opacity)
        if doubled:
            extra = s.fill(["Height"], above_step=node)
            s.bitmap(extra, "Height", res["height-ramps"])
            s.blend(extra, "Height", "LinearDodge", 1.0)
    s.export(["virtualMap/Normal_OpenGL:RGB", "virtualMap/Normal_DirectX:RGB"], floating=False)
    s.export(["documentMap/height:L", "documentMap/normal:RGB"], floating=True)
    label = {"grid2x2": "plane-amplitudes", "sphere": "sphere", "bevelled-cube": "bevelled-cube"}
    detail = (
        "s0 opacity 1, s1 0.5, s2 0.25, s3 doubled by a second fill in LinearDodge"
        if mesh == "grid2x2"
        else "opacity 1"
    )
    return Golden(
        f"height-normal-{label[mesh]}",
        "tier0/height-normal/default-method",
        f"Height to normal with the project's default method and strength on the authored {mesh} "
        f"mesh: the authored height ramps (linear ramp, cone, steps, sine ridge) as the Height "
        f"source ({detail}); Normal_OpenGL and Normal_DirectX virtual maps (PNG 16), Height and "
        "Normal channels (OpenEXR 32f).",
        mesh,
        [mesh, "height-ramps"],
        s,
    )


def ao_mixed() -> Golden:
    s = start("grid2x2")
    s.channels((("AO", "L16"),))
    res = s.imports("grey-a", "grey-b")
    s.add(ps.SET_MESH_MAP, usage="AO", resource_step=res["grey-a"])
    sets = MESH_SETS["grid2x2"]
    for texture_set, variant in zip(sets[:3], ("bitmap", "half", "uniform"), strict=True):
        node = s.fill(["AO"], position="top", texture_set=texture_set)
        if variant == "uniform":
            s.colour(node, "AO", [0.5, 0.5, 0.5])
        else:
            s.bitmap(node, "AO", res["grey-b"])
            s.blend(node, "AO", "Normal", 0.5 if variant == "half" else 1.0)
    s.export(["virtualMap/AO_Mixed:L", "documentMap/ambientOcclusion:L"], floating=False)
    return Golden(
        "ao-mixed",
        "tier0/ao-mixed/operator",
        "AO_Mixed operator: the authored AO mesh map (grey A, ramp along x) assigned to every "
        "texture set, an AO channel (L16) whose fill is grey B (ramp along y) at opacity 1 (s0) "
        "and 0.5 (s1), uniform 0.5 (s2), or empty (s3); AO_Mixed and the AO channel (PNG 16).",
        "grid2x2",
        ["grid2x2", "grey-a", "grey-b"],
        s,
    )


def template_slug(template: str) -> str:
    stem = template.rsplit("/", 1)[-1].removesuffix(".spt").lower()
    return re.sub(r"[^a-z0-9]+", "-", stem).strip("-")


def goldens(templates: tuple[str, ...]) -> list[Golden]:
    corpus = [blend_modes(f, m) for f, m in BLEND_FAMILIES.items()]
    corpus += [blend_inputs(), blend_normal_channel(), blend_order(), quantisation_thirds()]
    corpus += [colour_ramps(space) for space in ("sRGB", "Working", "Raw")]
    corpus.append(base_values(None, "default"))
    corpus += [base_values(t, template_slug(t)) for t in templates]
    corpus += [mask_precision(), group_masks(), effect_order(), levels_clamp(), resample_uv()]
    corpus += [height_normal(m) for m in ("grid2x2", "sphere", "bevelled-cube")]
    corpus.append(ao_mixed())
    return corpus


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def applied_settings(golden: Golden) -> list[dict[str, Any]]:
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
    depths = {
        (str(s["args"]["file_format"]), s["args"]["bit_depth"])
        for s in golden.sequence.steps
        if s["call"] == EXPORT
    }
    for file_format, depth in sorted(depths, key=lambda d: (d[0], str(d[1]))):
        settings.append(
            {
                "name": f"export.{file_format}.bit_depth",
                "value": depth,
                "applied_by": "recorder_api",
            }
        )
    settings += [
        {"name": "export.padding", "value": "infinite", "applied_by": "recorder_api"},
        {"name": "export.dithering", "value": False, "applied_by": "recorder_api"},
    ]
    return settings + golden.settings


def manifest(golden: Golden, input_hashes: dict[str, str]) -> dict[str, Any]:
    return {
        "schema": "uzpainter/parity/golden-public/1",
        "record_class": "public_manifest",
        "golden_id": f"{GOLDEN_PREFIX}/{golden.name}",
        "tier": "0",
        "domain": golden.domain,
        "description": golden.description,
        "inputs": [
            {
                "input_id": name,
                "kind": FIXTURES[name][0],
                "path": FIXTURES[name][1],
                "sha256": input_hashes[name],
                "provenance": {
                    "origin": "uzmigames_authored",
                    "licence": "Apache-2.0",
                    "note": "Generated by tools/parity/tier0_semantics/fixtures.py.",
                }
                if FIXTURES[name][2] is not None
                else {"origin": "uzmigames_authored", "licence": "Apache-2.0"},
            }
            for name in golden.inputs
        ],
        "instruction_sequence": {
            "author": "UzmiGames",
            "interface": "substance_painter_documented_python_api",
            "steps": golden.sequence.steps,
        },
        "applied_settings": applied_settings(golden),
        "expectations": [],
        "software": {
            "painter": {
                "product": "Adobe Substance 3D Painter",
                "version": "12.1.0",
                "build_id": PAINTER_BUILD,
            },
            "uzpainter_build_hash": None,
        },
        "private_records": [],
    }
