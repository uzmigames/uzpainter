"""Structured certification parameters match the native parameter boundary."""

from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

from tools.parity.proc_cert.batch import BatchError, BlobRef, Case, Domain, RasterSpec, _normal


def domain(rule: dict[str, Any]) -> Domain:
    return Domain(
        {
            "parameters": {"value": rule},
            "seeds": {"policy": "any_u32"},
            "geometry": {"mesh_classes": ["plane"], "uv_tiles": 1},
            "output": {
                "resolutions": [4],
                "formats": ["u8"],
                "colour_spaces": ["raw"],
                "channels": [1],
            },
        }
    )


def color(alpha: Any = None, space: str = "Linear sRGB") -> dict[str, Any]:
    return {"type": "color", "working_space": space, "components": [0, 0.5, 1], "alpha": alpha}


@pytest.mark.parametrize(
    "value",
    [
        [],
        [1],
        [1, 2, 3, 4, 5],
        [True, 2],
        ["1", 2],
        [[1, 2], 3],
        [float("inf"), 2],
        [float("nan"), 2],
        [1 << 63, 2],
        color(True),
        color(float("inf")),
        color(space=""),
        {**color(), "extra": 1},
        {**color(), "components": [0, True, 1]},
        {**color(), "components": [0, 1]},
        {"type": "color"},
        None,
    ],
)
def test_invalid_structured_parameters_refused(value: Any) -> None:
    with pytest.raises(BatchError, match="invalid parameter value"):
        domain({"set": [value]})
    assert domain({"set": [[1, 2], color()]}).params_refusal({"value": value}) is not None


def test_numeric_normalization_and_identity() -> None:
    params = {"vector": [1, 2.5], "color": color(1), "scalar": 1}
    before = deepcopy(params)
    equivalent = {
        "vector": [1.0, 2.5],
        "color": {**color(1.0), "components": [0.0, 0.5, 1.0]},
        "scalar": 1.0,
    }
    assert _normal(params) == _normal(equivalent)
    assert params == before
    assert _normal({"value": color()}) != _normal({"value": color(1)})
    assert _normal({"value": color()}) != _normal({"value": color(space="ACEScg")})
    assert (
        domain({"set": [[1, 2], color(1)]}).params_refusal({"value": equivalent["color"]}) is None
    )


def test_large_integer_components_remain_exact() -> None:
    first = [2**53, 1]
    second = [2**53 + 1, 1]
    assert _normal({"value": first}) != _normal({"value": second})
    assert domain({"set": [first]}).params_refusal({"value": second}) is not None
    assert domain({"set": [second]}).params_refusal({"value": second}) is None


@pytest.mark.parametrize("value", [[1, 2], color(), float("inf"), float("nan")])
def test_ranges_reject_structured_and_nonfinite_values(value: Any) -> None:
    assert domain({"range": [0, 2]}).params_refusal({"value": value}) is not None


def test_case_identity_keeps_strings_separate_and_booleans_numeric() -> None:
    ranged = domain({"range": [0, 2]})
    ranged.constraints = [{"coefficients": {"value": 1}, "max": 1}]
    assert ranged.params_refusal({"value": True}) is None
    assert ranged.params_refusal({"value": False}) is None
    ranged.constraints[0]["max"] = 0
    assert ranged.params_refusal({"value": True}) is not None
    calibration = Case(
        "cal",
        "calibration",
        "plane",
        "plane",
        1,
        {"value": 1},
        0,
        RasterSpec(4, "u8", "raw", 1),
        {},
        BlobRef("oracle", "0" * 64, 16, "raw"),
    )
    held_out = replace(calibration, case_id="held", set="held_out", params={"value": "1"})
    assert calibration.signature() != held_out.signature()
    assert calibration.signature() == replace(held_out, params={"value": True}).signature()
    assert calibration.signature() == replace(held_out, params={"value": 1.0}).signature()
