"""Tests of phase1.4_render-core-layer (P1-CORE, `docs/dag.md`): the integration of the four
render-layer children (`src/render/`, `docs/architecture/13-engine-integration.md` §4.1, §7).

- The UV raster on the plane, sphere and bevelled cube of the Tier 0 corpus
  (`parity/TIER0-SEMANTICS.md` §2) and the `TextureReadback` drain behind a kernel compiled
  through the kernel cache run `uzp-render-tests.exe`; they skip under `UZP_NO_GPU=1` (hosted CI,
  decision 028) and run on the owner's DX12 hardware adapter otherwise.
- The backend-neutral interface check runs anywhere: no header of the render layer reaches a DX12,
  DXGI or Vulkan header, so callers above the layer compile without backend headers.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from tests.render.test_core_device_kernels import run_case

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE = REPO_ROOT / "thirdparty" / "uzengine-render-core"

TIER0_MESHES = {
    "plane": REPO_ROOT / "parity" / "fixtures" / "meshes" / "plane.obj",
    "sphere": REPO_ROOT / "parity" / "fixtures" / "tier0-semantics" / "meshes" / "sphere.obj",
    "bevelled-cube": REPO_ROOT
    / "parity"
    / "fixtures"
    / "tier0-semantics"
    / "meshes"
    / "bevelled-cube.obj",
}

# The include search path of `uzp-render-tests` and `UzPainter.exe` for the render layer, in
# `build.zig` order (`src/`, `core_include_dirs`, `thirdparty_include_dirs`).
INCLUDE_DIRS = [
    REPO_ROOT / "src",
    *(
        CORE / d
        for d in (
            ".",
            "engine/logging",
            "engine/assertions",
            "engine/profiling",
            "engine/math",
            "engine/rhi",
            "engine/shader",
            "engine/paths",
            "platform/windows",
            "engine/rhi/dx12",
            "engine/rhi/vulkan",
        )
    ),
    *(
        REPO_ROOT / "thirdparty" / d
        for d in (
            "spdlog/include",
            "tracy/public",
            "directxmath/Inc",
            "spirv-reflect",
            "spirv-reflect/include",
            "vulkan-headers/include",
            "volk",
            "vma/include",
            "d3d12ma/include",
            "d3d12ma/src",
            "directx-headers/include",
            "directx-headers/include/directx",
            "agility/build/native/include",
            "dxc/inc",
        )
    ),
]

# Folders whose headers are DX12, DXGI or Vulkan headers.
BACKEND_DIRS = [
    CORE / "engine" / "rhi" / "dx12",
    CORE / "engine" / "rhi" / "vulkan",
    *(
        REPO_ROOT / "thirdparty" / d
        for d in ("directx-headers", "agility", "vulkan-headers", "volk", "vma", "d3d12ma")
    ),
]
# System headers of the backends (found in the Windows SDK when not in the repository).
BACKEND_SYSTEM = re.compile(r"^(d3d12|d3dcommon|dxgi|d3dx12|vulkan|wrl)", re.IGNORECASE)
INCLUDE = re.compile(r'^\s*#\s*include\s*([<"])([^>"]+)[>"]', re.MULTILINE)


def _resolve(name: str, quoted: bool, including: Path) -> Path | None:
    candidates = ([including.parent] if quoted else []) + INCLUDE_DIRS
    for directory in candidates:
        path = directory / name
        if path.is_file():
            return path.resolve()
    return None


def _backend_headers(header: Path) -> list[str]:
    """The backend headers `header` reaches through its includes, as `<chain>` strings."""
    found: list[str] = []
    seen: set[Path] = set()
    stack: list[tuple[Path, str]] = [(header.resolve(), header.name)]
    while stack:
        path, chain = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        for quote, name in INCLUDE.findall(text):
            target = _resolve(name, quote == '"', path)
            link = f"{chain} -> {name}"
            if target is None:
                if BACKEND_SYSTEM.match(Path(name).name):
                    found.append(link)
                continue
            if any(target.is_relative_to(d.resolve()) for d in BACKEND_DIRS):
                found.append(link)
                continue
            stack.append((target, link))
    return found


def test_render_layer_headers_are_backend_neutral() -> None:
    """2.5, spec "Caller compiled without backend headers": no header of `src/render/` reaches a
    DX12, DXGI or Vulkan header (directly or through the vendored RHI headers), so the
    compositor and exporter compile against the layer without backend headers."""
    headers = sorted((REPO_ROOT / "src" / "render").glob("*.h"))
    assert headers
    leaks = {h.name: chains for h in headers if (chains := _backend_headers(h))}
    assert not leaks, leaks


def test_backend_header_detection() -> None:
    """The check above detects a backend header: the vendored DX12 device header reaches one."""
    assert _backend_headers(CORE / "engine" / "rhi" / "dx12" / "dx12_device.h")


def test_tier0_meshes_rasterise_on_dx12(render_tests: Path, tmp_path: Path) -> None:
    """3.1: the plane, sphere and bevelled cube of the Tier 0 corpus rasterise on the DX12
    adapter with the conservative mask and texel-centre coverage equal to the double-precision
    reference, at a square and a non-square size; the plane covers every texel centre."""
    meshes = tmp_path / "tier0-meshes"
    meshes.mkdir()
    for name, source in TIER0_MESHES.items():
        shutil.copyfile(source, meshes / f"{name}.obj")
    passed, _ = run_case(render_tests, "uv-raster-tier0", tmp_path)
    for name in TIER0_MESHES:
        assert f"{name}.obj loads" in passed
        for size in ("512x512", "300x200"):
            label = f"{name} {size}"
            assert {
                f"{label}: rasterises",
                f"{label}: the conservative mask covers every texel a triangle touches",
                f"{label}: the conservative mask marks no untouched texel",
                f"{label}: the conservative mask contains the texel-centre coverage",
                f"{label}: texel-centre coverage equals the reference",
            } <= passed
    assert {"plane 512x512: every texel centre is covered"} <= passed
    assert {"plane 300x200: every texel centre is covered"} <= passed


def test_readback_drain_behind_cached_kernel(render_tests: Path, tmp_path: Path) -> None:
    """3.2: end to end on DX12: a kernel compiled through the kernel cache is dispatched into
    eight textures, 64 readbacks of them drain in submission order with every texel bit-exact,
    no staging buffer remains, and the dispatched kernel is in the cache folder."""
    passed, _ = run_case(render_tests, "readback-kernel", tmp_path)
    assert {
        "the ramp kernel compiles through the kernel cache",
        "the cached kernel is dispatched into eight textures",
        "64 readbacks of the dispatched textures are in flight at once",
        "the drain reports every request in submission order",
        "every drained texel equals the IEEE-strict CPU value bit for bit",
        "after the drain no request is outstanding and no staging buffer remains",
        "the dispatched DXIL kernel is in the kernel cache folder",
    } <= passed
