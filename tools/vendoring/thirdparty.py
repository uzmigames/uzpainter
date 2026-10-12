"""Third-party libraries of the vendored render core (`docs/architecture/13-engine-integration.md`
§2.2, §2.5; `docs/licensing-and-clean-room.md` §3) and of `UzPainter.exe` itself.

Every library is taken from its own upstream release archive, never from a UzEngine tree. The
render core's libraries (`Library.core`) are pinned at the version UzEngine's tree uses at the
selected commit; the libraries UzPainter selects itself (Embree, zlib, spng, first needed by the
`selftest` hardware slice, `phase0.6_toolchain-hardware-slice`; CPython and pybind11, first
needed by its CPython stages, `phase0.7_toolchain-cpython`) at the release recorded in their
`version_source`. `LIBRARIES` pins each archive (URL and SHA-256), the files selected from it, the
include directories the build adds, the licence result and the causes of every difference from
UzEngine's copy, where UzEngine has one. Each `thirdparty/<folder>/` holds the selected files at
their upstream relative paths plus `MANIFEST.json` and `ORIGIN.md`, both written from this table
and the import evidence by `tools.vendoring.import_thirdparty`.
"""

from __future__ import annotations

import fnmatch
import io
import json
import os
import tarfile
import urllib.request
import zipfile
from collections.abc import Collection, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from tools.vendoring.closure import compute_closure, index_tree, parse_includes, resolve_include
from tools.vendoring.hashing import sha256_hex
from tools.vendoring.subset import (
    HEADER_ONLY,
    INCLUDE_DIRS,
    PLANNED_CUTS,
    THIRD_PARTY_HEADERS,
    THIRD_PARTY_PREFIXES,
    VENDORED_DIR,
    expand_seeds,
    external_origin,
)

THIRDPARTY_DIR = "thirdparty"
# Written by the import; not upstream files.
METADATA_FILES = frozenset({"ORIGIN.md", "MANIFEST.json"})
# The UzEngine commit the render core was copied from (phase0.1_vendor-core-copy); the versions
# below are the ones UzEngine's tree uses at this commit.
UZENGINE_COMMIT = "380c142e481d56fe16b045f63315b42359e86a7d"
RETRIEVED = "2026-10-10"
IMPORTER = (
    "Rulebook task `phase0.2_vendor-thirdparty`, run with "
    "`python -m tools.vendoring.import_thirdparty` for UzmiGames"
)
IMPORTER_SLICE = (
    "Rulebook task `phase0.6_toolchain-hardware-slice`, run with "
    "`python -m tools.vendoring.import_thirdparty` for UzmiGames"
)
IMPORTER_CPYTHON = (
    "Rulebook task `phase0.7_toolchain-cpython`, run with "
    "`python -m tools.vendoring.import_thirdparty` for UzmiGames"
)
IMPORTER_NORMAL = (
    "Rulebook task `phase0.9_normal-convention-fixture`, run with "
    "`python -m tools.vendoring.import_thirdparty` for UzmiGames"
)
IMPORTER_STORE = (
    "Rulebook task `phase1.4_store-container-operations`, run with "
    "`python -m tools.vendoring.import_thirdparty` for UzmiGames"
)
STORE_ROLE = (
    "shipped: compiled into `uzp_store.lib`, the project store library (`src/store/`, "
    "`docs/architecture/09-project-file-format.md` §1); its native tests link it today, "
    "`UzPainter.exe` once the worker opens projects"
)
IMPORTER_MESH = (
    "Rulebook task `phase1.4_mesh-importers`, run with "
    "`python -m tools.vendoring.import_thirdparty` for UzmiGames"
)
IMPORTER_EXPORT = (
    "Rulebook task `phase1.16_export-processing-encoders`, run with "
    "`python -m tools.vendoring.import_thirdparty` for UzmiGames"
)
MESH_ROLE = (
    "build-only today: compiled into `uzp_mesh.lib` (UzPainter's mesh importers, `src/mesh/`) "
    "and its native tests `uzp-mesh-tests.exe` (`phase1.4_mesh-importers`); shipped once "
    "`UzPainter.exe` links the importers"
)
CPYTHON_VERSION_SOURCE = (
    "UzPainter's selection: CPython 3.13 because Painter 12.1 ships 3.13.9 "
    "(`docs/architecture/10-python-api.md` §1); 3.13.16 (tag `v3.13.16`, released 2026-09-30) is "
    "the newest 3.13 release with Windows binaries on the retrieval date"
)

COMPILED = "shipped: compiled into `UzPainter.exe`"
HEADERS = "build-only: headers, nothing of it is compiled on its own or shipped"

Result = Literal["identical", "line-endings", "different", "uzengine-only"]
RESULTS: tuple[Result, ...] = ("identical", "line-endings", "different", "uzengine-only")


@dataclass(frozen=True)
class LocalChange:
    """One recorded edit of a vendored file (the exception decision 089 allows: a root-cause fix
    that upstream lacks). `upstream` occurs exactly once in the archive member at `path` and is
    replaced by `replacement`; `cause` says why. The vendored file is the archive member with
    every change of its path applied, which the provenance tests recompute."""

    path: str
    upstream: str
    replacement: str
    cause: str


@dataclass(frozen=True)
class Library:
    """One third-party library and the pinned upstream package it is vendored from.

    Paths in `select`, `sources`, `licence_files`, `header_closure`, `include_dirs` and
    `differences` are relative to the archive root (`archive_root` stripped), which is also the
    layout of `thirdparty/<folder>/` and, for the libraries UzEngine has, of UzEngine's
    `runtime/thirdparty/<uzengine_folder>/`. `uzengine_folder` is None when UzEngine's tree has
    no copy (`uzengine_note` says why); `core` is False for libraries of `UzPainter.exe` that the
    render core does not use, which stay out of the render core's build lists."""

    name: str
    folder: str
    upstream: str
    version: str
    commit: str | None
    archive_url: str
    archive_name: str
    archive_sha256: str
    archive_root: str
    version_source: str
    select: tuple[str, ...]
    licence_files: tuple[str, ...]
    include_dirs: tuple[str, ...]
    licence: str
    role: str
    features: str
    uzengine_folder: str | None
    sources: tuple[str, ...] = ()
    header_closure: tuple[str, ...] = ()
    differences: Mapping[str, str] = field(default_factory=dict)
    uzengine_note: str = ""
    licence_notes: tuple[str, ...] = ()
    release_blocker: str | None = None
    core: bool = True
    importer: str = IMPORTER
    local_changes: tuple[LocalChange, ...] = ()

    @property
    def path(self) -> str:
        return f"{THIRDPARTY_DIR}/{self.folder}"

    @property
    def uzengine_dir(self) -> str | None:
        if self.uzengine_folder is None:
            return None
        return f"runtime/thirdparty/{self.uzengine_folder}"


LINE_ENDINGS_CAUSE = (
    "equal after CRLF -> LF; UzEngine's blob stores LF where the upstream file has CRLF "
    "(`core.autocrlf=true` normalised the text on commit)"
)

LIBRARIES: tuple[Library, ...] = (
    Library(
        name="spdlog",
        folder="spdlog",
        upstream="https://github.com/gabime/spdlog",
        version="v1.17.0",
        commit="79524ddd08a4ec981b7fea76afd08ee05f83755d",
        archive_url="https://github.com/gabime/spdlog/archive/refs/tags/v1.17.0.tar.gz",
        archive_name="spdlog-v1.17.0.tar.gz",
        archive_sha256="d8862955c6d74e5846b3f580b1605d2428b11d97a410d86e2fb13e857cd3a744",
        archive_root="spdlog-1.17.0/",
        version_source=(
            "`runtime/thirdparty/README.md` (spdlog 1.17.0); `scripts/setup.ps1` clones tag "
            "`v1.17.0`"
        ),
        select=("include/spdlog/*", "src/*.cpp", "LICENSE"),
        licence_files=("LICENSE", "include/spdlog/fmt/bundled/fmt.license.rst"),
        include_dirs=("include",),
        sources=(
            "src/async.cpp",
            "src/bundled_fmtlib_format.cpp",
            "src/cfg.cpp",
            "src/color_sinks.cpp",
            "src/file_sinks.cpp",
            "src/spdlog.cpp",
            "src/stdout_sinks.cpp",
        ),
        licence="MIT (spdlog, `LICENSE`); bundled {fmt} under its MIT-style licence "
        "(`include/spdlog/fmt/bundled/fmt.license.rst`)",
        role=COMPILED,
        features=(
            "Compiled library (`SPDLOG_COMPILED_LIB`) with the bundled {fmt} "
            "(`SPDLOG_FMT_EXTERNAL` undefined); the seven `src/*.cpp` units are compiled"
        ),
        uzengine_folder="spdlog",
    ),
    Library(
        name="Tracy",
        folder="tracy",
        upstream="https://github.com/wolfpld/tracy",
        version="v0.13.1",
        commit="05cceee0df3b8d7c6fa87e9638af311dbabc63cb",
        archive_url="https://github.com/wolfpld/tracy/archive/refs/tags/v0.13.1.tar.gz",
        archive_name="tracy-v0.13.1.tar.gz",
        archive_sha256="d4efc50ebcb0bfcfdbba148995aeb75044c0d80f5d91223aebfaa8fa9e563d2b",
        archive_root="tracy-0.13.1/",
        version_source=(
            "`runtime/thirdparty/README.md` (0.13.1, commit `05cceee0`); `scripts/setup.ps1` "
            "clones tag `v0.13.1`"
        ),
        select=("LICENSE",),
        header_closure=(
            "public/tracy/Tracy.hpp",
            "public/tracy/TracyD3D12.hpp",
            "public/tracy/TracyVulkan.hpp",
        ),
        licence_files=("LICENSE",),
        include_dirs=("public",),
        licence="BSD-3-Clause (`LICENSE`)",
        role=HEADERS,
        features=(
            "Public headers only: the textual include closure (all preprocessor branches) of "
            "`tracy/Tracy.hpp`, `tracy/TracyD3D12.hpp` and `tracy/TracyVulkan.hpp`, the three "
            "headers the render core includes. `TRACY_ENABLE` stays undefined, so the macros "
            "compile to stubs; no `TracyClient.cpp` and no other client source is vendored or "
            "linked"
        ),
        uzengine_folder="tracy",
        differences={
            "public/tracy/TracyD3D12.hpp": (
                "UzEngine committed the file with its patch "
                "`0001-fix-getdesc-abi-directx-headers.patch` applied: upstream lines 122 and 137 "
                "call `queue->GetDesc().Type`, UzEngine's call `queue->GetDesc(&queueDesc)` "
                "(out-parameter form). Not applied here: both lines are in the `#else` branch "
                "(lines 33-498) of `#ifndef TRACY_ENABLE` (line 4), which UzPainter's build never "
                "compiles because `TRACY_ENABLE` stays undefined; the upstream file is vendored "
                "and no modification entry is created"
            ),
            "patches/0001-fix-getdesc-abi-directx-headers.patch": (
                "UzEngine's patch for `TracyD3D12.hpp` (see above); the build does not need it, "
                "so neither the patch nor its result is vendored"
            ),
        },
    ),
    Library(
        name="DirectXMath",
        folder="directxmath",
        upstream="https://github.com/microsoft/DirectXMath",
        version="apr2025",
        commit="56206b1916646b29b37e1eac56e96e2008d6c71f",
        archive_url="https://github.com/microsoft/DirectXMath/archive/refs/tags/apr2025.tar.gz",
        archive_name="directxmath-apr2025.tar.gz",
        archive_sha256="8ac7f060d7fcc971d77c5a9f3ff98548ecf119c144a7c2dd9d21f4b66ba94cd4",
        archive_root="DirectXMath-apr2025/",
        version_source=(
            "`runtime/thirdparty/README.md` (apr2025); `scripts/setup.ps1` clones tag `apr2025`"
        ),
        select=("Inc/*", "LICENSE"),
        licence_files=("LICENSE",),
        include_dirs=("Inc",),
        licence="MIT (`LICENSE`)",
        role=HEADERS,
        features="The `Inc/` headers and inline files; no extensions, tests or samples",
        uzengine_folder="directxmath",
        differences={
            "Inc/sal.h": (
                "not part of DirectXMath: UzEngine's `scripts/setup.ps1` downloads it from "
                "`dotnet/runtime` branch `main` (unpinned) as a SAL stub for non-MSVC "
                'platforms. Not vendored: on Windows `#include "sal.h"` '
                "(`Inc/DirectXMath.h`) resolves to the toolchain's own `sal.h` (Windows SDK, "
                "and Zig 0.15.2's mingw-w64 headers `libc/include/any-windows-any/sal.h`)"
            ),
        },
    ),
    Library(
        name="SPIRV-Reflect",
        folder="spirv-reflect",
        upstream="https://github.com/KhronosGroup/SPIRV-Reflect",
        version="vulkan-sdk-1.4.309.0",
        commit="c637858562fbce1b6f5dc7ca48d4e8a5bd117b70",
        archive_url=(
            "https://github.com/KhronosGroup/SPIRV-Reflect/archive/refs/tags/"
            "vulkan-sdk-1.4.309.0.tar.gz"
        ),
        archive_name="spirv-reflect-vulkan-sdk-1.4.309.0.tar.gz",
        archive_sha256="ee57238d4a2c0abf7f0641fb5143bde211e8e31a94194458bab2b6b0a97cb282",
        archive_root="SPIRV-Reflect-vulkan-sdk-1.4.309.0/",
        version_source=(
            "`scripts/setup.ps1` clones tag `vulkan-sdk-1.4.309.0` "
            "(`runtime/thirdparty/README.md` has no SPIRV-Reflect section)"
        ),
        select=("spirv_reflect.h", "spirv_reflect.c", "include/spirv/unified1/spirv.h", "LICENSE"),
        licence_files=("LICENSE",),
        include_dirs=(".", "include"),
        sources=("spirv_reflect.c",),
        licence="Apache-2.0 (`LICENSE`); `include/spirv/unified1/spirv.h` carries the Khronos "
        "MIT-style permission notice in its header",
        role=COMPILED,
        features="`spirv_reflect.c` compiled as C11; no command-line tool, examples or tests",
        uzengine_folder="spirv-reflect",
        licence_notes=(
            "The tag has no `NOTICE` file, so Apache-2.0 §4(d) adds no attribution text.",
        ),
    ),
    Library(
        name="Vulkan-Headers",
        folder="vulkan-headers",
        upstream="https://github.com/KhronosGroup/Vulkan-Headers",
        version="v1.4.342",
        commit="3cfca3829608e778cf59b0dab55d77f4f6c79bee",
        archive_url="https://github.com/KhronosGroup/Vulkan-Headers/archive/refs/tags/v1.4.342.tar.gz",
        archive_name="vulkan-headers-v1.4.342.tar.gz",
        archive_sha256="71ec294f7499d02ba3e8b5a37b72a036ceea458f55bcc8f4dda05fec3234a1b9",
        archive_root="Vulkan-Headers-1.4.342/",
        version_source=(
            "`runtime/thirdparty/README.md` (1.4.342); `scripts/setup.ps1` clones tag `v1.4.342`"
        ),
        select=("include/vulkan/*.h", "include/vk_video/*.h", "LICENSE.md", "LICENSES/*"),
        licence_files=("LICENSE.md", "LICENSES/Apache-2.0.txt", "LICENSES/MIT.txt"),
        include_dirs=("include",),
        licence="Apache-2.0: every selected header carries `SPDX-License-Identifier: Apache-2.0` "
        "(repository statement `LICENSE.md`, texts `LICENSES/`)",
        role=HEADERS,
        features=(
            "C headers only (`include/vulkan/*.h`, `include/vk_video/*.h`); the C++ bindings "
            "(`*.hpp`, `*.cppm`) and the registry are not vendored"
        ),
        uzengine_folder="vulkan_headers",
        licence_notes=(
            "The tag has no `NOTICE` file, so Apache-2.0 §4(d) adds no attribution text.",
        ),
    ),
    Library(
        name="volk",
        folder="volk",
        upstream="https://github.com/zeux/volk",
        version="vulkan-sdk-1.4.304.1",
        commit="0b17a763ba5643e32da1b2152f8140461b3b7345",
        archive_url="https://github.com/zeux/volk/archive/refs/tags/vulkan-sdk-1.4.304.1.tar.gz",
        archive_name="volk-vulkan-sdk-1.4.304.1.tar.gz",
        archive_sha256="01f9facf95167f76d48c752c17ac602ffbc33d2e7157774e2c32a7de614b3687",
        archive_root="volk-vulkan-sdk-1.4.304.1/",
        version_source=(
            "`runtime/thirdparty/README.md` (vulkan-sdk-1.4.304.1); `scripts/setup.ps1` clones "
            "tag `vulkan-sdk-1.4.304.1`"
        ),
        select=("volk.h", "volk.c", "LICENSE.md"),
        licence_files=("LICENSE.md",),
        include_dirs=(".",),
        sources=("volk.c",),
        licence="MIT (`LICENSE.md`)",
        role=COMPILED,
        features="Meta-loader compiled with `VK_NO_PROTOTYPES`; `vulkan-1.dll` is loaded at run "
        "time from the system and never shipped",
        uzengine_folder="volk",
    ),
    Library(
        name="VMA",
        folder="vma",
        upstream="https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator",
        version="v3.2.1",
        commit="c788c52156f3ef7bc7ab769cb03c110a53ac8fcb",
        archive_url=(
            "https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator/archive/refs/tags/"
            "v3.2.1.tar.gz"
        ),
        archive_name="vma-v3.2.1.tar.gz",
        archive_sha256="5e7749504cb802427ffb7bec38a0b6a15db46ae253f00560acb3e624d9fe695c",
        archive_root="VulkanMemoryAllocator-3.2.1/",
        version_source=(
            "`runtime/thirdparty/README.md` (3.2.1); `scripts/setup.ps1` clones tag `v3.2.1`"
        ),
        select=("include/vk_mem_alloc.h", "LICENSE.txt"),
        licence_files=("LICENSE.txt",),
        include_dirs=("include",),
        licence="MIT (`LICENSE.txt`)",
        role=COMPILED,
        features="Single header; the implementation is compiled where the render core defines "
        "`VMA_IMPLEMENTATION` (`engine/rhi/vulkan/vulkan_device.cpp`)",
        uzengine_folder="vma",
    ),
    Library(
        name="D3D12MA",
        folder="d3d12ma",
        upstream="https://github.com/GPUOpen-LibrariesAndSDKs/D3D12MemoryAllocator",
        version="v3.1.0",
        commit="0fa62ed3a0a69b73230a8ec1faa752d4061c8dc8",
        archive_url=(
            "https://github.com/GPUOpen-LibrariesAndSDKs/D3D12MemoryAllocator/archive/refs/tags/"
            "v3.1.0.tar.gz"
        ),
        archive_name="d3d12ma-v3.1.0.tar.gz",
        archive_sha256="629aa00919f2f0f8cdfcdc485db5077f456e939e418cee148e17458efa055f63",
        archive_root="D3D12MemoryAllocator-3.1.0/",
        version_source=(
            "`runtime/thirdparty/README.md` (3.1.0); `scripts/setup.ps1` clones tag `v3.1.0`"
        ),
        select=("include/D3D12MemAlloc.h", "src/D3D12MemAlloc.cpp", "LICENSE.txt", "NOTICES.txt"),
        licence_files=("LICENSE.txt", "NOTICES.txt"),
        include_dirs=("include", "src"),
        licence="MIT (`LICENSE.txt`); `NOTICES.txt` adds the MIT notices of AMD, Microsoft "
        "(DirectX-Graphics-Samples code) and VulkanMemoryAllocator",
        role=COMPILED,
        features="`src/D3D12MemAlloc.cpp` compiled as a source included by the render core's "
        "`engine/rhi/dx12/dx12_d3d12ma.cpp`; no samples, tests or natvis",
        uzengine_folder="d3d12ma",
        licence_notes=("Binary distributions reproduce `LICENSE.txt` and `NOTICES.txt`.",),
    ),
    Library(
        name="DirectX-Headers",
        folder="directx-headers",
        upstream="https://github.com/microsoft/DirectX-Headers",
        version="v1.619.1",
        commit="9e393d6d8a3b30dcc6f2806ef604ec16a27b0d7e",
        archive_url="https://github.com/microsoft/DirectX-Headers/archive/refs/tags/v1.619.1.tar.gz",
        archive_name="directx-headers-v1.619.1.tar.gz",
        archive_sha256="6193774904c940eebb9b0c51b816b93dd776cfeb25a951f0f4a58f22387e5008",
        archive_root="DirectX-Headers-1.619.1/",
        version_source=(
            "`runtime/thirdparty/README.md` (1.619.1); `scripts/setup.ps1` clones tag `v1.619.1`"
        ),
        select=("include/directx/*", "LICENSE"),
        licence_files=("LICENSE",),
        include_dirs=("include", "include/directx"),
        licence="MIT (`LICENSE`)",
        role=HEADERS,
        features="`include/directx` only; ahead of the Agility headers in the include order, so "
        "`d3d12.h`, `d3d12sdklayers.h` and `d3dx12.h` resolve here; "
        "`src/d3dx12_property_format_table.cpp` is not compiled (UzEngine does not compile it "
        "either)",
        uzengine_folder="directx_headers",
    ),
    Library(
        name="Agility SDK",
        folder="agility",
        upstream="https://www.nuget.org/packages/Microsoft.Direct3D.D3D12",
        version="1.619.2",
        commit=None,
        archive_url="https://www.nuget.org/api/v2/package/Microsoft.Direct3D.D3D12/1.619.2",
        archive_name="microsoft.direct3d.d3d12.1.619.2.nupkg",
        archive_sha256="eb92d90bb23b2ec23410c41d791e41dbdbec942ab946924d1fdcb31eac6f0735",
        archive_root="",
        version_source=(
            "`scripts/setup.ps1` downloads package version `1.619.2` (`$agilityVersion`, set by "
            "UzEngine commit `94924089`, 2026-09-07); `runtime/thirdparty/README.md` still says "
            "1.619.1. The package the tree actually fetches, 1.619.2, is taken; both export "
            "`D3D12_SDK_VERSION` 619, equal to DirectX-Headers v1.619.1"
        ),
        select=(
            "build/native/include/*",
            "build/native/bin/x64/D3D12Core.dll",
            "build/native/bin/x64/d3d12SDKLayers.dll",
            "LICENSE.txt",
            "LICENSE-CODE.txt",
            "distributable files.txt",
            "README.md",
        ),
        licence_files=("LICENSE.txt", "LICENSE-CODE.txt", "distributable files.txt"),
        include_dirs=("build/native/include",),
        licence=(
            'Microsoft Software License Terms "MICROSOFT DIRECTX" (`LICENSE.txt`) for '
            "`build/native/bin/`; MIT (`LICENSE-CODE.txt`) for `build/native/include/` "
            "(scope stated in the package `README.md`)"
        ),
        role=(
            "shipped: `D3D12Core.dll` in the distribution's `D3D12\\` folder; "
            "`d3d12SDKLayers.dll` in debug packages only (`13-engine-integration.md` §5); "
            "headers build-only"
        ),
        features=(
            "x64 runtime DLLs only (no arm64/win32, no PDBs, no `d3dconfig.exe` or state-object "
            "compiler); headers kept for `D3D12_SDK_VERSION` but shadowed by DirectX-Headers in "
            "the include order"
        ),
        uzengine_folder="agility",
        uzengine_note=(
            "UzEngine has no committed copy: `.gitignore` lists `/runtime/thirdparty/agility/` "
            "and `scripts/setup.ps1` downloads the package on each machine, so there is nothing "
            "at the commit to compare."
        ),
        licence_notes=(
            "`distributable files.txt` lists `D3D12Core.dll`, `d3d12SDKLayers.dll` and "
            '`d3dconfig.exe` as distributable, so `LICENSE.txt` ("Distributables") permits '
            "redistributing the two vendored DLLs in object-code form.",
            '`LICENSE.txt` "Distribution Requirements" bind every distributor: add significant '
            "primary functionality; (i) require distributors and external end users to agree to "
            "terms that protect the DLLs and Microsoft at least as much as `LICENSE.txt`; "
            "(ii) indemnify Microsoft. It also forbids trademark use suggesting endorsement.",
            'UzEngine\'s README lists the package as "MIT"; only the headers are MIT.',
        ),
        release_blocker=(
            "RB-AGILITY-TERMS: redistribution of `D3D12Core.dll` is confirmed, but the "
            "distribution requirements (end-user terms protecting Microsoft, indemnification) "
            "are legal commitments only the owner can accept; the release packaging "
            "(`phase5.2_packaging`) must carry those terms before a release"
        ),
    ),
    Library(
        name="DXC",
        folder="dxc",
        upstream="https://github.com/microsoft/DirectXShaderCompiler",
        version="v1.9.2602",
        commit="21d28f727ad395b59394815ef76012e432f7e4e5",
        archive_url=(
            "https://github.com/microsoft/DirectXShaderCompiler/releases/download/v1.9.2602/"
            "dxc_2026_02_20.zip"
        ),
        archive_name="dxc_2026_02_20.zip",
        archive_sha256="a1e89031421cf3c1fca6627766ab3020ca4f962ac7e2caa7fab2b33a8436151e",
        archive_root="",
        version_source=(
            "`runtime/thirdparty/README.md` (1.9.2602); `scripts/setup.ps1` downloads the release "
            "asset `dxc_2026_02_20.zip` of tag `v1.9.2602`"
        ),
        select=(
            "inc/dxcapi.h",
            "bin/x64/dxcompiler.dll",
            "bin/x64/dxil.dll",
            "LICENSE-LLVM.txt",
            "LICENSE-MIT.txt",
            "LICENSE-MS.txt",
            "ReleaseNotes.md",
        ),
        licence_files=("LICENSE-LLVM.txt", "LICENSE-MIT.txt", "LICENSE-MS.txt"),
        include_dirs=("inc",),
        licence=(
            '`ReleaseNotes.md` "Licenses": `LICENSE-MIT.txt` for `d3d12shader.h`, '
            "`LICENSE-LLVM.txt` (University of Illinois/NCSA) for all other files; the package "
            'also holds `LICENSE-MS.txt` (Microsoft Software License Terms "MICROSOFT DIRECTX '
            'SHADER COMPILER"), whose scope the notes do not state'
        ),
        role=(
            "shipped: `dxcompiler.dll` and `dxil.dll` beside `UzPainter.exe` "
            "(`13-engine-integration.md` §5); `dxcapi.h` build-only"
        ),
        features=(
            "x64 DLLs and `dxcapi.h` only (no `dxc.exe`, `dxv.exe`, import libraries, "
            "arm64/x86 builds or other headers); `dxcapi.h` includes only `WinAdapter.h` and "
            "`<dlfcn.h>`, both inside its non-Windows branch"
        ),
        uzengine_folder="dxc",
        uzengine_note=(
            "UzEngine commits the package's text files only; its binaries (`*.dll`, `*.exe`, "
            "`*.lib`) are ignored by git and fetched by `scripts/setup.ps1`, so the two DLLs "
            "have no committed counterpart."
        ),
        licence_notes=(
            "`dxcompiler.dll` and `dxcapi.h`: NCSA per the package's own licence table; "
            "redistribution with the licence text is permitted.",
            "`dxil.dll`: the licence table puts it under NCSA, but `LICENSE-MS.txt`, the only "
            "text in the package that grants binary distribution of Microsoft code, permits "
            'distributing only "the object code form of the software listed in the '
            'distributables file list in the software", and the package contains no such list.',
            "Since DXC 1.8.2505 the compiler always uses its internal validator instead of an "
            "external `DXIL.dll` (`ReleaseNotes.md`), so whether `dxil.dll` must ship at all is "
            "for `phase0.8_toolchain-slice` to measure.",
        ),
        release_blocker=(
            "RB-DXC-DXIL: redistribution of `dxil.dll` is not confirmed — `LICENSE-MS.txt` has "
            "no stated scope and refers to a distributables list absent from the package; "
            "resolve by written confirmation of the terms or by not shipping `dxil.dll`"
        ),
    ),
    Library(
        name="Embree",
        folder="embree",
        upstream="https://github.com/RenderKit/embree",
        version="v4.4.1",
        commit="f590db83ef6559387df7f6d8725c34fb7acf851d",
        archive_url=(
            "https://github.com/RenderKit/embree/releases/download/v4.4.1/"
            "embree-4.4.1.x64.windows.zip"
        ),
        archive_name="embree-4.4.1.x64.windows.zip",
        archive_sha256="5aa1fa3161a720f9c610b06c652b80f421cb2b1fe8221fdf92b74157336fdf8f",
        archive_root="embree-4.4.1.x64.windows/",
        version_source=(
            "UzPainter's selection: the newest Embree 4.x release on the retrieval date (tag "
            "`v4.4.1`, published 2026-04-02), its prebuilt x64 Windows package "
            "(`13-engine-integration.md` §5: `embree4.dll` + `tbb12.dll` from an Embree 4.x "
            "release)"
        ),
        select=(
            "include/embree4/*.h",
            "bin/embree4.dll",
            "bin/tbb12.dll",
            "share/doc/Embree_superbuild/LICENSE.txt",
            "share/doc/Embree_superbuild/third-party-programs.txt",
            "share/doc/Embree_superbuild/third-party-programs-TBB.txt",
        ),
        licence_files=(
            "share/doc/Embree_superbuild/LICENSE.txt",
            "share/doc/Embree_superbuild/third-party-programs.txt",
            "share/doc/Embree_superbuild/third-party-programs-TBB.txt",
        ),
        include_dirs=("include",),
        licence=(
            "Apache-2.0 (`share/doc/Embree_superbuild/LICENSE.txt`; every header carries "
            "`SPDX-License-Identifier: Apache-2.0`); `tbb12.dll` is oneTBB, Apache-2.0, with its "
            "notices in `third-party-programs-TBB.txt`; `third-party-programs.txt` lists the "
            "notices of the release's components"
        ),
        role=(
            "shipped: `embree4.dll` and `tbb12.dll` beside `UzPainter.exe` "
            "(`13-engine-integration.md` §5), loaded at run time by the `embree` stage of "
            "`selftest`; headers build-only"
        ),
        features=(
            "Prebuilt x64 Windows release with TBB tasking: `embree4.dll`, `tbb12.dll` and the "
            "C API headers `include/embree4/*.h`. No import library (UzPainter loads "
            "`embree4.dll` with `LoadLibraryExW` and resolves the C API by name), no "
            "`tbbmalloc.dll` (neither vendored DLL imports it), no tutorials, ISPC headers, "
            "CMake files or documentation besides the licence files"
        ),
        uzengine_folder=None,
        uzengine_note=(
            "UzEngine's tree at the commit has no Embree (`runtime/thirdparty/` holds no Embree "
            "folder), so there is nothing to compare."
        ),
        licence_notes=(
            "Apache-2.0 §4(d): the release has no `NOTICE` file; binary distributions reproduce "
            "`LICENSE.txt`, `third-party-programs.txt` and `third-party-programs-TBB.txt`.",
            "`embree4.dll` and `tbb12.dll` import the Visual C++ runtime (`MSVCP140.dll`, "
            "`VCRUNTIME140.dll`), which the package does not contain; the measured import "
            "closure (`tools.toolchain.dll_closure`) records them, and their app-local shipping "
            "is governed by the Visual C++ runtime row of `docs/licensing-and-clean-room.md` §3.",
        ),
        core=False,
        importer=IMPORTER_SLICE,
    ),
    Library(
        name="zlib",
        folder="zlib",
        upstream="https://github.com/madler/zlib",
        version="v1.3.2",
        commit="da607da739fa6047df13e66a2af6b8bec7c2a498",
        archive_url="https://github.com/madler/zlib/releases/download/v1.3.2/zlib-1.3.2.tar.gz",
        archive_name="zlib-1.3.2.tar.gz",
        archive_sha256="bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16",
        archive_root="zlib-1.3.2/",
        version_source=(
            "UzPainter's selection: the newest zlib release on the retrieval date (tag `v1.3.2`, "
            "published 2026-02-17); spng needs zlib (`SPNG_USE_MINIZ` stays undefined)"
        ),
        select=(
            "LICENSE",
            "README",
            "adler32.c",
            "compress.c",
            "crc32.c",
            "crc32.h",
            "deflate.c",
            "deflate.h",
            "gzguts.h",
            "inffast.c",
            "inffast.h",
            "inffixed.h",
            "inflate.c",
            "inflate.h",
            "inftrees.c",
            "inftrees.h",
            "trees.c",
            "trees.h",
            "uncompr.c",
            "zconf.h",
            "zlib.h",
            "zutil.c",
            "zutil.h",
        ),
        licence_files=("LICENSE", "README"),
        include_dirs=(".",),
        sources=(
            "adler32.c",
            "compress.c",
            "crc32.c",
            "deflate.c",
            "inffast.c",
            "inflate.c",
            "inftrees.c",
            "trees.c",
            "uncompr.c",
            "zutil.c",
        ),
        licence="zlib licence (`LICENSE`; the same notice is in `README` and `zlib.h`)",
        role=COMPILED,
        features=(
            "The units spng, the export's PNG writer and tinyexr use, compiled as C11: "
            "`adler32`, `compress`, `crc32`, `deflate`, `inffast`, `inflate`, `inftrees`, "
            "`trees`, `uncompr` (tinyexr's `uncompress`, added by "
            "`phase1.16_export-processing-encoders`), `zutil`; `gzguts.h` only because "
            "`zutil.c` includes it; no gz* sources, contrib, examples or tests"
        ),
        uzengine_folder=None,
        uzengine_note=(
            "UzEngine takes zlib from vcpkg (`runtime/thirdparty/README.md`, vcpkg section); its "
            "tree at the commit has no zlib folder, so there is nothing to compare."
        ),
        core=False,
        importer=IMPORTER_SLICE,
    ),
    Library(
        name="spng",
        folder="spng",
        upstream="https://github.com/randy408/libspng",
        version="v0.7.4",
        commit="fb768002d4288590083a476af628e51c3f1d47cd",
        archive_url="https://github.com/randy408/libspng/archive/refs/tags/v0.7.4.tar.gz",
        archive_name="libspng-v0.7.4.tar.gz",
        archive_sha256="47ec02be6c0a6323044600a9221b049f63e1953faf816903e7383d4dc4234487",
        archive_root="libspng-0.7.4/",
        version_source=(
            "`runtime/thirdparty/README.md` (spng 0.7.4), also the newest spng release on the "
            "retrieval date; selected over libpng from the inventory "
            "(`docs/licensing-and-clean-room.md` §3) for the 16-bit PNG encoder and decoder of "
            "`selftest`"
        ),
        select=("spng/spng.c", "spng/spng.h", "LICENSE"),
        licence_files=("LICENSE",),
        include_dirs=("spng",),
        sources=("spng/spng.c",),
        licence="BSD-2-Clause (`LICENSE`)",
        role=COMPILED,
        features=(
            "`spng/spng.c` compiled as C11 with `SPNG_STATIC` and zlib (`SPNG_USE_MINIZ` "
            "undefined); encoder and decoder, 8 and 16 bits per sample; no examples or tests"
        ),
        uzengine_folder="spng",
        core=False,
        importer=IMPORTER_SLICE,
    ),
    Library(
        name="tinyexr",
        folder="tinyexr",
        upstream="https://github.com/syoyo/tinyexr",
        version="v3.2.0",
        commit="6f470c9ab24bf3992bc512ce07e8ecb00d9bf105",
        archive_url="https://github.com/syoyo/tinyexr/archive/refs/tags/v3.2.0.tar.gz",
        archive_name="tinyexr-v3.2.0.tar.gz",
        archive_sha256="df2bd61124a35d8138f8b0bc22418a1d4fe33622c818e0e022f5522afc0821b0",
        archive_root="tinyexr-3.2.0/",
        version_source=(
            "`runtime/thirdparty/README.md` pins tinyexr 1.0.9; UzPainter's selection is the "
            "newest release on the retrieval date (tag `v3.2.0`, published 2026-07-08), the "
            "export's OpenEXR writer (`docs/licensing-and-clean-room.md` §3, decision 089)"
        ),
        select=("tinyexr.h", "exr_reader.hh", "streamreader.hh", "LICENSE"),
        licence_files=("LICENSE", "tinyexr.h"),
        include_dirs=(".",),
        licence=(
            "BSD-3-Clause (`LICENSE`, also heading `tinyexr.h`); the OpenEXR-derived code in "
            "`tinyexr.h` under Industrial Light & Magic's BSD-3-Clause notice, reproduced in "
            "the header"
        ),
        role=(
            "shipped: the header-only implementation compiled once into `UzPainter.exe` and "
            "`uzp-export-tests.exe` by `src/export/tinyexr_unit.cpp`"
        ),
        features=(
            "`TINYEXR_IMPLEMENTATION` with `TINYEXR_USE_MINIZ` 0 over the vendored zlib "
            "(`zlib.h` included first; `uncompress` from `uncompr.c`), PIZ compression enabled, "
            "no threads, no ZFP; the scanline writer and reader of single-part images "
            "(`SaveEXRImageToMemory`, `LoadEXRImageFromMemory`); the v3 C sources under `src/` "
            "are not vendored"
        ),
        uzengine_folder="tinyexr",
        differences={
            "tinyexr.h": (
                "UzEngine pins tinyexr 1.0.9 (`runtime/thirdparty/README.md`); UzPainter takes "
                "release v3.2.0, so the headers differ by version"
            ),
            "miniz.c": (
                "UzEngine compiles tinyexr with miniz; UzPainter sets `TINYEXR_USE_MINIZ` 0 and "
                "uses the vendored zlib, so miniz is not vendored"
            ),
            "miniz.h": "see `miniz.c`",
        },
        core=False,
        importer=IMPORTER_EXPORT,
        local_changes=(
            LocalChange(
                path="tinyexr.h",
                upstream="  bool operator()(long long *a, long long *b) { return *a > *b; }",
                replacement=(
                    "  bool operator()(long long *a, long long *b) { return *a > *b || (*a == *b "
                    "&& a > b); }  // UzPainter local change (thirdparty/tinyexr/ORIGIN.md)"
                ),
                cause=(
                    "The heap order of the PIZ Huffman table builder (`hufBuildEncTable`) "
                    "breaks ties between equal frequencies by the symbol's address, as OpenEXR's "
                    "own `FHeapCompare` does (OpenEXR added the tie-break so that "
                    "`std::make_heap`/`pop_heap`/`push_heap` build the same table with every "
                    "standard library). Upstream compares frequencies only, so its PIZ bytes "
                    "depend on the C++ library's heap algorithm: with Zig's libc++ it re-encodes "
                    "20 of Painter 12.1.5's 216 recorded OpenEXR files byte for byte, with the "
                    "tie-break all 216 (decision 089)"
                ),
            ),
        ),
    ),
    Library(
        name="CPython",
        folder="cpython",
        upstream="https://www.python.org/downloads/release/python-31316/",
        version="v3.13.16",
        commit="cbc944f4bc59639a444dd971c737788ba2283a91",
        archive_url="https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip",
        archive_name="python-3.13.16-embed-amd64.zip",
        archive_sha256="97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297",
        archive_root="",
        version_source=CPYTHON_VERSION_SOURCE,
        select=(
            "LICENSE.txt",
            "python313.dll",
            "python313.zip",
            "python3.dll",
            "vcruntime140.dll",
            "vcruntime140_1.dll",
            "libcrypto-3.dll",
            "libffi-8.dll",
            "libssl-3.dll",
            "sqlite3.dll",
            "*.pyd",
        ),
        licence_files=("LICENSE.txt",),
        include_dirs=(),
        licence=(
            "PSF License Version 2 with the historical BeOpen, CNRI and CWI licences, the "
            "Zero-Clause BSD licence for documentation code and the licences of the incorporated "
            "software (bzip2, libffi, OpenSSL, SQLite, expat, mpdecimal, zlib and others), all in "
            '`LICENSE.txt`; its section "Additional Conditions for this Windows binary build" '
            "covers the Microsoft Distributable Code linked into every `.exe`, `.dll` and `.pyd`"
        ),
        role=(
            "shipped: every selected file beside `UzPainter.exe` (`13-engine-integration.md` "
            "§5); `python313.dll` is imported by `UzPainter.exe`, which embeds the interpreter"
        ),
        features=(
            "The Windows x64 embeddable package without `python.exe`, `pythonw.exe`, "
            "`python313._pth` (UzPainter installs its own, `src/python/python313._pth`) and the "
            "catalog `python.cat`: `python313.dll`, the standard library as `python313.zip`, the "
            "standard extension modules (`*.pyd`) and the DLLs they load, `python3.dll` for "
            "stable-ABI wheels, and the package's `vcruntime140.dll` and `vcruntime140_1.dll` "
            "(file version 14.51.36247.0, newer than `thirdparty/vc-runtime/`'s 14.44, so these "
            "two are the ones installed)"
        ),
        uzengine_folder=None,
        uzengine_note=(
            "UzEngine's tree at the commit has no CPython, so there is nothing to compare."
        ),
        licence_notes=(
            "The package's `python313.dll`, `python3.dll`, `vcruntime140.dll`, "
            "`vcruntime140_1.dll` and `LICENSE.txt` are byte-equal to those of "
            "`python-3.13.16-amd64.zip` (`thirdparty/cpython-dev/`), whose SHA-256 python.org "
            "publishes in its signed release index `windows-3.13.16.json`.",
            "`vcruntime140.dll` and `vcruntime140_1.dll` are Microsoft Visual C++ Distributable "
            "Code like `thirdparty/vc-runtime/`: their redistribution falls under release blocker "
            "RB-VCRT-TERMS (`docs/licensing-and-clean-room.md` §3).",
        ),
        core=False,
        importer=IMPORTER_CPYTHON,
    ),
    Library(
        name="CPython headers",
        folder="cpython-dev",
        upstream="https://www.python.org/downloads/release/python-31316/",
        version="v3.13.16",
        commit="cbc944f4bc59639a444dd971c737788ba2283a91",
        archive_url="https://www.python.org/ftp/python/3.13.16/python-3.13.16-amd64.zip",
        archive_name="python-3.13.16-amd64.zip",
        archive_sha256="bbf675bb5e763c1efbb09a3a461b259d81598a63c30c4b0d7ea11b9f063df159",
        archive_root="",
        version_source=CPYTHON_VERSION_SOURCE
        + "; the headers and import library come from the release's full Windows x64 package "
        "(the embeddable package has neither), listed with this SHA-256 in python.org's signed "
        "release index `windows-3.13.16.json`",
        select=("include/*", "libs/python313.lib", "LICENSE.txt"),
        licence_files=("LICENSE.txt",),
        include_dirs=("include",),
        licence="PSF License Version 2 and the incorporated licences (`LICENSE.txt`, the same "
        "file as in `thirdparty/cpython/`)",
        role=(
            "build-only: the C API headers and the import library `libs/python313.lib` "
            "`UzPainter.exe` links against; nothing of it is shipped"
        ),
        features=(
            "`include/` as distributed (the generated Windows `pyconfig.h`, GIL-enabled build) "
            "and `libs/python313.lib`; no `python3.lib`, `DLLs/`, `Lib/`, tools or Tcl/Tk"
        ),
        uzengine_folder=None,
        uzengine_note=(
            "UzEngine's tree at the commit has no CPython, so there is nothing to compare."
        ),
        core=False,
        importer=IMPORTER_CPYTHON,
    ),
    Library(
        name="pybind11",
        folder="pybind11",
        upstream="https://github.com/pybind/pybind11",
        version="v3.1.0",
        commit="97bf890db679505a14dfe547a5e77bb2bd05dc90",
        archive_url="https://github.com/pybind/pybind11/archive/refs/tags/v3.1.0.tar.gz",
        archive_name="pybind11-v3.1.0.tar.gz",
        archive_sha256="ef712655692a2e9bf7bb7874c022564a45f91d847ddee987e720cd9e28849665",
        archive_root="pybind11-3.1.0/",
        version_source=(
            "UzPainter's selection: the newest pybind11 release on the retrieval date (tag "
            "`v3.1.0`, published 2026-08-06; `docs/architecture/10-python-api.md` §1)"
        ),
        select=("include/pybind11/*", "LICENSE"),
        licence_files=("LICENSE",),
        include_dirs=("include",),
        licence="BSD-3-Clause (`LICENSE`)",
        role=(
            "shipped: header-only, compiled into `UzPainter.exe` (the `uzpainter` module and the "
            "embedding)"
        ),
        features=(
            "The headers `include/pybind11/` (embedding through `pybind11/embed.h`); no CMake "
            "files, tests, docs or the `pybind11` Python package"
        ),
        uzengine_folder=None,
        uzengine_note=(
            "UzEngine's tree at the commit has no pybind11, so there is nothing to compare."
        ),
        core=False,
        importer=IMPORTER_CPYTHON,
    ),
    Library(
        name="mikktspace",
        folder="mikktspace",
        upstream="https://github.com/mmikk/MikkTSpace",
        version="master@3e895b49",
        commit="3e895b49d05ea07e4c2133156cfa94369e19e409",
        archive_url=(
            "https://github.com/mmikk/MikkTSpace/archive/"
            "3e895b49d05ea07e4c2133156cfa94369e19e409.tar.gz"
        ),
        archive_name="MikkTSpace-3e895b49d05ea07e4c2133156cfa94369e19e409.tar.gz",
        archive_sha256="aeba65ddee85a679133d510d71d00b108f603752f90b15b9ecf7777033f6e351",
        archive_root="MikkTSpace-3e895b49d05ea07e4c2133156cfa94369e19e409/",
        version_source=(
            "`runtime/thirdparty/mikktspace` holds the same upstream code (its `mikktspace.c` "
            "carries one local patch, below); upstream has no release tags, so UzPainter pins "
            "commit `3e895b49`, the head of `master` on the retrieval date (approved source "
            "S-MIKK, `docs/architecture/12-mesh-import.md` §3)"
        ),
        select=("mikktspace.c", "mikktspace.h"),
        licence_files=("mikktspace.h",),
        include_dirs=(".",),
        sources=("mikktspace.c",),
        licence=(
            "zlib licence, stated in the comment block at the top of `mikktspace.h` (the same "
            "notice heads `mikktspace.c`)"
        ),
        role=(
            "build-only today: compiled into `uzp-normal-prototype.exe`, the Phase 0 tangent-frame "
            "prototype of `phase0.9_normal-convention-fixture`, and into `uzp_mesh.lib` "
            "(UzPainter's per-corner tangent frames, `src/mesh/tangents.cpp`, "
            "`phase1.5_mesh-tangents-certificate`) with its test executables; shipped once "
            "`UzPainter.exe` links the mesh module"
        ),
        features=(
            "`mikktspace.c` compiled as C11 (`genTangSpaceDefault`, per-corner tangents and "
            "bitangent sign); the repository's `README.md` is not vendored"
        ),
        uzengine_folder="mikktspace",
        differences={
            "mikktspace.c": (
                "UzEngine patched the rotate in `QuickSort`'s pivot generator (a shift by 32 when "
                "the rotate amount is 0, undefined in C, which Zig's Debug sanitizer traps); "
                "UzPainter vendors the upstream file unchanged and compiles it with "
                "`-fno-sanitize=undefined` instead (`build.zig`)"
            ),
        },
        core=False,
        importer=IMPORTER_NORMAL,
    ),
    Library(
        name="SQLite",
        folder="sqlite",
        upstream="https://www.sqlite.org/",
        version="3.54.0",
        commit="be8d059e9a49089ab2dce5ed26dd87aaf598fdc5fbe0b107c0dd758464bcd5e3",
        archive_url="https://www.sqlite.org/2026/sqlite-amalgamation-3540000.zip",
        archive_name="sqlite-amalgamation-3540000.zip",
        archive_sha256="68e913b0fe8ec6b4e5f391c594a28872884e80d6cd042a1e50c957be46b5aa4d",
        archive_root="sqlite-amalgamation-3540000/",
        version_source=(
            "UzPainter's selection: the newest SQLite release on the retrieval date (3.54.0, "
            "check-in of 2026-10-09 named by `SQLITE_SOURCE_ID` in `sqlite3.h`); the `.uzp` "
            "container of decision 010 (`docs/architecture/09-project-file-format.md` §1)"
        ),
        select=("sqlite3.c", "sqlite3.h"),
        licence_files=("sqlite3.h",),
        include_dirs=(".",),
        sources=("sqlite3.c",),
        licence=(
            "Public domain: the author's dedication (\"The author disclaims copyright to this "
            'source code") heads `sqlite3.h` and every part of `sqlite3.c` '
            "(https://www.sqlite.org/copyright.html)"
        ),
        role=STORE_ROLE,
        features=(
            "The amalgamation `sqlite3.c` compiled as C11 with `SQLITE_THREADSAFE=1`, "
            "`SQLITE_DQS=0`, `SQLITE_DEFAULT_FOREIGN_KEYS=1`, `SQLITE_OMIT_LOAD_EXTENSION` and "
            "`SQLITE_OMIT_DEPRECATED`; no shell (`shell.c`) and no `sqlite3ext.h`"
        ),
        uzengine_folder=None,
        uzengine_note=(
            "UzEngine's tree at the commit has no SQLite (`runtime/thirdparty/` holds no SQLite "
            "folder), so there is nothing to compare."
        ),
        core=False,
        importer=IMPORTER_STORE,
    ),
    Library(
        name="zstd",
        folder="zstd",
        upstream="https://github.com/facebook/zstd",
        version="v1.5.7",
        commit="f8745da6ff1ad1e7bab384bd1f9d742439278e99",
        archive_url="https://github.com/facebook/zstd/releases/download/v1.5.7/zstd-1.5.7.tar.gz",
        archive_name="zstd-1.5.7.tar.gz",
        archive_sha256="eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3",
        archive_root="zstd-1.5.7/",
        version_source=(
            "UzPainter's selection: the newest zstd release on the retrieval date (tag `v1.5.7`, "
            "published 2025-02-19; the archive SHA-256 equals the release's `.sha256` asset); "
            "payload compression of the `.uzp` container (decision 010, "
            "`docs/architecture/09-project-file-format.md` §1)"
        ),
        select=(
            "LICENSE",
            "lib/zstd.h",
            "lib/zstd_errors.h",
            "lib/common/*",
            "lib/compress/*",
            "lib/decompress/*.c",
            "lib/decompress/*.h",
        ),
        licence_files=("LICENSE",),
        include_dirs=("lib",),
        sources=(
            "lib/common/debug.c",
            "lib/common/entropy_common.c",
            "lib/common/error_private.c",
            "lib/common/fse_decompress.c",
            "lib/common/pool.c",
            "lib/common/threading.c",
            "lib/common/xxhash.c",
            "lib/common/zstd_common.c",
            "lib/compress/fse_compress.c",
            "lib/compress/hist.c",
            "lib/compress/huf_compress.c",
            "lib/compress/zstd_compress.c",
            "lib/compress/zstd_compress_literals.c",
            "lib/compress/zstd_compress_sequences.c",
            "lib/compress/zstd_compress_superblock.c",
            "lib/compress/zstd_double_fast.c",
            "lib/compress/zstd_fast.c",
            "lib/compress/zstd_lazy.c",
            "lib/compress/zstd_ldm.c",
            "lib/compress/zstd_opt.c",
            "lib/compress/zstd_preSplit.c",
            "lib/compress/zstdmt_compress.c",
            "lib/decompress/huf_decompress.c",
            "lib/decompress/zstd_ddict.c",
            "lib/decompress/zstd_decompress.c",
            "lib/decompress/zstd_decompress_block.c",
        ),
        licence=(
            "BSD-3-Clause (`LICENSE`), elected from upstream's dual licence (BSD or GPLv2, "
            "stated in every source file; the GPLv2 text `COPYING` is not vendored and not used)"
        ),
        role=STORE_ROLE,
        features=(
            "The compression and decompression units of `lib/` compiled as C11 with "
            "`ZSTD_DISABLE_ASM` (the x86-64 assembly `huf_decompress_amd64.S` is not vendored) and "
            "without `ZSTD_MULTITHREAD` or `ZSTD_LEGACY_SUPPORT`; no dictionary builder, legacy "
            "formats, deprecated API, programs, contrib or tests"
        ),
        uzengine_folder=None,
        uzengine_note=(
            "UzEngine's tree at the commit has no zstd (`runtime/thirdparty/` holds no zstd "
            "folder), so there is nothing to compare."
        ),
        core=False,
        importer=IMPORTER_STORE,
    ),
    Library(
        name="ufbx",
        folder="ufbx",
        upstream="https://github.com/ufbx/ufbx",
        version="v0.23.1",
        commit="26a482ae66871d7de36eb722aa060bce95bce274",
        archive_url="https://github.com/ufbx/ufbx/archive/refs/tags/v0.23.1.tar.gz",
        archive_name="ufbx-v0.23.1.tar.gz",
        archive_sha256="21edd1021dfb430e37aa6214c9b3bbaa5634b1859cbbef7231e738af4f19c956",
        archive_root="ufbx-0.23.1/",
        version_source=(
            "`runtime/thirdparty/README.md` lists ufbx 0.14.3; UzPainter selects the newest ufbx "
            "release on the retrieval date instead (tag `v0.23.1`, tagged 2026-09-25; ufbx "
            "publishes its releases as annotated tags, not GitHub releases), for the FBX importer "
            "of `docs/architecture/12-mesh-import.md` §2"
        ),
        select=("ufbx.c", "ufbx.h", "LICENSE"),
        licence_files=("LICENSE",),
        include_dirs=(".",),
        sources=("ufbx.c",),
        licence=(
            'MIT or public domain, the user\'s choice (`LICENSE`: "ALTERNATIVE A - MIT License", '
            'Copyright (c) 2020 Samuli Raivio; "ALTERNATIVE B - Public Domain '
            '(www.unlicense.org)"); `ufbx.c` and `ufbx.h` carry no notice of their own'
        ),
        role=MESH_ROLE,
        features=(
            "`ufbx.c` compiled as C11 with the default configuration (no `UFBX_CONFIG_HEADER`, "
            "`UFBX_CONFIG_SOURCE` or `UFBX_HEADER_PATH`); the `extra/` helpers, language "
            "bindings, examples, tests, test data and `misc/` tools are not vendored"
        ),
        uzengine_folder="ufbx",
        differences={
            "ufbx.c": (
                "version, not a patch: UzEngine's blob is byte-equal to `ufbx.c` of upstream tag "
                "`v0.14.3` (commit `19bdb7e7`); UzPainter vendors `v0.23.1`"
            ),
            "ufbx.h": (
                "version, not a patch: UzEngine's blob is byte-equal to `ufbx.h` of upstream tag "
                "`v0.14.3` (`UFBX_HEADER_VERSION` 0.14.3); UzPainter vendors `v0.23.1`"
            ),
        },
        core=False,
        importer=IMPORTER_MESH,
    ),
    Library(
        name="simdjson",
        folder="simdjson",
        upstream="https://github.com/simdjson/simdjson",
        version="v4.6.11",
        commit="f5de14f09256982933af2849beb43778bd421ca7",
        archive_url="https://github.com/simdjson/simdjson/archive/refs/tags/v4.6.11.tar.gz",
        archive_name="simdjson-v4.6.11.tar.gz",
        archive_sha256="61d948fc24f0d793829ad658058e7597d064988a89b4607ea02e401a82df98ff",
        archive_root="simdjson-4.6.11/",
        version_source=(
            "UzPainter's selection: the simdjson version fastgltf `v0.9.1` pins "
            '(`cmake/dependencies.cmake`: `SIMDJSON_TARGET_VERSION` "4.6.11", whose '
            "`singleheader/simdjson.h` and `singleheader/simdjson.cpp` fastgltf's build "
            "downloads); tag `v4.6.11`, released 2026-09-05. The newer 5.0.x releases "
            "(2026-09-28 to 2026-10-08) start a major version fastgltf v0.9.1 does not name"
        ),
        select=("singleheader/simdjson.h", "singleheader/simdjson.cpp", "LICENSE", "LICENSE-MIT"),
        licence_files=("LICENSE", "LICENSE-MIT"),
        include_dirs=("singleheader",),
        sources=("singleheader/simdjson.cpp",),
        licence=(
            "Apache-2.0 (`LICENSE`) or MIT (`LICENSE-MIT`), the user's choice (`README.md` "
            '"License"); the amalgamation embeds code under its own notices (licence notes below)'
        ),
        role=MESH_ROLE,
        features=(
            "The amalgamated single-header build: `singleheader/simdjson.cpp` compiled as C++ "
            "with run-time selection of the SIMD kernels (no architecture flags; `-mevex512` lets "
            "Zig 0.15.2's clang compile the AVX-512 `icelake` kernel's target regions against the "
            "baseline x86-64 CPU), `singleheader/simdjson.h` included by fastgltf; the split "
            "`include/` and `src/` trees, the amalgamation script and demo, `singleheader.zip`, "
            "benchmarks, tools, tests and documentation are not vendored"
        ),
        uzengine_folder=None,
        uzengine_note=(
            "UzEngine's tree at the commit has no simdjson (`runtime/thirdparty/` holds no "
            "simdjson folder; its `fastgltf` entry is a submodule link without files), so there "
            "is nothing to compare."
        ),
        licence_notes=(
            "The tag has no `NOTICE` file, so Apache-2.0 §4(d) adds no attribution text.",
            "Both amalgamated files embed `simdjson/internal/instruction_set.h`, adapted from "
            "PyTorch's `simd.h` under BSD-3-Clause with its notice in place (Facebook, Idiap "
            "Research Institute, Deepmind Technologies, NEC Laboratories America, NYU); clause 2 "
            "requires binary distributions to reproduce that notice.",
            "`simdjson.cpp` embeds `to_chars.cpp`, the Grisu2 conversion adapted from JSON for "
            'Modern C++, which states "distributed under the MIT license, Copyright (c) 2009 '
            'Florian Loitsch"; its UTF-8 validator is credited "based on code from Google '
            'Fuchsia (Apache Licensed)".',
            "string-view lite (Boost Software License 1.0, Martin Moene) is embedded inside "
            "`#ifndef SIMDJSON_HAS_STRING_VIEW`, a branch a C++17-or-later build never compiles.",
        ),
        core=False,
        importer=IMPORTER_MESH,
    ),
    Library(
        name="fastgltf",
        folder="fastgltf",
        upstream="https://github.com/spnda/fastgltf",
        version="v0.9.1",
        commit="705564d4d54500ae88befb0db9e361e447923655",
        archive_url="https://github.com/spnda/fastgltf/archive/refs/tags/v0.9.1.tar.gz",
        archive_name="fastgltf-v0.9.1.tar.gz",
        archive_sha256="d8705a496deb2831775baeef5009be36d24bf3d10f8d29ab016e977d0119c872",
        archive_root="fastgltf-0.9.1/",
        version_source=(
            "UzPainter's selection: the newest fastgltf release on the retrieval date (tag "
            "`v0.9.1`, published 2026-09-27), for the glTF/GLB importer of "
            "`docs/architecture/12-mesh-import.md` §2; its JSON parser is `thirdparty/simdjson/`"
        ),
        select=("include/fastgltf/*", "src/*.cpp", "LICENSE.md"),
        licence_files=("LICENSE.md",),
        include_dirs=("include",),
        sources=("src/base64.cpp", "src/fastgltf.cpp", "src/io.cpp"),
        licence=(
            "MIT (`LICENSE.md`, Copyright (c) 2022 - 2026 Sean Apeler; every selected header and "
            "source carries the same notice)"
        ),
        role=MESH_ROLE,
        features=(
            "The three library units `src/base64.cpp`, `src/fastgltf.cpp` and `src/io.cpp` "
            "compiled as C++ against `thirdparty/simdjson/` (`src/fastgltf.cpp` with `-mcrc32`, "
            "which its `sse4.2` CRC-32C target region needs under Zig 0.15.2's clang; the "
            "function is chosen at run time only on CPUs with SSE4.2) with the CMake option "
            "defaults (`FASTGLTF_USE_CUSTOM_SMALLVECTOR`, `FASTGLTF_DISABLE_CUSTOM_MEMORY_POOL`, "
            "`FASTGLTF_USE_64BIT_FLOAT`, `FASTGLTF_ENABLE_KHR_IMPLICIT_SHAPES` and "
            "`FASTGLTF_ENABLE_KHR_PHYSICS_RIGID_BODIES` all off); the headers `include/fastgltf/` "
            "(the DirectXMath and glm element-trait headers are vendored with them but no "
            "compiled unit includes them); no C++ module interface `src/fastgltf.ixx`, CMake "
            "files, downloaded `deps/`, tests, examples or documentation"
        ),
        uzengine_folder="fastgltf",
        uzengine_note=(
            "UzEngine's tree records `runtime/thirdparty/fastgltf` only as a submodule link "
            "(gitlink to fastgltf commit `d4734a7e55d8d25155e755d895e018e423845cd0`, committed "
            "upstream 2024-07-25) with no `.gitmodules` and no files at the commit, so there is "
            "nothing to compare."
        ),
        core=False,
        importer=IMPORTER_MESH,
    ),
)

LIBRARY_BY_NAME = {lib.name: lib for lib in LIBRARIES}
LIBRARY_BY_FOLDER = {lib.folder: lib for lib in LIBRARIES}


# ---------------------------------------------------------------------------------------------
# Archives


def default_cache() -> Path:
    """Download cache outside both repositories: `UZP_THIRDPARTY_CACHE`, else the user's local
    application-data folder."""
    override = os.environ.get("UZP_THIRDPARTY_CACHE")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "UzPainter" / "thirdparty-cache"


def fetch(lib: Library, cache: Path) -> Path:
    """The pinned archive of `lib` in `cache`, downloaded if absent. Raises `ValueError` if the
    bytes do not hash to `archive_sha256` (a cached file that does not match is replaced)."""
    path = cache / lib.archive_name
    if path.is_file() and sha256_hex(path.read_bytes()) == lib.archive_sha256:
        return path
    cache.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(lib.archive_url, headers={"User-Agent": "uzpainter-vendoring"})
    with urllib.request.urlopen(request, timeout=300) as response:
        data = cast(bytes, response.read())
    digest = sha256_hex(data)
    if digest != lib.archive_sha256:
        raise ValueError(
            f"{lib.name}: {lib.archive_url} hashes to {digest}, pinned {lib.archive_sha256}"
        )
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(data)
    partial.replace(path)
    return path


def read_archive(
    archive: Path, root: str, wanted: Collection[str] | None = None
) -> dict[str, bytes]:
    """Files of a `.tar.gz` or zip archive (`.nupkg` is a zip) keyed by their path below `root`.

    Members outside `root` and directories are skipped; with `wanted`, only those paths are
    read."""
    data = archive.read_bytes()
    files: dict[str, bytes] = {}
    if data[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                rel = _below(info.filename, root)
                if rel is None or info.is_dir() or (wanted is not None and rel not in wanted):
                    continue
                files[rel] = zf.read(info)
        return files
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
        for member in tf.getmembers():
            rel = _below(member.name, root)
            if rel is None or not member.isfile() or (wanted is not None and rel not in wanted):
                continue
            extracted = tf.extractfile(member)
            if extracted is not None:
                files[rel] = extracted.read()
    return files


def _below(name: str, root: str) -> str | None:
    name = name.replace("\\", "/")
    if not name.startswith(root):
        return None
    rel = name[len(root) :]
    return rel or None


def select_files(lib: Library, names: Collection[str], root: Path | None = None) -> list[str]:
    """The archive paths `lib` vendors: every name matching a `select` pattern (`fnmatch`, `*`
    also crosses `/`) plus, if `header_closure` is set, the textual include closure of those
    headers inside the extracted package at `root` (headers only, no paired sources).

    Raises `ValueError` if a pattern matches nothing or a licence file is not selected."""
    chosen: set[str] = set()
    for pattern in lib.select:
        matched = {n for n in names if fnmatch.fnmatchcase(n, pattern)}
        if not matched:
            raise ValueError(f"{lib.name}: pattern {pattern!r} matches no archive file")
        chosen |= matched
    if lib.header_closure:
        if root is None:
            raise ValueError(f"{lib.name}: header_closure needs the extracted package")
        closure = compute_closure(root, lib.header_closure, lib.include_dirs, pair_sources=False)
        chosen |= closure.files
    missing = [f for f in (*lib.licence_files, *lib.sources) if f not in chosen]
    if missing:
        raise ValueError(f"{lib.name}: licence or source files not selected: {missing}")
    return sorted(chosen)


def apply_local_changes(lib: Library, members: Mapping[str, bytes]) -> dict[str, bytes]:
    """The vendored bytes of `members` (archive path -> archive bytes): each `LocalChange` of `lib`
    applied to its file. Raises `ValueError` when a change's file is not among `members` or its
    upstream text does not occur exactly once."""
    out = dict(members)
    for change in lib.local_changes:
        if change.path not in out:
            raise ValueError(f"{lib.name}: local change of {change.path}, which is not selected")
        text = out[change.path]
        upstream = change.upstream.encode("utf-8")
        found = text.count(upstream)
        if found != 1:
            raise ValueError(
                f"{lib.name}: {change.path} holds the upstream text of a local change {found} "
                "times, not once"
            )
        out[change.path] = text.replace(upstream, change.replacement.encode("utf-8"))
    return out


# ---------------------------------------------------------------------------------------------
# Comparison with UzEngine's copy


def to_lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


@dataclass(frozen=True)
class ComparedFile:
    """One file of UzEngine's copy at the selected commit against the upstream package.

    `upstream_sha256` / `upstream_lf_sha256` are the hashes of the upstream file at the same
    relative path (raw, and with CRLF -> LF), or None if the package has no such file."""

    path: str
    uzengine_blob: str
    upstream_sha256: str | None
    upstream_lf_sha256: str | None
    result: Result


def classify(
    uzengine: bytes, upstream_sha256: str | None, upstream_lf_sha256: str | None
) -> Result:
    """Byte comparison of UzEngine's file with the recorded upstream hashes."""
    if upstream_sha256 is None:
        return "uzengine-only"
    if sha256_hex(uzengine) == upstream_sha256:
        return "identical"
    if sha256_hex(to_lf(uzengine)) == upstream_lf_sha256:
        return "line-endings"
    return "different"


def compare(
    uzengine: Mapping[str, tuple[str, bytes]], upstream: Mapping[str, bytes]
) -> list[ComparedFile]:
    """Compare every UzEngine file (`path -> (blob id, bytes)`) with the upstream package."""
    compared: list[ComparedFile] = []
    for path in sorted(uzengine):
        blob, data = uzengine[path]
        up = upstream.get(path)
        up_sha = sha256_hex(up) if up is not None else None
        up_lf = sha256_hex(to_lf(up)) if up is not None else None
        compared.append(ComparedFile(path, blob, up_sha, up_lf, classify(data, up_sha, up_lf)))
    return compared


def unexplained(lib: Library, compared: Sequence[ComparedFile]) -> list[str]:
    """Differing or UzEngine-only files without a recorded cause, and recorded causes that no
    longer match a difference."""
    needing = {c.path for c in compared if c.result in ("different", "uzengine-only")}
    problems = [
        f"{lib.name}: {p} differs from upstream without a recorded cause"
        for p in sorted(needing - set(lib.differences))
    ]
    problems += [
        f"{lib.name}: recorded cause for {p}, which does not differ"
        for p in sorted(set(lib.differences) - needing)
    ]
    return problems


# ---------------------------------------------------------------------------------------------
# Per-library manifest


@dataclass(frozen=True)
class VendoredFile:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class LibraryManifest:
    """`thirdparty/<folder>/MANIFEST.json`: the pinned package, the vendored files and the byte
    comparison with UzEngine's copy at `uzengine_commit`."""

    library: str
    upstream: str
    version: str
    commit: str | None
    archive_url: str
    archive_sha256: str
    archive_root: str
    files: list[VendoredFile]
    uzengine_commit: str
    uzengine_dir: str | None
    comparison: list[ComparedFile]
    not_in_uzengine: list[str]


def build_manifest(
    lib: Library, selected: Mapping[str, bytes], compared: Sequence[ComparedFile]
) -> LibraryManifest:
    uzengine_paths = {c.path for c in compared}
    return LibraryManifest(
        library=lib.name,
        upstream=lib.upstream,
        version=lib.version,
        commit=lib.commit,
        archive_url=lib.archive_url,
        archive_sha256=lib.archive_sha256,
        archive_root=lib.archive_root,
        files=[
            VendoredFile(path, sha256_hex(data), len(data))
            for path, data in sorted(selected.items())
        ],
        uzengine_commit=UZENGINE_COMMIT,
        uzengine_dir=lib.uzengine_dir,
        comparison=list(compared),
        not_in_uzengine=sorted(set(selected) - uzengine_paths),
    )


def dumps_manifest(manifest: LibraryManifest) -> str:
    return json.dumps(asdict(manifest), indent=2) + "\n"


def loads_manifest(text: str) -> LibraryManifest:
    raw = cast(dict[str, Any], json.loads(text))
    comparison: list[ComparedFile] = []
    for item in cast(list[dict[str, Any]], raw["comparison"]):
        result = item["result"]
        if result not in RESULTS:
            raise ValueError(f"bad comparison result {result!r} for {item.get('path')}")
        comparison.append(
            ComparedFile(
                path=str(item["path"]),
                uzengine_blob=str(item["uzengine_blob"]),
                upstream_sha256=_opt_str(item["upstream_sha256"]),
                upstream_lf_sha256=_opt_str(item["upstream_lf_sha256"]),
                result=result,
            )
        )
    return LibraryManifest(
        library=str(raw["library"]),
        upstream=str(raw["upstream"]),
        version=str(raw["version"]),
        commit=_opt_str(raw["commit"]),
        archive_url=str(raw["archive_url"]),
        archive_sha256=str(raw["archive_sha256"]),
        archive_root=str(raw["archive_root"]),
        files=[
            VendoredFile(str(f["path"]), str(f["sha256"]), int(f["size"]))
            for f in cast(list[dict[str, Any]], raw["files"])
        ],
        uzengine_commit=str(raw["uzengine_commit"]),
        uzengine_dir=_opt_str(raw["uzengine_dir"]),
        comparison=comparison,
        not_in_uzengine=[str(p) for p in cast(list[Any], raw["not_in_uzengine"])],
    )


def _opt_str(value: object) -> str | None:
    return None if value is None else str(value)


def load_manifest(repo_root: Path, lib: Library) -> LibraryManifest:
    return loads_manifest((repo_root / lib.path / "MANIFEST.json").read_text(encoding="utf-8"))


def folder_problems(repo_root: Path, lib: Library, manifest: LibraryManifest) -> list[str]:
    """The vendored folder against its table entry and manifest: pins equal, every manifest
    file present with its hash, no file outside the manifest, licence files present."""
    problems: list[str] = []
    pins = {
        "upstream": (manifest.upstream, lib.upstream),
        "version": (manifest.version, lib.version),
        "commit": (manifest.commit, lib.commit),
        "archive_url": (manifest.archive_url, lib.archive_url),
        "archive_sha256": (manifest.archive_sha256, lib.archive_sha256),
        "archive_root": (manifest.archive_root, lib.archive_root),
        "uzengine_dir": (manifest.uzengine_dir, lib.uzengine_dir),
    }
    problems += [
        f"{lib.name}: manifest {key} {got!r} != table {want!r}"
        for key, (got, want) in pins.items()
        if got != want
    ]
    root = repo_root / lib.path
    listed = {f.path for f in manifest.files}
    for entry in manifest.files:
        path = root / entry.path
        if not path.is_file():
            problems.append(f"{lib.path}/{entry.path}: missing")
            continue
        digest = sha256_hex(path.read_bytes())
        if digest != entry.sha256:
            problems.append(f"{lib.path}/{entry.path}: sha256 {digest} != manifest {entry.sha256}")
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel not in listed and rel not in METADATA_FILES:
            problems.append(f"{lib.path}/{rel}: not in the manifest")
    problems += [
        f"{lib.name}: licence file {f} not vendored" for f in lib.licence_files if f not in listed
    ]
    return problems


# ---------------------------------------------------------------------------------------------
# ORIGIN.md


def render_origin(lib: Library, manifest: LibraryManifest) -> str:
    """`ORIGIN.md` of a library, written from the table and the manifest."""
    commit = f"`{lib.commit}`" if lib.commit else "none (NuGet package, not a git tag)"
    provenance = (
        "Every file below is byte-equal to the archive member at the same path, except for the "
        "local changes listed below; none was taken from a UzEngine tree. `MANIFEST.json` "
        "records the SHA-256 of each vendored file."
        if lib.local_changes
        else "Every file below is byte-equal to the archive member at the same path; none was "
        "taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file."
    )
    lines = [
        f"# Origin of {lib.name}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Upstream | {lib.upstream} |",
        f"| Release | `{lib.version}` |",
        f"| Tag commit | {commit} |",
        f"| Archive | {lib.archive_url} |",
        f"| Archive SHA-256 | `{lib.archive_sha256}` |",
        f"| Archive root | `{lib.archive_root or '(none)'}` (stripped; paths below are relative "
        "to it) |",
        f"| Retrieved | {RETRIEVED} |",
        f"| Importer | {lib.importer} |",
        f"| Version source | {_version_source(lib)} |",
        f"| Licence | {lib.licence} |",
        f"| Licence files | {', '.join(f'`{f}`' for f in lib.licence_files)} (verbatim) |",
        f"| Distribution role | {lib.role} |",
        f"| Selected features | {lib.features} |",
        f"| Include directories | {', '.join(f'`{lib.path}/{d}`' for d in lib.include_dirs)} |",
        "",
        provenance,
        "",
        "## Licence inventory",
        "",
        f"- Status: {_status(lib)}",
    ]
    lines += [f"- {note}" for note in lib.licence_notes]
    if lib.local_changes:
        lines += ["", "## Local changes", ""]
        for change in lib.local_changes:
            lines += [
                f"- `{change.path}`: {change.cause}.",
                f"  - Upstream: `{change.upstream.strip()}`",
                f"  - Vendored: `{change.replacement.strip()}`",
            ]
    lines += ["", f"## Selected files ({len(manifest.files)})", ""]
    lines += [f"- `{f.path}` ({f.size:,} bytes)" for f in manifest.files]
    lines += ["", *_comparison_section(lib, manifest), ""]
    return "\n".join(lines)


def _version_source(lib: Library) -> str:
    if lib.uzengine_folder is None:
        return lib.version_source
    return f"UzEngine commit `{UZENGINE_COMMIT[:12]}`: {lib.version_source}"


def _status(lib: Library) -> str:
    if lib.release_blocker:
        return f"**release blocker** — {lib.release_blocker}"
    return "confirmed against the pinned package (licence text, notices, hash, features, role)"


def _comparison_section(lib: Library, manifest: LibraryManifest) -> list[str]:
    if manifest.uzengine_dir is None:
        return ["## Comparison with UzEngine's copy", "", lib.uzengine_note]
    by_result: dict[Result, list[ComparedFile]] = {r: [] for r in RESULTS}
    for c in manifest.comparison:
        by_result[c.result].append(c)
    lines = [
        "## Comparison with UzEngine's copy",
        "",
        f"UzEngine `{manifest.uzengine_dir}` at commit `{manifest.uzengine_commit}`, read from the "
        "commit's blobs (`git cat-file`), compared byte for byte with the archive file at the "
        "same relative path.",
        "",
        "| Result | Files |",
        "|---|---|",
    ]
    lines += [f"| {r} | {len(by_result[r])} |" for r in RESULTS]
    lines.append(f"| selected but absent from UzEngine's tree | {len(manifest.not_in_uzengine)} |")
    lines.append("")
    if lib.uzengine_note:
        lines += [lib.uzengine_note, ""]
    explained = by_result["different"] + by_result["uzengine-only"]
    if explained:
        lines += ["Differences and their causes:", ""]
        lines += [f"- `{c.path}` ({c.result}): {lib.differences[c.path]}" for c in explained]
        lines.append("")
    if by_result["line-endings"]:
        lines += [f"Line endings only ({LINE_ENDINGS_CAUSE}):", ""]
        lines += [f"- `{c.path}`" for c in by_result["line-endings"]]
        lines.append("")
    if manifest.not_in_uzengine:
        lines += ["Selected files absent from UzEngine's tree at the commit:", ""]
        lines += [f"- `{p}`" for p in manifest.not_in_uzengine]
        lines.append("")
    if by_result["identical"]:
        lines += ["Identical files:", ""]
        lines += [f"- `{c.path}`" for c in by_result["identical"]]
        lines.append("")
    patches = [c.path for c in manifest.comparison if c.path.startswith("patches/")]
    lines.append(
        "UzEngine patches: "
        + (
            f"{', '.join(f'`{p}`' for p in patches)}, not applied (cause above)."
            if patches
            else "none under this library at the commit."
        )
    )
    return lines


# ---------------------------------------------------------------------------------------------
# Include resolution of the build


def build_include_dirs(core: bool = True) -> list[str]:
    """The third-party include directories in build order, relative to `thirdparty/`: those of
    the render core's libraries, or (`core=False`) those of the libraries only `UzPainter.exe`
    uses."""
    return [
        f"{lib.folder}/{d}".removesuffix("/.")
        for lib in LIBRARIES
        if lib.core == core
        for d in lib.include_dirs
    ]


def compiled_sources(core: bool = True) -> list[str]:
    """Third-party translation units the build compiles on their own, relative to
    `thirdparty/`: the render core's (`uzrendercore.lib`), or (`core=False`) those compiled into
    `UzPainter.exe` only."""
    return [f"{lib.folder}/{s}" for lib in LIBRARIES if lib.core == core for s in lib.sources]


def library_of(path: str) -> Library | None:
    """The library whose folder holds `path` (relative to `thirdparty/`)."""
    return LIBRARY_BY_FOLDER.get(path.split("/", 1)[0])


_CRT = "C/C++ standard library or Windows C runtime"
_INTRINSICS = "compiler intrinsics header"
_WINSDK = "Windows SDK"
_ARM = "ARM-only branch, not built for x64"
_OTHER = "non-Windows platform branch, not built"
_DOC = "example inside a documentation comment, not code"
# Includes made by vendored third-party files that stay unresolved because they name a header of
# the toolchain or the Windows SDK, or sit in a branch UzPainter's Windows x64 build never takes.
# The closure follows every preprocessor branch textually, so inactive branches show up here.
THIRD_PARTY_SYSTEM_INCLUDES: dict[str, str] = {
    "crtdbg.h": _CRT,
    "direct.h": _CRT,
    "fcntl.h": _CRT,
    "io.h": _CRT,
    "malloc.h": _CRT,
    "process.h": _CRT,
    "share.h": _CRT,
    "signal.h": _CRT,
    "stdbool.h": _CRT,
    "sys/stat.h": _CRT,
    "sys/types.h": _CRT,
    "cpuid.h": _INTRINSICS,
    "emmintrin.h": _INTRINSICS,
    "immintrin.h": _INTRINSICS,
    "intrin.h": _INTRINSICS,
    "pmmintrin.h": _INTRINSICS,
    "smmintrin.h": _INTRINSICS,
    "xmmintrin.h": _INTRINSICS,
    "combaseapi.h": _WINSDK,
    "dxgi.h": _WINSDK,
    "dxgi1_4.h": _WINSDK,
    "fileapi.h": _WINSDK,
    "guiddef.h": _WINSDK,
    "oaidl.h": _WINSDK,
    "ocidl.h": _WINSDK,
    "ole2.h": _WINSDK,
    "rpc.h": _WINSDK,
    "rpcndr.h": _WINSDK,
    "sal.h": _WINSDK + " (also Zig's mingw-w64 headers)",
    "winapifamily.h": _WINSDK,
    "wincon.h": _WINSDK,
    "arm64_neon.h": _ARM,
    "arm_neon.h": _ARM,
    "AvailabilityMacros.h": _OTHER,
    "TargetConditionals.h": _OTHER,
    "WinAdapter.h": _OTHER,
    "X11/extensions/Xrandr.h": _OTHER,
    "directfb.h": _OTHER,
    "dlfcn.h": _OTHER,
    "elfutils/debuginfod.h": _OTHER,
    "execinfo.h": _OTHER,
    "ext/stdio_filebuf.h": _OTHER,
    "ext/stdio_sync_filebuf.h": _OTHER,
    "ggp_c/vulkan_types.h": _OTHER,
    "libunwind.h": _OTHER,
    "lwp.h": _OTHER,
    "mach/mach_time.h": _OTHER,
    "nvscibuf.h": _OTHER,
    "nvscisync.h": _OTHER,
    "pthread.h": _OTHER,
    "pthread_np.h": _OTHER,
    "screen/screen.h": _OTHER,
    "sys/param.h": _OTHER,
    "sys/syscall.h": _OTHER,
    "thread.h": _OTHER,
    "unwind.h": _OTHER,
    "vulkan_sci.h": _OTHER,
    "xcb/xcb.h": _OTHER,
    "zircon/types.h": _OTHER,
    "fmt/format.h": "spdlog with `SPDLOG_FMT_EXTERNAL`, not enabled (bundled fmt is used)",
    "fmt/xchar.h": "spdlog with `SPDLOG_FMT_EXTERNAL`, not enabled (bundled fmt is used)",
    "atlbase.h": "d3dx12 with `D3DX12_USE_ATL`, not enabled (WRL `ComPtr` is used)",
    "dxguids/dxguids.h": "D3D12MA with `D3D12MA_USING_DIRECTX_HEADERS`, not enabled",
    "dxguids.h": "D3D12MA on mingw-w64 <= 11.0.1 only; Zig 0.15.2 ships mingw-w64 13.0.0",
    "my_custom_assert.h": _DOC,
    "my_custom_min.h": _DOC,
}


def include_problems(thirdparty_root: Path) -> list[str]:
    """Include check over the vendored render core and its third-party libraries.

    The closure of the core subset and the compiled third-party sources is followed through the
    core's include directories and `build_include_dirs()`, all inside `thirdparty_root`. Every
    third-party include of the core must resolve, into the folder of the library
    `subset.external_origin` names; every unresolved include must be a standard, Windows SDK or
    non-Windows header (core) or be listed in `THIRD_PARTY_SYSTEM_INCLUDES` (third-party code);
    and every listed entry must still occur."""
    core = VENDORED_DIR.removeprefix(f"{THIRDPARTY_DIR}/")
    dirs = [f"{core}/{d}".removesuffix("/.") for d in INCLUDE_DIRS] + build_include_dirs()
    problems = [
        f"include directory {d} leaves the repository's thirdparty folder"
        for d in dirs
        if d.startswith(("/", "..")) or ":" in d or "/../" in f"/{d}/"
    ]
    seeds = [f"{core}/{s}" for s in expand_seeds(thirdparty_root / core)] + compiled_sources()
    result = compute_closure(
        thirdparty_root,
        seeds,
        dirs,
        {(f"{core}/{source}", spelling) for source, spelling in PLANNED_CUTS},
        {f"{core}/{h}" for h in HEADER_ONLY},
    )
    third_party_origins = set(THIRD_PARTY_HEADERS.values()) | set(THIRD_PARTY_PREFIXES.values())
    index = index_tree(thirdparty_root)
    cuts = {(f"{core}/{source}", spelling) for source, spelling in PLANNED_CUTS}
    for source in sorted(f for f in result.files if f.startswith(f"{core}/")):
        text = (thirdparty_root / source).read_text(encoding="utf-8", errors="replace")
        for include in parse_includes(text, source):
            target = resolve_include(index, include, dirs)
            if (source, include.spelling) in cuts or target is None:
                continue
            if target.startswith(f"{core}/"):
                continue
            origin = external_origin(include.spelling) or ""
            lib = library_of(target)
            if origin not in third_party_origins or lib is None or lib.name not in origin:
                problems.append(
                    f"{source}: {include.spelling} resolves to {target}, not to the folder of "
                    f"its declared origin ({origin or 'none'})"
                )
    seen_system: set[str] = set()
    for include in result.unresolved:
        system_origin = external_origin(include.spelling)
        allowed = system_origin is not None and system_origin not in third_party_origins
        if not include.source.startswith(f"{core}/") and (
            include.spelling in THIRD_PARTY_SYSTEM_INCLUDES
        ):
            seen_system.add(include.spelling)
            allowed = True
        if not allowed:
            problems.append(f"{include.source}: unresolved include {include.spelling}")
    problems += [
        f"THIRD_PARTY_SYSTEM_INCLUDES lists {s}, which no vendored file includes unresolved"
        for s in sorted(set(THIRD_PARTY_SYSTEM_INCLUDES) - seen_system)
    ]
    return problems


# Includes made by the third-party files compiled into `UzPainter.exe` only (zlib, spng, the
# Embree, CPython and pybind11 headers) that stay unresolved because they name a toolchain or
# Windows header or sit in a branch the Windows x64 build never takes.
APPLICATION_SYSTEM_INCLUDES: dict[str, str] = {
    "alloc.h": "zlib's Borland/Turbo C branch, not built",
    "arm64_neon.h": _ARM,
    "arm_neon.h": _ARM,
    "contrib/crc32vx/crc32_vx_hooks.h": "zlib's s390x branch (`HAVE_S390X_VX`), not built",
    "ctype.h": _CRT,
    "errno.h": _CRT,
    "fcntl.h": _CRT,
    "immintrin.h": _INTRINSICS,
    "inttypes.h": _CRT,
    "io.h": _CRT,
    "malloc.h": _CRT,
    "pthread.h": _OTHER,
    "unixio.h": _OTHER,
    "stdatomic.h": _CRT,
    "stdbool.h": _CRT,
    "sys/stat.h": _CRT,
    "sys/types.h": _CRT,
    "miniz.h": (
        "spng with `SPNG_USE_MINIZ` and tinyexr with `TINYEXR_USE_MINIZ` 1, neither enabled "
        "(zlib is used)"
    ),
    "nanozlib.h": "tinyexr with `TINYEXR_USE_NANOZLIB`, not enabled (zlib is used)",
    "zfp.h": "tinyexr with `TINYEXR_USE_ZFP`, not enabled",
    "omp.h": "tinyexr with `TINYEXR_USE_OPENMP`, not enabled",
    "tests/framac_stubs.h": "spng's Frama-C analysis branch (`__FRAMAC__`), not built",
    "basetsd.h": _WINSDK + " (CPython's `pyconfig.h`, `_MSC_VER` branch)",
    "winapifamily.h": _WINSDK + " (CPython's `pyconfig.h`; fastgltf's `core.hpp`, `_WIN32`)",
    "intrin.h": _INTRINSICS + " (MSVC branches of CPython, simdjson and fastgltf)",
    "stat.h": "CPython's `HAVE_STAT_H` branch, not defined by the Windows `pyconfig.h`",
    "bits/alltypes.h": "CPython's WASI branch (`pthread_stubs.h`), not built",
    "cxxabi.h": "pybind11's `__GNUG__` branch; the C++ ABI header of Zig's libc++abi",
    "yvals.h": "pybind11's MSVC debug branch (`_MSC_VER` and `_DEBUG`), not built",
    "crtdefs.h": "pybind11's MSVC debug branch (`_MSC_VER` and `_DEBUG`), not built",
    "process.h": _CRT,
    "stdalign.h": _CRT,
    "mmintrin.h": _INTRINSICS,
    "emmintrin.h": _INTRINSICS,
    "TargetConditionals.h": "SQLite's `__APPLE__` branch, not built",
    "sys/sysctl.h": "SQLite's Apple zone allocator and fastgltf's Apple ARM CRC branch "
    "(`__APPLE__`), not built",
    "malloc/malloc.h": "SQLite's Apple zone allocator (`__APPLE__`), not built",
    "libkern/OSAtomic.h": "SQLite's Apple zone allocator (`__APPLE__`), not built",
    "mingw.h": "SQLite's `_HAVE_MINGW_H` branch (autoconf builds only), not defined",
    "_mingw.h": "SQLite's `_HAVE__MINGW_H` branch (autoconf builds only), not defined",
    "sqlite_cfg.h": "SQLite's `_HAVE_SQLITE_CONFIG_H` branch (autoconf builds only), not defined",
    "cmnintrin.h": "SQLite's Windows CE branch (`_WIN32_WCE`), not built",
    "profileapi.h": "SQLite's `hwtime.h` MSVC branch (`_MSC_VER`), not built; " + _WINSDK,
    "vxWorks.h": "SQLite's VxWorks branch (`__RTP__`, `_WRS_KERNEL`), not built",
    "semaphore.h": "SQLite's Unix VFS, VxWorks branch (`SQLITE_OS_UNIX`), not built",
    "sys/cygwin.h": "SQLite's Cygwin branch (`__CYGWIN__`), not built",
    "sys/time.h": "SQLite's kvvfs (`SQLITE_OS_KV`), not built",
    "sys/ioctl.h": "SQLite's Unix VFS (`SQLITE_OS_UNIX`), not built",
    "sys/mman.h": "SQLite's Unix VFS (`SQLITE_OS_UNIX`), simdjson's `#ifndef _WIN32` and "
    "fastgltf's Apple/Linux memory-mapping branches, not built",
    "sys/file.h": "SQLite's Unix VFS (`SQLITE_OS_UNIX`) and fastgltf's Apple/Linux "
    "memory-mapping branch, not built",
    "sys/param.h": "SQLite's Unix VFS (`SQLITE_OS_UNIX`), not built",
    "sys/mount.h": "SQLite's Unix VFS (`SQLITE_OS_UNIX`), not built",
    "sys/dcmd_blk.h": "SQLite's Unix VFS, QNX branch (`SQLITE_OS_UNIX`), not built",
    "sys/statvfs.h": "SQLite's Unix VFS, QNX branch (`SQLITE_OS_UNIX`), not built",
    "utime.h": "SQLite's Unix VFS (`SQLITE_OS_UNIX`, `HAVE_UTIME`), not built",
    "dlfcn.h": "SQLite's Unix VFS extension loading (`SQLITE_OMIT_LOAD_EXTENSION` is set)",
    "sys/uio.h": "SQLite's `carray` extension (`SQLITE_ENABLE_CARRAY`), not enabled",
    "sqlite3rtree.h": "SQLite's non-amalgamation branch (`SQLITE_AMALGAMATION` is defined)",
    "tclsqlite.h": "SQLite's test harness branch (`SQLITE_TEST`), not built",
    "unicode/ubrk.h": "SQLite's ICU extension (`SQLITE_ENABLE_ICU`), not enabled",
    "unicode/ucol.h": "SQLite's ICU extension (`SQLITE_ENABLE_ICU`), not enabled",
    "unicode/uregex.h": "SQLite's ICU extension (`SQLITE_ENABLE_ICU`), not enabled",
    "unicode/ustring.h": "SQLite's ICU extension (`SQLITE_ENABLE_ICU`), not enabled",
    "unicode/utf16.h": "SQLite's ICU extension (`SQLITE_ENABLE_ICU`), not enabled",
    "unicode/utypes.h": "SQLite's ICU extension (`SQLITE_ENABLE_ICU`), not enabled",
    "intrinsics.h": "zstd's IAR ARM branch (`__ICCARM__`), not built",
    "cet.h": "zstd's ELF branch (`__ELF__`), not built for Windows",
    "altivec.h": "zstd's xxHash POWER branch and simdjson's `ppc64` kernel, not built for x64",
    "s390intrin.h": "zstd's xxHash s390x branch, not built for x64",
    "arm_sve.h": _ARM,
    "sys/times.h": "zstd's multithreaded debug branch (`ZSTD_MULTITHREAD`), not built",
    "../legacy/zstd_legacy.h": "zstd's legacy formats (`ZSTD_LEGACY_SUPPORT`), not built",
    "xmmintrin.h": _INTRINSICS + " (ufbx's x64 SSE branch)",
    "nmmintrin.h": _INTRINSICS + " (fastgltf's x86 CRC-32C branch)",
    "x86intrin.h": _INTRINSICS + " (simdjson's x86 kernels outside Visual Studio)",
    "smmintrin.h": _INTRINSICS + " (fastgltf's x86 Clang/GCC base64 branch; simdjson's "
    "`SIMDJSON_CLANG_VISUAL_STUDIO` branch, not built)",
    "avxintrin.h": _INTRINSICS + " (fastgltf's x86 Clang/GCC base64 branch; simdjson's "
    "`SIMDJSON_CLANG_VISUAL_STUDIO` branch, not built)",
    "avx2intrin.h": _INTRINSICS + " (fastgltf's x86 Clang/GCC base64 branch; simdjson's "
    "`SIMDJSON_CLANG_VISUAL_STUDIO` branch, not built)",
    "tmmintrin.h": _INTRINSICS + ", simdjson's `SIMDJSON_CLANG_VISUAL_STUDIO` branch, not built",
    "wmmintrin.h": _INTRINSICS + ", simdjson's `SIMDJSON_CLANG_VISUAL_STUDIO` branch, not built",
    "bmiintrin.h": _INTRINSICS + ", simdjson's `SIMDJSON_CLANG_VISUAL_STUDIO` branch, not built",
    "lzcntintrin.h": _INTRINSICS + ", simdjson's `SIMDJSON_CLANG_VISUAL_STUDIO` branch, not built",
    "avx512fintrin.h": _INTRINSICS
    + ", simdjson's `SIMDJSON_CLANG_VISUAL_STUDIO` branch, not built",
    "avx512dqintrin.h": _INTRINSICS
    + ", simdjson's `SIMDJSON_CLANG_VISUAL_STUDIO` branch, not built",
    "avx512cdintrin.h": _INTRINSICS
    + ", simdjson's `SIMDJSON_CLANG_VISUAL_STUDIO` branch, not built",
    "avx512bwintrin.h": _INTRINSICS
    + ", simdjson's `SIMDJSON_CLANG_VISUAL_STUDIO` branch, not built",
    "avx512vlintrin.h": _INTRINSICS
    + ", simdjson's `SIMDJSON_CLANG_VISUAL_STUDIO` branch, not built",
    "avx512vbmiintrin.h": _INTRINSICS
    + ", simdjson's `SIMDJSON_CLANG_VISUAL_STUDIO` branch, not built",
    "avx512vbmi2intrin.h": _INTRINSICS
    + ", simdjson's `SIMDJSON_CLANG_VISUAL_STUDIO` branch, not built",
    "cpuid.h": _INTRINSICS
    + ", simdjson's `HAVE_GCC_GET_CPUID` and `USE_GCC_GET_CPUID` branch, neither defined",
    "CppCoreCheck\\Warnings.h": "simdjson's Visual Studio Code Analysis branch (`_MSC_VER`), "
    "not built",
    "nonstd/string_view.tweak.hpp": "simdjson's string-view lite (`SIMDJSON_HAS_STRING_VIEW` "
    "undefined, before C++17 only), not built",
    "meta": "simdjson's static reflection (`SIMDJSON_STATIC_REFLECTION`, 0 by default), not built",
    "strings.h": "simdjson's non-Windows branch (`#ifndef _WIN32`), not built",
    "endian.h": "simdjson's non-Windows byte-order branch, not built",
    "machine/endian.h": "simdjson's Apple/FreeBSD byte-order branch, not built",
    "sys/byteorder.h": "simdjson's Solaris byte-order branch, not built",
    "sys/endian.h": "simdjson's z/OS and FreeBSD byte-order branches, not built",
    "byteswap.h": "simdjson's Linux byte-swap branch (`__linux__`), not built",
    "sys/auxv.h": "simdjson's LoongArch Linux CPU detection, not built for x64",
    "lsxintrin.h": "simdjson's LoongArch kernels (`lsx`, `lasx`), not built for x64",
    "lasxintrin.h": "simdjson's LoongArch kernels (`lasx`), not built for x64",
    "riscv_vector.h": "simdjson's RISC-V kernels (`rvv`), not built for x64",
    "riscv_bitmanip.h": "simdjson's RISC-V kernels (`__riscv_zbc`), not built for x64",
    "arm_acle.h": _ARM + " (fastgltf's `FASTGLTF_ENABLE_ARMV8_CRC`)",
    "android/asset_manager.h": "fastgltf's Android branch (`__ANDROID__`), not built",
}

# The headers of third-party code `UzPainter.exe` includes directly (Embree's C API, CPython's C
# API through pybind11's embedding header); the rest is reached through them.
APPLICATION_HEADERS = (
    "embree/include/embree4/rtcore.h",
    "pybind11/include/pybind11/embed.h",
    "cpython-dev/include/Python.h",
    "tinyexr/tinyexr.h",
)


def application_include_problems(thirdparty_root: Path) -> list[str]:
    """Include check over the third-party code compiled into `UzPainter.exe` only.

    The closure of `compiled_sources(core=False)` and `APPLICATION_HEADERS` is followed through
    `build_include_dirs(core=False)`, all inside `thirdparty_root`; every unresolved include must
    be a standard or Windows header (`subset.external_origin`) or be listed in
    `APPLICATION_SYSTEM_INCLUDES`, and every listed entry must still occur."""
    dirs = build_include_dirs(core=False)
    problems = [
        f"include directory {d} leaves the repository's thirdparty folder"
        for d in dirs
        if d.startswith(("/", "..")) or ":" in d or "/../" in f"/{d}/"
    ]
    seeds = [*compiled_sources(core=False), *APPLICATION_HEADERS]
    result = compute_closure(thirdparty_root, seeds, dirs, pair_sources=False)
    for path in sorted(result.files):
        lib = library_of(path)
        if lib is None or lib.core:
            problems.append(
                f"{path}: reached from UzPainter.exe's third-party code, outside its libraries"
            )
    seen: set[str] = set()
    for include in result.unresolved:
        if include.spelling in APPLICATION_SYSTEM_INCLUDES:
            seen.add(include.spelling)
            continue
        if external_origin(include.spelling) is None:
            problems.append(f"{include.source}: unresolved include {include.spelling}")
    problems += [
        f"APPLICATION_SYSTEM_INCLUDES lists {s}, which no vendored file includes unresolved"
        for s in sorted(set(APPLICATION_SYSTEM_INCLUDES) - seen)
    ]
    return problems
