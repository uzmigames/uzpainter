"""Tier 0 goldens first recorded under the current oracle envelope (decision 037).

The corpus of `corpus.py` was authored for Painter 12.1.0 and carried to later envelopes by the
refresh. The goldens here were authored after 12.1.5 became the acceptance oracle, so their
manifests exist only under the current envelope's manifest root:

- `tier0/semantics-ui/` (task `phase0.7_tier0-semantics-ui-cases`): the cases that need values
  only Painter's UI can set, named in the settings sheet (`applied_by: operator_settings_sheet`)
  and applied by the operator of `tools/parity/recorder/texture_sheet.py` (decisions 029, 047):
  - the height-to-normal method, a Texture Set Settings value per texture set (`Sharp`, the
    default, and `Smooth (Sobel)`), on the sphere and the bevelled cube, and on a 4x2 plane
    grid whose texture sets sweep the height amplitude (Painter 12.1.5 has no height-to-normal
    strength setting; the amplitude sweep is the strength sweep, decision 047);
  - groups in `Passthrough` (set in the Layers panel per channel) with no mask, a mask on the
    group, on a child and on both, beside the same four stacks with the group in `Normal`.
- `tier0/semantics/` (documented API only): recordings requested by Phase 1 analyses (decision
  048): `resample-uv-minify` and `resample-uv-impulse` (`parity/reports/phase1/
  compositor-resample-gaps.md` section 3) and `group-coverage-order`
  (`parity/reports/phase1/compositor-float32-residual.md`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder import vocabulary as ps
from tools.parity.tier0_semantics.corpus import (
    GOLDEN_PREFIX,
    MESH_SETS,
    USER,
    Golden,
    Sequence,
    manifest,
    start,
)

UI_DIR = "tier0/semantics-ui"
SEMANTICS_DIR = "tier0/semantics"
UI_PREFIX = "tier0/semantics-ui"
HEIGHT_METHODS = {"sharp": "Sharp", "sobel": "Smooth (Sobel)"}
HEIGHT_METHOD_SETTING = "Texture Set Settings/Height to normal method"
BLENDING_MODE_SETTING = "Layers/Blending mode"
PASSTHROUGH = "Passthrough"

# Height amplitude per texture set of the 4x2 plane grid: (fill opacity, copies of the fill).
# The first copy blends Normal at the opacity, every further copy LinearDodge at 1.
AMPLITUDES = ((1.0, 1), (0.75, 1), (0.5, 1), (0.25, 1), (0.1, 1), (1.0, 2), (1.0, 3), (1.0, 4))
# Group masks per texture set: (mask on the group, mask on the Multiply child).
GROUP_MASKS = ((False, False), (True, False), (False, True), (True, True))


def operator_setting(name: str, value: str) -> dict[str, Any]:
    return {"name": name, "value": value, "applied_by": "operator_settings_sheet"}


def method_settings(method: str, texture_sets: list[str]) -> list[dict[str, Any]]:
    return [
        operator_setting(f"{HEIGHT_METHOD_SETTING} ({texture_set})", HEIGHT_METHODS[method])
        for texture_set in texture_sets
    ]


def height_exports(s: Sequence) -> None:
    s.export(["virtualMap/Normal_OpenGL:RGB", "virtualMap/Normal_DirectX:RGB"], floating=False)
    s.export(["documentMap/height:L", "documentMap/normal:RGB"], floating=True)


def height_normal_mesh(mesh: str, method: str) -> Golden:
    s = start(mesh)
    res = s.imports("height-ramps")
    (texture_set,) = MESH_SETS[mesh]
    node = s.fill(["Height"], position="top", texture_set=texture_set)
    s.bitmap(node, "Height", res["height-ramps"])
    s.blend(node, "Height", "Normal", 1.0)
    height_exports(s)
    return Golden(
        f"height-normal-{method}-{mesh}",
        "tier0/height-normal/method",
        f"Height to normal with the texture set's method set to {HEIGHT_METHODS[method]!r} "
        f"through Painter's UI (Texture Set Settings) on the authored {mesh} mesh: the authored "
        "height ramps (linear ramp, cone, steps, sine ridge) as the Height source (opacity 1); "
        "Normal_OpenGL and Normal_DirectX virtual maps (PNG 16), Height and Normal channels "
        "(OpenEXR 32f).",
        mesh,
        [mesh, "height-ramps"],
        s,
        method_settings(method, [texture_set]),
    )


def height_normal_strength(method: str) -> Golden:
    s = start("grid4x2")
    res = s.imports("height-ramps")
    sets = MESH_SETS["grid4x2"]
    for texture_set, (opacity, copies) in zip(sets, AMPLITUDES, strict=True):
        node = s.fill(["Height"], position="top", texture_set=texture_set)
        s.bitmap(node, "Height", res["height-ramps"])
        s.blend(node, "Height", "Normal", opacity)
        for _ in range(copies - 1):
            node = s.fill(["Height"], above_step=node)
            s.bitmap(node, "Height", res["height-ramps"])
            s.blend(node, "Height", "LinearDodge", 1.0)
    height_exports(s)
    sweep = ", ".join(
        f"s{i} {'opacity ' + format(o, 'g') if c == 1 else 'x' + str(c)}"
        for i, (o, c) in enumerate(AMPLITUDES)
    )
    return Golden(
        f"height-normal-{method}-plane-strength",
        "tier0/height-normal/method",
        f"Height-to-normal strength sweep with every texture set's method set to "
        f"{HEIGHT_METHODS[method]!r} through Painter's UI. Painter 12.1.5 has no height-to-normal "
        "strength setting, so the sweep scales the height signal (decision 047): per texture set "
        "of the 4x2 plane grid the authored height ramps at one amplitude, as fill opacity or as "
        f"copies stacked in LinearDodge ({sweep}). Normal_OpenGL and Normal_DirectX virtual maps "
        "(PNG 16), Height and Normal channels (OpenEXR 32f).",
        "grid4x2",
        ["grid4x2", "height-ramps"],
        s,
        method_settings(method, sets),
    )


def group_passthrough_masks() -> Golden:
    s = start("grid4x2")
    plan = (("User0", "RGB16"), ("User1", "sRGB8"), ("User2", "RGB32F"))
    s.channels(plan)
    res = s.imports("field-a", "field-b", "grey-a", "grey-b")
    channels = [c for c, _ in plan]
    settings: list[dict[str, Any]] = []
    variants = [(PASSTHROUGH, masks) for masks in GROUP_MASKS]
    variants += [("Normal", masks) for masks in GROUP_MASKS]
    for texture_set, (mode, (group_mask, child_mask)) in zip(
        MESH_SETS["grid4x2"], variants, strict=True
    ):
        base = s.fill(channels, position="top", texture_set=texture_set)
        for channel in channels:
            s.bitmap(base, channel, res["field-a"])
        group = s.add(ps.INSERT_GROUP, above_step=base)
        for channel in channels:
            if mode == PASSTHROUGH:
                settings.append(
                    operator_setting(
                        f"{BLENDING_MODE_SETTING} (step {group}, {channel})", PASSTHROUGH
                    )
                )
            else:
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
        for node, source, masked in ((group, "grey-a", group_mask), (child, "grey-b", child_mask)):
            if masked:
                s.add(ps.ADD_MASK, node_step=node, background="Black")
                effect = s.add(ps.INSERT_FILL, inside_step=node, stack="Mask")
                s.bitmap(effect, None, res[source], effect=True)
    s.export_channels(plan)
    return Golden(
        "group-passthrough-masks",
        "tier0/group/masks",
        "Group Passthrough with masks, on the stack of the group-masks golden: fields A at the "
        "root, above it a group at opacity 0.75 holding fields B (Multiply) under a uniform "
        "0.2/0.9/0.5 fill (Screen, 0.5). s0-s3 the group in Passthrough, set per channel through "
        "Painter's UI (the documented BlendingMode.PassThrough does not exist at runtime): no "
        "mask, a mask on the group (grey A), on the Multiply child (grey B), on both; s4-s7 the "
        "same four with the group in Normal through the API. Channels RGB16, sRGB8 and RGB32F.",
        "grid4x2",
        ["grid4x2", "field-a", "field-b", "grey-a", "grey-b"],
        s,
        settings,
    )


# compositor-resample-gaps.md section 3: per set (filter, wrap).
MINIFY_SETS = (
    ("BilinearHQ", "Repeat"),
    ("BilinearSharp", "Repeat"),
    ("BilinearHQ", "RepeatNone"),
    ("BilinearSharp", "RepeatNone"),
)
MINIFY_SCALES = (5.13, 6.07, 7.77, 10.3, 13.2, 16.6)
# Per user channel: (scale [u, v], rotation in degrees, offset [u, v]).
MINIFY_CHANNELS = (
    *(([s, s], 0.0, [0.0, 0.0]) for s in MINIFY_SCALES),
    ([13.2, 5.13], 0.0, [0.0, 0.0]),
    ([7.77, 7.77], 30.0, [0.123, 0.456]),
)
IMPULSE_CHANNELS = (
    *(([s, s], 0.0, [0.0, 0.0]) for s in MINIFY_SCALES),
    ([13.2, 13.2], 0.0, [0.001953125, 0.0009765625]),
    ([7.77, 7.77], 0.0, [0.0048828125, 0.0]),
)


def resample_minifying(name: str, source: str, plan_of_channels: tuple[Any, ...]) -> Golden:
    s = start("grid2x2")
    plan = tuple((channel, "RGB16") for channel in USER)
    s.channels(plan)
    res = s.imports(source)
    for texture_set, (mode, wrap) in zip(MESH_SETS["grid2x2"], MINIFY_SETS, strict=True):
        below: int | None = None
        for channel, (scale, rotation, offset) in zip(USER, plan_of_channels, strict=True):
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
        name,
        "tier0/resample/uv",
        "",
        "grid2x2",
        ["grid2x2", source],
        s,
    )


def resample_uv_minify() -> Golden:
    golden = resample_minifying("resample-uv-minify", "pattern64", MINIFY_CHANNELS)
    golden.description = (
        "Bilinear minification (compositor-resample-gaps.md section 3, item 1): per user channel "
        "one fill projecting the 64x64 pattern at scales 5.13, 6.07, 7.77, 10.3, 13.2, 16.6, "
        "13.2x5.13 and 7.77 with rotation 30 and offset 0.123/0.456; BilinearHQ with repeat (s0), "
        "BilinearSharp with repeat (s1), BilinearHQ without repeat (s2), BilinearSharp without "
        "repeat (s3). RGB16 channels."
    )
    return golden


def resample_uv_impulse() -> Golden:
    golden = resample_minifying("resample-uv-impulse", "impulse64", IMPULSE_CHANNELS)
    golden.description = (
        "Bilinear minification kernel reads (compositor-resample-gaps.md section 3, item 2): the "
        "authored 64x64 impulse fixture (four isolated R impulses on 0, G impulses on a 16384 "
        "base, a B step at x = 32) at scales 5.13, 6.07, 7.77, 10.3, 13.2, 16.6, 13.2 with offset "
        "1/512, 1/1024 and 7.77 with offset 1/204.8, 0; filters and wraps per texture set as in "
        "resample-uv-minify. RGB16 channels."
    )
    return golden


# compositor-float32-residual.md recording request: per channel (name, format, L source).
COVERAGE_CHANNELS = (
    ("User0", "RGB32F"),
    ("User1", "L32F"),
    ("User2", "RGB16"),
    ("User3", "sRGB8"),
    ("User4", "RGB8"),
    ("User5", "L8"),
)
# Per set: (child source, top blending mode, top opacity); None is the uniform colour 0.
COVERAGE_SETS = (
    (None, "Normal", 0.5),
    ("field-b", "Normal", 0.5),
    ("field-b", "Screen", 0.5),
    ("field-b", "Normal", 0.3),
)
# An L channel takes the grey fixture that equals the RGB field's red ramp (decision 048).
GREY_OF = {"field-a": "grey-a", "field-b": "grey-b"}


def group_coverage_order() -> Golden:
    s = start("grid2x2")
    s.channels(COVERAGE_CHANNELS)
    res = s.imports("field-a", "field-b", "grey-a", "grey-b")
    channels = [c for c, _ in COVERAGE_CHANNELS]

    def source(field: str, fmt: str) -> int:
        return res[GREY_OF[field] if fmt.startswith("L") else field]

    for texture_set, (child_source, top_mode, top_opacity) in zip(
        MESH_SETS["grid2x2"], COVERAGE_SETS, strict=True
    ):
        root = s.fill(channels, position="top", texture_set=texture_set)
        for channel in channels:
            s.colour(root, channel, [0.0, 0.0, 0.0])
            s.blend(root, channel, "Normal", 1.0)
        group = s.add(ps.INSERT_GROUP, above_step=root)
        for channel in channels:
            s.blend(group, channel, "Normal", 1.0)
        child = s.fill(channels, inside_step=group, stack="Substack")
        for channel, fmt in COVERAGE_CHANNELS:
            if child_source is None:
                s.colour(child, channel, [0.0, 0.0, 0.0])
            else:
                s.bitmap(child, channel, source(child_source, fmt))
            s.blend(child, channel, "Normal", 1.0)
        s.add(ps.ADD_MASK, node_step=child, background="Black")
        effect = s.add(ps.INSERT_FILL, inside_step=child, stack="Mask")
        s.bitmap(effect, None, res["grey-b"], effect=True)
        top = s.fill(channels, above_step=child)
        for channel, fmt in COVERAGE_CHANNELS:
            s.bitmap(top, channel, source("field-a", fmt))
            s.blend(top, channel, top_mode, top_opacity)
    s.export_channels(COVERAGE_CHANNELS)
    return Golden(
        "group-coverage-order",
        "tier0/group/masks",
        "Float32 source-over order onto a partly covered backdrop (compositor-float32-residual.md "
        "recording request): per texture set a root fill of uniform 0 at opacity 1, above it a "
        "group (Normal, 1, no mask) holding a child fill under a mask (Black background, mask fill "
        "of grey B: the row ramp) and a top fill of fields A; s0 child uniform 0, top Normal 0.5; "
        "s1 child fields B, top Normal 0.5; s2 as s1 with the top in Screen; s3 as s1 with the top "
        "at 0.3. Channels RGB32F, L32F, RGB16, sRGB8, RGB8, L8; the L channels take grey A and "
        "grey B in place of fields A and B.",
        "grid2x2",
        ["grid2x2", "field-a", "field-b", "grey-a", "grey-b"],
        s,
    )


def ui_goldens() -> list[Golden]:
    corpus = [
        height_normal_mesh(mesh, method)
        for method in HEIGHT_METHODS
        for mesh in ("sphere", "bevelled-cube")
    ]
    corpus += [height_normal_strength(method) for method in HEIGHT_METHODS]
    corpus.append(group_passthrough_masks())
    return corpus


def api_goldens() -> list[Golden]:
    return [resample_uv_minify(), resample_uv_impulse(), group_coverage_order()]


def current_manifest(
    golden: Golden, input_hashes: dict[str, str], prefix: str, entry: dict[str, Any]
) -> dict[str, Any]:
    """The golden's manifest under the envelope `entry` (its build), private records empty."""
    data = manifest(golden, input_hashes)
    data["golden_id"] = f"{prefix}/{golden.name}"
    data["software"]["painter"] = {
        "product": "Adobe Substance 3D Painter",
        "version": str(entry["painter_version"]),
        "build_id": str(entry["painter_build"]),
    }
    return data


def planned_current(input_hashes: dict[str, str], root: Path) -> dict[Path, dict[str, Any]]:
    """Manifest path -> manifest of every golden of this module, under the current envelope."""
    entry = current_envelope(root)
    base = manifest_root(entry, root)
    planned = {
        base / UI_DIR / f"{g.name}.json": current_manifest(g, input_hashes, UI_PREFIX, entry)
        for g in ui_goldens()
    }
    planned |= {
        base / SEMANTICS_DIR / f"{g.name}.json": current_manifest(
            g, input_hashes, GOLDEN_PREFIX, entry
        )
        for g in api_goldens()
    }
    return planned


def ui_manifest_dir(root: Path) -> Path:
    return manifest_root(current_envelope(root), root) / UI_DIR
