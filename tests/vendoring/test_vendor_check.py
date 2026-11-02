"""Tests of the vendoring check (phase0.4_vendor-check, `tools/vendoring/vendor_check.py`).

The positive tests run the check on the vendored folder as imported and modified. Each negative
fixture is a copy of that folder with one deliberate defect and must fail with exactly the rule
the defect breaks.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from tools.vendoring.hashing import sha256_hex
from tools.vendoring.manifest import verbatim_entry
from tools.vendoring.modifications import notice
from tools.vendoring.subset import VENDORED_DIR
from tools.vendoring.vendor_check import (
    ARTIFACT_KINDS,
    BUILD_STEPS,
    RERUN,
    BuildEvidence,
    Violation,
    build_inputs_digest,
    build_path_violations,
    collect_build_paths,
    evidence_problems,
    folder_violations,
    git_head,
    main,
    read_build_log,
    verbose_build,
    write_build_log,
    zig_toolchain,
)

if TYPE_CHECKING:
    from tests.conftest import FreshBuild

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDORED = REPO_ROOT / VENDORED_DIR
ZIG = shutil.which("zig")
VERBATIM = f"{VENDORED_DIR}/engine/math/mat4.cpp"
MODIFIED = f"{VENDORED_DIR}/engine/rhi/rhi_factory.cpp"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository root holding a copy of the vendored folder."""
    shutil.copytree(VENDORED, tmp_path / VENDORED_DIR)
    return tmp_path


def _manifest(repo: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((repo / VENDORED_DIR / "MANIFEST.json").read_text("utf-8"))
    return data


def _edit_manifest(repo: Path, change: Callable[[dict[str, Any]], None]) -> None:
    data = _manifest(repo)
    change(data)
    (repo / VENDORED_DIR / "MANIFEST.json").write_text(json.dumps(data, indent=2) + "\n", "utf-8")


def _entry(data: dict[str, Any], vendored_path: str) -> dict[str, Any]:
    entry: dict[str, Any] = next(e for e in data["files"] if e["vendored_path"] == vendored_path)
    return entry


def _rewrite(repo: Path, vendored_path: str, content: bytes) -> None:
    """Replace a file and record its new hash in the manifest (a logged-looking edit)."""
    (repo / vendored_path).write_bytes(content)
    _edit_manifest(
        repo, lambda d: _entry(d, vendored_path).update(vendored_sha256=sha256_hex(content))
    )


def _rules(found: list[Violation]) -> set[str]:
    return {v.rule for v in found}


# ── Positive (3.1) ─────────────────────────────────────────────────────────────────────────


def test_imported_and_modified_folder_passes() -> None:
    assert folder_violations(REPO_ROOT) == []
    assert main(["--no-build"]) == 0


def test_fixture_copy_passes(repo: Path) -> None:
    """The fixtures start from a clean copy: any failure below comes from its one defect."""
    assert _entry(_manifest(repo), MODIFIED)["status"] == "modified"
    assert _entry(_manifest(repo), VERBATIM)["status"] == "verbatim"
    assert folder_violations(repo) == []


@pytest.mark.skipif(ZIG is None, reason="zig is not on PATH")
def test_full_check_with_build_passes(
    fresh_verbose_build: FreshBuild, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec scenario "Clean tree passes in CI": folder rules and the build-path rule over a fresh
    verbose build of `build.zig` (the session's shared one, `tests/conftest.py`) exit zero."""
    argv = [
        "--build-log",
        str(fresh_verbose_build.log_path),
        "--build-cache",
        str(fresh_verbose_build.cache),
        "--build-out",
        str(fresh_verbose_build.prefix),
    ]
    assert main(argv) == 0, capsys.readouterr().err
    assert "build paths checked" in capsys.readouterr().out


# ── Negative fixtures (3.2) ────────────────────────────────────────────────────────────────


def test_edited_verbatim_file(repo: Path) -> None:
    """Spec scenario "Silent edit detected"."""
    path = repo / VERBATIM
    path.write_bytes(path.read_bytes() + b"// silent edit\n")
    found = folder_violations(repo)
    assert _rules(found) == {"hash-drift"}
    assert all(v.message.startswith(VERBATIM) for v in found)


def test_edited_verbatim_file_with_rehashed_manifest(repo: Path) -> None:
    """Updating vendored_sha256 does not hide an unlogged edit of a verbatim file."""
    _rewrite(repo, VERBATIM, (repo / VERBATIM).read_bytes() + b"// edit\n")
    found = folder_violations(repo)
    assert _rules(found) == {"hash-drift"}
    assert any("verbatim but vendored_sha256 != upstream_sha256" in v.message for v in found)


def test_modified_file_without_notice(repo: Path) -> None:
    """Spec scenario "Missing notice detected"."""
    data = (repo / MODIFIED).read_bytes()
    _rewrite(repo, MODIFIED, data.split(b"\n", 1)[1])
    found = folder_violations(repo)
    assert _rules(found) == {"notice"}
    assert found[0].message.startswith(f"{MODIFIED}: modified but its first line is not")


def test_modified_entry_with_unknown_id(repo: Path) -> None:
    entry = _entry(_manifest(repo), MODIFIED)
    _edit_manifest(repo, lambda d: _entry(d, MODIFIED).update(modifications=["UZP-MOD-999"]))
    body = (repo / MODIFIED).read_bytes().split(b"\n", 1)[1]
    header = notice(["UZP-MOD-999"], entry["upstream_path"], entry["upstream_commit"])
    _rewrite(repo, MODIFIED, header.encode("utf-8") + b"\n" + body)
    found = folder_violations(repo)
    assert _rules(found) == {"hash-drift"}
    assert [v.message for v in found] == [
        f"{MODIFIED}: modification id UZP-MOD-999 is not in MODIFICATIONS.md"
    ]


def test_extra_unlisted_file(repo: Path) -> None:
    """Spec scenario "Unlisted file rejected"."""
    (repo / VENDORED_DIR / "engine/math/extra.h").write_text("#pragma once\n", "utf-8")
    found = folder_violations(repo)
    assert found == [
        Violation(
            "coverage",
            f"{VENDORED_DIR}/engine/math/extra.h: file under the folder is not in the manifest",
        )
    ]


def test_missing_listed_file(repo: Path) -> None:
    (repo / VERBATIM).unlink()
    assert folder_violations(repo) == [
        Violation("coverage", f"{VERBATIM}: listed in the manifest, missing")
    ]


@pytest.mark.parametrize(
    "rel",
    [
        "engine/asset/importers/mesh_importer.cpp",
        "engine/renderer/mesh/mesh_io.cpp",
        "engine/config/config.h",
    ],
)
def test_denylisted_file(repo: Path, rel: str) -> None:
    """Spec scenario "Defective mesh-cook file rejected": even with a well-formed manifest
    entry, a denylisted path fails with the denylist rule."""
    data = b"// excluded by 13-engine-integration.md section 2.4\n"
    (repo / VENDORED_DIR / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / VENDORED_DIR / rel).write_bytes(data)
    entry = verbatim_entry(f"runtime/{rel}", f"{VENDORED_DIR}/{rel}", "0" * 40, data)
    _edit_manifest(repo, lambda d: d["files"].append(asdict(entry)))
    assert folder_violations(repo) == [
        Violation("denylist", f"{VENDORED_DIR}/{rel}: path is on the §2.4 denylist")
    ]


def test_conflict_marker(repo: Path) -> None:
    head, body = (repo / MODIFIED).read_bytes().split(b"\n", 1)
    marked = head + b"\n<<<<<<< HEAD\nint a;\n=======\nint b;\n>>>>>>> topic\n" + body
    _rewrite(repo, MODIFIED, marked)
    found = folder_violations(repo)
    assert _rules(found) == {"conflict-marker"}
    assert [v.message.split(": ", 1)[0] for v in found] == [
        f"{MODIFIED}:2",
        f"{MODIFIED}:4",
        f"{MODIFIED}:6",
    ]


def test_malformed_manifest(repo: Path) -> None:
    (repo / VENDORED_DIR / "MANIFEST.json").write_text('{"files": [', "utf-8")
    found = folder_violations(repo)
    assert _rules(found) == {"manifest"}
    assert found[0].message.startswith(f"{VENDORED_DIR}/MANIFEST.json: JSONDecodeError")


def test_malformed_manifest_entry(repo: Path) -> None:
    _edit_manifest(repo, lambda d: _entry(d, VERBATIM).update(vendored_sha256="abc"))
    assert folder_violations(repo) == [
        Violation("manifest", f"{VERBATIM}: vendored_sha256 is not a lower-case SHA-256")
    ]


def test_malformed_log(repo: Path) -> None:
    log = repo / VENDORED_DIR / "MODIFICATIONS.md"
    log.write_text(log.read_text("utf-8").replace("| Reason | trim |\n", "", 1), "utf-8")
    found = folder_violations(repo)
    assert _rules(found) == {"manifest"}
    assert "UZP-MOD-001: missing fields ['Reason']" in found[0].message


def test_command_line_reports_each_rule(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Non-zero exit and one `[rule]` line per violation."""
    (repo / VERBATIM).write_bytes(b"edited\n")
    (repo / VENDORED_DIR / "stray.h").write_text("", "utf-8")
    assert main(["--repo-root", str(repo), "--no-build"]) == 1
    captured = capsys.readouterr()
    assert f"vendoring check [hash-drift] {VERBATIM}: sha256" in captured.err
    assert f"vendoring check [coverage] {VENDORED_DIR}/stray.h" in captured.err
    assert "vendoring check failed" in captured.out
    assert "coverage, hash-drift" in captured.out


# ── Build-path rule ────────────────────────────────────────────────────────────────────────

ZIG_DIR = Path(r"C:\zig\zig-x86_64-windows-0.15.2")
CACHE = Path(r"C:\Users\ci\AppData\Local\zig")
SDK = Path(r"C:\Program Files (x86)\Windows Kits\10")


def _compile(*args: str) -> str:
    return f"{ZIG_DIR}\\zig.exe clang++ src.cpp -std=c++23 {' '.join(args)} -c -o src.obj"


def _check(tmp_path: Path, log: str, repo_root: Path | None = None) -> list[Violation]:
    repo = repo_root or tmp_path / "UzPainter"
    repo.mkdir(parents=True, exist_ok=True)
    return build_path_violations(
        log, repo, repo, [ZIG_DIR, ZIG_DIR / "lib", CACHE, SDK], [CACHE / "p"]
    )


def test_collects_include_and_library_paths() -> None:
    log = "\n".join(
        [
            _compile("-I a", "-Ib", "-isystem c", "--sysroot=d", "-iquote e", "-DX=1"),
            "error: lld-link -NOLOGO -OUT:out.exe x.obj -LIBPATH:f -L g -Lh y.lib -lkernel32",
            "ar rcs z.lib w.obj",
            "render-core",
        ]
    )
    paths, compiles = collect_build_paths(log)
    assert compiles == 1
    assert [(p.kind, p.flag, p.path.as_posix()) for p in paths] == [
        ("compile", "-I", "a"),
        ("compile", "-I", "b"),
        ("compile", "-isystem", "c"),
        ("compile", "--sysroot", "d"),
        ("compile", "-iquote", "e"),
        ("link", "input", "x.obj"),
        ("link", "-LIBPATH:", "f"),
        ("link", "-L", "g"),
        ("link", "-L", "h"),
        ("link", "input", "y.lib"),
        ("link", "input", "z.lib"),
        ("link", "input", "w.obj"),
    ]


def test_repository_toolchain_and_sdk_paths_pass(tmp_path: Path) -> None:
    log = "\n".join(
        [
            _compile(
                "-I thirdparty/spdlog/include",
                r"-I .zig-cache\o\abc",
                f"-isystem {ZIG_DIR}\\lib\\libcxx\\include",
                f"-isystem {SDK}\\Include\\10.0.26100.0\\um",
            ),
            f"lld-link {CACHE}\\o\\abc\\kernel32.lib -LIBPATH:{SDK}\\Lib\\10.0.26100.0\\um\\x64",
        ]
    )
    assert _check(tmp_path, log) == []


def test_include_path_into_uzengine_checkout(tmp_path: Path) -> None:
    """Spec scenario "Engine include path rejected" (synthetic log): the path is named."""
    engine = Path(r"E:\UzmiGames\UzEngine\runtime\engine")
    found = _check(tmp_path, _compile("-I thirdparty/spdlog/include", f"-I {engine}"))
    assert found == [
        Violation(
            "build-path",
            f"compile -I {engine.resolve()} points into the UzEngine checkout "
            f"{Path(r'E:\UzmiGames\UzEngine').resolve()}",
        )
    ]


def test_uzengine_checkout_recognised_by_content(tmp_path: Path) -> None:
    """A UzEngine checkout under another folder name is still named as one."""
    checkout = tmp_path / "engine-src"
    (checkout / "runtime/engine/rhi").mkdir(parents=True)
    (checkout / "runtime/engine/rhi/rhi_device.h").write_text("", "utf-8")
    found = _check(tmp_path, _compile(f"-I {checkout / 'runtime' / 'engine'}"))
    assert len(found) == 1
    assert f"points into the UzEngine checkout {checkout.resolve()}" in found[0].message


def test_other_outside_paths_fail(tmp_path: Path) -> None:
    log = "\n".join(
        [
            _compile(r"-I D:\libs\boost", f"-I {CACHE}\\p\\pkg-123\\include"),
            r"lld-link x.obj -LIBPATH:D:\libs\lib C:\Program.lib",
        ]
    )
    messages = [v.message for v in _check(tmp_path, log)]
    assert len(messages) == 4
    assert messages[0].startswith(f"compile -I {Path(r'D:\libs\boost').resolve()} is outside")
    assert "is a package fetched into Zig's global cache" in messages[1]
    assert messages[2].startswith(f"link -LIBPATH: {Path(r'D:\libs\lib').resolve()} is outside")
    assert messages[3].startswith(f"link input {Path(r'C:\Program.lib').resolve()} is outside")


def test_log_without_compiler_invocation_fails(tmp_path: Path) -> None:
    assert _check(tmp_path, "render-core\n+- install uzrendercore\n") == [
        Violation("build-path", "the build log has no compiler invocation to inspect")
    ]


FIXTURE_BUILD = """const std = @import("std");

pub fn build(b: *std.Build) void {
    const inc = b.option([]const u8, "inc", "extra include directory") orelse @panic("-Dinc");
    const mod = b.createModule(.{ .target = b.graph.host, .optimize = .Debug });
    mod.addIncludePath(b.path("include"));
    mod.addIncludePath(.{ .cwd_relative = inc });
    mod.addCSourceFiles(.{ .files = &.{"a.c"}, .flags = &.{} });
    const obj = b.addObject(.{ .name = "a", .root_module = mod });
    b.getInstallStep().dependOn(&obj.step);
}
"""


@pytest.mark.skipif(ZIG is None, reason="zig is not on PATH")
def test_build_configuration_with_uzengine_include_path(tmp_path: Path) -> None:
    """Spec scenario "Engine include path rejected" end to end: a build configuration that adds
    an include path into a UzEngine checkout, built with `--verbose-cc`, fails by name."""
    assert ZIG is not None
    repo = tmp_path / "repo"
    engine = tmp_path / "UzEngine" / "runtime" / "engine"
    for folder in (repo / "include", engine):
        folder.mkdir(parents=True)
    (repo / "build.zig").write_text(FIXTURE_BUILD, "utf-8")
    (repo / "include" / "local.h").write_text("#define LOCAL 1\n", "utf-8")
    (engine / "engine.h").write_text("#define ENGINE 1\n", "utf-8")
    (repo / "a.c").write_text('#include "local.h"\n#include "engine.h"\nint a = LOCAL;\n', "utf-8")
    proc = subprocess.run(
        [ZIG, "build", f"-Dinc={engine}", "--cache-dir", str(repo / ".zig-cache"), "--verbose-cc"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    log = proc.stdout + proc.stderr
    assert proc.returncode == 0, log
    allowed, denied = zig_toolchain(ZIG)
    found = build_path_violations(log, repo, repo, allowed, denied)
    assert found == [
        Violation(
            "build-path",
            f"compile -I {engine.resolve()} points into the UzEngine checkout "
            f"{(tmp_path / 'UzEngine').resolve()}",
        )
    ]


# ── The build's own cache and prefix ───────────────────────────────────────────────────────


def _work(tmp_path: Path) -> Path:
    """A build work folder with spaces in its path, as a user name with spaces gives."""
    work = tmp_path / "pytest of a user" / "fresh build0"
    for name in ("cache", "out"):
        (work / name).mkdir(parents=True)
    return work


def _check_artifacts(tmp_path: Path, log: str, roots: list[Path]) -> list[Violation]:
    repo = tmp_path / "UzPainter"
    repo.mkdir(exist_ok=True)
    return build_path_violations(
        log, repo, repo, [ZIG_DIR, ZIG_DIR / "lib", CACHE, SDK], [CACHE / "p"], (), roots
    )


def test_build_artifact_roots_admit_linker_inputs_only(tmp_path: Path) -> None:
    """Objects and libraries under exactly `work/cache` and `work/out` pass, with spaces in the
    path; include and library search paths there, other suffixes, the work folder itself, its
    parent, a sibling folder and a `..` escape fail."""
    work = _work(tmp_path)
    cache, out = work / "cache", work / "out"
    passing = [
        cache / "o" / "abc" / "uzrendercore.lib",
        cache / "o" / "def" / "main.obj",
        cache / "o" / "def" / "shim.o",
        out / "lib" / "uzp_mesh.lib",
        out / "lib" / "libz.a",
        cache / "o" / "ghi" / "UzPainter.manifest.res",
    ]
    log = "\n".join(
        [
            _compile("-I thirdparty/spdlog/include"),
            f"lld-link -OUT:x.exe {' '.join(str(p) for p in passing)}",
        ]
    )
    assert _check_artifacts(tmp_path, log, [cache, out]) == []

    refused = [
        ("compile", "-I", cache / "o" / "inc", _compile(f"-I {cache / 'o' / 'inc'}")),
        ("compile", "-isystem", out / "include", _compile(f"-isystem {out / 'include'}")),
        ("link", "-LIBPATH:", cache / "o", f"lld-link x.obj -LIBPATH:{cache / 'o'}"),
        ("link", "-L", out / "lib", f"ld.lld x.o -L {out / 'lib'}"),
        ("link", "input", cache / "a.dll", f"lld-link {cache / 'a.dll'}"),
        ("link", "input", work / "stray.obj", f"lld-link {work / 'stray.obj'}"),
        ("link", "input", tmp_path / "x.lib", f"lld-link {tmp_path / 'x.lib'}"),
        ("link", "input", work / "cache2" / "x.obj", f"lld-link {work / 'cache2' / 'x.obj'}"),
        ("link", "input", work / "out-old" / "x.lib", f"lld-link {work / 'out-old' / 'x.lib'}"),
    ]
    for kind, flag, path, line in refused:
        found = _check_artifacts(tmp_path, f"{_compile()}\n{line}", [cache, out])
        assert len(found) == 1, (line, found)
        assert found[0].message.startswith(f"{kind} {flag} {path.resolve()} is "), found
    escaped, target = cache / "o" / ".." / ".." / "up.obj", (work / "up.obj").resolve()
    found = _check_artifacts(tmp_path, f"{_compile()}\nlld-link {escaped}", [cache, out])
    assert [v.message for v in found] == [
        f"link input {escaped} escapes the build's own cache or prefix to {target}"
    ]


def test_build_artifact_roots_keep_uzengine_and_fetched_package_rejections(
    tmp_path: Path,
) -> None:
    """A UzEngine checkout or a package Zig fetched fails even inside the artifact roots."""
    engine_cache = tmp_path / "UzEngine" / "cache"
    fetched = CACHE / "p" / "pkg-123"
    inputs = f"{engine_cache / 'o' / 'engine.lib'} {fetched / 'lib' / 'pkg.lib'}"
    log = "\n".join([_compile(), f"lld-link {inputs}"])
    messages = [v.message for v in _check_artifacts(tmp_path, log, [engine_cache, fetched])]
    assert len(messages) == 2
    assert "points into the UzEngine checkout" in messages[0]
    assert "is a package fetched into Zig's global cache" in messages[1]


def test_verbose_build_refuses_a_non_empty_cache(tmp_path: Path) -> None:
    """A cache holding an earlier build prints no compile, so the evidence would be stale:
    `verbose_build` refuses it before running anything (the zig given does not exist)."""
    work = tmp_path / "work"
    (work / "cache" / "o").mkdir(parents=True)
    no_zig = str(tmp_path / "no-zig.exe")
    with pytest.raises(ValueError, match="is not an empty directory"):
        verbose_build(REPO_ROOT, no_zig, work)
    (work / "cache" / "o").rmdir()
    (work / "cache").rmdir()
    (work / "cache").write_text("", "utf-8")
    with pytest.raises(ValueError, match="is not an empty directory"):
        verbose_build(REPO_ROOT, no_zig, work)


def test_build_artifact_roots_nested_in_allowed_roots_stay_narrow(tmp_path: Path) -> None:
    """A cache inside the repository or a prefix inside Zig's global cache (both allowed roots)
    still admits linker inputs only: the artifact-root rule runs before the general allow."""
    repo = tmp_path / "UzPainter"
    cache = repo / ".zig-cache" / "fresh" / "cache"
    out = CACHE / "o" / "work" / "out"
    assert (
        _check_artifacts(
            tmp_path, f"{_compile()}\nlld-link {cache / 'a.obj'} {out / 'b.lib'}", [cache, out]
        )
        == []
    )
    for flag, path, line in (
        ("-I", cache / "o", _compile(f"-I {cache / 'o'}")),
        ("-isystem", out / "include", _compile(f"-isystem {out / 'include'}")),
        ("-LIBPATH:", cache, f"lld-link x.obj -LIBPATH:{cache}"),
        ("-L", out / "lib", f"ld.lld x.o -L{out / 'lib'}"),
    ):
        found = _check_artifacts(tmp_path, f"{_compile()}\n{line}", [cache, out])
        assert [v.message for v in found] == [
            f"{'compile' if flag in ('-I', '-isystem') else 'link'} {flag} {path.resolve()} is in "
            f"the build's own cache or prefix, which supply only {ARTIFACT_KINDS}"
        ]
    # A `..` escape from the nested cache into the repository (an allowed root) still fails,
    # also after an allowed spelling of the same file, in either order.
    for escaped in (cache / ".." / ".." / "stray.obj", cache / ".." / "sibling" / "x.lib"):
        message = (
            f"link input {escaped} escapes the build's own cache or prefix to {escaped.resolve()}"
        )
        for inputs in (
            f"{escaped}",
            f"{escaped.resolve()} {escaped}",
            f"{escaped} {escaped.resolve()}",
        ):
            found = _check_artifacts(tmp_path, f"{_compile()}\nlld-link {inputs}", [cache, out])
            assert [v.message for v in found] == [message], inputs


TREE = "a6fb089e932f705ef1065695b36c6e90"  # as observed: `-I <cache>/o/<this>` on 256 compiles


def _include_tree_check(tmp_path: Path, line: str, cache: Path, out: Path) -> list[Violation]:
    repo = tmp_path / "UzPainter"
    repo.mkdir(exist_ok=True)
    allowed = [ZIG_DIR, ZIG_DIR / "lib", CACHE, SDK]
    return build_path_violations(
        f"{_compile()}\n{line}", repo, repo, allowed, [CACHE / "p"], (), [cache, out], cache
    )


def test_build_artifact_roots_admit_only_zigs_empty_include_trees(tmp_path: Path) -> None:
    """Zig's `Module.linkLibrary` adds `-I <cache>/o/<32 hex>`, the library's emitted include
    tree, empty because build.zig installs no header. Only that shape passes: a `-I` folder
    holding a header, missing, named otherwise, nested deeper, in the prefix, the cache root, a
    junction, or spelled through a junction fails; so do `-isystem`, `-iquote` and
    `-LIBPATH:`/`-L` of the empty tree, and the empty tree itself when no cache is named."""
    work = _work(tmp_path)
    cache, out = work / "cache", work / "out"
    tree = cache / "o" / TREE
    full, misnamed = cache / "o" / ("f" * 32), cache / "o" / "tree"
    deeper, in_out = tree / ("c" * 32), out / "o" / TREE
    for folder in (tree, full, misnamed, in_out):
        folder.mkdir(parents=True)
    (full / "engine.h").write_text("#pragma once\n", "utf-8")
    assert _include_tree_check(tmp_path, _compile(f"-I {tree}"), cache, out) == []
    assert _include_tree_check(tmp_path, _compile(f"-I{tree}"), cache, out) == []
    refused = [
        ("compile", "-I", full, _compile(f"-I {full}")),
        ("compile", "-I", cache / "o" / ("e" * 32), _compile(f"-I {cache / 'o' / ('e' * 32)}")),
        ("compile", "-I", misnamed, _compile(f"-I {misnamed}")),
        ("compile", "-I", deeper, _compile(f"-I {deeper}")),
        ("compile", "-I", in_out, _compile(f"-I {in_out}")),
        ("compile", "-I", cache, _compile(f"-I {cache}")),
        ("compile", "-I", cache / "o", _compile(f"-I {cache / 'o'}")),
        ("compile", "-isystem", tree, _compile(f"-isystem {tree}")),
        ("compile", "-iquote", tree, _compile(f"-iquote {tree}")),
        ("link", "-LIBPATH:", tree, f"lld-link x.obj -LIBPATH:{tree}"),
        ("link", "-L", tree, f"ld.lld x.o -L {tree}"),
    ]
    winapi = pytest.importorskip("_winapi")
    linked = cache / "o" / ("d" * 32)
    winapi.CreateJunction(str(tree), str(linked))
    refused.append(("compile", "-I", linked, _compile(f"-I {linked}")))
    for kind, flag, path, line in refused:
        found = _include_tree_check(tmp_path, line, cache, out)
        assert [v.message for v in found] == [
            f"{kind} {flag} {path.resolve()} is in the build's own cache or prefix, which supply "
            f"only {ARTIFACT_KINDS}"
        ], line
    repo = tmp_path / "UzPainter"
    unnamed = build_path_violations(
        f"{_compile()}\n{_compile(f'-I {tree}')}", repo, repo, [ZIG_DIR], [], (), [cache, out]
    )
    assert len(unnamed) == 1, unnamed
    # Spelled through a junction to the work folder: the spelling has a link on the way.
    winapi.CreateJunction(str(work), str(tmp_path / "work-link"))
    through = tmp_path / "work-link" / "cache" / "o" / TREE
    found = _include_tree_check(tmp_path, _compile(f"-I {through}"), cache, out)
    assert len(found) == 1, found
    # A `..` in the spelling (through a junction, or not) is refused even when it lands on it.
    for spelled in (linked / ".." / TREE, misnamed / ".." / TREE):
        found = _include_tree_check(tmp_path, _compile(f"-I {spelled}"), cache, out)
        assert len(found) == 1, (spelled, found)


def test_relative_artifact_roots_through_a_linked_folder_keep_escapes_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Roots given relative to the current folder, through a junction to the real work folder,
    still catch a `..` escape spelled through the junction into the repository."""
    winapi = pytest.importorskip("_winapi")
    real = tmp_path / "real"
    repo, cache = real / "UzPainter", real / "work" / "cache"
    for folder in (repo, cache, real / "work" / "out"):
        folder.mkdir(parents=True)
    winapi.CreateJunction(str(real), str(tmp_path / "alias"))
    monkeypatch.chdir(tmp_path)
    roots = [Path("alias/work/cache"), Path("alias/work/out")]
    escaped = tmp_path / "alias" / "work" / "cache" / ".." / ".." / "UzPainter" / "x.obj"
    found = build_path_violations(
        f"{_compile()}\nlld-link {escaped}", repo, repo, [ZIG_DIR], [], (), roots
    )
    assert [v.message for v in found] == [
        f"link input {escaped} escapes the build's own cache or prefix to {escaped.resolve()}"
    ]


def test_build_artifact_paths_stay_inside_the_root_they_name(tmp_path: Path) -> None:
    """A path spelled under the cache that resolves into the prefix, or the other way round,
    escapes its root and fails, though the other root would admit it."""
    work = _work(tmp_path)
    cache, out = work / "cache", work / "out"
    for escaped in (cache / ".." / "out" / "x.obj", out / ".." / "cache" / "o" / "y.lib"):
        found = _check_artifacts(tmp_path, f"{_compile()}\nlld-link {escaped}", [cache, out])
        assert [v.message for v in found] == [
            f"link input {escaped} escapes the build's own cache or prefix to {escaped.resolve()}"
        ]


def test_unquoted_path_with_spaces_whose_head_is_the_repository_is_refused(
    tmp_path: Path,
) -> None:
    """`<repo> evil\\include`, a folder beside the repository whose name is the repository's
    plus a space, prints as the repository followed by a relative tail: the head alone would
    pass, so the tail is refused as ambiguous, for separate and joined flags and for inputs."""
    repo = tmp_path / "UzPainter"
    outside = tmp_path / "UzPainter evil"
    (outside / "include").mkdir(parents=True)
    (repo / "evil").mkdir(parents=True)  # the tail even exists inside the repository
    tail = Path("evil") / "include"
    for kind, previous, line in (
        ("compile", str(repo), _compile(f"-I {outside / 'include'}")),
        ("compile", f"-I{repo}", _compile(f"-I{outside / 'include'}")),
        ("compile", str(repo), _compile(f"-isystem {outside / 'include'}")),
        ("link", f"-LIBPATH:{repo}", f"lld-link x.obj -LIBPATH:{outside / 'include'}"),
        ("link", str(repo), f"ld.lld x.o -L {outside / 'include'}"),
    ):
        found = _check(tmp_path, f"{_compile()}\n{line}", repo)
        assert [v.message for v in found] == [
            f"{kind} argument {str(tail)!r} after {previous!r} is ambiguous: Zig prints the "
            "command unquoted, so it may continue a path with spaces"
        ], line
    lib = outside / "include" / "x.lib"
    found = _check(tmp_path, f"{_compile()}\nlld-link a.obj {lib}", repo)
    assert [v.message for v in found] == [
        f"link argument {str(Path('evil') / 'include' / 'x.lib')!r} after {str(repo)!r} is "
        "ambiguous: Zig prints the command unquoted, so it may continue a path with spaces"
    ]
    # A relative input right after an absolute one may be its tail (`<repo>\x.lib evil.lib`).
    head = repo / "x.lib"
    found = _check(tmp_path, f"{_compile()}\nlld-link {head} evil.lib", repo)
    assert [v.message for v in found] == [
        f"link argument 'evil.lib' after {str(head)!r} is ambiguous: Zig prints the command "
        "unquoted, so it may continue a path with spaces"
    ]
    # Ordinary relative values after an option and a run of linker inputs stay accepted.
    plain = f"{_compile('-I thirdparty/spdlog/include', '-target x86_64-windows-gnu')}\n"
    assert _check(tmp_path, f"{plain}lld-link a.obj b.lib c.res -OUT:x.exe", repo) == []


def test_a_repository_path_with_spaces_stays_whole(tmp_path: Path) -> None:
    """A checkout at `...\\UzPainter work` is kept whole like the toolchain roots, so its own
    include and library paths pass and are not split into an ambiguous tail."""
    repo = tmp_path / "UzPainter work"
    inc, lib = repo / "thirdparty" / "spdlog" / "include", repo / "lib" / "x.lib"
    log = f"{_compile(f'-I {inc}', f'-I{inc}')}\nlld-link {lib} -LIBPATH:{repo / 'lib'}"
    assert _check(tmp_path, log, repo) == []
    sibling = tmp_path / "UzPainter work2" / "include"
    found = _check(tmp_path, _compile(f"-I {sibling}"), repo)
    assert [v.message for v in found] == [
        f"compile -I {sibling.resolve()} is outside the repository, the Zig toolchain and the "
        "Windows SDK"
    ]


# ── Build-log evidence and the command line ────────────────────────────────────────────────

FAKE_HEAD = "a" * 40
FAKE_INPUTS = "b" * 64


def _evidence(work: Path, **change: Any) -> BuildEvidence:
    command = (
        str(ZIG_DIR / "zig.exe"),
        "build",
        *BUILD_STEPS,
        "--cache-dir",
        str(work / "cache"),
        "--prefix",
        str(work / "out"),
        "--verbose-cc",
        "--verbose-link",
    )
    log = "\n".join(
        [
            _compile("-I thirdparty/spdlog/include"),
            f"lld-link {work / 'cache' / 'o' / 'a' / 'main.obj'}",
        ]
    )
    fields: dict[str, Any] = {
        "command": command,
        "commit": FAKE_HEAD,
        "inputs_before": FAKE_INPUTS,
        "inputs_after": FAKE_INPUTS,
        "exit_code": 0,
        "log": log,
    }
    return BuildEvidence(**(fields | change))


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


REGISTRY = (
    '{"current": "env-a", "envelopes": [{"envelope_id": "env-a", "manifest_root": '
    '"parity/manifests"}]}\n'
)
MATRIX = (
    '{"rows": [{"fixture": "tests/native/test_main.py::test_main", '
    '"evidence": ["docs/architecture/evidence.md#heading"]}]}\n'
)


def _sandbox(tmp_path: Path) -> Path:
    """A committed git repository shaped like the build's inputs: the vendored folder, build.zig,
    a native source, the Python facade, the capability generator's JSON (naming one Python test
    fixture and one architecture-evidence file), `docs/prd.md`, an envelope registry whose
    current Tier 0 manifests live outside `parity/envelopes/`, files the build never reads and a
    `.gitignore` for `tmp/`."""
    repo = tmp_path / "sandbox"
    shutil.copytree(VENDORED, repo / VENDORED_DIR)
    for rel, text in (
        ("build.zig", "// build\n"),
        (".gitignore", "tmp/\n"),
        ("src/main.cpp", "int main() { return 0; }\n"),
        ("tests/native/test_main.cpp", "int test() { return 0; }\n"),
        ("tests/native/test_main.py", "def test_main():\n    pass\n"),
        ("tests/other/test_other.py", "\n"),
        ("python/uzpainter/__init__.py", "\n"),
        ("tools/capabilities/operation-matrix.json", MATRIX),
        ("docs/prd.md", "# PRD\n"),
        ("docs/architecture/evidence.md", "# Heading\n"),
        ("docs/notes.md", "notes\n"),
        ("parity/envelopes/registry.json", REGISTRY),
        ("parity/manifests/tier0/golden.json", "{}\n"),
        ("parity/reports/phase1/report.md", "report\n"),
        (".rulebook/tasks/task.md", "task\n"),
    ):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, "utf-8", newline="\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "sandbox")
    return repo


def test_build_log_evidence_round_trip(tmp_path: Path) -> None:
    work = _work(tmp_path)
    build = _evidence(work)
    write_build_log(work / "build.log", build)
    assert read_build_log(work / "build.log") == build
    log, cache, out = work / "build.log", work / "cache", work / "out"
    assert evidence_problems(build, log, cache, out, FAKE_HEAD, FAKE_INPUTS) == []


def test_old_or_edited_build_logs_are_refused(tmp_path: Path) -> None:
    """A log without the evidence line (the old format) or edited after it was written fails."""
    log = tmp_path / "build.log"
    log.write_text(_compile() + "\n", "utf-8")
    with pytest.raises(ValueError, match="no uzpainter-build-evidence line"):
        read_build_log(log)
    write_build_log(log, _evidence(_work(tmp_path)))
    written = log.read_bytes()
    log.write_bytes(written + b"lld-link D:/elsewhere/x.lib\n")
    with pytest.raises(ValueError, match="the log was edited"):
        read_build_log(log)
    # The checksum covers the evidence fields too: a failed build relabelled as passing fails.
    log.write_bytes(written.replace(b'"exit_code": 0', b'"exit_code": 1', 1))
    assert b'"exit_code": 1' in log.read_bytes()
    with pytest.raises(ValueError, match="the log was edited"):
        read_build_log(log)


def test_build_log_evidence_problems(tmp_path: Path) -> None:
    """Another commit, inputs changed during or since the build, a failed build, a non-verbose
    command or other directories fail, each naming the rerun."""
    work = _work(tmp_path)
    log, cache, out = work / "build.log", work / "cache", work / "out"

    def problems(build: BuildEvidence, given_cache: Path = cache) -> list[str]:
        return evidence_problems(build, log, given_cache, out, FAKE_HEAD, FAKE_INPUTS)

    stale = "0" * 40
    assert problems(_evidence(work, commit=stale)) == [
        f"the log built commit {stale}, HEAD is {FAKE_HEAD}; {RERUN}"
    ]
    assert problems(_evidence(work, inputs_before="c" * 64)) == [
        f"the build inputs changed while the build ran; {RERUN}"
    ]
    changed = "c" * 64
    assert problems(_evidence(work, inputs_before=changed, inputs_after=changed)) == [
        f"the build inputs changed since the build (digest {changed}, now {FAKE_INPUTS}); {RERUN}"
    ]
    assert problems(_evidence(work, exit_code=1)) == [
        f"the logged build failed with exit code 1; {RERUN}"
    ]
    quiet = tuple(a for a in _evidence(work).command if a != "--verbose-link")
    assert problems(_evidence(work, command=quiet)) == [
        f"the logged command lacks --verbose-link; {RERUN}"
    ]
    other = tmp_path / "elsewhere" / "cache"
    assert problems(_evidence(work), other) == [
        f"{other} is not {cache.resolve()}, next to the log; {RERUN}",
        f"the logged --cache-dir {cache} is not {other}; {RERUN}",
    ]


def test_build_inputs_digest_follows_every_build_input(tmp_path: Path) -> None:
    """On the same HEAD, an edited, added or deleted build input changes the digest: a native
    source, the Python facade build.zig installs, the generator's JSON, `docs/prd.md`, the
    current Tier 0 manifests, and the evidence Markdown and fixture test the JSON names. Files
    the build never reads (other docs, reports, tests, tasks, ignored scratch, bytecode) do
    not; index flags do not hide an edit; an ignored header under the native scope counts."""
    repo = _sandbox(tmp_path)
    head, clean = git_head(repo), build_inputs_digest(repo)
    for rel in (
        "src/main.cpp",
        "tests/native/test_main.cpp",
        "python/uzpainter/__init__.py",
        "tools/capabilities/operation-matrix.json",
        "docs/prd.md",
        "parity/manifests/tier0/golden.json",
        "docs/architecture/evidence.md",
        "tests/native/test_main.py",
    ):
        file = repo / rel
        original = file.read_bytes()
        file.write_bytes(original + b"\n// edited on the same HEAD\n")
        assert build_inputs_digest(repo) != clean, rel
        file.write_bytes(original)
        assert build_inputs_digest(repo) == clean, rel
    for rel in (
        "docs/notes.md",
        "parity/reports/phase1/report.md",
        "tests/other/test_other.py",
        ".rulebook/tasks/task.md",
    ):
        (repo / rel).write_text("edited elsewhere\n", "utf-8")
        assert build_inputs_digest(repo) == clean, rel
    for added in (repo / "src/new.h", repo / "parity/manifests/tier0/new.json"):
        added.write_text("{}\n", "utf-8")
        assert build_inputs_digest(repo) != clean, added
        added.unlink()
    source = repo / "src/main.cpp"
    original = source.read_bytes()
    for flag in ("--assume-unchanged", "--skip-worktree"):
        _git(repo, "update-index", flag, "src/main.cpp")
        source.write_bytes(original + b"// hidden from git status\n")
        assert build_inputs_digest(repo) != clean, flag
        source.write_bytes(original)
        _git(repo, "update-index", flag.replace("--", "--no-", 1), "src/main.cpp")
    # An ignored header under the native scope is still compiled, so it counts.
    (repo / ".git" / "info" / "exclude").write_text("local_config.h\n", "utf-8")
    ignored = repo / "src" / "local_config.h"
    ignored.write_text("#define LOCAL 1\n", "utf-8")
    with_ignored = build_inputs_digest(repo)
    assert with_ignored != clean
    ignored.write_text("#define LOCAL 2\n", "utf-8")
    assert build_inputs_digest(repo) != with_ignored
    ignored.unlink()
    # Ignored scratch and Python bytecode do not.
    (repo / "tmp").mkdir()
    (repo / "tmp" / "run.log").write_text("log\n", "utf-8")
    (repo / "python" / "uzpainter" / "__pycache__").mkdir()
    (repo / "python" / "uzpainter" / "__pycache__" / "x.cpython-313.pyc").write_bytes(b"\x00")
    (repo / "src" / "stale.pyc").write_bytes(b"\x00")
    assert build_inputs_digest(repo) == clean
    source.unlink()
    assert build_inputs_digest(repo) != clean
    assert git_head(repo) == head


def test_command_line_requires_the_build_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Build validation without `--build-log`, `--build-cache` and `--build-out` is a usage
    error: the check never builds into a temporary folder of its own."""
    work = _work(tmp_path)
    log, cache = str(work / "build.log"), str(work / "cache")
    for argv in (
        [],
        ["--build-log", log],
        ["--build-log", log, "--build-cache", cache],
        ["--no-build", "--build-cache", cache],
    ):
        with pytest.raises(SystemExit) as exit_info:
            main(argv)
        assert exit_info.value.code == 2, argv
    assert "needs --build-log, --build-cache and --build-out" in capsys.readouterr().err


@pytest.mark.skipif(ZIG is None, reason="zig is not on PATH")
def test_command_line_checks_the_build_log_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing log fails; a log of another commit fails; a same-run log whose link inputs come
    from exactly the cache and prefix named on the command line passes; after a native source
    is edited on the same HEAD the same log fails and names the rerun."""
    repo = _sandbox(tmp_path)
    work = _work(tmp_path)
    log = work / "build.log"
    argv = [
        "--repo-root",
        str(repo),
        "--build-log",
        str(log),
        "--build-cache",
        str(work / "cache"),
        "--build-out",
        str(work / "out"),
    ]
    assert main(argv) == 1
    err = capsys.readouterr().err
    assert f"[build-path] {log}: FileNotFoundError" in err
    assert RERUN in err
    head, inputs = git_head(repo), build_inputs_digest(repo)
    fresh = {"commit": head, "inputs_before": inputs, "inputs_after": inputs}
    write_build_log(log, _evidence(work, **(fresh | {"commit": "0" * 40})))
    assert main(argv) == 1
    assert f"the log built commit {'0' * 40}" in capsys.readouterr().err
    write_build_log(log, _evidence(work, **fresh))
    log.write_bytes(log.read_bytes() + b"\n")
    assert main(argv) == 1
    err = capsys.readouterr().err
    assert "the log was edited" in err
    assert RERUN in err
    write_build_log(log, _evidence(work, **fresh))
    assert main(argv) == 0, capsys.readouterr().err
    assert "build paths checked" in capsys.readouterr().out
    source = repo / "src/main.cpp"
    source.write_bytes(source.read_bytes() + b"// edited on the same HEAD\n")
    assert main(argv) == 1
    err = capsys.readouterr().err
    assert "the build inputs changed since the build" in err
    assert RERUN in err
