"""Recording requests of the grunge goldens (`phase3.2_proc-grunge-families`).

One golden is one Painter project on the authored plane (UVs 0..1, one tile) at one resolution,
holding up to eight grunge cases:

1. `project.create` on the plane at the resolution.
2. Channels User0..User<n-1> are added as L32F. A base fill writes 0 (Raw) into each.
3. Case k is a fill above it that writes 1 (Raw) into User<k> only, under a black mask holding a
   fill effect whose source is the grunge (`FillEffectNode.set_source`, mask channel null), with
   the case's parameters and seed (`$randomseed`) set on that source. User<k> therefore holds the
   grunge's mask value: 0 (1 - m) + 1 m. The fill's UV projection stays Painter's default.
4. Each User<k> map is exported as OpenEXR 32f, no padding (`passthrough`), no dithering.

No mesh map is baked: a grunge reads none. Recorded twice by `python -m tools.parity.recorder
record` (r1; r2 after save and reopen). The readback of each `set_source` describes every
`Property` of the grunge's source (value, label, widget type, metadata): the parameter discovery
of item 2.2, private like every readback. The requests go under the current envelope's
`requests/phase3/proc-grunges/`.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.parity.envelope.registry import current_envelope, envelope_directory
from tools.parity.proc_generators.requests import (
    CHANNEL_FORMAT,
    LS,
    MAX_CASES,
    NORMAL_MAP_FORMAT,
    PADDING,
    PRODUCT,
    SEED_PARAMETER,
    Mesh,
    Steps,
    case_map,
    mesh_input,
    setting,
    user,
)
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT
from tools.parity.schemas import REPO_ROOT

FAMILY = "phase3/proc-grunges"
TASK = "phase3.2_proc-grunge-families"
PLANE = Mesh(
    "plane",
    "parity/fixtures/meshes/plane.obj",
    "plane",
    "the authored 20 cm plane (UVs 0..1, one tile)",
)
_STARTER = "resource://starter_assets/"
# The starter-asset survey of 2026-11-08 (Painter 12.2.0, `tools.parity.recorder.substance_survey`,
# private survey SHA-256 68d59fea6ba7...): UzPainter asset id -> (folder, name, version). The
# shelf of 12.2.0 lists the plain `bnw_spots_3`, `dirt_1`, `grunge_map_009` and `grunge_map_012`;
# the hat recipe recorded their "ratio" variants from its own project (inventory, item 2.1).
_VERSIONS = {
    "rock": ("grunge_rock", "grunge_rock", "5d95a51fa6ba5ebce1af058642b8bac869b72a70"),
    "stone-details": (
        "grunge_stone_details",
        "grunge_stone_details",
        "cff05d984d7468b0c3467dc3e96207c08a3f773d",
    ),
    "dirt-large": (
        "grunge_dirt_large",
        "grunge_dirt_large",
        "a3422c5859b29fa52c778829320ec8aa6a39f724",
    ),
    "dirt-spots-small": (
        "dirt_spots_dense_small",
        "dirt_spots_dense_small",
        "7632fdb9e1b055c3fce5554f5c2655b7d163d1d3",
    ),
    "spots-bw-a": ("noise_bnw_spots_2", "bnw_spots_2", "819c8c6c19ff20ad1c6b9464df87e0191800924c"),
    "spots-bw-b": ("noise_bnw_spots_3", "bnw_spots_3", "e6abf615277e09294a6e028e65119800a3dda994"),
    "dirt-a": ("noise_dirt_1", "dirt_1", "4161f7cc8a279c2ba9ae4b5cc7f1ef03a45aa99f"),
    "scratches-fine": (
        "grunge_scratches_fine",
        "grunge_scratches_fine",
        "b25239c1aef3a3ad47bd2c39b43011b094428d5b",
    ),
    "scratches": (
        "grunge_scratches",
        "grunge_scratches",
        "225c3fa989054e5800eb05b317855ecf5d9c1911",
    ),
    "scratches-dirty": (
        "grunge_scratches_dirty",
        "grunge_scratches_dirty",
        "c4fd78c8acc37f9fb7453778d17158f09ccd10b3",
    ),
    "rust-fine": (
        "grunge_rust_fine",
        "grunge_rust_fine",
        "732ff219a6c1bce1dd587cbf33f9222f0d98d4b1",
    ),
    "humidity": ("grunge_humidity", "grunge_humidity", "3aa3318473d0178d2b76070086bd77322b126ff8"),
    "map-a": ("noise_grunge_map_009", "grunge_map_009", "bc0ba172edae0258392468d44e91458dbb455011"),
    "map-b": ("noise_grunge_map_012", "grunge_map_012", "facd9911228b5e1f7f6342f0a35222005be71bf5"),
    "spots-soft": (
        "noise_gaussian_spots_2",
        "gaussian_spots_2",
        "33829a8fe873a56d2e79b00c7f9f6428feff6306",
    ),
    "cracks-leather": (
        "cracks_leather",
        "cracks_leather",
        "a3a6e3487860644d83789421dc644a294e481c33",
    ),
    "linen": ("fabric_linen", "fabric_linen", "7fa9d3720c64d4a797642fc3933c271befe7c247"),
}
GRUNGE_URLS = {
    asset: f"{_STARTER}{folder}/{name}?version={version}.sbsar"
    for asset, (folder, name, version) in _VERSIONS.items()
}


@dataclass(frozen=True)
class GrungeCase:
    case_id: str
    asset: str  # UzPainter grunge id (`uzasset://grunge/<id>@1`)
    parameters: tuple[tuple[str, Any], ...] = ()  # Painter names, in set order
    seed: int | None = None  # None: the source's default seed, not set


@dataclass(frozen=True)
class Golden:
    stage: str  # "diagnostic", "calibration", "held-out"
    label: str
    resolution: int
    cases: tuple[GrungeCase, ...] = field(default=())

    @property
    def name(self) -> str:
        return f"{self.stage}-{self.label}-plane-{self.resolution}"

    @property
    def golden_id(self) -> str:
        return f"{FAMILY}/{self.name}"


def check(golden: Golden) -> None:
    if not 1 <= len(golden.cases) <= MAX_CASES:
        raise ValueError(f"{golden.name}: 1 to {MAX_CASES} cases, not {len(golden.cases)}")
    log2 = math.log2(golden.resolution)
    if log2 != int(log2) or not 7 <= log2 <= 12:
        raise ValueError(f"{golden.name}: resolution {golden.resolution} is not 128..4096")
    ids = [case.case_id for case in golden.cases]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{golden.name}: duplicate case ids")
    for case in golden.cases:
        if case.asset not in GRUNGE_URLS:
            raise ValueError(f"{golden.name}/{case.case_id}: unknown grunge {case.asset!r}")
        names = [name for name, _ in case.parameters]
        if SEED_PARAMETER in names or len(set(names)) != len(names):
            raise ValueError(f"{golden.name}/{case.case_id}: seed in parameters or a duplicate")


def instruction_steps(golden: Golden) -> list[dict[str, Any]]:
    check(golden)
    steps = Steps()
    steps.add(
        ps.CREATE,
        mesh=PLANE.name,
        normal_map_format=NORMAL_MAP_FORMAT,
        default_texture_resolution=golden.resolution,
    )
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
        effect = steps.add(LS + "insert_fill", inside_step=fill, stack="Mask")
        steps.add(
            ps.SET_EFFECT_SOURCE, node_step=effect, channel=None, resource=GRUNGE_URLS[case.asset]
        )
        values = list(case.parameters)
        if case.seed is not None:
            values.append((SEED_PARAMETER, case.seed))
        for name, value in values:
            steps.add(
                ps.SET_PARAMETERS, node_step=effect, channel=None, parameter=name, value=value
            )
    maps = [case_map(k) for k in range(len(golden.cases))]
    steps.add(
        EXPORT, maps=maps, file_format="exr", bit_depth="32f", padding=PADDING, dithering=False
    )
    return steps.steps


def applied_settings(golden: Golden) -> list[dict[str, Any]]:
    return [
        setting("project.normal_map_format", NORMAL_MAP_FORMAT),
        setting("texture_set.resolution", golden.resolution, "px"),
        setting("export.exr.bit_depth", "32f"),
        setting("export.padding", PADDING),
        setting("export.dithering", False),
    ]


def case_text(k: int, case: GrungeCase) -> str:
    values = [f"{name} = {value}" for name, value in case.parameters]
    if case.seed is not None:
        values.append(f"{SEED_PARAMETER} = {case.seed}")
    settings = ", ".join(values) or "defaults"
    return f"User{k} {case.case_id}: {GRUNGE_URLS[case.asset]} ({settings})"


def description(golden: Golden) -> str:
    cases = "; ".join(case_text(k, case) for k, case in enumerate(golden.cases))
    return (
        f"Grunge golden of {TASK} ({golden.stage}): grunge cases on {PLANE.role}, texture set "
        f"{golden.resolution} px, no bake. Each case is a white Raw fill on its own L32F User "
        "channel, over a black base fill, under a black mask holding a fill effect whose source "
        f"is the grunge, at the fill's default UV projection: {cases}. The User maps are "
        "exported as OpenEXR 32f, padding passthrough, no dithering; recorded twice (same "
        "session; after save and reopen)."
    )


def manifest(golden: Golden, root: Path = REPO_ROOT) -> dict[str, Any]:
    check(golden)
    envelope = current_envelope(root)
    return {
        "schema": "uzpainter/parity/golden-public/1",
        "record_class": "public_manifest",
        "golden_id": golden.golden_id,
        "tier": "2a",
        "domain": f"procedural_asset/grunge/{golden.label}",
        "description": description(golden),
        "inputs": [mesh_input(PLANE, root)],
        "instruction_sequence": {
            "author": "UzmiGames",
            "interface": "substance_painter_documented_python_api",
            "steps": instruction_steps(golden),
        },
        "applied_settings": applied_settings(golden),
        "uncontrolled_settings": [],
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
