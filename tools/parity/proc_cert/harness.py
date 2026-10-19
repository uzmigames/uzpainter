"""Fit on the calibration set, then certify on both sets (decisions 222 and 303).

    run = CertificationRun(batch_path, store, reports_dir, Ledger(ledger_path))
    fit = run.fit(fitter)        # the fitter sees the calibration set only, behind the fence
    report = run.certify(fit)    # evaluates every case behind the fence, then compares

- `fit` loads the calibration oracles and inputs into read-only arrays, then raises the fence
  over the private store, the held-out root, the reports directory and the ledger and calls the
  fitter. A fitter that reaches any of them (or starts a process) is refused: no candidate
  comes out.
- Every call into candidate code runs behind the same fence: the fitter, the candidate's
  `fingerprint` (at fit and again at certify) and every `evaluate`. Each evaluated output is
  copied into an owned, read-only array before the next call.
- `certify` re-checks the batch pins and the candidate's fingerprint, refuses a held-out set
  already spent on another candidate (in the ledger or in the report), evaluates the candidate
  on every case, spends the held-out set on the candidate (the ledger entry, then the report
  file, created first as a reservation), then loads the oracles and compares.
- A case is `exact` only when every value equals its oracle. A missing, unreadable or wrong
  oracle is `oracle_unavailable`. Any non-zero difference is `residual`: a candidate exception
  for the owner, never a pass. The asset is `exact` only when every case of both sets is.
- The report holds hashes and residual statistics only. It is written in one canonical form, so
  the same batch and candidate give the same bytes.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from tools.parity.proc_cert.batch import (
    Batch,
    BatchError,
    BlobRef,
    Case,
    CaseSet,
    RasterSpec,
    canonical,
    load_batch,
)
from tools.parity.proc_cert.fence import Fence, HeldOutAccessError, fenced
from tools.parity.proc_cert.fingerprint import PROJECT_ROOT, FingerprintError, candidate_sha256
from tools.parity.proc_cert.ledger import Ledger
from tools.parity.proc_cert.raster import (
    DecoderMissing,
    Raster,
    RasterError,
    Residual,
    check_candidate,
    decode,
    pooled,
    raster_sha256,
    residual,
)
from tools.parity.store.store import OracleStore

REPORT_SCHEMA = "uzpainter/parity/proc-cert-report/1"
STATEMENT = (
    "exact results on these sampled cases are evidence for the declared domain, not a proof over "
    "every value in it (decision 222); this report certifies no Painter asset by itself"
)

EXACT = "exact"
RESIDUAL = "residual"
FAIL = "fail"
ORACLE_UNAVAILABLE = "oracle_unavailable"


class FitRefused(Exception):
    """The fitter (or the candidate during evaluation) reached a fenced root."""


class HeldOutSpent(Exception):
    """The held-out set was already revealed to a different candidate (decision 222 §2)."""


class CandidateChanged(Exception):
    """The candidate's fingerprint changed between fitting and certification."""


class Candidate(Protocol):
    def fingerprint(self) -> Mapping[str, Any]:
        """JSON data that identifies the candidate: family, code version and every fitted value
        that changes its outputs. The harness binds this declaration to the candidate's class
        and code; it cannot see fitted state the declaration leaves out, so reuse of a spent
        held-out set is refused only as far as this identity is complete."""
        ...

    def evaluate(self, case: Case, inputs: Mapping[str, Raster]) -> Raster:
        """The case's output as the declared integer raster."""
        ...


@dataclass(frozen=True)
class CalibrationCase:
    case: Case
    inputs: Mapping[str, Raster]
    oracle: Raster | None  # None: unavailable (reason says why); fit without it
    reason: str = ""


@dataclass(frozen=True)
class CalibrationAccess:
    """Everything a fitter may see: the domain and the calibration set. No store, no held-out."""

    asset: str
    asset_version: int
    domain: Mapping[str, Any]
    cases: tuple[CalibrationCase, ...]


Fitter = Callable[[CalibrationAccess], Candidate]


@dataclass(frozen=True)
class FitResult:
    batch_sha256: str
    candidate: Candidate
    candidate_sha256: str
    calibration_cases: int
    calibration_unavailable: int  # calibration cases fitted without their oracle
    _run: CertificationRun = field(repr=False)


def _spent_on(path: Path) -> str | None:
    spent: str | None = json.loads(path.read_text(encoding="utf-8")).get("candidate_sha256")
    return spent


def _refuse_if_breached(fence: Fence, what: str) -> None:
    if fence.refused:
        raise FitRefused(f"{what} reached a fenced root: " + "; ".join(sorted(set(fence.refused))))


class CertificationRun:
    def __init__(
        self,
        batch_path: Path,
        store: OracleStore | None,
        reports_dir: Path,
        ledger: Ledger,
        *,
        project_root: Path = PROJECT_ROOT,
    ) -> None:
        self.batch: Batch = load_batch(batch_path)
        self.store = store
        self.reports_dir = reports_dir.resolve()
        self.ledger = ledger
        self.project_root = project_root

    # --- private store -----------------------------------------------------------------------

    def _blob(self, spec: RasterSpec, ref: BlobRef, what: str) -> tuple[Raster | None, str]:
        if self.store is None:
            return None, f"{what} {ref.sha256}: no private store on this machine"
        data = self.store.load(ref.sha256, ref.size_bytes)
        if data is None:
            reason = self.store.resolve(ref.record_id, ref.sha256, ref.size_bytes).reason
            return None, f"{what} {ref.sha256}: {reason or 'unavailable'}"
        try:
            return decode(spec, ref.encoding, data), ""
        except DecoderMissing as error:
            return None, f"{what} {ref.sha256}: {error}"
        except RasterError as error:
            raise BatchError(f"{what} {ref.sha256} is not a {spec}: {error}") from error

    def _inputs(self, case: Case) -> tuple[dict[str, Raster], str]:
        inputs: dict[str, Raster] = {}
        for usage, (spec, ref) in case.inputs.items():
            values, reason = self._blob(spec, ref, f"input {usage}")
            if values is None:
                return {}, reason
            inputs[usage] = values
        return inputs, ""

    def _fence_roots(self) -> list[Path]:
        roots = [self.batch.held_out.root, self.reports_dir, *self.ledger.paths()]
        if self.store is not None:
            roots.append(self.store.root)
        return roots

    def report_path(self) -> Path:
        name = f"{self.batch.asset.replace('/', '__')}@{self.batch.asset_version}"
        return self.reports_dir / name / f"{self.batch.held_out.sha256[:16]}.json"

    def _fingerprint(self, candidate: Candidate, what: str) -> str:
        """The candidate's fingerprint, computed behind the fence (it runs candidate code)."""
        with fenced(self._fence_roots(), f"fingerprinting {self.batch.asset}") as fence:
            try:
                sha = candidate_sha256(candidate, self.project_root)
            except HeldOutAccessError as error:
                raise FitRefused(f"{what} reached a fenced root: {error}") from error
            except FingerprintError as error:
                raise FitRefused(str(error)) from error
        _refuse_if_breached(fence, what)
        return sha

    def import_fitter(self, spec: str) -> Fitter:
        """`module:callable`, imported behind the fence (importing runs the module's code)."""
        module_name, _, attribute = spec.partition(":")
        if not module_name or not attribute:
            raise BatchError(f"fitter {spec!r} is not module:callable")
        with fenced(self._fence_roots(), f"importing {spec}") as fence:
            try:
                fitter = getattr(importlib.import_module(module_name), attribute)
            except HeldOutAccessError as error:
                raise FitRefused(f"importing the fitter reached a fenced root: {error}") from error
        _refuse_if_breached(fence, "importing the fitter")
        if not callable(fitter):
            raise BatchError(f"fitter {spec!r} is not callable")
        result: Fitter = fitter
        return result

    # --- fitting -----------------------------------------------------------------------------

    def fit(self, fitter: Fitter) -> FitResult:
        cases = []
        for case in self.batch.cases(self.batch.calibration):
            inputs, reason = self._inputs(case)
            oracle = None
            if not reason:
                oracle, reason = self._blob(case.output, case.oracle, "oracle")
            cases.append(CalibrationCase(case, inputs, oracle, reason))
        access = CalibrationAccess(
            self.batch.asset,
            self.batch.asset_version,
            json.loads(canonical(self.batch.domain.document)),
            tuple(cases),
        )
        with fenced(self._fence_roots(), f"fitting {self.batch.asset}") as fence:
            try:
                candidate = fitter(access)
            except HeldOutAccessError as error:
                raise FitRefused(f"the fitter reached a fenced root: {error}") from error
        _refuse_if_breached(fence, "the fitter")
        sha = self._fingerprint(candidate, "the candidate's fingerprint")
        unavailable = sum(case.oracle is None for case in cases)
        return FitResult(self.batch.sha256, candidate, sha, len(cases), unavailable, self)

    # --- certification -----------------------------------------------------------------------

    def certify(self, fit: FitResult) -> dict[str, Any]:
        if fit._run is not self:
            raise BatchError("certify takes the FitResult of this run's own fit")
        current = load_batch(self.batch.path)
        if current.sha256 != fit.batch_sha256:
            raise BatchError("batch.json changed after fitting")
        if self._fingerprint(fit.candidate, "the candidate's fingerprint") != fit.candidate_sha256:
            raise CandidateChanged("the candidate's fingerprint changed after fitting")
        self._refuse_spent(self.ledger.spent_on(current.held_out.sha256), fit)
        path = self.report_path()
        if path.is_file():
            self._refuse_spent(_spent_on(path), fit)
        sets = {
            which.name: (which, current.cases(which))
            for which in (current.calibration, current.held_out)
        }
        inputs = {case.case_id: self._inputs(case) for _, cases in sets.values() for case in cases}
        outputs: dict[str, Raster | str] = {}
        with fenced(self._fence_roots(), f"evaluating {current.asset}") as fence:
            for _, cases in sets.values():
                for case in cases:
                    if inputs[case.case_id][1]:
                        continue
                    try:
                        produced = fit.candidate.evaluate(case, inputs[case.case_id][0])
                        # an owned, read-only copy before the next call into the candidate
                        outputs[case.case_id] = check_candidate(case.output, produced)
                    except RasterError as error:
                        outputs[case.case_id] = str(error)
                    except Exception as error:  # fails the case; a fence breach refuses the run
                        outputs[case.case_id] = f"candidate raised {type(error).__name__}: {error}"
        _refuse_if_breached(fence, "the candidate")
        self._reserve(path, fit)
        report = self._report(current, fit, sets, inputs, outputs)
        text = json.dumps(report, sort_keys=True, indent=2) + "\n"
        path.write_text(text, encoding="utf-8", newline="\n")  # the same bytes on every platform
        return report

    def _refuse_spent(self, spent_on: str | None, fit: FitResult) -> None:
        if spent_on is not None and spent_on != fit.candidate_sha256:
            raise HeldOutSpent(
                f"held-out set {self.batch.held_out.sha256} was revealed to candidate "
                f"{spent_on}; record a new held-out set and move these cases to calibration"
            )

    def _reserve(self, path: Path, fit: FitResult) -> None:
        """Spend the held-out set on this candidate before any oracle is loaded, so a run that
        stops before its report still leaves the set spent (created exclusively: of two runs
        racing for one held-out set, the second is refused). The ledger entry comes first: it is
        the durable record, which deleting the report does not undo."""
        self._refuse_spent(self.ledger.spend(self.batch.held_out.sha256, fit.candidate_sha256), fit)
        path.parent.mkdir(parents=True, exist_ok=True)
        reservation = {
            "schema": REPORT_SCHEMA,
            "candidate_sha256": fit.candidate_sha256,
            "outcome": "reserved",
        }
        try:
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(reservation, sort_keys=True, indent=2) + "\n")
        except FileExistsError:
            spent_on = _spent_on(path)
            if spent_on is None:
                raise HeldOutSpent(
                    f"{path} names no candidate; the held-out set is spent"
                ) from None
            self._refuse_spent(spent_on, fit)

    def _case_result(
        self, case: Case, input_reason: str, output: Raster | str | None
    ) -> tuple[dict[str, Any], Residual | None]:
        result: dict[str, Any] = {
            "case_id": case.case_id,
            "oracle_sha256": case.oracle.sha256,
            "candidate_sha256": None,
            "residual": None,
            "reason": "",
        }
        if input_reason:
            return {**result, "outcome": ORACLE_UNAVAILABLE, "reason": input_reason}, None
        oracle, reason = self._blob(case.output, case.oracle, "oracle")
        if isinstance(output, str) or output is None:
            outcome = ORACLE_UNAVAILABLE if oracle is None else FAIL
            return {**result, "outcome": outcome, "reason": reason or str(output)}, None
        result["candidate_sha256"] = raster_sha256(output)
        if oracle is None:
            return {**result, "outcome": ORACLE_UNAVAILABLE, "reason": reason}, None
        measured = residual(oracle, output, case.output.format)
        return {
            **result,
            "outcome": EXACT if measured.exact else RESIDUAL,
            "residual": measured.as_json(),
        }, measured

    def _report(
        self,
        batch: Batch,
        fit: FitResult,
        sets: Mapping[str, tuple[CaseSet, tuple[Case, ...]]],
        inputs: Mapping[str, tuple[dict[str, Raster], str]],
        outputs: Mapping[str, Raster | str],
    ) -> dict[str, Any]:
        measured: list[Residual] = []
        set_reports: dict[str, Any] = {}
        outcomes: list[str] = []
        for name, (which, cases) in sets.items():
            results = []
            for case in cases:
                result, one = self._case_result(
                    case, inputs[case.case_id][1], outputs.get(case.case_id)
                )
                results.append(result)
                if one is not None:
                    measured.append(one)
            counts = {
                outcome: sum(r["outcome"] == outcome for r in results)
                for outcome in (EXACT, RESIDUAL, FAIL, ORACLE_UNAVAILABLE)
            }
            outcomes.extend(r["outcome"] for r in results)
            set_reports[name] = {
                "corpus_id": which.corpus_id,
                "cases_sha256": which.sha256,
                "outcome": _set_outcome([r["outcome"] for r in results]),
                "counts": counts,
                "cases": results,
            }
        outcome = _set_outcome(outcomes)
        if outcome == EXACT:
            status: dict[str, Any] = {"kind": "exact"}
        elif measured and not all(one.exact for one in measured):
            status = {
                "kind": "calibrated",
                "residuals": {unit: one.statistics() for unit, one in pooled(measured).items()},
                "corpus_ids": [batch.calibration.corpus_id, batch.held_out.corpus_id],
            }
        else:
            status = {"kind": "unavailable"}
        return {
            "schema": REPORT_SCHEMA,
            "asset": batch.asset,
            "asset_version": batch.asset_version,
            "batch_sha256": batch.sha256,
            "domain_sha256": batch.domain.sha256(),
            "matrix": batch.matrix.summary(),
            "candidate_sha256": fit.candidate_sha256,
            "outcome": outcome,
            "certified": outcome == EXACT,
            "parity_status": status,
            "sets": set_reports,
            "statement": STATEMENT,
        }


def _set_outcome(outcomes: list[str]) -> str:
    """Exact only when every case is; any residual or failure fails; else unavailable."""
    if all(outcome == EXACT for outcome in outcomes):
        return EXACT
    if any(outcome in (RESIDUAL, FAIL) for outcome in outcomes):
        return FAIL
    return ORACLE_UNAVAILABLE
