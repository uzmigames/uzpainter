"""Self-test of the procedural certification harness (decisions 222 and 303; phase3.1 items 2.7
and 3.5, a permitted slice, not the task's acceptance).

Two synthetic families with formulas authored here stand in for recorded oracles; their hidden
constants (a bias, a multiplier) are what the fitters recover from the calibration set. The
negative cases are a one-texel perturbation, a missing blob, fitters and candidates that reach
the held-out set, a held-out list changed after its pin, sets that are not independent and a
held-out set spent on another candidate. Nothing here is a Painter asset or a Painter output.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from tools.parity.feasibility import png
from tools.parity.proc_cert.batch import (
    BATCH_SCHEMA,
    CASES_SCHEMA,
    BatchError,
    BlobRef,
    Case,
    Domain,
    RasterSpec,
    load_batch,
    parse_case,
    sha256_bytes,
)
from tools.parity.proc_cert.fence import HeldOutAccessError, fenced
from tools.parity.proc_cert.harness import (
    CalibrationAccess,
    CandidateChanged,
    CertificationRun,
    FitRefused,
    HeldOutSpent,
)
from tools.parity.proc_cert.raster import Raster
from tools.parity.store.store import OracleStore

U16 = npt.NDArray[np.uint16]

# --- synthetic families (authored formulas with known exact answers) ---------------------------

RAMP_BIAS = 1234  # the hidden constant of synthetic/affine-ramp
NOISE_MULT = 7  # the hidden constant of synthetic/seeded-noise
NOISE_MULTS = (3, 5, 7, 11, 13)  # what its fitter searches


def ramp(case: Case, bias: int) -> U16:
    n = case.output.resolution
    y, x = np.mgrid[0:n, 0:n].astype(np.int64)
    values = (case.params["a"] * x + case.params["b"] * y + bias + case.seed) % 65536
    result: U16 = values.astype(np.uint16).reshape(n, n, 1)
    return result


def position_map(mesh_id: str, resolution: int) -> U16:
    """The authored 'mesh map' of each synthetic mesh."""
    k = sum(mesh_id.encode()) % 97 + 1
    y, x = np.mgrid[0:resolution, 0:resolution].astype(np.int64)
    result: U16 = ((x * k + y * 31) % 65536).astype(np.uint16).reshape(resolution, resolution, 1)
    return result


def noise(case: Case, position: Raster, mult: int) -> U16:
    n = case.output.resolution
    y, x = np.mgrid[0:n, 0:n].astype(np.uint32)
    h = np.full((n, n), case.seed, np.uint32) * np.uint32(0x9E3779B1) + x * np.uint32(0x85EBCA77)
    h = h + y * np.uint32(0xC2B2AE3D)
    h ^= h >> np.uint32(15)
    h *= np.uint32(0x2C1B3C6D)
    h ^= h >> np.uint32(12)
    pos = position[..., 0].astype(np.int64)
    values = ((h >> np.uint32(16)).astype(np.int64) + case.params["scale"] * pos * mult) % 65536
    result: U16 = values.astype(np.uint16).reshape(n, n, 1)
    return result


RAMP_DOMAIN: dict[str, Any] = {
    "parameters": {"a": {"range": [0, 64]}, "b": {"range": [0, 64]}},
    "constraints": [{"coefficients": {"a": 1, "b": 1}, "max": 100}],
    "seeds": {"policy": "any_u32"},
    "geometry": {"mesh_classes": ["closed", "bevelled", "character"], "uv_tiles": 1, "inputs": {}},
    "output": {
        "resolutions": [8, 16],
        "formats": ["u16"],
        "colour_spaces": ["linear"],
        "channels": [1],
    },
}
NOISE_DOMAIN: dict[str, Any] = {
    "parameters": {"scale": {"range": [1, 8]}},
    "seeds": {"policy": "any_u32"},
    "geometry": {
        "mesh_classes": ["closed", "bevelled", "character"],
        "uv_tiles": 1,
        "inputs": {
            "position": {
                "resolutions": [8, 16],
                "formats": ["u16"],
                "colour_spaces": ["linear"],
                "channels": [1],
            }
        },
    },
    "output": {
        "resolutions": [8, 16],
        "formats": ["u16"],
        "colour_spaces": ["linear"],
        "channels": [1],
    },
}


def spec(case_id: str, mesh: str, params: dict[str, Any], seed: int, res: int) -> dict[str, Any]:
    classes = {"sphere": "closed", "cube": "bevelled", "hat": "character"}
    return {
        "case_id": case_id,
        "mesh": {"id": mesh, "class": classes[mesh], "uv_tiles": 1},
        "params": params,
        "seed": seed,
        "output": {"resolution": res, "format": "u16", "colour_space": "linear", "channels": 1},
    }


RAMP_CAL = [
    spec("cal-defaults", "sphere", {"a": 1, "b": 2}, 0, 16),
    spec("cal-boundary-low", "sphere", {"a": 0, "b": 0}, 0, 8),
    spec("cal-boundary-high", "cube", {"a": 64, "b": 36}, 9, 16),
]
RAMP_HELD = [
    spec("held-hat", "hat", {"a": 17, "b": 5}, 4242, 16),
    spec("held-cube", "cube", {"a": 3, "b": 50}, 77, 8),
]
NOISE_CAL = [
    spec("cal-defaults", "sphere", {"scale": 4}, 1, 16),
    spec("cal-low", "cube", {"scale": 1}, 2, 8),
    spec("cal-high", "sphere", {"scale": 8}, 2, 16),
]
NOISE_HELD = [
    spec("held-hat", "hat", {"scale": 3}, 99, 16),
    spec("held-cube", "cube", {"scale": 6}, 123456, 8),
]


# --- batch authoring ---------------------------------------------------------------------------


@dataclass
class Built:
    batch_path: Path
    store: OracleStore
    oracles: dict[str, str] = field(default_factory=dict)  # case id -> oracle sha256
    held_out_path: Path | None = None

    def run(self, reports: Path) -> CertificationRun:
        return CertificationRun(self.batch_path, self.store, reports)


def _put(store: OracleStore, scratch: Path, data: bytes) -> tuple[str, int]:
    sha = sha256_bytes(data)
    scratch.mkdir(parents=True, exist_ok=True)
    source = scratch / sha
    source.write_bytes(data)
    store.put_blob(source, sha)
    source.unlink()
    return sha, len(data)


def build(
    tmp: Path,
    family: str,
    *,
    calibration: list[dict[str, Any]] | None = None,
    held_out: list[dict[str, Any]] | None = None,
    domain: Mapping[str, Any] | None = None,
    perturb: str | None = None,
    encoding: str = "raw",
    held_root: str = "held-out",
) -> Built:
    """Write a batch whose oracles are the authored formulas (one texel +1 in `perturb`)."""
    store = OracleStore.init(tmp / "store")
    scratch = tmp / "scratch"
    built = Built(tmp / "batch" / "batch.json", store)
    cal = RAMP_CAL if family == "ramp" else NOISE_CAL
    held = RAMP_HELD if family == "ramp" else NOISE_HELD
    lists = {"calibration": calibration or cal, "held_out": held_out or held}
    pins: dict[str, Any] = {}
    for set_name, specs, root in (
        ("calibration", lists["calibration"], "calibration"),
        ("held_out", lists["held_out"], held_root),
    ):
        cases = []
        for entry in specs:
            entry = json.loads(json.dumps(entry))
            res = entry["output"]["resolution"]
            if family == "noise":
                position = position_map(entry["mesh"]["id"], res)
                sha, size = _put(store, scratch, position.astype("<u2").tobytes())
                entry["inputs"] = {
                    "position": {
                        "record_id": f"position-{entry['mesh']['id']}-{res}",
                        "sha256": sha,
                        "size_bytes": size,
                        "encoding": "raw",
                        "resolution": res,
                        "format": "u16",
                        "colour_space": "linear",
                        "channels": 1,
                    }
                }
            probe = Case(
                entry["case_id"],
                set_name,
                entry["mesh"]["id"],
                entry["mesh"]["class"],
                1,
                entry["params"],
                entry["seed"],
                RasterSpec(res, "u16", "linear", 1),
                {},
                BlobRef("unused", "0" * 64, 1, "raw"),
            )
            truth = (
                ramp(probe, RAMP_BIAS)
                if family == "ramp"
                else noise(probe, position_map(entry["mesh"]["id"], res), NOISE_MULT)
            ).copy()
            if entry["case_id"] == perturb:
                truth[res // 2, res // 3, 0] += 1
            data = png.encode(truth) if encoding == "png" else truth.astype("<u2").tobytes()
            sha, size = _put(store, scratch, data)
            built.oracles[entry["case_id"]] = sha
            entry["oracle"] = {
                "record_id": f"{entry['case_id']}-r1",
                "sha256": sha,
                "size_bytes": size,
                "encoding": encoding,
            }
            cases.append(entry)
        path = built.batch_path.parent / root / "cases.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps({"schema": CASES_SCHEMA, "set": set_name, "cases": cases}).encode()
        path.write_bytes(data)
        if set_name == "held_out":
            built.held_out_path = path
        pins[set_name] = {
            "corpus_id": f"synthetic-{family}-{set_name.replace('_', '-')}",
            "path": f"{root}/cases.json",
            "sha256": sha256_bytes(data),
        }
    built.batch_path.write_text(
        json.dumps(
            {
                "schema": BATCH_SCHEMA,
                "asset": f"synthetic/{'affine-ramp' if family == 'ramp' else 'seeded-noise'}",
                "asset_version": 1,
                "domain": domain or (RAMP_DOMAIN if family == "ramp" else NOISE_DOMAIN),
                **pins,
            }
        ),
        encoding="utf-8",
    )
    return built


# --- candidates and fitters --------------------------------------------------------------------


@dataclass
class RampCandidate:
    bias: int

    def fingerprint(self) -> Mapping[str, Any]:
        return {"family": "synthetic/affine-ramp", "code": 1, "bias": self.bias}

    def evaluate(self, case: Case, inputs: Mapping[str, Raster]) -> Raster:
        return ramp(case, self.bias)


@dataclass
class NoiseCandidate:
    mult: int

    def fingerprint(self) -> Mapping[str, Any]:
        return {"family": "synthetic/seeded-noise", "code": 1, "mult": self.mult}

    def evaluate(self, case: Case, inputs: Mapping[str, Raster]) -> Raster:
        return noise(case, inputs["position"], self.mult)


def fit_ramp(access: CalibrationAccess) -> RampCandidate:
    """bias = out(0, 0) - seed, read from the first available calibration oracle."""
    case = next(c for c in access.cases if c.oracle is not None)
    return RampCandidate((int(case.oracle[0, 0, 0]) - case.case.seed) % 65536)  # type: ignore[index]


def fit_noise(access: CalibrationAccess) -> NoiseCandidate:
    """Search the multiplier that reproduces every available calibration oracle bit-exactly."""
    usable = [c for c in access.cases if c.oracle is not None]
    for mult in NOISE_MULTS:
        if all(
            np.array_equal(noise(c.case, c.inputs["position"], mult), np.asarray(c.oracle))
            for c in usable
        ):
            return NoiseCandidate(mult)
    raise AssertionError("no multiplier fits the calibration set")


@dataclass
class Memoriser:
    """Overfits: replays each calibration oracle by its signature, zeros anywhere else."""

    table: dict[bytes, bytes]

    def fingerprint(self) -> Mapping[str, Any]:
        return {"family": "memoriser", "table": sha256_bytes(b"".join(sorted(self.table)))}

    def evaluate(self, case: Case, inputs: Mapping[str, Raster]) -> Raster:
        if case.signature() in self.table:
            return np.frombuffer(self.table[case.signature()], "<u2").reshape(case.output.shape)
        return np.zeros(case.output.shape, np.uint16)


def fit_memoriser(access: CalibrationAccess) -> Memoriser:
    return Memoriser(
        {c.case.signature(): c.oracle.tobytes() for c in access.cases if c.oracle is not None}
    )


def certify(built: Built, reports: Path, fitter: Callable[[CalibrationAccess], Any]) -> Any:
    run = built.run(reports)
    return run.certify(run.fit(fitter))


# --- positive cases ----------------------------------------------------------------------------


@pytest.mark.parametrize(("family", "fitter"), [("ramp", fit_ramp), ("noise", fit_noise)])
def test_exact_fits_certify_on_both_sets(tmp_path: Path, family: str, fitter: Any) -> None:
    built = build(tmp_path, family)
    run = built.run(tmp_path / "reports")
    fit = run.fit(fitter)
    assert fit.candidate.fingerprint() in (
        {"family": "synthetic/affine-ramp", "code": 1, "bias": RAMP_BIAS},
        {"family": "synthetic/seeded-noise", "code": 1, "mult": NOISE_MULT},
    )
    report = run.certify(fit)
    assert report["outcome"] == "exact"
    assert report["certified"] is True
    assert report["parity_status"] == {"kind": "exact"}
    assert report["sets"]["calibration"]["counts"]["exact"] == 3
    assert report["sets"]["held_out"]["counts"]["exact"] == 2
    assert report["sets"]["held_out"]["corpus_id"].endswith("held-out")
    assert all(
        case["residual"]["max_abs_diff"] == 0
        for s in report["sets"].values()
        for case in s["cases"]
    )


def test_png_oracles_compare_at_native_depth(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp", encoding="png")
    assert certify(built, tmp_path / "reports", fit_ramp)["outcome"] == "exact"


def test_reports_are_deterministic_and_hold_hashes_only(tmp_path: Path) -> None:
    built = build(tmp_path, "noise")
    run_a = built.run(tmp_path / "reports-a")
    run_b = built.run(tmp_path / "reports-b")
    report = run_a.certify(run_a.fit(fit_noise))
    run_b.certify(run_b.fit(fit_noise))
    text_a = run_a.report_path().read_bytes()
    assert text_a == run_b.report_path().read_bytes()
    assert json.loads(text_a) == report
    assert b"supported" not in text_a
    assert b"\r" not in text_a  # LF on every platform

    known = set(built.oracles.values()) | {
        report["batch_sha256"],
        report["domain_sha256"],
        report["candidate_sha256"],
        *(s["cases_sha256"] for s in report["sets"].values()),
        *(c["candidate_sha256"] for s in report["sets"].values() for c in s["cases"]),
    }

    def walk(node: Any) -> Iterator[Any]:
        if isinstance(node, dict):
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            assert len(node) <= 5, "a report never lists per-texel values"
            for value in node:
                yield from walk(value)
        else:
            yield node

    for leaf in walk(report):
        if isinstance(leaf, str) and re.fullmatch(r"[0-9a-f]{64}", leaf):
            assert leaf in known
    assert set(built.oracles.values()) <= known


# --- residual rejection ------------------------------------------------------------------------


@pytest.mark.parametrize("perturbed", ["held-hat", "cal-defaults"])
def test_a_one_texel_residual_is_reported_exactly_and_never_passes(
    tmp_path: Path, perturbed: str
) -> None:
    built = build(tmp_path, "ramp", perturb=perturbed)
    report = certify(built, tmp_path / "reports", fit_ramp)
    cases = {c["case_id"]: c for s in report["sets"].values() for c in s["cases"]}
    case = cases[perturbed]
    assert case["outcome"] == "residual"
    assert case["residual"] == {
        "max_abs_diff": 1,
        "sum_abs_diff": 1,
        "mean_abs_diff": 1 / 256,
        "p99_abs_diff": 0,  # nearest rank 254 of 256 values
        "differing_values": 1,
        "values": 256,
        "affected_texels": 1,
        "texels": 256,
    }
    assert all(c["outcome"] == "exact" for cid, c in cases.items() if cid != perturbed)
    assert report["outcome"] == "fail"
    assert report["certified"] is False
    assert report["parity_status"] == {
        "kind": "calibrated",
        "max_abs_diff": 1,
        "mean_abs_diff": 1 / (256 * 3 + 64 * 2),
        "p99_abs_diff": 0,
        "corpus_ids": ["synthetic-ramp-calibration", "synthetic-ramp-held-out"],
    }


def test_held_out_residual_fails_the_asset_although_calibration_is_exact(tmp_path: Path) -> None:
    report = certify(build(tmp_path, "noise"), tmp_path / "reports", fit_memoriser)
    assert report["sets"]["calibration"]["outcome"] == "exact"
    assert report["sets"]["held_out"]["outcome"] == "fail"
    assert report["sets"]["held_out"]["counts"]["residual"] == 2
    assert report["outcome"] == "fail"
    assert report["certified"] is False


@pytest.mark.parametrize(
    "output",
    [
        lambda r: r.astype(np.int64),  # right values, wrong type: never converted
        lambda r: r.astype(np.float32),
        lambda r: r[:-1],
    ],
)
def test_a_candidate_output_that_is_not_the_declared_raster_fails(
    tmp_path: Path, output: Callable[[U16], Any]
) -> None:
    @dataclass
    class Wrong(RampCandidate):
        def evaluate(self, case: Case, inputs: Mapping[str, Raster]) -> Raster:
            return output(ramp(case, self.bias))  # type: ignore[no-any-return]

    built = build(tmp_path, "ramp")
    run = built.run(tmp_path / "reports")
    report = run.certify(run.fit(lambda access: Wrong(fit_ramp(access).bias)))
    assert {c["outcome"] for s in report["sets"].values() for c in s["cases"]} == {"fail"}
    assert report["outcome"] == "fail"


# --- missing oracles ---------------------------------------------------------------------------


def _drop_blob(built: Built, case_id: str) -> None:
    path = built.store.blob_path(built.oracles[case_id])
    os.chmod(path, 0o600)
    path.unlink()


def test_a_missing_held_out_blob_is_oracle_unavailable(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp")
    _drop_blob(built, "held-cube")
    report = certify(built, tmp_path / "reports", fit_ramp)
    case = next(c for c in report["sets"]["held_out"]["cases"] if c["case_id"] == "held-cube")
    assert case["outcome"] == "oracle_unavailable"
    assert "missing" in case["reason"]
    assert report["sets"]["held_out"]["outcome"] == "oracle_unavailable"
    assert report["outcome"] == "oracle_unavailable"
    assert report["certified"] is False
    assert report["parity_status"] == {"kind": "unavailable"}


def test_a_missing_blob_and_a_residual_is_a_failure(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp", perturb="held-hat")
    _drop_blob(built, "held-cube")
    assert certify(built, tmp_path / "reports", fit_ramp)["outcome"] == "fail"


def test_a_missing_calibration_blob_reaches_the_fitter_as_unavailable(tmp_path: Path) -> None:
    built = build(tmp_path, "noise")
    _drop_blob(built, "cal-defaults")
    seen: dict[str, Any] = {}

    def fitter(access: CalibrationAccess) -> NoiseCandidate:
        seen.update({c.case.case_id: c.reason for c in access.cases if c.oracle is None})
        return fit_noise(access)

    report = certify(built, tmp_path / "reports", fitter)
    assert list(seen) == ["cal-defaults"]
    assert report["sets"]["calibration"]["outcome"] == "oracle_unavailable"
    assert report["outcome"] == "oracle_unavailable"


def test_without_a_store_every_case_is_oracle_unavailable(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp")
    run = CertificationRun(built.batch_path, None, tmp_path / "reports")
    report = run.certify(run.fit(lambda access: RampCandidate(0)))
    assert {c["outcome"] for s in report["sets"].values() for c in s["cases"]} == {
        "oracle_unavailable"
    }
    assert report["certified"] is False


# --- the fence: fitting cannot read held-out data ----------------------------------------------


def _held_out_attempts(built: Built, reports: Path) -> dict[str, Callable[[], object]]:
    held_sha = built.oracles["held-hat"]
    assert built.held_out_path is not None
    held_path = built.held_out_path
    return {
        "open the held-out list": lambda: held_path.read_bytes(),
        "list the held-out root": lambda: os.listdir(held_path.parent),
        "load a held-out blob through the store": lambda: built.store.load(held_sha),
        "open a held-out blob": lambda: built.store.blob_path(held_sha).open("rb").read(),
        "glob the store": lambda: list(built.store.root.rglob("*")),
        "read an earlier report": lambda: list(reports.rglob("*.json")),
        "start a process": lambda: subprocess.run([sys.executable, "-c", "0"], check=False),
        "rename the held-out list": lambda: os.rename(held_path, held_path.with_suffix(".x")),
    }


@pytest.mark.parametrize(
    "attempt",
    [
        "open the held-out list",
        "list the held-out root",
        "load a held-out blob through the store",
        "open a held-out blob",
        "glob the store",
        "read an earlier report",
        "start a process",
        "rename the held-out list",
    ],
)
def test_a_fitter_that_reaches_held_out_data_is_refused(tmp_path: Path, attempt: str) -> None:
    built = build(tmp_path, "ramp")
    reports = tmp_path / "reports"
    reports.mkdir()
    action = _held_out_attempts(built, reports)[attempt]

    def peeking(access: CalibrationAccess) -> RampCandidate:
        action()
        return fit_ramp(access)

    run = built.run(reports)
    with pytest.raises(FitRefused, match="fenced root"):
        run.fit(peeking)
    assert not run.report_path().exists()
    assert built.held_out_path is not None and built.held_out_path.is_file()


def test_a_fitter_that_swallows_the_refusal_is_still_refused(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp")
    assert built.held_out_path is not None
    held = built.held_out_path

    def sneaky(access: CalibrationAccess) -> RampCandidate:
        with contextlib.suppress(BaseException):
            held.read_bytes()
        return fit_ramp(access)

    with pytest.raises(FitRefused):
        built.run(tmp_path / "reports").fit(sneaky)


def test_a_candidate_that_reads_held_out_data_while_evaluating_is_refused(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp")
    held_sha = built.oracles["held-hat"]

    @dataclass
    class Peeking(RampCandidate):
        def evaluate(self, case: Case, inputs: Mapping[str, Raster]) -> Raster:
            built.store.load(held_sha)
            return ramp(case, self.bias)

    run = built.run(tmp_path / "reports")
    fit = run.fit(lambda access: Peeking(fit_ramp(access).bias))
    with pytest.raises(FitRefused, match="the candidate"):
        run.certify(fit)
    assert not run.report_path().exists()


def test_the_calibration_set_is_read_only_and_the_fence_is_scoped(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp")

    def writer(access: CalibrationAccess) -> RampCandidate:
        oracle = access.cases[0].oracle
        assert oracle is not None
        with pytest.raises(ValueError, match="read-only"):
            oracle[0, 0, 0] = 0
        return fit_ramp(access)

    built.run(tmp_path / "reports").fit(writer)
    assert built.held_out_path is not None
    assert built.held_out_path.read_bytes()  # readable again once the fitter has returned


def test_the_fence_refuses_relative_and_case_changed_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "Held"
    root.mkdir()
    (root / "blob").write_bytes(b"x")
    monkeypatch.chdir(tmp_path)
    variants = ["Held/blob", "Held/../Held/blob", str(root / "." / "blob")]
    if os.name == "nt":
        variants.append(str(root / "blob").swapcase())
    for variant in variants:
        with fenced([root], "test") as fence, pytest.raises(HeldOutAccessError):
            Path(variant).read_bytes()
        assert fence.refused
    assert (root / "blob").read_bytes() == b"x"


# --- pins, independence, spending --------------------------------------------------------------


def test_a_held_out_list_changed_after_its_pin_is_refused(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp")
    assert built.held_out_path is not None
    run = built.run(tmp_path / "reports")
    fit = run.fit(fit_ramp)
    built.held_out_path.write_bytes(built.held_out_path.read_bytes() + b" ")
    with pytest.raises(BatchError, match="pins"):
        run.certify(fit)
    with pytest.raises(BatchError, match="pins"):
        load_batch(built.batch_path)


@pytest.mark.parametrize(
    ("held_out", "message"),
    [
        (
            [spec("held-a", "sphere", {"a": 17, "b": 5}, 4242, 16)],
            "no mesh outside the calibration set",
        ),
        ([spec("held-a", "hat", {"a": 17, "b": 5}, 9, 16)], "no seed outside"),
        (
            [spec("held-a", "hat", {"a": 64, "b": 5}, 4242, 16)],
            "no new interior point of parameter a",
        ),
        (
            [spec("held-a", "hat", {"a": 1, "b": 5}, 4242, 16)],
            "no new interior point of parameter a",
        ),
        ([spec("held-a", "hat", {"a": 70, "b": 5}, 4242, 16)], r"params\.a = 70"),
        ([spec("held-a", "hat", {"a": 60, "b": 50}, 4242, 16)], "outside certified domain: params"),
        ([spec("held-a", "hat", {"a": 17, "b": 5}, 4242, 32)], r"output\.resolution = 32"),
        ([spec("cal-defaults", "hat", {"a": 17, "b": 5}, 4242, 16)], "used twice"),
    ],
)
def test_a_held_out_set_that_is_not_independent_is_refused(
    tmp_path: Path, held_out: list[dict[str, Any]], message: str
) -> None:
    with pytest.raises(BatchError, match=message):
        load_batch(build(tmp_path, "ramp", held_out=held_out).batch_path)


def test_a_held_out_case_repeating_a_calibration_case_is_refused(tmp_path: Path) -> None:
    held = [*RAMP_HELD, {**RAMP_CAL[0], "case_id": "held-copy"}]
    with pytest.raises(BatchError, match="shares its oracle blob") as error:
        load_batch(build(tmp_path, "ramp", held_out=held).batch_path)
    assert "repeats a calibration case" in str(error.value)


def test_the_held_out_root_must_be_separate(tmp_path: Path) -> None:
    with pytest.raises(BatchError, match="held_out root must be its own directory"):
        load_batch(build(tmp_path, "ramp", held_root="calibration/held").batch_path)


def test_a_spent_held_out_set_refuses_another_candidate(tmp_path: Path) -> None:
    built = build(tmp_path, "noise")
    reports = tmp_path / "reports"
    first = certify(built, reports, fit_memoriser)
    assert first["outcome"] == "fail"
    run = built.run(reports)
    with pytest.raises(HeldOutSpent, match="record a new held-out set"):
        run.certify(run.fit(fit_noise))
    again = built.run(reports)
    assert again.certify(again.fit(fit_memoriser)) == first  # the same candidate may re-run


def test_a_candidate_changed_after_fitting_is_refused(tmp_path: Path) -> None:
    run = build(tmp_path, "ramp").run(tmp_path / "reports")
    fit = run.fit(fit_ramp)
    fit.candidate.bias += 1  # type: ignore[attr-defined]
    with pytest.raises(CandidateChanged):
        run.certify(fit)


# --- the declared domain refuses, never clamps -------------------------------------------------


def _case(**changes: Any) -> Case:
    document = build_case_document()
    document.update(changes)
    return parse_case(document, "held_out")


def build_case_document() -> dict[str, Any]:
    entry = spec("probe", "hat", {"scale": 3}, 5, 16)
    blob = {"record_id": "r", "sha256": "0" * 64, "size_bytes": 1, "encoding": "raw"}
    raster = {"resolution": 16, "format": "u16", "colour_space": "linear", "channels": 1}
    return {**entry, "inputs": {"position": {**blob, **raster}}, "oracle": blob}


@pytest.mark.parametrize(
    ("changes", "field_name", "value", "certified"),
    [
        ({"params": {"scale": 8.5}}, "params.scale", 8.5, [1.0, 8.0]),
        ({"params": {"scale": 3, "extra": 1}}, "params.extra", 1, "not a parameter"),
        ({"params": {}}, "params.scale", "missing", "every declared parameter"),
        ({"seed": 1 << 32}, "seed", 1 << 32, [0, (1 << 32) - 1]),
        ({"inputs": {}}, "inputs.position", "missing", "a declared input"),
        (
            {
                "output": {
                    "resolution": 32,
                    "format": "u16",
                    "colour_space": "linear",
                    "channels": 1,
                }
            },
            "output.resolution",
            32,
            [8, 16],
        ),
        (
            {"output": {"resolution": 16, "format": "u16", "colour_space": "srgb", "channels": 1}},
            "output.colour_space",
            "srgb",
            ["linear"],
        ),
    ],
)
def test_the_domain_names_the_field_the_value_and_the_certified_range(
    changes: dict[str, Any], field_name: str, value: Any, certified: Any
) -> None:
    domain = Domain(NOISE_DOMAIN)
    assert domain.refusal(_case()) is None
    refusal = domain.refusal(_case(**changes))
    assert refusal is not None
    assert (refusal.field, refusal.value, refusal.certified) == (field_name, value, certified)
    assert str(refusal).startswith("outside certified domain")


def test_a_run_that_stops_after_the_reveal_still_spends_the_held_out_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = build(tmp_path, "noise")
    reports = tmp_path / "reports"
    run = built.run(reports)
    fit = run.fit(fit_memoriser)

    def crash(*args: Any, **kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(CertificationRun, "_report", crash)
    with pytest.raises(KeyboardInterrupt):
        run.certify(fit)
    monkeypatch.undo()
    assert json.loads(run.report_path().read_text(encoding="utf-8"))["outcome"] == "reserved"
    other = built.run(reports)
    with pytest.raises(HeldOutSpent):
        other.certify(other.fit(fit_noise))


def test_the_fingerprint_binds_the_candidate_class_not_only_its_declaration(
    tmp_path: Path,
) -> None:
    class Lookalike(RampCandidate):
        """Declares the same identity as RampCandidate."""

    built = build(tmp_path, "ramp")
    reports = tmp_path / "reports"
    certify(built, reports, fit_ramp)
    run = built.run(reports)
    with pytest.raises(HeldOutSpent):
        run.certify(run.fit(lambda access: Lookalike(fit_ramp(access).bias)))


def test_a_repeated_case_is_found_whatever_the_number_spelling(tmp_path: Path) -> None:
    copy = {**RAMP_CAL[0], "case_id": "held-float", "params": {"a": 1.0, "b": 2.0}}
    with pytest.raises(BatchError, match="held-float repeats a calibration case"):
        load_batch(build(tmp_path, "ramp", held_out=[*RAMP_HELD, copy]).batch_path)


@pytest.mark.parametrize(("policy", "loads"), [("listed", True), ("any_u32", False)])
def test_a_single_listed_seed_needs_no_other_held_out_seed(
    tmp_path: Path, policy: str, loads: bool
) -> None:
    seeds = {"policy": "listed", "seeds": [0]} if policy == "listed" else {"policy": "any_u32"}
    domain = {**RAMP_DOMAIN, "seeds": seeds}
    built = build(
        tmp_path,
        "ramp",
        calibration=[{**case, "seed": 0} for case in RAMP_CAL],
        held_out=[{**case, "seed": 0} for case in RAMP_HELD],
        domain=domain,
    )
    if loads:
        assert load_batch(built.batch_path).domain.seed_policy == "listed"
    else:
        with pytest.raises(BatchError, match="no seed outside"):
            load_batch(built.batch_path)
