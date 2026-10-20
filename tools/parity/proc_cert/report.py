"""Where procedural certification reports live and what a committed one may hold (decision 303
§6, phase3.1_proc-backend-seam item 2.7).

Reports are written under `parity/reports/phase3/proc-cert/` by default (`DEFAULT_REPORTS`), one
file per asset and held-out pin: `<family>__<id>@<version>/<first 16 hex digits of the pin>.json`
(`CertificationRun.report_path`). They hold hashes, integer residual statistics and case
outcomes only, so they can be committed; `report_problems` is the repository guard's rule for
them. A reservation (a certification that stopped after spending its held-out set) holds the
candidate's fingerprint only.

Committed batches live under `parity/manifests/phase3/proc-cert/` (`DEFAULT_BATCHES`):
`batch.json` and its two case lists, which name every oracle and input by hash; the bytes stay in
the private store. `batch_problems` is the guard's rule for those files.
"""

from __future__ import annotations

import re
from typing import Any

from tools.parity.proc_cert.batch import (
    BATCH_SCHEMA,
    CASES_SCHEMA,
    SETS,
    BatchError,
    Domain,
    parse_case,
    parse_matrix,
)
from tools.parity.proc_cert.fingerprint import PROJECT_ROOT
from tools.parity.proc_cert.harness import (
    EXACT,
    FAIL,
    ORACLE_UNAVAILABLE,
    REPORT_SCHEMA,
    RESIDUAL,
    STATEMENT,
)

DEFAULT_REPORTS = PROJECT_ROOT / "parity" / "reports" / "phase3" / "proc-cert"
DEFAULT_BATCHES = PROJECT_ROOT / "parity" / "manifests" / "phase3" / "proc-cert"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
# A drive letter, a UNC prefix or a root: a report names no file of any machine.
_PATH = re.compile(r"(?:^|[\s:'\"(])(?:[A-Za-z]:[\\/]|\\\\|/[A-Za-z0-9_.-]+/)")
OUTCOMES = (EXACT, RESIDUAL, FAIL, ORACLE_UNAVAILABLE)
REPORT_KEYS = {
    "schema",
    "asset",
    "asset_version",
    "batch_sha256",
    "domain_sha256",
    "matrix",
    "candidate_sha256",
    "outcome",
    "certified",
    "parity_status",
    "sets",
    "statement",
}
CASE_KEYS = {"case_id", "oracle_sha256", "candidate_sha256", "residual", "reason", "outcome"}


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256.match(value))


def _case_problems(where: str, case: Any) -> list[str]:
    if not isinstance(case, dict) or set(case) != CASE_KEYS:
        return [f"{where}: a case result has exactly {sorted(CASE_KEYS)}"]
    problems = []
    if case["outcome"] not in OUTCOMES:
        problems.append(f"{where}: outcome {case['outcome']!r}")
    if not _sha(case["oracle_sha256"]):
        problems.append(f"{where}: oracle_sha256")
    if case["candidate_sha256"] is not None and not _sha(case["candidate_sha256"]):
        problems.append(f"{where}: candidate_sha256")
    if not isinstance(case["reason"], str):
        problems.append(f"{where}: reason")
    residual = case["residual"]
    if residual is not None and not (
        isinstance(residual, dict)
        and all(
            isinstance(v, int | float | str) and not isinstance(v, bool) for v in residual.values()
        )
    ):
        problems.append(f"{where}: residual holds numbers and its unit only")
    return problems


def report_problems(document: Any) -> list[str]:
    """Why `document` is not a certification report or reservation fit to commit."""
    if not isinstance(document, dict) or document.get("schema") != REPORT_SCHEMA:
        return [f"schema is not {REPORT_SCHEMA}"]
    if document.get("outcome") == "reserved":
        if set(document) != {"schema", "candidate_sha256", "outcome"}:
            return ["a reservation holds exactly schema, candidate_sha256 and outcome"]
        return [] if _sha(document["candidate_sha256"]) else ["candidate_sha256"]
    if set(document) != REPORT_KEYS:
        return [f"a report holds exactly {sorted(REPORT_KEYS)}"]
    problems = [
        f"{key}: not a SHA-256"
        for key in ("batch_sha256", "domain_sha256", "candidate_sha256")
        if not _sha(document[key])
    ]
    if document["outcome"] not in OUTCOMES or document["outcome"] == RESIDUAL:
        problems.append(f"outcome {document['outcome']!r} is not exact, fail or oracle_unavailable")
    if document["certified"] is not (document["outcome"] == EXACT):
        problems.append("certified is true exactly when the outcome is exact")
    if document["statement"] != STATEMENT:
        problems.append("the statement is not the harness's (sampled cases are no proof)")
    status = document["parity_status"]
    kinds = ("exact", "calibrated", "unavailable")
    if not isinstance(status, dict) or status.get("kind") not in kinds:
        problems.append("parity_status.kind is exact, calibrated or unavailable")
    sets = document["sets"]
    if not isinstance(sets, dict) or set(sets) != set(SETS):
        problems.append(f"sets are exactly {list(SETS)}")
    else:
        for name, one in sets.items():
            if not isinstance(one, dict) or not _sha(one.get("cases_sha256")):
                problems.append(f"sets.{name}: cases_sha256")
                continue
            for case in one.get("cases", []):
                problems.extend(_case_problems(f"sets.{name}", case))
    problems.extend(
        f"names a file path: {text!r}" for text in _strings(document) if _PATH.search(text)
    )
    return problems


def batch_problems(document: Any) -> list[str]:
    """Why `document` is not a committed batch file: `batch.json` (the asset, the domain, the §6
    matrix and both case lists pinned by SHA-256) or a case list (cases naming oracles and inputs
    by hash). The batch's cross-file checks run when it loads (`load_batch`)."""
    if not isinstance(document, dict):
        return ["a batch file is an object"]
    try:
        if document.get("schema") == BATCH_SCHEMA:
            Domain(document.get("domain"))
            parse_matrix(document.get("matrix"))
            problems = []
            for name in SETS:
                entry = document.get(name)
                if not (
                    isinstance(entry, dict)
                    and _sha(entry.get("sha256"))
                    and isinstance(entry.get("path"), str)
                    and not entry["path"].startswith(("/", "\\"))
                    and ".." not in entry["path"].split("/")
                ):
                    problems.append(f"batch.{name}: a relative path inside the batch and its pin")
            return problems
        if document.get("schema") == CASES_SCHEMA:
            set_name = document.get("set")
            if not isinstance(set_name, str) or set_name not in SETS:
                return [f"set is one of {list(SETS)}"]
            cases = document.get("cases")
            if not isinstance(cases, list) or not cases:
                return ["a case list holds at least one case"]
            for case in cases:
                parse_case(case, set_name)
            return []
    except BatchError as error:
        return [str(error)]
    return [f"schema is not {BATCH_SCHEMA} or {CASES_SCHEMA}"]
