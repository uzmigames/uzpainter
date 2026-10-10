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
from typing import Any

import pytest
import yaml

from tools.vendoring.hashing import sha256_hex
from tools.vendoring.manifest import verbatim_entry
from tools.vendoring.modifications import notice
from tools.vendoring.subset import VENDORED_DIR
from tools.vendoring.vendor_check import (
    Violation,
    build_path_violations,
    collect_build_paths,
    folder_violations,
    main,
    zig_toolchain,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDORED = REPO_ROOT / VENDORED_DIR
ZIG = shutil.which("zig")
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "parity.yml"
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
def test_full_check_with_build_passes(capsys: pytest.CaptureFixture[str]) -> None:
    """Spec scenario "Clean tree passes in CI": folder rules and the build-path rule over a fresh
    verbose build of `build.zig` exit zero."""
    assert main([]) == 0, capsys.readouterr().err
    assert "build paths checked" in capsys.readouterr().out


def test_check_runs_in_the_hosted_ci_lane() -> None:
    """2.8: the hosted CPU lane runs the full check (build included, with the pinned Zig) on
    every push to `main` and every pull request into it, before the other gates."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow[True]  # PyYAML reads the `on` key as the boolean True
    assert {"push", "pull_request"} <= set(triggers)
    hosted = workflow["jobs"]["hosted"]
    assert hosted["runs-on"] == "windows-latest"
    steps = hosted["steps"]
    zig = next(s for s in steps if str(s.get("uses", "")).startswith("mlugg/setup-zig@"))
    assert str(zig["with"]["version"]) == "0.15.2"
    runs = [s.get("run", "") for s in steps]
    check = runs.index("python -m tools.vendoring.vendor_check")
    assert steps.index(zig) < check < runs.index("python -m pytest")


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
