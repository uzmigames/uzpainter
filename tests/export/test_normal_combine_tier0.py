"""Decision 293: separate padded Hn/C, compared with every r1/r2 float and PNG repeat."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.export.encoders_tier0 import _mesh_of, _semantics_golden
from tests.export.test_export_encoders import TEMPLATES, chan, run
from tests.export.test_island_normal import bits
from tests.export.tier0 import export_spec
from tools.parity.fit.decode import decode


@pytest.mark.parametrize("texture_set", ["uzp_nc_free", "uzp_nc_mesh"])
@pytest.mark.parametrize("container,depth", [("exr", "32f"), ("png", "16")])
def test_normal_combine_recorded_order(
    export_tests: Path, tmp_path: Path, texture_set: str, container: str, depth: str
) -> None:
    golden = _semantics_golden("export-padding-normal-combine")
    document = export_spec(golden.manifest, texture_set, tmp_path)
    document["mesh"] = str(_mesh_of(golden.manifest))
    spec_path = tmp_path / "project.json"
    spec_path.write_text(json.dumps(document), encoding="utf-8")
    target = tmp_path / "output"
    config: dict[str, Any] = {
        "exportShaderParams": False,
        "exportPath": target.as_posix(),
        "defaultExportPreset": "p",
        "exportPresets": [
            {
                "name": "p",
                "maps": [
                    {
                        "fileName": "$textureSet_n",
                        "channels": [chan(c, "virtualMap", "Normal_OpenGL") for c in "RGB"],
                    }
                ],
            }
        ],
        "exportList": [{"rootPath": texture_set}],
        "exportParameters": [
            {
                "parameters": {
                    "fileFormat": container,
                    "bitDepth": depth,
                    "dithering": False,
                    "paddingAlgorithm": "infinite",
                }
            }
        ],
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    [result] = run(
        export_tests, "export-diagnostic", str(TEMPLATES), str(spec_path), str(config_path)
    )
    assert "error" not in result, result
    ours = decode((target / f"{texture_set}_n.{container}").read_bytes())
    assert ours.bits == (32 if container == "exr" else 16)
    assert set(golden.recordings) == {"r1", "r2"}
    for recording in golden.recordings:
        matches = [
            key
            for key in golden.maps(recording)
            if (output := golden.output(recording, key))["texture_set"] == texture_set
            and output["map"] == "Normal_OpenGL"
            and output["storage_format"]["container"] == container
        ]
        assert len(matches) == 2, (recording, matches)
        for key in matches:
            theirs = golden.map(recording, key)
            got = ours.values if ours.integer else bits(ours.values)
            expected = theirs.values if theirs.integer else bits(theirs.values)
            assert np.array_equal(got, expected), (
                recording,
                key,
                int(np.count_nonzero(got != expected)),
            )
