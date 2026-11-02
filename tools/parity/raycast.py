"""Cross-backend ray-cast report of phase3.2_vulkan-ray-tracing (items 2.12, 3.4; decision 373).

`uzp-render-tests ray-cast-fixtures <dir>` traces every ray-cast fixture
(`src/render/ray_query.h` `RayCastFixtures`) on DX12 and on Vulkan, twice each, and writes
`<dir>/ray-cast-raw.json`: per fixture and backend the repeatability, the comparison with the CPU
reference, and the DX12/Vulkan comparison (per field the rays that differ, the largest |delta| of
the distance and the barycentrics, every differing ray with its fields). `build_report` turns it
into the committed report `parity/reports/<phase>/ray-cast.json`: the adapter and driver names
become SHA-256 digests and the kernel source's digest is added, so the report holds numbers,
identifiers and digests only (`parity/GUARD.md`). `report_problems` is the guard's check.

    python -m tools.parity.raycast <raw.json> --out parity/reports/phase3/ray-cast.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_SCHEMA = "uzpainter/parity/ray-cast-raw/1"
REPORT_SCHEMA = "uzpainter/parity/ray-cast-report/1"
KERNEL = Path("src/render/shaders/ray_cast.hlsl")
BACKENDS = ("dx12", "vulkan")
FIELDS = (
    "hit",
    "instance_id",
    "primitive_id",
    "geometry_index",
    "instance_index",
    "barycentrics",
    "t",
)
KINDS = ("interior", "miss", "edge", "vertex", "boundary", "grazing")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def kernel_sha256(repo_root: Path = REPO_ROOT) -> str:
    """SHA-256 of the ray-cast kernel source with LF line ends (checkouts may convert them)."""
    data = (repo_root / KERNEL).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _passed(fixture: dict[str, Any]) -> bool:
    runs_ok = all(
        run["repeatable"] and run["strict_differing"] == 0 and run["shared_wrong"] == 0
        for run in fixture["runs"]
    )
    return runs_ok and fixture["cross_backend"]["differing_rays"] == 0


def build_report(raw: dict[str, Any], kernel_digest: str, task: str) -> dict[str, Any]:
    """The committed report of a raw `ray-cast-fixtures` run."""
    if raw.get("schema") != RAW_SCHEMA:
        raise ValueError(f"not a {RAW_SCHEMA} document")
    backends = [
        {
            "backend": b["backend"],
            "adapter_sha256": sha256_text(b["adapter"]),
            "driver_sha256": sha256_text(b["driver"]),
        }
        for b in raw["backends"]
    ]
    fixtures = raw["fixtures"]
    return {
        "schema": REPORT_SCHEMA,
        "task": task,
        "kernel_sha256": kernel_digest,
        "tolerance": raw["tolerance"],
        "backends": backends,
        "fixtures": fixtures,
        "outcome": "pass" if fixtures and all(_passed(f) for f in fixtures) else "fail",
    }


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _diff_problems(where: str, diff: Any, rays: int) -> list[str]:
    if not isinstance(diff, dict):
        return [f"{where}: not an object"]
    keys = {"differing_rays", *FIELDS, "max_delta_t", "max_delta_barycentric", "differences"}
    problems = [f"{where}: unexpected or missing keys"] if set(diff) != keys else []
    for key in ("differing_rays", *FIELDS):
        if not _count(diff.get(key)):
            problems.append(f"{where}/{key}: not a count")
    for key in ("max_delta_t", "max_delta_barycentric"):
        if not _number(diff.get(key)):
            problems.append(f"{where}/{key}: not a non-negative number")
    differences = diff.get("differences")
    if not isinstance(differences, list):
        return [*problems, f"{where}/differences: not a list"]
    if _count(diff.get("differing_rays")) and len(differences) != diff["differing_rays"]:
        problems.append(f"{where}: differing_rays is not the number of differences")
    seen: set[int] = set()
    totals = dict.fromkeys(FIELDS, 0)
    for i, item in enumerate(differences):
        if not isinstance(item, dict) or set(item) != {"ray", "fields"} or not _count(item["ray"]):
            problems.append(f"{where}/differences/{i}: not {{ray, fields}}")
            continue
        if item["ray"] >= rays or item["ray"] in seen:
            problems.append(f"{where}/differences/{i}: ray outside the fixture or listed twice")
        seen.add(item["ray"])
        fields = item["fields"]
        if (
            not isinstance(fields, list)
            or not fields
            or any(f not in FIELDS for f in fields)
            or len(set(fields)) != len(fields)
        ):
            problems.append(f"{where}/differences/{i}/fields: not distinct field names")
            continue
        for field in fields:
            totals[field] += 1
    for field in FIELDS:
        if _count(diff.get(field)) and diff[field] != totals[field]:
            problems.append(f"{where}/{field}: not the number of rays listed with it")
    return problems


def report_problems(document: Any) -> list[str]:
    """Why `document` is not a ray-cast report: numbers, identifiers and digests only."""
    if not isinstance(document, dict) or document.get("schema") != REPORT_SCHEMA:
        return [f"schema is not {REPORT_SCHEMA}"]
    keys = {"schema", "task", "kernel_sha256", "tolerance", "backends", "fixtures", "outcome"}
    problems: list[str] = []
    if set(document) != keys:
        problems.append(f"keys are not {sorted(keys)}")
    if not isinstance(document.get("task"), str) or not IDENTIFIER.fullmatch(document["task"]):
        problems.append("task: not an identifier")
    if not isinstance(document.get("kernel_sha256"), str) or not SHA256.fullmatch(
        document["kernel_sha256"]
    ):
        problems.append("kernel_sha256: not a SHA-256 digest")
    if not _number(document.get("tolerance")):
        problems.append("tolerance: not a non-negative number")
    if document.get("outcome") not in ("pass", "fail"):
        problems.append("outcome: not pass or fail")
    backends = document.get("backends")
    if not isinstance(backends, list) or [b.get("backend") for b in backends] != list(BACKENDS):
        problems.append("backends: not dx12 then vulkan")
    else:
        for b in backends:
            if set(b) != {"backend", "adapter_sha256", "driver_sha256"} or not all(
                isinstance(b[k], str) and SHA256.fullmatch(b[k])
                for k in ("adapter_sha256", "driver_sha256")
            ):
                problems.append(f"backends/{b['backend']}: not backend, adapter and driver digests")
    fixtures = document.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        return [*problems, "fixtures: not a non-empty list"]
    fixture_keys = {"id", "rays", "triangles", "instances", "kinds", "runs", "cross_backend"}
    run_keys = {
        "backend",
        "repeatable",
        "strict_differing",
        "shared_rays",
        "shared_wrong",
        "versus_cpu",
    }
    for f in fixtures:
        if not isinstance(f, dict) or set(f) != fixture_keys:
            problems.append("fixture: unexpected or missing keys")
            continue
        where = f"fixtures/{f['id']}"
        if not isinstance(f["id"], str) or not IDENTIFIER.fullmatch(f["id"]):
            problems.append(f"{where}: id is not an identifier")
        for key in ("rays", "triangles", "instances"):
            if not _count(f[key]):
                problems.append(f"{where}/{key}: not a count")
        kinds = f["kinds"]
        if (
            not isinstance(kinds, dict)
            or set(kinds) != set(KINDS)
            or not all(_count(v) for v in kinds.values())
        ):
            problems.append(f"{where}/kinds: not a count per ray kind")
        elif _count(f["rays"]) and sum(kinds.values()) != f["rays"]:
            problems.append(f"{where}/kinds: do not add up to the rays")
        runs = f["runs"]
        if not isinstance(runs, list) or [r.get("backend") for r in runs] != list(BACKENDS):
            problems.append(f"{where}/runs: not dx12 then vulkan")
            continue
        for r in runs:
            if set(r) != run_keys or not isinstance(r["repeatable"], bool):
                problems.append(f"{where}/runs/{r.get('backend')}: unexpected keys")
                continue
            for key in ("strict_differing", "shared_rays", "shared_wrong"):
                if not _count(r[key]):
                    problems.append(f"{where}/runs/{r['backend']}/{key}: not a count")
            if isinstance(kinds, dict) and all(_count(kinds.get(k)) for k in KINDS):
                strict = kinds["interior"] + kinds["miss"]
                shared = kinds["edge"] + kinds["vertex"]
                if not (
                    _count(r["strict_differing"])
                    and r["strict_differing"] <= strict
                    and r["shared_rays"] == shared
                    and _count(r["shared_wrong"])
                    and r["shared_wrong"] <= shared
                ):
                    problems.append(f"{where}/runs/{r['backend']}: summaries outside the ray kinds")
            problems += _diff_problems(
                f"{where}/runs/{r['backend']}/versus_cpu", r["versus_cpu"], f["rays"]
            )
        problems += _diff_problems(f"{where}/cross_backend", f["cross_backend"], f["rays"])
    if not problems and document["outcome"] != (
        "pass" if all(_passed(f) for f in fixtures) else "fail"
    ):
        problems.append("outcome: does not follow from the fixtures")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("raw", type=Path, help="ray-cast-raw.json of uzp-render-tests")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--task", default="phase3.2_vulkan-ray-tracing")
    args = parser.parse_args(argv)
    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    report = build_report(raw, kernel_sha256(), args.task)
    problems = report_problems(report)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, allow_nan=False) + "\n"
    args.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"{args.out}: {report['outcome']}, {len(report['fixtures'])} fixtures")
    return 0 if report["outcome"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
