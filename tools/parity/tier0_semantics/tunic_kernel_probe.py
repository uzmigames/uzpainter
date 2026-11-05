"""The Tunic kernel-code padding probe (phase3.1_export-island-padding item 2.1, decision 401).

Decision 266's kernel-code probe on the Tunic v10 low mesh at 4096 px, the Tunic's Tier 1 size.
Every covered texel holds its own source (User3: its own centre, as the P-ramp probes), so the
recording decides the coverage of every texel: a texel is covered when its eight `infinite` maps
equal the sources on all 24 components. That confirms or refutes the candidate float32
device-coordinate coverage rule of `tools/parity/fit/padding_coverage.py` on decision 401's three
island-edge texels and on its one undecided Tunic texel, and decodes the Tunic's ring taps.

The mesh stays in the UzmiGames asset repository: the request names it by `assets3d_path` and
SHA-256 only, as the Tunic's Tier 1 golden does (decision 099), and the recorder resolves it under
`--assets-root` or from the private store. The eight kernel bitmaps are the repository's 4096 px
fixtures. Not part of the generated catalog, whose requests need no Assets3D root; written beside
it under `requests/tier0/assets3d/`.

    python -m tools.parity.tier0_semantics.tunic_kernel_probe          # write the request
    python -m tools.parity.recorder record <request> --assets-root <Assets3D root>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from tools.parity.envelope.registry import current_envelope
from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import sha256_file
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics.corpus import Golden, start
from tools.parity.tier0_semantics.recording_requests import (
    EXPORT_DOMAIN,
    EXR32F,
    KERNEL_CHANNELS,
    KERNEL_MAPS,
    KERNEL_TAIL,
    export,
    fixture,
    kernel_bitmaps,
    request_manifest,
    request_root,
)

NAME = "export-padding-kernel-tunic-4096"
RESOLUTION = 4096
MESH = "tunic-mesh"
TEXTURE_SET = "DefaultMaterial"
TUNIC_MANIFEST = (
    REPO_ROOT
    / "parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/manifests/phase2/tier1"
    / "tunic-v10-current.json"
)


def mesh_input() -> dict[str, Any]:
    """The Tunic v10 golden's own mesh input row: its Assets3D path, SHA-256 and provenance."""
    manifest = json.loads(TUNIC_MANIFEST.read_text(encoding="utf-8"))
    (row,) = [r for r in manifest["inputs"] if r["input_id"] == MESH]
    return dict(row)


def golden() -> Golden:
    """Decision 266's kernel probe sequence on the Tunic's one texture set."""
    s = start(MESH, resolution=RESOLUTION)
    s.channels(tuple((channel, "RGB32F") for channel in KERNEL_CHANNELS))
    bitmaps = kernel_bitmaps(RESOLUTION)
    res = s.imports(*bitmaps)
    node = s.fill(list(KERNEL_CHANNELS), position="top", texture_set=TEXTURE_SET)
    for channel, bitmap in zip(KERNEL_CHANNELS, bitmaps, strict=True):
        s.bitmap(node, channel, res[bitmap])
        s.blend(node, channel, "Normal", 1.0)
    s.add(ps.GET_PROJECTION, node_step=node)
    export(s, KERNEL_MAPS, EXR32F, "infinite")
    export(s, KERNEL_MAPS, EXR32F, "passthrough")
    return Golden(
        NAME,
        EXPORT_DOMAIN,
        "Decision 266's kernel-code probe (phase3.1_export-island-padding item 2.1, decision "
        "401: which texels Painter covers, every texel decided, and the infinite ring tap by "
        "tap) on the Tunic v10 low mesh, its texture set DefaultMaterial, kept in the UzmiGames "
        "asset repository and named by SHA-256 only (decision 099); document resolution "
        f"{RESOLUTION}, the Tunic's Tier 1 size. " + KERNEL_TAIL,
        MESH,
        bitmaps,
        s,
    )


def request() -> dict[str, Any]:
    """The probe's public request under the current envelope."""
    g = golden()
    hashes = {name: sha256_file(REPO_ROOT / fixture(name)[1]) for name in g.inputs}
    manifest = request_manifest(g, hashes, current_envelope(REPO_ROOT))
    manifest["inputs"] = [mesh_input(), *manifest["inputs"]]
    return manifest


def request_path(root: Path = REPO_ROOT) -> Path:
    return request_root(root) / "tier0" / "assets3d" / f"{NAME}.json"


def main() -> int:
    path = request_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(request(), indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print(path.relative_to(REPO_ROOT).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
