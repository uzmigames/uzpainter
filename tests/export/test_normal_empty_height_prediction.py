"""Decision 245 section 2's native prediction inputs and runner check
(`tools/parity/tier0_semantics/normal_empty_height_prediction.py`).

CPU: the closed spec (template channels and bases, Legacy, OpenGL, the pinned inputs, one
Normal-only fill with `NormalXYZLeft`, no Height), the three run configurations, the result check
(exact planned files, typed entries, causes bound to their file and not only decision numbers,
`undecided` kept, `error` and `written` never together), the exact PNG and OpenEXR decoders on
authored files, and the partial pins.

Native (`export_tests`, the coordinator's single `zig build export-tests`): the two `infinite`
runs and the refused `passthrough` run through `export-diagnostic`, the Height control all
+0.0 words, the PNG 16 Normal the write of the OpenEXR 32f one on covered texels, and
`normal_base` decision 079 F1's float32 code / 65535 on covered texels.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.export.test_export_encoders import TEMPLATES
from tests.export.tier0 import write16
from tools.parity.feasibility import png
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import normal_empty_height as request
from tools.parity.tier0_semantics import normal_empty_height_mask as mask
from tools.parity.tier0_semantics import normal_empty_height_prediction as p
from tools.parity.tier0_semantics import recording_requests as rr

OUT = Path("E:/out")


def test_spec_is_closed_and_normal_only() -> None:
    document = p.spec()
    assert set(document) == p.SPEC_KEYS
    assert document["template"] == "default"
    assert document["evaluator_profile"] == p.EVALUATOR_PROFILE
    assert document["color_management"] == "legacy"
    assert document["normal_map_format"] == "OpenGL"
    assert document["height_to_normal_method"] == "Sharp"
    assert document["channels"] == [{"type": t, "format": f} for t, f, _ in p.TEMPLATE_CHANNELS]
    assert [r["sha256"] for r in document["resources"]] == [
        p.INPUT_SHA256["normal-a"],
        p.INPUT_SHA256["normal-b"],
    ]
    assert all(Path(r["png"]).is_absolute() for r in document["resources"])
    assert Path(document["mesh"]).is_absolute()
    assert document["mesh_maps"] == {"Normal": p.INPUT_SHA256["normal-b"]}
    (layer,) = document["layers"]
    assert set(layer) == {
        "kind",
        "name",
        "visible",
        "sources",
        "active_channels",
        "blending",
        "projection",
    }
    assert layer["sources"] == {
        "Normal": {"bitmap": p.INPUT_SHA256["normal-a"], "color_space": "NormalXYZLeft"}
    }
    assert layer["active_channels"] == ["Normal"]
    assert layer["blending"] == {"Normal": {"mode": "Normal", "opacity": 1.0}}
    assert layer["projection"] == {
        "mode": "UV",
        "filtering_mode": "Nearest",
        "uv_wrapping_mode": "Repeat",
        "scale_mode": "Factors",
        "scale": [1.0, 1.0],
        "rotation": 0.0,
        "offset": [0.0, 0.0],
    }
    assert json.loads(json.dumps(document)) == document


def test_inputs_and_template_are_the_frozen_ones(tmp_path: Path) -> None:
    for name, sha in p.INPUT_SHA256.items():
        assert p.sha256_file(p.input_path(name)) == sha
    p.check_template()
    template = tmp_path / p.TEMPLATE_PATH
    template.parent.mkdir(parents=True)
    document = json.loads((REPO_ROOT / p.TEMPLATE_PATH).read_text(encoding="utf-8"))
    document["channels"][2]["format"] = "L32F"
    template.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError):
        p.check_template(tmp_path)
    changed = tmp_path / rr.fixture("normal-a")[1]
    changed.parent.mkdir(parents=True)
    changed.write_bytes(b"not normal-a")
    with pytest.raises(ValueError):
        p.input_path("normal-a", tmp_path)


def test_runs_plan_the_frozen_files() -> None:
    assert set(p.RUNS) == {"exr32-infinite", "png16-infinite", "exr32-passthrough-refused"}
    assert p.planned("exr32-infinite") == {
        "uzp_sphere_n.exr": "n",
        "uzp_sphere_h.exr": "h",
        "uzp_sphere_normal.exr": "normal",
        "uzp_sphere_normal_base.exr": "normal_base",
    }
    assert p.planned("png16-infinite") == {"uzp_sphere_n.png": "n"}
    for run, (parameters, padding, names) in p.RUNS.items():
        cfg = p.config(run, OUT)
        assert cfg["exportPath"] == OUT.as_posix()
        assert cfg["exportList"] == [{"rootPath": "uzp_sphere"}]
        assert cfg["exportParameters"] == [
            {"parameters": parameters | {"paddingAlgorithm": padding}}
        ]
        assert [m["fileName"] for m in cfg["exportPresets"][0]["maps"]] == [
            f"$textureSet_{n}" for n in names
        ]
    assert p.RUNS["exr32-passthrough-refused"][1] == "passthrough"


def refusal(relative: str, name: str, cause: tuple[str, str]) -> str:
    """A refusal shaped as `Refused` writes it (src/export/guards.cpp)."""
    return (
        f'export: uzp_sphere map "$textureSet_{name}" ({relative}): {cause[0]} (owner, {cause[1]})'
    )


def good(run: str) -> dict[str, Any]:
    if run == p.REFUSED_RUN:
        return {
            "error": "NotYetSupported",
            "message": refusal("uzp_sphere_n.exr", "n", p.PASSTHROUGH_CAUSE),
        }
    written = [
        {
            "relativePath": relative,
            "path": (OUT / relative).as_posix(),
            "bypassed": [refusal(relative, name, c) for c in p.BYPASSED[name]],
            "undecided": 3,
        }
        for relative, name in p.planned(run).items()
    ]
    return {"written": written}


@pytest.mark.parametrize("run", list(p.RUNS))
def test_clean_results_pass_and_the_report_is_nonconformant(run: str) -> None:
    report = p.validate_result(run, good(run), OUT)
    assert report["conformant"] is False
    if run != p.REFUSED_RUN:
        assert {f["undecided"] for f in report["files"].values()} == {3}


def number_only(result: dict[str, Any]) -> None:
    result["written"][0]["bypassed"][0] = "refused (decision 245)"


def cause_of_another_file(result: dict[str, Any]) -> None:
    result["written"][1]["bypassed"] = copy.deepcopy(result["written"][2]["bypassed"])


def causes_swapped(result: dict[str, Any]) -> None:
    result["written"][0]["bypassed"].reverse()


def extra_cause(result: dict[str, Any]) -> None:
    result["written"][1]["bypassed"].append(result["written"][1]["bypassed"][0])


def file_missing(result: dict[str, Any]) -> None:
    del result["written"][-1]


def file_twice(result: dict[str, Any]) -> None:
    result["written"][-1] = copy.deepcopy(result["written"][0])


def entry_not_a_dict(result: dict[str, Any]) -> None:
    result["written"][0] = "uzp_sphere_n.exr"


def relative_path_none(result: dict[str, Any]) -> None:
    result["written"][0]["relativePath"] = None


def path_not_a_string(result: dict[str, Any]) -> None:
    result["written"][0]["path"] = 7


def wrong_path(result: dict[str, Any]) -> None:
    result["written"][0]["path"] = "E:/elsewhere/uzp_sphere_n.exr"


def undecided_bool(result: dict[str, Any]) -> None:
    result["written"][0]["undecided"] = True


def undecided_negative(result: dict[str, Any]) -> None:
    result["written"][0]["undecided"] = -1


def extra_field(result: dict[str, Any]) -> None:
    result["written"][0]["nonconformant"] = False


def error_and_written(result: dict[str, Any]) -> None:
    result["error"] = "Failure"


@pytest.mark.parametrize(
    "spoil",
    [
        number_only,
        cause_of_another_file,
        causes_swapped,
        extra_cause,
        file_missing,
        file_twice,
        entry_not_a_dict,
        relative_path_none,
        path_not_a_string,
        wrong_path,
        undecided_bool,
        undecided_negative,
        extra_field,
        error_and_written,
    ],
)
def test_spoiled_positive_results_are_refused(spoil: Any) -> None:
    result = good("exr32-infinite")
    spoil(result)
    with pytest.raises(ValueError):
        p.validate_result("exr32-infinite", result, OUT)


@pytest.mark.parametrize(
    "result",
    [
        {"error": "NotYetSupported", "message": "refused (decision 245)"},
        {
            "error": "NotYetSupported",
            "message": refusal("uzp_sphere_h.exr", "h", p.PASSTHROUGH_CAUSE),
        },
        {"error": "Failure", "message": refusal("uzp_sphere_n.exr", "n", p.PASSTHROUGH_CAUSE)},
        {
            "error": "NotYetSupported",
            "message": refusal("uzp_sphere_n.exr", "n", p.PASSTHROUGH_CAUSE),
            "written": [],
        },
        {"written": []},
    ],
)
def test_the_refused_run_must_be_refused_for_its_cause(result: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        p.validate_result(p.REFUSED_RUN, result, OUT)


def write_exr(path: Path, planes: dict[str, np.ndarray]) -> None:
    import OpenEXR

    header = {"compression": OpenEXR.NO_COMPRESSION, "type": OpenEXR.scanlineimage}
    OpenEXR.File(header, {k: np.ascontiguousarray(v) for k, v in planes.items()}).write(str(path))


def rgb(size: int = p.SIZE, dtype: Any = np.float32) -> dict[str, np.ndarray]:
    ramp = np.arange(size * size, dtype=np.float64).reshape(size, size) / (size * size)
    return {c: (ramp + i).astype(dtype) for i, c in enumerate("RGB")}


def test_exr_words_keep_the_float32_words(tmp_path: Path) -> None:
    path = tmp_path / "rgb.exr"
    planes = rgb()
    planes["G"][0, 0] = np.float32(-0.0)
    write_exr(path, planes)
    words = p.exr_words(path, ("R", "G", "B"))
    assert {k: v.dtype for k, v in words.items()} == {c: np.dtype(np.uint32) for c in "RGB"}
    assert words["G"][0, 0] == 0x80000000
    assert np.array_equal(words["R"], planes["R"].view(np.uint32))
    grey = tmp_path / "y.exr"
    write_exr(grey, {"Y": np.zeros((p.SIZE, p.SIZE), np.float32)})
    assert not np.any(p.exr_words(grey, ("Y",))["Y"])


@pytest.mark.parametrize("case", ["half", "size", "channels", "nan"])
def test_exr_words_refuse_another_file(tmp_path: Path, case: str) -> None:
    path = tmp_path / f"{case}.exr"
    planes = rgb(dtype=np.float16) if case == "half" else rgb(128 if case == "size" else p.SIZE)
    if case == "nan":
        planes["B"][3, 3] = np.float32(np.nan)
    write_exr(path, planes)
    expected = ("Y",) if case == "channels" else ("R", "G", "B")
    with pytest.raises(ValueError):
        p.exr_words(path, expected)


def test_png16_rgb_reads_only_a_16_bit_rgb_file(tmp_path: Path) -> None:
    codes = (np.arange(p.SIZE * p.SIZE * 3, dtype=np.int64) % 65536).reshape(p.SIZE, p.SIZE, 3)
    good_path = tmp_path / "rgb16.png"
    good_path.write_bytes(png.encode(codes, 16))
    assert np.array_equal(p.png16_rgb(good_path), codes)
    for name, data in (
        ("rgb8.png", png.encode(codes % 256, 8)),
        ("small.png", png.encode(codes[:128, :128], 16)),
        ("grey.png", png.encode(codes[..., 0], 16)),
    ):
        (tmp_path / name).write_bytes(data)
        with pytest.raises(ValueError):
            p.png16_rgb(tmp_path / name)


def test_partial_pins_name_themselves_partial(tmp_path: Path) -> None:
    exe = tmp_path / "uzp-export-tests.exe"
    exe.write_bytes(b"exe")
    out = tmp_path / "uzp_sphere_n.exr"
    out.write_bytes(b"exr")
    configs = {run: p.config(run, tmp_path) for run in p.RUNS}
    pins = p.partial_pins(exe, TEMPLATES, p.spec(), configs, {"uzp_sphere_n.exr": out})
    assert pins["partial"] is True and pins["conformant"] is False
    assert pins["executable_sha256"] == p.sha256_file(exe)
    assert pins["templates"]["default.json"] == p.sha256_file(TEMPLATES / "default.json")
    assert set(pins["configs_sha256"]) == set(p.RUNS)
    assert pins["outputs_sha256"] == {"uzp_sphere_n.exr": p.sha256_file(out)}


# -- Native (export_tests: one zig build, owned by the coordinator) --------------------------


def diagnostic(exe: Path, spec_path: Path, config_path: Path) -> Any:
    proc = subprocess.run(
        [str(exe), "export-diagnostic", str(TEMPLATES), str(spec_path), str(config_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=1800,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, proc.stdout
    return json.loads(lines[0])


@pytest.fixture(scope="module")
def predicted(export_tests: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("normal-empty-height")
    spec_path = root / "spec.json"
    spec_path.write_text(json.dumps(p.spec()), encoding="utf-8")
    reports: dict[str, Any] = {}
    for run in p.RUNS:
        out = root / run
        config_path = root / f"{run}.json"
        config_path.write_text(json.dumps(p.config(run, out)), encoding="utf-8")
        reports[run] = p.validate_result(run, diagnostic(export_tests, spec_path, config_path), out)
        reports[run]["out"] = out
    return reports


def test_native_runs_bypass_and_refuse_their_causes(predicted: dict[str, Any]) -> None:
    assert set(predicted["exr32-infinite"]["files"]) == set(p.planned("exr32-infinite"))
    assert set(predicted["png16-infinite"]["files"]) == set(p.planned("png16-infinite"))
    assert "decision 245" in predicted[p.REFUSED_RUN]["refused"]


def test_native_controls(predicted: dict[str, Any]) -> None:
    exr = predicted["exr32-infinite"]["out"]
    covered = mask.frozen_classes().covered
    height = p.exr_words(exr / "uzp_sphere_h.exr", ("Y",))["Y"]
    assert not np.any(height), "Height is +0.0 in every word"
    normal = p.exr_words(exr / "uzp_sphere_n.exr", ("R", "G", "B"))
    floats = np.stack([normal[c].view(np.float32) for c in "RGB"], axis=-1)
    codes = p.png16_rgb(predicted["png16-infinite"]["out"] / "uzp_sphere_n.png")
    assert np.array_equal(codes[covered], write16(floats[covered]))
    mesh_map = p.png16_rgb(p.input_path(request.MESH_MAP_INPUT))
    unorm = (mesh_map.astype(np.float64) / 65535.0).astype(np.float32).view(np.uint32)
    base = p.exr_words(exr / "uzp_sphere_normal_base.exr", ("R", "G", "B"))
    for i, c in enumerate("RGB"):
        assert np.array_equal(base[c][covered], unorm[..., i][covered]), c
