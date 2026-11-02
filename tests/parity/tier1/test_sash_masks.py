"""The Sash v5 masks producer on stand-in donors and authored receipts (decision 300 item 7).

The donors are authored stand-ins with the real `waist_masks.py`'s shape: the same import
prologue (ROOT found by `AGENTS.md`, `sys.path` inserts, `import garment_material_masks` and
`import waist_gen`), a `Field` with `valid`, `idx`, `out`, `tex` and `save_mask`, and a `sash`
whose one `save_mask` loop writes the 20 masks before its colour part reads `swatch("cloth")`.
They are committed to a throwaway git repository, so the producer reads them as raw blobs the way
it reads Assets3D. Front P's three receipts are authored with the same fields its records hold.
Nothing here reads Assets3D, the real intermediates or a swatch, or claims anything about the
real masks.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tools.parity.feasibility import png
from tools.parity.recorder import sash_current
from tools.parity.recorder.job import sha256_bytes, sha256_file
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier1 import sash_intermediates as host
from tools.parity.tier1 import sash_intermediates_blender as side
from tools.parity.tier1 import sash_masks as m
from tools.parity.tier1.sash_masks import MasksError

RES = 8
RUNTIME = {"python": "stand-in", "numpy": "stand-in"}
CENTRE = [0.0125, -0.025]

GM_CODE = '''"""Stand-in garment_material_masks: an asymmetric island and nearest-texel indices."""
import numpy as np


def rasterize(low, res):
    valid = np.zeros((res, res), bool)
    valid[: res // 2, : res // 2 + 1] = True
    valid[0, res - 1] = True
    return {"tri_id": np.where(valid, 0, -1)}


def nearest(valid):
    res = valid.shape[0]
    ys, xs = np.nonzero(valid)
    gy, gx = np.mgrid[0:res, 0:res]
    d = (gy[..., None] - ys) ** 2 + (gx[..., None] - xs) ** 2
    k = np.argmin(d, axis=-1)
    return np.stack([ys[k], xs[k]])
'''

G_CODE = '''"""Stand-in waist_gen."""
BELT_H = 0.0508
'''

MASKS_TEMPLATE = '''"""Stand-in waist_masks: the real import shape, Field and mask/colour split."""
import sys
from pathlib import Path

import numpy as np

from tools.parity.feasibility import png as PNG

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "AGENTS.md").exists())
sys.path.insert(0, str(ROOT / "Pipeline/painting"))
sys.path.insert(0, str(HERE))
import garment_material_masks as GM  # noqa: E402
import waist_gen as G  # noqa: E402

SW = {"cloth": ROOT / "Swatches/cloth.png", "hem": ROOT / "Swatches/hem.png"}


def sample(img, u, v):
    return np.ones((len(u), 3)) * img.mean()


class Field:
    def __init__(self, work, res, C):
        low = dict(np.load(work / "low.npz"))
        rz = GM.rasterize(low, res)
        self.res = res
        self.valid = rz["tri_id"] >= 0
        n = int(self.valid.sum())
        hn = np.load(work / "highnormal.npy")
        ao = np.load(work / "ao.npy").astype(np.float64)
        self.P = np.linspace(0.0, 1.0, n) * (1.0 + float(low["co"].sum()))
        self.ao = ao[self.valid]
        self.ridge = hn[..., 0][self.valid]
        self.r = np.full(n, float(np.hypot(*C["centre"])))
        self.idx = GM.nearest(self.valid)
        self.out = {}

    def tex(self, v):
        a = np.zeros((self.res, self.res), np.float32)
        a[self.valid] = v
        return a[self.idx[0], self.idx[1]]

    def save_mask(self, out, name, v):
        v = np.clip(np.nan_to_num(v), 0, 1)
        PNG.write(out / f"{name}.png", (self.tex(v)[::-1] * 65535 + 0.5).astype(np.uint16))
        self.out[name] = round(float(v.mean()), 5)

    def save_rgb(self, out, name, rgb):
        PNG.write(out / f"{name}.png", np.zeros((self.res, self.res, 3), np.uint16), 8)


def swatch(name):
    return PNG.read(SW[name]).astype(np.float64) / 255.0


def cyl_uv(F):
    return F.P, F.P


def sash(F, C, out):
    P = F.P
    cloth = P < 0.5 * P.max()
    hem = ~cloth
    level = P / P.max() * G.BELT_H / G.BELT_H + F.ridge * F.r
    for name, v in (PAIRS):
        F.save_mask(out, name, v)
    uu, vv = cyl_uv(F)
    col = sample(swatch("cloth"), uu, vv)
    col[hem] = sample(swatch("hem"), uu[hem], vv[hem])
    F.save_rgb(out, "T_sash", col)
'''


def masks_code(names: tuple[str, ...] = m.MASKS) -> str:
    pairs = [
        f'("{name}", cloth.astype(float))'
        if name == "M_cloth"
        else f'("{name}", (level * {k + 1} / 20 + 0.5 * F.ao) % 1.0)'
        for k, name in enumerate(names)
    ]
    return MASKS_TEMPLATE.replace("(PAIRS)", "(" + ", ".join(pairs) + ",)")


def git(root: Path, *args: str) -> str:
    command = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t"]
    command += ["-c", "core.autocrlf=false", *args]
    return subprocess.run(command, capture_output=True, check=True).stdout.decode().strip()


def donor_repo(root: Path, donor: str | None = None) -> m.Pins:
    """The three stand-ins committed at their Assets3D paths; pins computed from their bytes."""
    codes = {"garment_material_masks": GM_CODE, "waist_gen": G_CODE}
    codes["waist_masks"] = donor if donor is not None else masks_code()
    root.mkdir(parents=True)
    (root / "AGENTS.md").write_bytes(b"stand-in\n")
    sources = []
    for source in m.SOURCES:
        data = codes[source.name].encode("utf-8")
        path = root / source.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        checkout = None
        if source.checkout_sha256 is not None:
            checkout = sha256_bytes(data.replace(b"\n", b"\r\n"))
        sources.append(
            m.Source(
                source.name,
                source.path,
                m.git_blob_id(data),
                sha256_bytes(data),
                len(data),
                checkout,
            )
        )
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "stand-in donors")
    return m.Pins(
        snapshot=git(root, "rev-parse", "HEAD"),
        sources=tuple(sources),
        runtime=dict(RUNTIME),
        resolution=RES,
    )


def write_json(path: Path, record: dict[str, Any]) -> None:
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def entry(path: Path) -> dict[str, Any]:
    return {"sha256": sha256_file(path), "size_bytes": path.stat().st_size}


@dataclass
class World:
    extraction: Path
    ao: Path
    centre: Path

    def edit(self, path: Path, change: Callable[[dict[str, Any]], None]) -> None:
        record = json.loads(path.read_bytes())
        change(record)
        write_json(path, record)


def build_world(root: Path, ao_scale: float = 1.0) -> World:
    """Front P's extraction, AO and centre runs as their records hold them."""
    rng = np.random.default_rng(7)
    extract, ao_dir, centre_dir = root / "extract", root / "ao", root / "centre"
    for d in (extract, ao_dir, centre_dir):
        d.mkdir(parents=True)
    arrays: dict[str, Any] = {}
    for name, (dtype, tail) in side.LOW_ARRAYS.items():
        values = rng.integers(0, 4, size=(4, *tail)) if dtype == "<i4" else rng.random((4, *tail))
        arrays[name] = np.asarray(values, dtype)
    raw = {name: host.npy_bytes(array) for name, array in arrays.items()}
    for name, data in raw.items():
        (extract / host.LOW_FILES[name]).write_bytes(data)
    (extract / host.LOW_NPZ).write_bytes(host.npz_bytes(list(raw.items())))
    normal = rng.random((RES, RES, 3)).astype(np.float32)
    (extract / host.HIGHNORMAL).write_bytes(host.npy_bytes(normal))
    names = [host.LOW_NPZ, host.HIGHNORMAL, *host.LOW_FILES.values()]
    extraction = extract / host.RECORD_NAME
    write_json(
        extraction,
        {
            "schema": host.RECORD_SCHEMA,
            "kind": "extract",
            "low": {"digests": {k: side.array_digest(a) for k, a in arrays.items()}},
            "normal": {"digest": side.array_digest(normal)},
            "outputs": {name: entry(extract / name) for name in names},
        },
    )
    link = {"record": str(extraction), "record_sha256": sha256_file(extraction)}
    ao = (rng.random((RES, RES)) * ao_scale).astype(np.float16)
    (ao_dir / side.AO_NAME).write_bytes(host.npy_bytes(ao))
    ao_record = ao_dir / host.RECORD_NAME
    write_json(
        ao_record,
        {
            "schema": host.RECORD_SCHEMA,
            "kind": "ao",
            "extraction": link,
            "ao": {
                "low": {"digests": {k: side.array_digest(a) for k, a in arrays.items()}},
                "digest": side.array_digest(ao),
            },
            "outputs": {side.AO_NAME: entry(ao_dir / side.AO_NAME)},
        },
    )
    npz = host.npz_bytes([("centre", host.npy_bytes(np.asarray(CENTRE, np.float64)))])
    (centre_dir / host.CENTRE_NPZ).write_bytes(npz)
    centre = centre_dir / host.RECORD_NAME
    write_json(
        centre,
        {
            "schema": host.RECORD_SCHEMA,
            "kind": "centre",
            "status": m.CENTRE_STATUS,
            "centre": CENTRE,
            "extraction": link,
            "outputs": {host.CENTRE_NPZ: entry(centre_dir / host.CENTRE_NPZ)},
        },
    )
    return World(extraction, ao_record, centre)


def cited(record: Any) -> set[str]:
    """Every string value of a record at any depth (what a consumer's citation check reads)."""
    if isinstance(record, dict):
        return set().union(*(cited(v) for v in record.values()))
    if isinstance(record, list):
        return set().union(*(cited(v) for v in record))
    return {record} if isinstance(record, str) else set()


def read_record(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = json.loads(path.read_bytes())
    return record


@dataclass
class Setup:
    assets: Path
    pins: m.Pins
    world: World
    work: Path

    def plan(self, run: str = "masks-r1", **kwargs: Any) -> m.Plan:
        return m.plan(
            self.work / run,
            self.assets,
            self.world.extraction,
            self.world.ao,
            self.world.centre,
            pins=kwargs.pop("pins", self.pins),
            runtime=kwargs.pop("runtime", lambda: dict(RUNTIME)),
            verify_extraction=kwargs.pop("verify_extraction", read_record),
            **kwargs,
        )

    def produce(self, run: str = "masks-r1", **kwargs: Any) -> tuple[dict[str, Any], list[str]]:
        return m.produce(self.plan(run, **kwargs), self.assets, self.pins)


@pytest.fixture
def setup(tmp_path: Path) -> Setup:
    pins = donor_repo(tmp_path / "assets")
    return Setup(tmp_path / "assets", pins, build_world(tmp_path / "intermediates"), tmp_path / "w")


def test_twenty_masks_and_a_typed_receipt(setup: Setup) -> None:
    path_before = list(sys.path)
    record, problems = setup.produce()
    assert problems == []
    assert sys.path == path_before
    assert not {s.name for s in m.SOURCES} & set(sys.modules)
    run_dir = setup.work / "masks-r1"
    staged = {host.LOW_NPZ, host.HIGHNORMAL, side.AO_NAME, host.CENTRE_NPZ}
    pngs = {f"{name}.png" for name in m.MASKS}
    assert {p.name for p in run_dir.iterdir()} == staged | pngs | {m.RECORD_NAME}
    assert read_record(run_dir / m.RECORD_NAME) == record
    assert (record["schema"], record["kind"], record["status"]) == (
        m.RECORD_SCHEMA,
        "masks",
        "produced",
    )
    assert [o["name"] for o in record["outputs"]] == list(m.MASKS)
    for output in record["outputs"]:
        data = (run_dir / output["file"]).read_bytes()
        assert output["sha256"] == sha256_bytes(data) and output["size_bytes"] == len(data)
        assert (output["shape"], output["depth"], output["colour_type"]) == ([RES, RES], 16, 0)
        assert (data[:8], data[12:16], data[24], data[25]) == (png.SIGNATURE, b"IHDR", 16, 0)
        role = "auxiliary" if output["name"] == "M_cloth" else "stack-input"
        assert output["role"] == role
        # What front R's consumer reads: the receipt cites each mask and P's extraction receipt.
        assert output["sha256"] in cited(record)
    assert sorted(record["stack_inputs"]) == list(m.STACK_MASKS)
    assert record["auxiliary"] == ["M_cloth"]
    link = sha256_file(setup.world.extraction)
    assert link in cited(record)
    assert record["extraction_link"] == {
        "extraction_record_sha256": link,
        "cited_by": ["ao", "centre"],
    }
    assert record["receipts"]["ao"]["sha256"] == sha256_file(setup.world.ao)
    assert record["receipts"]["centre"]["sha256"] == sha256_file(setup.world.centre)
    for name, arrays in record["arrays"].items():
        assert arrays["sha256"] == sha256_file(run_dir / name)
    assert record["split"]["boundary_reached"] == 'swatch("cloth")'
    assert record["split"]["masks_written"] == 20
    assert record["colour"]["status"] == "not-in-scope"
    assert record["repeat"]["result"] == "not-a-repeat"
    assert [s["sha256"] for s in record["sources"]] == [s.sha256 for s in setup.pins.sources]


def test_a_repeat_agrees_byte_for_byte(setup: Setup) -> None:
    first, _ = setup.produce()
    earlier = setup.work / "masks-r1" / m.RECORD_NAME
    record, problems = setup.produce("masks-r1-repeat", expect=earlier)
    assert problems == []
    assert record["status"] == "reproduced"
    assert record["repeat"] == {
        "of_record": str(earlier),
        "of_record_sha256": sha256_file(earlier),
        "result": "byte-identical",
        "problems": [],
    }
    for name in m.MASKS:
        a = (setup.work / "masks-r1" / f"{name}.png").read_bytes()
        assert (setup.work / "masks-r1-repeat" / f"{name}.png").read_bytes() == a
    assert record["outputs"] == first["outputs"]


def test_a_repeat_reports_a_difference(setup: Setup) -> None:
    setup.produce()
    earlier = setup.work / "masks-r1" / m.RECORD_NAME
    record = read_record(earlier)
    record["outputs"][3]["sha256"] = "0" * 64
    tampered = setup.work / "earlier.json"
    write_json(tampered, record)
    repeat, problems = setup.produce("masks-r1-repeat", expect=tampered)
    assert problems and problems[0].startswith("outputs is")
    assert repeat["status"] == "not-reproduced"
    assert repeat["repeat"]["result"] == "differs"


def test_other_inputs_give_other_masks(setup: Setup, tmp_path: Path) -> None:
    first, _ = setup.produce()
    other = Setup(setup.assets, setup.pins, build_world(tmp_path / "other", 0.5), setup.work)
    second, _ = other.produce("masks-r2")
    assert first["outputs"][1]["sha256"] != second["outputs"][1]["sha256"]
    assert m.compare_records(second, first)


def test_the_sources_are_the_pinned_blobs_never_the_checkout(setup: Setup) -> None:
    for source in setup.pins.sources:
        (setup.assets / source.path).write_text('raise SystemExit("live file")\n')
    record, problems = setup.produce()
    assert problems == [] and len(record["outputs"]) == 20


@pytest.mark.parametrize(
    "change",
    [
        lambda s: m.Source(s.name, s.path, s.blob, "0" * 64, s.size_bytes, s.checkout_sha256),
        lambda s: m.Source(s.name, s.path, "0" * 40, s.sha256, s.size_bytes, s.checkout_sha256),
        lambda s: m.Source(s.name, s.path + ".old", s.blob, s.sha256, s.size_bytes),
    ],
)
def test_a_source_off_its_pin_is_refused(
    setup: Setup, change: Callable[[m.Source], m.Source]
) -> None:
    sources = tuple(change(s) if s.name == "waist_masks" else s for s in setup.pins.sources)
    pins = m.Pins(setup.pins.snapshot, sources, setup.pins.runtime, RES)
    with pytest.raises(MasksError):
        setup.plan(pins=pins)


def test_the_checkout_form_is_checked(setup: Setup) -> None:
    sources = tuple(
        m.Source(s.name, s.path, s.blob, s.sha256, s.size_bytes, "0" * 64)
        if s.checkout_sha256
        else s
        for s in setup.pins.sources
    )
    with pytest.raises(MasksError, match="CRLF"):
        setup.plan(pins=m.Pins(setup.pins.snapshot, sources, setup.pins.runtime, RES))


def test_the_real_pins() -> None:
    """The three source pins the round names, and the runtime and image pins."""
    by_name = {s.name: s for s in m.SOURCES}
    assert by_name["waist_masks"].sha256.startswith("959eca0bc3e2")
    assert by_name["waist_gen"].checkout_sha256 == (
        "15cf7cb9831df33ad645b5bf9b26a2cdc49d9c104f93ecf12c26eae6cb37b746"
    )
    assert by_name["garment_material_masks"].sha256.startswith("dfed970b93a3")
    assert m.SNAPSHOT == sash_current.SNAPSHOT
    assert [s.name for s in m.SOURCES][-1] == m.DONOR
    assert set(m.RUNTIME) == {"python", "numpy", "scipy", "pillow", "pillow_zlib"}
    assert m.RESOLUTION == 2048


def test_the_roles_agree_with_the_consumer() -> None:
    assert set(m.STACK_MASKS) == set(sash_current.BITMAPS) - {sash_current.COLOUR}
    assert len(m.MASKS) == len(set(m.MASKS)) == 20
    assert set(m.MASKS) == set(m.STACK_MASKS) | m.AUXILIARY
    assert m.MASK_FORM == (16, 0)  # the stack's 16-bit grey masks


def test_the_split_on_the_stand_in() -> None:
    report = m.split_report(masks_code().encode())
    assert report["masks_written"] == 20 and report["colour_statements"] == 4


LOOP = "    for name, v in ("
SPLIT_BREAKS = {
    "a swatch read before the masks": lambda c: c.replace(LOOP, '    _ = swatch("cloth")\n' + LOOP),
    "a sample in the mask part": lambda c: c.replace(LOOP, "    _ = sample\n" + LOOP),
    "Field reads a swatch": lambda c: c.replace(
        "        self.out = {}", '        self.out = {}\n        self.s = swatch("hem")'
    ),
    "the top level reads a swatch": lambda c: c + '\n_FIRST = swatch("cloth")\n',
    "the colour part writes a mask": lambda c: c.replace(
        "    uu, vv = cyl_uv(F)", '    uu, vv = cyl_uv(F)\n    F.save_mask(out, "M_x", uu)'
    ),
    "the hem swatch is read first": lambda c: c.replace(
        'sample(swatch("cloth"), uu, vv)', 'sample(swatch("hem"), uu, vv)'
    ),
    "no colour part": lambda c: c[: c.index("    uu, vv = cyl_uv(F)")],
}


@pytest.mark.parametrize("name", sorted(SPLIT_BREAKS))
def test_a_broken_split_is_refused(name: str) -> None:
    with pytest.raises(MasksError):
        m.split_report(SPLIT_BREAKS[name](masks_code()).encode())


@pytest.mark.parametrize("names", [m.MASKS[:-1], (*m.MASKS[1:], m.MASKS[0]), (*m.MASKS, "M_x")])
def test_other_mask_names_are_refused(names: tuple[str, ...]) -> None:
    with pytest.raises(MasksError, match="mask loop names"):
        m.split_report(masks_code(names).encode())


def test_an_unpinned_runtime_is_refused(setup: Setup) -> None:
    with pytest.raises(MasksError, match="numpy is 'other'"):
        setup.plan(runtime=lambda: {**RUNTIME, "numpy": "other"})
    assert not setup.work.exists()


INPUT_BREAKS: dict[str, Callable[[World], object]] = {
    "the AO cites another extraction": lambda w: w.edit(
        w.ao, lambda r: r["extraction"].update(record_sha256="0" * 64)
    ),
    "the centre cites another extraction": lambda w: w.edit(
        w.centre, lambda r: r["extraction"].update(record_sha256="0" * 64)
    ),
    "the AO baked another low": lambda w: w.edit(
        w.ao, lambda r: r["ao"]["low"]["digests"].update(co="0" * 64)
    ),
    "an authored centre": lambda w: w.edit(w.centre, lambda r: r.update(status="authored")),
    "another centre value": lambda w: w.edit(w.centre, lambda r: r.update(centre=[0.0, 0.0])),
    "ao.npy changed": lambda w: (w.ao.parent / side.AO_NAME).write_bytes(
        host.npy_bytes(np.zeros((RES, RES), np.float16))
    ),
    "a low.npz member is not its loose array": lambda w: w.edit(
        w.extraction, lambda r: r["outputs"]["low.co.npy"].update(sha256="0" * 64)
    ),
    "the Normal's digest": lambda w: w.edit(
        w.extraction, lambda r: r["normal"].update(digest="0" * 64)
    ),
    "the AO record is another kind": lambda w: w.edit(w.ao, lambda r: r.update(kind="centre")),
}


@pytest.mark.parametrize("name", sorted(INPUT_BREAKS))
def test_a_broken_input_is_refused_before_anything_is_written(setup: Setup, name: str) -> None:
    INPUT_BREAKS[name](setup.world)
    with pytest.raises(MasksError):
        setup.plan()
    assert not setup.work.exists()


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c.replace("return a[self.idx[0], self.idx[1]]", "return a"),
        lambda c: c.replace("self.tex(v)[::-1]", "self.tex(v)"),
    ],
    ids=["unpadded", "not flipped"],
)
def test_padding_and_orientation_are_checked_on_the_bytes(
    tmp_path: Path, change: Callable[[str], str]
) -> None:
    pins = donor_repo(tmp_path / "assets", change(masks_code()))
    setup = Setup(tmp_path / "assets", pins, build_world(tmp_path / "i"), tmp_path / "w")
    with pytest.raises(MasksError, match="nearest island texel"):
        setup.produce()
    assert not (tmp_path / "w" / "masks-r1" / m.RECORD_NAME).exists()


def fake_donor(sash: Callable[..., None]) -> types.ModuleType:
    class Field:
        def __init__(self, work: Path, res: int, construction: dict[str, Any]) -> None:
            self.out: dict[str, float] = {}

        def save_rgb(self, *args: Any) -> None:
            raise AssertionError("replaced by the producer")

    module = types.ModuleType("waist_masks")
    module.Field = Field  # type: ignore[attr-defined]
    module.sash = sash  # type: ignore[attr-defined]
    return module


@pytest.mark.parametrize(
    ("sash", "message"),
    [
        (lambda f, c, out: None, "no colour boundary"),
        (lambda f, c, out: f.save_rgb(out, "T_sash", None), "reached save_rgb"),
    ],
)
def test_the_colour_boundary_must_stop_sash(
    tmp_path: Path, sash: Callable[..., None], message: str
) -> None:
    npz = host.npz_bytes([("centre", host.npy_bytes(np.asarray(CENTRE, np.float64)))])
    (tmp_path / host.CENTRE_NPZ).write_bytes(npz)
    with pytest.raises(MasksError, match=message):
        m.run_donor(fake_donor(sash), tmp_path, RES)


def test_the_boundary_stops_at_the_first_swatch_read(tmp_path: Path) -> None:
    npz = host.npz_bytes([("centre", host.npy_bytes(np.asarray(CENTRE, np.float64)))])
    (tmp_path / host.CENTRE_NPZ).write_bytes(npz)
    reached: list[str] = []

    def sash(f: Any, c: Any, out: Path) -> None:
        reached.append("masks")
        module.swatch("cloth")
        reached.append("colour")

    module = fake_donor(sash)
    _, swatch = m.run_donor(module, tmp_path, RES)
    assert (swatch, reached) == ("cloth", ["masks"])


def test_run_directories_are_private_and_fresh(setup: Setup) -> None:
    with pytest.raises(RecorderError):
        m.plan(
            REPO_ROOT / "tmp" / "scratch" / "masks",
            setup.assets,
            setup.world.extraction,
            setup.world.ao,
            setup.world.centre,
            pins=setup.pins,
            runtime=lambda: dict(RUNTIME),
            verify_extraction=read_record,
        )
    (setup.work / "masks-r1").mkdir(parents=True)
    with pytest.raises(MasksError, match="already exists"):
        setup.plan()


def test_the_plan_writes_nothing(setup: Setup) -> None:
    plan = setup.plan()
    document = plan.as_json(setup.pins)
    assert document["split"]["masks_written"] == 20
    assert set(document["arrays"]) == set(m.INPUT_FILES.values())
    assert not setup.work.exists()


PEEK = '\n\ndef _peek():\n    return SW["cloth"].read_bytes()\n'


@pytest.mark.parametrize(
    "call",
    ["    _ = _peek()\n", "    try:\n        _peek()\n    except BaseException:\n        pass\n"],
    ids=["raised", "swallowed"],
)
def test_the_donor_may_open_nothing_under_assets3d(tmp_path: Path, call: str) -> None:
    """A helper the static proof does not see reads a swatch: the runtime guard refuses it."""
    code = masks_code().replace("\n\nclass Field:", PEEK + "\n\nclass Field:")
    code = code.replace(LOOP, call + LOOP)
    pins = donor_repo(tmp_path / "assets", code)
    swatch = tmp_path / "assets" / "Swatches" / "cloth.png"
    swatch.parent.mkdir()
    swatch.write_bytes(b"a swatch that exists")
    setup = Setup(tmp_path / "assets", pins, build_world(tmp_path / "i"), tmp_path / "w")
    with pytest.raises(MasksError, match="opened"):
        setup.produce()
    assert not (tmp_path / "w" / "masks-r1" / m.RECORD_NAME).exists()
    with m.no_reads_under(tmp_path / "elsewhere"):
        assert swatch.read_bytes()  # the guard covers only its root, only inside its block


def test_low_npz_must_hold_exactly_its_members(setup: Setup) -> None:
    extract = setup.world.extraction.parent
    members = [(n, (extract / host.LOW_FILES[n]).read_bytes()) for n in side.LOW_ARRAYS]
    (extract / host.LOW_NPZ).write_bytes(host.npz_bytes([*members, ("co", members[0][1])]))
    setup.world.edit(
        setup.world.extraction,
        lambda r: r["outputs"][host.LOW_NPZ].update(sha256=sha256_file(extract / host.LOW_NPZ)),
    )
    with pytest.raises(MasksError, match="holds"):
        setup.plan()


def test_a_non_finite_centre_is_refused(setup: Setup) -> None:
    setup.world.edit(setup.world.centre, lambda r: r.update(centre=[float("inf"), 0.0]))
    with pytest.raises(MasksError, match="non-JSON constant"):
        setup.plan()


def test_an_extraction_changed_while_checked_is_refused(setup: Setup) -> None:
    def verify(path: Path) -> dict[str, Any]:
        record = read_record(path)
        setup.world.edit(path, lambda r: r.update(label="changed"))
        return record

    with pytest.raises(MasksError, match="changed while"):
        setup.plan(verify_extraction=verify)


def test_a_failed_repeat_is_no_baseline(setup: Setup) -> None:
    setup.produce()
    earlier = setup.work / "masks-r1" / m.RECORD_NAME
    record = read_record(earlier)
    record["status"] = "not-reproduced"
    failed = setup.work / "failed.json"
    write_json(failed, record)
    with pytest.raises(MasksError, match="not a baseline"):
        setup.plan("masks-r1-repeat", expect=failed)
