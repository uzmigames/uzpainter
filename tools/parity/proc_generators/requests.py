"""Recording requests of the mesh-map generator goldens (`phase3.2_proc-generator-families`).

One golden is one Painter project on one mesh at one resolution, holding up to eight cases of one
generator:

1. `project.create` on the mesh at the resolution; Painter bakes the mesh maps low as high
   (`OutputSize` the resolution, `LowAsHigh` on, every other baking parameter at Painter's
   default; bakers Normal, WorldSpaceNormal, AO, Curvature, Position, Thickness).
2. Channels User0..User<n-1> are added as L32F. A base fill writes 0 (Raw) into each.
3. Case k is a fill above it that writes 1 (Raw) into User<k> only, under a black mask that
   holds the generator with the case's parameters (`set_parameters`, the seed as `$randomseed`).
   User<k> therefore holds the generator's mask value: 0 (1 - m) + 1 m.
4. Each User<k> map and the six baked mesh maps are exported as OpenEXR 32f, no padding
   (`passthrough`), no dithering. The mesh maps are the case inputs: exactly the maps the
   generator read, as stored.

Recorded twice by `python -m tools.parity.recorder record` (r1; r2 after save and reopen). The
requests go under the current envelope's `requests/phase3/proc-generators/`. Parameter names are
the ones the documented `Property` API reports (`parity/semantics/proc-generator-parameters.json`,
item 2.1); the values are authored here.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.parity.envelope.registry import current_envelope, envelope_directory
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT, sha256_file
from tools.parity.schemas import REPO_ROOT

FAMILY = "phase3/proc-generators"
TASK = "phase3.2_proc-generator-families"
NORMAL_MAP_FORMAT = "OpenGL"
PADDING = "passthrough"
PRODUCT = "Adobe Substance 3D Painter"
CHANNEL_FORMAT = "L32F"
MAX_CASES = 8  # User0..User7
SEED_PARAMETER = "$randomseed"
LS = "substance_painter.layerstack."
BAKERS = ("Normal", "WorldSpaceNormal", "AO", "Curvature", "Position", "Thickness")
# The exported mesh map of each usage a case reads (export map name, channel layout).
MESH_MAPS: dict[str, str] = {
    "Normal": "meshMap/normal_base:RGB",
    "WorldSpaceNormal": "meshMap/world_space_normals:RGB",
    "AO": "meshMap/ambient_occlusion:L",
    "Curvature": "meshMap/curvature:L",
    "Position": "meshMap/position:RGB",
    "Thickness": "meshMap/thickness:L",
}
UNCONTROLLED = ["preferences.bake_backend"]


@dataclass(frozen=True)
class Mesh:
    name: str
    path: str  # repository path of the authored mesh, or its Assets3D path with `sha256`
    mesh_class: str
    role: str
    sha256: str | None = None  # an Assets3D input's pinned hash; None for a repository file


MESHES = {
    "sphere": Mesh(
        "sphere",
        "parity/fixtures/feasibility/sphere.obj",
        "sphere",
        "the authored unit sphere (longitude/latitude UVs)",
    ),
    "rounded-cube": Mesh(
        "rounded-cube",
        "parity/fixtures/feasibility/rounded-cube.obj",
        "bevelled-cube",
        "the authored unit cube with edges and corners rounded at radius 0.1 (six UV islands)",
    ),
    # Hat v6 low is lost (decision 260: only the v8 project survives); the delivered hat v8 low
    # mesh is the garment-class stand-in. Git-ignored in Assets3D, so it is kept in the private
    # store as an input (decision 144) and recorded with `--assets-root`.
    "hat-v8": Mesh(
        "hat-v8",
        "Creatures/Undead/Skeletal Mage/Models3D/10-Chapeu/Export/10-Chapeu-v8.fbx",
        "garment",
        "the delivered Skeletal Mage hat v8 low mesh (one UV tile)",
        "4b860d91dc999aa96abf61326fda090ab9ee386299318ee4b6f1734c872a4a2b",
    ),
}
ASSETS3D_LICENCE = "LicenseRef-UzmiGames-Assets3D"


@dataclass(frozen=True)
class GeneratorCase:
    case_id: str
    painter_name: str  # the generator's GUI name in Painter (05 §3 compatibility alias)
    parameters: tuple[tuple[str, Any], ...] = ()  # in set order; the seed is `seed`
    seed: int | None = None  # None: the generator's default seed, not set


@dataclass(frozen=True)
class Golden:
    stage: str  # e.g. "diagnostic", "calibration", "held-out"
    generator: str  # UzPainter family id, e.g. "curvature", or "mixed" for several
    mesh: str
    resolution: int
    cases: tuple[GeneratorCase, ...] = field(default=())

    @property
    def name(self) -> str:
        return f"{self.stage}-{self.generator}-{self.mesh}-{self.resolution}"

    @property
    def golden_id(self) -> str:
        return f"{FAMILY}/{self.name}"


def check(golden: Golden) -> None:
    if not 1 <= len(golden.cases) <= MAX_CASES:
        raise ValueError(f"{golden.name}: 1 to {MAX_CASES} cases, not {len(golden.cases)}")
    if golden.mesh not in MESHES:
        raise ValueError(f"{golden.name}: unknown mesh {golden.mesh!r}")
    log2 = math.log2(golden.resolution)
    if log2 != int(log2) or not 7 <= log2 <= 12:
        raise ValueError(f"{golden.name}: resolution {golden.resolution} is not 128..4096")
    ids = [case.case_id for case in golden.cases]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{golden.name}: duplicate case ids")
    for case in golden.cases:
        names = [name for name, _ in case.parameters]
        if SEED_PARAMETER in names or len(set(names)) != len(names):
            raise ValueError(f"{golden.name}/{case.case_id}: seed in parameters or a duplicate")


class Steps:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []

    def add(self, call: str, **args: Any) -> int:
        number = len(self.steps) + 1
        self.steps.append({"step": number, "call": call, "args": args})
        return number


def user(k: int) -> str:
    return f"User{k}"


def case_map(k: int) -> str:
    return f"documentMap/user{k}:L"


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
    steps.add(ps.BAKING_SET, parameter="OutputSize", value=[log2, log2])
    steps.add(ps.BAKING_SET, parameter="LowAsHigh", value=True)
    steps.add(ps.BAKING_SET_ENABLED_BAKERS, usages=list(BAKERS))
    steps.add(ps.BAKE)
    channels = [user(k) for k in range(len(golden.cases))]
    for channel in channels:
        steps.add(ps.ADD_CHANNEL, channel=channel, format=CHANNEL_FORMAT)
    base = steps.add(LS + "insert_fill", position="top")
    steps.add(LS + "FillLayerNode.active_channels", node_step=base, channels=channels)
    for channel in channels:
        steps.add(
            LS + "FillLayerNode.set_source",
            node_step=base,
            channel=channel,
            color=[0.0, 0.0, 0.0],
            color_space="Raw",
        )
    below = base
    for k, case in enumerate(golden.cases):
        fill = steps.add(LS + "insert_fill", above_step=below)
        below = fill
        steps.add(LS + "FillLayerNode.active_channels", node_step=fill, channels=[user(k)])
        steps.add(
            LS + "FillLayerNode.set_source",
            node_step=fill,
            channel=user(k),
            color=[1.0, 1.0, 1.0],
            color_space="Raw",
        )
        steps.add(LS + "LayerNode.add_mask", node_step=fill, background="Black")
        generator = steps.add(
            LS + "insert_generator_effect",
            inside_step=fill,
            stack="Mask",
            resource_name=case.painter_name,
            resource_usage="GENERATOR",
        )
        values = list(case.parameters)
        if case.seed is not None:
            values.append((SEED_PARAMETER, case.seed))
        for name, value in values:
            steps.add(
                "substance_painter.source.SourceSubstance.set_parameters",
                node_step=generator,
                parameter=name,
                value=value,
            )
    maps = [case_map(k) for k in range(len(golden.cases))] + [MESH_MAPS[u] for u in BAKERS]
    steps.add(
        EXPORT, maps=maps, file_format="exr", bit_depth="32f", padding=PADDING, dithering=False
    )
    return steps.steps


def setting(name: str, value: Any, unit: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"name": name, "value": value, "applied_by": "recorder_api"}
    return item | ({"unit": unit} if unit else {})


def applied_settings(golden: Golden) -> list[dict[str, Any]]:
    return [
        setting("project.normal_map_format", NORMAL_MAP_FORMAT),
        setting("texture_set.resolution", golden.resolution, "px"),
        setting("baking.common.OutputSize", int(math.log2(golden.resolution)), "log2 px"),
        setting("baking.common.LowAsHigh", True),
        setting("baking.enabled_bakers", ",".join(BAKERS)),
        setting("export.exr.bit_depth", "32f"),
        setting("export.padding", PADDING),
        setting("export.dithering", False),
    ]


def case_text(k: int, case: GeneratorCase) -> str:
    values = [f"{name} = {value}" for name, value in case.parameters]
    if case.seed is not None:
        values.append(f"{SEED_PARAMETER} = {case.seed}")
    settings = ", ".join(values) or "defaults"
    return f"User{k} {case.case_id}: {case.painter_name} ({settings})"


def description(golden: Golden) -> str:
    mesh = MESHES[golden.mesh]
    cases = "; ".join(case_text(k, case) for k, case in enumerate(golden.cases))
    log2 = int(math.log2(golden.resolution))
    return (
        f"Mesh-map generator golden of {TASK} ({golden.stage}): the {golden.generator} "
        f"generator cases on {mesh.role}, texture set {golden.resolution} px. Painter bakes "
        f"the mesh maps low as high (OutputSize {log2}, LowAsHigh, bakers "
        f"{', '.join(BAKERS)}, every other baking parameter at Painter's default). Each case "
        "is a white Raw fill on its own L32F User channel, over a black base fill, under a black "
        f"mask holding the generator: {cases}. The User maps and the six baked mesh maps are "
        "exported as OpenEXR 32f, padding passthrough, no dithering; recorded twice (same "
        "session; after save and reopen). Bake backend uncontrolled."
    )


def mesh_input(mesh: Mesh, root: Path = REPO_ROOT) -> dict[str, Any]:
    if mesh.sha256 is None:
        return {
            "input_id": mesh.name,
            "kind": "mesh",
            "path": mesh.path,
            "sha256": sha256_file(root / mesh.path),
            "provenance": {"origin": "uzmigames_authored", "licence": "Apache-2.0"},
        }
    return {
        "input_id": mesh.name,
        "kind": "mesh",
        "assets3d_path": mesh.path,
        "sha256": mesh.sha256,
        "provenance": {"origin": "uzmigames_authored", "licence": ASSETS3D_LICENCE},
    }


def manifest(golden: Golden, root: Path = REPO_ROOT) -> dict[str, Any]:
    check(golden)
    mesh = MESHES[golden.mesh]
    envelope = current_envelope(root)
    build = envelope["painter_build"]
    return {
        "schema": "uzpainter/parity/golden-public/1",
        "record_class": "public_manifest",
        "golden_id": golden.golden_id,
        "tier": "2a",
        "domain": f"procedural_asset/generator/{golden.generator}",
        "description": description(golden),
        "inputs": [mesh_input(mesh, root)],
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
                "build_id": build,
            },
            "uzpainter_build_hash": None,
        },
        "private_records": [],
    }


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
