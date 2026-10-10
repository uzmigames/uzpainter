"""The Visual C++ runtime DLLs shipped app-local beside `UzPainter.exe`
(`docs/architecture/13-engine-integration.md` §5, "Further Visual C++ runtime DLLs ... only as
measured"; owner answer to question q1 of `phase0.6_toolchain-hardware-slice`, 2026-10-10).

Measured need: Embree 4.4.1's `embree4.dll` and `tbb12.dll` import `MSVCP140.dll` and
`VCRUNTIME140.dll`, and `msvcp140.dll` imports `VCRUNTIME140_1.dll`
(`python -m tools.toolchain.dll_closure`). Microsoft publishes these files
for app-local deployment in the Visual C++ 2015-2022 Redistributable folder of Visual Studio
(`VC\\Redist\\MSVC\\<version>\\x64\\Microsoft.VC143.CRT\\`), not as a downloadable archive, so the
provenance is pinned by version, SHA-256 and Authenticode signer of each file instead of an
archive hash. `thirdparty/vc-runtime/` holds the two DLLs, `MANIFEST.json` and `ORIGIN.md`.

    python -m tools.vendoring.vcruntime import [--redist <Microsoft.VC143.CRT folder>]
    python -m tools.vendoring.vcruntime check

`import` copies the files after checking hash and signature; `check` re-checks the folder.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from tools.vendoring.hashing import sha256_hex

FOLDER = "thirdparty/vc-runtime"
VERSION = "14.44.35211.0"
REDIST_VERSION = "14.44.35112"
DEFAULT_REDIST = (
    Path(r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Redist\MSVC")
    / REDIST_VERSION
    / "x64"
    / "Microsoft.VC143.CRT"
)
SIGNER = (
    "CN=Microsoft Windows Software Compatibility Publisher, O=Microsoft Corporation, "
    "L=Redmond, S=Washington, C=US"
)
RETRIEVED = "2026-10-10"
RELEASE_BLOCKER = (
    "RB-VCRT-TERMS: the files are Distributable Code of Microsoft Visual Studio 2022 "
    "(list: https://aka.ms/vs/17/redist.txt); redistributing them binds UzmiGames to the Visual "
    "Studio licence terms for Distributable Code, which only the owner can accept; until then "
    "they ship in development builds only"
)


@dataclass(frozen=True)
class RuntimeFile:
    name: str
    sha256: str
    thumbprint: str  # signer certificate thumbprint (SHA-1), as Windows reports it


FILES: tuple[RuntimeFile, ...] = (
    RuntimeFile(
        "msvcp140.dll",
        "0f885b509a685d2bbfa652fed26b5fb31d88fbdab0a978c641d1c7b8aa460aa9",
        "81915C173D7FFCBF49EAA8CF7594696B29A035E1",
    ),
    RuntimeFile(
        "vcruntime140.dll",
        "d5e4d9a3e835fa679450145d6a7d94e36573a509317111904d9b3712c30d9066",
        "EC5F0D7EE2327688384B4FDF5D7633553A0D055F",
    ),
    # Imported by msvcp140.dll itself (measured), so part of the same closure.
    RuntimeFile(
        "vcruntime140_1.dll",
        "1f2d41c4aa5db0bc33ebf7b66d72943a817d7ce6cbe880502a9403823633093f",
        "EC5F0D7EE2327688384B4FDF5D7633553A0D055F",
    ),
)
METADATA_FILES = frozenset({"MANIFEST.json", "ORIGIN.md"})


def signature(path: Path) -> tuple[str, str, str]:
    """(status, signer subject, signer thumbprint) from Windows' Authenticode check."""
    script = (
        f"$s = Get-AuthenticodeSignature -LiteralPath '{path}'; "
        '"$($s.Status)|$($s.SignerCertificate.Subject)|$($s.SignerCertificate.Thumbprint)"'
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    ).stdout.strip()
    status, subject, thumbprint = out.split("|", 2)
    return status, subject, thumbprint


def file_problems(path: Path, entry: RuntimeFile, check_signature: bool = True) -> list[str]:
    if not path.is_file():
        return [f"{path}: missing"]
    problems: list[str] = []
    digest = sha256_hex(path.read_bytes())
    if digest != entry.sha256:
        problems.append(f"{path}: sha256 {digest} != pinned {entry.sha256}")
    if check_signature:
        status, subject, thumbprint = signature(path)
        if status != "Valid" or subject != SIGNER or thumbprint != entry.thumbprint:
            problems.append(
                f"{path}: Authenticode {status}, signer {subject!r} ({thumbprint}); pinned "
                f"Valid, {SIGNER!r} ({entry.thumbprint})"
            )
    return problems


def manifest(root: Path) -> dict[str, object]:
    return {
        "library": "Microsoft Visual C++ runtime (app-local)",
        "source": f"Visual Studio 2022 VC\\Redist\\MSVC\\{REDIST_VERSION}\\x64\\"
        "Microsoft.VC143.CRT",
        "file_version": VERSION,
        "signer": SIGNER,
        "files": [
            {
                "path": f.name,
                "sha256": f.sha256,
                "size": (root / f.name).stat().st_size,
                "signer_thumbprint": f.thumbprint,
            }
            for f in FILES
        ],
    }


def render_origin(root: Path) -> str:
    lines = [
        "# Origin of the Visual C++ runtime (app-local)",
        "",
        "| Field | Value |",
        "|---|---|",
        "| Publisher | Microsoft Corporation |",
        "| Package | Microsoft Visual C++ 2015-2022 Redistributable, app-local deployment folder "
        f"of Visual Studio 2022: `VC\\Redist\\MSVC\\{REDIST_VERSION}\\x64\\"
        "Microsoft.VC143.CRT\\` |",
        f"| File version | `{VERSION}` |",
        f"| Authenticode signer | {SIGNER} (status Valid on import) |",
        f"| Retrieved | {RETRIEVED} |",
        "| Importer | Rulebook task `phase0.6_toolchain-hardware-slice`, run with "
        "`python -m tools.vendoring.vcruntime import` for UzmiGames |",
        "| Why | Measured import closure: Embree 4.4.1's `embree4.dll` and `tbb12.dll` import "
        "`MSVCP140.dll` and `VCRUNTIME140.dll`, and `msvcp140.dll` imports "
        "`VCRUNTIME140_1.dll`; a clean Windows has no Visual C++ runtime "
        "(`13-engine-integration.md` §5; owner answer to q1, 2026-10-10) |",
        "| Distribution role | shipped: beside `UzPainter.exe` |",
        "| Licence | Microsoft Visual Studio 2022 licence terms, Distributable Code "
        "(https://aka.ms/vs/17/redist.txt); not Apache-2.0 |",
        "",
        "Microsoft publishes these files for app-local deployment in Visual Studio's redist "
        "folder rather than as a downloadable archive, so each file is pinned by SHA-256 and "
        "Authenticode signer (`MANIFEST.json`, `tools/vendoring/vcruntime.py`); the bytes are "
        "the redist folder's, unchanged.",
        "",
        "## Licence inventory",
        "",
        f"- Status: **release blocker** — {RELEASE_BLOCKER}",
        "",
        f"## Files ({len(FILES)})",
        "",
    ]
    lines += [
        f"- `{f.name}` ({(root / f.name).stat().st_size:,} bytes), SHA-256 `{f.sha256}`, signer "
        f"thumbprint `{f.thumbprint}`"
        for f in FILES
    ]
    return "\n".join([*lines, ""])


def folder_problems(repo_root: Path, check_signature: bool = True) -> list[str]:
    root = repo_root / FOLDER
    problems = [p for f in FILES for p in file_problems(root / f.name, f, check_signature)]
    listed = {f.name for f in FILES} | METADATA_FILES
    problems += [
        f"{FOLDER}/{p.name}: not a pinned file"
        for p in sorted(root.iterdir())
        if p.name not in listed
    ]
    if not problems:
        recorded = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
        if recorded != manifest(root):
            problems.append(f"{FOLDER}/MANIFEST.json differs from the pinned table")
        if (root / "ORIGIN.md").read_text(encoding="utf-8") != render_origin(root):
            problems.append(f"{FOLDER}/ORIGIN.md is not current")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.vendoring.vcruntime")
    parser.add_argument("action", choices=("import", "check"))
    parser.add_argument("--redist", type=Path, default=DEFAULT_REDIST)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    root = args.repo_root / FOLDER
    if args.action == "import":
        problems = [p for f in FILES for p in file_problems(args.redist / f.name, f)]
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        root.mkdir(parents=True, exist_ok=True)
        for f in FILES:
            shutil.copyfile(args.redist / f.name, root / f.name)
        (root / "MANIFEST.json").write_bytes(
            (json.dumps(manifest(root), indent=2) + "\n").encode("utf-8")
        )
        (root / "ORIGIN.md").write_bytes(render_origin(root).encode("utf-8"))
        print(f"{FOLDER}: {len(FILES)} files imported")
        return 0
    problems = folder_problems(args.repo_root)
    print("\n".join(problems) if problems else f"{FOLDER}: {len(FILES)} files verified")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
