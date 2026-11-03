"""The Tunic v10 fields-and-masks producer on a stand-in donor and authored receipts (decision 300).

The donor is an authored stand-in with the real `garment_material_masks.py`'s interface: a
`main` that parses `fields --work --resolution` and `masks --work --out`, `np.savez` of
`raster.npz` and `geo.npz` with the real members, dtypes and shapes, `ridge.npy` and `rim_sd.npy`,
the two reports with their `seconds`, and 16 padded 16-bit masks. It is committed to a throwaway
git repository at the donor's Assets3D path and run, step by step, in this process instead of a
child process. Front U3's records and the AO's are authored with the fields they hold. Nothing
here reads Assets3D, the real intermediates or the real donor, or claims anything about the real
masks.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

import numpy as np
import pytest

from tests.parity.tier1.test_tunic_ao import accepted_low, build_low, commit_donor
from tools.parity.recorder import tunic
from tools.parity.recorder.job import sha256_file
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier1 import sash_masks
from tools.parity.tier1 import tunic_ao as ao_host
from tools.parity.tier1 import tunic_ao_blender as ao_side
from tools.parity.tier1 import tunic_masks as m
from tools.parity.tier1.tunic_masks import MasksError

RES = 8
AO_RES = 4
RUNTIME = {"python": "stand-in", "numpy": "stand-in"}

DONOR_CODE = '''"""Stand-in garment_material_masks: the real CLI, members and file names."""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from tools.parity.feasibility import png as PNG

NAMES = NAMES_HERE


def nearest(valid):
    res = valid.shape[0]
    ys, xs = np.nonzero(valid)
    gy, gx = np.mgrid[0:res, 0:res]
    d = (gy[..., None] - ys) ** 2 + (gx[..., None] - xs) ** 2
    k = np.argmin(d, axis=-1)
    return np.stack([ys[k], xs[k]])


def cmd_fields(args):
    work = Path(args.work)
    res = args.resolution
    low = dict(np.load(work / "low.npz"))
    tri_id = -np.ones((res, res), np.int32)
    tri_id[: res // 2, : res // 2 + 1] = 0
    tri_id[0, res - 1] = 1
    valid = tri_id >= 0
    n = int(valid.sum())
    P = np.zeros((res, res, 3), np.float32)
    scale = 1.0 + float(low["co"].sum())
    P[valid] = (np.linspace(0.0, 1.0, n)[:, None] * scale).astype(np.float32)
    N = np.zeros((res, res, 3), np.float32)
    L = np.zeros((res, res), np.float32)
    island = np.where(valid, 0, -1).astype(np.int32)
    isl_of_tri = np.zeros(len(low["lt"]), np.int64)
    bary = np.zeros((res, res, 3), np.float16)
    np.savez(work / "raster.npz", tri_id=tri_id, P=P, N=N, L=L, island=island,
             isl_of_tri=isl_of_tri, bary=bary)
    if RIDGE and (work / "highnormal.npy").exists():
        np.save(work / "ridge.npy", np.load(work / "highnormal.npy")[..., 0].astype(RIDGE_DTYPE))
    np.save(work / "rim_sd.npy", np.where(valid, 0.01, 0.0).astype(np.float32))
    nv = len(low["co"])
    zeros = np.zeros(n, np.float32)
    np.savez(work / "geo.npz", sd_hem=zeros, sd_other=zeros, conv=zeros, d_hem=np.zeros(nv),
             is_rim=np.zeros(nv, bool))
    report = {"resolution": res, "coverage": float(valid.mean()), "seconds": time.perf_counter_ns()}
    (work / "fields_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("FIELDS_DONE")


def cmd_masks(args):
    work, out = Path(args.work), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rz = np.load(work / "raster.npz")
    valid = rz["tri_id"] >= 0
    res = valid.shape[0]
    ao = np.load(work / "ao.npy").astype(np.float32)
    rows, cols = nearest(valid)
    P = rz["P"][valid][:, 0].astype(np.float64)
    written = {}
    for k, name in enumerate(NAMES):
        v = (P * (k + 1) / 16 + float(ao.mean())) % 1.0
        a = np.zeros((res, res), np.float32)
        a[valid] = v
        if PAD:
            a = a[rows, cols]
        PNG.write(out / (name + ".png"), (a[::-1] * 65535 + 0.5).astype(np.uint16))
        written[name] = round(float(v.mean()), 5)
    report = {"mean": written, "seconds": time.perf_counter_ns()}
    (out / "masks_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fields")
    f.add_argument("--work", required=True)
    f.add_argument("--resolution", type=int, default=4096)
    s = sub.add_parser("masks")
    s.add_argument("--work", required=True)
    s.add_argument("--out", required=True)
    args = parser.parse_args()
    {"fields": cmd_fields, "masks": cmd_masks}[args.command](args)


if __name__ == "__main__":
    main()
'''


def donor_code(ridge: bool = True, ridge_dtype: str = "np.float32", pad: bool = True) -> str:
    return (
        DONOR_CODE.replace("NAMES_HERE", repr(m.DONOR_MASKS))
        .replace("RIDGE_DTYPE", ridge_dtype)
        .replace("RIDGE and", f"{ridge} and")
        .replace("if PAD:", f"if {pad}:")
    )


def nearest(valid: Any) -> Any:
    """The stand-in donor's padding indices (brute force, no SciPy on hosted CI)."""
    res = valid.shape[0]
    ys, xs = np.nonzero(valid)
    gy, gx = np.mgrid[0:res, 0:res]
    k = np.argmin((gy[..., None] - ys) ** 2 + (gx[..., None] - xs) ** 2, axis=-1)
    return np.stack([ys[k], xs[k]])


def write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def build_ao(
    root: Path,
    low: ao_host.LowInputs,
    value: float = 0.5,
    digests: Mapping[str, str] | None = None,
    repeat_changes: Mapping[str, Any] | None = None,
) -> NS:
    """The AO r1 record and its reproduced repeat, as `tunic_ao` writes them (the repeat's
    fields optionally changed while it still claims to reproduce r1)."""
    r1, repeat = root / "ao-r1", root / "ao-r1-repeat"
    ao = np.full((AO_RES, AO_RES), value, np.float16)
    key = f"{ao_side.DONOR_OUT}/{ao_side.AO_NAME}"
    for folder in (r1, repeat):
        (folder / ao_side.DONOR_OUT).mkdir(parents=True)
        np.save(folder / key, ao, allow_pickle=False)
    record = {
        "schema": ao_host.RECORD_SCHEMA,
        "kind": "ao",
        "status": "baked",
        "gpu": {"pin": ao_host.GpuPin().as_json()},
        "low_inputs": {
            "record_sha256": low.record_sha256,
            "repeat_sha256": low.repeat_sha256,
            "digests": dict(digests or low.digests),
        },
        "ao": {"bake": {"digest": ao_side.array_digest(ao)}},
        "outputs": {key: {"sha256": sha256_file(r1 / key)}},
    }
    write_json(r1 / ao_host.RECORD_NAME, record)
    expect = {
        "of_record_sha256": sha256_file(r1 / ao_host.RECORD_NAME),
        "reproduced": True,
        "problems": [],
    }
    write_json(repeat / ao_host.RECORD_NAME, {**record, **(repeat_changes or {}), "expect": expect})
    return NS(record=r1 / ao_host.RECORD_NAME, repeat=repeat / ao_host.RECORD_NAME)


def in_process(
    monkeypatch: pytest.MonkeyPatch,
    pins: m.Pins,
    runtime: Any = None,
    after: Callable[[str], None] = lambda step: None,
) -> m.Runner:
    """The child process, run here: `donor_step` with the stand-in pins and the env passed;
    `after` runs once a step is done (to change a file while the producer runs)."""

    def run(command: Sequence[str], cwd: Path, env: Mapping[str, str], log: Path, t: int) -> int:
        child = (sys.executable, "-B", "-m", "tools.parity.tier1.tunic_masks", "donor-step")
        assert command[:5] == child
        assert cwd == REPO_ROOT and t == m.TIMEOUTS_S[command[5]]
        step, run_dir, assets = command[5], Path(command[6]), Path(command[7])
        monkeypatch.setenv("PYTHONHASHSEED", env["PYTHONHASHSEED"])
        log.write_text("stand-in child\n", encoding="utf-8")
        try:
            m.donor_step(step, run_dir, assets, pins, runtime or (lambda: dict(RUNTIME)))
        except Exception as error:  # a child process exits non-zero on any error
            log.write_text(str(error), encoding="utf-8")
            return 1
        after(step)
        return 0

    return run


class Setup(NS):
    def plan(self, run: str = "masks-r1", **kwargs: Any) -> m.Plan:
        return m.plan(
            self.work / run,
            self.assets,
            kwargs.pop("low", self.low),
            kwargs.pop("ao_record", self.ao.record),
            kwargs.pop("ao_repeat", self.ao.repeat),
            pins=self.pins,
            runtime=lambda: dict(RUNTIME),
            **kwargs,
        )

    def produce(
        self,
        run: str = "masks-r1",
        runtime: Any = None,
        memory: Callable[[], int] = lambda: 1,
        after: Callable[[str], None] = lambda step: None,
        **kw: Any,
    ) -> tuple[dict[str, Any], list[str]]:
        return m.produce(
            self.plan(run, **kw),
            self.assets,
            self.pins,
            in_process(self.monkeypatch, self.pins, runtime, after),
            memory,
            nearest,
        )


def make_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: str) -> Setup:
    assets = tmp_path / "assets"
    assets.mkdir()
    donor, snapshot = commit_donor(assets, "garment_material_masks", m.DONOR.path, code)
    world = build_low(tmp_path / "u3", normal_res=RES)
    low = accepted_low(world)
    pins = m.Pins(
        snapshot=snapshot,
        donor=donor,
        runtime=dict(RUNTIME),
        resolution=RES,
        ao_resolution=AO_RES,
        vertices=4,
        triangles=2,
        low=world.pins,
        memory_budget=1,
        disk_budget=1,
    )
    return Setup(
        assets=assets,
        pins=pins,
        world=world,
        low=low,
        ao=build_ao(tmp_path / "ao", low),
        work=tmp_path / "w",
        root=tmp_path,
        monkeypatch=monkeypatch,
    )


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Setup:
    return make_setup(tmp_path, monkeypatch, donor_code())


# ------------------------------------------------------------------------------- the sets
def test_the_sets_follow_the_contract() -> None:
    assert m.stack_set_problems() == []
    contract = ("M_pores", "M_fiber", "M_dyeinv", "M_stains", "M_fray", "M_hem", "M_cav")
    assert (*contract, "M_ridgewear", "M_lining") == m.SUBSTITUTES  # its table, in its order
    assert sorted(m.DISCARDED) == sorted(
        ["M_band", "M_embro", "M_piping", "M_hemband", "M_lacerings", "M_laceholes", "M_hemline"]
    )
    assert set(tunic.RECOVERED) - set(m.DISCARDED) == {"M_piping_lining_v9"}
    assert len(m.DONOR_MASKS) == 16 and m.MASK_FORM == (16, 0)
    assert sash_masks.SOURCES[0] == m.DONOR  # the same blob front T pinned
    assert m.RUNTIME == sash_masks.RUNTIME and m.SNAPSHOT == ao_host.SNAPSHOT
    assert m.step_argv("fields", Path("w"), 4096) == [
        "fields",
        "--work",
        "w",
        "--resolution",
        "4096",
    ]
    assert m.step_argv("masks", Path("w"), 4096) == [
        "masks",
        "--work",
        "w",
        "--out",
        str(Path("w") / "donor-masks"),
    ]


# ---------------------------------------------------------------------------- the producer
def test_nine_substitutes_seven_discarded_eight_preserved(setup: Setup) -> None:
    path_before, argv_before = list(sys.path), list(sys.argv)
    record, problems = setup.produce()
    assert problems == [] and record["status"] == "produced"
    assert (list(sys.path), list(sys.argv)) == (path_before, argv_before)
    assert [o["name"] for o in record["substitutes"]] == [
        n for n in m.DONOR_MASKS if n in m.SUBSTITUTES
    ]
    assert {o["role"] for o in record["substitutes"]} == {"current-round substitute"}
    assert sorted(o["name"] for o in record["discarded"]) == sorted(m.DISCARDED)
    assert {o["role"] for o in record["discarded"]} == {"discarded-never-bound"}
    assert {p["name"]: p["sha256"] for p in record["preserved"]} == {
        name: sha256 for name, (_, sha256) in tunic.RECOVERED.items()
    }
    assert len(record["stack_masks"]) == 17
    run_dir = setup.work / "masks-r1"
    for entry in record["substitutes"]:
        assert sha256_file(run_dir / entry["file"]) == entry["sha256"]
    fields = record["fields"]
    assert sorted(fields["outputs"]) == sorted(m.FIELD_FILES)
    assert fields["report"]["excluded"] == ["seconds"]
    assert "seconds" not in fields["report"]["content"]
    assert "seconds" not in record["masks_report"]["content"]
    assert record["children"]["fields"]["runtime"] == RUNTIME
    assert record["children"]["masks"]["python_hash_seed"] == "0"
    assert record["staged"]["low.npz"] == setup.world.pins.low_npz_sha256
    assert record["ao_inputs"]["record_sha256"] == sha256_file(setup.ao.record)
    assert (run_dir / m.RECORD_NAME).is_file()


def test_a_repeat_agrees_byte_for_byte_npz_files_included(setup: Setup) -> None:
    first, _ = setup.produce()
    again, problems = setup.produce(
        "masks-r1-repeat", expect=setup.work / "masks-r1" / m.RECORD_NAME
    )
    assert problems == [] and again["status"] == "reproduced"
    assert again["repeat"]["result"] == "byte-identical"
    assert again["fields"]["outputs"]["raster.npz"] == first["fields"]["outputs"]["raster.npz"]
    assert again["fields"]["outputs"]["geo.npz"] == first["fields"]["outputs"]["geo.npz"]
    timings = [
        json.loads((setup.work / run / m.FIELDS_REPORT).read_bytes())["seconds"]
        for run in ("masks-r1", "masks-r1-repeat")
    ]
    assert timings[0] != timings[1]  # the one excluded field does differ
    with pytest.raises(MasksError, match="first produced"):
        setup.plan("masks-r1-again", expect=setup.work / "masks-r1-repeat" / m.RECORD_NAME)


def test_other_ao_gives_other_masks_and_no_reproduction(setup: Setup) -> None:
    setup.produce()
    other = build_ao(setup.root / "ao2", setup.low, value=0.25)
    record, problems = setup.produce(
        "masks-r1-other",
        ao_record=other.record,
        ao_repeat=other.repeat,
        expect=setup.work / "masks-r1" / m.RECORD_NAME,
    )
    assert record["status"] == "not-reproduced"
    assert any(p.startswith("substitutes") for p in problems)


def test_the_ao_must_be_reproduced_and_on_u3s_low(setup: Setup) -> None:
    original = setup.ao.repeat.read_bytes()
    record = json.loads(original)
    setup.ao.repeat.write_text(json.dumps({**record, "expect": {"reproduced": False}}))
    with pytest.raises(MasksError, match="does not say it reproduced"):
        setup.plan()
    setup.ao.repeat.write_bytes(original)
    moved = {**setup.low.digests, "co": "0" * 64}  # both records agree, on another low
    other = build_ao(setup.root / "ao-moved", setup.low, digests=moved)
    with pytest.raises(MasksError, match="another low"):
        setup.plan(ao_record=other.record, ao_repeat=other.repeat)


@pytest.mark.parametrize(
    "changes",
    [
        {"gpu": {"pin": {**ao_host.GpuPin().as_json(), "driver_version": "620.00"}}},
        {"ao": {"bake": {"digest": "0" * 64}}},
        {"scripts": {"host_sha256": "0" * 64}},
    ],
)
def test_a_repeat_that_claims_reproduction_is_compared_again(
    setup: Setup, changes: dict[str, Any]
) -> None:
    claimed = build_ao(setup.root / "ao-claimed", setup.low, repeat_changes=changes)
    with pytest.raises(MasksError, match="does not reproduce"):
        setup.plan(ao_record=claimed.record, ao_repeat=claimed.repeat)


def test_the_repeats_ao_file_is_hashed_too(setup: Setup) -> None:
    repeat_ao = setup.ao.repeat.parent / ao_side.DONOR_OUT / ao_side.AO_NAME
    repeat_ao.write_bytes(repeat_ao.read_bytes() + b"\0")
    with pytest.raises(MasksError, match="does not hash"):
        setup.plan()


def test_a_receipt_changed_during_the_run_is_refused(setup: Setup) -> None:
    def touch(step: str) -> None:
        if step == "fields":
            setup.ao.repeat.write_bytes(setup.ao.repeat.read_bytes() + b"\n")

    with pytest.raises(MasksError, match="after fields"):
        setup.produce(after=touch)
    assert not (setup.work / "masks-r1" / m.MASKS_OUT).exists()  # masks never ran


def test_the_code_closure_binds_the_steps_to_the_hashed_files(setup: Setup) -> None:
    closure = m.code_closure()
    assert "tools/parity/tier1/tunic_masks.py" in closure
    assert closure["tools/parity/tier1/tunic_ao_blender.py"] == sha256_file(
        REPO_ROOT / "tools/parity/tier1/tunic_ao_blender.py"
    )
    assert m.closure_problems(closure, closure, "a step") == []
    assert "no code closure" in m.closure_problems({}, closure, "a step")[0]
    path = "tools/parity/tier1/tunic_masks.py"
    assert "pinned" in m.closure_problems({path: "0" * 64}, closure, "a step")[0]
    record, _ = setup.produce()
    assert record["code"] == record["children"]["masks"]["code"]
    assert set(record["receipts"]) >= {"low_record", "ao_repeat", "ao_repeat_npy", "low/low.npz"}


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (donor_code(ridge=False), r"fields wrote no \['ridge.npy'\]"),
        (donor_code(ridge_dtype="np.float64"), "ridge.npy is <f8"),
        (donor_code(pad=False), "padding"),
    ],
)
def test_a_degraded_donor_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: str, message: str
) -> None:
    with pytest.raises(MasksError, match=message):
        make_setup(tmp_path, monkeypatch, code).produce()


def test_an_unpinned_child_runtime_and_a_short_budget_are_refused(setup: Setup) -> None:
    with pytest.raises(MasksError, match="fields exited 1"):
        setup.produce(runtime=lambda: {"python": "other", "numpy": "stand-in"})
    found = json.loads((setup.work / "masks-r1" / "fields-runtime.json").read_bytes())
    assert found["runtime"]["python"] == "other"
    refused = json.loads((setup.work / "masks-r1" / m.RECORD_NAME).read_bytes())
    assert refused["status"] == "refused" and "exited 1" in refused["error"]
    evidence = refused["integrity"]
    assert sorted(evidence) == ["after_fields", "at_failure", "before"]
    assert evidence["before"]["python"]["sha256"] == sha256_file(Path(sys.executable))
    assert evidence["at_failure"]["receipts"] == evidence["before"]["receipts"]
    assert evidence["after_fields"]["donor_copy"] == setup.pins.donor.sha256
    assert "tools/parity/tier1/tunic_masks.py" in evidence["at_failure"]["code"]
    with pytest.raises(MasksError, match="memory free for fields"):
        setup.produce("masks-r2", memory=lambda: 0)
    assert not (setup.work / "masks-r2" / "raster.npz").exists()


@pytest.mark.parametrize("timeout", [False, True])
def test_a_hash_that_cannot_be_read_fails_closed_and_keeps_the_error(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, timeout: bool
) -> None:
    """After `fields` starts the donor's copy can no longer be hashed (OSError): the integrity
    pass records it as unreadable, the run is refused with a record, and the error that ended
    the run (the refusal itself, or the step's timeout) is the one raised."""
    broken: list[bool] = []

    def flaky(path: Path) -> str:
        if broken and path.name == m.DONOR_FILE:
            raise OSError("the disk went away")
        return sha256_file(path)

    monkeypatch.setattr(m, "sha256_file", flaky)
    inner = in_process(monkeypatch, setup.pins)

    def runner(command: Sequence[str], cwd: Path, env: Mapping[str, str], log: Path, t: int) -> int:
        broken.append(True)
        if timeout:
            raise subprocess.TimeoutExpired(list(command), t)
        return inner(command, cwd, env, log, t)

    expected: type[BaseException] = subprocess.TimeoutExpired if timeout else MasksError
    with pytest.raises(expected) as raised:
        m.produce(setup.plan(), setup.assets, setup.pins, runner, lambda: 1, nearest)
    if not timeout:
        assert "after fields: donor_copy is unreadable: the disk went away" in str(raised.value)
    refused = json.loads((setup.work / "masks-r1" / m.RECORD_NAME).read_bytes())
    assert refused["status"] == "refused" and type(raised.value).__name__ in refused["error"]
    for when in ("after_fields", "at_failure"):
        assert refused["integrity"][when]["donor_copy"] == "unreadable: the disk went away"
    assert refused["integrity"]["before"]["donor_copy"] is None  # not yet written


def test_donor_step_refuses_another_blob_or_hash_seed(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = setup.work / "child"
    run_dir.mkdir(parents=True)
    (run_dir / m.DONOR_FILE).write_text("other bytes\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    with pytest.raises(MasksError, match="pinned blob"):
        m.donor_step("fields", run_dir, setup.assets, setup.pins, lambda: dict(RUNTIME))
    monkeypatch.delenv("PYTHONHASHSEED")
    with pytest.raises(MasksError, match="PYTHONHASHSEED"):
        m.donor_step("fields", run_dir, setup.assets, setup.pins, lambda: dict(RUNTIME))


def test_the_donor_may_open_nothing_under_assets3d(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    swatch = tmp_path / "assets" / "Swatches" / "cloth.png"  # under Assets3D: refused unread
    reading = donor_code().replace(
        'low = dict(np.load(work / "low.npz"))',
        f'low = dict(np.load(work / "low.npz"))\n    open({str(swatch)!r}, "rb")',
    )
    setup = make_setup(tmp_path, monkeypatch, reading)
    with pytest.raises(MasksError, match="fields exited 1"):
        setup.produce()
    assert "under" in (setup.work / "masks-r1" / "fields.log").read_text(encoding="utf-8")


def test_the_plan_writes_nothing_and_runs_stay_private(setup: Setup) -> None:
    the_plan = setup.plan()
    assert not the_plan.run_dir.exists()
    assert the_plan.as_json(setup.pins)["steps"]["fields"][-1] == str(RES)
    with pytest.raises(Exception, match="repository"):
        m.plan(
            REPO_ROOT / "tmp" / "scratch" / "x",
            setup.assets,
            setup.low,
            setup.ao.record,
            setup.ao.repeat,
        )
    (setup.work / "taken").mkdir(parents=True)
    with pytest.raises(MasksError, match="already exists"):
        setup.plan("taken")


def test_compare_records_leaves_out_only_the_runs_paths() -> None:
    record: dict[str, Any] = {
        "low_inputs": {"record": "a", "record_sha256": "s"},
        "children": {"fields": {"argv": ["x"]}},
    }
    other: dict[str, Any] = {
        "low_inputs": {"record": "b", "record_sha256": "s"},
        "children": {"fields": {"argv": ["y"]}},
    }
    assert m.compare_records(record, other) == []
    other["low_inputs"]["record_sha256"] = "t"
    assert m.compare_records(record, other)[0].startswith("low_inputs")
    # A donor report's keys are compared whatever their names.
    report = {"fields": {"report": {"content": {"record": 1}}}}
    assert m.compare_records(report, {"fields": {"report": {"content": {"record": 2}}}})


def test_available_memory_reads_the_machine() -> None:
    assert m.available_memory() > 0
