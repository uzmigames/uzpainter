"""`export-padding`'s `infinite` OpenEXR 32f maps written end to end by the diagnostic measure
export (decisions 286 and 409), against Painter's r1 and r2 files on every texel.

The texture set `uzp_islands` (256 px, islands mesh) fills BaseColor (sRGB8), SpecularRoughness
(L8), Height (L16F), Opacity (L8), User0 (RGB16) and User1 (L32F) from bitmaps. The Opacity
channel is left out of the rebuild (its bitmap's default colour space on Opacity and its base are
not recorded); every other documentMap of the `infinite` OpenEXR 32f steps is compared, covered
texels, ring and gutter alike. User1 is the decision 409 case (its padding runs on the values
before the float32 read-out) and Height the half store's raw chain. The virtual Normal's covered
island edge is `phase4.1_export-island-padding-exact`'s and is not compared. Since decision 414
production writes the same padding under EXC-013; this mode stays not conformant.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import numpy as np

from tests.export.encoders_tier0 import _add_template_channels, _mesh_of, _semantics_golden
from tests.export.test_export_encoders import TEMPLATES, run
from tests.export.tier0 import export_spec
from tools.parity.fit.decode import decode
from tools.parity.recorder.job import Step, export_step

TEXTURE_SET = "uzp_islands"
NOT_COMPARED = {"normal_opengl", "opacity"}


def test_infinite_exr32_document_maps_equal_painter_on_every_texel(
    export_tests: Path, tmp_path: Path
) -> None:
    golden = _semantics_golden("export-padding")
    manifest = deepcopy(golden.manifest)
    sequence = manifest["instruction_sequence"]
    sequence["steps"] = [s for s in sequence["steps"] if s["args"].get("channel") != "Opacity"]
    for s in sequence["steps"]:
        if "channels" in s["args"] and isinstance(s["args"]["channels"], list):
            s["args"]["channels"] = [c for c in s["args"]["channels"] if c != "Opacity"]
    steps = {s["step"]: s for s in sequence["steps"]}
    targets: dict[int, list[tuple[str, str, str]]] = {}
    for recording in ("r1", "r2"):
        for key in golden.maps(recording):
            output = golden.output(recording, key)
            step = output["export_settings"]["step"]
            fmt = output["storage_format"]
            if (
                str(output["texture_set"]).split("/")[0] == TEXTURE_SET
                and steps[step]["args"].get("padding") == "infinite"
                and fmt["container"] == "exr"
                and fmt["bits_per_channel"] == 32
                and str(output["map"]).lower() not in NOT_COMPARED
            ):
                targets.setdefault(step, []).append((recording, key, str(output["map"])))
    assert targets
    document = export_spec(manifest, TEXTURE_SET, tmp_path / "spec")
    document["mesh"] = str(_mesh_of(manifest))
    document["channels"] = [c for c in document["channels"] if c["type"] != "Opacity"]
    _add_template_channels(document)
    spec_path = tmp_path / "spec" / "project.json"
    spec_path.write_text(json.dumps(document), encoding="utf-8")
    compared = []
    for step, outputs in sorted(targets.items()):
        raw = steps[step]
        out = tmp_path / f"out{step}"
        config = export_step(Step(step, raw["call"], raw["args"])).config(out, [TEXTURE_SET])
        for preset in config["exportPresets"]:
            preset["maps"] = [m for m in preset["maps"] if "opacity" not in json.dumps(m).lower()]
        config_path = tmp_path / f"config{step}.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        [result] = run(
            export_tests, "export-diagnostic", str(TEMPLATES), str(spec_path), str(config_path)
        )
        assert "error" not in result, result
        files = list(out.rglob("*.exr"))
        for recording, key, map_name in outputs:
            [path] = [p for p in files if p.stem.lower().endswith("_" + map_name.lower())]
            theirs = np.asarray(golden.map(recording, key).values, np.float32)
            ours = np.asarray(decode(path.read_bytes()).values, np.float32).reshape(theirs.shape)
            differing = int(np.count_nonzero(ours.view(np.uint32) != theirs.view(np.uint32)))
            compared.append((recording, step, map_name.lower(), differing))
    assert {m for _, _, m, _ in compared} == {
        "basecolor",
        "specularroughness",
        "height",
        "user0",
        "user1",
    }, compared
    assert [c for c in compared if c[3]] == [], compared
