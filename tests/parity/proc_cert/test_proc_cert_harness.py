"""Self-test of the procedural certification harness (decisions 222 and 303; phase3.1 items 2.7
and 3.5, a permitted slice, not the task's acceptance).

Two synthetic families with formulas authored here stand in for recorded oracles; their hidden
constants (a bias, a multiplier) are what the fitters recover from the calibration set. The
negative cases are a one-texel perturbation, a missing blob, fitters and candidates that reach
the held-out set, a held-out list changed after its pin, sets that are not independent and a
held-out set spent on another candidate. Each calibration set covers the §6 matrix with decision
222's counts at small resolutions (4, 8 and 16 texels a side, not 1024 to 4096). Nothing here is a
Painter asset or a Painter output.
"""

from __future__ import annotations

import contextlib
import importlib
import io
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
from tools.parity.guard.guard import PATH_RULES
from tools.parity.proc_cert import cli
from tools.parity.proc_cert.batch import (
    BATCH_SCHEMA,
    CASES_SCHEMA,
    BatchError,
    BlobRef,
    Case,
    Domain,
    RasterSpec,
    canonical,
    load_batch,
    parse_case,
    sha256_bytes,
)
from tools.parity.proc_cert.fence import HeldOutAccessError, fenced
from tools.parity.proc_cert.fingerprint import candidate_sha256, import_closure
from tools.parity.proc_cert.harness import (
    CalibrationAccess,
    CandidateChanged,
    CertificationRun,
    FitRefused,
    HeldOutSpent,
)
from tools.parity.proc_cert.ledger import (
    DEFAULT_LEDGER,
    Ledger,
    LedgerError,
    ledger_problems,
    render,
)
from tools.parity.proc_cert.raster import (
    DTYPES,
    Raster,
    RasterError,
    check_candidate,
    decode,
    raster_sha256,
    residual,
)
from tools.parity.store.store import OracleStore

U16 = npt.NDArray[np.uint16]

# --- synthetic families (authored formulas with known exact answers) ---------------------------

RAMP_BIAS = 1234  # the hidden constant of synthetic/affine-ramp
NOISE_MULT = 7  # the hidden constant of synthetic/seeded-noise
NOISE_MULTS = (3, 5, 7, 11, 13)  # what its fitter searches


def ramp(case: Case, bias: int) -> Raster:
    """u16 code values; for a float output, the same ramp divided by 7 in that float type."""
    n = case.output.resolution
    y, x = np.mgrid[0:n, 0:n].astype(np.int64)
    values = (case.params["a"] * x + case.params["b"] * y + bias + case.seed) % 65536
    result: U16 = values.astype(np.uint16).reshape(n, n, 1)
    if case.output.format == "u16":
        return result
    floats: Raster = (result.astype(np.float64) / 7).astype(DTYPES[case.output.format])
    return floats


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


RESOLUTIONS = [4, 8, 16]
RAMP_DOMAIN: dict[str, Any] = {
    "parameters": {"a": {"range": [0, 64]}, "b": {"range": [0, 64]}},
    "constraints": [{"coefficients": {"a": 1, "b": 1}, "max": 100}],
    "seeds": {"policy": "any_u32"},
    "geometry": {"mesh_classes": ["closed", "bevelled", "character"], "uv_tiles": 1, "inputs": {}},
    "output": {
        "resolutions": RESOLUTIONS,
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
                "resolutions": RESOLUTIONS,
                "formats": ["u16"],
                "colour_spaces": ["linear"],
                "channels": [1],
            }
        },
    },
    "output": {
        "resolutions": RESOLUTIONS,
        "formats": ["u16"],
        "colour_spaces": ["linear"],
        "channels": [1],
    },
}


def spec(case_id: str, mesh: str, params: dict[str, Any], seed: int, res: int) -> dict[str, Any]:
    classes = {"sphere": "closed", "cube": "bevelled", "hat": "character", "boot": "character"}
    return {
        "case_id": case_id,
        "mesh": {"id": mesh, "class": classes[mesh], "uv_tiles": 1},
        "params": params,
        "seed": seed,
        "output": {"resolution": res, "format": "u16", "colour_space": "linear", "channels": 1},
    }


def parameter_sets(defaults: Any, recipe: Any, low: Any, high: Any) -> list[dict[str, Any]]:
    return [
        {"id": "defaults", "role": "defaults", "params": defaults},
        {"id": "recipe-stripes", "role": "recipe", "params": recipe},
        {"id": "boundary-low", "role": "boundary", "params": low},
        {"id": "boundary-high", "role": "boundary", "params": high},
    ]


# §6 with decision 222's counts: 3 meshes x 3 resolutions x 4 parameter sets x 2 seeds.
RAMP_MATRIX: dict[str, Any] = {
    "meshes": ["sphere", "cube", "hat"],
    "resolutions": RESOLUTIONS,
    "parameter_sets": parameter_sets(
        {"a": 1, "b": 2}, {"a": 5, "b": 9}, {"a": 0, "b": 0}, {"a": 64, "b": 36}
    ),
    "seeds": [0, 9],
}
NOISE_MATRIX: dict[str, Any] = {
    "meshes": ["sphere", "cube", "hat"],
    "resolutions": RESOLUTIONS,
    "parameter_sets": parameter_sets({"scale": 4}, {"scale": 2}, {"scale": 1}, {"scale": 8}),
    "seeds": [1, 2],
}


def matrix_cases(matrix: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One calibration case per cell of the matrix."""
    return [
        spec(f"cal-{mesh}-{res}-{s['id']}-{seed}", mesh, s["params"], seed, res)
        for mesh in matrix["meshes"]
        for res in matrix["resolutions"]
        for s in matrix["parameter_sets"]
        for seed in matrix["seeds"]
    ]


CAL_DEFAULTS = "cal-sphere-16-defaults-0"  # a 16 x 16 calibration case of the ramp
RAMP_CAL = matrix_cases(RAMP_MATRIX)
RAMP_HELD = [
    spec("held-boot", "boot", {"a": 17, "b": 5}, 4242, 16),
    spec("held-cube", "cube", {"a": 3, "b": 50}, 77, 8),
]
NOISE_CAL = matrix_cases(NOISE_MATRIX)
NOISE_HELD = [
    spec("held-boot", "boot", {"scale": 3}, 99, 16),
    spec("held-cube", "cube", {"scale": 6}, 123456, 8),
]


# --- batch authoring ---------------------------------------------------------------------------


@dataclass
class Built:
    batch_path: Path
    store: OracleStore
    ledger: Path
    oracles: dict[str, str] = field(default_factory=dict)  # case id -> oracle sha256
    held_out_path: Path | None = None

    def run(self, reports: Path, **options: Any) -> CertificationRun:
        return CertificationRun(
            self.batch_path, self.store, reports, Ledger(self.ledger), **options
        )


def exr_bytes(values: Raster, scratch: Path) -> bytes:
    """A one-channel (Y) OpenEXR file of `values`, written by OpenEXR's binding."""
    exr = pytest.importorskip("OpenEXR", reason="writes the EXR oracles; owner's machine only")
    scratch.mkdir(parents=True, exist_ok=True)
    path = scratch / "oracle.exr"
    header = {"compression": exr.ZIP_COMPRESSION, "type": exr.scanlineimage}
    with exr.File(header, {"Y": np.ascontiguousarray(values[..., 0])}) as stream:
        stream.write(str(path))
    data = path.read_bytes()
    path.unlink()
    return data


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
    matrix: Mapping[str, Any] | None = None,
    perturb: str | None = None,
    encoding: str = "raw",
    fmt: str = "u16",
    held_root: str = "held-out",
) -> Built:
    """Write a batch whose oracles are the authored formulas (one texel +1 code value, or +1 ULP
    for a float format, in `perturb`). The calibration set defaults to every cell of `matrix`."""
    store = OracleStore.init(tmp / "store")
    scratch = tmp / "scratch"
    built = Built(tmp / "batch" / "batch.json", store, Ledger.create(tmp / "ledger.json").path)
    matrix = matrix or (RAMP_MATRIX if family == "ramp" else NOISE_MATRIX)
    held = RAMP_HELD if family == "ramp" else NOISE_HELD
    lists = {"calibration": calibration or matrix_cases(matrix), "held_out": held_out or held}
    pins: dict[str, Any] = {}
    for set_name, specs, root in (
        ("calibration", lists["calibration"], "calibration"),
        ("held_out", lists["held_out"], held_root),
    ):
        cases = []
        for entry in specs:
            entry = json.loads(json.dumps(entry))
            entry["output"]["format"] = fmt
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
                RasterSpec(res, fmt, "linear", 1),
                {},
                BlobRef("unused", "0" * 64, 1, "raw"),
            )
            truth = (
                ramp(probe, RAMP_BIAS)
                if family == "ramp"
                else noise(probe, position_map(entry["mesh"]["id"], res), NOISE_MULT)
            ).copy()
            if entry["case_id"] == perturb:
                if fmt == "u16":
                    truth[res // 2, res // 3, 0] += 1
                else:
                    texel = truth[res // 2, res // 3, 0]
                    truth[res // 2, res // 3, 0] = np.nextafter(texel, texel.dtype.type(np.inf))
            if encoding == "png":
                data = png.encode(truth.astype(np.uint16))
            elif encoding == "exr":
                data = exr_bytes(truth, scratch)
            else:
                data = truth.astype(DTYPES[fmt]).tobytes()
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
    domain = domain or (RAMP_DOMAIN if family == "ramp" else NOISE_DOMAIN)
    if fmt != "u16":
        domain = {**domain, "output": {**domain["output"], "formats": [fmt]}}
    built.batch_path.write_text(
        json.dumps(
            {
                "schema": BATCH_SCHEMA,
                "asset": f"synthetic/{'affine-ramp' if family == 'ramp' else 'seeded-noise'}",
                "asset_version": 1,
                "domain": domain,
                "matrix": matrix,
                **pins,
            }
        ),
        encoding="utf-8",
    )
    return built


def rewrite(built: Built, set_name: str, change: Callable[[list[dict[str, Any]]], None]) -> None:
    """Change one case list and pin its new bytes in batch.json (an authoring step, before any
    fitting)."""
    batch = json.loads(built.batch_path.read_text(encoding="utf-8"))
    path = built.batch_path.parent / batch[set_name]["path"]
    document = json.loads(path.read_bytes())
    change(document["cases"])
    data = json.dumps(document).encode()
    path.write_bytes(data)
    batch[set_name]["sha256"] = sha256_bytes(data)
    built.batch_path.write_text(json.dumps(batch), encoding="utf-8")


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
        """The complete fitted state: every key and the bytes it replays."""
        entries = sorted([key.hex(), sha256_bytes(value)] for key, value in self.table.items())
        return {"family": "memoriser", "table": sha256_bytes(canonical(entries))}

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
    assert report["sets"]["calibration"]["counts"]["exact"] == 72
    assert report["sets"]["held_out"]["counts"]["exact"] == 2
    assert report["matrix"] == {
        "cells": 72,
        "meshes": 3,
        "resolutions": RESOLUTIONS,
        "parameter_sets": {"defaults": 1, "recipe": 1, "boundary": 2},
        "seeds": 2,
    }
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
            # a report lists cases and a few identifiers, never per-texel values
            assert all(isinstance(value, dict) for value in node) or len(node) <= 5
            for value in node:
                yield from walk(value)
        else:
            yield node

    for leaf in walk(report):
        if isinstance(leaf, str) and re.fullmatch(r"[0-9a-f]{64}", leaf):
            assert leaf in known
    assert set(built.oracles.values()) <= known


# --- residual rejection ------------------------------------------------------------------------


@pytest.mark.parametrize("perturbed", ["held-boot", CAL_DEFAULTS])
def test_a_one_texel_residual_is_reported_exactly_and_never_passes(
    tmp_path: Path, perturbed: str
) -> None:
    built = build(tmp_path, "ramp", perturb=perturbed)
    report = certify(built, tmp_path / "reports", fit_ramp)
    cases = {c["case_id"]: c for s in report["sets"].values() for c in s["cases"]}
    case = cases[perturbed]
    assert case["outcome"] == "residual"
    assert case["residual"] == {
        "unit": "code_u16",
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
    values = sum(c["output"]["resolution"] ** 2 for c in RAMP_CAL + RAMP_HELD)
    assert report["parity_status"] == {
        "kind": "calibrated",
        "residuals": {
            "code_u16": {"max_abs_diff": 1, "mean_abs_diff": 1 / values, "p99_abs_diff": 0}
        },
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
        lambda r: r.astype(np.int16),  # same size, signed
        lambda r: r[:-1],
    ],
)
def test_a_candidate_output_that_is_not_the_declared_raster_fails(
    tmp_path: Path, output: Callable[[Raster], Any]
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
    built = build(tmp_path, "ramp", perturb="held-boot")
    _drop_blob(built, "held-cube")
    assert certify(built, tmp_path / "reports", fit_ramp)["outcome"] == "fail"


def test_a_missing_calibration_blob_reaches_the_fitter_as_unavailable(tmp_path: Path) -> None:
    built = build(tmp_path, "noise")
    _drop_blob(built, "cal-sphere-16-defaults-1")
    seen: dict[str, Any] = {}

    def fitter(access: CalibrationAccess) -> NoiseCandidate:
        seen.update({c.case.case_id: c.reason for c in access.cases if c.oracle is None})
        return fit_noise(access)

    report = certify(built, tmp_path / "reports", fitter)
    assert list(seen) == ["cal-sphere-16-defaults-1"]
    assert report["sets"]["calibration"]["outcome"] == "oracle_unavailable"
    assert report["outcome"] == "oracle_unavailable"


def test_without_a_store_every_case_is_oracle_unavailable(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp")
    run = CertificationRun(built.batch_path, None, tmp_path / "reports", Ledger(built.ledger))
    report = run.certify(run.fit(lambda access: RampCandidate(0)))
    assert {c["outcome"] for s in report["sets"].values() for c in s["cases"]} == {
        "oracle_unavailable"
    }
    assert report["certified"] is False


# --- the fence: fitting cannot read held-out data ----------------------------------------------


def _held_out_attempts(built: Built, reports: Path) -> dict[str, Callable[[], object]]:
    held_sha = built.oracles["held-boot"]
    assert built.held_out_path is not None
    held_path = built.held_out_path
    return {
        "read the ledger": lambda: built.ledger.read_bytes(),
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
        "read the ledger",
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
    held_sha = built.oracles["held-boot"]

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
        ([spec("held-a", "boot", {"a": 17, "b": 5}, 9, 16)], "no seed outside"),
        (
            [spec("held-a", "boot", {"a": 64, "b": 5}, 4242, 16)],
            "no new interior point of parameter a",
        ),
        (
            [spec("held-a", "boot", {"a": 1, "b": 5}, 4242, 16)],
            "no new interior point of parameter a",
        ),
        ([spec("held-a", "boot", {"a": 70, "b": 5}, 4242, 16)], r"params\.a = 70"),
        (
            [spec("held-a", "boot", {"a": 60, "b": 50}, 4242, 16)],
            "outside certified domain: params",
        ),
        ([spec("held-a", "boot", {"a": 17, "b": 5}, 4242, 32)], r"output\.resolution = 32"),
        ([spec(CAL_DEFAULTS, "boot", {"a": 17, "b": 5}, 4242, 16)], "used twice"),
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
            RESOLUTIONS,
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
        matrix={**RAMP_MATRIX, "seeds": [0]},  # one seed: all the matrix can hold
        held_out=[{**case, "seed": 0} for case in RAMP_HELD],
        domain=domain,
    )
    if loads:
        assert load_batch(built.batch_path).domain.seed_policy == "listed"
    else:
        with pytest.raises(BatchError, match="no seed outside"):
            load_batch(built.batch_path)


# --- SUP-024: blobs a fitter sees, fenced fingerprints, owned outputs, complete identities -------


def test_a_calibration_input_that_is_a_held_out_oracle_is_refused(tmp_path: Path) -> None:
    """SUP-024 (a): the fitter is given the calibration inputs as well as the oracles."""
    built = build(tmp_path, "noise")
    assert built.held_out_path is not None
    held = next(
        c
        for c in json.loads(built.held_out_path.read_bytes())["cases"]
        if c["case_id"] == "held-boot"
    )

    def collide(cases: list[dict[str, Any]]) -> None:
        position = cases[0]["inputs"]["position"]
        position.update(sha256=held["oracle"]["sha256"], size_bytes=held["oracle"]["size_bytes"])

    rewrite(built, "calibration", collide)
    with pytest.raises(BatchError, match=r"held-boot shares its oracle blob .*oracle or input"):
        load_batch(built.batch_path)


@pytest.mark.parametrize("swallow", [False, True])
def test_a_fingerprint_that_reads_protected_files_only_at_certify_is_refused(
    tmp_path: Path, swallow: bool
) -> None:
    """SUP-024 (b): the fingerprint is candidate code, fenced at certify as at fit."""
    built = build(tmp_path, "ramp")
    assert built.held_out_path is not None
    held: Path = built.held_out_path

    @dataclass
    class LateReader(RampCandidate):
        calls: int = 0

        def fingerprint(self) -> Mapping[str, Any]:
            self.calls += 1
            if self.calls > 1:  # the first call is the fit's; read only at certify
                guard = (
                    contextlib.suppress(HeldOutAccessError) if swallow else contextlib.nullcontext()
                )
                with guard:
                    held.read_bytes()
            return super().fingerprint()

    run = built.run(tmp_path / "reports")
    fit = run.fit(lambda access: LateReader(fit_ramp(access).bias))
    with pytest.raises(FitRefused, match="fingerprint reached a fenced root"):
        run.certify(fit)
    assert not run.report_path().exists()
    assert Ledger(built.ledger).read() == {}


def test_a_candidate_that_reuses_one_output_buffer_is_scored_correctly(tmp_path: Path) -> None:
    """SUP-024 (c): each output is copied before the next evaluate overwrites the buffer."""

    @dataclass
    class Reusing(RampCandidate):
        buffers: dict[tuple[int, ...], U16] = field(default_factory=dict)

        def evaluate(self, case: Case, inputs: Mapping[str, Raster]) -> Raster:
            shape = case.output.shape
            buffer = self.buffers.setdefault(shape, np.zeros(shape, np.uint16))
            buffer[...] = ramp(case, self.bias)
            return buffer

    built = build(tmp_path, "ramp")
    report = certify(built, tmp_path / "reports", lambda access: Reusing(fit_ramp(access).bias))
    assert report["outcome"] == "exact"
    batch = load_batch(built.batch_path)
    for which in (batch.calibration, batch.held_out):
        expected = {c.case_id: raster_sha256(ramp(c, RAMP_BIAS)) for c in batch.cases(which)}
        found = {c["case_id"]: c["candidate_sha256"] for c in report["sets"][which.name]["cases"]}
        assert found == expected


def test_a_checked_output_is_an_owned_read_only_copy() -> None:
    output = np.arange(16, dtype=np.uint16).reshape(4, 4, 1)
    checked = check_candidate(RasterSpec(4, "u16", "linear", 1), output)
    assert not np.shares_memory(checked, output)
    assert not checked.flags.writeable
    output[...] = 0
    assert int(checked.max()) == 15


def test_changing_the_fitted_contents_invalidates_reuse(tmp_path: Path) -> None:
    """SUP-024 (d): the memoriser's identity covers its keys and the values it replays."""
    built = build(tmp_path, "noise")
    reports = tmp_path / "reports"
    first = built.run(reports)
    fit = first.fit(fit_memoriser)
    assert isinstance(fit.candidate, Memoriser)
    table = fit.candidate.table
    key = next(iter(table))
    original = table[key]
    table[key] = bytes(len(original))  # the same keys, other fitted values
    with pytest.raises(CandidateChanged):
        first.certify(fit)
    table[key] = original
    first.certify(fit)

    def same_keys_other_values(access: CalibrationAccess) -> Memoriser:
        memoriser = fit_memoriser(access)
        memoriser.table[key] = bytes(len(memoriser.table[key]))
        return memoriser

    again = built.run(reports)
    with pytest.raises(HeldOutSpent):
        again.certify(again.fit(same_keys_other_values))


# --- the fingerprint covers the import closure -------------------------------------------------

CANDIDATE_MODULE = """from . import helper


class Candidate:
    def fingerprint(self):
        return {"family": "closure", "offset": helper.OFFSET}

    def evaluate(self, case, inputs):
        from PACKAGE.lazy import SCALE

        return SCALE
"""


@pytest.fixture
def closure_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Path, Any]]:
    """A project tree of its own: a candidate module, a helper it imports at the top, a module
    it imports inside a method, and a module nothing imports."""
    name = "proc_cert_closure_" + re.sub(r"\W", "_", tmp_path.name)
    package = tmp_path / "project" / name
    package.mkdir(parents=True)
    for module, text in (
        ("__init__", ""),
        ("helper", "OFFSET = 1\n"),
        ("lazy", "SCALE = 2\n"),
        ("unrelated", "X = 0\n"),
        ("candidate", CANDIDATE_MODULE.replace("PACKAGE", name)),
    ):
        (package / f"{module}.py").write_text(text, encoding="utf-8")
    monkeypatch.syspath_prepend(str(package.parent))
    try:
        yield package, importlib.import_module(f"{name}.candidate").Candidate()
    finally:
        for loaded in [n for n in sys.modules if n.split(".")[0] == name]:
            del sys.modules[loaded]


def test_the_fingerprint_hashes_the_imported_project_modules(
    closure_project: tuple[Path, Any],
) -> None:
    package, candidate = closure_project
    root, name = package.parent, package.name
    closure = import_closure([type(candidate).__module__], root)
    assert set(closure) == {name, f"{name}.candidate", f"{name}.helper", f"{name}.lazy"}
    assert f"{name}.lazy" not in sys.modules  # found from the source; nothing was imported
    before = candidate_sha256(candidate, root)
    (package / "unrelated.py").write_text("X = 1\n", encoding="utf-8")
    assert candidate_sha256(candidate, root) == before
    (package / "lazy.py").write_text("SCALE = 3\n", encoding="utf-8")  # imported in a method
    changed = candidate_sha256(candidate, root)
    assert changed != before
    (package / "helper.py").write_text("OFFSET = 1  # edited\n", encoding="utf-8")
    assert candidate_sha256(candidate, root) != changed


def test_an_imported_module_changed_after_fitting_changes_the_candidate(
    tmp_path: Path, closure_project: tuple[Path, Any]
) -> None:
    package, candidate = closure_project
    built = build(tmp_path, "ramp")
    run = built.run(tmp_path / "reports", project_root=package.parent)
    fit = run.fit(lambda access: candidate)
    (package / "helper.py").write_text("OFFSET = 1  # a new version\n", encoding="utf-8")
    with pytest.raises(CandidateChanged):
        run.certify(fit)


def test_a_candidate_outside_the_project_tree_is_refused(
    tmp_path: Path, closure_project: tuple[Path, Any]
) -> None:
    _, candidate = closure_project
    run = build(tmp_path, "ramp").run(tmp_path / "reports")  # the repository is the project
    with pytest.raises(FitRefused, match="not defined in a module of the project tree"):
        run.fit(lambda access: candidate)


# --- the durable held-out ledger ---------------------------------------------------------------


def test_deleting_a_local_report_does_not_reset_the_spend(tmp_path: Path) -> None:
    built = build(tmp_path, "noise")
    first = built.run(tmp_path / "reports-a")
    report = first.certify(first.fit(fit_memoriser))
    pin = load_batch(built.batch_path).held_out.sha256
    first.report_path().unlink()
    for reports in ("reports-a", "reports-b"):  # the same directory, and another one
        other = built.run(tmp_path / reports)
        with pytest.raises(HeldOutSpent, match="record a new held-out set"):
            other.certify(other.fit(fit_noise))
        assert not other.report_path().exists()
    again = built.run(tmp_path / "reports-a")
    assert again.certify(again.fit(fit_memoriser)) == report  # the same candidate may re-run
    assert Ledger(built.ledger).read() == {pin: report["candidate_sha256"]}


def test_the_ledger_is_canonical_lf_and_holds_hashes_only(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp")
    report = certify(built, tmp_path / "reports", fit_ramp)
    pin = load_batch(built.batch_path).held_out.sha256
    data = built.ledger.read_bytes()
    assert data == render({pin: report["candidate_sha256"]})
    assert b"\r" not in data and data.endswith(b"}\n")
    document = json.loads(data)
    assert ledger_problems(document) == []
    assert document == {
        "schema": "uzpainter/parity/proc-cert-ledger/1",
        "spent": {pin: report["candidate_sha256"]},
    }
    assert ledger_problems({**document, "spent": {pin: "not a hash"}})
    assert ledger_problems({**document, "asset": "synthetic/affine-ramp"})


def test_the_committed_ledger_is_valid_and_guarded() -> None:
    assert ledger_problems(json.loads(DEFAULT_LEDGER.read_bytes())) == []
    path = DEFAULT_LEDGER.relative_to(Path(__file__).resolve().parents[3]).as_posix()
    assert path == "parity/reports/phase3/held-out-ledger.json"
    rule = next(r for r in PATH_RULES if r[0].match(path))
    assert "held-out ledger" in rule[1]


def test_a_missing_or_locked_ledger_is_refused(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp")
    with pytest.raises(LedgerError, match="no held-out ledger"):
        Ledger(tmp_path / "elsewhere.json")
    run = built.run(tmp_path / "reports")
    fit = run.fit(fit_ramp)
    lock = Ledger(built.ledger).lock
    lock.write_bytes(b"")
    with pytest.raises(LedgerError, match="another certification"):
        run.certify(fit)
    assert Ledger(built.ledger).read() == {}
    assert not run.report_path().exists()
    lock.unlink()
    assert run.certify(fit)["outcome"] == "exact"


# --- float (EXR) oracles, decision 305 ---------------------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "encoding"), [("f16", "exr"), ("f32", "exr"), ("f16", "raw"), ("f32", "raw")]
)
def test_float_oracles_compare_bit_exactly(tmp_path: Path, fmt: str, encoding: str) -> None:
    built = build(tmp_path, "ramp", fmt=fmt, encoding=encoding)
    report = certify(built, tmp_path / "reports", lambda access: RampCandidate(RAMP_BIAS))
    assert report["outcome"] == "exact"
    assert report["sets"]["calibration"]["counts"]["exact"] == 72
    assert report["sets"]["held_out"]["cases"][0]["residual"]["unit"] == f"ulp_{fmt}"


@pytest.mark.parametrize("fmt", ["f16", "f32"])
def test_a_one_ulp_residual_is_measured_in_ulps(tmp_path: Path, fmt: str) -> None:
    built = build(tmp_path, "ramp", fmt=fmt, encoding="exr", perturb="held-boot")
    report = certify(built, tmp_path / "reports", lambda access: RampCandidate(RAMP_BIAS))
    case = next(c for c in report["sets"]["held_out"]["cases"] if c["case_id"] == "held-boot")
    assert case["outcome"] == "residual"
    assert case["residual"]["unit"] == f"ulp_{fmt}"
    assert (case["residual"]["max_abs_diff"], case["residual"]["sum_abs_diff"]) == (1, 1)
    assert case["residual"]["affected_texels"] == 1
    assert report["outcome"] == "fail"
    assert list(report["parity_status"]["residuals"]) == [f"ulp_{fmt}"]


def test_a_float_candidate_of_another_precision_fails(tmp_path: Path) -> None:
    @dataclass
    class Wide(RampCandidate):
        def evaluate(self, case: Case, inputs: Mapping[str, Raster]) -> Raster:
            wide: Any = ramp(case, self.bias).astype(np.float64)  # right values, wrong type
            return wide  # type: ignore[no-any-return]

    built = build(tmp_path, "ramp", fmt="f32")
    report = certify(built, tmp_path / "reports", lambda access: Wide(RAMP_BIAS))
    assert {c["outcome"] for s in report["sets"].values() for c in s["cases"]} == {"fail"}


@pytest.mark.parametrize("fmt", ["f16", "f32"])
def test_the_ulp_distance_follows_the_bit_patterns(fmt: str) -> None:
    dtype = DTYPES[fmt]
    bits = np.dtype({"f16": "<u2", "f32": "<u4"}[fmt])
    quiet, payload = (
        np.array([n], bits).view(dtype)[0]
        for n in {"f16": (0x7E00, 0x7E01), "f32": (0x7FC00000, 0x7FC00001)}[fmt]
    )

    def distance(a: Any, b: Any) -> int:
        oracle, candidate = np.array([[[a]]], dtype), np.array([[[b]]], dtype)
        measured = residual(oracle, candidate, fmt)
        assert measured.exact == bool((oracle.view(bits) == candidate.view(bits)).all())
        return measured.histogram[-1][0]

    one, two, zero = dtype.type(1.0), dtype.type(2.0), dtype.type(0.0)
    tiny = np.nextafter(zero, one)  # the smallest subnormal
    assert distance(0.0, -0.0) == 1  # signed zeros are adjacent patterns
    assert distance(one, one) == 0
    assert distance(one, np.nextafter(one, two)) == 1
    assert distance(-tiny, tiny) == 3  # -tiny, -0, +0, +tiny
    assert distance(quiet, payload) == 1  # NaNs compare by their bits, never by value
    assert distance(quiet, quiet) == 0


def test_an_exr_or_png_blob_of_another_type_is_refused(tmp_path: Path) -> None:
    data = exr_bytes(np.full((4, 4, 1), 0.5, np.float16), tmp_path)
    with pytest.raises(RasterError, match="EXR has 16-bit samples, f32 needs 32"):
        decode(RasterSpec(4, "f32", "linear", 1), "exr", data)
    assert decode(RasterSpec(4, "f16", "linear", 1), "exr", data).dtype == np.float16
    document = build_case_document()
    document["output"] = {**document["output"], "format": "f32"}
    document["oracle"] = {**document["oracle"], "encoding": "png"}
    with pytest.raises(BatchError, match="a png blob cannot hold f32 samples"):
        parse_case(document, "held_out")


# --- the §6 matrix -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("matrix", "message"),
    [
        ({"meshes": ["sphere", "cube"]}, "needs 3 distinct meshes"),
        ({"resolutions": [8, 16]}, "needs 3 distinct resolutions"),
        ({"resolutions": [4, 8, 32]}, "matrix resolution 32 is outside"),
        ({"seeds": [0]}, "needs 2 distinct seeds"),
        (
            {"parameter_sets": [s for s in RAMP_MATRIX["parameter_sets"] if s["role"] != "recipe"]},
            "at least one recipe parameter set",
        ),
        ({"parameter_sets": RAMP_MATRIX["parameter_sets"][:3]}, "exactly 2 boundary sets"),
        (
            {
                "parameter_sets": [
                    *RAMP_MATRIX["parameter_sets"][:3],
                    {"id": "boundary-high", "role": "boundary", "params": {"a": 30, "b": 30}},
                ]
            },
            "boundary set boundary-high puts no ranged parameter at an end",
        ),
        (
            {
                "parameter_sets": [
                    *RAMP_MATRIX["parameter_sets"],
                    {"id": "recipe-copy", "role": "recipe", "params": {"a": 1.0, "b": 2}},
                ]
            },
            "two matrix parameter sets have the same values",
        ),
    ],
)
def test_a_matrix_without_decision_222s_counts_is_refused(
    tmp_path: Path, matrix: dict[str, Any], message: str
) -> None:
    built = build(tmp_path, "ramp", calibration=RAMP_CAL, matrix={**RAMP_MATRIX, **matrix})
    with pytest.raises(BatchError, match=message):
        load_batch(built.batch_path)


def test_calibration_must_cover_every_cell_of_the_matrix(tmp_path: Path) -> None:
    missing = "cal-hat-8-boundary-high-9"
    built = build(tmp_path, "ramp", calibration=[c for c in RAMP_CAL if c["case_id"] != missing])
    with pytest.raises(
        BatchError,
        match=r"leaves 1 cell.*first mesh hat, resolution 8, parameter set boundary-high, seed 9",
    ):
        load_batch(built.batch_path)


def test_a_batch_without_a_matrix_is_refused(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp")
    batch = json.loads(built.batch_path.read_text(encoding="utf-8"))
    del batch["matrix"]
    built.batch_path.write_text(json.dumps(batch), encoding="utf-8")
    with pytest.raises(BatchError, match=r"batch\.matrix"):
        load_batch(built.batch_path)


# --- the command line --------------------------------------------------------------------------


def _cli(*argv: str) -> tuple[int, Any, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, json.loads(out.getvalue()) if out.getvalue() else None, err.getvalue()


def test_the_cli_validates_fits_certifies_and_reports(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp")
    batch = str(built.batch_path)
    common = ("--reports", str(tmp_path / "reports"), "--ledger", str(built.ledger))
    store = ("--store", str(built.store.root))
    module = "tests.parity.proc_cert.test_proc_cert_harness"

    code, out, _ = _cli("validate", batch)
    assert code == 0 and out["matrix"]["cells"] == 72 and out["held_out"]["cases"] == 2

    code, out, _ = _cli("fit", batch, "--fitter", f"{module}:fit_ramp", *common, *store)
    assert code == 0 and out["calibration_cases"] == 72 and out["held_out_spent_on"] is None
    candidate = out["candidate_sha256"]
    assert Ledger(built.ledger).read() == {}  # fitting spends nothing

    code, out, _ = _cli("report", batch, *common)
    assert (code, out) == (1, {"report": None, "held_out_spent_on": None})

    code, out, _ = _cli("certify", batch, "--fitter", f"{module}:fit_ramp", *common, *store)
    assert code == 0 and out["outcome"] == "exact" and out["candidate_sha256"] == candidate

    code, out, _ = _cli("report", batch, *common)
    assert code == 0 and out["certified"] is True and out["held_out_spent_on"] == candidate

    code, _, err = _cli("certify", batch, "--fitter", f"{module}:fit_memoriser", *common, *store)
    assert code == 2 and "HeldOutSpent" in err


def test_the_cli_refuses_a_broken_batch_and_a_bad_fitter(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp")
    assert built.held_out_path is not None
    built.held_out_path.write_bytes(built.held_out_path.read_bytes() + b" ")
    code, _, err = _cli("validate", str(built.batch_path))
    assert code == 2 and "pins" in err
    fixed = build(tmp_path / "again", "ramp")
    common = ("--reports", str(tmp_path / "reports"), "--ledger", str(fixed.ledger), "--no-store")
    code, _, err = _cli("fit", str(fixed.batch_path), "--fitter", "no_colon", *common)
    assert code == 2 and "module:callable" in err


def test_the_cli_runs_as_a_module(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp")
    result = subprocess.run(
        [sys.executable, "-m", "tools.parity.proc_cert", "validate", str(built.batch_path)],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["asset"] == "synthetic/affine-ramp"
