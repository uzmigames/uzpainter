"""Channel exports of the felt and leather grain material fills (`phase3.3_procedural-families`
item 2.16, decision 431).

Each golden is one default material fill of `fabric_felt` or `leather_grain` alone over the
empty stack of the plane at 128 px, OpenGL, Legacy: the fill's active channels, then the
BaseColor, BaseMetalness, SpecularRoughness, Normal and Height channels as OpenEXR 32f with
passthrough padding and no dithering, repeated after save/reopen. The `-preset` goldens apply
the material's first preset, chosen in Painter by index, and are the held-out outputs of the
L8 rule (fitted on the default fills of the 2026-11-11 survey). They are recorded by
`tests/python/capture_material_channels_session.py` in the Painter session whose
`assets snapshot` captures fill the destination project they are compared with (decision 431).

Nothing about the assets is authored beyond their URLs: no parameter, preset or output name.

    python -m tools.parity.tier0_semantics.material_channels write   # commit the requests
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence as Args
from typing import Any

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import EXPORT
from tools.parity.recorder.material_survey import MATERIAL_URLS
from tools.parity.tier0_semantics.corpus import Golden, Sequence, manifest, start
from tools.parity.tier0_semantics.source_substance_control import PLANE_SHA256, _pin
from tools.parity.tier0_semantics.source_substance_presets import PREFIX, SET_MATERIAL_SOURCE

PREFIX_NAME = "material-channels-"
MAPS = [
    "documentMap/basecolor:RGB",
    "documentMap/basemetalness:L",
    "documentMap/specularroughness:L",
    "documentMap/normal:RGB",
    "documentMap/height:L",
]
# Each golden: (family, whether the first preset is applied).
STATES: dict[str, tuple[str, bool]] = {
    "felt": ("felt", False),
    "leather-grain": ("leather-grain", False),
    "felt-preset": ("felt", True),
    "leather-grain-preset": ("leather-grain", True),
}


def request(state: str) -> dict[str, Any]:
    family, preset = STATES[state]
    name = PREFIX_NAME + state
    sequence: Sequence = start("plane", resolution=128)
    fill = sequence.add(ps.INSERT_FILL, position="top")
    sequence.add(SET_MATERIAL_SOURCE, node_step=fill, resource_url=MATERIAL_URLS[family])
    if preset:
        sequence.add(PREFIX + "apply_preset", node_step=fill, material=True, preset_index=0)
    sequence.add(ps.GET_ACTIVE_CHANNELS, node_step=fill)
    sequence.add(
        EXPORT,
        maps=list(MAPS),
        file_format="exr",
        bit_depth="32f",
        padding="passthrough",
        dithering=False,
    )
    description = (
        "Item 2.16 (decision 431): the starter material "
        + family
        + " alone as a fill's material source over the empty stack, "
        + ("with its first preset (chosen in Painter by index) applied, " if preset else "")
        + "its active channels, then the BaseColor, BaseMetalness, SpecularRoughness, Normal and "
        "Height channels as OpenEXR 32f with passthrough padding and no dithering, repeated after "
        "save/reopen. Recorded in the Painter session that captured the destination's snapshots."
    )
    result = manifest(
        Golden(name, "tier0/api-probes/" + name, description, "plane", ["plane"], sequence),
        {"plane": PLANE_SHA256},
    )
    result["golden_id"] = "tier0/api-probes/" + name
    return _pin(result)


def requests() -> dict[str, dict[str, Any]]:
    """Every item-2.16 request by name."""
    return {PREFIX_NAME + state: request(state) for state in STATES}


def main(argv: Args[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["write"]:
        print("usage: python -m tools.parity.tier0_semantics.material_channels write")
        return 2
    root = manifest_root(current_envelope()).parent / "requests/tier0/api-probes"
    for name, built in requests().items():
        (root / f"{name}.json").write_text(
            json.dumps(built, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(root / f"{name}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
