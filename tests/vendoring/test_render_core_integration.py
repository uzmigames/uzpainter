"""Integration acceptance of phase0.5_vendor-render-core (P0-VENDOR, `docs/dag.md`).

The children test their own parts (`test_vendored_core.py`, `test_thirdparty.py`,
`test_modifications.py`, `test_vendor_check.py`). These tests check the gate on the whole tree:

- 3.1: the files `build.zig.zon` declares as the package (`.paths`) are copied to a folder outside
  the repository and built there with fresh local and global Zig caches. Zig's cache manifests
  list every file each compile step read, headers included; every one is inside the copy or the
  pinned Zig release's own `lib` folder, so the build needs nothing else on the machine.
- 3.2: no submodule, no `runtime.lib`, no patch queue, no package dependency (pin) and no path in
  `build.zig` that leaves the repository.

The vendoring check on the integrated tree (3.3) is `test_vendor_check.py`
(`test_full_check_with_build_passes`).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UZENGINE_REPO = Path(os.environ.get("UZENGINE_REPO", r"E:\UzmiGames\UzEngine"))
ZIG = shutil.which("zig")
EXIT_SKIP = 77
NO_GPU_ENV = "UZP_NO_GPU"

# Cache-manifest prefix indices (Zig 0.15 `std.Build.Cache`): 0 = absolute or relative to the
# build root, 1 = Zig's `lib` folder, 2 = the local cache, 3 = the global cache.
PREFIX_ABSOLUTE = "0"
PREFIX_ZIG_LIB = "1"
PREFIX_LOCAL_CACHE = "2"
PREFIX_GLOBAL_CACHE = "3"
MANIFEST_LINE_RE = re.compile(r"^\d+ \d+ \d+ [0-9a-f]{32} (\d+) (.+)$")

# Folders the repository walk skips: version control, build output, tool caches.
SKIPPED_DIRS = frozenset(
    {".git", ".zig-cache", "zig-out", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
)
PATCH_SUFFIXES = (".patch", ".diff")
PATCH_QUEUE_NAMES = frozenset({"patches", "series", ".pc"})


@dataclass(frozen=True)
class RelocatedBuild:
    root: Path
    prefix: Path
    dependencies: list[tuple[str, str]]


def _package_paths() -> list[str]:
    """The `.paths` of `build.zig.zon`: the files and folders that make up the package."""
    zon = (REPO_ROOT / "build.zig.zon").read_text(encoding="utf-8")
    block = re.search(r"\.paths\s*=\s*\.\{(.*?)\}", zon, re.DOTALL)
    assert block, "build.zig.zon has no .paths"
    paths = re.findall(r'"([^"]+)"', block.group(1))
    assert paths
    return paths


def _manifest_dependencies(cache: Path) -> list[tuple[str, str]]:
    """(prefix index, path) of every file listed in the cache's manifests (`h/*.txt`)."""
    deps = []
    for manifest in sorted((cache / "h").glob("*.txt")):
        for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
            match = MANIFEST_LINE_RE.match(line)
            if match:
                deps.append((match.group(1), match.group(2)))
    return deps


@pytest.fixture(scope="module")
def relocated(tmp_path_factory: pytest.TempPathFactory) -> Iterator[RelocatedBuild]:
    """`zig build render-core native-tests` of a copy of the package outside the repository,
    with a local and a global cache that start empty."""
    if ZIG is None:
        pytest.skip("zig is not on PATH")
    work = tmp_path_factory.mktemp("relocated")
    root = work / "uzpainter"
    for rel in _package_paths():
        source = REPO_ROOT / rel
        if source.is_dir():
            shutil.copytree(source, root / rel)
        else:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, root / rel)
    proc = subprocess.run(
        [
            ZIG,
            "build",
            "render-core",
            "native-tests",
            "--cache-dir",
            str(work / "cache"),
            "--global-cache-dir",
            str(work / "global-cache"),
            "--prefix",
            str(work / "out"),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-6000:]
    deps = _manifest_dependencies(work / "cache") + _manifest_dependencies(work / "global-cache")
    yield RelocatedBuild(root=root, prefix=work / "out", dependencies=deps)
    shutil.rmtree(work, ignore_errors=True)


def _inside(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


# ── 3.1 Clean build outside the repository ──────────────────────────────────────────────────


def test_relocated_build_produces_library_and_tests(relocated: RelocatedBuild) -> None:
    assert (relocated.prefix / "lib" / "uzrendercore.lib").is_file()
    bin_dir = relocated.prefix / "bin"
    for name in ("uzp-vendor-tests.exe", "dxcompiler.dll", "dxil.dll", "D3D12/D3D12Core.dll"):
        assert (bin_dir / name).is_file(), name


def test_relocated_build_reads_only_the_copy_and_the_zig_release(
    relocated: RelocatedBuild,
) -> None:
    """Every file a build step read (sources, every included header, libraries) is in the copy,
    in Zig's own `lib` folder or in the build's own caches; none is in the repository or a
    UzEngine checkout."""
    root = relocated.root.resolve()
    prefixes = {index for index, _ in relocated.dependencies}
    assert PREFIX_ABSOLUTE in prefixes and PREFIX_ZIG_LIB in prefixes
    assert prefixes <= {PREFIX_ABSOLUTE, PREFIX_ZIG_LIB, PREFIX_LOCAL_CACHE, PREFIX_GLOBAL_CACHE}

    outside: set[str] = set()
    read: set[Path] = set()
    for index, raw in relocated.dependencies:
        if index != PREFIX_ABSOLUTE:
            continue
        path = Path(raw) if Path(raw).is_absolute() else root / raw
        path = path.resolve()
        read.add(path)
        if not _inside(path, root):
            outside.add(str(path))
    assert outside == set()
    assert not any(_inside(p, UZENGINE_REPO.resolve()) for p in read)
    # The vendored core's headers were among the files read, so the scan covered includes.
    rhi = root / "thirdparty" / "uzengine-render-core" / "engine" / "rhi"
    assert rhi / "rhi_device.h" in read
    assert any(p.suffix == ".h" and _inside(p, root / "thirdparty" / "d3d12ma") for p in read)


def test_relocated_build_runs_on_the_adapter(relocated: RelocatedBuild) -> None:
    """The relocated executable creates DX12 and Vulkan devices (hardware adapter case)."""
    if os.environ.get(NO_GPU_ENV) == "1":
        pytest.skip(f"{NO_GPU_ENV}=1: no GPU on this runner (decision 028)")
    exe = relocated.prefix / "bin" / "uzp-vendor-tests.exe"
    proc = subprocess.run(
        [str(exe), "factory"],
        cwd=exe.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    output = proc.stdout + proc.stderr
    if proc.returncode == EXIT_SKIP:
        pytest.skip(f"no adapter: {output.strip()}")
    assert proc.returncode == 0, output
    assert "PASS factory creates DX12" in proc.stdout
    assert "PASS factory creates Vulkan" in proc.stdout
    assert "FAIL " not in proc.stdout


# ── 3.2 Build inspection ────────────────────────────────────────────────────────────────────


def _walk(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIPPED_DIRS]
        base = Path(dirpath)
        for name in dirnames + filenames:
            yield base / name


def test_no_submodule_runtime_lib_or_patch_queue() -> None:
    found = []
    for path in _walk(REPO_ROOT):
        name = path.name.lower()
        if (
            name in (".gitmodules", "runtime.lib")
            or name.endswith(PATCH_SUFFIXES)
            or name in PATCH_QUEUE_NAMES
        ):
            found.append(path.relative_to(REPO_ROOT).as_posix())
    assert found == []


def test_build_has_no_package_dependency() -> None:
    """No fetched package and therefore no pinned URL or hash: `build.zig.zon` declares no
    dependencies and `build.zig` uses none."""
    zon = (REPO_ROOT / "build.zig.zon").read_text(encoding="utf-8")
    assert re.search(r"\.dependencies\s*=\s*\.\{\s*\}", zon)
    assert ".url" not in zon and ".hash" not in zon
    script = (REPO_ROOT / "build.zig").read_text(encoding="utf-8")
    assert "b.dependency(" not in script and "lazyDependency(" not in script


def test_build_script_paths_stay_in_the_repository() -> None:
    """`build.zig` names files only through `b.path` (relative to the build root): no absolute
    path, no parent-folder step, no `cwd_relative` or system include/library path."""
    script = (REPO_ROOT / "build.zig").read_text(encoding="utf-8")
    code = "\n".join(line.split("//", 1)[0] for line in script.splitlines())
    literals = re.findall(r'"((?:[^"\\]|\\.)*)"', code)
    # A lone "/" is the separator of `core_root ++ "/" ++ dir`, not a path.
    assert not [s for s in literals if re.match(r"^([A-Za-z]:[\\/]|/.|\\\\)", s)]
    assert not [s for s in literals if ".." in s.replace("\\", "/").split("/")]
    for banned in ("cwd_relative", "addSystemIncludePath", "addLibraryPath"):
        assert banned not in code, banned
    # An object file or import library (`python313.lib`) only through `b.path`.
    assert code.count("addObjectFile(") == code.count("addObjectFile(b.path(")
    assert "uzengine" not in code.replace("uzengine-render-core", "").lower()
