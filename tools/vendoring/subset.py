"""The vendored UzEngine render-core subset (`docs/architecture/13-engine-integration.md` §2).

Paths are relative to UzEngine's `runtime/` folder, which is also the layout of
`thirdparty/uzengine-render-core/` (§3.2).
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from pathlib import Path

UPSTREAM_PREFIX = "runtime/"
VENDORED_DIR = "thirdparty/uzengine-render-core"

# Metadata files written by the import; they are not upstream source files (§3.2).
METADATA_FILES = frozenset({"LICENSE", "ORIGIN.md", "MANIFEST.json", "MODIFICATIONS.md"})

# §2.1: every file of these folders (non-recursive) is part of the subset.
SEED_DIRS = (
    "engine/rhi/dx12",
    "engine/rhi/vulkan",
    "engine/math",
)

# §2.1: individual files.
SEED_FILES = (
    # RHI interface and backend factory
    "engine/rhi/rhi.h",
    "engine/rhi/rhi_backend.h",
    "engine/rhi/rhi_device.h",
    "engine/rhi/rhi_command_list.h",
    "engine/rhi/rhi_types.h",
    "engine/rhi/rhi_fence.h",
    "engine/rhi/rhi_swapchain.h",
    "engine/rhi/rhi_resource_pool.h",
    "engine/rhi/rhi_gpu_profiler_types.h",
    "engine/rhi/rhi_frame_limiter.h",
    "engine/rhi/rhi_config.h",
    "engine/rhi/rhi_config.cpp",
    "engine/rhi/rhi_factory.cpp",
    # Shader compilation
    "engine/shader/shader_compiler.h",
    "engine/shader/shader_compiler.cpp",
    "engine/shader/shader_reflection.h",
    "engine/shader/shader_reflection.cpp",
    "engine/shader/shader_cache.h",
    "engine/shader/shader_cache.cpp",
    # Texture format definition (header only)
    "engine/asset/formats/uztexture_format.h",
    # Core utilities
    "engine/logging/log.h",
    "engine/logging/log.cpp",
    "engine/assertions/engine_assert.h",
    "engine/assertions/engine_assert.cpp",
    "engine/profiling/profiler.h",
    "engine/profiling/profiler.cpp",
    "engine/paths/paths.h",
    "engine/paths/paths.cpp",
    # Windows platform
    "platform/platform_types.h",
    "platform/windows/crash_handler.h",
    "platform/windows/crash_handler.cpp",
    "platform/windows/stack_walker.h",
    "platform/windows/stack_walker.cpp",
    "platform/windows/file_system.h",
    "platform/windows/file_system.cpp",
    "platform/windows/platform_window.h",
    "platform/windows/platform_window.cpp",
    "platform/windows/input.h",
    "platform/windows/input.cpp",
)

# §2.1: headers whose `.cpp` is deliberately not vendored (§2.4: the `.uztexture` writer).
HEADER_ONLY = frozenset({"engine/asset/formats/uztexture_format.h"})

# §2.4 / §3.3: paths that must never be present in the vendored folder.
DENYLIST = (
    "engine/asset/importers/**",
    "engine/asset/formats/uzmesh_format.*",
    "engine/asset/formats/uztexture_format.cpp",
    "engine/renderer/**",
    "engine/config/**",
    "engine/core/cvar.*",
    "engine/rhi/dx11/**",
    "engine/rhi/metal/**",
    "engine/rhi/optimization/**",
)

# Include directories of UzEngine's Windows build (`runtime/build.zig`: the runtime root,
# `engine_include_dirs`, `windows_engine_include_dirs`, and the backend folders added with
# `addIncludePath`). Order matters: it is the compiler's search order.
INCLUDE_DIRS = (
    ".",
    "engine",
    "engine/app",
    "engine/logging",
    "engine/assertions",
    "engine/profiling",
    "engine/memory",
    "engine/config",
    "engine/math",
    "engine/containers",
    "engine/random",
    "engine/rhi",
    "engine/rhi/optimization",
    "engine/shader",
    "engine/paths",
    "engine/core",
    "engine/renderer",
    "engine/renderer/camera",
    "engine/renderer/core",
    "engine/renderer/core/params",
    "engine/renderer/core/gbuffer",
    "engine/renderer/core/shader",
    "engine/renderer/core/pipeline",
    "engine/renderer/core/memory",
    "engine/renderer/core/lod",
    "engine/renderer/core/lighting",
    "engine/renderer/material",
    "engine/material",
    "engine/material/compiler",
    "engine/renderer/memory",
    "engine/renderer/mesh",
    "engine/renderer/upload",
    "engine/renderer/render_graph",
    "engine/renderer/shadows",
    "engine/renderer/ibl",
    "engine/renderer/gi",
    "engine/renderer/probes",
    "engine/renderer/lighting",
    "engine/renderer/atmosphere",
    "engine/renderer/fog",
    "engine/renderer/scene",
    "engine/renderer/frame",
    "engine/renderer/headless",
    "engine/renderer/passes",
    "engine/renderer/passes/geometry",
    "engine/renderer/passes/lighting",
    "engine/renderer/passes/atmosphere",
    "engine/renderer/passes/postprocess",
    "engine/renderer/postprocess",
    "engine/renderer/passes/debug",
    "engine/renderer/passes/ibl",
    "engine/renderer/passes/gi",
    "engine/renderer/passes/pathtracing",
    "engine/renderer/raytracing",
    "engine/asset",
    "engine/asset/formats",
    "engine/asset/mesh",
    "engine/asset/importers",
    "engine/job",
    "engine/ecs",
    "engine/ecs/core",
    "engine/ecs/scene",
    "engine/ecs/lighting",
    "engine/ecs/mesh",
    "engine/ecs/environment",
    "engine/ecs/metadata",
    "engine/ecs/update",
    "engine/ecs/loaders",
    "engine/scripting",
    "engine/scripting/scene",
    "engine/scripting/core",
    "engine/scripting/renderer",
    "engine/scripting/editor",
    "engine/scripting/animation",
    "engine/ipc",
    "engine/vfx",
    "engine/vfx/core",
    "engine/vfx/components",
    "engine/vfx/system",
    "engine/vfx/curves",
    "engine/vfx/modules",
    "engine/vfx/asset",
    "engine/vfx/parameters",
    "engine/vfx/data_interfaces",
    "engine/vfx/events",
    "engine/renderer/passes/vfx",
    "engine/vfx/decals",
    "engine/vfx/trails",
    "engine/vfx/lod",
    "engine/vfx/budget",
    "engine/vfx/baker",
    "engine/vfx/stack",
    "engine/vfx/editor",
    "engine/vfx/editor/undo",
    "engine/vfx/material",
    "engine/vfx/mesh",
    "engine/vfx/lighting",
    "engine/physics",
    "engine/animation",
    "engine/event",
    "engine/property",
    "engine/debug",
    "engine/ui",
    "editor/grid",
    "editor/outline",
    "editor/gizmo",
    "editor/font",
    "editor/stats",
    "editor/screenshot",
    "editor/input",
    "editor/selection",
    "editor/toolbar",
    "platform/windows",
    "engine/rhi/dx12",
    "engine/rhi/dx11",
    "engine/rhi/vulkan",
)


# §2.2 / §3.4: includes the closure does not follow because a recorded local modification
# removes them. Keys are `(including file, include spelling)`; values are modification ids.
PLANNED_CUTS: dict[tuple[str, str], str] = {
    ("engine/rhi/rhi_config.cpp", "config.h"): "UZP-MOD-002",
    ("engine/rhi/rhi_factory.cpp", "dx11/dx11_device.h"): "UZP-MOD-001",
    ("engine/rhi/rhi_factory.cpp", "metal/metal_device.h"): "UZP-MOD-001",
}

# §2.2: headers allowed to stay unresolved, by origin. Exact spellings, then folder prefixes.
CXX_STANDARD_HEADERS = frozenset(
    {
        "algorithm",
        "any",
        "array",
        "atomic",
        "bit",
        "bitset",
        "cassert",
        "cctype",
        "cerrno",
        "cfloat",
        "charconv",
        "chrono",
        "cinttypes",
        "climits",
        "clocale",
        "cmath",
        "compare",
        "complex",
        "concepts",
        "condition_variable",
        "cstdarg",
        "cstddef",
        "cstdint",
        "cstdio",
        "cstdlib",
        "cstring",
        "ctime",
        "cwchar",
        "deque",
        "exception",
        "execution",
        "expected",
        "filesystem",
        "format",
        "forward_list",
        "fstream",
        "functional",
        "future",
        "initializer_list",
        "iomanip",
        "ios",
        "iosfwd",
        "iostream",
        "istream",
        "iterator",
        "limits",
        "list",
        "locale",
        "map",
        "memory",
        "memory_resource",
        "mutex",
        "new",
        "numbers",
        "numeric",
        "optional",
        "ostream",
        "queue",
        "random",
        "ranges",
        "ratio",
        "regex",
        "scoped_allocator",
        "set",
        "shared_mutex",
        "source_location",
        "span",
        "sstream",
        "stack",
        "stdexcept",
        "streambuf",
        "string",
        "string_view",
        "system_error",
        "thread",
        "tuple",
        "type_traits",
        "typeindex",
        "typeinfo",
        "unordered_map",
        "unordered_set",
        "utility",
        "valarray",
        "variant",
        "vector",
        "version",
        "assert.h",
        "float.h",
        "limits.h",
        "math.h",
        "stdarg.h",
        "stddef.h",
        "stdint.h",
        "stdio.h",
        "stdlib.h",
        "string.h",
        "time.h",
        "wchar.h",
    }
)
WINDOWS_SDK_HEADERS = frozenset(
    {
        "Windows.h",
        "windows.h",
        "windowsx.h",
        "DbgHelp.h",
        "ShlObj.h",
        "shellapi.h",
        "shellscalingapi.h",
        "timeapi.h",
        "unknwn.h",
        "hidusage.h",
        "xinput.h",
        "dxgi1_6.h",
        "dxgidebug.h",
        "wrl/client.h",
    }
)
THIRD_PARTY_HEADERS: dict[str, str] = {
    "D3D12MemAlloc.h": "D3D12MA",
    "D3D12MemAlloc.cpp": "D3D12MA",
    "d3d12.h": "DirectX-Headers / Agility SDK",
    "d3d12sdklayers.h": "DirectX-Headers / Agility SDK",
    "d3dx12.h": "DirectX-Headers",
    "dxcapi.h": "DXC",
    "DirectXMath.h": "DirectXMath",
    "spirv_reflect.h": "SPIRV-Reflect",
    "vk_mem_alloc.h": "VMA",
    "volk.h": "volk",
}
THIRD_PARTY_PREFIXES: dict[str, str] = {
    "spdlog/": "spdlog",
    "tracy/": "Tracy (public headers)",
    "vulkan/": "Vulkan-Headers",
}
# Linux and macOS system headers inside `#elif defined(__linux__)` / `__APPLE__` branches;
# never compiled for Windows.
OTHER_PLATFORM_HEADERS = frozenset({"unistd.h", "X11/Xlib.h", "mach-o/dyld.h"})


def external_origin(spelling: str) -> str | None:
    """The origin of an allowed unresolved include, or None if it is not allowed."""
    if spelling in CXX_STANDARD_HEADERS:
        return "C/C++ standard library"
    if spelling in WINDOWS_SDK_HEADERS:
        return "Windows SDK"
    if spelling in OTHER_PLATFORM_HEADERS:
        return "non-Windows system header (platform branch not built)"
    if spelling in THIRD_PARTY_HEADERS:
        return THIRD_PARTY_HEADERS[spelling]
    for prefix, origin in THIRD_PARTY_PREFIXES.items():
        if spelling.startswith(prefix):
            return origin
    return None


def expand_seeds(root: Path) -> list[str]:
    """The declared subset as concrete root-relative paths found under `root`, sorted.

    Raises `FileNotFoundError` if a declared file or folder is missing.
    """
    files: set[str] = set()
    for directory in SEED_DIRS:
        folder = root / directory
        if not folder.is_dir():
            raise FileNotFoundError(f"subset folder {directory} not found under {root}")
        files.update(f"{directory}/{p.name}" for p in folder.iterdir() if p.is_file())
    for file in SEED_FILES:
        if not (root / file).is_file():
            raise FileNotFoundError(f"subset file {file} not found under {root}")
        files.add(file)
    return sorted(files)


def denylisted(paths: Iterable[str]) -> list[str]:
    """The paths that match a §2.4 denylist pattern (`**` matches any depth)."""
    hits: list[str] = []
    for path in paths:
        for pattern in DENYLIST:
            if pattern.endswith("/**"):
                if path.startswith(pattern[:-2]):
                    hits.append(path)
                    break
            elif fnmatch.fnmatchcase(path, pattern):
                hits.append(path)
                break
    return hits
