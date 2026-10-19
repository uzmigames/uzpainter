"""`python -m tools.parity.proc_cert`: validate, fit, certify and report (decision 303).

    validate BATCH                         load and check the batch; nothing is fitted
    fit      BATCH --fitter M:F --reports D   fit behind the fence and print the candidate's
                                           fingerprint; the held-out set is not spent
    certify  BATCH --fitter M:F --reports D   fit, then certify on both sets: spends the held-out
                                           set on the candidate and writes the report
    report   BATCH --reports D             print the report and the ledger entry of the batch;
                                           a report whose batch, domain, matrix, case lists or
                                           candidate is not the current batch's and the ledger's
                                           spend is refused (exit 2), never shown as certified

`--store` names the private store (default: this machine's, `UZP_PARITY_STORE`); `--no-store`
runs without one, so every case is `oracle_unavailable`. `--ledger` defaults to the committed
`parity/reports/phase3/held-out-ledger.json`. Output is JSON on stdout.

Exit codes: 0 done (certify: the asset is exact); 1 certify or report found no exact asset or no
report; 2 refused (a batch, fence, spend or ledger refusal).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tools.parity.proc_cert.batch import BatchError, load_batch
from tools.parity.proc_cert.harness import (
    CandidateChanged,
    CertificationRun,
    FitRefused,
    HeldOutSpent,
    StaleReport,
)
from tools.parity.proc_cert.ledger import DEFAULT_LEDGER, Ledger, LedgerError
from tools.parity.store.store import OracleStore, StoreError, locate

# Refusals, and a batch, store or ledger path that does not open or parse (JSON errors are
# ValueErrors).
REFUSALS = (
    BatchError,
    FitRefused,
    HeldOutSpent,
    CandidateChanged,
    StaleReport,
    LedgerError,
    StoreError,
    OSError,
    ValueError,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.parity.proc_cert",
        description="Procedural calibration and held-out certification (decisions 222, 303).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="load and check a batch")
    validate.add_argument("batch", type=Path)
    for name, text in (
        ("fit", "fit on the calibration set and print the candidate's fingerprint"),
        ("certify", "fit, then certify on both sets (spends the held-out set)"),
        ("report", "print the batch's report and ledger entry"),
    ):
        command = commands.add_parser(name, help=text)
        command.add_argument("batch", type=Path)
        if name != "report":
            command.add_argument("--fitter", required=True, help="module:callable")
        command.add_argument("--reports", type=Path, required=True, help="reports directory")
        command.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
        if name != "report":
            store = command.add_mutually_exclusive_group()
            store.add_argument("--store", type=Path, help="the private store's root")
            store.add_argument("--no-store", action="store_true", help="run without a store")
    return parser


def _store(args: argparse.Namespace) -> OracleStore | None:
    if getattr(args, "no_store", False):
        return None
    if getattr(args, "store", None) is not None:
        return OracleStore.open(args.store)
    return locate()


def _print(document: Any) -> None:
    sys.stdout.write(json.dumps(document, sort_keys=True, indent=2) + "\n")


def _summary(report: dict[str, Any], path: Path) -> dict[str, Any]:
    return {
        "report": str(path),
        "asset": report.get("asset"),
        "outcome": report.get("outcome"),
        "certified": report.get("certified"),
        "candidate_sha256": report.get("candidate_sha256"),
        "parity_status": report.get("parity_status"),
        "counts": {name: one.get("counts") for name, one in report.get("sets", {}).items()},
    }


def _run(args: argparse.Namespace) -> int:
    if args.command == "validate":
        batch = load_batch(args.batch)
        _print(
            {
                "asset": batch.asset,
                "asset_version": batch.asset_version,
                "batch_sha256": batch.sha256,
                "domain_sha256": batch.domain.sha256(),
                "matrix": batch.matrix.summary(),
                **{
                    which.name: {
                        "corpus_id": which.corpus_id,
                        "cases_sha256": which.sha256,
                        "cases": len(batch.cases(which)),
                    }
                    for which in (batch.calibration, batch.held_out)
                },
            }
        )
        return 0
    ledger = Ledger(args.ledger)
    run = CertificationRun(
        args.batch, _store(args) if args.command != "report" else None, args.reports, ledger
    )
    if args.command == "report":
        spent_on = ledger.spent_on(run.batch.held_out.sha256)
        stored = run.stored_report()  # StaleReport unless its identity is the current batch's
        if stored is None:
            _print({"report": None, "held_out_spent_on": spent_on})
            return 1
        _print({**_summary(stored, run.report_path()), "held_out_spent_on": spent_on})
        return 0 if stored.get("certified") is True else 1
    fit = run.fit(run.import_fitter(args.fitter))
    if args.command == "fit":
        _print(
            {
                "asset": run.batch.asset,
                "candidate_sha256": fit.candidate_sha256,
                "calibration_cases": fit.calibration_cases,
                "calibration_cases_unavailable": fit.calibration_unavailable,
                "held_out_spent_on": ledger.spent_on(run.batch.held_out.sha256),
            }
        )
        return 0
    report = run.certify(fit)
    _print(_summary(report, run.report_path()))
    return 0 if report["certified"] is True else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except REFUSALS as error:
        sys.stderr.write(f"refused: {type(error).__name__}: {error}\n")
        return 2
