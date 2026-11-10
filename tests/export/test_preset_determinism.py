"""Byte determinism of the Unreal and glTF presets (phase3.3_unreal-gltf-presets item 4.3, EXP-05).

Two exports of each shipped preset from the same build, project and configuration write the same
files byte for byte, and their receipts list the same files with the same hashes. Each export is
a separate `uzp-export-tests publish` process into its own output folder; the folders differ, so
only what the receipt says about the files is compared, not the receipt's own bytes.

The presets and encodings: `unreal-engine-packed` (its default PNG 8) and
`unreal-engine-packed-dds` (PNG 16 with BC7/BC5 DDS) on the authored set in AO_Mixed's scope
(`test_unreal_preset.publish`, as `test_shipped_preset_publishes_in_ao_mixed_scope`),
`gltf-pbr-metal-roughness` on the same set, and the Unreal preset's TGA 8 encoding through the
test-only copy whose ORM R reads the AO document map (`variant_presets`; TGA 8 refuses the L file
SpecularWeight, so it runs on the authored set without that channel, as
`test_tga_holds_the_png8_codes`). The pilots' production rebuilds (Tier 1, GPU) repeat their bytes
as well (`test_unreal_pilots.py`, `test_gltf_pilots.py`); this case is the CPU lane's.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tests.export.test_unreal_preset import DDS, PACKED, publish, variant_presets

GLTF = "gltf-pbr-metal-roughness"


def digests(files: Path) -> dict[str, str]:
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(files.iterdir())}


def receipt_files(files: Path) -> list[dict[str, Any]]:
    receipt = json.loads((files.parent / "receipt.json").read_text(encoding="utf-8"))
    files_listed: list[dict[str, Any]] = receipt["files"]
    return files_listed


@pytest.mark.parametrize(
    ("reference", "in_scope", "variant", "parameters"),
    [
        (PACKED, True, False, {}),
        (DDS, True, False, {}),
        (GLTF, True, False, {}),
        (PACKED, False, True, {"fileFormat": "tga", "bitDepth": "8"}),
    ],
    ids=["unreal-png8", "unreal-dds", "gltf", "unreal-tga8"],
)
def test_two_exports_write_the_same_bytes(
    export_tests: Path,
    tmp_path: Path,
    reference: str,
    in_scope: bool,
    variant: bool,
    parameters: dict[str, Any],
) -> None:
    presets = variant_presets(tmp_path / "presets") if variant else None
    first, second = (
        publish(export_tests, tmp_path / run, reference, presets, in_scope=in_scope, **parameters)
        for run in ("a", "b")
    )
    written = digests(first)
    assert written, f"{reference} wrote no file"
    assert digests(second) == written
    listed = receipt_files(first)
    assert listed == receipt_files(second)
    assert {f["path"]: f["sha256"] for f in listed} == written
