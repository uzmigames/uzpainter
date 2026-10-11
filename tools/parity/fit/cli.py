"""Tier 0 stability and fits command (`parity/FITS.md`).

Run from the repository root on the owner's machine (the private store must exist):

- `python -m tools.parity.fit run [--fit NAME ...]` compares the recordings of every Tier 0
  golden, runs the fits (all, or the named ones), writes `parity/semantics/<file>.json` and
  `parity/reports/phase0/tier0-stability.md`;
- `python -m tools.parity.fit check [--fit NAME ...]` re-runs the fits and checks that every
  published residual is reproduced exactly.

Both read the goldens of the current envelope (`parity/envelopes/registry.json`, decision 037).
A fit published against an older envelope's build is not checked against the current one until
`check` reproduces it there and `run` republishes it; the current envelope's drift report lists
it under `fits_to_recheck` (`recheck_problems`).

Exit status: 0 done / reproduced, 1 store unavailable or a difference found, 2 usage error.
"""

from __future__ import annotations

import argparse
import importlib
import json
import platform
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np

from tools.parity.envelope.registry import current_envelope, load_registry
from tools.parity.fit.common import SEMANTICS_DIR, Context, publishable_problems
from tools.parity.fit.oracle import OracleUnavailable, load
from tools.parity.fit.report import render
from tools.parity.fit.stability import GoldenStability, golden_stability
from tools.parity.schemas import load_json
from tools.parity.store.store import locate

# fit module (tools/parity/fit/<name>.py) -> its file under parity/semantics/
FITS = {
    "blend": "blend-modes.json",
    "profile": "evaluator-profile.json",
    "srgb": "srgb-transfer.json",
    "normal": "height-to-normal.json",
    "resample": "resampling.json",
    "ao": "ao-mixed.json",
}
REPORT = "parity/reports/phase0/tier0-stability.md"


def fit_module(name: str) -> ModuleType:
    return importlib.import_module(f"tools.parity.fit.{name}")


def manifests(ctx: Context) -> list[Path]:
    return sorted(ctx.manifests.glob("*/*.json"))


def stability_of_all(ctx: Context) -> tuple[list[GoldenStability], dict[str, str]]:
    results, domains = [], {}
    for path in manifests(ctx):
        golden = load(ctx.store, path)
        results.append(golden_stability(golden, ctx.repository))
        domains[golden.golden_id] = str(golden.manifest.get("domain", ""))
    return results, domains


def dump(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2) + "\n"


def commit(repository: Path) -> str:
    """The checked-out commit, read from `.git` without running git."""
    head = (repository / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    if not head.startswith("ref: "):
        return head[:7]
    ref = head[5:]
    loose = repository / ".git" / ref
    if loose.is_file():
        return loose.read_text(encoding="utf-8").strip()[:7]
    packed = repository / ".git" / "packed-refs"
    for line in packed.read_text(encoding="utf-8").splitlines() if packed.is_file() else []:
        if line.endswith(" " + ref):
            return line.split()[0][:7]
    return "unknown"


def published(repository: Path) -> dict[str, dict[str, Any]]:
    folder = repository / SEMANTICS_DIR
    documents = {}
    for file in FITS.values():
        if (folder / file).is_file():
            documents[file] = load_json(folder / file)
    return documents


def run(ctx: Context, names: Sequence[str]) -> int:
    folder = ctx.repository / SEMANTICS_DIR
    for name in names:
        module = fit_module(name)
        if FITS[name] != module.FILE:
            raise ValueError(f"{name}: FILE {module.FILE} is not {FITS[name]}")
        document = module.fit(ctx)
        problems = publishable_problems(document)
        if problems:
            print(f"{module.FILE}: not publishable: {problems[:3]}", file=sys.stderr)
            return 1
        (folder / module.FILE).write_text(dump(document), encoding="utf-8", newline="\n")
        print(f"wrote {SEMANTICS_DIR}/{module.FILE}")
    stability, domains = stability_of_all(ctx)
    meta = {
        "machine": platform.node(),
        "Python": platform.python_version(),
        "numpy": np.__version__,
        "repository commit": commit(ctx.repository) + " plus the working tree of this task",
        "Painter build of the oracles": f"`{ctx.painter_build}`",
        "manifests": f"`{ctx.manifests.relative_to(ctx.repository).as_posix()}/`",
    }
    text = render(stability, domains, published(ctx.repository), meta)
    (ctx.repository / REPORT).write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {REPORT}")
    return 0


def reproduction_problems(ctx: Context, name: str) -> list[str]:
    """Differences between a fresh run of fit `name` and its published file."""
    module = fit_module(name)
    path = ctx.repository / SEMANTICS_DIR / module.FILE
    if not path.is_file():
        return [f"{module.FILE}: not published"]
    fresh = json.loads(dump(module.fit(ctx)))
    old = load_json(path)
    if fresh == old:
        return []
    problems = []
    if old["painter_build_id"] != fresh["painter_build_id"]:
        problems.append(
            f"{module.FILE}: published against Painter {old['painter_build_id']}, re-checked "
            f"against envelope {ctx.envelope['envelope_id']}"
        )
    old_entries = {e["entry_id"]: e for e in old["entries"]}
    for e in fresh["entries"]:
        before = old_entries.pop(e["entry_id"], None)
        if before is None:
            problems.append(f"{module.FILE}: entry {e['entry_id']} not published")
        elif before != e:
            problems.append(f"{module.FILE}: entry {e['entry_id']} differs from the published one")
    problems += [f"{module.FILE}: published entry {k} not reproduced" for k in old_entries]
    return problems or [f"{module.FILE}: document header differs"]


def recheck_problems(repository: Path) -> list[str]:
    """Published fits not checked against the current envelope and not listed for re-check.

    A fit names the Painter build its residuals were measured on. A build of no registered
    envelope is an error; an older envelope's build must appear in the current envelope's drift
    report `fits_to_recheck`, so it is never counted as checked against the current build."""
    registry = load_registry(repository)
    current = current_envelope(repository)
    builds = {e["painter_build"] for e in registry["envelopes"]}
    drift = current["drift_report"]
    listed = (
        {f["semantics"] for f in load_json(repository / drift)["fits_to_recheck"]}
        if drift
        else set()
    )
    problems = []
    for path in sorted((repository / SEMANTICS_DIR).glob("*.json")):
        build = load_json(path)["painter_build_id"]
        relative = path.relative_to(repository).as_posix()
        if build not in builds:
            problems.append(f"{relative}: Painter build {build} is no registered envelope's")
        elif build != current["painter_build"] and relative not in listed:
            problems.append(
                f"{relative}: published against {build}, neither checked against the current "
                f"envelope {current['envelope_id']} nor listed in its fits_to_recheck"
            )
    return problems


def check(ctx: Context, names: Sequence[str]) -> int:
    problems = [p for name in names for p in reproduction_problems(ctx, name)]
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f"reproduced: {', '.join(names)}")
    return 1 if problems else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.fit", description=__doc__)
    parser.add_argument("command", choices=("run", "check"))
    parser.add_argument("--fit", action="append", choices=tuple(FITS), help="limit to these fits")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository root")
    args = parser.parse_args(argv)
    store = locate()
    if store is None:
        print("oracle_unavailable: no private oracle store on this machine", file=sys.stderr)
        return 1
    ctx = Context(store, args.repo)
    names = tuple(args.fit or FITS)
    try:
        return run(ctx, names) if args.command == "run" else check(ctx, names)
    except OracleUnavailable as error:
        print(f"oracle_unavailable: {error}", file=sys.stderr)
        return 1
