"""Recording requests of the Tier 2b bake goldens on the analytic fixtures (decision 384).

Each request is one Painter project created from a fixture's low mesh (`fixtures.py`) at 512 px,
one or two bakers enabled, baked once through the documented baking API, the baked maps exported
twice (PNG 16 and OpenEXR 32f, no padding, no dithering) and recorded twice (r1; r2 after save and
reopen) by `python -m tools.parity.recorder record`. Written under the current envelope's
`requests/tier2b/bakes/`; the batch compiler schedules them (`tools/parity/recorder/batch.py`).

Settings common to every golden:
- `OutputSize` (9, 9), the texture-set resolution, so no export resamples a mesh map;
- `DilationWidth` 0 and export padding `passthrough`: the native bakers refuse a dilation above 0
  and fill nothing (decisions 337 §2, 341 §1), so the goldens hold Painter's raw texels;
- the scene's own settings from its C++ request: the plane, slab and bevelled cube bake their highs
  with absolute distances (`RelativeScale` off; the native bakers refuse a relative distance
  without a box size, `06-baking.md` §3), the cube with `FilterMethod` By mesh name; the sphere
  bakes low as high with Painter's default distances;
- every other parameter at Painter's default (`assets/defaults/baking.json`, the admitted Tier 0
  baking-defaults captures); each parameter a golden sets is read back by the recorder.

The swept values are the ones each baker task's Tier 2b item names (see `GOLDENS`). Height,
Opacity and BentNormals have no request: Painter's documentation names no export map for them
(decision 110's P21-A), so no documented call reads their baked maps out.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT, sha256_bytes
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier2b_bakes.fixtures import (
    BEVEL_MAX_DEPTH,
    BEVEL_MAX_HEIGHT,
    FIXTURE_DIR_NAME,
    PLANE_MAX_DEPTH,
    PLANE_MAX_HEIGHT,
    committed_fixtures,
)

FAMILY = "tier2b/bakes"
RESOLUTION, OUTPUT_SIZE_LOG2 = 512, 9
NORMAL_MAP_FORMAT = "OpenGL"
UNCONTROLLED = ["preferences.bake_backend"]
EXPORTS: tuple[tuple[str, int | str], ...] = (("png", 16), ("exr", "32f"))
PADDING = "passthrough"
PRODUCT = "Adobe Substance 3D Painter"


@dataclass(frozen=True)
class Scene:
    name: str
    low: str  # fixture file stem
    high: str | None  # None: baked low as high
    common: tuple[tuple[str, Any], ...]  # common parameters the scene's C++ request fixes
    role: str

    def inputs(self) -> list[str]:
        return [self.low] if self.high is None else [self.low, self.high]


def absolute(height: float, depth: float) -> tuple[tuple[str, Any], ...]:
    return (("RelativeScale", False), ("MaxHeight", height), ("MaxDepth", depth))


SCENES = {
    "plane": Scene(
        "plane",
        "plane-low",
        "plane-high",
        absolute(PLANE_MAX_HEIGHT, PLANE_MAX_DEPTH),
        "the low plane under a wider flat high 0.005 above it (CaseNormalPlane)",
    ),
    "slab": Scene(
        "slab",
        "plane-low",
        "slab-high",
        absolute(PLANE_MAX_HEIGHT, PLANE_MAX_DEPTH),
        "the low plane in a 0.25-thick slab (CaseThicknessPlane)",
    ),
    "sphere": Scene(
        "sphere",
        "sphere-on-ground",
        None,
        (("LowAsHigh", True),),
        "the sphere on its ground, baked low as high",
    ),
    "bevelled-cube": Scene(
        "bevelled-cube",
        "bevelled-cube-low",
        "bevelled-cube-high",
        (("FilterMethod", "By mesh name"), *absolute(BEVEL_MAX_HEIGHT, BEVEL_MAX_DEPTH)),
        "the bevelled cube with highs matched by name: chamfered cube, knob under an _ignorebf "
        "cover, unmatched decoy (CaseMatchByName)",
    ),
}
ENUM_PARAMETERS = frozenset(
    {"FilterMethod", "ColorSource", "ColorGenerator", "Mode", "Axis", "Normalization"}
    | {"NormalizationScale", "MaximizeRange"}
)


@dataclass(frozen=True)
class Golden:
    baker: str  # golden-name prefix
    task: str
    scene: str
    usages: tuple[str, ...]
    maps: tuple[str, ...]
    variant: str = ""
    baker_parameters: tuple[tuple[str, str, Any], ...] = ()  # (usage, key, value)
    curvature_method: str | None = None

    @property
    def name(self) -> str:
        return "-".join(part for part in (self.baker, self.scene, self.variant) if part)

    @property
    def golden_id(self) -> str:
        return f"{FAMILY}/{self.name}"


ANALYTIC = ("plane", "sphere", "bevelled-cube")
NORMAL_MAP, CURVATURE_MAP = "meshMap/normal_base:RGB", "meshMap/curvature:L"
POSITION_NORMALIZATIONS = ("BBox", "BSphere", "None")
POSITION_SCALES = ("Per Material", "Full Scene")
THICKNESS_RANGES = ("Relative to ray distances", "Relative to min/max (per UV tile)", "None")
ID_GENERATORS = ("Random", "Hue shift", "Grayscale")
ID_SOURCE = "Mesh ID / Polygroup"


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def goldens() -> tuple[Golden, ...]:
    found: list[Golden] = []
    for scene in ANALYTIC:
        found.append(Golden("normal", "phase3.2_baker-normal", scene, ("Normal",), (NORMAL_MAP,)))
        found.append(
            Golden(
                "world-space-normal",
                "phase3.4_baker-world-space-normal",
                scene,
                ("WorldSpaceNormal",),
                ("meshMap/world_space_normals:RGB",),
            )
        )
        for ground, variant in ((False, "no-ground-plane"), (True, "ground-plane")):
            found.append(
                Golden(
                    "ao",
                    "phase3.4_baker-ao",
                    scene,
                    ("AO",),
                    ("meshMap/ambient_occlusion:L",),
                    variant,
                    (("AO", "GroundPlane", ground),),
                )
            )
        found.append(
            Golden(
                "curvature",
                "phase3.4_baker-curvature",
                scene,
                ("Curvature",),
                (CURVATURE_MAP,),
                "from-mesh",
                curvature_method="FromMesh",
            )
        )
        found.append(
            Golden(
                "curvature",
                "phase3.4_baker-curvature",
                scene,
                ("Normal", "Curvature"),
                (NORMAL_MAP, CURVATURE_MAP),
                "from-normal-map",
                curvature_method="FromNormalMap",
            )
        )
        position = ("meshMap/position:RGB",)
        for normalization in POSITION_NORMALIZATIONS:
            for scale in POSITION_SCALES:
                found.append(
                    Golden(
                        "position",
                        "phase3.4_baker-position",
                        scene,
                        ("Position",),
                        position,
                        f"all-axis-{slug(normalization)}-{slug(scale)}",
                        (
                            ("Position", "Mode", "All axis"),
                            ("Position", "Normalization", normalization),
                            ("Position", "NormalizationScale", scale),
                        ),
                    )
                )
        for axis in ("X", "Y", "Z"):
            found.append(
                Golden(
                    "position",
                    "phase3.4_baker-position",
                    scene,
                    ("Position",),
                    position,
                    f"one-axis-{axis.lower()}",
                    (("Position", "Mode", "One axis"), ("Position", "Axis", axis)),
                )
            )
        for generator in ID_GENERATORS:
            found.append(
                Golden(
                    "id",
                    "phase3.4_baker-id",
                    scene,
                    ("ID",),
                    ("meshMap/id:RGB",),
                    f"mesh-id-{slug(generator)}",
                    (("ID", "ColorSource", ID_SOURCE), ("ID", "ColorGenerator", generator)),
                )
            )
    for scene in ("slab", "sphere", "bevelled-cube"):
        for normalization in THICKNESS_RANGES:
            found.append(
                Golden(
                    "thickness",
                    "phase3.4_baker-thickness",
                    scene,
                    ("Thickness",),
                    ("meshMap/thickness:L",),
                    slug(normalization),
                    (("Thickness", "MaximizeRange", normalization),),
                )
            )
    return tuple(found)


GOLDENS = goldens()


def fixture_path(stem: str) -> str:
    return f"parity/fixtures/{FIXTURE_DIR_NAME}/{stem}.obj"


def inputs(scene: Scene) -> list[dict[str, Any]]:
    data = committed_fixtures()
    return [
        {
            "input_id": stem,
            "kind": "mesh",
            "path": fixture_path(stem),
            "sha256": sha256_bytes(data[f"{stem}.obj"]),
            "provenance": {"origin": "uzmigames_authored", "licence": "Apache-2.0"},
        }
        for stem in scene.inputs()
    ]


def set_args(key: str, value: Any, usage: str | None = None) -> dict[str, Any]:
    args: dict[str, Any] = {"parameter": key}
    if usage is not None:
        args["usage"] = usage
    if key in ENUM_PARAMETERS:
        args["enum_label"] = value
    else:
        args["value"] = value
    return args


def parameters(golden: Golden) -> list[tuple[str | None, str, Any]]:
    """Every `BakingParameters.set` of the golden, in order: (usage or None, key, value)."""
    scene = SCENES[golden.scene]
    common: list[tuple[str | None, str, Any]] = [
        (None, "OutputSize", [OUTPUT_SIZE_LOG2, OUTPUT_SIZE_LOG2]),
        (None, "DilationWidth", 0),
    ]
    common += [(None, key, value) for key, value in scene.common]
    return common + [(usage, key, value) for usage, key, value in golden.baker_parameters]


def instruction_steps(golden: Golden) -> list[dict[str, Any]]:
    scene = SCENES[golden.scene]
    calls: list[tuple[str, dict[str, Any]]] = [
        (
            ps.CREATE,
            {
                "mesh": scene.low,
                "normal_map_format": NORMAL_MAP_FORMAT,
                "default_texture_resolution": RESOLUTION,
            },
        )
    ]
    settings = parameters(golden)
    calls += [(ps.BAKING_SET, set_args(k, v)) for usage, k, v in settings if usage is None]
    if scene.high is not None:
        calls.append((ps.BAKING_SET, {"parameter": "HipolyMesh", "input": scene.high}))
    calls += [(ps.BAKING_SET, set_args(k, v, u)) for u, k, v in settings if u is not None]
    if golden.curvature_method is not None:
        calls.append((ps.BAKING_SET_CURVATURE_METHOD, {"method": golden.curvature_method}))
    calls.append((ps.BAKING_SET_ENABLED_BAKERS, {"usages": list(golden.usages)}))
    calls.append((ps.BAKE, {}))
    for file_format, depth in EXPORTS:
        calls.append(
            (
                EXPORT,
                {
                    "maps": list(golden.maps),
                    "file_format": file_format,
                    "bit_depth": depth,
                    "padding": PADDING,
                    "dithering": False,
                },
            )
        )
    return [{"step": n, "call": call, "args": args} for n, (call, args) in enumerate(calls, 1)]


def setting(name: str, value: Any, unit: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"name": name, "value": value, "applied_by": "recorder_api"}
    return item | ({"unit": unit} if unit else {})


def applied_settings(golden: Golden) -> list[dict[str, Any]]:
    applied = [
        setting("project.normal_map_format", NORMAL_MAP_FORMAT),
        setting("texture_set.resolution", RESOLUTION, "px"),
    ]
    for usage, key, value in parameters(golden):
        name = f"baking.{'common' if usage is None else usage}.{key}"
        if key == "OutputSize":
            applied.append(setting(name, OUTPUT_SIZE_LOG2, "log2 px"))
        else:
            applied.append(setting(name, value))
    if golden.curvature_method is not None:
        applied.append(setting("baking.curvature_method", golden.curvature_method))
    applied.append(setting("baking.enabled_bakers", ",".join(golden.usages)))
    applied += [setting(f"export.{fmt}.bit_depth", depth) for fmt, depth in EXPORTS]
    applied += [setting("export.padding", PADDING), setting("export.dithering", False)]
    return applied


def description(golden: Golden) -> str:
    scene = SCENES[golden.scene]
    swept = ", ".join(f"{usage} {key} {value}" for usage, key, value in golden.baker_parameters)
    if golden.curvature_method is not None:
        swept = ", ".join(filter(None, (f"CurvatureMethod {golden.curvature_method}", swept)))
    return (
        f"Tier 2b bake golden of {golden.task} (decision 384) on the analytic fixture "
        f"{golden.scene}: {scene.role}. Painter bakes {' and '.join(golden.usages)} at "
        f"{RESOLUTION} px (OutputSize 9, DilationWidth 0, "
        + ", ".join(f"{key} {value}" for key, value in scene.common)
        + (f"; {swept}" if swept else "")
        + "; every other baking parameter at Painter's default; normal map format OpenGL, "
        "tangent space the project default). The baked maps are exported as PNG 16 and OpenEXR "
        "32f, padding passthrough, no dithering; recorded twice (same session; after save and "
        "reopen). Bake backend uncontrolled."
    )


def painter_identity(root: Path = REPO_ROOT) -> dict[str, str]:
    entry = current_envelope(root)
    return {
        "product": PRODUCT,
        "version": str(entry["painter_version"]),
        "build_id": str(entry["painter_build"]),
    }


def manifest(golden: Golden, root: Path = REPO_ROOT) -> dict[str, Any]:
    return {
        "schema": "uzpainter/parity/golden-public/1",
        "record_class": "public_manifest",
        "golden_id": golden.golden_id,
        "tier": "2b",
        "domain": f"bake_map/{golden.usages[-1].lower()}",
        "description": description(golden),
        "inputs": inputs(SCENES[golden.scene]),
        "instruction_sequence": {
            "author": "UzmiGames",
            "interface": "substance_painter_documented_python_api",
            "steps": instruction_steps(golden),
        },
        "applied_settings": applied_settings(golden),
        "uncontrolled_settings": list(UNCONTROLLED),
        "expectations": [],
        "software": {"painter": painter_identity(root), "uzpainter_build_hash": None},
        "private_records": [],
    }


def requests_dir(root: Path = REPO_ROOT) -> Path:
    return manifest_root(current_envelope(root), root).parent / "requests" / FAMILY


def request_path(golden: Golden, root: Path = REPO_ROOT) -> Path:
    return requests_dir(root) / f"{golden.name}.json"


def write_requests(root: Path = REPO_ROOT) -> list[Path]:
    """Write every golden's request under the current envelope (a request names no records)."""
    written = []
    for golden in GOLDENS:
        path = request_path(golden, root)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(manifest(golden, root), indent=2) + "\n"
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    return written
