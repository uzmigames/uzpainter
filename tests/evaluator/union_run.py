"""The union run of the compositor's Tier 0 golden sets (phase1.14_compositor-core item 3.1).

One command, on the owner's machine (private store, DX12; decision 028):

    python tests/evaluator/union_run.py [--label interim|final]

It runs every Tier 0 golden test of the compositor children (`tests/evaluator/test_compositor_*.py`,
the `backend=gpu` parametrisation of each) twice, in two separate pytest processes, and writes
`parity/reports/phase1/compositor-core.md` (numbers and hashes only).

Inside a run the environment variable `UZP_UNION_RUN` names the pass directory, the hooks of this
module (registered by `tests/evaluator/conftest.py`) keep only the GPU items, and the
children's comparison sites call `observe` (one compared map against one recording, with the
child's own conversion and domain) while `evaluate` (`test_compositor_tile_dag.py`) calls
`note_rasters` (the SHA-256 of every raw channel raster it evaluated). Outside a run both do
nothing. Per comparison the run records the |Δ| statistics (`tools.parity.fit.stats`), the
non-zero |Δ| histogram (so pooled p99 values are exact), the verdict of `tools.parity.verdict`
(r1 the exact target of an unstable golden, decision 032; the exception register) and, per map,
the oracle stability r1 against r2. UzPainter repeatability is the two passes' rasters compared
byte for byte (item 3.2 has its own lane in `test_compositor_core.py`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

if __name__ == "__main__":
    # Run as a script: the repository root is the import root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.oracle import Golden
from tools.parity.fit.stats import abs_differences, difference
from tools.parity.schemas import REGISTER_PATH, load_json
from tools.parity.verdict import Comparison, Outcome, evaluate

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV = "UZP_UNION_RUN"
OBSERVATIONS = "observations.jsonl"
RASTERS = "rasters.jsonl"
OUTCOMES = "outcomes.jsonl"
REPORT = REPO_ROOT / "parity" / "reports" / "phase1" / "compositor-core.md"
# The Tier 0 folders whose goldens record compositor semantics (api-probes and the template
# captures are readbacks, not channel maps).
SEMANTIC_FOLDERS = ("semantics", "semantics-ui")


def run_directory() -> Path | None:
    value = os.environ.get(ENV)
    return Path(value) if value else None


def current_test() -> str:
    return os.environ.get("PYTEST_CURRENT_TEST", "").rsplit(" (", 1)[0]


def append(name: str, record: Mapping[str, Any]) -> None:
    directory = run_directory()
    assert directory is not None
    with (directory / name).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


# ── Observation hooks (no-ops outside a union run) ───────────────────────────


_register: list[Mapping[str, Any]] | None = None
_oracle: dict[tuple[str, str], dict[str, Any]] = {}
_calls: dict[str, int] = defaultdict(int)


def register_entries() -> list[Mapping[str, Any]]:
    global _register
    if _register is None:
        _register = list(load_json(REGISTER_PATH)["entries"])
    return _register


def oracle_stability(golden: Golden, map_name: str) -> dict[str, Any]:
    """r1 against r2 of one map, decoded at native depth (`tools/parity/fit/stability.py`)."""
    key = (golden.golden_id, map_name)
    if key not in _oracle:
        if "r2" not in golden.recordings:
            _oracle[key] = {"compared": False}
        else:
            diff = difference(golden.map("r1", map_name).values, golden.map("r2", map_name).values)
            _oracle[key] = {"compared": True, "stable": diff.equal, "difference": diff.as_dict()}
    return _oracle[key]


def histogram(delta: np.ndarray) -> list[list[float]]:
    """The non-zero |Δ| values with their counts, ascending."""
    nonzero = delta[delta != 0]
    if nonzero.size == 0:
        return []
    values, counts = np.unique(nonzero, return_counts=True)
    return [[float(v), int(c)] for v, c in zip(values, counts, strict=True)]


def observe(
    golden: Golden,
    map_name: str,
    recording: str,
    unit: str,
    ours: np.ndarray,
    theirs: np.ndarray,
    domain: np.ndarray | None = None,
) -> None:
    """Records one comparison of the union run: `ours` (the evaluator's map converted as the
    child compares it) against `theirs` (recording `recording` of `map_name`), over the texels of
    `domain` (all when None). Does nothing outside a union run."""
    if run_directory() is None:
        return
    a = np.asarray(ours)
    b = np.asarray(theirs).reshape(a.shape)
    if a.dtype.kind in "iu" and b.dtype.kind == "f" and np.array_equal(b, np.floor(b)):
        b = b.astype(np.int64)
    if domain is not None:
        domain = np.asarray(domain, np.bool_).reshape(a.shape[:2])
    delta = abs_differences(a, b, domain)
    diff = difference(a, b, domain)
    oracle = oracle_stability(golden, map_name)
    stable = bool(oracle.get("stable", True))
    if diff.equal and stable:
        verdict: dict[str, Any] = {
            "outcome": Outcome.PASS.value,
            "reason": "exact equality",
            "exceptions": [],
        }
    else:
        mask = np.ones(a.shape[:2], np.bool_) if domain is None else domain
        result = evaluate(
            Comparison(
                tier="0",
                domain=str(golden.manifest.get("domain", "")),
                oracle=b[mask].astype(np.float64).ravel().tolist(),
                candidate=a[mask].astype(np.float64).ravel().tolist(),
                oracle_stable=stable,
                exact_target=recording == "r1",
            ),
            register_entries(),
        )
        verdict = {
            "outcome": result.outcome.value,
            "reason": result.reason,
            "exceptions": [f"{e}@{v}" for e, v in result.exceptions_relied_on],
        }
    append(
        OBSERVATIONS,
        {
            "test": current_test(),
            "golden_id": golden.golden_id,
            "record_sha256": golden.record_sha256,
            "map": map_name,
            "recording": recording,
            "unit": unit,
            "domain": "all" if domain is None else f"{int(domain.sum())} texels",
            "difference": diff.as_dict(),
            "histogram": histogram(delta),
            "oracle": oracle,
            "verdict": verdict,
        },
    )


def note_rasters(result: Mapping[str, Any], output: str) -> None:
    """Records the SHA-256 of every raw raster of one `evaluate` call (its order within the
    test identifies it across passes) and the adapter the executable reported."""
    if run_directory() is None:
        return
    test = current_test()
    call = _calls[test]
    _calls[test] += 1
    rasters = {
        channel: hashlib.sha256((Path(result["_dir"]) / entry["file"]).read_bytes()).hexdigest()
        for channel, entry in sorted(result["channels"].items())
        if "file" in entry
    }
    adapters = [
        line.split("adapter ", 1)[1].strip() for line in output.splitlines() if "adapter " in line
    ]
    append(
        RASTERS,
        {
            "test": test,
            "call": call,
            "rasters": rasters,
            "adapter": adapters[0] if adapters else None,
        },
    )


# ── Pytest hooks (registered by tests/evaluator/conftest.py) ─────────────────


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """In a union run keep only the GPU parametrisation of the children's Tier 0 tests."""
    if run_directory() is None:
        return
    keep: list[pytest.Item] = []
    drop: list[pytest.Item] = []
    for item in items:
        params = getattr(getattr(item, "callspec", None), "params", {})
        file = Path(str(item.fspath)).name
        in_children = file.startswith("test_compositor_") and file != "test_compositor_core.py"
        (keep if in_children and params.get("backend") == "gpu" else drop).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
    items[:] = keep


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if run_directory() is None:
        return
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        message = ""
        if report.outcome != "passed":
            message = str(report.longrepr).strip().splitlines()[-1][:300] if report.longrepr else ""
        append(OUTCOMES, {"test": report.nodeid, "outcome": report.outcome, "message": message})


# ── Aggregation and report ───────────────────────────────────────────────────


def read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


@dataclass
class Pool:
    """|Δ| pooled over several compared maps of one unit."""

    maps: int = 0
    total: int = 0
    texels: int = 0
    affected: int = 0
    differing: int = 0
    worst: float = 0.0
    hist: dict[float, int] = field(default_factory=lambda: defaultdict(int))

    def add(self, record: Mapping[str, Any]) -> None:
        d = record["difference"]
        self.maps += 1
        self.total += int(d["total"])
        self.texels += int(d["texels"])
        self.affected += int(d["affected_texels"])
        self.differing += int(d["differing"])
        self.worst = max(self.worst, float(d["max"]))
        for value, count in record["histogram"]:
            self.hist[float(value)] += int(count)

    @property
    def mean(self) -> float:
        if any(math.isinf(v) for v in self.hist):
            return math.inf
        return math.fsum(v * c for v, c in self.hist.items()) / self.total if self.total else 0.0

    @property
    def p99(self) -> float:
        """Nearest-rank 99th percentile of every pooled |Δ| (zeros included)."""
        rank = math.ceil(0.99 * self.total)
        zeros = self.total - sum(self.hist.values())
        if rank <= zeros:
            return 0.0
        seen = zeros
        for value in sorted(self.hist):
            seen += self.hist[value]
            if seen >= rank:
                return value
        return self.worst


def number(value: float) -> str:
    if math.isinf(value):
        return "inf"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6g}"


def percent(part: int, whole: int) -> str:
    return f"{100.0 * part / whole:.4f}" if whole else "0"


def summarise(passes: Sequence[Path]) -> dict[str, Any]:
    """Everything the report states, from the pass directories."""
    first = passes[0]
    observations = read_lines(first / OBSERVATIONS)
    outcomes = {p.name: read_lines(p / OUTCOMES) for p in passes}
    rasters = {p.name: read_lines(p / RASTERS) for p in passes}
    keys = {
        p.name: {
            (r["test"], r["call"], c): h for r in rasters[p.name] for c, h in r["rasters"].items()
        }
        for p in passes
    }
    reference = keys[first.name]
    repeat_total = len(reference)
    repeat_same = sum(
        1 for k, h in reference.items() if all(keys[p.name].get(k) == h for p in passes[1:])
    )
    repeat_diff = sorted(
        f"{k[0]} call {k[1]} {k[2]}"
        for k, h in reference.items()
        if any(keys[p.name].get(k) != h for p in passes[1:])
    )
    observed_b = {
        (o["golden_id"], o["map"], o["recording"], o["test"]): o["difference"]
        for o in read_lines(passes[-1] / OBSERVATIONS)
    }
    stats_repeat = sum(
        1
        for o in observations
        if observed_b.get((o["golden_id"], o["map"], o["recording"], o["test"])) == o["difference"]
    )
    return {
        "observations": observations,
        "outcomes": outcomes,
        "repeat_total": repeat_total,
        "repeat_same": repeat_same,
        "repeat_diff": repeat_diff,
        "stats_repeat": stats_repeat,
        "adapters": sorted({r["adapter"] for r in rasters[first.name] if r["adapter"]}),
    }


def unobserved_goldens(observed: Iterable[str]) -> list[str]:
    root = manifest_root(current_envelope()) / "tier0"
    found = set(observed)
    missing = []
    for folder in SEMANTIC_FOLDERS:
        for path in sorted((root / folder).glob("*.json")):
            golden_id = str(load_json(path)["golden_id"])
            if golden_id not in found:
                missing.append(golden_id)
    return missing


def render_report(summary: Mapping[str, Any], header: Mapping[str, str]) -> str:
    observations: list[dict[str, Any]] = summary["observations"]
    by_golden: dict[tuple[str, str], dict[str, Pool]] = defaultdict(lambda: defaultdict(Pool))
    oracle_maps: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    verdicts: dict[str, int] = defaultdict(int)
    record_sha: dict[str, str] = {}
    for o in observations:
        by_golden[(o["golden_id"], o["unit"])][o["recording"]].add(o)
        oracle_maps[o["golden_id"]][o["map"]] = o["oracle"]
        verdicts[o["verdict"]["outcome"]] += 1
        record_sha[o["golden_id"]] = o["record_sha256"]
    pass_names = list(summary["outcomes"])
    outcome_counts = {
        name: {
            k: sum(1 for r in summary["outcomes"][name] if r["outcome"] == k)
            for k in ("passed", "failed", "skipped")
        }
        for name in pass_names
    }
    maps = {(o["golden_id"], o["map"]) for o in observations}
    exact_r1 = sum(
        1 for o in observations if o["recording"] == "r1" and o["difference"]["differing"] == 0
    )
    r1 = sum(1 for o in observations if o["recording"] == "r1")
    unstable = sum(
        1 for m in oracle_maps.values() for s in m.values() if s.get("compared") and not s["stable"]
    )
    lines = [
        "# Compositor core: union of the Tier 0 golden sets (`phase1.14_compositor-core`)",
        "",
        f"Run: **{header['label']}**, {header['date']}, "
        f"commit `{header['commit']}`{header['dirty']}, "
        f"envelope `{header['envelope']}`, backend DX12 (`gpu`), adapter {header['adapter']}. "
        f"Command: `python tests/evaluator/union_run.py --label {header['label']}` "
        f"({header['passes']} passes in separate processes, {header['durations']}). Numbers and "
        "hashes only (`docs/licensing-and-clean-room.md`).",
        "",
        "The union is every Tier 0 golden test of the compositor children "
        "(`tests/evaluator/test_compositor_*.py`, `backend=gpu`), each comparing with its own "
        "conversion and domain (`tests/evaluator/union_run.py`). |Δ| is in the unit named per row "
        "(16-bit export codes or float values); mean and p99 are pooled over every compared value "
        "of the row (p99 nearest-rank, exact from the |Δ| histograms); differing texels have at "
        "least one differing component. Verdicts follow `tools/parity/verdict.py` (an unstable "
        "golden's exact target is r1, decision 032; r2 passes only through the exception "
        "register).",
        "",
        "## Headline",
        "",
        f"- Goldens compared: {len({g for g, _ in by_golden})}; maps: {len(maps)}; comparisons: "
        f"{len(observations)} ({r1} against r1, {len(observations) - r1} against r2).",
        f"- Against r1: {exact_r1} of {r1} maps exact.",
        "- Verdicts: " + ", ".join(f"{k} {v}" for k, v in sorted(verdicts.items())) + ".",
        f"- Oracle stability: {unstable} of {sum(len(m) for m in oracle_maps.values())} compared "
        "maps differ between r1 and r2.",
        f"- UzPainter repeatability: {summary['repeat_same']} of {summary['repeat_total']} "
        "evaluated channel rasters byte-identical across the passes; "
        f"{summary['stats_repeat']} of {len(observations)} comparison statistics identical.",
        "- Tests per pass: "
        + "; ".join(
            f"{name}: {c['passed']} passed, {c['failed']} failed, {c['skipped']} skipped"
            for name, c in outcome_counts.items()
        )
        + ".",
        "",
        "## Per golden",
        "",
        "| Golden | Unit | Maps | vs r1: max, mean, p99 | r1 differing texels (%) "
        "| vs r2: max, mean, p99 | r2 differing texels (%) | Oracle r1 vs r2 | Record SHA-256 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for (golden_id, unit), pools in sorted(by_golden.items()):
        cells = []
        for recording in ("r1", "r2"):
            pool = pools.get(recording)
            if pool is None or pool.maps == 0:
                cells += ["not compared", "-"]
                continue
            cells.append(f"{number(pool.worst)}, {number(pool.mean)}, {number(pool.p99)}")
            cells.append(
                f"{pool.affected} of {pool.texels} ({percent(pool.affected, pool.texels)})"
            )
        golden_maps = oracle_maps[golden_id]
        diverging = [s for s in golden_maps.values() if s.get("compared") and not s["stable"]]
        if not any(s.get("compared") for s in golden_maps.values()):
            oracle = "one recording"
        elif diverging:
            worst = max(float(s["difference"]["max"]) for s in diverging)
            oracle = f"unstable: {len(diverging)} of {len(golden_maps)} maps, max {number(worst)}"
        else:
            oracle = f"stable ({len(golden_maps)} maps)"
        maps_count = max(p.maps for p in pools.values())
        lines.append(
            f"| `{golden_id}` | {unit} | {maps_count} | "
            + " | ".join(cells)
            + f" | {oracle} | `{record_sha[golden_id][:16]}` |"
        )
    residual = [o for o in observations if o["difference"]["differing"]]
    lines += ["", "## Maps with a difference", ""]
    if not residual:
        lines.append("None: every compared map equals its recording.")
    else:
        lines += [
            "| Golden | Map | Recording | max, mean, p99 | Differing texels (%) | Verdict "
            "| Oracle |",
            "|---|---|---|---|---|---|---|",
        ]
        for o in sorted(residual, key=lambda o: (o["golden_id"], o["map"], o["recording"])):
            d = o["difference"]
            verdict = o["verdict"]["outcome"] + (
                f" ({', '.join(o['verdict']['exceptions'])})" if o["verdict"]["exceptions"] else ""
            )
            oracle = "stable" if o["oracle"].get("stable", True) else "unstable"
            affected, texels = int(d["affected_texels"]), int(d["texels"])
            stats = ", ".join(number(float(d[k])) for k in ("max", "mean", "p99"))
            lines.append(
                f"| `{o['golden_id']}` | {o['map']} | {o['recording']} | {stats} | "
                f"{affected} of {texels} ({percent(affected, texels)}) | {verdict} | {oracle} |"
            )
    failing = [r for r in summary["outcomes"][pass_names[0]] if r["outcome"] != "passed"]
    lines += ["", "## Tests not passed (first pass)", ""]
    if not failing:
        lines.append("None.")
    else:
        lines.append(
            "A failing test stops at its first failing comparison, so the maps after it are not "
            "observed; a skipped test observed nothing."
        )
        lines.append("")
        for r in failing:
            lines.append(f"- `{r['test']}`: {r['outcome']}. {r['message']}")
    lines += ["", "## Repeatability differences", ""]
    lines.append(
        "None."
        if not summary["repeat_diff"]
        else "\n".join(f"- {k}" for k in summary["repeat_diff"])
    )
    missing = unobserved_goldens(g for g, _ in by_golden)
    lines += [
        "",
        "## Current-envelope semantic goldens no child test compares",
        "",
        "Recorded goldens of `tier0/semantics` and `tier0/semantics-ui` outside the union (not yet "
        "owned by a comparison, or outside the compositor):",
        "",
    ]
    lines += [f"- `{g}`" for g in missing] if missing else ["None."]
    return "\n".join(lines) + "\n"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--label", default="interim", help="interim or final (named in the report)")
    parser.add_argument("--work", type=Path, default=None, help="pass directories (default: temp)")
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--passes", type=int, default=2)
    parser.add_argument("pytest_args", nargs="*", help="extra pytest arguments (e.g. -k blend)")
    args = parser.parse_args(argv)
    from tools.parity.store.store import locate

    if locate() is None or os.environ.get("UZP_NO_GPU") == "1":
        print("union run: needs the private oracle store and a DX12 adapter (decision 028)")
        return 2
    work = args.work or Path(os.environ.get("TEMP", "/tmp")) / f"uzp-union-{int(time.time())}"
    passes = [work / f"pass-{chr(ord('a') + i)}" for i in range(args.passes)]
    durations = []
    for directory in passes:
        directory.mkdir(parents=True, exist_ok=False)
        start = time.monotonic()
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/evaluator",
                "-q",
                "-p",
                "no:cacheprovider",
                *args.pytest_args,
            ],
            cwd=REPO_ROOT,
            env={**os.environ, ENV: str(directory)},
            check=False,
        )
        durations.append(f"{directory.name} {time.monotonic() - start:.0f} s")
    summary = summarise(passes)
    status = git("status", "--porcelain")
    header = {
        "label": args.label,
        "date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "commit": git("rev-parse", "--short=12", "HEAD"),
        "dirty": " (uncommitted changes)" if status else "",
        "envelope": str(current_envelope()["envelope_id"]),
        "adapter": ", ".join(summary["adapters"]) or "not reported",
        "passes": str(len(passes)),
        "durations": ", ".join(durations),
    }
    args.report.write_text(render_report(summary, header), encoding="utf-8")
    print(f"union run: {len(summary['observations'])} comparisons; report {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
