"""The Sash v5 intermediates helper on authored data, with no Blender (decision 300 item 7).

The "Authoring low" is a quad (part 1) and a triangle (part 2); front N's "Low-Game table" is
built from it the way `deliver.py` and `sash_low_blender` build theirs. The "Blender" of the host
tests is a Python function that writes what the Blender side would write. The construction
centre is tested on a wrap generated with `low_gen.wrap_low`'s column angles and
`waist_gen.Waist.point`'s formula, stored as float32 under a shuffled vertex and face order.
Nothing here opens the Sash `.blend`, runs Blender or claims anything about the real files.

Test limit: the `object.bake` option list and the Blender reports are authored from the API
documentation; the first real run is what confirms them (an unpinned option refuses the bake).
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import subprocess
import zipfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

import numpy as np
import pytest

from tools.parity.feasibility import png
from tools.parity.recorder.job import sha256_file
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier1 import sash_intermediates as host
from tools.parity.tier1 import sash_intermediates_blender as side
from tools.parity.tier1 import sash_low_blender as low_side
from tools.parity.tier1 import sash_low_export as low_host
from tools.parity.tier1.sash_intermediates import CentreError
from tools.parity.tier1.sash_intermediates_blender import ExtractError
from tools.parity.tier1.sash_low_export import SourcePin

IDENTITY3 = np.eye(3)
POSITIONS = [
    (0.0, 0.0, 1.1),
    (0.125, 0.0, 1.1),
    (0.125, 0.25, 1.15),
    (0.0, 0.25, 1.125),
    (0.5, 0.5, 1.2),
    (0.75, 0.5, 1.2),
    (0.75, 0.75, 1.25),
]
FACE_LOOPS = [0, 1, 2, 3, 4, 5, 6]  # quad 0-3 then triangle 4-6: loop i is on vertex i
LOOP_TRIANGLES = [(0, 1, 2), (0, 2, 3), (4, 5, 6)]
UVS = [(0.1, 0.2), (0.6, 0.2), (0.6, 0.9), (0.1, 0.9), (0.7, 0.1), (0.9, 0.1), (0.9, 0.3)]
NORMALS = [(0.0, 0.0, 1.0), (0.0, 0.6, 0.8), (0.6, 0.0, 0.8), (0.0, 0.0, 1.0)] + [
    (0.0, 1.0, 0.0)
] * 3
PARTS = [1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 2.0]


def authored_arrays() -> dict[str, Any]:
    arrays = side.donor_arrays(
        POSITIONS,
        LOOP_TRIANGLES,
        FACE_LOOPS,
        UVS,
        NORMALS,
        PARTS,
        IDENTITY3,
        np.zeros(3),
        IDENTITY3,
    )
    arrays["face_loop_start"] = np.array([0, 4], np.int32)
    arrays["face_loop_total"] = np.array([4, 3], np.int32)
    return arrays


def game_table(arrays: Mapping[str, Any], normal_shift: float = 2e-4) -> low_side.TriangleTable:
    """Low-Game as deliver.py builds it: one loop per triangle corner, in order."""
    lt, lv = arrays["lt"], arrays["lv"]
    corners = [int(loop) for tri in lt for loop in tri]
    # Low-Game's normals passed through a custom-normal conversion: other float32 values.
    shifted = arrays["cn"][corners] + np.float32(normal_shift)
    normals = shifted.astype(np.float32).astype(np.float64).tolist()
    table, _ = low_side.table_from_document(
        {
            "positions": arrays["co"].astype(np.float64).tolist(),
            "triangles": lv[lt].tolist(),
            "loops": [[3 * k, 3 * k + 1, 3 * k + 2] for k in range(len(lt))],
            "uv": arrays["uv"].astype(np.float64)[corners].tolist(),
            "normals": normals,
            "exported_normals": normals,
        }
    )
    return table


def redelivered_of(table: low_side.TriangleTable) -> Any:
    """What replaying deliver.py's conversion gives when it reproduces Low-Game."""
    return np.array([table.normals[loop] for tri in table.loops for loop in tri], np.float32)


def write_low_game(directory: Path, table: low_side.TriangleTable) -> tuple[Path, dict[str, str]]:
    directory.mkdir(parents=True)
    exported = [table.normals[loop] for tri in table.loops for loop in tri]
    data = json.dumps(low_side.table_document(table, exported)).encode()
    (directory / low_side.TABLE_NAME).write_bytes(data)
    pins = {
        "obj_sha256": "a" * 64,
        "mtl_sha256": "b" * 64,
        "table_sha256": hashlib.sha256(data).hexdigest(),
    }
    record = {
        "schema": low_host.RECORD_SCHEMA,
        "source": {"sha256": low_host.SOURCE.sha256},
        "outputs": {
            "obj": {"sha256": pins["obj_sha256"]},
            "mtl": {"sha256": pins["mtl_sha256"]},
            "table": {"sha256": pins["table_sha256"]},
        },
        "mesh": {"digests": low_side.table_digests(table)},
    }
    path = directory / low_host.RECORD_NAME
    path.write_text(json.dumps(record), encoding="utf-8")
    return path, pins


def normal_png(samples: Any) -> tuple[bytes, SourcePin]:
    data = png.encode(samples, 16)
    pin = SourcePin("normal", "Textures/normal.png", hashlib.sha256(data).hexdigest(), len(data))
    return data, pin


NORMAL_SAMPLES = np.arange(4 * 3 * 3, dtype=np.uint16).reshape(3, 4, 3) * 1871 + 1


def make_scene(root: Path, arrays: dict[str, Any]) -> NS:
    """A source `.blend`, an Assets3D root with the Normal, and front N's accepted record of a
    Low-Game built from `arrays`."""
    blend = b"authored blend bytes"
    source = root / "assets" / "piece.blend"
    source.parent.mkdir(parents=True)
    source.write_bytes(blend)
    source_pin = SourcePin("blend", "piece.blend", hashlib.sha256(blend).hexdigest(), len(blend))
    data, normal_pin = normal_png(NORMAL_SAMPLES)
    normal = root / "assets" / normal_pin.assets3d_path
    normal.parent.mkdir(parents=True)
    normal.write_bytes(data)
    table = game_table(arrays)
    record, pins = write_low_game(root / "low-game", table)
    blender = root / "blender.exe"
    blender.write_bytes(b"authored blender bytes")
    return NS(
        blender=blender,
        root=root,
        assets=root / "assets",
        source=source,
        source_pin=source_pin,
        normal_pin=normal_pin,
        arrays=arrays,
        table=table,
        record=record,
        pins=pins,
        triangles=len(arrays["lt"]),
    )


@pytest.fixture
def scene(tmp_path: Path) -> NS:
    return make_scene(tmp_path, authored_arrays())


def accepted(scene: NS) -> dict[str, Any]:
    """The keyword arguments that re-check an extraction of `scene`."""
    return {"low_game_pins": scene.pins, "triangles": scene.triangles}


def plan(scene: NS, mode: str, run: str) -> host.Plan:
    run_dir = scene.root / "work" / run
    return host.Plan(
        mode=mode,
        blender=scene.blender,
        blender_sha256=sha256_file(scene.blender),
        script_sha256=sha256_file(host.SCRIPT),
        source=scene.source,
        source_origin="assets3d",
        run_dir=run_dir,
        command=host.blender_command(scene.blender, host.SCRIPT, run_dir, mode),
        source_pin=scene.source_pin,
    )


Runner = Callable[[Sequence[str], Path, Mapping[str, str], Path, int], int]


def fake_extract(
    arrays: Mapping[str, Any],
    code: int = 0,
    extra: str | None = None,
    redelivered: Any = None,
    identity: bool = True,
) -> Runner:
    replayed = redelivered_of(game_table(arrays)) if redelivered is None else redelivered

    def run(
        command: Sequence[str], cwd: Path, env: Mapping[str, str], log: Path, timeout: int
    ) -> int:
        assert command[-2:] == ("extract", str(cwd)) and env["TEMP"] == str(cwd)
        assert (cwd / side.SOURCE_BLEND_NAME).stat().st_mode & 0o222 == 0  # read-only copy
        log.write_text("authored\n", encoding="utf-8")
        if code:
            return code
        for name in side.LOW_ARRAYS:
            np.save(cwd / f"low.{name}.npy", arrays[name], allow_pickle=False)
        for name in side.FACE_ARRAYS:
            np.save(cwd / f"authoring.{name}.npy", arrays[name], allow_pickle=False)
        np.save(cwd / side.REDELIVERED_NAME, replayed, allow_pickle=False)
        report = {
            "extractor": side.EXTRACTOR,
            "mode": "extract",
            "blender": {"version": [5, 2, 3]},
            "blend": str(cwd / side.SOURCE_BLEND_NAME),
            "object": {
                "name": side.LOW_OBJECT,
                "depsgraph_mode": side.DEPSGRAPH_MODE,
                "vertices": len(arrays["co"]),
                "loops": len(arrays["lv"]),
                "polygons": len(arrays["face_loop_start"]),
                "loop_triangles": len(arrays["lt"]),
                "matrix_world": [
                    [1.0 if i == j else (0.0 if identity else 0.5) for j in range(4)]
                    for i in range(4)
                ],
                "matrix_is_identity": identity,
                "modifiers": [],
            },
            "part_attribute": [side.PART_ATTRIBUTE, "POINT", "FLOAT"],
            "uv_map": side.UV_MAP,
            "digests": {name: side.array_digest(a) for name, a in arrays.items()},
            "redelivered": {
                "donor": side.DELIVER_PATH,
                "donor_sha256": side.DELIVER_SHA256,
                "digest": side.array_digest(replayed),
            },
        }
        side.write_json(cwd / side.EXTRACT_REPORT, report)
        if extra:
            (cwd / extra).write_text("left behind", encoding="utf-8")
        return 0

    return run


def extract(scene: NS, run: str, runner: Runner) -> dict[str, Any]:
    return host.run_extract(
        plan(scene, "extract", run),
        scene.record,
        scene.assets,
        None,
        runner,
        normal_pin=scene.normal_pin,
        normal_layout=(4, 3, 16, 2),
        low_game_pins=scene.pins,
        triangles=scene.triangles,
    )


# --------------------------------------------------------------------------- Blender side
def test_blender_side_imports_nothing_from_the_repository() -> None:
    tree = ast.parse(Path(side.__file__).read_text(encoding="utf-8"))
    modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    modules += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not [m for m in modules if m.startswith("tools")]
    assert side.SOURCE_BLEND_NAME == low_side.SOURCE_BLEND_NAME


def test_donor_arrays_follow_the_donor_arithmetic() -> None:
    rotation = np.diag([2.0, 1.0, 0.5])
    translation = np.array([0.1, -0.2, 0.3])
    arrays = side.donor_arrays(
        POSITIONS,
        LOOP_TRIANGLES,
        FACE_LOOPS,
        UVS,
        NORMALS,
        PARTS,
        rotation,
        translation,
        np.linalg.inv(rotation).T,
    )
    expected = (rotation @ np.asarray(POSITIONS, np.float32).T).T + translation
    assert np.array_equal(arrays["co"], expected.astype(np.float32))
    assert arrays["lt"].shape == (3, 3) and arrays["lt"].dtype == np.int32
    norms = np.linalg.norm(arrays["cn"].astype(np.float64), axis=1)
    assert np.allclose(norms, 1.0, atol=1e-6)
    for name, (dtype, tail) in side.LOW_ARRAYS.items():
        assert arrays[name].dtype.str == dtype and arrays[name].shape[1:] == tail


def attribute(domain: str = "POINT", kind: str = "FLOAT", values: Sequence[float] = PARTS) -> NS:
    def foreach_get(name: str, out: Any) -> None:
        assert name == "value"
        out[:] = values

    return NS(domain=domain, data_type=kind, data=NS(foreach_get=foreach_get))


@pytest.mark.parametrize(
    ("attr", "message"),
    [
        (None, "no zero fallback"),
        (attribute(domain="FACE"), "pinned POINT/FLOAT"),
        (attribute(kind="INT"), "pinned POINT/FLOAT"),
        (attribute(values=[1.0, 1.5, 1, 1, 2, 2, 2]), "not part ids"),
        (attribute(values=[0.0, 1, 1, 1, 2, 2, 2]), "not part ids"),
    ],
)
def test_part_values_refuse_instead_of_zeroing(attr: Any, message: str) -> None:
    with pytest.raises(ExtractError, match=message):
        side.part_values(attr, len(PARTS))


def test_part_values_read_the_point_attribute() -> None:
    assert side.part_values(attribute(), len(PARTS)).tolist() == PARTS


def test_bake_options_are_complete_and_hold_the_donor_values() -> None:
    # Either API shape: view_from an operator option, or only a scene bake setting.
    with_view = [*side.BAKE_OPTIONS, "rna_type"]
    without_view = [name for name in with_view if name != "view_from"]
    assert side.option_problems(with_view, side.operator_pins(with_view)) == []
    assert side.option_problems(without_view, side.operator_pins(without_view)) == []
    assert "view_from" in side.operator_pins(with_view)
    assert "view_from" not in side.operator_pins(without_view)
    problems = side.option_problems([*with_view, "new_option"], side.operator_pins(with_view))
    assert problems == ["object.bake option 'new_option' is not pinned"]
    assert side.option_problems(["type"], {"type": "AO", "margin": 8}) == [
        "pinned option 'margin' is not an option of object.bake"
    ]
    donor = {"type": "AO", "use_selected_to_active": True, "max_ray_distance": 0.014}
    assert donor.items() <= side.BAKE_OPTIONS.items()
    assert (side.BAKE_OPTIONS["cage_extrusion"], side.BAKE_OPTIONS["margin"]) == (0.006, 8)
    assert side.BAKE_OPTIONS["use_cage"] is False and side.BAKE_OPTIONS["cage_object"] == ""
    assert side.bake_call_options(side.BAKE_OPTIONS)["pass_filter"] == set()
    assert side.BAKE_OPTIONS["view_from"] == "ABOVE_SURFACE"
    assert side.CYCLES_SETTINGS["device"] == "CPU" and side.CYCLES_SETTINGS["samples"] == 96
    assert side.CYCLES_SETTINGS["seed"] == 0 and side.AO_RESOLUTION == 2048


def test_ao_array_keeps_channel_r_and_blender_rows() -> None:
    pixels = np.arange(2 * 2 * 4, dtype=np.float32) / 16
    ao = side.ao_array(pixels, 2)
    assert ao.dtype == np.float16 and ao.tolist() == [[0.0, 0.25], [0.5, 0.75]]


def test_array_digest_names_dtype_shape_and_bytes() -> None:
    a = np.arange(6, dtype=np.int32)
    assert side.array_digest(a) == side.array_digest(a.copy())
    assert side.array_digest(a) != side.array_digest(a.reshape(2, 3))
    assert side.array_digest(a) != side.array_digest(a.astype(np.int64))


# ------------------------------------------------------------------------------ the Normal
def test_normal_is_decoded_at_16_bits_with_blender_rows() -> None:
    samples = NORMAL_SAMPLES.copy()
    samples[0, 0] = (0, 1, 65535)
    data, pin = normal_png(samples)
    array, info = host.normal_array(data, pin, (4, 3, 16, 2))
    assert array.dtype == np.float32 and array.shape == (3, 4, 3)
    expected = samples.astype(np.float32) / np.float32(65535)
    assert np.array_equal(array, expected[::-1])
    assert array[-1, 0].tolist() == [0.0, np.float32(1) / np.float32(65535), 1.0]
    assert info["chunks"] == [["IHDR", 1], ["IDAT", 1], ["IEND", 1]]
    assert info["channels"] == "RGB"


def test_normal_refuses_another_file_a_bad_crc_or_another_layout() -> None:
    data, pin = normal_png(NORMAL_SAMPLES)
    with pytest.raises(ExtractError, match="pinned"):
        host.normal_array(data + b"\0", pin, (4, 3, 16, 2))
    broken = bytearray(data)
    broken[-20] ^= 0xFF  # inside the IDAT body
    bad_pin = SourcePin("n", "n.png", hashlib.sha256(broken).hexdigest(), len(broken))
    with pytest.raises(ExtractError, match="CRC"):
        host.normal_array(bytes(broken), bad_pin, (4, 3, 16, 2))
    eight = png.encode(NORMAL_SAMPLES // 257, 8)
    eight_pin = SourcePin("n", "n.png", hashlib.sha256(eight).hexdigest(), len(eight))
    with pytest.raises(ExtractError, match="depth 8"):
        host.normal_array(eight, eight_pin, (4, 3, 16, 2))


def test_npz_bytes_are_fixed_and_load_with_numpy() -> None:
    members = [
        ("co", host.npy_bytes(np.ones((2, 3), np.float32))),
        ("lt", host.npy_bytes(np.zeros(3))),
    ]
    first = host.npz_bytes(members)
    assert first == host.npz_bytes(members)
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert [i.filename for i in archive.infolist()] == ["co.npy", "lt.npy"]
        assert {i.date_time for i in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}
    loaded = np.load(io.BytesIO(first), allow_pickle=False)
    assert loaded["co"].tolist() == [[1.0] * 3] * 2


# --------------------------------------------------------------------- Low-Game comparison
def test_low_problems_accept_the_same_low_and_record_the_normal_conversion() -> None:
    arrays = authored_arrays()
    table = game_table(arrays)
    assert host.low_problems(arrays, table, redelivered_of(table), 3) == []
    diagnostics = host.normal_diagnostics(arrays, table)
    assert diagnostics["authoring_vs_low_game_unequal_corners"] == diagnostics["corners"] == 9
    assert 1e-4 < diagnostics["authoring_vs_low_game_max_component"] < 3e-4


def _move_position(a: dict[str, Any], r: Any) -> None:
    a["co"][2, 1] = np.nextafter(a["co"][2, 1], np.float32(1))


def _move_uv(a: dict[str, Any], r: Any) -> None:
    a["uv"][3, 0] = np.nextafter(a["uv"][3, 0], np.float32(1))


def _replay_other_normal(a: dict[str, Any], r: Any) -> None:
    r[4, 2] = np.nextafter(r[4, 2], np.float32(2))


def _retriangulate(a: dict[str, Any], r: Any) -> None:
    a["lt"][1] = (1, 2, 3)


def _join_parts(a: dict[str, Any], r: Any) -> None:
    a["lining"][4] = 1.0


def _no_wrap(a: dict[str, Any], r: Any) -> None:
    a["lining"][:4] = 3.0


def _fractional_part(a: dict[str, Any], r: Any) -> None:
    a["lining"][4:] = 2.5


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (_move_position, "positions differ"),
        (_move_uv, "another corner UV"),
        (_replay_other_normal, "does not reproduce Low-Game's"),
        (_retriangulate, "name other vertices"),
        (_join_parts, "spans two PartId"),
        (_no_wrap, "no vertex has PartId 1"),
        (_fractional_part, "not part ids"),
    ],
)
def test_low_problems_refuse_any_difference(
    change: Callable[[dict[str, Any], Any], None], message: str
) -> None:
    arrays = authored_arrays()
    table = game_table(arrays)
    redelivered = redelivered_of(table)
    change(arrays, redelivered)
    assert any(message in p for p in host.low_problems(arrays, table, redelivered, 3))


def test_low_problems_refuse_another_triangle_count() -> None:
    arrays = authored_arrays()
    table = game_table(arrays)
    problems = host.low_problems(arrays, table, redelivered_of(table))
    assert any("loop triangles" in p for p in problems)


def test_load_low_game_checks_every_pin(scene: NS) -> None:
    _, table = host.load_low_game(scene.record, **scene.pins)
    assert table == scene.table
    with pytest.raises(ExtractError, match="obj"):
        host.load_low_game(scene.record, **{**scene.pins, "obj_sha256": "d" * 64})
    (scene.record.parent / low_side.TABLE_NAME).write_bytes(b"{}")
    with pytest.raises(ExtractError, match="does not hash"):
        host.load_low_game(scene.record, **scene.pins)


# --------------------------------------------------------------------------- host runs
def test_extract_writes_low_npz_highnormal_and_a_reproducible_record(scene: NS) -> None:
    record = extract(scene, "r1", fake_extract(scene.arrays))
    run_dir = scene.root / "work" / "r1"
    low = np.load(run_dir / host.LOW_NPZ, allow_pickle=False)
    assert list(low.keys()) == list(side.LOW_ARRAYS)
    for name in side.LOW_ARRAYS:
        assert np.array_equal(low[name], scene.arrays[name])
    normal = np.load(run_dir / host.HIGHNORMAL, allow_pickle=False)
    assert np.array_equal(normal, (NORMAL_SAMPLES.astype(np.float32) / np.float32(65535))[::-1])
    assert record["kind"] == "extract" and record["low"]["parts"] == {"1": 4, "2": 3}
    source = record["source"]
    assert source["copy_sha256_after"] == source["original_sha256_after"] == scene.source_pin.sha256
    assert json.loads((run_dir / host.RECORD_NAME).read_text(encoding="utf-8")) == record
    repeat = extract(scene, "r1-repeat", fake_extract(scene.arrays))
    assert host.compare_records(repeat, record) == []
    changed = json.loads(json.dumps(repeat))
    changed["outputs"][host.LOW_NPZ]["sha256"] = "0" * 64
    assert host.compare_records(changed, record)


def test_extract_refuses_a_mismatch_and_writes_no_low_npz(scene: NS) -> None:
    arrays = authored_arrays()
    _move_position(arrays, None)
    with pytest.raises(ExtractError, match="positions differ"):
        extract(scene, "r1", fake_extract(arrays, redelivered=redelivered_of(scene.table)))
    run_dir = scene.root / "work" / "r1"
    assert not (run_dir / host.LOW_NPZ).exists() and not (run_dir / host.RECORD_NAME).exists()
    replayed = redelivered_of(scene.table)
    replayed[0, 0] += np.float32(1e-3)
    with pytest.raises(ExtractError, match="does not reproduce"):
        extract(scene, "r2", fake_extract(scene.arrays, redelivered=replayed))
    assert not (scene.root / "work" / "r2" / host.LOW_NPZ).exists()


@pytest.mark.parametrize(
    ("runner", "message"),
    [
        (fake_extract(authored_arrays(), code=1), "Blender exited 1"),
        (fake_extract(authored_arrays(), extra="stray.txt"), "unexpected"),
    ],
)
def test_extract_refuses_a_failed_or_untidy_blender(
    scene: NS, runner: Runner, message: str
) -> None:
    with pytest.raises(ExtractError, match=message):
        extract(scene, "r1", runner)


def test_a_timeout_still_gets_the_after_run_hashes(scene: NS) -> None:
    def changes_the_source(
        command: Sequence[str], cwd: Path, env: Mapping[str, str], log: Path, timeout: int
    ) -> int:
        scene.source.write_bytes(b"changed during the run")
        raise subprocess.TimeoutExpired(list(command), timeout)

    def times_out(
        command: Sequence[str], cwd: Path, env: Mapping[str, str], log: Path, timeout: int
    ) -> int:
        raise subprocess.TimeoutExpired(list(command), timeout)

    with pytest.raises(subprocess.TimeoutExpired):
        extract(scene, "r1", times_out)
    with pytest.raises(ExtractError, match=r"changed during the run \(after TimeoutExpired"):
        extract(scene, "r2", changes_the_source)


def test_signed_zero_is_another_float32_bit_pattern() -> None:
    arrays = authored_arrays()
    table = game_table(arrays)
    assert arrays["co"][0, 0] == 0.0
    arrays["co"][0, 0] = -0.0
    problems = host.low_problems(arrays, table, redelivered_of(table), 3)
    assert any("positions differ" in p for p in problems)


def test_run_directories_are_fresh_and_outside_the_repository(tmp_path: Path) -> None:
    with pytest.raises(RecorderError, match="inside the repository"):
        host.run_dir_for("r1", REPO_ROOT / "tmp" / "scratch")
    (tmp_path / "r1").mkdir()
    with pytest.raises(ExtractError, match="already exists"):
        host.run_dir_for("r1", tmp_path)
    with pytest.raises(ExtractError, match="run name"):
        host.run_dir_for("../r1", tmp_path)


# object.bake's RNA defaults in Blender 5.2.3, as its readback showed them in ao-r1 and in front
# P's control (view_from's operator default is assumed equal to the scene default).
BAKE_DEFAULTS: dict[str, Any] = {
    "type": "COMBINED",
    "pass_filter": [],
    "filepath": "",
    "width": 512,
    "height": 512,
    "margin": 16,
    "margin_type": "EXTEND",
    "use_selected_to_active": False,
    "max_ray_distance": 0.0,
    "cage_extrusion": 0.0,
    "cage_object": "",
    "normal_space": "TANGENT",
    "normal_r": "POS_X",
    "normal_g": "POS_Y",
    "normal_b": "POS_Z",
    "target": "IMAGE_TEXTURES",
    "save_mode": "INTERNAL",
    "use_clear": False,
    "use_cage": False,
    "use_split_materials": False,
    "use_automatic_name": False,
    "uv_layer": "",
    "view_from": "ABOVE_SURFACE",
}


def unset_readback(names: Sequence[str], defaults: Mapping[str, Any]) -> dict[str, Any]:
    """The populated, all-unset, all-default readback Blender 5.2 gives in background."""
    return side.readback_state(names, dict(defaults), dict.fromkeys(names, False), defaults)


CUBE_DEFAULTS = {"size": 2.0, "location": [0.0, 0.0, 0.0]}


def fake_control(retains: bool = False, cube_moves: bool = True) -> Runner:
    """The control's Blender: the readbacks as measured (or retaining the call), the effects."""

    def readbacks(call: Mapping[str, Any], defaults: Mapping[str, Any]) -> tuple[Any, Any]:
        names = sorted(call)
        before = unset_readback(names, defaults)
        if not retains:
            return before, before
        after = side.readback_state(names, dict(call), dict.fromkeys(names, True), defaults)
        return before, after

    def run(
        command: Sequence[str], cwd: Path, env: Mapping[str, str], log: Path, timeout: int
    ) -> int:
        assert command[-2:] == ("control", str(cwd)) and timeout == host.TIMEOUTS_S["control"]
        assert side.SOURCE_BLEND_NAME not in " ".join(command)  # no file is opened
        log.write_text("authored\n", encoding="utf-8")
        cube_before, cube_after = readbacks(side.CONTROL_CUBE, CUBE_DEFAULTS)
        bake_defaults = {n: BAKE_DEFAULTS[n] for n in side.CONTROL_BAKE}
        bake_before, bake_after = readbacks(side.CONTROL_BAKE, bake_defaults)
        report = {
            "extractor": side.EXTRACTOR,
            "mode": "control",
            "blender": {"version": [5, 2, 3]},
            "cube": {
                "call": side.CONTROL_CUBE,
                "result": ["FINISHED"],
                "before": cube_before,
                "after": cube_after,
                "effect": {
                    "dimensions": [3.0, 3.0, 3.0] if cube_moves else [2.0, 2.0, 2.0],
                    "location": [1.0, 2.0, 3.0] if cube_moves else [0.0, 0.0, 0.0],
                },
            },
            "bake": {
                "call": side.CONTROL_BAKE,
                "result": ["FINISHED"],
                "before": bake_before,
                "after": bake_after,
                "effect": {"min": 1.0, "max": 1.0},
            },
        }
        side.write_json(cwd / side.CONTROL_REPORT, report)
        return 0

    return run


def control(scene: NS, run: str = "c1", runner: Runner | None = None) -> Path:
    host.run_control(
        scene.blender,
        scene.root / "work" / run,
        runner or fake_control(),
        blender_sha256=sha256_file(scene.blender),
    )
    path: Path = scene.root / "work" / run / host.RECORD_NAME
    return path


def ao(scene: NS, run: str, runner: Runner, control_record: Path | None = None) -> dict[str, Any]:
    return host.run_ao(
        plan(scene, "ao", run),
        scene.root / "work" / "x1" / host.RECORD_NAME,
        control_record or control(scene, f"{run}-control"),
        runner,
        **accepted(scene),
    )


def fake_ao(
    value: float = 0.5,
    digests: Mapping[str, str] | None = None,
    used: Mapping[str, Any] | None = None,
    view_from_on_operator: bool = True,
    scene_view_from: str = "ABOVE_SURFACE",
    pixel_max: float | None = None,
    readback: Mapping[str, Any] | None = None,
) -> Runner:
    passed = sorted(n for n in side.BAKE_OPTIONS if view_from_on_operator or n != "view_from")
    call = {name: side.BAKE_OPTIONS[name] for name in passed}
    defaults = {name: BAKE_DEFAULTS[name] for name in passed}
    before = unset_readback(passed, defaults)
    if readback is None:
        if used is None:  # what Blender 5.2 in background keeps: nothing (measured)
            readback = before
        else:
            values = {name: used[name] for name in passed}
            readback = side.readback_state(passed, values, dict.fromkeys(passed, True), defaults)

    def run(
        command: Sequence[str], cwd: Path, env: Mapping[str, str], log: Path, timeout: int
    ) -> int:
        assert command[-2:] == ("ao", str(cwd)) and timeout == host.TIMEOUTS_S["ao"]
        log.write_text("authored\n", encoding="utf-8")
        expect = json.loads((cwd / side.AO_EXPECT).read_text(encoding="utf-8"))["low_digests"]
        ao = np.full((side.AO_RESOLUTION,) * 2, value, np.float16)
        np.save(cwd / side.AO_NAME, ao, allow_pickle=False)
        report = {
            "extractor": side.EXTRACTOR,
            "mode": "ao",
            "blender": {"version": [5, 2, 3]},
            "blend": str(cwd / side.SOURCE_BLEND_NAME),
            "low": {"name": side.LOW_OBJECT, "digests": dict(digests or expect)},
            "high": {"name": side.HIGH_OBJECT},
            "as_found": {"world": {"ao_distance": 10.0}},
            "cycles_applied": side.CYCLES_SETTINGS,
            "bake_options": side.BAKE_OPTIONS,
            "operator_options": passed,
            "operator_call": call,
            "bake_readback_before": before,
            "bake_readback": readback,
            "bake_options_used": readback["used"],
            "scene_bake_after": {"view_from": scene_view_from},
            "image": {
                "name": side.AO_IMAGE,
                "colorspace": side.AO_COLORSPACE,
                "size": [side.AO_RESOLUTION] * 2,
            },
            "pixels": {
                "finite": True,
                "rgb_equal": True,
                "min": value,
                "max": pixel_max or value,
            },
            "digest": side.array_digest(ao),
        }
        side.write_json(cwd / side.AO_REPORT, report)
        return 0

    return run


def test_ao_bakes_on_the_accepted_low_and_reproduces(
    scene: NS, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(side, "AO_RESOLUTION", 4)
    extract(scene, "x1", fake_extract(scene.arrays))
    proof = control(scene)
    record = ao(scene, "ao1", fake_ao(), proof)
    expect = json.loads((scene.root / "work" / "ao1" / side.AO_EXPECT).read_text(encoding="utf-8"))
    assert expect["low_digests"] == {k: side.array_digest(a) for k, a in scene.arrays.items()}
    assert record["kind"] == "ao" and "NEW AO substitute" in record["label"]
    assert record["control"]["outcome"] == host.RETENTION_UNAVAILABLE
    assert record["control"]["record_sha256"] == sha256_file(proof)
    repeat = ao(scene, "ao2", fake_ao(), proof)
    assert host.compare_records(repeat, record) == []
    other = ao(scene, "ao3", fake_ao(value=0.25), proof)
    assert any("outputs" in p for p in host.compare_records(other, record))


def test_ao_refuses_another_low_or_a_tampered_extraction(
    scene: NS, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(side, "AO_RESOLUTION", 4)
    extract(scene, "x1", fake_extract(scene.arrays))
    with pytest.raises(ExtractError, match="low digests"):
        ao(scene, "ao1", fake_ao(digests={"co": "0" * 64}))
    (scene.root / "work" / "x1" / host.LOW_NPZ).write_bytes(b"changed")
    with pytest.raises(ExtractError, match="recorded"):
        ao(scene, "ao2", fake_ao())


def test_an_extraction_record_is_checked_again_not_trusted(scene: NS) -> None:
    extract(scene, "x1", fake_extract(scene.arrays))
    run_dir = scene.root / "work" / "x1"
    path = run_dir / host.RECORD_NAME
    assert host.load_extraction(path, scene.source_pin.sha256, **accepted(scene))["kind"]
    record = json.loads(path.read_text(encoding="utf-8"))
    for name in (host.HIGHNORMAL, side.REDELIVERED_NAME):
        dropped = {**record, "outputs": {k: v for k, v in record["outputs"].items() if k != name}}
        path.write_text(json.dumps(dropped), encoding="utf-8")
        with pytest.raises(ExtractError, match="exactly the extraction's outputs"):
            host.load_extraction(path, scene.source_pin.sha256, **accepted(scene))
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ExtractError, match="obj is"):
        host.load_extraction(
            path, scene.source_pin.sha256, low_game_pins={**scene.pins, "obj_sha256": "d" * 64}
        )


def test_ao_receipt_holds_the_options_object_bake_ran_with(
    scene: NS, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(side, "AO_RESOLUTION", 4)
    extract(scene, "x1", fake_extract(scene.arrays))
    # Blender 5.2 in background keeps no call state: unavailable, with the control's proof.
    receipt = ao(scene, "ao0", fake_ao())["ao"]
    assert receipt["bake_readback"]["status"] == "unavailable"
    assert receipt["bake_readback"]["kind"] == "populated"
    assert receipt["bake_options_used"] is None
    assert receipt["operator_call"] == side.BAKE_OPTIONS
    # A Blender that keeps the call: compared. RNA floats read back at float32.
    used = {**side.BAKE_OPTIONS, "max_ray_distance": float(np.float32(0.014))}
    record = ao(scene, "ao1", fake_ao(used=used))
    assert record["ao"]["bake_readback"]["status"] == "readback"
    assert record["ao"]["bake_options_used"] == used
    assert record["ao"]["bake_options"]["use_cage"] is False
    assert record["ao"]["scene_bake_after"] == {"view_from": "ABOVE_SURFACE"}
    # view_from as a scene-only setting is accepted when the scene holds the pin.
    ao(scene, "ao2", fake_ao(view_from_on_operator=False))
    names = sorted(side.BAKE_OPTIONS)
    defaults = {n: BAKE_DEFAULTS[n] for n in names}
    false_claim = {**unset_readback(names, defaults), "values": {**defaults, "margin": 8}}
    incomplete = {**unset_readback(names, defaults), "set": {"type": False}}
    for run, runner, message in (
        ("ao3", fake_ao(used={**used, "margin": 16}), "ran with margin 16"),
        ("ao4", fake_ao(scene_view_from="ACTIVE_CAMERA"), "bake view_from"),
        ("ao5", fake_ao(pixel_max=1.0001), "pixel range"),
        ("ao6", fake_ao(readback=false_claim), "not what its evidence shows"),
        ("ao7", fake_ao(readback=incomplete), "cover exactly the options passed"),
    ):
        with pytest.raises(ExtractError, match=message):
            ao(scene, run, runner)


def test_unavailable_needs_the_control_to_show_it(
    scene: NS, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(side, "AO_RESOLUTION", 4)
    extract(scene, "x1", fake_extract(scene.arrays))
    for run, runner, outcome in (
        ("c-retains", fake_control(retains=True), "retention-observed"),
        ("c-no-effect", fake_control(cube_moves=False), "inconclusive"),
    ):
        proof = control(scene, run, runner)
        assert json.loads(proof.read_text(encoding="utf-8"))["outcome"] == outcome
        with pytest.raises(ExtractError, match=f"the control shows {outcome}"):
            ao(scene, f"ao-{run}", fake_ao(), proof)
    proof = control(scene, "c-ok")
    record = json.loads(proof.read_text(encoding="utf-8"))
    record["outcome"] = "inconclusive"
    proof.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ExtractError, match="re-derives as retention-unavailable"):
        ao(scene, "ao-tampered", fake_ao(), proof)


def test_readback_state_needs_complete_declared_evidence() -> None:
    names = ["margin", "type"]
    defaults = {"margin": 16, "type": "COMBINED"}
    none = side.readback_state(names, None, None, defaults)
    assert (none["kind"], none["status"], none["used"]) == ("none", "unavailable", None)
    unset = side.readback_state(names, defaults, {"margin": False, "type": False}, defaults)
    assert (unset["kind"], unset["status"]) == ("populated", "unavailable")
    kept = side.readback_state(
        names, {"margin": 8, "type": "AO"}, {"margin": True, "type": True}, defaults
    )
    assert kept["status"] == "readback" and kept["used"] == {"margin": 8, "type": "AO"}
    for args, message in (
        (([], {}, {}, {}), "names of the options"),
        ((names, {}, {}, defaults), "cover exactly"),
        ((names, defaults, {"margin": False, "type": 0}, defaults), "not a bool"),
        ((names, None, {"margin": False, "type": False}, defaults), "carries no"),
        ((names, defaults, {"margin": False, "type": False}, {"margin": 16}), "defaults"),
    ):
        with pytest.raises(ExtractError, match=message):
            side.readback_state(*args)


# --------------------------------------------------------------------------------- centre
def wrap_mesh(seed: int, centre: tuple[float, float] = (0.00213, 0.03917)) -> dict[str, Any]:
    """A wrap as `low_gen.wrap_low` builds it (columns at its angles, 13 rows, x = cx + R sin,
    y = cy - R cos) plus a hem quad of part 2, under shuffled vertex and face orders."""
    rng = np.random.default_rng(seed)
    degrees = host.donor_column_degrees()
    count, rows = len(degrees), host.WRAP_ROWS
    theta = np.radians(degrees)[:, None]
    radius = 0.13 + 0.02 * rng.random((count, rows))
    grid = np.stack(
        [
            centre[0] + radius * np.sin(theta),
            centre[1] - radius * np.cos(theta),
            1.1 + 0.05 * rng.random((count, rows)),
        ],
        axis=-1,
    ).reshape(-1, 3)
    points = np.vstack(
        [grid, [[0.3, 0.3, 1.0], [0.31, 0.3, 1.0], [0.31, 0.31, 1.0], [0.3, 0.31, 1.0]]]
    )
    order = rng.permutation(len(points))  # vertex k of the grid becomes vertex order[k]
    co = np.empty((len(points), 3), np.float32)
    co[order] = points.astype(np.float32)

    def vid(i: int, r: int) -> int:
        return int(order[(i % count) * rows + r])

    faces: list[tuple[int, ...]] = [
        (vid(i, r), vid(i + 1, r), vid(i + 1, r + 1), vid(i, r + 1))
        for i in range(count)
        for r in range(rows - 1)
    ]
    faces.append(tuple(int(order[count * rows + k]) for k in range(4)))
    faces = [faces[k] for k in rng.permutation(len(faces))]
    lining = np.full(len(points), 2.0, np.float32)
    lining[order[: count * rows]] = 1.0
    sizes = [len(face) for face in faces]
    return {
        "co": co,
        "lv": np.array([v for face in faces for v in face], np.int32),
        "face_loop_start": np.array(np.cumsum([0, *sizes[:-1]]), np.int32),
        "face_loop_total": np.array(sizes, np.int32),
        "lining": lining,
        "centre": centre,
        "theta0": [vid(int(np.flatnonzero(degrees == 0.0)[0]), r) for r in range(rows)],
    }


def columns_of(mesh: Mapping[str, Any]) -> list[list[int]]:
    return host.wrap_columns(
        mesh["lv"], mesh["face_loop_start"], mesh["face_loop_total"], mesh["lining"]
    )


@pytest.mark.parametrize("seed", [3, 11])
def test_centre_is_derived_from_the_wrap_geometry(seed: int) -> None:
    mesh = wrap_mesh(seed)
    columns = columns_of(mesh)
    assert len(columns) == 94 and {len(c) for c in columns} == {13}
    derived = host.derive_centre(mesh["co"], columns)
    assert np.allclose(derived["centre"], mesh["centre"], rtol=0, atol=1e-7)
    assert derived["theta0_x"] == float(np.float32(mesh["centre"][0]))
    assert [c["degrees"] for c in derived["intersection"]] == [0.0, 88.0]
    assert derived["hypotheses"] == 188 and derived["condition_number"] < 1.1
    assert derived["max_residual_over_tolerance"] <= 1.0
    theta0 = derived["intersection"][0]["column"]
    assert sorted(columns[theta0]) == sorted(mesh["theta0"])


def test_centre_refuses_a_vertex_off_its_radial_line() -> None:
    mesh = wrap_mesh(3)
    columns = columns_of(mesh)
    vertex = columns[40][6]
    offset = mesh["co"][vertex, :2].astype(np.float64) - mesh["centre"]
    normal = np.array([-offset[1], offset[0]]) / np.hypot(*offset)  # (cos theta, sin theta)
    mesh["co"][vertex, :2] += (2e-6 * normal).astype(np.float32)
    with pytest.raises(CentreError, match="0 of 188"):
        host.derive_centre(mesh["co"], columns)


def test_centre_refuses_another_column_count() -> None:
    mesh = wrap_mesh(3)
    with pytest.raises(CentreError, match="93 wrap columns"):
        host.derive_centre(mesh["co"], columns_of(mesh)[:-1])


def test_wrap_topology_refuses_a_split_quad_or_a_joined_part() -> None:
    mesh = wrap_mesh(3)
    lv, start, total = mesh["lv"].tolist(), mesh["face_loop_start"], mesh["face_loop_total"]
    k = int(np.flatnonzero(mesh["lining"][mesh["lv"][start]] == 1.0)[0])
    a, b, c, d = lv[start[k] : start[k] + 4]
    split = [*lv[: start[k]], a, b, c, a, c, d, *lv[start[k] + 4 :]]
    sizes = [*total[:k].tolist(), 3, 3, *total[k + 1 :].tolist()]
    starts = np.cumsum([0, *sizes[:-1]])
    with pytest.raises(CentreError, match="not a quad"):
        host.wrap_columns(np.array(split), starts, np.array(sizes), mesh["lining"])
    joined = mesh["lining"].copy()
    joined[a] = 2.0
    with pytest.raises(CentreError, match="joins the wrap"):
        host.wrap_columns(mesh["lv"], start, total, joined)


def wrap_arrays(mesh: Mapping[str, Any]) -> dict[str, Any]:
    """The wrap mesh as the extraction's arrays: each quad split along its first diagonal."""
    lt = [
        tri
        for s in mesh["face_loop_start"].tolist()
        for tri in ((s, s + 1, s + 2), (s, s + 2, s + 3))
    ]
    loops = len(mesh["lv"])
    return {
        "co": mesh["co"],
        "lt": np.array(lt, np.int32),
        "lv": mesh["lv"],
        "uv": (np.arange(2 * loops, dtype=np.float32).reshape(-1, 2) % 97) / np.float32(97),
        "cn": np.tile(np.array([0.0, 0.0, 1.0], np.float32), (loops, 1)),
        "lining": mesh["lining"],
        "face_loop_start": mesh["face_loop_start"],
        "face_loop_total": mesh["face_loop_total"],
    }


def wrap_extraction(root: Path, identity: bool = True) -> tuple[NS, Path]:
    """A wrap scene through the whole extraction (fake Blender), so its record is real."""
    wrap = make_scene(root, wrap_arrays(wrap_mesh(5)))
    extract(wrap, "x1", fake_extract(wrap.arrays, identity=identity))
    return wrap, root / "work" / "x1" / host.RECORD_NAME


def test_run_centre_derives_and_labels_the_result(tmp_path: Path) -> None:
    wrap, path = wrap_extraction(tmp_path)
    checks = {"source_sha256": wrap.source_pin.sha256, **accepted(wrap)}
    record = host.run_centre(tmp_path / "c1", derive=path, **checks)
    assert record["status"] == "derived-from-preserved-geometry"
    assert "DERIVED FROM PRESERVED GEOMETRY" in record["label"]
    assert "not the historical construction.npz" in record["historical"]
    assert np.allclose(record["centre"], wrap_mesh(5)["centre"], rtol=0, atol=1e-7)
    centre = np.load(tmp_path / "c1" / host.CENTRE_NPZ, allow_pickle=False)["centre"]
    assert centre.dtype == np.float64 and centre.tolist() == record["centre"]
    repeat = host.run_centre(tmp_path / "c2", derive=path, **checks)
    assert host.compare_records(repeat, record) == []


def test_run_centre_needs_the_identity_matrix(tmp_path: Path) -> None:
    wrap, path = wrap_extraction(tmp_path, identity=False)
    checks = {"source_sha256": wrap.source_pin.sha256, **accepted(wrap)}
    with pytest.raises(CentreError, match="identity matrix"):
        host.run_centre(tmp_path / "c1", derive=path, **checks)
    assert not (tmp_path / "c1").exists()
    # Editing the record's flag alone does not pass: it must be the report's.
    record = json.loads(path.read_text(encoding="utf-8"))
    record["low"]["object"]["matrix_is_identity"] = True
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ExtractError, match="object facts"):
        host.run_centre(tmp_path / "c2", derive=path, **checks)


def test_run_centre_authored_or_missing(tmp_path: Path) -> None:
    authored = host.run_centre(tmp_path / "a", authored=(0.0, 0.039), provenance="owner note")
    assert authored["status"] == "authored" and authored["provenance"] == "owner note"
    assert (tmp_path / "a" / host.CENTRE_NPZ).is_file()
    missing = host.run_centre(tmp_path / "m", missing="no preserved assembly")
    assert missing["status"] == "missing" and not (tmp_path / "m" / host.CENTRE_NPZ).exists()
    with pytest.raises(ExtractError, match="provenance"):
        host.run_centre(tmp_path / "b", authored=(0.0, 0.039), provenance=" ")
    with pytest.raises(ExtractError, match="exactly one"):
        host.run_centre(tmp_path / "b", authored=(0.0, 0.0), missing="x")
