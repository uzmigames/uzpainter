"""The Sash v5 AO mesh map producer on synthetic AO arrays and an authored AO record.

The donor is a stand-in `sashchain.sh` holding the pinned conversion line, committed to a
throwaway git repository so the producer reads it as a raw blob the way it reads Assets3D. Front
P's AO record is authored with the fields its records hold. Nothing here reads Assets3D or a real
`ao.npy`, or claims anything about the real AO map.
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import types
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import pytest

from tools.parity.feasibility import png
from tools.parity.recorder import sash_current
from tools.parity.recorder.job import sha256_bytes, sha256_file
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier1 import sash_ao_map as a
from tools.parity.tier1 import sash_intermediates as host
from tools.parity.tier1 import sash_intermediates_blender as side
from tools.parity.tier1.sash_ao_map import AoMapError

RES = 8
RUNTIME = {"python": "stand-in", "numpy": "stand-in"}


def runtime() -> dict[str, str]:
    return dict(RUNTIME)


def git(root: Path, *args: str) -> str:
    command = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t"]
    command += ["-c", "core.autocrlf=false", *args]
    return subprocess.run(command, capture_output=True, check=True).stdout.decode().strip()


def donor_repo(root: Path, line: str = a.DONOR_LINE) -> a.Pins:
    """A stand-in `sashchain.sh` at its Assets3D path; its pins computed from its bytes."""
    data = f'#!/bin/sh\npython -c "\nimport numpy as np; from PIL import Image\n{line}\n'.encode()
    path = root / a.DONOR.path
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "stand-in donor")
    return a.Pins(
        snapshot=git(root, "rev-parse", "HEAD"),
        donor=a.Donor(a.DONOR.path, a.git_blob_id(data), sha256_bytes(data), len(data)),
        runtime=dict(RUNTIME),
        resolution=RES,
    )


def synthetic_ao() -> Any:
    """Every row distinct (so a flip shows) and the edges of the range, as float16."""
    ramp = np.linspace(0.0, 1.0, RES * RES, dtype=np.float32).reshape(RES, RES)
    ramp[0, 0], ramp[-1, -1], ramp[1, 1] = 0.0, 1.0, 0.5
    return ramp.astype(np.float16)


def npy(array: Any) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return buffer.getvalue()


def entry(path: Path) -> dict[str, Any]:
    return {"sha256": sha256_file(path), "size_bytes": path.stat().st_size}


@dataclass
class World:
    root: Path
    assets: Path
    pins: a.Pins
    ao_dir: Path
    record: Path

    @property
    def sha256(self) -> str:
        return sha256_file(self.record)

    def plan(self, run: str = "ao-map-r1", **kwargs: Any) -> a.Plan:
        return a.plan(
            self.root / run,
            self.assets,
            self.record,
            kwargs.pop("sha256", self.sha256),
            pins=self.pins,
            runtime=runtime,
            **kwargs,
        )


def author(
    ao_dir: Path,
    ao: Any,
    *,
    edit: Callable[[dict[str, Any]], None] = lambda _: None,
    expect_link: str | None = None,
) -> Path:
    """Front P's AO run as its record names it: the extraction it cites, `ao-expect.json`,
    `ao-report.json` and `ao.npy`."""
    ao_dir.mkdir(parents=True, exist_ok=True)
    extraction = ao_dir.parent / "intermediates-r1" / host.RECORD_NAME
    extraction.parent.mkdir(exist_ok=True)
    extraction.write_text('{"schema": "stand-in", "kind": "extract"}\n', encoding="utf-8")
    link = sha256_file(extraction)
    expect = {"low_digests": {}, "extraction_record_sha256": expect_link or link}
    (ao_dir / side.AO_EXPECT).write_text(json.dumps(expect), encoding="utf-8")
    (ao_dir / side.AO_REPORT).write_text('{"mode": "ao"}', encoding="utf-8")
    (ao_dir / side.AO_NAME).write_bytes(npy(ao))
    record: dict[str, Any] = {
        "schema": host.RECORD_SCHEMA,
        "kind": "ao",
        "extraction": {"record": str(extraction), "record_sha256": link},
        "ao": {"digest": side.array_digest(ao), "row_order": "bottom first"},
        "outputs": {
            name: entry(ao_dir / name) for name in (side.AO_NAME, side.AO_EXPECT, side.AO_REPORT)
        },
    }
    edit(record)
    path = ao_dir / host.RECORD_NAME
    path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return path


@pytest.fixture
def world(tmp_path: Path) -> World:
    pins = donor_repo(tmp_path / "assets")
    ao_dir = tmp_path / "work" / "ao-r1"
    record = author(ao_dir, synthetic_ao())
    return World(tmp_path / "work", tmp_path / "assets", pins, ao_dir, record)


def test_the_pins_name_the_current_round_s_consumer() -> None:
    assert a.RECORD_SCHEMA == sash_current.AO_MAP_SCHEMA
    assert PurePosixPath(sash_current.AO).name == a.OUTPUT_NAME
    assert a.RESOLUTION == 2048 and a.PNG_FORM == (16, 0)


def test_the_cli_requires_the_accepted_ao_record(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        a.main(["--assets-root", "x", "--ao-record-sha256", "0" * 64])
    assert "--ao" in capsys.readouterr().err


def test_quantize_is_the_donor_line_itself() -> None:
    """The pinned `sashchain.sh` line, executed on the same array, gives the same samples."""
    ao = synthetic_ao()
    saved: list[Any] = []
    image = types.SimpleNamespace(
        fromarray=lambda array: types.SimpleNamespace(save=lambda _: saved.append(array))
    )
    fake_np = types.SimpleNamespace(
        load=lambda _: ao, float32=np.float32, uint16=np.uint16, clip=np.clip
    )
    exec(a.DONOR_LINE.removesuffix('"'), {"np": fake_np, "Image": image})
    assert len(saved) == 1
    samples = a.quantize(ao)
    assert samples.dtype == np.uint16 and np.array_equal(samples, saved[0])
    assert samples[-1, 0] == 0 and samples[0, -1] == 65535  # the rows are flipped
    assert samples[-2, 1] == 32768  # 0.5 * 65535 + 0.5, truncated


def test_r1_and_repeat_are_byte_identical(world: World) -> None:
    record, problems = a.produce(world.plan(), world.pins)
    assert problems == [] and record["status"] == "produced"
    run = world.root / "ao-map-r1"
    assert {p.name for p in run.iterdir()} == {a.OUTPUT_NAME, a.RECORD_NAME}
    data = (run / a.OUTPUT_NAME).read_bytes()
    assert [kind for kind, _ in png.chunks(data)] == [b"IHDR", b"IDAT", b"IEND"]
    assert np.array_equal(png.decode(data)[:, :, 0], a.quantize(synthetic_ao()))
    output = record["outputs"][a.OUTPUT_NAME]
    assert output == {
        "sha256": sha256_bytes(data),
        "size_bytes": len(data),
        "shape": [RES, RES],
        "depth": 16,
        "colour_type": 0,
        "sample_range": [0, 65535],
    }
    assert record["inputs"] == {side.AO_NAME: {"sha256": sha256_file(world.ao_dir / side.AO_NAME)}}
    assert record["receipt"]["sha256"] == world.sha256
    assert record["substitute"]["classification"] == "current-round substitute"
    assert json.loads((run / a.RECORD_NAME).read_text(encoding="utf-8")) == record

    again, problems = a.produce(
        world.plan("ao-map-r1-repeat", expect=run / a.RECORD_NAME), world.pins
    )
    assert problems == [] and again["status"] == "reproduced"
    assert again["repeat"] == {
        "of_record": str(run / a.RECORD_NAME),
        "of_record_sha256": sha256_file(run / a.RECORD_NAME),
        "result": "byte-identical",
        "problems": [],
    }
    assert (world.root / "ao-map-r1-repeat" / a.OUTPUT_NAME).read_bytes() == data


def test_a_repeat_that_differs_says_so(world: World) -> None:
    record, _ = a.produce(world.plan(), world.pins)
    earlier = world.root / "ao-map-r1" / "earlier.json"  # next to the earlier PNG
    record["encoder"] = {**record["encoder"], "filter": "another"}
    earlier.write_text(json.dumps(record), encoding="utf-8")
    again, problems = a.produce(world.plan("r1-repeat", expect=earlier), world.pins)
    assert again["status"] == "not-reproduced" and again["repeat"]["result"] == "differs"
    assert again["repeat"]["of_record_sha256"] == sha256_file(earlier)
    assert len(problems) == 1 and problems[0].startswith("encoder ")


def test_a_repeat_checks_the_earlier_png_itself(world: World) -> None:
    a.produce(world.plan(), world.pins)
    earlier = world.root / "ao-map-r1"
    (earlier / a.OUTPUT_NAME).write_bytes(b"not the png")
    with pytest.raises(AoMapError, match="is not the 25-Faixa"):
        world.plan("r1-repeat", expect=earlier / a.RECORD_NAME)
    assert not (world.root / "r1-repeat").exists()


def test_a_failed_write_leaves_nothing(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    the_plan = world.plan()
    monkeypatch.setattr(a, "sha256_file", lambda _: "0" * 64)
    with pytest.raises(AoMapError, match="was not written as encoded"):
        a.produce(the_plan, world.pins)
    assert not (world.root / "ao-map-r1").exists()


def _set(path: tuple[str, ...], value: Any) -> Callable[[dict[str, Any]], None]:
    def edit(record: dict[str, Any]) -> None:
        for key in path[:-1]:
            record = record[key]
        record[path[-1]] = value

    return edit


@pytest.mark.parametrize(
    ("ao", "edit", "message"),
    [
        (None, _set(("kind",), "extract"), "is not a"),
        (None, _set(("extraction", "record_sha256"), "0" * 64), "does not hash to"),
        (None, _set(("outputs", side.AO_NAME, "sha256"), "0" * 64), "is not the ao.npy"),
        (None, _set(("outputs", side.AO_REPORT, "size_bytes"), 1), "is not the ao-report"),
        (None, _set(("outputs", side.AO_EXPECT), None), "names no ao-expect"),
        (None, _set(("ao", "digest"), "0" * 64), "differs from its record's digest"),
        (np.full((RES, RES), np.nan, np.float16), None, "non-finite"),
        (np.full((RES, RES), np.inf, np.float16), None, "non-finite"),
        (np.full((RES, RES), 1.5, np.float16), None, "outside [0, 1]"),
        (np.full((RES, RES), -0.25, np.float16), None, "outside [0, 1]"),
        (np.zeros((RES, RES), np.float32), None, "pinned <f2"),
        (np.zeros((RES, RES + 1), np.float16), None, "pinned <f2"),
    ],
)
def test_inputs_refuse_and_write_nothing(
    world: World, ao: Any, edit: Callable[[dict[str, Any]], None] | None, message: str
) -> None:
    author(world.ao_dir, synthetic_ao() if ao is None else ao, edit=edit or (lambda _: None))
    with pytest.raises(AoMapError, match=re.escape(message)):
        world.plan()
    assert not (world.root / "ao-map-r1").exists()


def test_the_ao_record_must_be_the_accepted_one(world: World) -> None:
    with pytest.raises(AoMapError, match="the accepted"):
        world.plan(sha256="0" * 64)


def test_the_extraction_link_is_exact(world: World) -> None:
    author(world.ao_dir, synthetic_ao(), expect_link="1" * 64)
    with pytest.raises(AoMapError, match="names another extraction"):
        world.plan()
    author(world.ao_dir, synthetic_ao())
    sha256 = world.sha256
    extraction = world.root / "intermediates-r1" / host.RECORD_NAME
    extraction.write_text("{}", encoding="utf-8")
    with pytest.raises(AoMapError, match="does not hash to"):
        world.plan(sha256=sha256)
    author(world.ao_dir, synthetic_ao())
    (world.ao_dir / side.AO_NAME).write_bytes(npy(synthetic_ao() * np.float16(0.5)))
    with pytest.raises(AoMapError, match=r"is not the ao\.npy"):
        world.plan()


@pytest.mark.parametrize(
    ("data", "message"),
    [(b"", "is not a .npy array"), (None, "holds a NpzFile")],
)
def test_ao_npy_must_be_one_array(world: World, data: bytes | None, message: str) -> None:
    """Bytes that match their record but hold no array, or an archive, refuse cleanly."""
    buffer = io.BytesIO()
    np.savez(buffer, ao=synthetic_ao())
    payload = buffer.getvalue() if data is None else data

    def edit(record: dict[str, Any]) -> None:
        entry = {"sha256": sha256_bytes(payload), "size_bytes": len(payload)}
        record["outputs"][side.AO_NAME] = entry

    author(world.ao_dir, synthetic_ao(), edit=edit)
    (world.ao_dir / side.AO_NAME).write_bytes(payload)
    with pytest.raises(AoMapError, match=re.escape(message)):
        world.plan()


def test_the_donor_and_runtime_are_pinned(world: World, tmp_path: Path) -> None:
    other = donor_repo(tmp_path / "other", line="something else")
    with pytest.raises(AoMapError, match="conversion line"):
        a.plan(
            world.root / "r1",
            tmp_path / "other",
            world.record,
            world.sha256,
            pins=other,
            runtime=runtime,
        )
    wrong = a.Pins(
        snapshot=world.pins.snapshot,
        donor=a.Donor(a.DONOR.path, "0" * 40, world.pins.donor.sha256, world.pins.donor.size_bytes),
        runtime=dict(RUNTIME),
        resolution=RES,
    )
    with pytest.raises(AoMapError, match="pinned 0000"):
        a.plan(
            world.root / "r1", world.assets, world.record, world.sha256, pins=wrong, runtime=runtime
        )
    with pytest.raises(AoMapError, match="runtime is not pinned"):
        a.plan(
            world.root / "r1",
            world.assets,
            world.record,
            world.sha256,
            pins=world.pins,
            runtime=lambda: {"python": "other", "numpy": "stand-in"},
        )
    assert set(a.found_runtime()) == set(a.RUNTIME)


def test_run_directories_are_fresh_and_outside_the_repository(world: World) -> None:
    with pytest.raises(RecorderError, match="inside the repository"):
        a.plan(REPO_ROOT / "tmp" / "scratch" / "r1", world.assets, world.record, world.sha256)
    (world.root / "ao-map-r1").mkdir()
    with pytest.raises(AoMapError, match="already exists"):
        world.plan()
