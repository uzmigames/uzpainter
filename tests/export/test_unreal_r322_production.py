"""The shipped Unreal Engine (Packed) preset through the production export on R-322's Legacy cube
(phase3.2_unreal-ue56-packed-preset items 2.5 and 3.1, decision 422), on the owner's machine with
the private oracle store (skipped without it).

R-322's Legacy session (`export-presets-unreal-packed-legacy`) exports the preset by its versioned
URL with explicit PNG 8 and TGA 8 parameters (`infinite` padding, no dithering; steps 52 and 54).
UzPainter rebuilds the session's stack (`test_tga_capture_replay.r322_spec`) and publishes the
same configuration through `PublishExport` (whose project records the mesh's file name, `$mesh`),
restricted to Painter's four maps (the `_SpecularWeight` file
is UzPainter's own extension, which Painter does not write; as an L file it has no recorded TGA).
Every covered texel of every file equals Painter's r1 and r2, except the Normal's covered
island-edge texels (EXC-014, decision 417); the uncovered texels are the padding (EXC-013). The
receipt names exactly those exceptions. The ORM with its G and B swapped fails the comparison
(item 3.4).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tests.evaluator.test_compositor_tile_dag import TEMPLATES_DIR
from tests.export.test_export_publication import call, consumed
from tests.export.test_tga_capture_replay import CONFIG_ID, TEXTURE_SET, authored_inputs, r322_spec
from tests.export.tier0 import needs_store
from tools.parity import coverage as cov
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.decode import decode
from tools.parity.fit.oracle import load
from tools.parity.store.store import locate

PNG8_CONFIG = "probe-presets-unreal-packed-bevelled-cube-unreal-png8"
MAPS = ("BaseColor", "OcclusionRoughnessMetallic", "Normal", "Emissive")
PATTERN = "$mesh_$textureSet_{}(_$colorSpace)(.$udim)"


@pytest.mark.parametrize(
    ("config_id", "step", "extension"), [(PNG8_CONFIG, 52, "png"), (CONFIG_ID, 54, "tga")]
)
def test_unreal_preset_on_r322_legacy_equals_painter(
    export_tests: Path, tmp_path: Path, config_id: str, step: int, extension: str
) -> None:
    needs_store()
    path = (
        manifest_root(current_envelope())
        / "tier0/semantics/export-presets-unreal-packed-legacy.json"
    )
    golden = load(locate(), path)
    manifest = golden.manifest
    spec = r322_spec(manifest, tmp_path / "spec")
    config = json.loads(authored_inputs(manifest)[config_id].read_text(encoding="utf-8"))
    config["exportPath"] = (tmp_path / "out").as_posix()
    config["exportList"] = [
        {"rootPath": TEXTURE_SET, "filter": {"outputMaps": [PATTERN.format(m) for m in MAPS]}}
    ]
    (tmp_path / "spec" / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    code, lines, err = call(
        export_tests,
        "publish",
        str(TEMPLATES_DIR),
        str(tmp_path / "spec" / "spec.json"),
        str(tmp_path / "config.json"),
    )
    assert code == 0 and len(lines) == 1 and "error" not in lines[0], (code, lines, err)
    selected = consumed(export_tests, tmp_path / "out")
    assert "error" not in selected, selected
    generation = tmp_path / "out" / "generations" / str(selected["generation"])
    receipt = json.loads((generation / "receipt.json").read_text(encoding="utf-8"))
    names = {f"bevelled-cube_{TEXTURE_SET}_{m}.{extension}" for m in MAPS}
    assert {f["path"] for f in receipt["files"]} == names, receipt["files"]
    relied = {e["exception_id"]: set(e["paths"]) for e in receipt["exceptions_relied_on"]}
    assert relied == {
        "EXC-013": names,
        "EXC-014": {f"bevelled-cube_{TEXTURE_SET}_Normal.{extension}"},
    }, relied
    covered = cov.coverage(cov.obj_triangles(Path(spec["mesh"]), TEXTURE_SET), 256, 256)
    edge = covered & (cov.distance_bands(~covered, 1) == 1)
    for m in MAPS:
        name = f"bevelled-cube_{TEXTURE_SET}_{m}.{extension}"
        ours = np.asarray(decode((generation / "files" / name).read_bytes()).values)
        compared = covered & ~edge if m == "Normal" else covered
        for recording in ("r1", "r2"):
            theirs = np.asarray(golden.map(recording, f"probe/s{step}/{name}").values)
            assert ours.shape == theirs.shape, (m, recording)
            differ = int(np.count_nonzero(np.any(ours != theirs, axis=-1) & compared))
            assert differ == 0, f"{name} {recording}: {differ} compared texels differ"
            if m == "OcclusionRoughnessMetallic":
                # Item 3.4, defect detection: the same file with G and B swapped (metallic where
                # roughness belongs) fails this packing check on R-322's distinct channels.
                swapped = ours[..., [0, 2, 1]]
                assert np.count_nonzero(np.any(swapped != theirs, axis=-1) & compared) > 0
