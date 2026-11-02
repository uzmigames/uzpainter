"""The Sash v5 colour producer on stand-in donors, authored receipts and synthetic swatches.

The donor is an authored stand-in with the real `waist_masks.py`'s shape and its real Pillow
`save_mask`, `save_rgb`, `swatch`, `sample` and colour part, committed with a stand-in `v5.json`
to a throwaway git repository. Front T's masks producer runs on it first (r1, then the repeat),
so the masks record the colour producer compares against is a real one. The swatches are
synthetic noise authored in pytest's `tmp_path`, with authored provenance records. Nothing here
reads Assets3D, a real swatch or a real intermediate, or claims anything about the real T_sash.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.parity.tier1.test_sash_masks import (
    RES,
    RUNTIME,
    World,
    build_world,
    donor_repo,
    git,
    read_record,
    write_json,
)
from tools.parity.feasibility import png
from tools.parity.recorder import sash_current
from tools.parity.recorder.job import sha256_bytes, sha256_file
from tools.parity.recorder.output import WORK_ENV
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier1 import sash_colour as c
from tools.parity.tier1 import sash_intermediates as host
from tools.parity.tier1 import sash_masks as m
from tools.parity.tier1.sash_colour import ColourError

SIDE = 64  # the synthetic swatches' side (any intact PNG of its declared shape is accepted)
REFERENCES = {"cloth": "ref-sash-cloth.png", "hem": "ref-hem-tabs.png"}  # synthetic stand-ins
TEMPLATE = '''"""Stand-in waist_masks: the real import shape, Pillow writes and colour part."""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "AGENTS.md").exists())
sys.path.insert(0, str(ROOT / "Pipeline/painting"))
sys.path.insert(0, str(HERE))
import garment_material_masks as GM  # noqa: E402
import waist_gen as G  # noqa: E402

FOLDER = ROOT / "Creatures/Undead/Skeletal Mage/Models3D/25-Faixa-Cintura/Textures/Swatches"
SW = {"leather": ROOT / "_tmp/astra/paint-swatches/23/leather-BaseColor-v1.png",
      "cloth": FOLDER / "sash-cloth-BaseColor-v1.png",
      "hem": FOLDER / "hem-leather-BaseColor-v1.png"}
TILE = 0.15
GAIN = {"leather": (0.85, 0.70, 0.52), "cloth": (0.70, 0.66, 0.62), "hem": (0.61, 0.58, 0.63)}


def sample(img, u, v):
    h, w, _ = img.shape
    x = np.mod(u, 1.0) * w - 0.5; y = np.mod(-v, 1.0) * h - 0.5
    x0 = np.floor(x).astype(int); y0 = np.floor(y).astype(int)
    fx = (x - x0)[:, None]; fy = (y - y0)[:, None]
    g = lambda yy, xx: img[np.mod(yy, h), np.mod(xx, w)]
    return (g(y0, x0) * (1 - fx) * (1 - fy) + g(y0, x0 + 1) * fx * (1 - fy)
            + g(y0 + 1, x0) * (1 - fx) * fy + g(y0 + 1, x0 + 1) * fx * fy)


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
        self.th = np.linspace(0.0, 6.0, n)
        self.z = self.ao * 0.1
        self.idx = GM.nearest(self.valid)
        self.out = {}

    def tex(self, v, ch=1):
        a = np.zeros((self.res, self.res) if ch == 1 else (self.res, self.res, ch), np.float32)
        a[self.valid] = v
        return a[self.idx[0], self.idx[1]]

    def save_mask(self, out, name, v):
        v = np.clip(np.nan_to_num(v), 0, 1)
        q = (self.tex(v)[::-1] * 65535 + 0.5).astype(np.uint16)
        Image.fromarray(q).save(out / f"{name}.png")
        self.out[name] = round(float(v.mean()), 5)

    def save_rgb(self, out, name, rgb):
        q = (np.clip(self.tex(rgb, 3)[::-1], 0, 1) * 255 + 0.5).astype(np.uint8)
        Image.fromarray(q).save(out / f"{name}.png")
        self.out[name] = [round(float(x), 4) for x in np.median(rgb, 0)]


def swatch(name):
    s = np.asarray(Image.open(SW[name]).convert("RGB"), np.float64) / 255.0
    lin = np.where(s <= 0.04045, s / 12.92, ((s + 0.055) / 1.055) ** 2.4)
    lin = lin * np.array(GAIN[name]) ** 2.2
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)


def cyl_uv(F, phase=0.0):
    return F.th * 0.14 / TILE + phase, F.z / TILE


def sash(F, C, out):
    P = F.P
    cloth = P < 0.5 * P.max()
    hem = ~cloth
    level = P / P.max() * G.BELT_H / G.BELT_H + F.ridge * F.r
    for name, v in (PAIRS):
        F.save_mask(out, name, v)
    uu, vv = cyl_uv(F)
    col = sample(swatch("cloth"), uu, vv)
    col[hem] = sample(swatch("hem"), uu[hem] + 0.37, vv[hem])
    F.save_rgb(out, "T_sash", col)
'''
CLOTH_READ = 'sample(swatch("cloth"), uu, vv)'
HEM_READ = 'sample(swatch("hem"), uu[hem] + 0.37, vv[hem])'
RGB_WRITE = 'F.save_rgb(out, "T_sash", col)'


def colour_code() -> str:
    pairs = [
        f'("{name}", cloth.astype(float))'
        if name == "M_cloth"
        else f'("{name}", (level * {k + 1} / 20 + 0.5 * F.ao) % 1.0)'
        for k, name in enumerate(m.MASKS)
    ]
    return TEMPLATE.replace("(PAIRS)", "(" + ", ".join(pairs) + ",)")


def noise(seed: int, side: int = SIDE, channels: int = 3) -> np.ndarray[Any, Any]:
    return np.random.default_rng(seed).integers(0, 256, size=(side, side, channels))


def image_entry(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "sha256": sha256_bytes(data),
        "size_bytes": len(data),
        "width": int.from_bytes(data[16:20], "big"),
        "height": int.from_bytes(data[20:24], "big"),
        "bit_depth": data[24],
        "colour_type": data[25],
    }


def write_swatch(directory: Path, name: str, samples: np.ndarray[Any, Any], depth: int = 8) -> Path:
    """A generated swatch's authored provenance record, its synthetic image, prompt and one
    synthetic visual reference."""
    directory.mkdir(parents=True)
    image = directory / c.SWATCH_FILES[name]
    png.write(image, samples, depth)
    prompt = directory / "prompt.txt"
    prompt.write_text(f"synthetic {name} noise for pytest; not a real swatch\n", encoding="utf-8")
    reference = directory / REFERENCES[name]
    png.write(reference, noise(50 + len(name)), 8)
    record = directory / c.SWATCH_RECORD_NAME
    write_json(
        record,
        {
            "schema": c.SWATCH_SCHEMA,
            "kind": "swatch",
            "swatch": name,
            "file": image.name,
            "image": image_entry(image),
            "source": {
                "type": "generated",
                "generator": "numpy default_rng (authored in pytest)",
                "model": "uniform integer noise",
                "route": "tests/parity/tier1/test_sash_colour.py write_swatch, in tmp_path",
                "prompt_file": prompt.name,
                "prompt_sha256": sha256_file(prompt),
                "references": [
                    {
                        "role": "visual-reference",
                        "file": reference.name,
                        "sha256": sha256_file(reference),
                        "size_bytes": reference.stat().st_size,
                    }
                ],
                "authorization_declaration": "synthetic pytest swatch; never a real one",
            },
            "classification": "current-round substitute",
        },
    )
    return record


def edit(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    record = read_record(path)
    change(record)
    write_json(path, record)


@dataclass
class Chain:
    """A stand-in Assets3D, front P's world, front T's two masks runs and two swatches."""

    root: Path
    assets: Path
    pins: c.Pins
    world: World
    masks_record: Path
    swatches: dict[str, Path]
    originals: dict[str, Path] = field(default_factory=dict)

    @property
    def work(self) -> Path:
        return self.root / "w"

    def plan(self, run: str = "colour-r1", **kwargs: Any) -> c.Plan:
        return c.plan(
            self.work / run,
            self.assets,
            self.world.extraction,
            self.world.ao,
            self.world.centre,
            kwargs.pop("masks_record", self.masks_record),
            kwargs.pop("swatches", self.swatches),
            pins=kwargs.pop("pins", self.pins),
            runtime=lambda: dict(RUNTIME),
            verify_extraction=read_record,
            **kwargs,
        )

    def produce(self, run: str = "colour-r1", **kwargs: Any) -> tuple[dict[str, Any], list[str]]:
        return c.produce(self.plan(run, **kwargs), self.assets, self.pins)


def build_chain(root: Path, code: str | None = None) -> Chain:
    assets = root / "assets"
    stand_in = donor_repo(assets, code if code is not None else colour_code())
    originals = {}
    for k, name in enumerate(c.SWATCHES):
        originals[name] = root / "originals" / c.SWATCH_FILES[name]
        png.write(originals[name], noise(100 + k), 8)
    manifest = assets / c.MANIFEST.path
    manifest.parent.mkdir(parents=True)
    files = {
        f"amostra-{name}": {
            "path": c.SWATCH_PATHS[name],
            "sha256": {"algorithm": "sha256", "value": sha256_file(originals[name])},
        }
        for name in c.SWATCHES
    }
    manifest.write_bytes(json.dumps({"files": files}, indent=2).encode() + b"\n")
    git(assets, "add", "-A")
    git(assets, "commit", "-q", "-m", "stand-in v5.json")
    data = manifest.read_bytes()
    pins = c.Pins(
        donor=m.Pins(git(assets, "rev-parse", "HEAD"), stand_in.sources, dict(RUNTIME), RES),
        manifest=m.Source(
            "v5.json", c.MANIFEST.path, m.git_blob_id(data), sha256_bytes(data), len(data)
        ),
        originals={name: sha256_file(path) for name, path in originals.items()},
    )
    world = build_world(root / "intermediates")
    work = root / "w"

    def masks_run(run: str, expect: Path | None = None) -> Path:
        plan = m.plan(
            work / run,
            assets,
            world.extraction,
            world.ao,
            world.centre,
            expect=expect,
            pins=pins.donor,
            runtime=lambda: dict(RUNTIME),
            verify_extraction=read_record,
        )
        _, problems = m.produce(plan, assets, pins.donor)
        assert problems == []
        return work / run / m.RECORD_NAME

    repeat = masks_run("masks-r1-repeat", masks_run("masks-r1"))
    swatches = {
        name: write_swatch(root / "swatches" / name, name, noise(7 + k))
        for k, name in enumerate(c.SWATCHES)
    }
    return Chain(root, assets, pins, world, repeat, swatches, originals)


@pytest.fixture
def chain(tmp_path: Path) -> Chain:
    return build_chain(tmp_path)


def test_one_t_sash_and_a_typed_receipt(chain: Chain) -> None:
    record, problems = chain.produce()
    assert problems == []
    run_dir = chain.work / "colour-r1"
    staged = {*m.INPUT_FILES.values(), *c.SWATCH_FILES.values()}
    assert {p.name for p in run_dir.iterdir()} == staged | {"T_sash.png", c.RECORD_NAME}
    assert read_record(run_dir / c.RECORD_NAME) == record
    assert (record["schema"], record["kind"], record["status"]) == (
        c.RECORD_SCHEMA,
        "colour",
        "produced",
    )
    [output] = record["outputs"]
    data = (run_dir / "T_sash.png").read_bytes()
    assert output["sha256"] == sha256_bytes(data) and output["size_bytes"] == len(data)
    assert (output["name"], output["shape"], output["depth"], output["colour_type"]) == (
        "T_sash",
        [RES, RES],
        8,
        2,
    )
    assert (data[:8], data[12:16], data[24], data[25]) == (png.SIGNATURE, b"IHDR", 8, 2)
    receipts = record["receipts"]
    assert set(receipts) == {"extraction", "ao", "centre", "masks", "swatch-cloth", "swatch-hem"}
    assert receipts["masks"]["sha256"] == sha256_file(chain.masks_record)
    assert receipts["masks"]["of_record_sha256"] == sha256_file(
        chain.work / "masks-r1" / m.RECORD_NAME
    )
    for name, path in chain.swatches.items():
        assert receipts[f"swatch-{name}"]["sha256"] == sha256_file(path)
        assert record["swatches"][name]["sha256"] == sha256_file(run_dir / c.SWATCH_FILES[name])
        assert record["swatches"][name]["classification"] == "current-round substitute"
    assert record["inputs"]["before"] == record["inputs"]["after"]
    assert set(record["inputs"]["before"]["staged"]) == staged
    assert record["masks"]["compared"] == list(m.MASKS)
    assert record["parameters"]["swatch_reads"] == ["cloth", "hem"]
    assert [s["sha256"] for s in record["sources"]] == [s.sha256 for s in chain.pins.donor.sources]
    assert record["manifest"]["lists"] == dict(chain.pins.originals)
    assert record["substitute"]["classification"] == "current-round substitute"
    assert record["repeat"]["result"] == "not-a-repeat"


def test_the_remaps_change_nothing_the_donor_writes(chain: Chain, tmp_path: Path) -> None:
    """The unmodified donor, with the swatches at its own paths, writes the same bytes."""
    chain.produce()
    run_dir = chain.work / "colour-r1"
    for name, path in chain.swatches.items():
        target = chain.assets / c.SWATCH_PATHS[name]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path.parent / c.SWATCH_FILES[name], target)
    donor = m.load_donor(
        m.read_sources(chain.assets, chain.pins.donor), chain.assets, chain.pins.donor
    )
    with np.load(run_dir / host.CENTRE_NPZ) as archive:
        construction = dict(archive)
    direct = tmp_path / "direct"
    direct.mkdir()
    donor.sash(donor.Field(run_dir, RES, construction), construction, direct)
    assert (direct / "T_sash.png").read_bytes() == (run_dir / "T_sash.png").read_bytes()
    masks = {o["name"]: o["sha256"] for o in read_record(chain.masks_record)["outputs"]}
    assert {n: sha256_file(direct / f"{n}.png") for n in m.MASKS} == masks


def test_a_repeat_agrees_byte_for_byte(chain: Chain) -> None:
    first, _ = chain.produce()
    earlier = chain.work / "colour-r1" / c.RECORD_NAME
    record, problems = chain.produce("colour-r1-repeat", expect=earlier)
    assert problems == [] and record["status"] == "reproduced"
    assert record["repeat"] == {
        "of_record": str(earlier),
        "of_record_sha256": sha256_file(earlier),
        "result": "byte-identical",
        "problems": [],
    }
    assert record["outputs"] == first["outputs"]


def test_a_repeat_reports_a_difference(chain: Chain) -> None:
    chain.produce()
    tampered = chain.work / "earlier.json"
    shutil.copyfile(chain.work / "colour-r1" / c.RECORD_NAME, tampered)
    edit(tampered, lambda r: r["outputs"][0].update(sha256="1" * 64))
    record, problems = chain.produce("colour-r1-repeat", expect=tampered)
    assert problems and problems[0].startswith("outputs is")
    assert (record["status"], record["repeat"]["result"]) == ("not-reproduced", "differs")


def test_a_failed_repeat_is_no_baseline(chain: Chain) -> None:
    chain.produce()
    failed = chain.work / "failed.json"
    shutil.copyfile(chain.work / "colour-r1" / c.RECORD_NAME, failed)
    edit(failed, lambda r: r.update(status="not-reproduced"))
    with pytest.raises(ColourError, match="not a baseline"):
        chain.plan("colour-r1-repeat", expect=failed)


def _copy_mask(chain: Chain, source: str, target: str) -> None:
    folder = chain.masks_record.parent
    shutil.copyfile(folder / f"{source}.png", folder / f"{target}.png")
    entry = image_entry(folder / f"{target}.png")

    def change(record: dict[str, Any]) -> None:
        output = next(o for o in record["outputs"] if o["name"] == target)
        output.update(sha256=entry["sha256"], size_bytes=entry["size_bytes"])

    edit(chain.masks_record, change)


MASK_DIFFERENCES: dict[str, Callable[[Chain], None]] = {
    "bytes": lambda ch: _copy_mask(ch, "M_hem", "M_weave"),
    "mean": lambda ch: edit(ch.masks_record, lambda r: r["outputs"][3].update(coverage_mean=0.5)),
}


@pytest.mark.parametrize("name", sorted(MASK_DIFFERENCES))
def test_a_mask_unlike_the_masks_record_refuses(chain: Chain, name: str) -> None:
    MASK_DIFFERENCES[name](chain)
    with pytest.raises(ColourError, match="front T's record holds"):
        chain.produce()
    run_dir = chain.work / "colour-r1"
    assert not (run_dir / c.RECORD_NAME).exists() and not (run_dir / "T_sash.png").exists()
    assert not [p for p in run_dir.iterdir() if p.name.startswith("M_")]


MASKS_RECORD_BREAKS: dict[str, Callable[[Chain], object]] = {
    "the first run, not the repeat": lambda ch: setattr(
        ch, "masks_record", ch.work / "masks-r1" / m.RECORD_NAME
    ),
    "another extraction receipt": lambda ch: edit(
        ch.masks_record, lambda r: r["receipts"]["extraction"].update(sha256="2" * 64)
    ),
    "another AO array": lambda ch: edit(
        ch.masks_record, lambda r: r["arrays"]["ao.npy"].update(sha256="2" * 64)
    ),
    "another source": lambda ch: edit(
        ch.masks_record, lambda r: r["sources"][2].update(sha256="2" * 64)
    ),
    "a mask file changed": lambda ch: (ch.masks_record.parent / "M_dust.png").write_bytes(b"x"),
    "a mask file missing": lambda ch: (ch.masks_record.parent / "M_dust.png").unlink(),
    "a mask missing": lambda ch: edit(ch.masks_record, lambda r: r["outputs"].pop()),
    "a differing repeat": lambda ch: edit(
        ch.masks_record, lambda r: r["repeat"].update(result="differs")
    ),
}


@pytest.mark.parametrize("name", sorted(MASKS_RECORD_BREAKS))
def test_a_masks_record_that_does_not_vouch_is_refused(chain: Chain, name: str) -> None:
    MASKS_RECORD_BREAKS[name](chain)
    with pytest.raises(ColourError):
        chain.plan()
    assert not (chain.work / "colour-r1").exists()


def _source(**change: Any) -> Callable[[dict[str, Any]], None]:
    return lambda r: r["source"].update(change)


def _reference(**change: Any) -> Callable[[dict[str, Any]], None]:
    return lambda r: r["source"]["references"][0].update(change)


def _as_original(name: str, v5_json_sha256: str) -> Callable[[dict[str, Any]], None]:
    def change(record: dict[str, Any]) -> None:
        record["classification"] = "original"
        record["source"] = {
            "type": "original",
            "assets3d_path": c.SWATCH_PATHS[name],
            "v5_json_sha256": v5_json_sha256,
        }

    return change


def _rewrite(chain: Chain, samples: np.ndarray[Any, Any], depth: int = 8) -> None:
    folder = chain.swatches["cloth"].parent
    png.write(folder / c.SWATCH_FILES["cloth"], samples, depth)
    edit(chain.swatches["cloth"], lambda r: r.update(image=image_entry(folder / r["file"])))


def _same_image(chain: Chain) -> None:
    cloth = chain.swatches["cloth"].parent / c.SWATCH_FILES["cloth"]
    hem = chain.swatches["hem"].parent / c.SWATCH_FILES["hem"]
    shutil.copyfile(cloth, hem)
    edit(chain.swatches["hem"], lambda r: r.update(image=image_entry(hem)))


SWATCH_BREAKS: dict[str, Callable[[Chain], object]] = {
    "no record": lambda ch: ch.swatches["cloth"].unlink(),
    "no image": lambda ch: (ch.swatches["cloth"].parent / c.SWATCH_FILES["cloth"]).unlink(),
    "an empty image": lambda ch: (
        ch.swatches["cloth"].parent / c.SWATCH_FILES["cloth"]
    ).write_bytes(b""),
    "an image off its hash": lambda ch: edit(
        ch.swatches["cloth"], lambda r: r["image"].update(sha256="3" * 64)
    ),
    "another recorded size": lambda ch: edit(
        ch.swatches["cloth"], lambda r: r["image"].update(width=SIDE * 2)
    ),
    "a 16-bit image": lambda ch: _rewrite(ch, noise(1) * 257, 16),
    "a grey image": lambda ch: _rewrite(ch, noise(1, channels=1)),
    "the same image twice": _same_image,
    "an unknown key": lambda ch: edit(ch.swatches["cloth"], lambda r: r.update(note="x")),
    "no source": lambda ch: edit(ch.swatches["cloth"], lambda r: r.pop("source")),
    "a placeholder generator": lambda ch: edit(ch.swatches["cloth"], _source(generator="TODO")),
    "no authorization declaration": lambda ch: edit(
        ch.swatches["cloth"], _source(authorization_declaration="")
    ),
    "the old authorization key": lambda ch: edit(
        ch.swatches["cloth"],
        lambda r: r["source"].update(authorization=r["source"].pop("authorization_declaration")),
    ),
    "a placeholder route": lambda ch: edit(ch.swatches["cloth"], _source(route="tbd")),
    "no references key": lambda ch: edit(
        ch.swatches["cloth"], lambda r: r["source"].pop("references")
    ),
    "references not a list": lambda ch: edit(ch.swatches["cloth"], _source(references={})),
    "a reference off its hash": lambda ch: edit(ch.swatches["cloth"], _reference(sha256="7" * 64)),
    "a reference off its size": lambda ch: edit(ch.swatches["cloth"], _reference(size_bytes=1)),
    "a reference missing": lambda ch: (ch.swatches["cloth"].parent / REFERENCES["cloth"]).unlink(),
    "a reference elsewhere": lambda ch: edit(
        ch.swatches["cloth"], _reference(file=f"../hem/{REFERENCES['hem']}")
    ),
    "the image as its own reference": lambda ch: edit(
        ch.swatches["cloth"],
        _reference(
            file=c.SWATCH_FILES["cloth"],
            sha256=sha256_file(ch.swatches["cloth"].parent / c.SWATCH_FILES["cloth"]),
            size_bytes=(ch.swatches["cloth"].parent / c.SWATCH_FILES["cloth"]).stat().st_size,
        ),
    ),
    "a reference with no role": lambda ch: edit(ch.swatches["cloth"], _reference(role="")),
    "a reference with an unknown key": lambda ch: edit(ch.swatches["cloth"], _reference(note="x")),
    "a prompt off its hash": lambda ch: edit(ch.swatches["cloth"], _source(prompt_sha256="4" * 64)),
    "a prompt elsewhere": lambda ch: edit(
        ch.swatches["cloth"], _source(prompt_file="../hem/prompt.txt")
    ),
    "a generated swatch called original": lambda ch: edit(
        ch.swatches["cloth"], lambda r: r.update(classification="original")
    ),
    "an unknown source type": lambda ch: edit(ch.swatches["cloth"], _source(type="found")),
    "the hem record as cloth": lambda ch: ch.swatches.update(cloth=ch.swatches["hem"]),
    "another file name": lambda ch: edit(ch.swatches["cloth"], lambda r: r.update(file="a.png")),
    "a missing swatch": lambda ch: ch.swatches.pop("hem"),
    "an original that is not v5.json's": lambda ch: edit(
        ch.swatches["cloth"], _as_original("cloth", ch.pins.manifest.sha256)
    ),
}


def _original(chain: Chain, name: str, v5_json_sha256: str) -> None:
    """The swatch record turned into an original's, with the original image next to it."""
    original = chain.originals[name]
    shutil.copyfile(original, chain.swatches[name].parent / c.SWATCH_FILES[name])
    change = _as_original(name, v5_json_sha256)

    def both(record: dict[str, Any]) -> None:
        change(record)
        record["image"] = image_entry(original)

    edit(chain.swatches[name], both)


@pytest.mark.parametrize("name", sorted(SWATCH_BREAKS))
def test_a_swatch_without_valid_provenance_is_refused(chain: Chain, name: str) -> None:
    SWATCH_BREAKS[name](chain)
    with pytest.raises((ColourError, OSError)):
        chain.plan()
    assert not (chain.work / "colour-r1").exists()


def test_an_original_names_the_manifest_and_matches_its_listing(chain: Chain) -> None:
    _original(chain, "hem", chain.pins.manifest.sha256)
    plan = chain.plan()
    assert plan.swatches["hem"].entry["classification"] == "original"
    assert plan.swatches["hem"].entry["source"]["v5_json_sha256"] == chain.pins.manifest.sha256
    assert plan.receipts()["swatch-hem"]["image_sha256"] == chain.pins.originals["hem"]


@pytest.mark.parametrize("cited", ["the image's hash", "another manifest"])
def test_an_original_citing_another_manifest_is_refused(chain: Chain, cited: str) -> None:
    other = chain.pins.originals["hem"] if cited == "the image's hash" else "8" * 64
    _original(chain, "hem", other)
    with pytest.raises(ColourError, match=r"pinned v5\.json's own SHA-256"):
        chain.plan()


def test_a_generated_swatch_may_declare_no_reference(chain: Chain) -> None:
    edit(chain.swatches["hem"], _source(references=[]))
    plan = chain.plan()
    assert plan.swatches["hem"].entry["source"]["references"] == []
    assert not [label for label in plan.verified() if label.startswith("reference-hem")]
    assert f"reference-cloth-{REFERENCES['cloth']}" in plan.verified()


def test_a_manifest_off_its_pins_is_refused(chain: Chain) -> None:
    pins = c.Pins(chain.pins.donor, chain.pins.manifest, {"cloth": "5" * 64, "hem": "6" * 64})
    with pytest.raises(ColourError, match="lists"):
        chain.plan(pins=pins)


DONOR_BREAKS = {
    "cloth read twice": lambda code: code.replace(HEM_READ, HEM_READ.replace('"hem"', '"cloth"')),
    "another colour name": lambda code: code.replace(RGB_WRITE, RGB_WRITE.replace("T_sash", "T_x")),
    "two colour writes": lambda code: code.replace(RGB_WRITE, RGB_WRITE + "\n    " + RGB_WRITE),
    "another swatch path": lambda code: code.replace(
        '"cloth": FOLDER / "sash-cloth', '"cloth": ROOT / "sash-cloth'
    ),
}


@pytest.mark.parametrize("name", sorted(DONOR_BREAKS))
def test_the_donor_may_read_and_write_only_its_colour(tmp_path: Path, name: str) -> None:
    chain = build_chain(tmp_path, DONOR_BREAKS[name](colour_code()))
    with pytest.raises(ColourError):
        chain.produce()
    assert not (chain.work / "colour-r1" / c.RECORD_NAME).exists()


MID_RUN_CHANGES: dict[str, Callable[[Chain], object]] = {
    "a receipt": lambda ch: edit(
        ch.swatches["cloth"], lambda r: r["source"].update(model="another model")
    ),
    "a prompt": lambda ch: (ch.swatches["hem"].parent / "prompt.txt").write_text("another"),
    "a deleted prompt": lambda ch: (ch.swatches["hem"].parent / "prompt.txt").unlink(),
    "a swatch image": lambda ch: _rewrite(ch, noise(2)),
    "a visual reference": lambda ch: png.write(
        ch.swatches["hem"].parent / REFERENCES["hem"], noise(3), 8
    ),
}


@pytest.mark.parametrize("name", sorted(MID_RUN_CHANGES))
def test_a_verified_file_changed_during_the_run_is_refused(
    chain: Chain, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    run_donor = c.run_donor

    def changing(*args: Any) -> Any:
        found = run_donor(*args)
        MID_RUN_CHANGES[name](chain)
        return found

    monkeypatch.setattr(c, "run_donor", changing)
    with pytest.raises(ColourError, match="changed while"):
        chain.produce()
    assert not (chain.work / "colour-r1" / c.RECORD_NAME).exists()


def test_run_directories_are_private_and_fresh(chain: Chain) -> None:
    with pytest.raises(RecorderError):
        c.plan(
            REPO_ROOT / "tmp" / "scratch" / "colour",
            chain.assets,
            chain.world.extraction,
            chain.world.ao,
            chain.world.centre,
            chain.masks_record,
            chain.swatches,
            pins=chain.pins,
            runtime=lambda: dict(RUNTIME),
            verify_extraction=read_record,
        )
    (chain.work / "colour-r1").mkdir(parents=True)
    with pytest.raises(ColourError, match="already exists"):
        chain.plan()


def test_the_plan_writes_nothing(chain: Chain) -> None:
    document = chain.plan().as_json(chain.pins)
    assert set(document["receipts"]) == {
        "extraction",
        "ao",
        "centre",
        "masks",
        "swatch-cloth",
        "swatch-hem",
    }
    assert set(document["swatches"]) == set(c.SWATCHES)
    assert not (chain.work / "colour-r1").exists()


def test_the_real_pins() -> None:
    """The colour's form and swatch files are the consumer's; the manifest is the snapshot's."""
    assert c.COLOUR == sash_current.COLOUR
    assert tuple(c.SWATCH_FILES[name] for name in c.SWATCHES) == sash_current.SWATCHES
    assert c.COLOUR_FORM == (8, sash_current.RGB)
    assert {sash_current.RGB, sash_current.RGBA} == c.SWATCH_COLOUR_TYPES
    assert c.PINS.donor == m.PINS and c.PINS.donor.resolution == 2048
    assert c.MANIFEST.sha256.startswith("c5566c38a6a1")
    assert c.ORIGINALS["cloth"].startswith("5ab8cdf3edef")
    assert c.ORIGINALS["hem"].startswith("546bba43d729")


def test_the_cli_refuses_without_swatches(tmp_path: Path) -> None:
    """With no provenance record at the default paths, the CLI refuses before writing."""
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.parity.tier1.sash_colour",
            "--assets-root",
            str(tmp_path),
            "--ao",
            str(tmp_path / "ao.json"),
            "--run",
            "colour-cli-check",
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        env={**os.environ, WORK_ENV: str(tmp_path / "w")},
        check=False,
    )
    assert run.returncode == 2 and b"sash_colour:" in run.stderr
    assert not (tmp_path / "w" / "colour-cli-check").exists()
