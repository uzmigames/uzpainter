"""Recording requests and batches of the filter goldens (`tools.parity.proc_filters`)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tools.parity.proc_filters import goldens as gold
from tools.parity.proc_filters.batch import levels_asset, sharpen_asset
from tools.parity.proc_filters.requests import (
    LEVELS,
    MAX_CHANNELS,
    FilterCase,
    Golden,
    filter_search,
    manifest,
)
from tools.parity.recorder.job import job_from_manifest


def golden(*cases: FilterCase, mesh: str = "rounded-cube", resolution: int = 1024) -> Golden:
    return Golden("probe", "mixed", mesh, resolution, cases)


def test_a_request_is_a_recorder_job_with_one_channel_per_case_and_the_content() -> None:
    document = manifest(
        golden(
            FilterCase("sharpen", "Sharpen", (("intensity", 0.25),)),
            FilterCase("levels", LEVELS, (("input_min", 0.1), ("clamp", 1))),
            FilterCase("grey", "Grayscale Conversion"),
        )
    )
    job_from_manifest(document)  # the recorder's own offline check
    steps = document["instruction_sequence"]["steps"]
    calls = [step["call"].rsplit(".", 1)[-1] for step in steps]
    assert calls.count("add_channel") == 4
    assert calls.count("insert_fill") == 4
    assert calls.count("insert_filter_effect") == 2
    assert calls.count("insert_levels_effect") == 1
    searches = [s["args"]["filter_search"] for s in steps if "filter_search" in s["args"]]
    assert searches == [
        "s:starterassets u:filter n:Sharpen=",
        's:starterassets u:filter n:"Grayscale Conversion"=',
    ]
    projections = [s["args"] for s in steps if s["call"].endswith("set_projection_parameters")]
    assert {tuple(p["scale"]) for p in projections} == {(4.0, 4.0)}  # one bitmap texel a texel
    export = steps[-1]["args"]
    assert export["maps"] == [f"documentMap/user{k}:L" for k in range(4)] + [
        "meshMap/world_space_normals:RGB"
    ]
    assert export["padding"] == "passthrough" and export["bit_depth"] == "32f"
    inputs = {i["input_id"]: i for i in document["inputs"]}
    assert inputs["content-grey"]["path"] == "parity/fixtures/proc-filters/content-grey.png"


def test_a_quoted_name_is_only_used_for_a_name_with_a_space() -> None:
    assert filter_search("Blur") == "s:starterassets u:filter n:Blur="
    assert filter_search("Grayscale Conversion").endswith('n:"Grayscale Conversion"=')


@pytest.mark.parametrize(
    "bad",
    [
        golden(),
        golden(*(FilterCase(f"c{k}", "Sharpen") for k in range(MAX_CHANNELS))),
        golden(FilterCase("a", "Sharpen"), FilterCase("a", "Sharpen")),
        golden(FilterCase("a", "Sharpen", (("intensity", 1), ("intensity", 2)))),
        golden(FilterCase("a", "Sharpen"), resolution=3000),
        golden(FilterCase("a", "Sharpen"), mesh="teapot"),
    ],
)
def test_malformed_goldens_are_refused(bad: Golden) -> None:
    with pytest.raises(ValueError):
        manifest(bad)


def test_the_batches_declare_the_matrix_the_harness_needs() -> None:
    for asset, sets in ((sharpen_asset(), gold.SHARPEN_SETS), (levels_asset(), gold.LEVELS_SETS)):
        roles = [role for _, role, _ in asset.parameter_sets]
        assert roles.count("defaults") == 1 and roles.count("boundary") == 2
        assert "recipe" in roles and len(asset.parameter_sets) == len(sets)
        assert asset.domain["seeds"] == {"policy": "listed", "seeds": [0]}
        assert set(asset.domain["geometry"]["inputs"]) == {"content", "WorldSpaceNormal"}
    # Every held-out point is a set the calibration matrix does not hold, or the same set on
    # another mesh: the held-out meshes are outside the calibration meshes.
    assert not {m for m, _ in gold.HELD_OUT} & set(gold.CALIBRATION_MESHES)


def test_the_levels_defaults_case_sets_nothing() -> None:
    (defaults, *_) = gold.levels_cases(gold.LEVELS_SETS)
    assert defaults.parameters == ()
    assert gold.levels_cases(gold.LEVELS_SETS)[1].parameters[0] == ("input_min", 0.42)


def test_discovery_publishes_the_named_filters_without_description_text() -> None:
    from tools.parity.proc_filters.discovery import markdown, publish

    def row(name: str) -> dict[str, object]:
        prop = {
            "label": "Intensity",
            "widget_type": "Slider",
            "properties": {"defaultValue": 1, "min": 0, "max": 4, "description": "SECRET PROSE"},
        }
        source = {
            "resource_url": f"resource://starter_assets/{name}/{name}?version=1.sbsar",
            "properties": {"intensity": prop},
            "presets": [],
            "image_inputs": [],
            "image_outputs": ["output"],
        }
        return {"url": source["resource_url"], "gui_name": name, "source": source}

    survey = {
        "schema": "uzpainter/filter-survey/1",
        "query": "q",
        "painter_build": {"build_id": "12.2.0+js-api.1.1.20"},
        "rows": [row("Sharpen"), row("Blur"), row("Grayscale Conversion"), row("Other")],
    }
    text = markdown(publish(json.dumps(survey).encode()))
    assert "| `intensity` | Intensity | Slider | 1 | 0 | 4 |" in text
    assert "SECRET PROSE" not in text and "Other" not in text


def _content(codes: Any) -> tuple[Any, Any]:
    import numpy as np

    from tools.parity.proc_filters.levels_candidate import twice_inverted
    from tools.parity.vk_sampler_probe import unorm16

    k = np.asarray(codes, np.int64)
    content = twice_inverted(unorm16.fetch(k))[..., None]
    normals = np.full((*k.shape, 3), np.float32(0.5), np.float32)
    normals[0] = 0.0
    return content, normals


def test_levels_candidate_follows_its_model_and_stores_through_the_channel() -> None:
    from types import SimpleNamespace

    import numpy as np

    from tools.parity.proc_filters.levels_candidate import fit, levels, twice_inverted
    from tools.parity.vk_sampler_probe import unorm16

    k = np.arange(36, dtype=np.int64).reshape(6, 6) * 1800 + 7
    content, normals = _content(k)
    candidate = fit(None)
    defaults = SimpleNamespace(params=gold.LEVELS_DEFAULTS)
    out = candidate.evaluate(defaults, {"content": content, "WorldSpaceNormal": normals})
    assert out.dtype == np.dtype("<f4") and out.shape == (6, 6, 1)
    assert (out[2:4, 2:4, 0] == content[2:4, 2:4, 0]).all()  # the defaults are the identity
    assert (out[:2] == 0).all()  # outside the compared texels
    point = gold.LEVELS_SETS[1][2]
    out = candidate.evaluate(
        SimpleNamespace(params=point), {"content": content, "WorldSpaceNormal": normals}
    )
    expected = twice_inverted(levels(unorm16.fetch(k), point))
    assert (out[2:4, 2:4, 0] == expected[2:4, 2:4]).all()


def test_filter_candidates_refuse_content_off_the_16_bit_codes() -> None:
    from types import SimpleNamespace

    import numpy as np

    from tools.parity.proc_filters.levels_candidate import ContentInputError
    from tools.parity.proc_filters.levels_candidate import fit as fit_levels
    from tools.parity.proc_filters.sharpen_candidate import fit as fit_sharpen

    content = np.full((5, 5, 1), np.float32(0.3), np.float32)  # no 16-bit code stores as 0.3
    normals = np.full((5, 5, 3), np.float32(0.5), np.float32)
    inputs = {"content": content, "WorldSpaceNormal": normals}
    with pytest.raises(ContentInputError):
        fit_levels(None).evaluate(SimpleNamespace(params=gold.LEVELS_DEFAULTS), inputs)
    with pytest.raises(ContentInputError):
        fit_sharpen(None).evaluate(SimpleNamespace(params={"intensity": 1.0}), inputs)


def test_sharpen_candidate_is_the_clamped_laplacian_on_16_bit_codes() -> None:
    import numpy as np

    from tools.parity.proc_filters.sharpen_candidate import sharpen_codes

    k = np.random.default_rng(11).integers(0, 65536, (8, 8))
    laplacian = 4 * k - sum(np.roll(k, s, a) for s in (1, -1) for a in (0, 1))
    for intensity in (0.0, 1.0, 4.0):  # an integer intensity: no code midpoint, no rounding
        expected = np.clip(k + intensity * laplacian, 0, 65535)
        assert (sharpen_codes(k, intensity) == expected).all()


def test_hardware_log2_and_exp2_follow_the_measured_tables() -> None:
    import numpy as np

    from tools.parity.fit import hwmath

    f32 = np.float32
    assert list(hwmath.log2(np.array([1, 2, 4], f32))) == [0.0, 1.0, 2.0]
    assert np.isneginf(hwmath.log2(np.array([0], f32)))[0]
    assert np.isnan(hwmath.log2(np.array([-1], f32)))[0]
    assert list(hwmath.exp2(np.array([0, 1, -1, -200], f32))) == [1.0, 2.0, 0.5, 0.0]
    assert hwmath.pow(np.array([0.25], f32), np.array([0.5], f32))[0] == f32(0.5)
