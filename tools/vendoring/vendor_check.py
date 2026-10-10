"""The vendoring check of `thirdparty/uzengine-render-core/` (`13-engine-integration.md` §3.3).

Run on every commit by the hosted CPU lane of CI (`.github/workflows/parity.yml`):

    python -m tools.vendoring.vendor_check              # folder rules + a fresh verbose build
    python -m tools.vendoring.vendor_check --no-build   # folder rules only
    python -m tools.vendoring.vendor_check --build-log build.log

Each failure is printed as `[<rule>] <message>` and the exit code is 1; a clean tree exits 0.
Rules:

- `manifest`: `MANIFEST.json` or `MODIFICATIONS.md` cannot be read, or an entry is malformed;
- `hash-drift`: a file's SHA-256 differs from `vendored_sha256`, a `verbatim` entry differs from
  upstream, or a `modified` entry names a modification id the log does not record for that file;
- `notice`: a `modified` file does not start with the Apache-2.0 §4(b) notice naming its ids,
  original UzEngine path and commit;
- `coverage`: a file under the folder without a manifest entry (`LICENSE`, `ORIGIN.md`,
  `MANIFEST.json`, `MODIFICATIONS.md` excepted), or a manifest entry without its file;
- `denylist`: a path matching the §2.4 exclusions (`subset.DENYLIST`);
- `conflict-marker`: a git merge-conflict marker in any file of the folder;
- `build-path`: an include or library path of the build (from `zig build --verbose-cc
  --verbose-link`) outside the repository, other than the pinned Zig toolchain's directories and
  the Windows SDK; a path into a UzEngine checkout is named as such.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tools.vendoring.checks import conflict_markers, list_files
from tools.vendoring.hashing import git_blob_sha1, sha256_hex
from tools.vendoring.manifest import Manifest, ManifestEntry, loads
from tools.vendoring.modifications import LOG_NAME, Modification, ids_by_file, notice, parse_log
from tools.vendoring.subset import METADATA_FILES, VENDORED_DIR, denylisted

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_NAME = "MANIFEST.json"
BUILD_STEPS = ("render-core", "native-tests")

SHA256_RE = re.compile(r"[0-9a-f]{64}")
SHA1_RE = re.compile(r"[0-9a-f]{40}")

# Compiler options whose value is an include or library search path (separate or joined).
COMPILE_PATH_FLAGS = (
    "-isystem",
    "-idirafter",
    "-iquote",
    "-isysroot",
    "-iframework",
    "--sysroot",
    "-I",
    "-L",
    "-F",
)
LINKERS = frozenset({"lld-link", "ld.lld", "ld", "lld", "ar", "llvm-ar", "llvm-lib", "lib"})
LIBPATH_RE = re.compile(r"^[-/]libpath:(.+)$", re.IGNORECASE)
LINK_INPUT_SUFFIXES = (".lib", ".a", ".obj", ".o", ".res", ".def", ".dll")

# A UzEngine checkout: a folder named UzEngine, or one holding UzEngine's runtime RHI.
UZENGINE_NAME = "uzengine"
UZENGINE_MARKER = Path("runtime/engine/rhi/rhi_device.h")


@dataclass(frozen=True)
class Violation:
    rule: str
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.message}"


# ── Folder rules ───────────────────────────────────────────────────────────────────────────


def _entry_problems(entry: ManifestEntry, vendored_dir: str) -> list[str]:
    problems: list[str] = []
    if not entry.vendored_path.startswith(f"{vendored_dir}/"):
        problems.append(f"vendored_path is not under {vendored_dir}/")
    for name in ("upstream_sha256", "vendored_sha256"):
        if not SHA256_RE.fullmatch(getattr(entry, name)):
            problems.append(f"{name} is not a lower-case SHA-256")
    for name in ("upstream_blob_sha1", "upstream_commit"):
        if not SHA1_RE.fullmatch(getattr(entry, name)):
            problems.append(f"{name} is not a lower-case SHA-1")
    return problems


def _load(repo_root: Path, vendored_dir: str) -> tuple[Manifest | None, list[Modification]]:
    """Manifest and log, or `ValueError` naming the file that cannot be read."""
    folder = repo_root / vendored_dir
    try:
        manifest = loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(
            f"{vendored_dir}/{MANIFEST_NAME}: {type(error).__name__}: {error}"
        ) from error
    try:
        log = parse_log((folder / LOG_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"{vendored_dir}/{LOG_NAME}: {type(error).__name__}: {error}") from error
    return manifest, log


def folder_violations(repo_root: Path, vendored_dir: str = VENDORED_DIR) -> list[Violation]:
    """Every rule except `build-path`, over `repo_root / vendored_dir`."""
    root = repo_root / vendored_dir
    files = list_files(root)
    found: list[Violation] = []

    manifest: Manifest | None
    log: list[Modification] = []
    try:
        manifest, log = _load(repo_root, vendored_dir)
    except ValueError as error:
        found.append(Violation("manifest", str(error)))
        manifest = None

    entries: list[ManifestEntry] = []
    if manifest is not None:
        seen: set[str] = set()
        for entry in manifest.files:
            problems = _entry_problems(entry, vendored_dir)
            if entry.vendored_path in seen:
                problems.append("listed twice")
            seen.add(entry.vendored_path)
            found += [Violation("manifest", f"{entry.vendored_path}: {p}") for p in problems]
            if not problems:
                entries.append(entry)
        found += _entry_violations(repo_root, vendored_dir, entries, log)
        listed = {entry.vendored_path for entry in manifest.files}
        found += [
            Violation(
                "coverage", f"{vendored_dir}/{rel}: file under the folder is not in the manifest"
            )
            for rel in files
            if rel not in METADATA_FILES and f"{vendored_dir}/{rel}" not in listed
        ]

    prefix = f"{vendored_dir}/"
    candidates = set(files) | {e.vendored_path.removeprefix(prefix) for e in entries}
    found += [
        Violation("denylist", f"{vendored_dir}/{rel}: path is on the §2.4 denylist")
        for rel in denylisted(sorted(candidates))
    ]
    found += [
        Violation("conflict-marker", f"{vendored_dir}/{m.path}:{m.line}: {m.text!r}")
        for m in conflict_markers(root, files)
    ]
    return found


def _entry_violations(
    repo_root: Path, vendored_dir: str, entries: Iterable[ManifestEntry], log: list[Modification]
) -> list[Violation]:
    """`hash-drift`, `notice` and the missing-file half of `coverage`."""
    logged = {mod.id for mod in log}
    by_file = ids_by_file(log)
    prefix = f"{vendored_dir}/"
    found: list[Violation] = []
    for entry in entries:
        path = repo_root / entry.vendored_path
        if not path.is_file():
            found.append(
                Violation("coverage", f"{entry.vendored_path}: listed in the manifest, missing")
            )
            continue
        data = path.read_bytes()
        digest = sha256_hex(data)
        if digest != entry.vendored_sha256:
            found.append(
                Violation(
                    "hash-drift",
                    f"{entry.vendored_path}: sha256 {digest} != vendored_sha256 "
                    f"{entry.vendored_sha256} (an edit not recorded in {LOG_NAME})",
                )
            )
        if entry.status == "verbatim":
            if entry.vendored_sha256 != entry.upstream_sha256:
                found.append(
                    Violation(
                        "hash-drift",
                        f"{entry.vendored_path}: verbatim but vendored_sha256 != upstream_sha256",
                    )
                )
            elif git_blob_sha1(data) != entry.upstream_blob_sha1:
                found.append(
                    Violation(
                        "hash-drift",
                        f"{entry.vendored_path}: verbatim but its git blob id != "
                        f"upstream_blob_sha1 {entry.upstream_blob_sha1}",
                    )
                )
            if entry.modifications:
                found.append(
                    Violation(
                        "hash-drift", f"{entry.vendored_path}: verbatim with modification ids"
                    )
                )
            continue
        if not entry.modifications:
            found.append(
                Violation("hash-drift", f"{entry.vendored_path}: modified without modification ids")
            )
        file_ids = by_file.get(entry.vendored_path.removeprefix(prefix), [])
        for mod_id in entry.modifications:
            if mod_id not in logged:
                found.append(
                    Violation(
                        "hash-drift",
                        f"{entry.vendored_path}: modification id {mod_id} is not in {LOG_NAME}",
                    )
                )
            elif mod_id not in file_ids:
                found.append(
                    Violation(
                        "hash-drift",
                        f"{entry.vendored_path}: {LOG_NAME} {mod_id} does not list this file",
                    )
                )
        expected = notice(entry.modifications, entry.upstream_path, entry.upstream_commit)
        first = data.split(b"\n", 1)[0].rstrip(b"\r").decode("utf-8", errors="replace")
        if first != expected:
            found.append(
                Violation(
                    "notice",
                    f"{entry.vendored_path}: modified but its first line is not the Apache-2.0 "
                    f"§4(b) notice {expected!r}",
                )
            )
    return found


# ── Build-path rule ────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BuildPath:
    kind: str  # "compile" or "link"
    flag: str
    path: Path


def _protect(line: str, spaced: Sequence[str]) -> tuple[str, dict[str, str]]:
    """Replace allowed roots that contain spaces by space-free placeholders, so a whitespace
    split keeps them whole (Zig prints argv joined with spaces, unquoted)."""
    table: dict[str, str] = {}
    for index, root in enumerate(spaced):
        for variant in {root, root.replace("\\", "/")}:
            if variant.lower() in line.lower():
                key = f"\x00{index}\x00"
                line = re.sub(re.escape(variant), key, line, flags=re.IGNORECASE)
                table[key] = root
    return line, table


def _restore(token: str, table: dict[str, str]) -> str:
    for key, root in table.items():
        token = token.replace(key, root)
    return token


def _command_kind(tokens: list[str]) -> tuple[str, int] | None:
    """`("compile", i)` or `("link", i)` with the index of the first argument, or None."""
    if not tokens:
        return None
    head = Path(tokens[0]).name.lower().removesuffix(".exe")
    if head == "zig" and len(tokens) > 1:
        if tokens[1] in ("clang", "clang++", "cc", "c++"):
            return "compile", 2
        if tokens[1] in LINKERS:
            return "link", 2
        return None
    if head in ("clang", "clang++"):
        return "compile", 1
    if head in LINKERS:
        return "link", 1
    return None


def collect_build_paths(log: str, spaced_roots: Sequence[str] = ()) -> tuple[list[BuildPath], int]:
    """Include and library paths of every compiler and linker invocation in a `--verbose-cc
    --verbose-link` log (relative paths are left relative), and the number of compiler
    invocations seen."""
    found: list[BuildPath] = []
    compiles = 0
    for raw in log.splitlines():
        line, table = _protect(raw.removeprefix("error: ").strip(), spaced_roots)
        tokens = [_restore(t, table) for t in line.split()]
        kind = _command_kind(tokens)
        if kind is None:
            continue
        what, start = kind
        args = tokens[start:]
        if what == "compile":
            compiles += 1
            for index, token in enumerate(args):
                if token in COMPILE_PATH_FLAGS:
                    if index + 1 < len(args):
                        found.append(BuildPath(what, token, Path(args[index + 1])))
                    continue
                for flag in COMPILE_PATH_FLAGS:
                    # `--sysroot=<dir>`, or a short option joined to its value (`-I<dir>`).
                    joined = f"{flag}=" if flag.startswith("--") else flag
                    if token.startswith(joined) and len(token) > len(joined):
                        found.append(BuildPath(what, flag, Path(token[len(joined) :])))
                        break
        else:
            for index, token in enumerate(args):
                libpath = LIBPATH_RE.match(token)
                if libpath:
                    found.append(BuildPath(what, "-LIBPATH:", Path(libpath.group(1))))
                elif token == "-L" and index + 1 < len(args):
                    found.append(BuildPath(what, "-L", Path(args[index + 1])))
                elif token.startswith("-L") and len(token) > 2:
                    found.append(BuildPath(what, "-L", Path(token[2:])))
                elif not token.startswith("-") and token.lower().endswith(LINK_INPUT_SUFFIXES):
                    found.append(BuildPath(what, "input", Path(token)))
    return found, compiles


def _inside(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def uzengine_checkout(path: Path, repo_root: Path, known: Sequence[Path] = ()) -> Path | None:
    """The UzEngine checkout `path` points into: one of `known`, an ancestor named `UzEngine`,
    or an ancestor holding `runtime/engine/rhi/rhi_device.h`. Ancestors above `repo_root` are
    not considered for paths inside the repository."""
    for root in known:
        if _inside(path, root):
            return root
    ancestors = [path, *path.parents]
    if _inside(path, repo_root):
        ancestors = [a for a in ancestors if _inside(a, repo_root)]
    for ancestor in ancestors:
        if ancestor.name.casefold() == UZENGINE_NAME or (ancestor / UZENGINE_MARKER).is_file():
            return ancestor
    return None


def build_path_violations(
    log: str,
    cwd: Path,
    repo_root: Path,
    allowed_roots: Sequence[Path],
    denied_roots: Sequence[Path] = (),
    uzengine_roots: Sequence[Path] = (),
) -> list[Violation]:
    """The `build-path` rule over a verbose build log run in `cwd`.

    A path passes when it is inside `repo_root` or one of `allowed_roots` (the Zig toolchain,
    the Windows SDK) and not inside `denied_roots` (packages Zig fetched into its global cache).
    A path into a UzEngine checkout always fails, by name."""
    repo = repo_root.resolve()
    spaced = [str(r) for r in allowed_roots if " " in str(r)]
    paths, compiles = collect_build_paths(log, spaced)
    if compiles == 0:
        return [Violation("build-path", "the build log has no compiler invocation to inspect")]
    found: list[Violation] = []
    reported: set[tuple[str, Path]] = set()
    for item in paths:
        path = (item.path if item.path.is_absolute() else cwd / item.path).resolve()
        if (item.flag, path) in reported:
            continue
        reported.add((item.flag, path))
        checkout = uzengine_checkout(path, repo, uzengine_roots)
        if checkout is not None:
            found.append(
                Violation(
                    "build-path",
                    f"{item.kind} {item.flag} {path} points into the UzEngine checkout {checkout}",
                )
            )
        elif any(_inside(path, d) for d in denied_roots):
            found.append(
                Violation(
                    "build-path",
                    f"{item.kind} {item.flag} {path} is a package fetched into Zig's global cache, "
                    "outside the repository",
                )
            )
        elif not (_inside(path, repo) or any(_inside(path, r) for r in allowed_roots)):
            found.append(
                Violation(
                    "build-path",
                    f"{item.kind} {item.flag} {path} is outside the repository, the Zig "
                    "toolchain and the Windows SDK",
                )
            )
    return found


def zig_toolchain(zig: str) -> tuple[list[Path], list[Path]]:
    """Allowed roots of the pinned Zig (its installation, `lib_dir`, `global_cache_dir`) and the
    denied root inside them (`global_cache_dir/p`, fetched packages), from `zig env`."""
    env = subprocess.run(
        [zig, "env"], capture_output=True, text=True, check=True, timeout=60
    ).stdout
    allowed = [Path(zig).resolve().parent]
    values: dict[str, Path] = {}
    for key in ("lib_dir", "global_cache_dir"):
        match = re.search(rf'\.{key} = "([^"]+)"', env)
        if match is None:
            raise ValueError(f"`zig env` reports no {key}")
        values[key] = Path(match.group(1).replace("\\\\", "\\")).resolve()
    allowed += values.values()
    return allowed, [values["global_cache_dir"] / "p"]


def windows_sdk_roots() -> list[Path]:
    """Installed Windows 10/11 SDK roots (`KitsRoot10`), from the registry."""
    if sys.platform != "win32":
        return []
    import winreg

    roots: list[Path] = []
    for key_path in (
        r"SOFTWARE\Microsoft\Windows Kits\Installed Roots",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows Kits\Installed Roots",
    ):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "KitsRoot10")
        except OSError:
            continue
        root = Path(str(value)).resolve()
        if root not in roots:
            roots.append(root)
    return roots


def run_build(repo_root: Path, zig: str) -> tuple[int, str, Path]:
    """`zig build render-core native-tests --verbose-cc --verbose-link` from a fresh local cache
    inside the repository (so every compile and link is printed); returns the exit code, the
    log and the build's working directory."""
    work = repo_root / ".zig-cache" / f"vendor-check-{uuid.uuid4().hex[:12]}"
    try:
        proc = subprocess.run(
            [
                zig,
                "build",
                *BUILD_STEPS,
                "--cache-dir",
                str(work / "cache"),
                "--prefix",
                str(work / "out"),
                "--verbose-cc",
                "--verbose-link",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
            check=False,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return proc.returncode, proc.stdout + proc.stderr, repo_root


def build_violations(
    repo_root: Path, build_log: Path | None, uzengine_roots: Sequence[Path]
) -> list[Violation]:
    """Run (or read) the verbose build and apply the `build-path` rule."""
    zig = shutil.which("zig")
    if zig is None:
        return [Violation("build-path", "zig is not on PATH; the build paths cannot be collected")]
    if build_log is None:
        code, log, cwd = run_build(repo_root, zig)
        if code != 0:
            tail = "\n".join(log.splitlines()[-20:])
            return [Violation("build-path", f"zig build failed with exit code {code}:\n{tail}")]
    else:
        log, cwd = build_log.read_text(encoding="utf-8", errors="replace"), repo_root
    allowed, denied = zig_toolchain(zig)
    return build_path_violations(
        log, cwd, repo_root, [*allowed, *windows_sdk_roots()], denied, uzengine_roots
    )


# ── Command line ───────────────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.vendoring.vendor_check")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    build = parser.add_mutually_exclusive_group()
    build.add_argument("--no-build", action="store_true", help="skip the build-path rule")
    build.add_argument(
        "--build-log", type=Path, help="read the verbose build log instead of building"
    )
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()

    found = folder_violations(repo_root)
    if not args.no_build:
        env_repo = os.environ.get("UZENGINE_REPO")
        known = [Path(env_repo).resolve()] if env_repo else []
        found += build_violations(repo_root, args.build_log, known)

    for violation in found:
        print(f"vendoring check {violation}", file=sys.stderr)
    rules = sorted({v.rule for v in found})
    build_note = "build-path rule skipped (--no-build)" if args.no_build else "build paths checked"
    if found:
        print(
            f"vendoring check failed: {len(found)} violations of {', '.join(rules)}; {build_note}"
        )
        return 1
    count = len(json.loads((repo_root / VENDORED_DIR / MANIFEST_NAME).read_text("utf-8"))["files"])
    print(f"vendoring check passed: {count} vendored files; {build_note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
