"""DLL import closure of the one-folder distribution (`docs/architecture/13-engine-integration.md`
§5: "DLL count and footprint are measured, not promised").

    python -m tools.toolchain.dll_closure <folder> [--clean-machine] [--json <file>]

Reads the import tables (load-time and delay-load) of every binary in the output folder and
compares them with the allowlist of §5. The allowlist check fails when

- a binary in the folder is neither a listed shipped file (`SHIPPED`, `SHIPPED_PATTERNS`, an
  extension module of the CPython embeddable package beside the executable) nor a Visual C++
  runtime DLL (`VC_RUNTIME`) that some binary in the folder imports ("only as measured"); a
  Windows system DLL (`SYSTEM`) in the folder fails as such;
- an imported DLL is neither in the folder, nor a Windows system DLL, nor a Visual C++ runtime
  DLL; the message names the DLL and the binaries that import it.

Visual C++ runtime DLLs that are imported but not in the folder are allowed by §5 but are not
part of a clean Windows: they are listed as `missing_app_local`, and `--clean-machine` (the
static half of the clean-machine start) fails on them too.

The result lists the binaries with their sizes (count and footprint) and every import. Exit code
0 when the checks pass, 1 otherwise, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tools.toolchain.pe import BINARY_SUFFIXES, MACHINE_AMD64, PEError, read_imports

SECTION = "13-engine-integration.md section 5"

# Files of the distribution (§5 table), by path relative to the folder (lower case).
SHIPPED: dict[str, str] = {
    "uzpainter.exe": "UzPainter build (render core and libc++ linked statically)",
    "d3d12/d3d12core.dll": "Direct3D 12 Agility SDK runtime",
    "d3d12/d3d12sdklayers.dll": "Direct3D 12 Agility SDK debug layer (debug packages only)",
    "dxcompiler.dll": "DirectX Shader Compiler",
    "dxil.dll": "DirectX Shader Compiler validator",
    "embree4.dll": "Embree 4.x release",
    "tbb12.dll": "Embree 4.x release (oneTBB tasking)",
    "python313.dll": "CPython 3.13 embeddable package",
    "python3.dll": "CPython 3.13 embeddable package (stable-ABI forwarder)",
    "libcrypto-3.dll": "CPython 3.13 embeddable package (OpenSSL of `_ssl`, `_hashlib`)",
    "libssl-3.dll": "CPython 3.13 embeddable package (OpenSSL of `_ssl`)",
    "libffi-8.dll": "CPython 3.13 embeddable package (libffi of `_ctypes`)",
    "sqlite3.dll": "CPython 3.13 embeddable package (SQLite of `_sqlite3`)",
}
# Files shipped by pattern (path relative to the folder, lower case; `*` also crosses `/`).
SHIPPED_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "lib/site-packages/*",
        "pinned wheel of the MCP SDK closure (`thirdparty/python-wheels/`)",
    ),
)
# The standard extension modules (`*.pyd`) of the embeddable package sit beside the executable.
EMBEDDABLE_EXTENSION = "CPython 3.13 embeddable package (standard extension module)"

# Visual C++ runtime DLLs: shipped app-local only when an import requires them (§5, "Further
# Visual C++ runtime DLLs ... only as measured"; CPython's embeddable package brings its own
# `vcruntime140*.dll`). A clean Windows has none of them.
VC_RUNTIME: frozenset[str] = frozenset(
    {
        "concrt140.dll",
        "msvcp140.dll",
        "msvcp140_1.dll",
        "msvcp140_2.dll",
        "msvcp140_atomic_wait.dll",
        "msvcp140_codecvt_ids.dll",
        "vcomp140.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "vcruntime140_threads.dll",
    }
)

# DLLs that are part of Windows 10/11 x64 itself: imported, never shipped (§5 "System DLLs").
# API sets (`api-ms-win-*`, `ext-ms-win-*`) are resolved by the loader's API set schema.
# `vulkan-1.dll` comes with the GPU driver and is loaded by volk at run time (§5). The second
# group is imported by the CPython embeddable package and the pinned wheels (measured for
# phase0.7_toolchain-cpython).
SYSTEM: frozenset[str] = frozenset(
    {
        "advapi32.dll",
        "bcrypt.dll",
        "cfgmgr32.dll",
        "comctl32.dll",
        "comdlg32.dll",
        "crypt32.dll",
        "d3d11.dll",
        "d3d12.dll",
        "d3d12core.dll",
        "dbghelp.dll",
        "dwmapi.dll",
        "dxcore.dll",
        "dxgi.dll",
        "gdi32.dll",
        "imm32.dll",
        "kernel32.dll",
        "kernelbase.dll",
        "ntdll.dll",
        "ole32.dll",
        "oleaut32.dll",
        "powrprof.dll",
        "psapi.dll",
        "rpcrt4.dll",
        "setupapi.dll",
        "shcore.dll",
        "shell32.dll",
        "shlwapi.dll",
        "ucrtbase.dll",
        "user32.dll",
        "userenv.dll",
        "uxtheme.dll",
        "version.dll",
        "vulkan-1.dll",
        "winmm.dll",
        "wintrust.dll",
        "ws2_32.dll",
        "xinput1_4.dll",
        # CPython embeddable package and pinned wheels
        "aclui.dll",
        "activeds.dll",
        "bcryptprimitives.dll",
        "credui.dll",
        "dsound.dll",
        "iphlpapi.dll",
        "ktmw32.dll",
        "loadperf.dll",
        "lz32.dll",
        "mpr.dll",
        "msimg32.dll",
        "mswsock.dll",
        "netapi32.dll",
        "ntdsapi.dll",
        "odbc32.dll",
        "oleacc.dll",
        "pdh.dll",
        "propsys.dll",
        "query.dll",
        "rasapi32.dll",
        "secur32.dll",
        "sfc.dll",
        "urlmon.dll",
        "wevtapi.dll",
        "winhttp.dll",
        "wininet.dll",
        "winspool.drv",
        "wtsapi32.dll",
    }
)
SYSTEM_PATTERNS = ("api-ms-win-*.dll", "ext-ms-win-*.dll")


def is_system(name: str) -> bool:
    lower = name.lower()
    return lower in SYSTEM or any(fnmatch.fnmatchcase(lower, p) for p in SYSTEM_PATTERNS)


@dataclass(frozen=True)
class Binary:
    path: str  # relative to the folder, forward slashes
    size: int
    role: str
    load_time: tuple[str, ...]
    delay_load: tuple[str, ...]


@dataclass
class ClosureReport:
    folder: str
    binaries: list[Binary] = field(default_factory=list)
    resolved_in_folder: dict[str, list[str]] = field(default_factory=dict)
    system_imports: dict[str, list[str]] = field(default_factory=dict)
    missing_app_local: dict[str, list[str]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """The folder matches the allowlist."""
        return not self.problems

    @property
    def clean_machine_ready(self) -> bool:
        """Every import resolves inside the folder or to a DLL of Windows itself."""
        return self.ok and not self.missing_app_local

    @property
    def footprint(self) -> int:
        return sum(b.size for b in self.binaries)

    def clean_machine_problems(self) -> list[str]:
        return [
            f"{dll}: Visual C++ runtime DLL imported by {', '.join(users)} is not in the output "
            f"folder; a clean Windows has none ({SECTION}: shipped app-local as measured)"
            for dll, users in self.missing_app_local.items()
        ]


def _binaries(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in BINARY_SUFFIXES
    )


def check_folder(folder: Path) -> ClosureReport:
    """The import closure of every binary under `folder` against the allowlist."""
    report = ClosureReport(folder=str(folder))
    in_folder: set[str] = set()
    importers: dict[str, set[str]] = {}
    for path in _binaries(folder):
        rel = path.relative_to(folder).as_posix()
        try:
            parsed = read_imports(path)
        except PEError as error:
            report.problems.append(f"{rel}: not a readable PE32+ image ({error})")
            continue
        if parsed.machine != MACHINE_AMD64:
            report.problems.append(f"{rel}: machine 0x{parsed.machine:04x} is not x64")
        name = path.name.lower()
        pattern_role = next(
            (
                role
                for pattern, role in SHIPPED_PATTERNS
                if fnmatch.fnmatchcase(rel.lower(), pattern)
            ),
            None,
        )
        if rel.lower() in SHIPPED:
            role = SHIPPED[rel.lower()]
        elif pattern_role is not None:
            role = pattern_role
        elif "/" not in rel and name.endswith(".pyd"):
            role = EMBEDDABLE_EXTENSION
        elif name in VC_RUNTIME:
            role = "Visual C++ runtime, app-local"
        elif is_system(name):
            role = "Windows system DLL"
            report.problems.append(
                f"{rel}: Windows system DLL in the output folder ({SECTION}: system DLLs are "
                "never shipped)"
            )
        else:
            role = "not on the allowlist"
            report.problems.append(
                f"{rel}: binary in the output folder is not on the allowlist of {SECTION}"
            )
        report.binaries.append(
            Binary(rel, path.stat().st_size, role, parsed.load_time, parsed.delay_load)
        )
        in_folder.add(name)
        for dll in (*parsed.load_time, *parsed.delay_load):
            importers.setdefault(dll.lower(), set()).add(rel)

    for dll, users in sorted(importers.items()):
        names = sorted(users)
        if dll in in_folder:
            report.resolved_in_folder[dll] = names
        elif is_system(dll):
            report.system_imports[dll] = names
        elif dll in VC_RUNTIME:
            report.missing_app_local[dll] = names
        else:
            report.problems.append(
                f"{dll}: imported by {', '.join(names)}, neither in the output folder nor a "
                f"Windows system DLL on the allowlist of {SECTION}"
            )
    for binary in report.binaries:
        name = Path(binary.path).name.lower()
        if name in VC_RUNTIME and name not in importers:
            report.problems.append(
                f"{binary.path}: Visual C++ runtime DLL that no binary in the folder imports "
                f"({SECTION}: only as measured)"
            )
    return report


def render_text(report: ClosureReport, clean_machine: bool = False) -> str:
    lines = [f"DLL closure of {report.folder}"]
    lines.append(f"binaries: {len(report.binaries)}, footprint {report.footprint:,} bytes")
    for b in report.binaries:
        lines.append(f"  {b.path} ({b.size:,} bytes) - {b.role}")
        lines.append(f"    imports: {', '.join(b.load_time) or 'none'}")
        if b.delay_load:
            lines.append(f"    delay-loads: {', '.join(b.delay_load)}")
    lines.append(f"resolved in the folder: {', '.join(report.resolved_in_folder) or 'none'}")
    lines.append(f"Windows system DLLs imported: {len(report.system_imports)}")
    for dll, users in report.missing_app_local.items():
        lines.append(f"Visual C++ runtime needed app-local: {dll} (imported by {', '.join(users)})")
    problems = list(report.problems)
    if clean_machine:
        problems += report.clean_machine_problems()
    if problems:
        lines.append(f"check FAILED ({len(problems)}):")
        lines += [f"  {p}" for p in problems]
    else:
        what = "allowlist and clean-machine closure" if clean_machine else "allowlist"
        lines.append(f"{what} check passed")
    return "\n".join(lines)


def to_json(report: ClosureReport) -> dict[str, object]:
    return {
        **asdict(report),
        "ok": report.ok,
        "clean_machine_ready": report.clean_machine_ready,
        "footprint": report.footprint,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.toolchain.dll_closure")
    parser.add_argument("folder", type=Path)
    parser.add_argument(
        "--clean-machine",
        action="store_true",
        help="also fail when an import needs a DLL a clean Windows lacks",
    )
    parser.add_argument("--json", type=Path, help="also write the result as JSON")
    args = parser.parse_args(argv)
    if not args.folder.is_dir():
        print(f"{args.folder} is not a folder", file=sys.stderr)
        return 2
    report = check_folder(args.folder)
    print(render_text(report, args.clean_machine))
    if args.json:
        args.json.write_text(json.dumps(to_json(report), indent=2) + "\n", encoding="utf-8")
    passed = report.clean_machine_ready if args.clean_machine else report.ok
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
