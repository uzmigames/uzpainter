"""Explicit project-private procedural refs, raw CPU export and bundle reopen."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import OpenEXR
import pytest
from jsonschema import Draft202012Validator

from tests.export.conftest import export_tests as export_tests
from tests.python.conftest import REPO_ROOT, Run
from tests.python.test_pyapi_native import EXPORT_CONFIG, ok


@pytest.mark.parametrize("seed", [None, 0, 7, -7, -(1 << 63), (1 << 63) - 1])
def test_snapshot_fill_exports_after_reopen_and_bundle(
    run: Run,
    export_tests: Path,  # noqa: F811
    tmp_path: Path,
    seed: int | None,
) -> None:
    project_path = tmp_path / "snapshot.uzp"
    ok(run('create(128)\nproject.save_as(WORK + "/snapshot.uzp")\nproject.close()\nresult = True'))
    ok(run('create(128)\nproject.save_as(WORK + "/foreign.uzp")\nproject.close()\nresult = True'))
    native = subprocess.run(
        [str(export_tests), "snapshot-source", str(project_path)]
        + ([] if seed is None else [str(seed)]),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert native.returncode == 0, native.stdout + native.stderr
    assert "exact CPU readout" in native.stdout
    transactions = ok(
        run("""
project.open(WORK + "/snapshot.uzp")
material = ts.get_active_stack().material()
with uzpainter.Transaction("temporary resize"):
    material.set_resolution(ts.Resolution(256, 256))
    material.set_resolution(ts.Resolution(128, 128))
def invalid_final():
    with uzpainter.Transaction("invalid final size"):
        material.set_resolution(ts.Resolution(256, 256))
revision = project.revision()
error = raises(invalid_final)
result = [error, project.revision() == revision, material.get_resolution().width]
project.close()
""")
    )
    assert "128" in transactions[0]
    assert transactions[1:] == [True, 128]
    config = json.loads(EXPORT_CONFIG)
    output = config["exportPresets"][0]["maps"][0]
    output["fileName"] = "$textureSet_scalar"
    output["channels"][0]["srcMapName"] = "user0"
    output["parameters"].update(fileFormat="exr", bitDepth="32f", paddingAlgorithm="passthrough")
    result = ok(
        run(
            f"""
config = json.loads({json.dumps(config)!r})
files = []
receipts = []
for name in ("snapshot", "snapshot-imported"):
    project.open(WORK + "/" + name + ".uzp")
    config["exportPath"] = WORK + "/export-" + name
    output = export.export_project_textures(config)
    files.append(output["files"][0]["path"])
    receipts.append(output["receipt"])
    if name == "snapshot":
        dump = project.dump_recipe()
    project.close()
rebuild = raises(project.rebuild_from_recipe, dump, WORK)
result = {{"files": files, "receipts": receipts, "rebuild": rebuild}}
"""
        )
    )
    assert "snapshot planes" in result["rebuild"]
    expected = np.frombuffer((tmp_path / "snapshot-expected.raw").read_bytes(), dtype=np.uint32)
    schema = json.loads((REPO_ROOT / "src/export/schema/receipt.schema.json").read_text())
    for image_path, receipt_path in zip(result["files"], result["receipts"], strict=True):
        with OpenEXR.File(image_path, separate_channels=True) as image:
            channels = image.channels()
            assert len(channels) == 1
            actual = next(iter(channels.values())).pixels
            np.testing.assert_array_equal(actual.view(np.uint32).ravel(), expected)
        receipt = json.loads(Path(receipt_path).read_text())
        Draft202012Validator(schema).validate(receipt)
        assert len(receipt["procedural_snapshots"]) == 1
        provenance = receipt["procedural_snapshots"][0]
        assert provenance["raster_sha256"] not in receipt["resource_hashes"]
        assert provenance["plane_id"] > 0 and provenance["version_id"] > 0
