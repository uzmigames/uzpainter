"""Where certification reports and batches live, and the repository guard's rules for them
(phase3.1_proc-backend-seam item 2.7, decision 303 §6, `tools/parity/proc_cert/report.py`).

The batches and oracles are the synthetic families of `test_proc_cert_harness.py` (authored
formulas, not Painter assets); their oracles live in a temporary private store.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from tests.parity.proc_cert.test_proc_cert_harness import CAL_DEFAULTS, build, certify, fit_ramp
from tools.parity.guard.guard import PATH_RULES
from tools.parity.proc_cert import cli
from tools.parity.proc_cert.report import (
    DEFAULT_BATCHES,
    DEFAULT_REPORTS,
    batch_problems,
    report_problems,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def guard(path: str, document: Any) -> tuple[str, list[str]]:
    """The schema of the guard's first rule for `path`, and its problems with `document`."""
    rule = next(r for r in PATH_RULES if r[0].match(path))
    data = json.dumps(document).encode()
    return rule[1], rule[2](path, document, data, cast(Any, None))


def test_reports_and_batches_default_to_the_committed_phase3_folders() -> None:
    assert DEFAULT_REPORTS.relative_to(REPO_ROOT).as_posix() == "parity/reports/phase3/proc-cert"
    assert DEFAULT_BATCHES.relative_to(REPO_ROOT).as_posix() == "parity/manifests/phase3/proc-cert"
    for command in ("fit", "certify", "report"):
        args = cli._parser().parse_args(
            [command, "batch.json"] + (["--fitter", "m:f"] if command != "report" else [])
        )
        assert args.reports == DEFAULT_REPORTS


def test_a_certified_report_and_its_batch_pass_the_guard(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp")
    reports = tmp_path / "reports"
    run = built.run(reports)
    report = run.certify(run.fit(fit_ramp))
    assert report["certified"] is True
    relative = run.report_path().relative_to(reports).as_posix()
    assert relative.startswith("synthetic__affine-ramp@1/")
    path = f"parity/reports/phase3/proc-cert/{relative}"
    schema, problems = guard(path, json.loads(run.report_path().read_bytes()))
    assert schema.startswith("procedural certification report") and problems == []

    batch_dir = built.batch_path.parent
    for file in sorted(batch_dir.rglob("*.json")):
        inside = file.relative_to(batch_dir).as_posix()
        name = f"parity/manifests/phase3/proc-cert/synthetic/affine-ramp/{inside}"
        schema, problems = guard(name, json.loads(file.read_bytes()))
        assert schema.startswith("procedural certification batch") and problems == [], name


def test_a_residual_report_is_committable_and_still_a_failure(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp", perturb=CAL_DEFAULTS)
    report = certify(built, tmp_path / "reports", fit_ramp)
    assert (report["outcome"], report["certified"]) == ("fail", False)
    assert report_problems(report) == []


def test_a_report_that_names_a_path_or_breaks_its_shape_is_refused(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp")
    report = certify(built, tmp_path / "reports", fit_ramp)
    with_path = json.loads(json.dumps(report))
    with_path["sets"]["held_out"]["cases"][0]["reason"] = "read E:/UzmiGames/store/blob"
    assert any("names a file path" in p for p in report_problems(with_path))
    extra = {**report, "store": "anywhere"}
    assert report_problems(extra) and "a report holds exactly" in report_problems(extra)[0]
    claimed = {**report, "outcome": "fail"}
    assert "certified is true exactly when the outcome is exact" in report_problems(claimed)
    reserved = {"schema": report["schema"], "candidate_sha256": report["candidate_sha256"]}
    assert report_problems({**reserved, "outcome": "reserved"}) == []
    assert report_problems({**reserved, "outcome": "reserved", "x": 1})


def test_a_batch_file_that_is_not_a_batch_is_refused(tmp_path: Path) -> None:
    built = build(tmp_path, "ramp")
    batch = json.loads(built.batch_path.read_bytes())
    assert batch_problems(batch) == []
    escaped = {**batch, "held_out": {**batch["held_out"], "path": "../elsewhere/cases.json"}}
    assert batch_problems(escaped) == [
        "batch.held_out: a relative path inside the batch and its pin"
    ]
    assert batch_problems({**batch, "domain": {}})
    assert batch_problems({"schema": "golden-public"}) == [
        "schema is not uzpainter/parity/proc-cert-batch/1 or uzpainter/parity/proc-cert-cases/1"
    ]


def test_a_report_named_outside_the_layout_has_no_rule() -> None:
    for path in (
        "parity/reports/phase3/proc-cert/report.json",
        "parity/reports/phase3/proc-cert/synthetic__affine-ramp@1/abc.json",
    ):
        assert not any(
            r[1].startswith("procedural certification report")
            for r in PATH_RULES
            if r[0].match(path)
        )
