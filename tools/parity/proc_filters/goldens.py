"""The filter goldens of `phase3.2_proc-filter-families` (2026-11-10).

Parameter names are the ones the documented `Property` API reports (item 2.1,
`docs/analysis/proc-filter-families/01-parameter-discovery.md`, survey SHA-256 `d9c18e02...`) for
the starter-asset filters, and the documented `LevelsEffectParams` fields for the native levels
effect; the values are authored here. Each batch is declared before any golden is recorded, and
its held-out list is pinned before calibration starts (decision 222).

**Sharpen batch.** Certified editable domain: `intensity` in [0, 4] (the documented range), the
single listed seed 0 (no `$randomseed` property is listed), a content-stack filter on an L32F
channel whose content is any float32 raster at the output's resolution, one UV tile, output
1024/2048/4096 float32 mono. The §6 matrix: sphere, rounded cube, hat v8 low (hat v6 low is lost,
decision 260) x {1024, 2048, 4096} x {defaults, the three hat v8 recipe sets (`intensity` 0.25 and
0.4 on mask stacks, 0.2 on a content stack, `Assets3D .../10-Chapeu/report.json`), two boundary
sets (`intensity` 0 and 4)}. Held-out: the knob cube at 2048 and the Tunic v10 low mesh at 1024
(meshes outside the calibration set) with the defaults, one recipe set and two interior points.

**Levels batch.** The native levels effect certified as a filter asset (decision 328 §1): the
domain of `assets/procedural/records/filter.levels@1.json` (input and output ranges in [0, 1],
gamma in [0.125, 8], clamp in {0, 1}, input_min + 2^-8 <= input_max), the same geometry and
output. The §6 matrix: the same meshes and resolutions x {defaults, the right bracer's recipe
(input 0.42 to 0.6, `Assets3D .../22-Bracal-Direito/report.json`), two boundary sets}. Held-out:
the same meshes as Sharpen's, with the defaults, the recipe set and two interior points.

**Diagnostic** (one golden, never a calibration or held-out case): Blur and Grayscale Conversion,
which no Assets3D recipe uses (the harness needs a recipe parameter set in the §6 matrix,
decision 303), and Sharpen on an RGB channel, on the rounded cube at 1024 with RGB content.
"""

from __future__ import annotations

from typing import Any

from tools.parity.proc_filters.requests import LEVELS, FilterCase, Golden

SHARPEN = "Sharpen"
# (set id, role, intensity)
SHARPEN_SETS: tuple[tuple[str, str, float], ...] = (
    ("defaults", "defaults", 1.0),
    ("recipe-hat-v8-mask-a", "recipe", 0.25),
    ("recipe-hat-v8-content", "recipe", 0.2),
    ("recipe-hat-v8-mask-b", "recipe", 0.4),
    ("boundary-min", "boundary", 0.0),
    ("boundary-max", "boundary", 4.0),
)
SHARPEN_HELD_OUT: tuple[tuple[str, str, float], ...] = (
    ("defaults", "defaults", 1.0),
    ("recipe-hat-v8-mask-a", "recipe", 0.25),
    ("interior-a", "interior", 0.63),
    ("interior-b", "interior", 2.71),
)

LEVELS_DEFAULTS: dict[str, Any] = {
    "input_min": 0.0,
    "input_max": 1.0,
    "gamma": 1.0,
    "output_min": 0.0,
    "output_max": 1.0,
    "clamp": 0,
}
# (set id, role, the levels point; the defaults set leaves every field at Painter's default)
LEVELS_SETS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("defaults", "defaults", LEVELS_DEFAULTS),
    ("recipe-bracer-r", "recipe", {**LEVELS_DEFAULTS, "input_min": 0.42, "input_max": 0.6}),
    (
        "boundary-a",
        "boundary",
        {**LEVELS_DEFAULTS, "input_min": 0.0, "input_max": 1.0, "gamma": 0.125, "clamp": 0},
    ),
    (
        "boundary-b",
        "boundary",
        {
            "input_min": 0.25,
            "input_max": 0.75,
            "gamma": 8.0,
            "output_min": 1.0,
            "output_max": 0.0,
            "clamp": 1,
        },
    ),
)
LEVELS_HELD_OUT: tuple[tuple[str, str, dict[str, Any]], ...] = (
    LEVELS_SETS[0],
    LEVELS_SETS[1],
    (
        "interior-a",
        "interior",
        {
            "input_min": 0.1,
            "input_max": 0.85,
            "gamma": 1.7,
            "output_min": 0.05,
            "output_max": 0.9,
            "clamp": 0,
        },
    ),
    (
        "interior-b",
        "interior",
        {
            "input_min": 0.3,
            "input_max": 0.55,
            "gamma": 0.4,
            "output_min": 0.2,
            "output_max": 0.95,
            "clamp": 1,
        },
    ),
)

CALIBRATION_MESHES = ("sphere", "rounded-cube", "hat-v8")
RESOLUTIONS = (1024, 2048, 4096)
HELD_OUT = (("knob-cube", 2048), ("tunic-v10", 1024))


def sharpen_cases(sets: tuple[tuple[str, str, float], ...]) -> tuple[FilterCase, ...]:
    return tuple(FilterCase(i, SHARPEN, (("intensity", value),)) for i, _, value in sets)


def levels_steps(point: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    if point == LEVELS_DEFAULTS:
        return ()  # Painter's defaults: nothing is set
    return tuple((name, point[name]) for name in LEVELS_DEFAULTS)


def levels_cases(sets: tuple[tuple[str, str, dict[str, Any]], ...]) -> tuple[FilterCase, ...]:
    return tuple(FilterCase(i, LEVELS, levels_steps(point)) for i, _, point in sets)


def sharpen_goldens() -> tuple[Golden, ...]:
    calibration = tuple(
        Golden("calibration", "sharpen", mesh, resolution, sharpen_cases(SHARPEN_SETS))
        for mesh in CALIBRATION_MESHES
        for resolution in RESOLUTIONS
    )
    held_out = tuple(
        Golden("held-out", "sharpen", mesh, resolution, sharpen_cases(SHARPEN_HELD_OUT))
        for mesh, resolution in HELD_OUT
    )
    return (*calibration, *held_out)


def levels_goldens() -> tuple[Golden, ...]:
    calibration = tuple(
        Golden("calibration", "levels", mesh, resolution, levels_cases(LEVELS_SETS))
        for mesh in CALIBRATION_MESHES
        for resolution in RESOLUTIONS
    )
    held_out = tuple(
        Golden("held-out", "levels", mesh, resolution, levels_cases(LEVELS_HELD_OUT))
        for mesh, resolution in HELD_OUT
    )
    return (*calibration, *held_out)


DIAGNOSTIC = Golden(
    "diagnostic",
    "mixed",
    "rounded-cube",
    1024,
    (
        FilterCase("blur-defaults", "Blur"),
        FilterCase("blur-intensity-4", "Blur", (("intensity", 4.0),)),
        FilterCase("grayscale-defaults", "Grayscale Conversion"),
        FilterCase(
            "grayscale-bt709",
            "Grayscale Conversion",
            (("Red", 0.2126), ("Green", 0.7152), ("Blue", 0.0722)),
        ),
        FilterCase("grayscale-average", "Grayscale Conversion", (("grayscale_type", 2),)),
        FilterCase("sharpen-rgb-defaults", SHARPEN),
    ),
    content="content-rgb",
    channel_format="RGB32F",
)


def goldens() -> tuple[Golden, ...]:
    return (DIAGNOSTIC, *sharpen_goldens(), *levels_goldens())
