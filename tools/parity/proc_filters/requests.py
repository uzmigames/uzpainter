"""Recording requests of the filter goldens (`phase3.2_proc-filter-families`).

One golden is one Painter project on one mesh at one resolution:

1. `project.create` on the mesh at the resolution.
2. Channels User0..User<n> are added (L32F, or RGB32F for an RGB golden).
3. The golden's content bitmap (`fixtures.py`) is imported as a project texture.
4. User0 is the content: a fill writing the bitmap into User0 only, UV projection with the
   bitmap tiled resolution / 256 times (one bitmap texel per texture texel), Nearest filtering.
5. Case k is a fill above it writing the same bitmap, the same way, into User<k> only, with one
   content effect: the starter-asset filter found by its documented resource search, its active
   channels User<k>, and the case's parameters (`set_parameters`); or a native levels effect on
   User<k> with the case's levels parameters.
6. Painter bakes World Space Normals low as high (`OutputSize` the resolution, `DilationWidth`
   0, every other baking parameter at Painter's default). Baked with no dilation, the map marks
   Painter's own UV coverage (decision 423 §1); it is the last state step, as in the generator
   goldens (a bake leaves Painter in its Baking mode, which has no active stack).
7. Every User map and the World Space Normals map are exported as OpenEXR 32f, padding
   `passthrough`, no dithering.

Recorded twice by `python -m tools.parity.recorder record` (r1; r2 after save and reopen). The
requests go under the current envelope's `requests/phase3/proc-filters/`. Parameter names are the
ones the documented `Property` API reports (item 2.1,
`docs/analysis/proc-filter-families/01-parameter-discovery.md`); the values are authored here.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.parity.envelope.registry import current_envelope, envelope_directory
from tools.parity.proc_filters import fixtures
from tools.parity.proc_generators.requests import MESHES, Steps, mesh_input, setting
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT, sha256_file
from tools.parity.schemas import REPO_ROOT

FAMILY = "phase3/proc-filters"
TASK = "phase3.2_proc-filter-families"
NORMAL_MAP_FORMAT = "OpenGL"
PADDING = "passthrough"
PRODUCT = "Adobe Substance 3D Painter"
MAX_CHANNELS = 8  # User0..User7
UNCONTROLLED = ["preferences.bake_backend"]
FIXTURE_DIR = "parity/fixtures/proc-filters"
CONTENT: dict[str, tuple[str, Any]] = {
    "content-grey": (f"{FIXTURE_DIR}/content-grey.png", fixtures.content_grey),
    "content-rgb": (f"{FIXTURE_DIR}/content-rgb.png", fixtures.content_rgb),
}
# Documented search syntax (the Tier 0 `effect-order` golden's form): GUI name, exact match; a
# name with a space is quoted (`n:Grayscale Conversion=` finds nothing).
FILTER_SEARCH = "s:starterassets u:filter n:{name}="


def filter_search(painter_name: str) -> str:
    name = f'"{painter_name}"' if " " in painter_name else painter_name
    return FILTER_SEARCH.format(name=name)


LEVELS = "levels"  # a case that is the native levels effect, not a starter-asset filter
WSN_MAP = "meshMap/world_space_normals:RGB"


@dataclass(frozen=True)
class FilterCase:
    case_id: str
    painter_name: str  # the filter's GUI name in Painter, or LEVELS
    parameters: tuple[tuple[str, Any], ...] = ()  # in set order


@dataclass(frozen=True)
class Golden:
    stage: str  # "diagnostic", "calibration" or "held-out"
    family: str  # UzPainter family id, e.g. "sharpen", or "mixed"
    mesh: str
    resolution: int
    cases: tuple[FilterCase, ...] = field(default=())
    content: str = "content-grey"
    channel_format: str = "L32F"

    @property
    def name(self) -> str:
        return f"{self.stage}-{self.family}-{self.mesh}-{self.resolution}"

    @property
    def golden_id(self) -> str:
        return f"{FAMILY}/{self.name}"

    @property
    def layout(self) -> str:
        return "L" if self.channel_format.startswith("L") else "RGB"


def check(golden: Golden) -> None:
    if not 1 <= len(golden.cases) <= MAX_CHANNELS - 1:
        raise ValueError(f"{golden.name}: 1 to {MAX_CHANNELS - 1} cases, not {len(golden.cases)}")
    if golden.mesh not in MESHES:
        raise ValueError(f"{golden.name}: unknown mesh {golden.mesh!r}")
    if golden.content not in CONTENT:
        raise ValueError(f"{golden.name}: unknown content {golden.content!r}")
    if golden.channel_format not in ("L32F", "RGB32F"):
        raise ValueError(f"{golden.name}: channel format {golden.channel_format!r}")
    log2 = math.log2(golden.resolution)
    if log2 != int(log2) or not 8 <= log2 <= 12:
        raise ValueError(f"{golden.name}: resolution {golden.resolution} is not 256..4096")
    ids = [case.case_id for case in golden.cases]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{golden.name}: duplicate case ids")
    for case in golden.cases:
        names = [name for name, _ in case.parameters]
        if len(set(names)) != len(names):
            raise ValueError(f"{golden.name}/{case.case_id}: a parameter set twice")


def user(k: int) -> str:
    return f"User{k}"


def content_fill(
    steps: Steps, golden: Golden, channel: str, resource: int, below: int | None
) -> int:
    position: dict[str, Any] = {"position": "top"} if below is None else {"above_step": below}
    fill = steps.add(ps.INSERT_FILL, **position)
    steps.add(ps.SET_ACTIVE_CHANNELS, node_step=fill, channels=[channel])
    steps.add(ps.SET_SOURCE, node_step=fill, channel=channel, resource_step=resource)
    tiles = float(golden.resolution // fixtures.SIZE)
    steps.add(
        ps.SET_PROJECTION,
        node_step=fill,
        filtering_mode="Nearest",
        uv_wrapping_mode="Repeat",
        scale_mode="Factors",
        scale=[tiles, tiles],
        rotation=0.0,
        offset=[0.0, 0.0],
    )
    return fill


def effect_steps(steps: Steps, fill: int, channel: str, case: FilterCase) -> None:
    inside = {"inside_step": fill, "stack": "Content"}
    if case.painter_name == LEVELS:
        levels = steps.add(ps.INSERT_LEVELS, **inside)
        steps.add(ps.SET_LEVELS_CHANNEL, node_step=levels, channel=channel)
        if case.parameters:
            steps.add(ps.SET_LEVELS, node_step=levels, **dict(case.parameters))
        return
    effect = steps.add(ps.INSERT_FILTER, filter_search=filter_search(case.painter_name), **inside)
    steps.add(ps.SET_FILTER_CHANNELS, node_step=effect, channels=[channel])
    for name, value in case.parameters:
        steps.add(ps.SET_PARAMETERS, node_step=effect, parameter=name, value=value)


def instruction_steps(golden: Golden) -> list[dict[str, Any]]:
    check(golden)
    log2 = int(math.log2(golden.resolution))
    steps = Steps()
    steps.add(
        ps.CREATE,
        mesh=golden.mesh,
        normal_map_format=NORMAL_MAP_FORMAT,
        default_texture_resolution=golden.resolution,
    )
    count = 1 + len(golden.cases)
    for k in range(count):
        steps.add(ps.ADD_CHANNEL, channel=user(k), format=golden.channel_format)
    resource = steps.add(ps.IMPORT_RESOURCE, input=golden.content, usage="TEXTURE")
    below = content_fill(steps, golden, user(0), resource, None)
    for k, case in enumerate(golden.cases, start=1):
        below = content_fill(steps, golden, user(k), resource, below)
        effect_steps(steps, below, user(k), case)
    # The bake comes last: it leaves Painter in its Baking mode, which has no active stack.
    steps.add(ps.BAKING_SET, parameter="OutputSize", value=[log2, log2])
    steps.add(ps.BAKING_SET, parameter="LowAsHigh", value=True)
    steps.add(ps.BAKING_SET, parameter="DilationWidth", value=0)
    steps.add(ps.BAKING_SET_ENABLED_BAKERS, usages=["WorldSpaceNormal"])
    steps.add(ps.BAKE)
    maps = [f"documentMap/user{k}:{golden.layout}" for k in range(count)] + [WSN_MAP]
    steps.add(
        EXPORT, maps=maps, file_format="exr", bit_depth="32f", padding=PADDING, dithering=False
    )
    return steps.steps


def applied_settings(golden: Golden) -> list[dict[str, Any]]:
    return [
        setting("project.normal_map_format", NORMAL_MAP_FORMAT),
        setting("texture_set.resolution", golden.resolution, "px"),
        setting("baking.common.OutputSize", int(math.log2(golden.resolution)), "log2 px"),
        setting("baking.common.LowAsHigh", True),
        setting("baking.common.DilationWidth", 0),
        setting("baking.enabled_bakers", "WorldSpaceNormal"),
        setting("export.exr.bit_depth", "32f"),
        setting("export.padding", PADDING),
        setting("export.dithering", False),
    ]


def case_text(k: int, case: FilterCase) -> str:
    settings = ", ".join(f"{name} = {value}" for name, value in case.parameters) or "defaults"
    what = "the native levels effect" if case.painter_name == LEVELS else case.painter_name
    return f"User{k} {case.case_id}: {what} ({settings})"


def description(golden: Golden) -> str:
    mesh = MESHES[golden.mesh]
    cases = "; ".join(case_text(k, case) for k, case in enumerate(golden.cases, start=1))
    tiles = golden.resolution // fixtures.SIZE
    log2 = int(math.log2(golden.resolution))
    return (
        f"Filter golden of {TASK} ({golden.stage}): {golden.family} cases on {mesh.role}, "
        f"texture set {golden.resolution} px, {golden.channel_format} User channels. Every User "
        f"channel is a fill of the authored {golden.content} bitmap (UV projection, tiled "
        f"{tiles} x {tiles}, Nearest, so one bitmap texel per texel); User0 is that content "
        "alone, and each case adds one content effect on its own channel, the starter-asset "
        "filter found by the documented search s:starterassets u:filter n:<name>= with the "
        f"case's parameters, or the native levels effect: {cases}. Painter then bakes World "
        f"Space Normals low as high (OutputSize {log2}, LowAsHigh, DilationWidth 0, every other "
        "baking parameter at Painter's default) to mark its UV coverage. The User maps and the "
        "World Space Normals map are exported as OpenEXR 32f, padding passthrough, no "
        "dithering; recorded twice (same session; after save and reopen). Bake backend "
        "uncontrolled."
    )


def content_input(content: str, root: Path = REPO_ROOT) -> dict[str, Any]:
    path, _ = CONTENT[content]
    return {
        "input_id": content,
        "kind": "image",
        "path": path,
        "sha256": sha256_file(root / path),
        "provenance": {"origin": "uzmigames_authored", "licence": "Apache-2.0"},
    }


def manifest(golden: Golden, root: Path = REPO_ROOT) -> dict[str, Any]:
    check(golden)
    envelope = current_envelope(root)
    return {
        "schema": "uzpainter/parity/golden-public/1",
        "record_class": "public_manifest",
        "golden_id": golden.golden_id,
        "tier": "2a",
        "domain": f"procedural_asset/filter/{golden.family}",
        "description": description(golden),
        "inputs": [mesh_input(MESHES[golden.mesh], root), content_input(golden.content, root)],
        "instruction_sequence": {
            "author": "UzmiGames",
            "interface": "substance_painter_documented_python_api",
            "steps": instruction_steps(golden),
        },
        "applied_settings": applied_settings(golden),
        "uncontrolled_settings": list(UNCONTROLLED),
        "expectations": [],
        "software": {
            "painter": {
                "product": PRODUCT,
                "version": envelope["painter_version"],
                "build_id": envelope["painter_build"],
            },
            "uzpainter_build_hash": None,
        },
        "private_records": [],
    }


def write_fixtures(root: Path = REPO_ROOT) -> list[Path]:
    """Write each content bitmap; an existing one must be byte-equal."""
    written = []
    for path, make in CONTENT.values():
        target = root / path
        data = make()
        if target.exists() and target.read_bytes() != data:
            raise ValueError(f"{target}: an authored fixture changed")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append(target)
    return written


def request_dir(root: Path = REPO_ROOT) -> Path:
    envelope = current_envelope(root)
    directory = envelope_directory(envelope["envelope_id"])
    return root / "parity" / "envelopes" / directory / "requests" / FAMILY


def write_requests(goldens: Sequence[Golden], root: Path = REPO_ROOT) -> list[Path]:
    """Write each golden's request; an existing request must be byte-equal (requests are
    authored once: a changed recipe gets a new golden name)."""
    written: list[Path] = []
    directory = request_dir(root)
    for golden in goldens:
        path = directory / f"{golden.name}.json"
        text = json.dumps(manifest(golden, root), indent=2) + "\n"
        if path.exists() and path.read_text(encoding="utf-8") != text:
            raise ValueError(f"{path}: an authored request changed; name a new golden")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    return written
