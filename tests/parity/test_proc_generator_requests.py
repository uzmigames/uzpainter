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
