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
MAGENTA_SHARE = 0.9


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


def magenta_share(pixels: Pixels) -> float:
    hits = sum(1 for r, g, b in pixels if r > 0.95 and g < 0.05 and b > 0.95)
    return hits / len(pixels)


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


def analyse_probe(probe: dict[str, Any], directory: Path, mesh: Mesh) -> dict[str, Any]:
    """Answers per row id from the probe's renders and operator entries."""
    renders = probe["renders"]

    def image(name: str) -> Render:
        return load_render(directory / renders[name]["file"])

    render_a, render_b = image("A"), image("B")
    a, pa = render_a.image, render_a.pixels
    repeat = difference(pa, render_b.pixels)
    region = object_region(a)
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
    tone_baked = changed(difference(pa, image("C").pixels), repeat)
    exr: dict[str, Any] | None = None
    if "A_exr" in renders:
        exr_a = directory / renders["A_exr"]["file"]
        exr_format = measure_storage_format(exr_a)
        exr_tone = exr_a.read_bytes() != (directory / renders["C_exr"]["file"]).read_bytes()
        exr = {
            "sample_type": exr_format.sample_type,
            "bits_per_channel": exr_format.bits_per_channel,
            "channels": exr_format.channels,
            "tone_mapping_changes_file": exr_tone,
            "conclusive": identical,
        }
    answers["save_render"] = answer(
        "confirmed_by_probe",
        f"Save Render offers {probe['save_render_types']!r}. PNG: {png.bits_per_channel}-bit, "
        f"{png.channels} channels, colour chunk: {png.encoding or 'none'}; the tone mapping "
        + ("is" if tone_baked else "is not")
        + " baked in (Linear vs ACES renders "
        + ("differ" if tone_baked else "are equal")
        + ")."
        + (f" OpenEXR: {exr}." if exr else " OpenEXR not offered."),
        ["render/A", "render/C", *(["render/A_exr", "render/C_exr"] if exr else [])],
        png={
            "bits_per_channel": png.bits_per_channel,
            "channels": png.channels,
            "colour_chunk": png.encoding,
            "tone_mapping_baked": tone_baked,
        },
        exr=exr,
    )

    d = image("D").pixels
    lut_saved = magenta_share(d) >= MAGENTA_SHARE
    lut_viewport = bool(probe["lut"]["viewport_magenta"])
    answers["colour_lut"] = answer(
        "confirmed_by_probe",
        "With an all-magenta colour-profile LUT active, the Iray viewport "
        + ("shows" if lut_viewport else "does not show")
        + " the LUT and the saved render "
        + ("contains" if lut_saved else "does not contain")
        + f" it ({magenta_share(d):.3f} of pixels magenta).",
        ["render/D", "probe.json"],
        viewport=lut_viewport,
        saved_render=lut_saved,
    )

    vignette = changed(difference(pa, image("E").pixels), repeat)
    answers["display_settings"] = answer(
        "confirmed_by_probe",
        "Tone mapping "
        + ("changes" if tone_baked else "does not change")
        + " the saved Iray image; the colour-profile LUT "
        + ("changes" if lut_saved else "does not change")
        + " it; the post effect Vignette "
        + ("changes" if vignette else "does not change")
        + " it. Fixtures keep Linear tone mapping, no colour profile and post effects off.",
        ["render/A", "render/C", "render/D", "render/E"],
        tone_mapping=tone_baked,
        colour_lut=lut_saved,
        post_effect_vignette=vignette,
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
        f"Save Render right after a settings change (Status {probe['stale']['status_at_save']!r}) "
        + {
            "previous_frame": "saved the previous converged frame: stale frames are possible.",
            "current_frame": "saved the current, unfinished frame of the new settings.",
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
        f"{denoiser} (lag-1 correlation {rho:.3f}, residual sd {sigma:.4f}); the Iray Settings "
        "panel has no denoiser control (panel image).",
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
        f"Iray applies height as {height}; outline pixels changed: {outline}.",
        ["render/A", "render/J"],
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

    answers.update(persistence_answers(probe))
    usable = (
        stale in ("current_frame", "previous_frame")
        and (png.encoding is not None or tone_baked)
        and centred == 0
        and (a.width, a.height) == (probe["sheet"]["width"], probe["sheet"]["height"])
    )
    answers["pixel_route"] = answer(
        "confirmed_by_probe",
        "Save Render (PNG, display-referred)"
        if usable
        else "Save Render unusable: the external 1:1 observation fallback is needed",
        ["render/A", "render/C", "render/F", "render/G"],
        route="save_render" if usable else "external_observation_1to1",
    )
    return answers


PERSISTED_SETTINGS = (
    ("Iray Settings", "Min Sample"),
    ("Iray Settings", "Max Sample"),
    ("Iray Settings", "Max Time"),
    ("Iray Settings", "Caustic Sampler"),
    ("Iray Settings", "Firefly Filter"),
    ("Iray Settings", "Width"),
    ("Iray Settings", "Height"),
    ("Viewer and MDL Settings", "Environment Exposure"),
    ("Viewer and MDL Settings", "Environment Rotation"),
    ("Viewer and MDL Settings", "Emissive Intensity"),
    ("Viewer and MDL Settings", "IOR"),
)


def persistence_answers(probe: dict[str, Any]) -> dict[str, Any]:
    entries = probe["entries"]

    def values(name: str) -> dict[tuple[str, str], str]:
        return {(e["panel"], e["setting"]): str(e["value"]) for e in entries[name]}

    applied, reopened, fresh = values("persistence"), values("after_reopen"), values("new_project")
    table = {
        f"{panel}/{setting}": {
            "applied": applied.get((panel, setting)),
            "after_save_reopen": reopened.get((panel, setting)),
            "new_project_same_session": fresh.get((panel, setting)),
            "kept_by_project": reopened.get((panel, setting)) == applied.get((panel, setting)),
            "kept_by_session": fresh.get((panel, setting)) == applied.get((panel, setting)),
        }
        for panel, setting in PERSISTED_SETTINGS
    }
    iray = {k: v for k, v in table.items() if k.startswith("Iray Settings/")}
    viewer = {k: v for k, v in table.items() if not k.startswith("Iray Settings/")}
    defaults = {f"{e['panel']}/{e['setting']}": e["value"] for e in entries["mdl_defaults"]}

    def summary(rows: dict[str, Any]) -> str:
        return "; ".join(
            f"{name}: "
            + ("saved with the project" if row["kept_by_project"] else "not saved with the project")
            + (", carried into a new project" if row["kept_by_session"] else "")
            for name, row in rows.items()
        )

    return {
        "iray_settings": answer(
            "confirmed_by_probe",
            "No Python or JavaScript API symbol reads or sets them (documentation scan); the "
            "operator fixes and reads them in the panel. " + summary(iray) + ".",
            [
                "probe.json",
                "panel/after-reopen/iray-settings",
                "panel/after-reopen/viewer-and-mdl-settings",
            ],
            persistence=iray,
        ),
        "viewer_mdl_settings": answer(
            "confirmed_by_probe",
            "Not in the Python or JavaScript API; operator-recorded. " + summary(viewer) + ".",
            [
                "probe.json",
                "panel/after-reopen/iray-settings",
                "panel/after-reopen/viewer-and-mdl-settings",
            ],
            persistence=viewer,
        ),
        "default_mdl_parameters": answer(
            "confirmed_by_probe",
            "Defaults shown on a new project's material: "
            + ", ".join(f"{k} = {v}" for k, v in sorted(defaults.items()))
            + "; operator-recorded per material instance.",
            ["probe.json", "panel/defaults/viewer-and-mdl-settings"],
            defaults=defaults,
        ),
    }
