"""Tier 0 stability and fits command (`parity/FITS.md`).

Run from the repository root on the owner's machine (the private store must exist):

- `python -m tools.parity.fit run [--fit NAME ...]` compares the recordings of every Tier 0
  golden, runs the fits (all, or the named ones), writes `parity/semantics/<file>.json` and
  `parity/reports/phase0/tier0-stability.md`;
- `python -m tools.parity.fit check [--fit NAME ...]` re-runs the fits and checks that every
  published residual is reproduced exactly.

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

from tools.parity.fit.common import (
    MANIFESTS,
    PAINTER_BUILD,
    SEMANTICS_DIR,
    Context,
    publishable_problems,
)
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


def manifests(repository: Path) -> list[Path]:
    return sorted((repository / MANIFESTS).glob("*/*.json"))


def stability_of_all(ctx: Context) -> tuple[list[GoldenStability], dict[str, str]]:
    results, domains = [], {}
    for path in manifests(ctx.repository):
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
        "Painter build of the oracles": f"`{PAINTER_BUILD}`",
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
    old_entries = {e["entry_id"]: e for e in old["entries"]}
    for e in fresh["entries"]:
        before = old_entries.pop(e["entry_id"], None)
        if before is None:
            problems.append(f"{module.FILE}: entry {e['entry_id']} not published")
        elif before != e:
            problems.append(f"{module.FILE}: entry {e['entry_id']} differs from the published one")
    problems += [f"{module.FILE}: published entry {k} not reproduced" for k in old_entries]
    return problems or [f"{module.FILE}: document header differs"]


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
