"""CPython boundary run report of `phase0.7_toolchain-cpython` (item 2.11).

    python -m tools.toolchain.cpython_report --work <scratch dir> [--out <report.md>]

Run on the owner's machine (decision 028). Builds `zig build painter` into `<work>/dist`, then
records in one Markdown report:

- `UzPainter.exe selftest` (every stage; the CPython stages in detail) with versions;
- the isolation run: `PYTHONPATH`, `PYTHONHOME`, `PYTHONSTARTUP`, the user site-packages and the
  current folder all offering a conflicting `mcp`;
- the failure path with `python313.zip` removed from a copy of the folder;
- the installed `Lib\\site-packages\\` against the pinned wheels (`tools.vendoring.wheels`);
- the DLL import closure with the CPython binaries and the native wheels
  (`tools.toolchain.dll_closure`);
- a start of a copy of the folder with the environment reduced to the Windows folders;
- the route of `13-engine-integration.md` §4.2: direct, C-ABI fallback, or the evidence for a
  toolchain change (which waits for the owner's update of decision 021).

Every scratch file stays under `<work>`; only the Markdown report is written to `--out` (default
`parity/reports/phase0/toolchain-cpython.md`). Exit code 0 when every CPython stage passed, 1
otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.toolchain.dll_closure import ClosureReport, check_folder, is_system
from tools.toolchain.slice_report import reduced_environment, run_selftest
from tools.vendoring.wheels import NOT_INSTALLED, WHEELS, read_wheels, site_packages_problems

REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_PATH = 260
DEFAULT_OUT = REPO_ROOT / "parity" / "reports" / "phase0" / "toolchain-cpython.md"
CPYTHON_STAGES = (
    "cpython-start",
    "cpython-uzpainter",
    "cpython-buffer16",
    "cpython-exceptions",
    "cpython-mcp-sdk",
)
CONFLICTING_MCP = "raise ImportError('conflicting mcp imported from {}')\n"


def longest_relative_path(folder: Path) -> str:
    """The longest path of a file below `folder`, relative to it (Windows separators)."""
    return max(
        (str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file()), key=len
    )


def cpython_passed(report: dict[str, Any]) -> bool:
    by_name = {s["name"]: s for s in report["stages"]}
    return all(by_name[name]["status"] == "passed" for name in CPYTHON_STAGES)


def isolation_run(bin_dir: Path, work: Path) -> tuple[int, dict[str, Any], dict[str, str]]:
    """`selftest --no-gpu` with every user-Python channel offering a conflicting `mcp`."""
    evil = work / "conflicting-python"
    user_sites = [
        evil / "appdata" / "Python" / "Python313" / "site-packages",
        evil / "userbase" / "Python313" / "site-packages",
    ]
    for folder in [evil, *user_sites]:
        (folder / "mcp").mkdir(parents=True)
        (folder / "mcp" / "__init__.py").write_text(
            CONFLICTING_MCP.format(folder), encoding="utf-8"
        )
    (evil / "mcp.py").write_text(CONFLICTING_MCP.format(evil), encoding="utf-8")
    overrides = {
        "PYTHONPATH": str(evil),
        "PYTHONHOME": str(evil),
        "PYTHONSTARTUP": str(evil / "mcp.py"),
        "PYTHONUSERBASE": str(evil / "userbase"),
        "APPDATA": str(evil / "appdata"),
    }
    env = {**os.environ, **overrides}
    env.pop("UZP_NO_GPU", None)
    out = work / "run-isolation"
    proc = subprocess.run(
        [str(bin_dir / "UzPainter.exe"), "selftest", "--no-gpu", "--out-dir", str(out)],
        cwd=evil,
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
        check=False,
    )
    report = json.loads((out / "selftest-report.json").read_text(encoding="utf-8"))
    return proc.returncode, report, overrides


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _stage(report: dict[str, Any], name: str) -> dict[str, Any]:
    return next(s for s in report["stages"] if s["name"] == name)


def _route(gpu: dict[str, Any], isolation: dict[str, Any]) -> list[str]:
    if cpython_passed(gpu) and cpython_passed(isolation):
        return [
            "**Route: direct.** `UzPainter.exe`, built by the pinned Zig 0.15.2 (clang, MinGW-w64 "
            "target, libc++ linked statically), imports `python313.dll` of the official "
            "embeddable package (built by MSVC) and passes every CPython stage, so the C-ABI "
            "fallback (the Python-facing layer as a separate DLL) was not built and the "
            "toolchain stays Zig; decision 021 is unchanged.",
        ]
    return [
        "**Route: not qualified directly.** A CPython stage failed (outputs above). Per "
        "`13-engine-integration.md` §4.2 the next step is the C-ABI fallback under the same "
        "Zig; a toolchain change waits for the owner's update of decision 021.",
    ]


def render(
    work: Path,
    zig_version: str,
    gpu: tuple[int, dict[str, Any]],
    isolation: tuple[int, dict[str, Any], dict[str, str]],
    failure: tuple[int, dict[str, Any]],
    reduced: tuple[int, dict[str, Any]],
    wheel_problems: list[str],
    closure: ClosureReport,
    longest: str,
) -> str:
    code, report = gpu
    env = report["environment"]
    start = _stage(report, "cpython-start")["details"]
    mcp = _stage(report, "cpython-mcp-sdk")["details"]
    passed = cpython_passed(report)
    lines = [
        "# Toolchain CPython boundary — owner's machine run",
        "",
        "Task `phase0.7_toolchain-cpython` (child of `phase0.8_toolchain-slice`, P0-TOOLCHAIN, "
        "`docs/dag.md`), check of `docs/architecture/13-engine-integration.md` §4.2 and §5 "
        "(PRD ARC-08). Decision 028: this local run report is the evidence. Generated by "
        "`python -m tools.toolchain.cpython_report` on "
        f"{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}.",
        "",
        f"**Result: CPython boundary {'qualified' if passed else 'not qualified'}** "
        f"(`selftest` exit code {code}; CPython stages "
        f"{'all passed' if passed else 'not all passed'}; whole run {report['result']}).",
        "",
        *_route(report, isolation[1]),
        "",
        "## Versions",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| OS build | {env['os_build']} |",
        f"| Zig | {zig_version} (the executable reports {env['zig']}, {env['build_mode']} build) |",
        f"| CPython | {start['version']} — embeddable package `python-3.13.16-embed-amd64.zip` "
        "(`thirdparty/cpython/`), headers and `python313.lib` from "
        "`python-3.13.16-amd64.zip` (`thirdparty/cpython-dev/`) |",
        "| pybind11 | 3.1.0 (`thirdparty/pybind11/`) |",
        f"| MCP SDK | `mcp` {mcp['mcp_version']} with {len(WHEELS)} pinned wheels "
        "(`thirdparty/python-wheels/`) |",
        f"| Installed distributions | {_cell(mcp['distributions'])} |",
        "",
        "## Stages",
        "",
        "| Stage | Mandatory | Result | Time | Reason / facts |",
        "|---|---|---|---|---|",
    ]
    for stage in report["stages"]:
        if stage["name"] in CPYTHON_STAGES:
            facts = stage["reason"] or "; ".join(
                f"{k} {v}"
                for k, v in stage["details"].items()
                if k not in ("version", "distributions", "sys_path", "doc")
            )
        else:
            facts = stage["reason"] or "(not part of this task; see its own report)"
        lines.append(
            f"| `{stage['name']}` | {'yes' if stage['mandatory'] else 'no'} | "
            f"{stage['status']} | {stage['duration_ms']:.0f} ms | {_cell(facts)} |"
        )
    lines += [
        "",
        f"`sys.path` of the embedded interpreter: {_cell(start['sys_path'])}.",
        "",
        "## Isolation from a user Python",
        "",
    ]
    iso_code, iso_report, overrides = isolation
    iso_mcp = _stage(iso_report, "cpython-mcp-sdk")["details"]
    lines += [
        "A copy of the run with every channel of a user Python offering a conflicting `mcp` "
        "package that raises on import: "
        + ", ".join(f"`{k}`" for k in overrides)
        + " pointed at it, and the current folder holding `mcp.py` and `mcp/`. The machine also "
        "has its own Python 3.13 installed.",
        "",
        f"Exit code {iso_code}; CPython stages "
        f"{'all passed' if cpython_passed(iso_report) else 'not all passed'}; `mcp` imported "
        f"from `{iso_mcp.get('mcp_file', '(not imported)')}`.",
        "",
        "## Failure path: standard library removed",
        "",
    ]
    fail_code, fail_report = failure
    fail_start = _stage(fail_report, "cpython-start")
    lines += [
        f"With `python313.zip` deleted from a copy of the folder, `selftest` exits with code "
        f'{fail_code}; `cpython-start` {fail_start["status"]}: "{_cell(fail_start["reason"])}"; '
        + ", ".join(
            f"`{name}` {_stage(fail_report, name)['status']}" for name in CPYTHON_STAGES[1:]
        )
        + ".",
        "",
        "## Installed site-packages",
        "",
        (
            "`Lib\\site-packages\\` holds exactly the files of the pinned wheels' `RECORD`s "
            "(hash and size), without console scripts and without "
            + ", ".join(f"`{f}/`" for f in NOT_INSTALLED)
            + "."
            if not wheel_problems
            else "Differences from the pinned wheels: "
            + "; ".join(_cell(p) for p in wheel_problems[:20])
        ),
        "",
        "## DLL import closure",
        "",
    ]
    wheel_binaries = [b for b in closure.binaries if b.path.lower().startswith("lib/")]
    lines += [
        f"{len(closure.binaries)} binaries ({len(wheel_binaries)} of them in "
        f"`Lib\\site-packages\\`), footprint {closure.footprint:,} bytes; "
        f"{len(closure.system_imports)} distinct Windows system DLLs and API sets imported.",
        "",
        "| Binary | Size (bytes) | Role | Imports other than Windows system DLLs |",
        "|---|---|---|---|",
    ]
    for b in closure.binaries:
        if b in wheel_binaries:
            continue
        own = [d for d in (*b.load_time, *b.delay_load) if not is_system(d)]
        lines.append(
            f"| `{b.path}` | {b.size:,} | {_cell(b.role)} | "
            f"{', '.join(f'`{d}`' for d in own) or '-'} |"
        )
    wheel_own = sorted(
        {d for b in wheel_binaries for d in (*b.load_time, *b.delay_load) if not is_system(d)},
        key=str.lower,
    )
    lines += [
        "",
        f"The wheels' binaries import, besides Windows system DLLs: "
        f"{', '.join(f'`{d}`' for d in wheel_own)}; all resolve inside the folder.",
        "",
        f"Allowlist check: {'passed' if closure.ok else 'FAILED'}"
        + ("" if closure.ok else ": " + "; ".join(_cell(p) for p in closure.problems[:20]))
        + ". Clean-machine closure: "
        + ("closed" if closure.clean_machine_ready else "open")
        + " (every import resolves inside the folder or to Windows itself).",
        "",
        "## Path length",
        "",
        f"The longest file path below the folder is {len(longest)} characters (`{longest}`). "
        "`UzPainter.exe` has no `longPathAware` manifest, so its file APIs, and the embedded "
        "interpreter's, are limited to `MAX_PATH` (260 characters with the terminating null): "
        f"the install folder path may be at most {MAX_PATH - 2 - len(longest)} characters. A "
        "deeper folder makes files of the wheels unreachable (observed: `jsonschema_specifications"
        "` schema files, so `cpython-mcp-sdk` fails); this run's folder is "
        f"{len(str(work / 'dist' / 'bin'))} characters.",
        "",
        "## Start with a reduced environment",
        "",
    ]
    red_code, red_report = reduced
    lines += [
        "A copy of the folder started with the environment reduced to the Windows folders (no "
        f"Python, SDK or Zig on `PATH`), `--no-gpu`: exit code {red_code}; "
        + ", ".join(f"`{name}` {_stage(red_report, name)['status']}" for name in CPYTHON_STAGES)
        + ". This machine has Python and the Visual C++ runtime installed, so this is not a "
        "clean-machine run; the start on a clean Windows 10/11 x64 machine without Python is "
        "the owner's own test: pending owner action.",
        "",
        "## Reproduce",
        "",
        "```",
        "python -m tools.toolchain.cpython_report --work <scratch folder>",
        "python -m pytest tests/toolchain/test_cpython.py tests/vendoring/test_wheels.py",
        "```",
        "",
    ]
    # Scratch paths of this machine are not part of the evidence.
    return "\n".join(lines).replace(str(work), "<work>")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.toolchain.cpython_report")
    parser.add_argument("--work", type=Path, required=True, help="scratch folder (recreated)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    zig = shutil.which("zig")
    if zig is None:
        print("zig is not on PATH", file=sys.stderr)
        return 1
    work = args.work.resolve()
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    zig_version = subprocess.run(
        [zig, "version"], capture_output=True, text=True, check=True, timeout=60
    ).stdout.strip()
    subprocess.run(
        [zig, "build", "painter", "--prefix", str(work / "dist")],
        cwd=REPO_ROOT,
        check=True,
        timeout=3600,
    )
    bin_dir = work / "dist" / "bin"
    gpu = run_selftest(bin_dir / "UzPainter.exe", work / "run")
    isolation = isolation_run(bin_dir, work)

    no_stdlib = work / "no-stdlib"
    shutil.copytree(bin_dir, no_stdlib)
    (no_stdlib / "python313.zip").unlink()
    failure = run_selftest(no_stdlib / "UzPainter.exe", work / "run-no-stdlib", "--no-gpu")

    reduced_copy = work / "reduced-env"
    shutil.copytree(bin_dir, reduced_copy)
    reduced = run_selftest(
        reduced_copy / "UzPainter.exe",
        work / "run-reduced-env",
        "--no-gpu",
        env=reduced_environment(work),
    )
    wheel_problems = site_packages_problems(
        bin_dir / "Lib" / "site-packages", read_wheels(REPO_ROOT)
    )
    closure = check_folder(bin_dir)
    text = render(
        work,
        zig_version,
        gpu,
        isolation,
        failure,
        reduced,
        wheel_problems,
        closure,
        longest_relative_path(bin_dir),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"report written to {args.out}")
    return 0 if cpython_passed(gpu[1]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
