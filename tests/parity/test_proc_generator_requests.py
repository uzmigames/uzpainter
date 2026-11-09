"""Recording requests of the mesh-map generator goldens (`tools.parity.proc_generators`)."""

from __future__ import annotations

import pytest

from tools.parity.proc_generators.requests import (
    MAX_CASES,
    SEED_PARAMETER,
    GeneratorCase,
    Golden,
    manifest,
)
from tools.parity.recorder.job import job_from_manifest


def golden(*cases: GeneratorCase, mesh: str = "rounded-cube", resolution: int = 1024) -> Golden:
    return Golden("probe", "mixed", mesh, resolution, cases)


def test_a_request_is_a_recorder_job_with_one_channel_per_case() -> None:
    document = manifest(
        golden(
            GeneratorCase("defaults", "Position"),
            GeneratorCase("seed-1", "Position", seed=1),
            GeneratorCase("edit", "Curvature", (("contrast", 0.5),)),
        )
    )
    job_from_manifest(document)  # the recorder's own offline check
    steps = document["instruction_sequence"]["steps"]
    calls = [step["call"].rsplit(".", 1)[-1] for step in steps]
    assert calls.count("add_channel") == 3
    assert calls.count("insert_generator_effect") == 3
    seeds = [s["args"] for s in steps if s["args"].get("parameter") == SEED_PARAMETER]
    assert seeds == [{"node_step": seeds[0]["node_step"], "parameter": SEED_PARAMETER, "value": 1}]
    export = steps[-1]["args"]
    assert export["maps"][:3] == [f"documentMap/user{k}:L" for k in range(3)]
    assert export["file_format"] == "exr" and export["bit_depth"] == "32f"
    assert len(export["maps"]) == 3 + 6
    assert document["software"]["painter"]["build_id"] == "12.2.0+js-api.1.1.20"


def test_the_hat_is_an_assets3d_input_pinned_by_hash() -> None:
    document = manifest(golden(GeneratorCase("defaults", "Position"), mesh="hat-v8"))
    (mesh,) = document["inputs"]
    assert "path" not in mesh and mesh["assets3d_path"].endswith("10-Chapeu-v8.fbx")
    assert mesh["provenance"]["licence"] == "LicenseRef-UzmiGames-Assets3D"


@pytest.mark.parametrize(
    "bad",
    [
        golden(),
        golden(*(GeneratorCase(f"c{k}", "Position") for k in range(MAX_CASES + 1))),
        golden(GeneratorCase("a", "Position"), GeneratorCase("a", "Position")),
        golden(GeneratorCase("a", "Position", ((SEED_PARAMETER, 2),))),
        golden(GeneratorCase("a", "Position"), resolution=3000),
        golden(GeneratorCase("a", "Position"), mesh="teapot"),
    ],
)
def test_malformed_goldens_are_refused(bad: Golden) -> None:
    with pytest.raises(ValueError):
        manifest(bad)


def test_compared_texels_are_the_bake_coverage_eroded_by_one() -> None:
    import numpy as np

    from tools.parity.proc_generators.coverage import covered_texels

    normals = np.zeros((6, 6, 3), np.float32)
    normals[1:5, 1:5] = 0.5  # a covered 4 x 4 island
    expected = np.zeros((6, 6), bool)
    expected[2:4, 2:4] = True
    assert (covered_texels(normals) == expected).all()


def test_occlusion_candidate_follows_its_fitted_model() -> None:
    from types import SimpleNamespace

    import numpy as np

    from tools.parity.proc_generators.occlusion_candidate import fit

    ao = np.full((5, 5, 1), np.float32(9347 / 65535), np.float32)
    normals = np.full((5, 5, 3), np.float32(0.5), np.float32)
    normals[0] = 0.0
    candidate = fit(None)
    one = np.float32(1.0)
    inverted = one - ao[2, 2, 0]
    for ao_invert, global_invert, value in (
        (0, 0, one - inverted),
        (1, 1, one - inverted),
        (1, 0, inverted),
        (0, 1, inverted),
    ):
        case = SimpleNamespace(params={"ao_invert": ao_invert, "global_invert": global_invert})
        out = candidate.evaluate(case, {"AO": ao, "WorldSpaceNormal": normals})
        assert out.dtype == np.dtype("<f4") and out.shape == (5, 5, 1)
        assert out[2, 2, 0] == value
        assert (out[:2] == 0).all()  # outside the compared texels


def test_discovery_publishes_semantics_without_description_text() -> None:
    import json

    from tools.parity.proc_generators.discovery import markdown, publish

    prop = {
        "label": "Invert",
        "widget_type": "Togglebutton",
        "value": 0,
        "properties": {"defaultValue": 0, "min": 0, "max": 1, "description": "SECRET PROSE"},
    }
    source = {
        "resource_url": "resource://starter_assets/x/x?version=1.sbsar",
        "properties": {"invert": prop},
        "presets": [],
        "image_inputs": ["a"],
        "image_outputs": ["b"],
    }
    survey = {
        "schema": "uzpainter/generator-survey/1",
        "query": "q",
        "painter_build": {"build_id": "12.2.0+js-api.1.1.20"},
        "rows": [{"url": source["resource_url"], "gui_name": "X", "source": source}],
    }
    text = markdown(publish(json.dumps(survey).encode(), {"x": "X"}))
    assert "| `invert` | Invert | Togglebutton | 0 | 0 | 1 |" in text
    assert "SECRET PROSE" not in text
