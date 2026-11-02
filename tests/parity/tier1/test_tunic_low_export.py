"""The Tunic v10 low exporter and extraction on authored data, with no Blender (decision 300 s. 7).

The "Blender" of the host tests is a Python function that writes what the Blender side would write
for a two-triangle stand-in; the Blender side's pure helpers run on small authored stand-ins for
its RNA collections. Nothing here opens the Tunic `.blend`, runs Blender or claims anything about
the real file.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import shutil
import subprocess
import zipfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

import numpy as np
import pytest

from tools.parity.recorder import tunic
from tools.parity.recorder.job import sha256_file
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier1 import sash_intermediates_blender, sash_low_blender, tunic_intermediates
from tools.parity.tier1 import tunic_intermediates_blender as inspect_side
from tools.parity.tier1 import tunic_low_blender as side
from tools.parity.tier1 import tunic_low_export as host
from tools.parity.tier1.sash_low_export import SourcePin
from tools.parity.tier1.tunic_low_blender import ExportError

Runner = Callable[[Sequence[str], Path, Mapping[str, str], Path, int], int]
NORMAL_SHAPE = (4, 2, 3)


# ----------------------------------------------------------------------------- pins
def test_pins_follow_the_contract_the_inspection_and_the_precedent() -> None:
    assert host.pin_problems() == []
    assert side.SOURCE_MATERIALS == ("DefaultMaterial.001",)  # literally, never DefaultMaterial
    assert side.TEXTURE_SET == "DefaultMaterial"
    assert side.REMAP["source_material"] == "DefaultMaterial.001"
    assert side.REMAP["export_material"] == "DefaultMaterial"
    assert "not the recovered historical material" in side.REMAP.values()
    assert side.OBJ_EXPORT_OPTIONS == sash_low_blender.OBJ_EXPORT_OPTIONS
    assert side.FILE_BROWSER_OPTIONS == sash_low_blender.FILE_BROWSER_OPTIONS
    assert (side.VERTICES, side.TRIANGLES) == (5392, 11000)
    assert side.NORMAL_SETTINGS["colorspace"] == "Non-Color"
    assert (side.NORMAL_IMAGE, side.NORMAL_SHA256) == tunic.NORMAL
    assert side.DONOR_BLOB_SHA256 == inspect_side.DONOR_BLOB_SHA256
    assert getattr(host, "SOURCE") is tunic_intermediates.SOURCE  # noqa: B009 (not re-exported)
    assert tunic_intermediates.SOURCE.sha256.startswith("f6243a57")
    assert host.CONVENTIONS["positions"]["tolerance"] == 5e-7 + 1e-7
    assert host.CONVENTIONS["normals"]["tolerance"] == 5e-5 + 1e-6


def test_the_blender_side_imports_nothing_from_the_repository_and_saves_no_file() -> None:
    tree = ast.parse(Path(side.__file__).read_text(encoding="utf-8"))
    modules = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    modules += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in modules if m.startswith("tools")]
    # Only numpy's `np.save` of the arrays: no `save_mainfile`, `image.save`, `pack`, ...
    saves = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and (n.attr.startswith("save") or n.attr == "pack")
    ]
    assert saves and all(isinstance(n.value, ast.Name) and n.value.id == "np" for n in saves)


def test_shared_helpers_equal_their_precedents() -> None:
    rng = np.random.default_rng(3)
    values = rng.random(9).astype(np.float32)
    tris = rng.integers(0, 9, size=(7, 3))
    assert side.crossings(values, side.triangle_edges(tris)) == inspect_side.crossings(
        values, inspect_side.triangle_edges(tris)
    )
    array = rng.random((3, 2)).astype(np.float32)
    assert side.array_digest(array) == sash_intermediates_blender.array_digest(array)
    assert side.png_header(b"x" * 40) is None


# ----------------------------------------------------------------------------- the donor
def test_donor_arrays_are_the_donors_arithmetic() -> None:
    rng = np.random.default_rng(7)
    raw = {
        "co": rng.normal(size=12).astype(np.float32),
        "lt": np.arange(6, dtype=np.int32),
        "lv": np.array([0, 1, 2, 0, 2, 3], np.int32),
        "uv": rng.random(12).astype(np.float32),
        "cn": rng.normal(size=18).astype(np.float32),
    }
    lining = np.array([0.0, 0.25, 1.0, 0.0], np.float32)
    rotation = np.array([[0.0, -2.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 3.0]])
    translation = np.array([0.5, -1.0, 2.0])
    normal_matrix = np.linalg.inv(rotation).T
    arrays = side.donor_arrays(raw, lining, rotation, translation, normal_matrix)
    # garment_blender_io.py extract, lines 73-92, written out again.
    co = (rotation @ raw["co"].reshape(-1, 3).T).T + translation
    cn = (normal_matrix @ raw["cn"].reshape(-1, 3).T).T
    cn = cn / (np.linalg.norm(cn, axis=1, keepdims=True) + 1e-12)
    assert np.array_equal(arrays["co"], co.astype(np.float32))
    assert np.array_equal(arrays["cn"], cn.astype(np.float32))
    assert arrays["lt"].shape == (2, 3) and arrays["uv"].shape == (6, 2)
    assert {k: (a.dtype.str, a.shape[1:]) for k, a in arrays.items()} == side.LOW_ARRAYS
    assert list(arrays) == list(side.LOW_ARRAYS)


def test_decode_normal_keeps_rgb_rows_bottom_first() -> None:
    pixels = np.arange(2 * 3 * 4, dtype=np.float32)
    decoded = side.decode_normal(pixels, 3, 2)
    assert decoded.shape == (2, 3, 3) and decoded.dtype == np.float32
    assert decoded[0, 0].tolist() == [0.0, 1.0, 2.0]  # the first row of image.pixels
    assert decoded[1, 2].tolist() == [20.0, 21.0, 22.0]


class Collection(list[Any]):
    """An RNA collection stand-in: `foreach_get` fills a flat buffer from per-item values."""

    def __init__(self, items: Sequence[Any], fields: Mapping[str, Any]):
        super().__init__(items)
        self.fields = fields
        self.active: Any = None

    def foreach_get(self, name: str, buffer: Any) -> None:
        buffer[:] = np.asarray(self.fields[name]).ravel()

    def get(self, name: str) -> Any:
        return next((item for item in self if getattr(item, "name", None) == name), None)


def test_lining_values_refuse_where_the_donor_zero_fills() -> None:
    def attribute(domain: str = "POINT", kind: str = "FLOAT") -> NS:
        return NS(domain=domain, data_type=kind, data=Collection([], {"value": [0, 1, 0.5]}))

    assert side.lining_values(attribute(), 3).tolist() == [0.0, 1.0, 0.5]
    with pytest.raises(ExportError, match="no zero fallback"):
        side.lining_values(None, 3)
    with pytest.raises(ExportError, match="FACE/FLOAT"):
        side.lining_values(attribute(domain="FACE"), 3)
    with pytest.raises(ExportError, match="POINT/INT"):
        side.lining_values(attribute(kind="INT"), 3)


def test_lining_problems() -> None:
    tris = [0, 1, 2, 0, 2, 3]
    good = np.array([0.0, 0.25, 1.0, 0.0], np.float32)
    assert side.lining_problems(good, 4, tris) == []
    assert side.lining_summary(good, tris)["crossings_triangle_edges"] == 3
    nan = good.copy()
    nan[1] = np.nan
    assert "non-finite" in side.lining_problems(nan, 4, tris)[0]
    assert "no triangle edge" in side.lining_problems(np.zeros(4, np.float32), 4, tris)[0]
    at = np.array([0.5, 0.5, 1.0, 0.5], np.float32)  # touching 0.5 is not crossing it
    assert "no triangle edge" in side.lining_problems(at, 4, tris)[0]
    assert "pinned float32" in side.lining_problems(good.astype(np.float64), 4, tris)[0]
    assert "pinned float32" in side.lining_problems(good[:3], 4, tris)[0]


def test_triangulation_problems(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(side, "VERTICES", 4)
    monkeypatch.setattr(side, "TRIANGLES", 2)
    assert side.triangulation_problems(np.arange(6), [3, 3], 4) == []
    assert "pinned 4" in side.triangulation_problems(np.arange(6), [3, 3], 5)[0]
    assert "not triangles" in side.triangulation_problems(np.arange(6), [4, 2], 4)[0]
    rotated = [1, 2, 0, 3, 4, 5]
    assert "in order" in side.triangulation_problems(rotated, [3, 3], 4)[0]


def test_read_mesh_reads_the_donors_buffers() -> None:
    uv = NS(name="UVMap", data=Collection([], {"uv": [[0.1, 0.2]] * 6}))
    mesh = NS(
        vertices=Collection([0] * 4, {"co": np.arange(12)}),
        loops=Collection([0] * 6, {"vertex_index": [0, 1, 2, 0, 2, 3]}),
        loop_triangles=Collection([0, 0], {"loops": np.arange(6)}),
        uv_layers=Collection([uv], {}),
        corner_normals=Collection([], {"vector": [[0.0, 0.0, 1.0]] * 6}),
        polygons=Collection([0, 0], {"loop_total": [3, 3]}),
    )
    mesh.uv_layers.active = uv
    raw = side.read_mesh(mesh)
    assert raw["co"].dtype == np.float32 and raw["co"].shape == (12,)
    assert raw["lt"].dtype == np.int32 and raw["lv"].tolist() == [0, 1, 2, 0, 2, 3]
    assert raw["uv"].shape == (12,) and raw["cn"].shape == (18,)
    assert raw["loop_total"].tolist() == [3, 3]
    assert sorted(side.raw_digests(raw)) == ["cn", "co", "lt", "lv", "uv"]
    mesh.uv_layers.active = NS(name="Other")
    with pytest.raises(ExportError, match="active UV layer"):
        side.read_mesh(mesh)


IDENTITY = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]


def source_object(**changes: Any) -> NS:
    layer = NS(name="UVMap")
    layers = Collection([layer], {})
    layers.active = layer
    obj = NS(
        name=side.SOURCE_OBJECT,
        type="MESH",
        modifiers=[],
        constraints=[],
        matrix_world=IDENTITY,
        material_slots=[NS(material=NS(name="DefaultMaterial.001"))],
        data=NS(shape_keys=None, uv_layers=layers),
    )
    obj.__dict__.update(changes)
    return obj


def test_source_problems() -> None:
    assert side.source_problems(source_object()) == []
    assert "not a MESH" in side.source_problems(source_object(type="CURVE"))[0]
    found = side.source_problems(
        source_object(
            modifiers=[NS(name="Armature", type="ARMATURE")],
            constraints=[object()],
            matrix_world=[[2.0 if i == j else 0.0 for j in range(4)] for i in range(4)],
            material_slots=[NS(material=NS(name="DefaultMaterial"))],
        )
    )
    assert [p.split(" ")[0] for p in found] == ["modifier", "the", "world", "material"]
    assert "pinned ['DefaultMaterial.001']" in found[3]
    shaped = source_object()
    shaped.data.shape_keys = object()
    assert side.source_problems(shaped) == ["the mesh has shape keys"]
    two = source_object()
    two.data.uv_layers.append(NS(name="UV2"))
    assert "UV layers" in side.source_problems(two)[0]


def test_name_problems_and_options() -> None:
    empty = Collection([], {})
    assert side.name_problems(empty, empty, empty) == []
    taken = Collection([NS(name="DefaultMaterial")], {})
    assert side.name_problems(taken, empty, empty) == [
        "the file already holds a material named 'DefaultMaterial'"
    ]
    names = [*side.OBJ_EXPORT_OPTIONS, "filepath", "filter_glob", "rna_type"]
    assert side.option_problems(names, side.OBJ_EXPORT_OPTIONS) == []
    assert side.option_problems([*names, "new_option"], side.OBJ_EXPORT_OPTIONS) == [
        "wm.obj_export option 'new_option' is not pinned"
    ]


def normal_identity(**png: Any) -> dict[str, Any]:
    return {"sha256": side.NORMAL_SHA256, "png": {**side.NORMAL_PNG, **png}}


def test_normal_problems_check_the_bytes_and_settings_before_any_decode() -> None:
    settings = dict(side.NORMAL_SETTINGS)
    assert side.normal_problems(normal_identity(), settings) == []
    assert side.normal_problems(None, settings) == [f"{side.NORMAL_IMAGE} has no packed file"]
    assert (
        "packed SHA-256" in side.normal_problems({**normal_identity(), "sha256": "0"}, settings)[0]
    )
    assert "PNG header" in side.normal_problems(normal_identity(bit_depth=8), settings)[0]
    srgb = {**settings, "colorspace": "sRGB"}
    assert side.normal_problems(normal_identity(), srgb) == [
        f"{side.NORMAL_IMAGE} colorspace is 'sRGB', pinned 'Non-Color'"
    ]
    extra = {**settings, "view_as_render": False}
    assert "not pinned" in side.normal_problems(normal_identity(), extra)[0]


def test_image_settings_and_loaded() -> None:
    image = NS(
        type="IMAGE",
        source="FILE",
        file_format="PNG",
        packed_files=[object()],
        colorspace_settings=NS(name="Non-Color", is_data=True),
        alpha_mode="STRAIGHT",
        use_half_precision=True,
        size=(4096, 4096),
        channels=4,
        depth=96,
        is_float=True,
        has_data=True,
        is_dirty=False,
    )
    assert side.image_settings(image) == side.NORMAL_SETTINGS
    assert side.image_loaded(image) == side.NORMAL_LOADED


# ------------------------------------------------------------------------------- the host
def stand_in() -> dict[str, Any]:
    """Two triangles of a quad, the raw buffers the Blender side reads, and what it derives."""
    raw = {
        "co": np.array([0, 0, 0, 1, 0, 0, 1, 0.0078125, 0, 0, 1, 0.25], np.float32),
        "lt": np.arange(6, dtype=np.int32),
        "lv": np.array([0, 1, 2, 0, 2, 3], np.int32),
        "uv": np.array([0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0.0078125, 1], np.float32),
    }
    normals = np.array([[0.0, 0.0, 1.0], [0.6, 0.0, 0.8], [0.0, 0.6, 0.8]] * 2, np.float32)
    raw["cn"] = normals.ravel()
    lining = np.array([0.0, 0.25, 1.0, 0.0], np.float32)
    arrays = side.donor_arrays(raw, lining, np.eye(3), np.zeros(3), np.eye(3))
    normal = np.arange(np.prod(NORMAL_SHAPE), dtype=np.float32).reshape(NORMAL_SHAPE) / 32
    return {"raw": raw, "arrays": arrays, "normal": normal}


def obj_text(arrays: Mapping[str, Any], raw_cn: Any, normal_offset: float = 0.0) -> str:
    """What Blender's exporter writes for the stand-in, with the pinned options."""
    lines = ["# Blender 5.2.3 LTS", "# www.blender.org", f"mtllib {side.MTL_NAME}"]
    lines.append(f"o {side.EXPORT_OBJECT}")
    for x, y, z in host.to_obj_axes(arrays["co"]):
        lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
    for u, v in arrays["uv"]:
        lines.append(f"vt {u:.6f} {v:.6f}")
    for x, y, z in host.to_obj_axes(raw_cn.reshape(-1, 3)):
        lines.append(f"vn {x + normal_offset:.4f} {y:.4f} {z:.4f}")
    lines += ["s 0", f"usemtl {side.TEXTURE_SET}"]
    for corners in arrays["lt"]:
        lines.append("f " + " ".join(f"{arrays['lv'][c] + 1}/{c + 1}/{c + 1}" for c in corners))
    return "\n".join(lines) + "\n"


MTL = (
    "# Blender 5.2.3 LTS MTL File: '18-Tunica-v10.blend'\n# www.blender.org\n\n"
    "newmtl DefaultMaterial\nNs 250.000000\nKd 0.800000 0.800000 0.800000\nd 1.000000\nillum 2\n"
)


def authored_report(cwd: Path, data: Mapping[str, Any]) -> dict[str, Any]:
    arrays, raw, normal = data["arrays"], data["raw"], data["normal"]
    settings = dict(side.NORMAL_SETTINGS)
    loaded = dict(side.NORMAL_LOADED)
    return {
        "exporter": side.EXPORTER,
        "mode": "export",
        "blender": {"version": [5, 2, 3], "numpy": "2.3.4"},
        "blend": str(cwd / side.SOURCE_BLEND_NAME),
        "depsgraph_mode": "VIEWPORT",
        "donor": host.DONOR,
        "precedent": side.PRECEDENT,
        "source": {
            "object": side.SOURCE_OBJECT,
            "materials": ["DefaultMaterial.001"],
            "modifiers": [],
            "matrix_world": IDENTITY,
            "matrix_is_identity": True,
            "uv_layers": ["UVMap"],
            "visibility_as_found": {"hide_get": False},
        },
        "remap": side.REMAP,
        "export": {
            "object": side.EXPORT_OBJECT,
            "material": side.TEXTURE_SET,
            "obj": side.OBJ_NAME,
            "mtl": side.MTL_NAME,
            "options": side.OBJ_EXPORT_OPTIONS,
            "readback_digests": side.raw_digests(raw),
        },
        "mesh": {"vertices": 4, "loops": 6, "polygons": 2, "triangles": 2},
        "lining": side.lining_summary(arrays["lining"], arrays["lv"][arrays["lt"]]),
        "normal": {
            "image": side.NORMAL_IMAGE,
            "packed": normal_identity(),
            "settings": settings,
            "loaded": loaded,
            "after_decode": {"settings": settings, "loaded": loaded},
            "decode": side.NORMAL_DECODE,
        },
        "digests": {
            **{name: side.array_digest(a) for name, a in arrays.items()},
            "evaluated_cn": side.array_digest(raw["cn"].reshape(-1, 3)),
            "highnormal": side.array_digest(normal),
        },
    }


def fake_blender(
    code: int = 0,
    extra: str | None = None,
    touch_copy: bool = False,
    timeout: bool = False,
    normal_offset: float = 0.0,
    mtl: str = MTL,
    edit: Callable[[dict[str, Any]], None] = lambda data: None,
    report: Callable[[dict[str, Any]], None] = lambda document: None,
) -> Runner:
    def run(
        command: Sequence[str], cwd: Path, env: Mapping[str, str], log: Path, seconds: int
    ) -> int:
        assert command[-2:] == ("export", str(cwd)) and env["TEMP"] == str(cwd)
        assert seconds == host.TIMEOUT_S
        copy = cwd / side.SOURCE_BLEND_NAME
        assert copy.stat().st_mode & 0o222 == 0  # read-only copy
        log.write_text("authored\n", encoding="utf-8")
        if timeout:
            raise subprocess.TimeoutExpired(list(command), seconds)
        if touch_copy:
            copy.chmod(0o666)
            copy.write_bytes(b"changed")
        if code:
            return code
        data = stand_in()
        document = authored_report(cwd, data)
        edit(data)
        report(document)
        for name, array in data["arrays"].items():
            np.save(cwd / side.LOW_FILES[name], array, allow_pickle=False)
        np.save(cwd / side.RAW_NORMALS, data["raw"]["cn"].reshape(-1, 3), allow_pickle=False)
        np.save(cwd / side.HIGHNORMAL, data["normal"], allow_pickle=False)
        text = obj_text(data["arrays"], data["raw"]["cn"], normal_offset)
        (cwd / side.OBJ_NAME).write_text(text, encoding="utf-8")
        (cwd / side.MTL_NAME).write_text(mtl, encoding="utf-8")
        side.write_json(cwd / side.REPORT_NAME, document)
        if extra:
            (cwd / extra).write_text("left behind", encoding="utf-8")
        return 0

    return run


@pytest.fixture
def scene(tmp_path: Path) -> NS:
    blend = b"authored blend bytes"
    pin = SourcePin(
        "blend", "piece/" + side.SOURCE_BLEND_NAME, hashlib.sha256(blend).hexdigest(), len(blend)
    )
    assets = tmp_path / "assets"
    source = assets / pin.assets3d_path
    source.parent.mkdir(parents=True)
    source.write_bytes(blend)
    blender = tmp_path / "blender.exe"
    blender.write_bytes(b"authored blender bytes")
    return NS(root=tmp_path, assets=assets, source=source, pin=pin, blender=blender)


def planned(scene: NS, run: str = "low-r1") -> host.Plan:
    return host.plan_export(
        scene.blender,
        run,
        scene.assets,
        None,
        source_pin=scene.pin,
        blender_sha256=sha256_file(scene.blender),
        work=scene.root / "work",
    )


def export(scene: NS, runner: Runner, run: str = "low-r1", **kwargs: Any) -> dict[str, Any]:
    return host.run_export(
        planned(scene, run), runner, vertices=4, triangles=2, normal_shape=NORMAL_SHAPE, **kwargs
    )


def on_disk(scene: NS, run: str = "low-r1") -> dict[str, Any]:
    path = scene.root / "work" / run / host.RECORD_NAME
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def test_plan_pins_the_command_and_writes_nothing(scene: NS) -> None:
    plan = planned(scene)
    assert plan.run_dir == (scene.root / "work" / "low-r1").resolve()
    assert not plan.run_dir.exists() and plan.source_origin == "assets3d"
    assert plan.command[1:6] == (
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "--offline-mode",
        "-noaudio",
    )
    assert plan.command[6] == str(plan.run_dir / side.SOURCE_BLEND_NAME)
    assert plan.command[-4:] == (str(host.SCRIPT), "--", "export", str(plan.run_dir))
    document = plan.as_json()
    assert document["script"]["blender_side"] == "tools/parity/tier1/tunic_low_blender.py"
    assert document["script"]["host_sha256"] == sha256_file(Path(host.__file__))
    assert document["conventions"] == host.CONVENTIONS and document["remap"] == side.REMAP


def test_plan_refuses_pins_an_existing_run_and_the_repository(scene: NS) -> None:
    with pytest.raises(ExportError, match="pinned"):
        host.plan_export(
            scene.blender, "r", scene.assets, None, source_pin=scene.pin, work=scene.root
        )
    with pytest.raises(ExportError, match="run name"):
        planned(scene, "../escape")
    other = SourcePin("blend", "piece/other.blend", scene.pin.sha256, 1)
    with pytest.raises(ExportError, match="source name"):
        host.plan_export(scene.blender, "r", scene.assets, None, source_pin=other)
    (scene.root / "work" / "low-r1").mkdir(parents=True)
    with pytest.raises(ExportError, match="already exists"):
        planned(scene)
    with pytest.raises(Exception, match="repository"):
        host.plan_export(
            scene.blender,
            "low-r1",
            scene.assets,
            None,
            source_pin=scene.pin,
            blender_sha256=sha256_file(scene.blender),
            work=REPO_ROOT / "tmp" / "scratch",
        )


def test_export_records_every_hash_the_remap_and_the_products(scene: NS) -> None:
    record = export(scene, fake_blender())
    assert record == on_disk(scene) and record["status"] == "exported"
    assert record["remap"] == side.REMAP and record["selection"]["materials"] == [
        "DefaultMaterial.001"
    ]
    hashes = record["hashes"]
    assert sorted(hashes) == sorted(host.HASH_KEYS)
    for stem, pinned in (
        ("original", scene.pin.sha256),
        ("copy", scene.pin.sha256),
        ("blender", sha256_file(scene.blender)),
        ("blender_side", sha256_file(host.SCRIPT)),
        ("host", sha256_file(host.HOST)),
    ):
        assert hashes[f"{stem}_sha256_before"] == hashes[f"{stem}_sha256_after"] == pinned
    run_dir = scene.root / "work" / "low-r1"
    assert {p.name for p in run_dir.iterdir()} == host.OUTPUTS | {host.LOW_NPZ, host.RECORD_NAME}
    assert sorted(record["outputs"]) == sorted(host.RECORD_OUTPUTS)
    assert record["lining"]["crossings_triangle_edges"] == 3
    assert record["obj_deviation"]["positions"] < host.CONVENTIONS["positions"]["tolerance"]
    # low.npz: what the donor's np.savez holds, member for member, and fixed zip metadata.
    data = stand_in()
    with np.load(run_dir / host.LOW_NPZ, allow_pickle=False) as packed:
        assert list(packed.files) == list(side.LOW_ARRAYS)
        for name, array in data["arrays"].items():
            assert packed[name].dtype == array.dtype and np.array_equal(packed[name], array)
    with zipfile.ZipFile(run_dir / host.LOW_NPZ) as archive:
        assert {info.date_time for info in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}
    buffer = io.BytesIO()
    np.save(buffer, data["normal"], allow_pickle=False)
    assert (run_dir / side.HIGHNORMAL).read_bytes() == buffer.getvalue()


def test_a_repeat_reproduces_byte_for_byte_and_a_difference_is_recorded(scene: NS) -> None:
    first = export(scene, fake_blender())
    again = export(scene, fake_blender(), run="low-r1-repeat", expected=first)
    assert again["expect"] == {"reproduced": True, "problems": []}
    assert again["outputs"][host.LOW_NPZ] == first["outputs"][host.LOW_NPZ]
    other_mtl = MTL.replace("Ns 250", "Ns 200")  # passes every check, other bytes
    moved = export(scene, fake_blender(mtl=other_mtl), run="low-r1-moved", expected=first)
    assert moved["expect"]["reproduced"] is False
    assert any(p.startswith("outputs") for p in moved["expect"]["problems"])
    assert on_disk(scene, "low-r1-moved")["expect"]["reproduced"] is False


def bad_cn(data: dict[str, Any]) -> None:
    data["arrays"]["cn"] = data["arrays"]["cn"] * np.float32(1.0000001)


def no_crossing(data: dict[str, Any]) -> None:
    data["arrays"]["lining"] = np.zeros(4, np.float32)


def rotated(data: dict[str, Any]) -> None:
    data["arrays"]["lt"] = data["arrays"]["lt"][:, [1, 2, 0]].copy()


def other_material(document: dict[str, Any]) -> None:
    document["source"]["materials"] = ["DefaultMaterial"]


def colour(document: dict[str, Any]) -> None:
    document["normal"]["settings"]["colorspace"] = "sRGB"


def readback(document: dict[str, Any]) -> None:
    document["export"]["readback_digests"]["cn"] = "0" * 64


@pytest.mark.parametrize(
    ("runner", "message"),
    [
        (fake_blender(code=3), "exited 3"),
        (fake_blender(extra="blender.crash.txt"), "unexpected"),
        (fake_blender(touch_copy=True), "copy"),
        (fake_blender(report=other_material), "source materials"),
        (fake_blender(report=colour), "normal settings"),
        (fake_blender(report=readback), "evaluated cn"),
        (fake_blender(normal_offset=1e-4), "OBJ normals"),
        (fake_blender(mtl=MTL + "map_Kd base.png\n"), "MTL names textures"),
        (fake_blender(mtl=MTL.replace("DefaultMaterial", "DefaultMaterial.001")), "MTL"),
        (fake_blender(edit=bad_cn), "donor's arithmetic"),
        (fake_blender(edit=no_crossing), "no triangle edge"),
        (fake_blender(edit=rotated), "in order"),
    ],
)
def test_a_refused_run_still_records_every_hash(scene: NS, runner: Runner, message: str) -> None:
    with pytest.raises(ExportError, match=message):
        export(scene, runner)
    record = on_disk(scene)
    assert record["status"] == "refused" and message in record["error"]
    hashes = record["hashes"]
    assert hashes["original_sha256_before"] == hashes["original_sha256_after"]
    assert hashes["blender_side_sha256_after"] == sha256_file(host.SCRIPT)
    expected = hashlib.sha256(b"changed").hexdigest() if message == "copy" else scene.pin.sha256
    assert hashes["copy_sha256_after"] == expected
    assert host.LOW_NPZ not in record["files"]


def test_a_timeout_records_the_after_hashes(scene: NS) -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        export(scene, fake_blender(timeout=True))
    record = on_disk(scene)
    assert record["status"] == "refused" and "TimeoutExpired" in record["error"]
    assert all(record["hashes"][key] is not None for key in host.HASH_KEYS)


def test_a_blender_changed_after_the_plan_is_not_launched(scene: NS) -> None:
    plan = planned(scene)
    scene.blender.write_bytes(b"another executable")

    def never(*args: Any) -> int:
        raise AssertionError("launched")

    with pytest.raises(ExportError, match="before the run blender"):
        host.run_export(plan, never)
    hashes = on_disk(scene)["hashes"]
    assert hashes["blender_sha256_before"] == hashlib.sha256(b"another executable").hexdigest()
    assert hashes["original_sha256_before"] == scene.pin.sha256
    assert hashes["copy_sha256_before"] is None  # refused before the copy is made
    assert_tool_hashes(hashes, scene, blender=hashlib.sha256(b"another executable").hexdigest())


def assert_tool_hashes(hashes: Mapping[str, Any], scene: NS, blender: str | None = None) -> None:
    """The executable and both scripts are hashed before and after, whatever failed."""
    pins = {
        "blender": blender or sha256_file(scene.blender),
        "blender_side": sha256_file(host.SCRIPT),
        "host": sha256_file(host.HOST),
    }
    for stem, pinned in pins.items():
        assert hashes[f"{stem}_sha256_before"] == hashes[f"{stem}_sha256_after"] == pinned


def test_a_source_changed_before_the_copy_is_refused_with_its_hash(scene: NS) -> None:
    plan = planned(scene)
    scene.source.write_bytes(b"changed after the plan")
    with pytest.raises(ExportError, match="before the run"):
        host.run_export(plan, fake_blender())
    hashes = on_disk(scene)["hashes"]
    changed = hashlib.sha256(b"changed after the plan").hexdigest()
    assert hashes["original_sha256_before"] == hashes["original_sha256_after"] == changed
    assert hashes["copy_sha256_before"] is None and hashes["copy_sha256_after"] is None
    assert_tool_hashes(hashes, scene)


@pytest.mark.parametrize("failing", ["copyfile", "chmod"])
def test_a_copy_or_chmod_failure_still_records_every_hash(
    scene: NS, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    def fail(*args: Any) -> None:
        raise PermissionError(f"{failing} denied")

    monkeypatch.setattr(shutil if failing == "copyfile" else os, failing, fail)
    with pytest.raises(PermissionError, match="denied"):
        host.run_export(planned(scene), fake_blender())
    record = on_disk(scene)
    assert record["status"] == "refused" and "denied" in record["error"]
    hashes = record["hashes"]
    assert hashes["original_sha256_before"] == hashes["original_sha256_after"] == scene.pin.sha256
    copied = scene.pin.sha256 if failing == "chmod" else None
    assert hashes["copy_sha256_before"] == hashes["copy_sha256_after"] == copied
    assert_tool_hashes(hashes, scene)


def test_obj_problems_name_vertices_and_tolerances() -> None:
    data = stand_in()
    text = obj_text(data["arrays"], data["raw"]["cn"])
    deviation: dict[str, float] = {}
    assert host.obj_problems(text, data["arrays"], deviation) == []
    assert sorted(deviation) == ["normals", "positions", "uv"]
    swapped = text.replace("f 1/1/1 2/2/2", "f 2/1/1 1/2/2")
    assert "name other vertices" in host.obj_problems(swapped, data["arrays"], {})[0]
    assert (
        "out of range" in host.obj_problems(text.replace("3/3/3", "9/3/3"), data["arrays"], {})[0]
    )
    renamed = text.replace(f"usemtl {side.TEXTURE_SET}", "usemtl DefaultMaterial.001")
    assert "usemtl" in host.obj_problems(renamed, data["arrays"], {})[0]
    assert "unexpected 'g'" in host.obj_problems(text + "g group\n", data["arrays"], {})[0]
    shifted = text.replace("v 1.000000", "v 1.000002", 1)
    assert "OBJ positions" in host.obj_problems(shifted, data["arrays"], {})[0]


def test_compare_records_ignores_only_the_run_specific_report() -> None:
    record = {
        "schema": host.RECORD_SCHEMA,
        "outputs": {side.REPORT_NAME: {"sha256": "a"}, side.OBJ_NAME: {"sha256": "b"}},
    }
    other = json.loads(json.dumps(record))
    other["outputs"][side.REPORT_NAME]["sha256"] = "c"
    problems = host.compare_records(record, other)
    assert not [p for p in problems if p.startswith("outputs")]
    other["outputs"][side.OBJ_NAME]["sha256"] = "d"
    assert [p for p in host.compare_records(record, other) if p.startswith("outputs")]


def test_the_cli_dry_run_and_a_wrong_expect(
    scene: NS, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = planned(scene, host.DEFAULT_RUN)
    monkeypatch.setattr(host, "locate", lambda: None)
    monkeypatch.setattr(host, "plan_export", lambda blender, run, assets, store: plan)
    argv = ["--blender", str(scene.blender), "--assets-root", str(scene.assets)]
    assert host.main([*argv, "--dry-run"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["command"][-2] == "export" and document["conventions"] == host.CONVENTIONS
    assert not (scene.root / "work").exists()
    wrong = scene.root / "wrong.json"
    wrong.write_text(json.dumps({"schema": "other"}), encoding="utf-8")
    assert host.main([*argv, "--expect", str(wrong)]) == 2
    assert "not an exported" in capsys.readouterr().err


def test_the_cli_prints_a_summary_without_paths(
    scene: NS, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = planned(scene, host.DEFAULT_RUN)
    run_export = host.run_export
    monkeypatch.setattr(host, "locate", lambda: None)
    monkeypatch.setattr(host, "plan_export", lambda blender, run, assets, store: plan)
    monkeypatch.setattr(
        host,
        "run_export",
        lambda plan, expected=None: run_export(
            plan, fake_blender(), expected, vertices=4, triangles=2, normal_shape=NORMAL_SHAPE
        ),
    )
    assert host.main(["--blender", str(scene.blender), "--assets-root", str(scene.assets)]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["status"] == "exported" and str(scene.root) not in out
