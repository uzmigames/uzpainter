"""Image analyses of the Iray probe session and the answers they give (07 §2.1, §3.3).

The probe (`tools/parity/recorder/iray_probe.py`) saves renders with Save Render under fixed
names and writes `probe.json`; `analyse_probe` turns them into one answer per row of 07 §2.1
that the public documentation leaves "not confirmed". Decision rules, all stated here:

- Two renders *differ* when some pixel differs by more than the larger of one 8-bit code value
  and twice the largest difference between the two same-settings renders A and B (the
  session's own repeat noise).
- Denoiser: on the object interior (the silhouette eroded by 3 px), the residual between the
  2-sample render I and the S-sample render A is pixel-independent Monte-Carlo noise without a
  denoiser (lag-1 autocorrelation below 0.3) and spatially correlated with one (above 0.6); a
  residual below one code value or a correlation in between is inconclusive (`uncontrolled`).
- Height: displacement moves the outline (silhouette mismatches outside the edge band); bump
  changes only the shading inside an unchanged outline.
- Camera: the probe renders the sphere from a rotated camera; the Euler order whose projected
  silhouette has no mismatch with the render is the confirmed order.
- Display transform (fixed pipeline, decision 038): the saved render's background, in 8-bit
  codes, must equal the standard's 89,89,89 (clear colour linear 0.1 through Default - sRGB).
- Pixel route: Save Render is usable when its frame is not unclear-stale, it is display-referred,
  the unrotated silhouette matches and it has the override resolution; the live view is 1:1
  only when the viewport is at least the render's size.
- Presets: `ref_match` verifies when its background reads 141,142,148 and the panels read back
  clear colour 8D8E94 and rotation 180; `base_color` when its sheet applied and a live view was
  captured.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.parity.recorder.capture import Image, decode_png, measure_storage_format
from tools.parity.render_procedure.projection import (
    BACKGROUND,
    BAND,
    OBJECT,
    ROTATION_ORDERS,
    Camera,
    Mesh,
    silhouette_mask,
)

Pixels = Sequence[tuple[float, ...]]
CODE_8BIT = 1.0 / 255.0
EROSION = 3
UNCORRELATED, CORRELATED = 0.3, 0.6


def normalised(image: Image, bits: int) -> Pixels:
    top = float((1 << bits) - 1)
    return [tuple(v / top for v in p[:3]) for p in image.pixels]


@dataclass(frozen=True)
class Render:
    image: Image
    pixels: Pixels


def load_render(path: Path) -> Render:
    image = decode_png(path)
    return Render(image, normalised(image, measure_storage_format(path).bits_per_channel))


@dataclass(frozen=True)
class Diff:
    max_abs: float
    mean_abs: float
    differing: int
    pixels: int

    def as_json(self) -> dict[str, Any]:
        return {
            "max_abs": self.max_abs,
            "mean_abs": self.mean_abs,
            "differing": self.differing,
            "pixels": self.pixels,
        }


def difference(a: Pixels, b: Pixels, region: list[bool] | None = None) -> Diff:
    if len(a) != len(b):
        raise ValueError("images of different sizes")
    worst, total, differing, count = 0.0, 0.0, 0, 0
    for index, (pa, pb) in enumerate(zip(a, b, strict=True)):
        if region is not None and not region[index]:
            continue
        delta = max(abs(x - y) for x, y in zip(pa, pb, strict=True))
        worst = max(worst, delta)
        total += delta
        differing += delta > 0
        count += 1
    return Diff(worst, total / count if count else 0.0, differing, count)


def changed(diff: Diff, repeat: Diff) -> bool:
    return diff.max_abs > max(CODE_8BIT, 2.0 * repeat.max_abs)


def background_value(image: Image) -> tuple[int, ...]:
    w, h = image.width, image.height
    border = [image.pixels[x] for x in range(w)] + [image.pixels[(h - 1) * w + x] for x in range(w)]
    border += [image.pixels[y * w] for y in range(h)] + [
        image.pixels[y * w + w - 1] for y in range(h)
    ]
    return Counter(border).most_common(1)[0][0]


def background_uniform(image: Image) -> bool:
    value = background_value(image)
    w, h = image.width, image.height
    border = [image.pixels[x] for x in range(w)] + [image.pixels[(h - 1) * w + x] for x in range(w)]
    return all(p == value for p in border)


def object_region(image: Image) -> list[bool]:
    value = background_value(image)
    return [p != value for p in image.pixels]


def erode(region: list[bool], width: int, height: int, steps: int) -> list[bool]:
    current = region
    for _ in range(steps):
        current = [
            current[i]
            and (i % width > 0 and current[i - 1])
            and (i % width < width - 1 and current[i + 1])
            and (i >= width and current[i - width])
            and (i < width * (height - 1) and current[i + width])
            for i in range(width * height)
        ]
    return current


def residual_correlation(
    noisy: Pixels, reference: Pixels, region: list[bool], width: int
) -> tuple[float, float]:
    """Lag-1 autocorrelation (mean of horizontal and vertical) and standard deviation of the
    luminance residual noisy - reference over `region`."""
    residual = {
        i: sum(noisy[i]) / 3.0 - sum(reference[i]) / 3.0
        for i, inside in enumerate(region)
        if inside
    }
    if len(residual) < 16:
        return 0.0, 0.0
    mean = sum(residual.values()) / len(residual)
    variance = sum((r - mean) ** 2 for r in residual.values()) / len(residual)
    if variance == 0.0:
        return 0.0, 0.0
    correlations = []
    for step in (1, width):
        pairs = [
            (residual[i] - mean) * (residual[i + step] - mean)
            for i in residual
            if i + step in residual and (step != 1 or (i + 1) % width)
        ]
        correlations.append(sum(pairs) / len(pairs) / variance if pairs else 0.0)
    return sum(correlations) / 2.0, math.sqrt(variance)


def silhouette_mismatches(image: Image, mask: list[bytes]) -> int:
    """Pixels whose coverage disagrees with the mask outside its don't-care band."""
    value = background_value(image)
    mismatches = 0
    for y, row in enumerate(mask):
        for x, code in enumerate(row):
            is_background = image.pixels[y * image.width + x] == value
            if (code == BACKGROUND and not is_background) or (code == OBJECT and is_background):
                mismatches += 1
            elif code not in (BACKGROUND, BAND, OBJECT):
                raise ValueError(f"mask code {code}")
    return mismatches


def rotation_order_scores(
    image: Image,
    mesh: Mesh,
    position: tuple[float, float, float],
    rotation: tuple[float, float, float],
    field_of_view: float,
) -> dict[str, int]:
    camera = Camera(position, rotation, field_of_view, "Perspective")
    return {
        order: silhouette_mismatches(
            image, silhouette_mask(mesh, camera, image.width, image.height, order)
        )
        for order in ROTATION_ORDERS
    }


def answer(status: str, text: str, evidence: list[str], **extra: Any) -> dict[str, Any]:
    return {"status": status, "answer": text, "evidence": evidence, **extra}


V2_BACKGROUND = (89, 89, 89)
REF_MATCH_BACKGROUND = (141, 142, 148)
REF_MATCH_CLEAR_COLOUR = "8D8E94"
REF_MATCH_ROTATION = 180.0


def entry_values(probe: dict[str, Any], label: str) -> dict[str, Any]:
    return {f"{e['panel']}/{e['setting']}": e["value"] for e in probe["entries"].get(label, [])}


def view_dimensions(path: Path) -> list[int]:
    image = decode_png(path)
    return [image.width, image.height]


def analyse_probe(probe: dict[str, Any], directory: Path, mesh: Mesh) -> dict[str, Any]:
    """Answers per row id from the probe's renders and operator entries (fixed pipeline,
    decision 038), plus `presets`: whether `ref_match` and `base_color` apply and verify."""
    renders = probe["renders"]

    def image(name: str) -> Render:
        return load_render(directory / renders[name]["file"])

    render_a, render_b = image("A"), image("B")
    a, pa = render_a.image, render_a.pixels
    repeat = difference(pa, render_b.pixels)
    region = object_region(a)
    v2 = entry_values(probe, "v2")
    answers: dict[str, Any] = {}

    identical = (directory / renders["A"]["file"]).read_bytes() == (
        directory / renders["B"]["file"]
    ).read_bytes()
    answers["random_seed"] = answer(
        "uncontrolled",
        "Iray's seed is neither documented nor settable. Two renders of the same state in one "
        "session are "
        + ("bit-identical." if identical else f"not bit-identical ({repeat.as_json()}).")
        + " Session-separated repeatability is measured by the references (07 §4 step 1a).",
        ["render/A", "render/B"],
        bit_identical_same_session=identical,
        repeat=repeat.as_json(),
    )

    png = measure_storage_format(directory / renders["A"]["file"])
    background = code8(background_value(a), png.bits_per_channel)
    display_referred = background == V2_BACKGROUND
    exr = renders.get("A_exr")
    answers["save_render"] = answer(
        "confirmed_by_probe",
        f"Save Render offers {probe['save_render_types']!r}; other dialog options: "
        f"{probe['save_render_options']!r}. PNG: {png.bits_per_channel}-bit, {png.channels} "
        f"channels, colour chunk: {png.encoding or 'none'}; its background in 8-bit codes "
        f"{list(background)} "
        + (
            "equals the standard's display value 89,89,89 (linear 0.1 through Default - sRGB): "
            "the display transform is baked in."
            if display_referred
            else "differs from the standard's display value 89,89,89."
        )
        + (
            f" OpenEXR: {exr['sample_type']}, {exr['bits_per_channel']}-bit, "
            f"{exr['channels']} channels."
            if exr
            else ""
        ),
        ["render/A", *(["render/A_exr"] if exr else [])],
        png={
            "bits_per_channel": png.bits_per_channel,
            "channels": png.channels,
            "colour_chunk": png.encoding,
            "background": list(background),
            "display_referred": display_referred,
        },
        exr=None
        if exr is None
        else {k: exr[k] for k in ("sample_type", "bits_per_channel", "channels")},
    )

    colour = probe["render_state"]["colour_management"]
    answers["display_view_transform"] = answer(
        "confirmed_by_probe" if colour["mode"] == "ocio" and display_referred else "uncontrolled",
        f"Colour management {colour['mode']!r} (OCIO = Painter's substance config). The "
        "viewport's display-transform selector is drawn over the viewport, outside the UI "
        "Automation tree and both APIs, so automation cannot set it: a fresh Painter session "
        "shows Default - sRGB (panel image), and every capture verifies it through the "
        f"background, which must read 89,89,89 (read {list(background)}).",
        ["probe.json", "render/A", "panel/v2/viewport-display-transform"],
        pinned="Default - sRGB",
        background=list(background),
    )

    answers["colour_lut"] = answer(
        "not_required",
        "Fixed pipeline (decision 038): no colour profile and no LUT. Activate Color Profile is "
        f"applied off and read back ({v2.get('Display Settings/Activate Color Profile')!r}).",
        ["probe.json", "panel/v2/display-settings"],
        pinned={"Display Settings/Activate Color Profile": False, "color_lut_url": None},
    )
    answers["display_settings"] = answer(
        "not_required",
        "Fixed pipeline (decision 038): post effects, colour profile and display SSS off, "
        "applied and read back; tone mapping does not apply to a colour-managed project "
        "(set_tone_mapping raises).",
        ["probe.json", "panel/v2/display-settings"],
        pinned={
            name: v2.get(name)
            for name in (
                "Display Settings/Activate Post Effects",
                "Display Settings/Activate Color Profile",
                "Display Settings/Activate Subsurface Scattering",
            )
        },
    )
    answers["default_mdl_parameters"] = answer(
        "not_required",
        "Fixed pipeline (decision 038): the material is the default shader instance of a new "
        "project, left at Painter's defaults (panel image); its parameters are not a variable.",
        ["panel/defaults/shader-settings", "panel/height/shader-settings"],
        pinned="Painter's default shader instance",
    )

    iray = {k: v for k, v in v2.items() if k.startswith("Iray Settings/")}
    sized = (a.width, a.height) == (probe["sheet"]["width"], probe["sheet"]["height"])
    answers["iray_settings"] = answer(
        "confirmed_by_probe" if sized else "uncontrolled",
        "No API reads or sets them; the UI operator applies each pinned value and reads it back "
        f"from the widget ({iray}); the saved render is {a.width}x{a.height}. Persistence is not "
        "relied on: every capture re-applies and re-reads the sheet. Caustic Sampler and the "
        "resolution override beyond the pinned values are not required (decision 038).",
        ["probe.json", "panel/v2/iray-settings", "render/A"],
        pinned=iray,
    )
    converged = probe["convergence"]
    answers["readiness"] = answer(
        "confirmed_by_probe",
        "No API exposes it; the UI operator reads Status, Iterations and Rendering time from "
        f"Iray's information section ({converged}), and the recorder gates the capture on Done, "
        "Iterations = S and a time below Max Time.",
        ["probe.json", "panel/v2/iray-settings"],
        convergence=converged,
    )
    viewer = {k: v for k, v in v2.items() if k.startswith("Display Settings/")}
    answers["viewer_mdl_settings"] = answer(
        "confirmed_by_probe",
        "Not in the APIs; the UI operator applies each pinned environment and dome value and "
        f"reads it back ({viewer}). The MDL settings sweep is not required (decision 038).",
        ["probe.json", "panel/v2/display-settings"],
        pinned=viewer,
    )

    f, g = image("F").pixels, image("G").pixels
    to_previous, to_converged = difference(f, pa), difference(f, g)
    if not changed(to_previous, repeat):
        stale = "previous_frame"
    elif to_converged.mean_abs < to_previous.mean_abs:
        stale = "current_frame"
    else:
        stale = "unclear"
    answers["stale_frame"] = answer(
        "confirmed_by_probe" if stale != "unclear" else "uncontrolled",
        f"Save Render right after a camera change (Status {probe['stale']['status_at_save']!r}) "
        + {
            "previous_frame": "saved the previous converged frame: stale frames are possible.",
            "current_frame": "saved a frame of the new settings, not the previous frame.",
            "unclear": "saved a frame matching neither the previous nor the new settings.",
        }[stale],
        ["render/A", "render/F", "render/G", "probe.json"],
        outcome=stale,
        to_previous=to_previous.as_json(),
        to_converged=to_converged.as_json(),
    )

    interior = erode(region, a.width, a.height, EROSION)
    rho, sigma = residual_correlation(image("I").pixels, pa, interior, a.width)
    if sigma < CODE_8BIT:
        denoiser = "inconclusive: the 2-sample residual is below one code value"
        status = "uncontrolled"
    elif rho < UNCORRELATED:
        denoiser, status = "no denoiser acts on the saved render", "confirmed_by_probe"
    elif rho > CORRELATED:
        denoiser, status = "a denoiser acts on the saved render", "confirmed_by_probe"
    else:
        denoiser, status = "inconclusive residual correlation", "uncontrolled"
    answers["denoiser"] = answer(
        status,
        f"{denoiser} (lag-1 correlation {rho:.3f}, residual sd {sigma:.4f}); the Renderer "
        "Settings panel has no denoiser control (panel image).",
        ["render/A", "render/I", "panel/defaults/iray-settings"],
        correlation=rho,
        residual_sd=sigma,
    )

    j = image("J")
    outline = sum(1 for x, y in zip(region, object_region(j.image), strict=True) if x != y)
    shading = changed(difference(pa, j.pixels, interior), repeat)
    if outline > max(4, sum(region) // 200):
        height = "displacement (the outline moves)"
    elif shading:
        height = "bump (shading changes inside an unchanged outline)"
    else:
        height = "neither (a height stripe map changes nothing)"
    answers["height"] = answer(
        "confirmed_by_probe",
        "With the shader at Painter's defaults (panel image), Iray applies a painted height "
        f"as {height}; outline pixels changed: {outline}.",
        ["render/A", "render/J", "panel/height/shader-settings"],
        outline_changed=outline,
        interior_shading_changed=shading,
    )

    camera = probe["camera_probe"]
    px, py, pz = (float(v) for v in camera["position"])
    rx, ry, rz = (float(v) for v in camera["rotation"])
    scores = rotation_order_scores(
        image("H").image, mesh, (px, py, pz), (rx, ry, rz), float(camera["field_of_view"])
    )
    matching = sorted(order for order, score in scores.items() if score == 0)
    centred = silhouette_mismatches(
        a, silhouette_mask(mesh, Camera.from_render_state(probe["render_state"]), a.width, a.height)
    )
    answers["camera_projection"] = answer(
        "confirmed_by_probe" if centred == 0 and matching else "uncontrolled",
        f"Unrotated camera: {centred} silhouette mismatches. Rotated camera "
        f"{camera['rotation']}: Euler orders without mismatch {matching} (scores {scores}).",
        ["render/A", "render/H", "probe.json"],
        unrotated_mismatches=centred,
        order_scores=scores,
        confirmed_orders=matching,
        background_uniform=background_uniform(a),
    )

    view = probe["files"].get("view/V")
    view_size = view_dimensions(directory / view["file"]) if view else None
    one_to_one = view_size is not None and view_size[0] >= a.width and view_size[1] >= a.height
    usable = stale in ("current_frame", "previous_frame") and display_referred and centred == 0
    usable = usable and sized
    answers["pixel_route"] = answer(
        "confirmed_by_probe",
        (
            "Save Render (PNG, display-referred, at the override resolution)"
            if usable
            else "Save Render unusable: the external 1:1 observation fallback is needed"
        )
        + f". The live view of the viewport is {view_size} pixels for a {a.width}x{a.height} "
        + (
            "render: a 1:1 observation is possible."
            if one_to_one
            else "render: it is scaled, so an external observation is not 1:1 at this size."
        ),
        ["render/A", "render/F", "render/G", "view/V"],
        route="save_render" if usable else "external_observation_1to1",
        live_view=view_size,
        live_view_one_to_one=one_to_one,
    )
    ref_bits = measure_storage_format(directory / renders["R"]["file"]).bits_per_channel
    answers["presets"] = preset_answers(probe, directory, image("R").image, ref_bits)
    return answers


def code8(pixel: tuple[int, ...], bits: int) -> tuple[int, ...]:
    """An RGB pixel of a `bits`-deep image in 8-bit code values (rounded)."""
    top = (1 << bits) - 1
    return tuple(round(v * 255 / top) for v in pixel[:3])


def preset_answers(probe: dict[str, Any], directory: Path, ref: Image, bits: int) -> dict[str, Any]:
    """Whether the ref_match preset and the base_color diagnostic apply and verify."""
    background = code8(background_value(ref), bits)
    shown = entry_values(probe, "ref_match")
    try:
        rotation = float(shown.get("Display Settings/Environment Rotation", "nan"))
    except ValueError:
        rotation = math.nan
    ref_ok = (
        background == REF_MATCH_BACKGROUND
        and str(shown.get("Display Settings/Clear color value", "")).upper()
        == REF_MATCH_CLEAR_COLOUR
        and rotation == REF_MATCH_ROTATION
    )
    base = entry_values(probe, "base_color")
    view = probe["files"].get("view/BC")
    return {
        "ref_match": {
            "applied_and_verified": ref_ok,
            "background": list(background),
            "readback": shown,
            "environment_url": probe["ref_match"]["environment_url"],
            "evidence": ["render/R", "panel/ref_match/display-settings", "probe.json"],
        },
        "base_color": {
            "applied_and_verified": bool(base) and view is not None,
            "readback": base,
            "live_view": None if view is None else view_dimensions(directory / view["file"]),
            "evidence": ["view/BC", "panel/base_color/display-settings", "probe.json"],
        },
    }
