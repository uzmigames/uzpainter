"""Link map of `UzPainter.exe` (`phase0.6_toolchain-hardware-slice`, item 2.8).

    python -m tools.toolchain.link_map --work <dir> [--json <file>]

Zig's build API has no linker-map option, so the map comes from the linker itself: the tool
builds `zig build painter` with a fresh cache under `<dir>` and `--verbose-link`, takes the exact
`lld-link` command that produced `UzPainter.exe`, and runs it again through `zig lld-link` with
`/MAP` added and the outputs redirected into `<dir>/relink/`. The map (MSVC layout, as lld-link
writes it in MinGW mode: each public symbol with its `library:object` origin) is then inspected:
the vendored render core (`uzrendercore.lib`) and libc++ (`c++.lib`, `c++abi.lib`) must
contribute object members, which shows they are linked statically, and the executable must
import no C++ runtime DLL.

Exit code 0 when the inspection passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tools.toolchain.pe import read_imports

REPO_ROOT = Path(__file__).resolve().parents[2]
EXE_NAME = "UzPainter.exe"
# Archives by the name the map gives them (`library:object`, library without its extension).
CORE_ARCHIVE = "uzrendercore"
LIBCXX_ARCHIVES = ("c++", "c++abi")
# Render-core members the selftest's code paths must pull in.
REQUIRED_CORE_MEMBERS = ("dx12_device.obj", "dx12_command_list.obj", "shader_compiler.obj")
# A C++ runtime DLL in the import table would mean libc++ is not linked statically.
CXX_RUNTIME_DLLS = re.compile(
    r"^(lib)?c\+\+(abi)?\.dll$|^libstdc\+\+.*\.dll$|^msvcp\d+.*\.dll$", re.IGNORECASE
)
OBJECT_SUFFIXES = (".obj", ".o")


@dataclass
class LinkMapReport:
    map_path: str
    command_inputs: list[str]
    members: dict[str, list[str]] = field(default_factory=dict)
    exe_imports: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def find_link_command(log: str, exe_name: str = EXE_NAME) -> list[str]:
    """The `lld-link` argument list (after `lld-link`) whose `-OUT:` is `exe_name`."""
    for raw in log.splitlines():
        line = raw.strip().removeprefix("error: ").strip()
        tokens = line.split()
        if "lld-link" not in tokens:
            continue
        args = tokens[tokens.index("lld-link") + 1 :]
        if any(t.upper().startswith("-OUT:") and t.endswith(exe_name) for t in args):
            return args
    raise ValueError(f"no lld-link command producing {exe_name} in the build log")


def relink_args(args: Sequence[str], out_dir: Path, map_path: Path) -> list[str]:
    """`args` with the outputs moved into `out_dir` and `/MAP` added."""
    redirected: list[str] = []
    for token in args:
        upper = token.upper()
        if upper.startswith("-OUT:"):
            redirected.append(f"-OUT:{out_dir / EXE_NAME}")
        elif upper.startswith("-PDB:"):
            redirected.append(f"-PDB:{out_dir / 'UzPainter.pdb'}")
        elif upper.startswith("-IMPLIB:"):
            redirected.append(f"-IMPLIB:{out_dir / 'UzPainter.lib'}")
        else:
            redirected.append(token)
    return [*redirected, f"-MAP:{map_path}"]


def archive_members(map_text: str) -> dict[str, list[str]]:
    """Archive name (lower case, no extension) -> sorted members that contribute symbols to the
    image, from the `library:object` column of the map's symbol lines."""
    members: dict[str, set[str]] = {}
    for line in map_text.splitlines():
        tokens = line.split()
        if len(tokens) < 3:
            continue
        origin = tokens[-1]
        archive, sep, member = origin.rpartition(":")
        if sep and archive and member.lower().endswith(OBJECT_SUFFIXES):
            members.setdefault(archive.lower(), set()).add(member)
    return {k: sorted(v) for k, v in sorted(members.items())}


def inspect(map_text: str, exe_imports: Sequence[str]) -> list[str]:
    """Problems with the static linking the map and the import table show."""
    members = archive_members(map_text)
    problems: list[str] = []
    core = set(members.get(CORE_ARCHIVE, []))
    if not core:
        problems.append(f"{CORE_ARCHIVE}.lib contributes no object to {EXE_NAME}")
    missing = [m for m in REQUIRED_CORE_MEMBERS if m not in core]
    if core and missing:
        problems.append(f"{CORE_ARCHIVE}.lib members not linked: {', '.join(missing)}")
    for archive in LIBCXX_ARCHIVES:
        if not members.get(archive):
            problems.append(f"libc++ archive {archive}.lib contributes no object to {EXE_NAME}")
    dlls = [d for d in exe_imports if CXX_RUNTIME_DLLS.match(d)]
    if dlls:
        problems.append(f"{EXE_NAME} imports a C++ runtime DLL: {', '.join(dlls)}")
    return problems


def build_and_map(work: Path, zig: str) -> LinkMapReport:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    build = subprocess.run(
        [
            zig,
            "build",
            "painter",
            "--prefix",
            str(work / "prefix"),
            "--cache-dir",
            str(work / "cache"),
            "--verbose-link",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    log = build.stdout + build.stderr
    (work / "build.log").write_text(log, encoding="utf-8")
    if build.returncode != 0:
        raise RuntimeError(
            f"zig build painter failed ({build.returncode}); see {work / 'build.log'}"
        )
    return map_build(log, work / "prefix", work, zig)


def map_build(log: str, prefix: Path, work: Path, zig: str) -> LinkMapReport:
    """Relink `UzPainter.exe` with `/MAP` from the `--verbose-link` log of a build that linked it
    (its link inputs still on disk) into `work/relink/`, and inspect the map and the import table
    of `prefix/bin/UzPainter.exe`."""
    args = find_link_command(log)
    inputs = [t for t in args if not t.startswith("-")]
    absent = [t for t in inputs if not Path(t).exists()]
    if absent:
        raise RuntimeError(f"link inputs not found (path with spaces?): {absent[:3]}")
    relink = work / "relink"
    relink.mkdir(parents=True)
    map_path = work / "UzPainter.map"
    linked = subprocess.run(
        [zig, "lld-link", *relink_args(args, relink, map_path)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if linked.returncode != 0 or not map_path.is_file():
        raise RuntimeError(f"zig lld-link with /MAP failed: {linked.stderr.strip()[:2000]}")
    map_text = map_path.read_text(encoding="utf-8", errors="replace")
    imports = read_imports(prefix / "bin" / EXE_NAME)
    exe_imports = [*imports.load_time, *imports.delay_load]
    return LinkMapReport(
        map_path=str(map_path),
        command_inputs=[Path(t).name for t in inputs],
        members=archive_members(map_text),
        exe_imports=exe_imports,
        problems=inspect(map_text, exe_imports),
    )


def render_text(report: LinkMapReport) -> str:
    lines = [f"link map {report.map_path}", f"link inputs: {', '.join(report.command_inputs)}"]
    for archive in (CORE_ARCHIVE, *LIBCXX_ARCHIVES):
        lines.append(f"{archive}.lib: {len(report.members.get(archive, []))} members linked")
    lines.append(f"{EXE_NAME} imports: {', '.join(report.exe_imports)}")
    if report.problems:
        lines.append("link map inspection FAILED:")
        lines += [f"  {p}" for p in report.problems]
    else:
        lines.append("link map inspection passed: render core and libc++ linked statically")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.toolchain.link_map")
    parser.add_argument("--work", type=Path, required=True, help="scratch folder (recreated)")
    parser.add_argument("--json", type=Path, help="also write the result as JSON")
    args = parser.parse_args(argv)
    zig = shutil.which("zig")
    if zig is None:
        print("zig is not on PATH", file=sys.stderr)
        return 1
    report = build_and_map(args.work.resolve(), zig)
    print(render_text(report))
    if args.json:
        payload = {**asdict(report), "ok": report.ok}
        args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
