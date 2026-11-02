"""The vendoring check of `thirdparty/uzengine-render-core/` (`13-engine-integration.md` §3.3).

Run locally, in the coordinator's full gate before the owner pushes (decision 200):

    python -m tools.vendoring.vendor_check --no-build   # folder rules only
    python -m tools.vendoring.vendor_check --build-log <work>/build.log \
        --build-cache <work>/cache --build-out <work>/out

The check never builds by itself. It reads the log that `verbose_build` and `write_build_log` made
(the session fixture `fresh_verbose_build` of `tests/conftest.py`, under pytest's own `tmp_path`).
The log's first line binds it to its run: command, commit, the digest of the build inputs
(`build_inputs_digest`) before and after the build, exit code and SHA-256 of the log. A log of
another commit, of inputs changed during or since the build, of a failed build, edited, or naming
other directories than the flags fails, with an instruction to rerun the build.

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
  the Windows SDK; a path into a UzEngine checkout is named as such. The build's own cache and
  prefix (`--build-cache`, `--build-out`) supply only linker inputs (objects, libraries, the
  compiled manifest resource) and the empty `-I` include trees Zig adds for linked libraries.
  An argument that may continue an unquoted path with spaces fails as ambiguous.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from tools.vendoring.checks import conflict_markers, list_files
from tools.vendoring.hashing import git_blob_sha1, sha256_hex
from tools.vendoring.manifest import Manifest, ManifestEntry, loads
from tools.vendoring.modifications import LOG_NAME, Modification, ids_by_file, notice, parse_log
from tools.vendoring.subset import METADATA_FILES, VENDORED_DIR, denylisted

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_NAME = "MANIFEST.json"
BUILD_STEPS = ("render-core", "native-tests", "painter", "render-tests")

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
# What the build's own cache and prefix may supply to the linker: objects, libraries and the
# resource Zig compiles from `.win32_manifest` (`src/UzPainter.manifest`).
BUILD_ARTIFACT_SUFFIXES = (".obj", ".o", ".lib", ".a", ".res")
ARTIFACT_KINDS = "linker objects, libraries and resources, and Zig's empty -I include trees"
ZIG_CACHE_ENTRY_RE = re.compile(r"[0-9a-f]{32}")
EVIDENCE_TAG = "uzpainter-build-evidence"
RERUN = "rerun the fresh verbose build (the fresh_verbose_build fixture of tests/conftest.py)"
# What `zig build` reads, as git pathspecs (`build_input_pathspecs` adds the generator's own
# references): build.zig and its package file; the native sources and the packages they build
# (`src/`, `thirdparty/`); the `#embed` and default assets; the Python facade it installs
# (`python/`); the C and C++ files of the native tests; the capability generator and its JSON
# inputs (`tools/capabilities/`), which also read `docs/prd.md` and the envelope registry with
# its manifests (`parity/envelopes/`); and the snapshot mesh it installs.
# Ignored files count where the build still reads them (an ignored header is still compiled).
IGNORED_INPUT_SCOPE = (
    "build.zig",
    "build.zig.zon",
    "src",
    "thirdparty",
    "assets",
    "python",
    *(f":(glob)tests/**/*.{suffix}" for suffix in ("c", "cc", "cpp", "h", "hpp", "inl")),
)
BUILD_INPUT_SCOPE = (
    *IGNORED_INPUT_SCOPE,
    "tools/capabilities",
    "docs/prd.md",
    "parity/envelopes",
    "parity/fixtures/meshes/plane.obj",
)

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
    """Replace folders whose path contains spaces by space-free placeholders, so a whitespace
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


def _commands(log: str, spaced_roots: Sequence[str]) -> Iterator[tuple[str, str, list[str]]]:
    """`(kind, program, arguments)` of every compiler and linker invocation in the log, split
    at whitespace with the spaced roots kept whole."""
    for raw in log.splitlines():
        line, table = _protect(raw.removeprefix("error: ").strip(), spaced_roots)
        tokens = [_restore(t, table) for t in line.split()]
        kind = _command_kind(tokens)
        if kind is not None:
            what, start = kind
            program = Path(tokens[start - 1]).name.lower().removesuffix(".exe")
            yield what, program, tokens[start:]


def _joined_path_flag(token: str) -> bool:
    """An include or library path flag joined to its value (`-I<dir>`, `-LIBPATH:<dir>`)."""
    if LIBPATH_RE.match(token):
        return True
    for flag in COMPILE_PATH_FLAGS:
        joined = f"{flag}=" if flag.startswith("--") else flag
        if token.startswith(joined) and len(token) > len(joined):
            return True
    return False


def ambiguous_tokens(log: str, spaced_roots: Sequence[str] = ()) -> list[tuple[str, str, str]]:
    """`(kind, previous, token)` for every argument that may continue an unquoted path with
    spaces (Zig prints argv joined with spaces): a relative argument that follows a path value
    (`-I <dir>`, `-I<dir>`, `-LIBPATH:<dir>`) or another argument that no option explains,
    unless it is one more linker input after a linker input. Such an argument cannot be told
    apart from the tail of `<path value> <rest>`, so the rule refuses it rather than checking
    only the head."""
    found: list[tuple[str, str, str]] = []
    for what, program, args in _commands(log, spaced_roots):
        for index in range(1, len(args)):
            token, previous = args[index], args[index - 1]
            if token.startswith("-") or Path(token).is_absolute():
                continue
            if previous.startswith("-") and not _joined_path_flag(previous):
                continue  # The value of an option, or an input after a flag.
            if index == 1 and program in ("ar", "llvm-ar"):
                continue  # `ar <operation> <archive> ...`
            if (
                what == "link"
                and not Path(previous).is_absolute()
                and all(t.lower().endswith(LINK_INPUT_SUFFIXES) for t in (token, previous))
            ):
                continue  # A run of relative inputs; a relative tail after an absolute head fails.
            found.append((what, previous, token))
    return found


def collect_build_paths(log: str, spaced_roots: Sequence[str] = ()) -> tuple[list[BuildPath], int]:
    """Include and library paths of every compiler and linker invocation in a `--verbose-cc
    --verbose-link` log (relative paths are left relative), and the number of compiler
    invocations seen."""
    found: list[BuildPath] = []
    compiles = 0
    for what, _, args in _commands(log, spaced_roots):
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


def _build_artifact(item: BuildPath, path: Path) -> bool:
    """A linker input object, library or compiled resource (`BUILD_ARTIFACT_SUFFIXES`)."""
    return (
        item.kind == "link"
        and item.flag == "input"
        and path.suffix.lower() in BUILD_ARTIFACT_SUFFIXES
    )


def _empty_include_tree(item: BuildPath, raw: Path, path: Path, cache: Path | None) -> bool:
    """The one include path the build's own cache may supply: Zig 0.15.2's `Module.linkLibrary`
    passes `-I` of the linked library's emitted include tree (std/Build/Module.zig:655 and :184;
    `Compile.getEmittedIncludeTree`, a write-files folder), which stays empty because build.zig
    installs no header. Bounded to exactly that shape: the `-I` flag (never `-isystem` or a
    library search path), a folder `<cache>/o/<32 hex digits>` spelled with no `..` or link,
    itself a real folder (not a link or junction), with no entry at all. Anything that could
    supply a header fails."""
    if cache is None or item.kind != "compile" or item.flag != "-I":
        return False
    if path.parent != cache.resolve() / "o" or not ZIG_CACHE_ENTRY_RE.fullmatch(path.name):
        return False
    if ".." in raw.parts or Path(os.path.normpath(raw)) != path:
        return False
    if path.is_symlink() or path.is_junction():
        return False
    return path.is_dir() and not any(path.iterdir())


def _spaced_prefix(root: Path) -> str | None:
    """`root` up to its deepest folder whose name has a space, or None. Kept whole in a log
    line, it also keeps whole the paths beside `root` (siblings, `..` escapes) that the rule must
    see to refuse."""
    for candidate in (root, *root.parents):
        if " " in candidate.name:
            return str(candidate)
    return None


def spaced_prefixes(roots: Iterable[Path]) -> list[str]:
    """The `_spaced_prefix` of each root that has one, longest first (for `_protect`)."""
    prefixes = {_spaced_prefix(Path(root)) for root in roots}
    return sorted((p for p in prefixes if p is not None), key=len, reverse=True)


def protected_tokens(line: str, roots: Iterable[Path]) -> list[str]:
    """The whitespace-separated arguments of one log line, with each known folder whose path
    has spaces (`roots`: the repository, the toolchain, the build's cache and prefix) kept whole,
    as the `build-path` rule splits them."""
    protected, table = _protect(line, spaced_prefixes(roots))
    return [_restore(token, table) for token in protected.split()]


def build_path_violations(
    log: str,
    cwd: Path,
    repo_root: Path,
    allowed_roots: Sequence[Path],
    denied_roots: Sequence[Path] = (),
    uzengine_roots: Sequence[Path] = (),
    build_artifact_roots: Sequence[Path] = (),
    include_tree_cache: Path | None = None,
) -> list[Violation]:
    """The `build-path` rule over a verbose build log run in `cwd`.

    In order: a path into a UzEngine checkout fails, by name; a path inside `denied_roots`
    (packages Zig fetched into its global cache) fails; a path spelled under one of
    `build_artifact_roots` (exactly the build's `--cache-dir` and `--prefix`) that resolves
    outside that same root (`..`, a link) fails; inside those roots only linker inputs
    (`_build_artifact`) and, under `include_tree_cache` (the `--cache-dir`), Zig's empty
    library include trees (`_empty_include_tree`) pass, and every other include path and every
    library search path fails, even when the root lies inside an allowed one;
    anything else passes when it is inside `repo_root` or one of `allowed_roots` (the Zig
    toolchain, the Windows SDK). Apart from these, an argument that may continue an unquoted path
    with spaces (`ambiguous_tokens`) fails."""
    repo = repo_root.resolve()
    artifact_roots = [root.resolve() for root in build_artifact_roots]
    # Absolute but unresolved, so a spelling through a linked parent folder still matches.
    spelled_roots = [root.absolute() for root in build_artifact_roots]
    # The repository and the working folder may have spaces too (`D:\projects\UzPainter work`).
    spaced = spaced_prefixes([*allowed_roots, *artifact_roots, repo, cwd.resolve()])
    paths, compiles = collect_build_paths(log, spaced)
    if compiles == 0:
        return [Violation("build-path", "the build log has no compiler invocation to inspect")]
    found: list[Violation] = []
    # Each spelling is checked, so an allowed spelling of a path cannot mask an escaping one.
    reported: set[tuple[str, Path]] = set()
    for item in paths:
        raw = item.path if item.path.is_absolute() else cwd / item.path
        path = raw.resolve()
        if (item.flag, raw) in reported:
            continue
        reported.add((item.flag, raw))
        # The cache or prefix root the path is spelled under (before `..` and links resolve);
        # it must stay inside that same root.
        named = [
            resolved
            for given, resolved in zip(spelled_roots, artifact_roots, strict=True)
            if raw.is_relative_to(given) or raw.is_relative_to(resolved)
        ]
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
        elif named and not any(_inside(path, r) for r in named):
            found.append(
                Violation(
                    "build-path",
                    f"{item.kind} {item.flag} {raw} escapes the build's own cache or prefix "
                    f"to {path}",
                )
            )
        elif any(_inside(path, r) for r in artifact_roots):
            admitted = _build_artifact(item, path) or _empty_include_tree(
                item, raw, path, include_tree_cache
            )
            if path in artifact_roots or not admitted:
                found.append(
                    Violation(
                        "build-path",
                        f"{item.kind} {item.flag} {path} is in the build's own cache or prefix, "
                        f"which supply only {ARTIFACT_KINDS}",
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
    found += [
        Violation(
            "build-path",
            f"{kind} argument {token!r} after {previous!r} is ambiguous: Zig prints the command "
            "unquoted, so it may continue a path with spaces",
        )
        for kind, previous, token in ambiguous_tokens(log, spaced)
    ]
    return list(dict.fromkeys(found))


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


@dataclass(frozen=True)
class BuildEvidence:
    """One verbose build: its command, the commit it built, the digest of its inputs before and
    after it ran (`build_inputs_digest`), its exit code and its log."""

    command: tuple[str, ...]
    commit: str
    inputs_before: str
    inputs_after: str
    exit_code: int
    log: str

    def fields(self) -> dict[str, object]:
        """Every field but the log, as the evidence line records them."""
        return {
            "command": list(self.command),
            "commit": self.commit,
            "inputs_before": self.inputs_before,
            "inputs_after": self.inputs_after,
            "exit_code": self.exit_code,
        }

    @property
    def sha256(self) -> str:
        """SHA-256 over the canonical fields and the log, so an edit to either shows."""
        fields = json.dumps(self.fields(), sort_keys=True)
        return sha256_hex(f"{fields}\n{self.log}".encode())


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=120,
    ).stdout


def git_head(repo_root: Path) -> str:
    """The commit `HEAD` of `repo_root`."""
    return _git(repo_root, "rev-parse", "HEAD").strip()


def build_input_pathspecs(repo_root: Path) -> list[str]:
    """`BUILD_INPUT_SCOPE` plus what the capability generator reads beyond it, found with its own
    rules: the current envelope's Tier 0 manifests (`current_tier0_dir`), and every
    architecture-evidence Markdown file (`ARCH_ANCHOR`) and matrix-fixture Python test
    (`FIXTURE`) that its JSON inputs name."""
    from tools.capabilities.generate_capabilities import (
        ARCH_ANCHOR,
        FIXTURE,
        GenerationError,
        current_tier0_dir,
    )

    named: set[str] = set()
    # No readable registry: the registry itself is in scope, and the build fails.
    with contextlib.suppress(GenerationError, ValueError):
        named.add(current_tier0_dir(repo_root).relative_to(repo_root).as_posix())

    def walk(value: object) -> None:
        if isinstance(value, str):
            for pattern in (ARCH_ANCHOR, FIXTURE):
                match = pattern.match(value)
                if match:
                    named.add(match.group(1))
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for source in sorted((repo_root / "tools" / "capabilities").glob("*.json")):
        # The file itself is in scope; a broken one fails the build.
        with contextlib.suppress(OSError, ValueError):
            walk(json.loads(source.read_text(encoding="utf-8")))
    return [*BUILD_INPUT_SCOPE, *(f":(literal){path}" for path in sorted(named))]


def build_inputs_digest(repo_root: Path) -> str:
    """SHA-256 over the path and the git blob id of the on-disk bytes of every file of
    `build_input_pathspecs`, tracked (a deleted one counts as `deleted`) or untracked and not
    ignored, plus the ignored files of `IGNORED_INPUT_SCOPE`; Python bytecode never counts.

    Git only lists the files; every one is hashed from disk, so index flags (`assume-unchanged`,
    `skip-worktree`) and clean filters cannot hide an edit. Only the digest leaves this function,
    never file contents."""
    listed = _git(
        repo_root,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        *build_input_pathspecs(repo_root),
    )
    ignored = _git(
        repo_root,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
        "--",
        *IGNORED_INPUT_SCOPE,
    )
    lines: list[str] = []
    for path in sorted(set(filter(None, f"{listed}\0{ignored}".split("\0")))):
        if "__pycache__" in path.split("/") or path.endswith((".pyc", ".pyo")):
            continue
        file = repo_root / path
        blob = git_blob_sha1(file.read_bytes()) if file.is_file() else "deleted"
        lines.append(f"{path}\0{blob}\n")
    return sha256_hex("".join(lines).encode("utf-8"))


def verbose_build(
    repo_root: Path, zig: str, work: Path, steps: Sequence[str] = BUILD_STEPS
) -> BuildEvidence:
    """`zig build <steps> --verbose-cc --verbose-link` with the local cache `work/cache` and the
    prefix `work/out`. The cache must be missing or empty, so that every compile and link runs and
    is printed; anything else raises `ValueError`. The caller owns `work`."""
    cache = work / "cache"
    if cache.exists() and (not cache.is_dir() or any(cache.iterdir())):
        raise ValueError(f"{cache} is not an empty directory; the build log would not be fresh")
    command = (
        zig,
        "build",
        *steps,
        "--cache-dir",
        str(cache),
        "--prefix",
        str(work / "out"),
        "--verbose-cc",
        "--verbose-link",
    )
    commit = git_head(repo_root)
    before = build_inputs_digest(repo_root)
    proc = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    after = build_inputs_digest(repo_root)
    return BuildEvidence(command, commit, before, after, proc.returncode, proc.stdout + proc.stderr)


def write_build_log(path: Path, build: BuildEvidence) -> None:
    """The log, after a first line naming its command, commit, input digests, exit code and the
    SHA-256 over those and the log."""
    header = build.fields() | {"sha256": build.sha256}
    path.write_bytes(f"{EVIDENCE_TAG} {json.dumps(header)}\n{build.log}".encode())


def read_build_log(path: Path) -> BuildEvidence:
    """What `write_build_log` wrote, or `ValueError` when the file cannot be read, has no evidence
    line, or its fields or log no longer match the recorded SHA-256. The checksum shows an
    accidental edit; it is not a signature."""
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"{type(error).__name__}: {error}") from error
    first, _, log = text.partition("\n")
    if not first.startswith(f"{EVIDENCE_TAG} "):
        raise ValueError(f"no {EVIDENCE_TAG} line: not a log written by write_build_log")
    try:
        header = json.loads(first.removeprefix(f"{EVIDENCE_TAG} "))
        command = tuple(str(arg) for arg in header["command"])
        build = BuildEvidence(
            command,
            str(header["commit"]),
            str(header["inputs_before"]),
            str(header["inputs_after"]),
            int(header["exit_code"]),
            log,
        )
        recorded = str(header["sha256"])
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError(f"malformed {EVIDENCE_TAG} line: {error!r}") from error
    if build.sha256 != recorded:
        raise ValueError(
            f"evidence sha256 {build.sha256} != recorded {recorded}: the log was edited"
        )
    return build


def _option(command: Sequence[str], flag: str) -> str | None:
    """The value of `flag` when the command passes it exactly once."""
    values = [command[i + 1] for i, arg in enumerate(command[:-1]) if arg == flag]
    return values[0] if len(values) == 1 else None


def evidence_problems(
    build: BuildEvidence, log_path: Path, cache: Path, out: Path, commit: str, inputs: str
) -> list[str]:
    """Why `build` is not a successful verbose build of `BUILD_STEPS` at `commit` with the build
    inputs `inputs` (`build_inputs_digest` now), into exactly `cache` and `out`, the `cache` and
    `out` folders next to the log. Each problem ends with the rerun instruction."""
    problems: list[str] = []
    work = log_path.resolve().parent
    if build.commit != commit:
        problems.append(f"the log built commit {build.commit}, HEAD is {commit}")
    if build.inputs_before != build.inputs_after:
        problems.append("the build inputs changed while the build ran")
    elif build.inputs_after != inputs:
        problems.append(
            f"the build inputs changed since the build (digest {build.inputs_after}, now {inputs})"
        )
    if build.exit_code != 0:
        problems.append(f"the logged build failed with exit code {build.exit_code}")
    command = build.command
    if len(command) < 2 or command[1] != "build":
        problems.append(f"the logged command is not `zig build`: {list(command)}")
    missing = [s for s in (*BUILD_STEPS, "--verbose-cc", "--verbose-link") if s not in command]
    if missing:
        problems.append(f"the logged command lacks {', '.join(missing)}")
    for flag, name, given in (("--cache-dir", "cache", cache), ("--prefix", "out", out)):
        if given.resolve() != work / name:
            problems.append(f"{given} is not {work / name}, next to the log")
        logged = _option(command, flag)
        if logged is None or Path(logged).resolve() != given.resolve():
            problems.append(f"the logged {flag} {logged} is not {given}")
    return [f"{problem}; {RERUN}" for problem in problems]


def build_violations(
    repo_root: Path,
    build_log: Path,
    build_cache: Path,
    build_out: Path,
    uzengine_roots: Sequence[Path],
) -> list[Violation]:
    """Read the verbose build log, check its evidence and apply the `build-path` rule."""
    zig = shutil.which("zig")
    if zig is None:
        return [Violation("build-path", "zig is not on PATH; the build paths cannot be collected")]
    try:
        build = read_build_log(build_log)
    except ValueError as error:
        return [Violation("build-path", f"{build_log}: {error}; {RERUN}")]
    problems = evidence_problems(
        build,
        build_log,
        build_cache,
        build_out,
        git_head(repo_root),
        build_inputs_digest(repo_root),
    )
    if problems:
        return [Violation("build-path", f"{build_log}: {p}") for p in problems]
    allowed, denied = zig_toolchain(zig)
    logged = [_option(build.command, flag) for flag in ("--cache-dir", "--prefix")]
    return build_path_violations(
        build.log,
        repo_root,
        repo_root,
        [*allowed, *windows_sdk_roots()],
        denied,
        uzengine_roots,
        # The flags' spelling and the logged one: both resolve to the same folders (checked
        # above), and either may be how the log spells a path.
        [build_cache, build_out, *(Path(value) for value in logged if value is not None)],
        include_tree_cache=build_cache,
    )


# ── Command line ───────────────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.vendoring.vendor_check")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    build = parser.add_mutually_exclusive_group()
    build.add_argument("--no-build", action="store_true", help="skip the build-path rule")
    build.add_argument(
        "--build-log", type=Path, help="the verbose build log that write_build_log wrote"
    )
    parser.add_argument("--build-cache", type=Path, help="that build's --cache-dir")
    parser.add_argument("--build-out", type=Path, help="that build's --prefix")
    args = parser.parse_args(argv)
    if args.no_build and (args.build_cache or args.build_out):
        parser.error("--build-cache and --build-out go with --build-log, not with --no-build")
    if not args.no_build and not (args.build_log and args.build_cache and args.build_out):
        parser.error(
            "the build-path rule needs --build-log, --build-cache and --build-out of a fresh "
            "verbose build (the fresh_verbose_build fixture of tests/conftest.py); the check "
            "does not build by itself; --no-build runs the folder rules only"
        )
    repo_root = args.repo_root.resolve()

    found = folder_violations(repo_root)
    if not args.no_build:
        env_repo = os.environ.get("UZENGINE_REPO")
        known = [Path(env_repo).resolve()] if env_repo else []
        found += build_violations(
            repo_root, args.build_log, args.build_cache, args.build_out, known
        )

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
