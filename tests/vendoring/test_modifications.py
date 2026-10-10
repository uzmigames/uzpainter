"""Tests of phase0.3_vendor-modifications: UzPainter's own static-library build of the vendored
render core (`build.zig`) and the local modifications UZP-MOD-001…006, UZP-MOD-008 and
UZP-MOD-009 (`thirdparty/uzengine-render-core/MODIFICATIONS.md`; UZP-MOD-009 is covered by
`tests/render/test_core_readback.py`).

The native cases run `uzp-vendor-tests.exe` (`tests/native/vendor_modifications_test.cpp`),
built once per module from a fresh cache so the build log lists every compile and link
command. Cases that need a DX12 or Vulkan adapter skip when the executable reports none
(exit code 77) or when `UZP_NO_GPU=1` (set by hosted CI, decision 028); on the owner's machine
they run on the hardware adapter.
"""

from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from tools.vendoring import git
from tools.vendoring.citations import failing_citations
from tools.vendoring.closure import compute_closure
from tools.vendoring.manifest import load
from tools.vendoring.modifications import (
    UPSTREAM_CITATIONS,
    cited_locations,
    load_log,
    problems,
)
from tools.vendoring.subset import HEADER_ONLY, INCLUDE_DIRS, VENDORED_DIR, expand_seeds
from tools.vendoring.thirdparty import LIBRARY_BY_NAME, compiled_sources

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDORED = REPO_ROOT / VENDORED_DIR
SELECTED_COMMIT = "380c142e481d56fe16b045f63315b42359e86a7d"
UZENGINE_REPO = Path(os.environ.get("UZENGINE_REPO", r"E:\UzmiGames\UzEngine"))
ZIG = shutil.which("zig")
PINNED_ZIG = "0.15.2"
EXIT_SKIP = 77
# Native cases that create a DX12 or Vulkan device, and the flag hosted CI sets (no GPU).
ADAPTER_CASES = frozenset({"factory", "fence", "agility"})
NO_GPU_ENV = "UZP_NO_GPU"
TEST_SOURCE = REPO_ROOT / "tests" / "native" / "vendor_modifications_test.cpp"
ABSOLUTE_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"'<>|]*")


@dataclass(frozen=True)
class Build:
    log: str
    prefix: Path

    @property
    def exe(self) -> Path:
        return self.prefix / "bin" / "uzp-vendor-tests.exe"

    def compile_commands(self) -> list[list[str]]:
        """Token lists of the `zig clang` commands in the `--verbose-cc` log."""
        commands = []
        for line in self.log.splitlines():
            tokens = line.removeprefix("error: ").split()
            if (
                len(tokens) > 2
                and tokens[0].lower().endswith(("zig.exe", "zig"))
                and (tokens[1] in ("clang", "clang++"))
            ):
                commands.append(tokens)
        return commands


@pytest.fixture(scope="module")
def build() -> Iterator[Build]:
    """`zig build render-core native-tests` from a fresh local cache inside the repository."""
    if ZIG is None:
        pytest.skip("zig is not on PATH")
    work = REPO_ROOT / ".zig-cache" / f"standalone-{uuid.uuid4().hex[:12]}"
    try:
        proc = subprocess.run(
            [
                ZIG,
                "build",
                "render-core",
                "native-tests",
                "--cache-dir",
                str(work / "cache"),
                "--prefix",
                str(work / "out"),
                "--verbose-cc",
                "--verbose-link",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
            check=False,
        )
        log = proc.stdout + proc.stderr
        assert proc.returncode == 0, log[-6000:]
        yield Build(log=log, prefix=work / "out")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _toolchain_dirs() -> list[Path]:
    """Zig's own installation and global cache, as `zig env` reports them."""
    assert ZIG is not None
    env = subprocess.run(
        [ZIG, "env"], capture_output=True, text=True, check=True, timeout=60
    ).stdout
    dirs = [Path(ZIG).resolve().parent]
    for key in ("lib_dir", "global_cache_dir"):
        match = re.search(rf'\.{key} = "([^"]+)"', env)
        assert match, f"zig env has no {key}"
        dirs.append(Path(match.group(1).replace("\\\\", "\\")).resolve())
    return dirs


def _inside(path: Path, roots: list[Path]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def _run(build: Build, cwd: Path, *args: str) -> tuple[set[str], list[str], str]:
    """Run one native case; return the passed checks, the failed checks and the output.

    Cases that create a DX12 or Vulkan device skip under `UZP_NO_GPU=1` (hosted CI has no
    GPU, decision 028); they run on the owner's machine."""
    if args[0] in ADAPTER_CASES and os.environ.get(NO_GPU_ENV) == "1":
        pytest.skip(
            f"{NO_GPU_ENV}=1: `{' '.join(args)}` needs a DX12/Vulkan hardware adapter; "
            "run it locally on the owner's machine (decision 028)"
        )
    proc = subprocess.run(
        [str(build.exe), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    output = proc.stdout + proc.stderr
    if proc.returncode == EXIT_SKIP:
        pytest.skip(f"no adapter for `{' '.join(args)}`: {output.strip()}")
    passed = {line[5:] for line in proc.stdout.splitlines() if line.startswith("PASS ")}
    failed = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
    assert proc.returncode == 0 and not failed, output
    return passed, failed, output


# ── Build (3.1) ────────────────────────────────────────────────────────────────────────────


def test_zig_release_is_pinned() -> None:
    """build.zig.zon and build.zig pin Zig 0.15.2; the installed compiler is that release."""
    zon = (REPO_ROOT / "build.zig.zon").read_text(encoding="utf-8")
    assert f'.minimum_zig_version = "{PINNED_ZIG}"' in zon
    script = (REPO_ROOT / "build.zig").read_text(encoding="utf-8")
    assert ".major = 0, .minor = 15, .patch = 2" in script
    assert "@compileError" in script
    if ZIG is None:
        pytest.skip("zig is not on PATH")
    version = subprocess.run(
        [ZIG, "version"], capture_output=True, text=True, check=True, timeout=60
    ).stdout.strip()
    assert version == PINNED_ZIG


def test_standalone_static_library_build(build: Build) -> None:
    """3.1: the static library and the test executable build from UzPainter's own build.zig;
    every source, include and library path in the build log is inside the repository (or is
    the pinned Zig toolchain itself), and nothing names a UzEngine checkout."""
    assert (build.prefix / "lib" / "uzrendercore.lib").is_file()
    assert build.exe.is_file()
    assert not (REPO_ROOT / ".gitmodules").exists()
    assert "runtime.lib" not in build.log

    repo = REPO_ROOT.resolve()
    toolchain = _toolchain_dirs()
    uzengine = UZENGINE_REPO.resolve()
    outside: set[str] = set()
    for match in ABSOLUTE_PATH_RE.finditer(build.log):
        path = Path(match.group(0).rstrip(".,;:)")).resolve()
        assert not _inside(path, [uzengine]), f"build log names the UzEngine checkout: {path}"
        if not _inside(path, [repo, *toolchain]):
            outside.add(str(path))
    assert outside == set()

    commands = build.compile_commands()
    compiled: set[Path] = set()
    for tokens in commands:
        source = Path(tokens[2]).resolve()
        compiled.add(source)
        includes = [Path(tokens[i + 1]).resolve() for i, t in enumerate(tokens) if t == "-I"]
        assert includes, f"no include path for {source}"
        assert all(_inside(p, [repo]) and p.is_dir() for p in includes), includes
        assert not any(t.startswith(("-DTRACY_ENABLE", "-DUZ_PROFILING_ENABLED")) for t in tokens)
        if source.suffix == ".cpp":
            assert "-std=c++23" in tokens, source
            assert "-DSPDLOG_COMPILED_LIB" in tokens, source

    manifest = load(VENDORED / "MANIFEST.json")
    vendored_sources = {
        (REPO_ROOT / e.vendored_path).resolve()
        for e in manifest.files
        if e.vendored_path.endswith(".cpp")
    }
    # volk's implementation is compiled through vulkan_device.cpp (VOLK_IMPLEMENTATION).
    thirdparty_sources = {
        (REPO_ROOT / "thirdparty" / s).resolve() for s in compiled_sources() if s != "volk/volk.c"
    }
    vulkan_device = (VENDORED / "engine/rhi/vulkan/vulkan_device.cpp").read_text(encoding="utf-8")
    assert "#define VOLK_IMPLEMENTATION" in vulkan_device
    expected = vendored_sources | thirdparty_sources | {TEST_SOURCE.resolve()}
    assert compiled == expected
    assert len(commands) == len(expected)
    for banned in ("/dx11/", "/metal/", "engine/config/", "engine/core/cvar"):
        assert not any(banned in p.as_posix() for p in compiled), banned


# ── UZP-MOD-001 / UZP-MOD-002 (3.2) ───────────────────────────────────────────────────────


def test_no_engine_config_or_cvar_include() -> None:
    """3.2: with no include cut at all, the vendored subset's closure is exactly its manifest
    and no compiled source reaches `config.h`, `cvar.h` or a DX11/Metal header."""
    manifest = load(VENDORED / "MANIFEST.json")
    expected = {e.vendored_path.removeprefix(f"{VENDORED_DIR}/") for e in manifest.files}
    result = compute_closure(VENDORED, expand_seeds(VENDORED), INCLUDE_DIRS, (), HEADER_ONLY)
    assert result.files == expected
    banned = [
        i
        for i in result.unresolved
        if Path(i.spelling).name in ("config.h", "cvar.h")
        or i.spelling.startswith(("dx11/", "metal/", "engine/config", "engine/core/cvar"))
    ]
    assert banned == []


def test_factory_accepts_only_dx12_and_vulkan(build: Build, tmp_path: Path) -> None:
    """3.2: DX11, Metal and Null are rejected with an explicit error; DX12 and Vulkan devices
    are created."""
    passed, _, _ = _run(build, tmp_path, "factory")
    for name in ("DX11", "Metal", "Null"):
        assert f"factory rejects {name}" in passed
        assert f"factory reports {name} as unsupported" in passed
    for name in ("DX12", "Vulkan"):
        assert f"factory creates {name}" in passed
        assert f"factory does not reject {name}" in passed


# ── UZP-MOD-003 (3.3) ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("backend", ["dx12", "vulkan"])
def test_fence_wait_is_bounded_and_truthful(build: Build, tmp_path: Path, backend: str) -> None:
    """3.3: a never-signalled fence returns `timeout` at its one-second deadline, a signalled
    fence returns `signaled`, and an injected device loss returns `device_lost` with the
    backend's reason (DX12 `ID3D12Device5::RemoveDevice`; Vulkan `VK_ERROR_DEVICE_LOST`
    injected through volk's function table)."""
    passed, _, _ = _run(build, tmp_path, "fence", backend)
    lost = "removed device" if backend == "dx12" else "VK_ERROR_DEVICE_LOST"
    for check in (
        f"{backend} never-signalled fence returns timeout",
        f"{backend} timeout returns at the one-second deadline",
        f"{backend} signalled fence returns signaled",
        f"{backend} {lost} returns device_lost",
        f"{backend} device_lost returns before the deadline",
    ):
        assert check in passed, check
    reason = (
        "dx12 device_lost carries the device-removed reason"
        if backend == "dx12"
        else "vulkan device_lost carries VK_ERROR_DEVICE_LOST"
    )
    assert reason in passed


# ── UZP-MOD-004 (3.4) ─────────────────────────────────────────────────────────────────────


def test_inline_ray_query_decision(build: Build, tmp_path: Path) -> None:
    """3.4: ray queries are reported for DXR Tier 1.1 + SM 6.6, not for Tier 1.0 or SM < 6.6."""
    passed, _, _ = _run(build, tmp_path, "rayquery-decision")
    assert "ray query reported for Tier 1.1 + SM 6.6" in passed
    assert "ray query not reported for Tier 1.0 + SM 6.6" in passed
    assert "ray query not reported for Tier 1.1 + SM 6.5" in passed
    assert len(passed) == 7


# ── UZP-MOD-005 (3.5) ─────────────────────────────────────────────────────────────────────


def test_agility_runtime_loads_from_d3d12_subfolder(build: Build, tmp_path: Path) -> None:
    """3.5: with D3D12Core.dll in D3D12\\ beside the executable, the device factory is created
    for that folder, the runtime is loaded from it, and it is the pinned SDK release."""
    passed, _, output = _run(build, tmp_path, "agility")
    assert "device factory created from D3D12\\" in passed
    assert "Agility runtime loaded from D3D12\\D3D12Core.dll" in passed
    assert "exe exports D3D12SDKPath .\\D3D12\\" in passed
    pinned = LIBRARY_BY_NAME["Agility SDK"].version
    version = re.search(r"^INFO AGILITY_VERSION (\S+)$", output, re.MULTILINE)
    assert version is not None
    assert version.group(1) == f"{pinned}.0"
    header = (REPO_ROOT / "thirdparty/agility/build/native/include/d3d12.h").read_text(
        encoding="utf-8", errors="replace"
    )
    sdk = re.search(r"#define\s+D3D12_SDK_VERSION\s+\(\s*(\d+)\s*\)", header)
    built = re.search(r"^INFO D3D12_SDK_VERSION (\d+)$", output, re.MULTILINE)
    assert sdk is not None and built is not None
    assert built.group(1) == sdk.group(1)


# ── UZP-MOD-006 (3.6) ─────────────────────────────────────────────────────────────────────

SPIRV_MAGIC = 0x07230203
SPIRV_1_5 = 0x00010500
OP_EXTENSION = 10
OP_CAPABILITY = 17
CAPABILITY_RAY_QUERY_KHR = 4472


def _spirv_module(path: Path) -> tuple[int, set[int], set[str]]:
    """Version word, declared capabilities and extensions of a SPIR-V module."""
    data = path.read_bytes()
    words = struct.unpack(f"<{len(data) // 4}I", data)
    assert words[0] == SPIRV_MAGIC
    capabilities: set[int] = set()
    extensions: set[str] = set()
    index = 5
    while index < len(words):
        count, opcode = words[index] >> 16, words[index] & 0xFFFF
        assert count > 0
        if opcode == OP_CAPABILITY:
            capabilities.add(words[index + 1])
        elif opcode == OP_EXTENSION:
            literal = data[(index + 1) * 4 : (index + count) * 4]
            extensions.add(literal.split(b"\0", 1)[0].decode("ascii"))
        index += count
    return words[1], capabilities, extensions


def test_spirv_targets_vulkan_1_2_with_ray_query(build: Build, tmp_path: Path) -> None:
    """3.6: compute kernels compiled to SPIR-V carry the SPIR-V 1.5 header of `vulkan1.2`;
    with ray queries requested the module declares SPV_KHR_ray_query and RayQueryKHR."""
    out = tmp_path / "spv"
    passed, _, _ = _run(build, tmp_path, "spirv", str(out))
    assert {"plain compiles to SPIR-V", "rayquery compiles to SPIR-V"} <= passed
    version, capabilities, extensions = _spirv_module(out / "plain.spv")
    assert version == SPIRV_1_5
    assert CAPABILITY_RAY_QUERY_KHR not in capabilities
    assert "SPV_KHR_ray_query" not in extensions
    version, capabilities, extensions = _spirv_module(out / "rayquery.spv")
    assert version == SPIRV_1_5
    assert CAPABILITY_RAY_QUERY_KHR in capabilities
    assert "SPV_KHR_ray_query" in extensions


# ── UZP-MOD-008 ───────────────────────────────────────────────────────────────────────────

OP_DECORATE = 71
DECORATION_NO_CONTRACTION = 42
DXIL_FLOAT_OP_RE = re.compile(r"= (fmul|fadd|fsub|fdiv)\b([^%]*)%")


def _no_contraction_count(path: Path) -> int:
    """Number of `OpDecorate <id> NoContraction` instructions in a SPIR-V module."""
    data = path.read_bytes()
    words = struct.unpack(f"<{len(data) // 4}I", data)
    count, index = 0, 5
    while index < len(words):
        length, opcode = words[index] >> 16, words[index] & 0xFFFF
        assert length > 0
        if opcode == OP_DECORATE and words[index + 2] == DECORATION_NO_CONTRACTION:
            count += 1
        index += length
    return count


def _dxil_float_ops(path: Path) -> list[tuple[str, bool]]:
    """(opcode, carries a fast-math flag) of every float arithmetic line of a disassembly."""
    ops = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = DXIL_FLOAT_OP_RE.search(line)
        if match:
            ops.append((match.group(1), "fast" in match.group(2).split()))
    return ops


def test_ieee_strict_arithmetic(build: Build, tmp_path: Path) -> None:
    """UZP-MOD-008: with `ieeeStrict` DXC is passed `-Gis`: DXIL float arithmetic loses its
    fast-math flags and SPIR-V arithmetic is decorated NoContraction; without it the same
    kernel is compiled `fast` (DXIL) and without NoContraction (SPIR-V)."""
    out = tmp_path / "ieee"
    passed, _, _ = _run(build, tmp_path, "ieee", str(out))
    assert {"ieee-off compiles to DXIL", "ieee-on compiles to SPIR-V"} <= passed
    relaxed = _dxil_float_ops(out / "ieee-off.dxil.txt")
    strict = _dxil_float_ops(out / "ieee-on.dxil.txt")
    assert relaxed and all(fast for _, fast in relaxed), relaxed
    assert strict and not any(fast for _, fast in strict), strict
    assert _no_contraction_count(out / "ieee-off.spv") == 0
    assert _no_contraction_count(out / "ieee-on.spv") >= 3


# ── Notices, log and manifest (2.9, 3.7) ──────────────────────────────────────────────────


def test_notices_log_and_manifest_agree() -> None:
    """3.7: every modified file starts with its §4(b) notice, is logged with a covering test
    that exists, and its manifest entry carries the logged ids and its current hash."""
    log = load_log(REPO_ROOT)
    # UZP-MOD-007 (Vulkan acceleration structures) is planned for phase3.3 and not applied yet.
    assert [m.id for m in log] == [f"UZP-MOD-00{n}" for n in (1, 2, 3, 4, 5, 6, 8, 9)]
    manifest = load(VENDORED / "MANIFEST.json")
    assert problems(REPO_ROOT, manifest, log) == []
    modified = {e.vendored_path for e in manifest.files if e.status == "modified"}
    logged = {f"{VENDORED_DIR}/{path}" for m in log for path in m.files}
    assert modified == logged
    for entry in manifest.files:
        if entry.status == "modified":
            assert entry.vendored_sha256 != entry.upstream_sha256, entry.vendored_path


def test_log_citations_hold_at_the_selected_commit(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Every upstream `path:line` the log cites is a checked citation, and each holds on a
    fresh `git archive` of the selected commit."""
    text = (VENDORED / "MODIFICATIONS.md").read_text(encoding="utf-8")
    known = {c.location for c in UPSTREAM_CITATIONS}
    cited = set(cited_locations(text))
    assert cited and cited <= known, cited - known
    if not git.has_commit(UZENGINE_REPO, SELECTED_COMMIT):
        pytest.skip(f"UzEngine commit {SELECTED_COMMIT} not available at {UZENGINE_REPO}")
    export_root = tmp_path_factory.mktemp("uzengine-export")
    git.export(UZENGINE_REPO, SELECTED_COMMIT, ("runtime/engine",), export_root)
    assert failing_citations(export_root / "runtime", UPSTREAM_CITATIONS) == []
