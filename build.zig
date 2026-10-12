//! UzPainter build (`docs/architecture/13-engine-integration.md` §4.2).
//!
//! `zig build` builds `uzrendercore`, the vendored UzEngine render core
//! (`thirdparty/uzengine-render-core/`, local modifications in its `MODIFICATIONS.md`) as a static
//! library, the native tests of those modifications and `UzPainter.exe`. Steps:
//!
//! - `zig build render-core`  the static library only (`zig-out/lib/uzrendercore.lib`)
//! - `zig build native-tests` the test executable with `dxcompiler.dll`, `dxil.dll` and the
//!   Agility SDK's `D3D12\D3D12Core.dll` beside it (`zig-out/bin/`)
//! - `zig build painter`      `UzPainter.exe` (`src/`, the render core and libc++ linked
//!   statically) with the same run-time files plus Embree's `embree4.dll` and `tbb12.dll` and
//!   the Visual C++ runtime they import, and the embedded CPython: the embeddable package
//!   (`python313.dll`, `python313.zip`, ...), `python313._pth` and the pinned wheels unpacked into
//!   `Lib/site-packages/` (`zig-out/bin/`, the one-folder layout of `13-engine-integration.md` §5),
//!   and `capabilities.json`
//! - `zig build capabilities` the capability manifest `zig-out/bin/capabilities.json`, generated
//!   by `tools/capabilities/generate_capabilities.py` (Python on PATH, or `-Dpython=<exe>`)
//! - `zig build probe-tests`  `uzp-probe-tests.exe`, the native tests of the `selftest` probe
//!   decisions (`tests/native/selftest_probes_test.cpp`)
//! - `zig build render-tests` `uzp-render-tests.exe`, the native tests of the render layer
//!   (`src/render/`, `tests/render/render_core_test.cpp`) with the DX run-time files beside it
//! - `zig build normal-prototype` `uzp-normal-prototype.exe`, the Phase 0 tangent-frame
//!   prototype of the normal-convention fixture (`src/prototype/`, mikktspace, spng, zlib)
//! - `zig build uzp-core`     the document model as a static library (`zig-out/lib/uzp_core.lib`,
//!   `src/uzp_core/`): no render layer, no render core, no GPU
//! - `zig build uzp-core-tests` `uzp-core-tests.exe`, the native tests of the document model and
//!   the canonical manifest (`src/uzp_core/`, `tests/uzp_core/uzp_core_test.cpp`)
//! - `zig build uzp-core-transaction-tests` `uzp-core-transaction-tests.exe`, the native tests of
//!   transactions, operation records and name addressing (`tests/uzp_core/transaction_test.cpp`)
//! - `zig build evaluator-tests` `uzp-evaluator-tests.exe`, the native tests of the compositor's
//!   tile DAG, cache, admission, templates and kernels (`src/evaluator/`,
//!   `tests/evaluator/evaluator_test.cpp`) with the DX run-time files and `assets/templates/`
//!   beside it
//! - `zig build export-tests` `uzp-export-tests.exe`, the native tests of the export plan
//!   compiler (`src/export/`, `tests/export/export_test.cpp`) with `assets/templates/` beside it
//! - `zig build uzp-store`    the project store as a static library (`zig-out/lib/uzp_store.lib`,
//!   `src/store/` with SQLite and zstd); `zig build uzp-store-tests` `uzp-store-tests.exe`, its
//!   native tests with the test-only fault hooks (`tests/store/store_test.cpp`);
//!   `zig build uzp-store-save-tests` `uzp-store-save-tests.exe`, the save, retention, compaction
//!   and lock tests (`tests/store/save_test.cpp`); `zig build uzp-store-inspect-tests`
//!   `uzp-store-inspect-tests.exe`, the inspect, export-bundle and census tests
//!   (`tests/store/inspect_test.cpp`); `zig build uzp-store-settle-tests`
//!   `uzp-store-settle-tests.exe`, the settling evidence of 09 §7 end to end
//!   (`tests/store/settle_test.cpp`); `UzPainter.exe` links the store for its `inspect`,
//!   `export-bundle` and `store-census` commands
//! - `zig build mesh-tests`   `uzp-mesh-tests.exe`: the mesh importers (`src/mesh/` with ufbx,
//!   fastgltf and simdjson, the static library `uzp_mesh`, with the MikkTSpace tangents and the
//!   certificate) and their native tests (`tests/mesh/mesh_test.cpp`), plus
//!   `uzp-normal-bake.exe`, the normal-convention bake over the production tangent frames
//!   (`tests/mesh/normal_bake.cpp`) and `uzp-mesh-reload-tests.exe`, the mesh reload
//!   (`tests/mesh/reload_test.cpp`)
//!
//! Every include and library path is inside this repository. Windows system headers and import
//! libraries come from the MinGW-w64 files bundled with the pinned Zig release; nothing refers
//! to a UzEngine checkout, `runtime.lib` or a submodule.

const std = @import("std");
const builtin = @import("builtin");

/// The pinned Zig release. `build.zig.zon` declares the same version as `minimum_zig_version`;
/// this check refuses newer releases as well.
const pinned_zig: std.SemanticVersion = .{ .major = 0, .minor = 15, .patch = 2 };

comptime {
    if (builtin.zig_version.order(pinned_zig) != .eq) {
        @compileError("UzPainter builds with Zig 0.15.2 only; this is Zig " ++ builtin.zig_version_string);
    }
}

const core_root = "thirdparty/uzengine-render-core";

/// Language level and defines of the vendored core. The profiling defines (`TRACY_ENABLE`,
/// `UZ_PROFILING_ENABLED`) stay undefined, so the profiling macros and Tracy's GPU headers
/// compile to stubs and no Tracy client is linked (`13-…` §2.2).
const cxx_flags = [_][]const u8{ "-std=c++23", "-DSPDLOG_COMPILED_LIB" };

/// `dx12_d3d12ma.cpp` includes `D3D12MemAlloc.cpp`; like UzEngine's build it is compiled
/// without the undefined-behaviour sanitizer that Zig enables in Debug builds.
const d3d12ma_flags = cxx_flags ++ [_][]const u8{"-fno-sanitize=undefined"};

/// The translation units of the vendored subset (MANIFEST.json) compiled into the library,
/// relative to `core_root`. Two are listed separately: `dx12_d3d12ma.cpp` for its flags, and
/// `agility_export_source`. No DX11, Metal, engine-config or CVar source exists in the subset.
const core_sources = [_][]const u8{
    "engine/assertions/engine_assert.cpp",
    "engine/logging/log.cpp",
    "engine/math/mat4.cpp",
    "engine/math/quaternion.cpp",
    "engine/math/transform.cpp",
    "engine/math/vector2.cpp",
    "engine/math/vector3.cpp",
    "engine/math/vector4.cpp",
    "engine/paths/paths.cpp",
    "engine/profiling/profiler.cpp",
    "engine/rhi/dx12/dx12_buffer_creation.cpp",
    "engine/rhi/dx12/dx12_command_list.cpp",
    "engine/rhi/dx12/dx12_descriptor_allocator.cpp",
    "engine/rhi/dx12/dx12_device.cpp",
    "engine/rhi/dx12/dx12_fence.cpp",
    "engine/rhi/dx12/dx12_gpu_breadcrumbs.cpp",
    "engine/rhi/dx12/dx12_gpu_profiler.cpp",
    "engine/rhi/dx12/dx12_guids.cpp",
    "engine/rhi/dx12/dx12_pso_creation.cpp",
    "engine/rhi/dx12/dx12_swapchain.cpp",
    "engine/rhi/dx12/dx12_texture_creation.cpp",
    "engine/rhi/rhi_config.cpp",
    "engine/rhi/rhi_factory.cpp",
    "engine/rhi/vulkan/vulkan_command_list.cpp",
    "engine/rhi/vulkan/vulkan_device.cpp",
    "engine/rhi/vulkan/vulkan_fence.cpp",
    "engine/rhi/vulkan/vulkan_gpu_profiler.cpp",
    "engine/rhi/vulkan/vulkan_resources.cpp",
    "engine/rhi/vulkan/vulkan_swapchain.cpp",
    "engine/shader/shader_cache.cpp",
    "engine/shader/shader_compiler.cpp",
    "engine/shader/shader_reflection.cpp",
    "platform/windows/crash_handler.cpp",
    "platform/windows/file_system.cpp",
    "platform/windows/input.cpp",
    "platform/windows/platform_window.cpp",
    "platform/windows/stack_walker.cpp",
};

/// Exports `D3D12SDKVersion` and `D3D12SDKPath` (the `D3D12` subfolder). The D3D12 loader
/// reads these exports from the executable only, so this file is compiled into each
/// executable, never into the library (as in UzEngine's build).
const agility_export_source = "engine/rhi/dx12/dx12_agility.cpp";

/// Include directories of the vendored core, relative to `core_root`: the folders its quoted
/// includes name (UzEngine's `engine_include_dirs` reduced to the vendored subset).
const core_include_dirs = [_][]const u8{
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
};

/// Third-party include directories in search order (`tools/vendoring/thirdparty.py`,
/// `build_include_dirs`). DirectX-Headers precede the Agility SDK headers, which they shadow.
const thirdparty_include_dirs = [_][]const u8{
    "thirdparty/spdlog/include",
    "thirdparty/tracy/public",
    "thirdparty/directxmath/Inc",
    "thirdparty/spirv-reflect",
    "thirdparty/spirv-reflect/include",
    "thirdparty/vulkan-headers/include",
    "thirdparty/volk",
    "thirdparty/vma/include",
    "thirdparty/d3d12ma/include",
    "thirdparty/d3d12ma/src",
    "thirdparty/directx-headers/include",
    "thirdparty/directx-headers/include/directx",
    "thirdparty/agility/build/native/include",
    "thirdparty/dxc/inc",
};

/// spdlog is compiled as a library (`SPDLOG_COMPILED_LIB`) with its bundled {fmt}.
const spdlog_sources = [_][]const u8{
    "async.cpp",
    "bundled_fmtlib_format.cpp",
    "cfg.cpp",
    "color_sinks.cpp",
    "file_sinks.cpp",
    "spdlog.cpp",
    "stdout_sinks.cpp",
};

/// UzPainter's own C++ sources, relative to `src/`, compiled into `UzPainter.exe`.
const app_sources = [_][]const u8{
    "main.cpp",
    "selftest/harness.cpp",
    "selftest/hardware_slice.cpp",
    "selftest/png16.cpp",
    "selftest/embree_stage.cpp",
    "selftest/probe_report.cpp",
    "selftest/probes.cpp",
    "selftest/dx12_probes.cpp",
    "selftest/vulkan_probes.cpp",
    "selftest/cpython_stages.cpp",
    "python/interpreter.cpp",
    "python/uzpainter_module.cpp",
};

/// UzPainter's render layer over the vendored RHI (`src/render/`, P1-CORE), relative to `src/`:
/// compiled into `UzPainter.exe` and into `uzp-render-tests.exe`.
const render_sources = [_][]const u8{
    "render/backend.cpp",
    "render/capabilities.cpp",
    "render/device.cpp",
    "render/dilation.cpp",
    "render/engine_thread.cpp",
    "render/image_pass.cpp",
    "render/kernel_cache.cpp",
    "render/mips.cpp",
    "render/resample.cpp",
    "render/texture_readback.cpp",
    "render/uv_raster.cpp",
    "render/xxhash64.cpp",
};
/// Warnings are errors in UzPainter's render layer and its tests (never in vendored code).
const own_warning_flags = [_][]const u8{ "-Wall", "-Wextra", "-Werror" };

/// Third-party code only `UzPainter.exe` uses (`tools/vendoring/thirdparty.py`, libraries with
/// `core=False`): include directories in the order of `build_include_dirs(core=False)`, and the
/// C sources of `compiled_sources(core=False)`. Embree contributes headers only: its DLL is loaded
/// at run time. CPython contributes its C API headers and the import library of `python313.dll`
/// (`thirdparty/cpython-dev/`), pybind11 its headers.
const app_thirdparty_include_dirs = [_][]const u8{
    "thirdparty/embree/include",
    "thirdparty/zlib",
    "thirdparty/spng/spng",
    "thirdparty/tinyexr",
    "thirdparty/cpython-dev/include",
    "thirdparty/pybind11/include",
};
const python_import_library = "thirdparty/cpython-dev/libs/python313.lib";
const zlib_sources = [_][]const u8{
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
};
/// spng without DLL import/export decorations, on zlib (`SPNG_USE_MINIZ` undefined).
const spng_flags = [_][]const u8{ "-std=c11", "-DSPNG_STATIC" };
/// Mikkelsen's reference `mikktspace.c`, vendored unpatched: its `QuickSort` pivot rotate shifts a
/// 32-bit value by 32 when the rotate amount is 0, which the Debug sanitizer traps, so it is
/// compiled without it (`thirdparty/mikktspace/ORIGIN.md`).
const mikktspace_flags = [_][]const u8{ "-std=c11", "-fno-sanitize=undefined" };
/// Include directories of `uzp-normal-prototype.exe` (`src/prototype/`), the Phase 0
/// tangent-frame prototype: mikktspace and the PNG encoder only, no render core.
const prototype_include_dirs = [_][]const u8{
    "thirdparty/mikktspace",
    "thirdparty/zlib",
    "thirdparty/spng/spng",
};
/// The document model (`src/uzp_core/`, `docs/architecture/03-project-model.md`, `04-…` §1,
/// `09-project-file-format.md`), relative to `src/`. No third-party code.
const uzp_core_sources = [_][]const u8{
    "uzp_core/manifest/json.cpp",
    "uzp_core/manifest/sha256.cpp",
    "uzp_core/manifest/manifest.cpp",
    "uzp_core/types/receipt.cpp",
    "uzp_core/types/resource_url.cpp",
    "uzp_core/types/validation.cpp",
    "uzp_core/document/document.cpp",
    "uzp_core/document/nodes.cpp",
    "uzp_core/naming/naming.cpp",
    "uzp_core/operation/operation.cpp",
    "uzp_core/transaction/transaction.cpp",
};
/// Warnings are errors in UzPainter's document model and its tests (never in vendored code).
const uzp_core_flags = cxx_flags ++ [_][]const u8{ "-Wall", "-Wextra", "-Werror" };
/// The compositor (`src/evaluator/`, P1-COMPOSITOR, `04-layer-stack-and-compositing.md` §7),
/// relative to `src/`: compiled into `UzPainter.exe` and into `uzp-evaluator-tests.exe` over the
/// render layer and the document model. Contraction is off so that every float operation of its
/// CPU reference is one IEEE operation, as in its kernels (`src/evaluator/arith.h`).
const evaluator_sources = [_][]const u8{
    "evaluator/admission.cpp",
    "evaluator/arith.cpp",
    "evaluator/cpu_store.cpp",
    "evaluator/dag.cpp",
    "evaluator/diagnostics.cpp",
    "evaluator/error.cpp",
    "evaluator/evaluate.cpp",
    "evaluator/evaluator.cpp",
    "evaluator/geometry_mask.cpp",
    "evaluator/gpu_store.cpp",
    "evaluator/hash.cpp",
    "evaluator/height_to_normal.cpp",
    "evaluator/hwmath.cpp",
    "evaluator/kernelgen.cpp",
    "evaluator/profile.cpp",
    "evaluator/projection_uv.cpp",
    "evaluator/sources.cpp",
    "evaluator/support.cpp",
    "evaluator/templates.cpp",
};
/// The export plan compiler (`src/export/`, P1-EXPORT, `08-export.md` §1, §2, §6), relative to
/// `src/`: compiled with the evaluator into `UzPainter.exe` and into `uzp-export-tests.exe`.
const export_sources = [_][]const u8{
    "export/config.cpp",
    "export/encode.cpp",
    "export/exr_writer.cpp",
    "export/padding.cpp",
    "export/plan.cpp",
    "export/png_writer.cpp",
    "export/virtual_maps.cpp",
    "export/write.cpp",
};
/// tinyexr's implementation (`thirdparty/tinyexr/`, decision 089), one translation unit of
/// third-party code relative to `src/`: compiled without UzPainter's warning flags.
const tinyexr_unit = "export/tinyexr_unit.cpp";
/// spng is linked statically wherever the evaluator is (its bitmap decoder, `sources.h`).
const evaluator_flags = cxx_flags ++ own_warning_flags ++ [_][]const u8{ "-ffp-contract=off", "-DSPNG_STATIC" };
/// The project templates the evaluator reads (`src/evaluator/templates.h`), installed beside the
/// executables as `bin/assets/templates/`.
const templates_dir = "assets/templates";
/// The mesh importers (`src/mesh/`, `docs/architecture/12-mesh-import.md`), relative to `src/`,
/// compiled with `uzp_core_flags` into `uzp_mesh.lib`.
const mesh_sources = [_][]const u8{
    "mesh/texturing_mesh.cpp",
    "mesh/mesh_builder.cpp",
    "mesh/obj_parser.cpp",
    "mesh/fbx_import.cpp",
    "mesh/gltf_import.cpp",
    "mesh/mesh_import.cpp",
    "mesh/mask_image.cpp",
    "mesh/tangents.cpp",
    "mesh/certificate.cpp",
    "mesh/reload.cpp",
};
/// Third-party include directories of the mesh importers (`tools/vendoring/thirdparty.py`): ufbx,
/// fastgltf and the simdjson it parses with, and the PNG decoder of the orientation contract.
const mesh_thirdparty_include_dirs = [_][]const u8{
    "thirdparty/ufbx",
    "thirdparty/fastgltf/include",
    "thirdparty/simdjson/singleheader",
    "thirdparty/zlib",
    "thirdparty/spng/spng",
    "thirdparty/mikktspace",
};
/// ufbx's single C file, vendored unpatched.
const ufbx_flags = [_][]const u8{"-std=c11"};
/// fastgltf's units and the simdjson amalgamation it includes as `<simdjson.h>`, vendored
/// unpatched. Both select SIMD kernels at run time through function target attributes, which
/// Zig 0.15.2's clang no longer completes from the attribute alone: fastgltf's SSE4.2 CRC-32C
/// needs the `crc32` feature (`-mcrc32`) and simdjson's AVX-512 kernel the `evex512` feature
/// (`-mevex512`; both `ORIGIN.md` files). Zig passes the target's feature list after `-cflags`,
/// so the two features are added to the target of the library `uzp_gltf` instead. Neither
/// enables an instruction set by itself (`crc32` only backs the intrinsics, `evex512` only
/// widens AVX-512 code that a target region enables); the kernels still run only on processors
/// whose run-time check selects them.
const fastgltf_sources = [_][]const u8{ "fastgltf.cpp", "base64.cpp", "io.cpp" };

/// The project store (`src/store/`, `docs/architecture/09-project-file-format.md`), relative to
/// `src/`, compiled with `uzp_core_flags` into `uzp_store.lib` with SQLite and zstd.
const store_sources = [_][]const u8{
    "store/container.cpp",
    "store/blobs.cpp",
    "store/versioning.cpp",
    "store/integrity.cpp",
    "store/commit.cpp",
    "store/planes.cpp",
    "store/plane_integrity.cpp",
    "store/project_store.cpp",
    "store/save.cpp",
    "store/compact.cpp",
    "store/lock.cpp",
    "store/inspect.cpp",
    "store/bundle_codec.cpp",
    "store/bundle.cpp",
    "store/census.cpp",
    "store/cli.cpp",
};
/// Test-only fault hooks of the store (`src/store/fault.h`): compiled, with
/// `-DUZP_STORE_FAULT_HOOKS=1` on every store source, into `uzp-store-tests.exe` only, never into
/// `uzp_store.lib`.
const store_fault_source = "store/fault.cpp";
const store_thirdparty_include_dirs = [_][]const u8{ "thirdparty/sqlite", "thirdparty/zstd/lib" };
/// The SQLite amalgamation with the options recorded in `thirdparty/sqlite/ORIGIN.md`.
const sqlite_flags = [_][]const u8{
    "-std=c11",
    "-DSQLITE_THREADSAFE=1",
    "-DSQLITE_DQS=0",
    "-DSQLITE_DEFAULT_FOREIGN_KEYS=1",
    "-DSQLITE_OMIT_LOAD_EXTENSION",
    "-DSQLITE_OMIT_DEPRECATED",
};
/// zstd without its x86-64 assembly (not vendored), multithreading or legacy formats.
const zstd_flags = [_][]const u8{ "-std=c11", "-DZSTD_DISABLE_ASM" };
const zstd_sources = [_][]const u8{
    "common/debug.c",
    "common/entropy_common.c",
    "common/error_private.c",
    "common/fse_decompress.c",
    "common/pool.c",
    "common/threading.c",
    "common/xxhash.c",
    "common/zstd_common.c",
    "compress/fse_compress.c",
    "compress/hist.c",
    "compress/huf_compress.c",
    "compress/zstd_compress.c",
    "compress/zstd_compress_literals.c",
    "compress/zstd_compress_sequences.c",
    "compress/zstd_compress_superblock.c",
    "compress/zstd_double_fast.c",
    "compress/zstd_fast.c",
    "compress/zstd_lazy.c",
    "compress/zstd_ldm.c",
    "compress/zstd_opt.c",
    "compress/zstd_preSplit.c",
    "compress/zstdmt_compress.c",
    "decompress/huf_decompress.c",
    "decompress/zstd_ddict.c",
    "decompress/zstd_decompress.c",
    "decompress/zstd_decompress_block.c",
};

/// Run-time files installed beside the executables (`zig-out/bin/`) as in the distribution
/// (`13-engine-integration.md` §5): repository path, then the path below `bin/`.
const dx_runtime_files = [_][2][]const u8{
    .{ "thirdparty/dxc/bin/x64/dxcompiler.dll", "dxcompiler.dll" },
    .{ "thirdparty/dxc/bin/x64/dxil.dll", "dxil.dll" },
    .{ "thirdparty/agility/build/native/bin/x64/D3D12Core.dll", "D3D12/D3D12Core.dll" },
};
/// Embree, and the Visual C++ runtime its prebuilt DLLs import, app-local
/// (`tools/vendoring/vcruntime.py`). `vcruntime140.dll` and `vcruntime140_1.dll` come with the
/// CPython embeddable package (`thirdparty/cpython/`, file version 14.51), which is newer than
/// `thirdparty/vc-runtime/`'s (14.44) and so serves Embree, `msvcp140.dll` and CPython alike.
const embree_runtime_files = [_][2][]const u8{
    .{ "thirdparty/embree/bin/embree4.dll", "embree4.dll" },
    .{ "thirdparty/embree/bin/tbb12.dll", "tbb12.dll" },
    .{ "thirdparty/vc-runtime/msvcp140.dll", "msvcp140.dll" },
};
/// The CPython embeddable package (`thirdparty/cpython/`): every vendored file is installed
/// beside the executable except the licence text and the vendoring metadata.
const cpython_package_dir = "thirdparty/cpython";
const cpython_package_excluded = [_][]const u8{ ".txt", ".md", ".json" };
/// UzPainter's module search path of the embedded interpreter, beside `python313.dll`.
const cpython_pth_file = "src/python/python313._pth";
/// The pinned wheel closure of the MCP SDK (`tools/vendoring/wheels.py`), unpacked into
/// `bin/Lib/site-packages/`.
const wheels_dir = "thirdparty/python-wheels";
/// Top-level wheel folders left out of the install, with the reasons in
/// `tools/vendoring/wheels.py` (`NOT_INSTALLED`): pywin32's Pythonwin (needs the MFC runtime,
/// which is not shipped) and `adodbapi` (LGPL-2.1); the MCP SDK uses neither.
const wheel_folders_not_installed = [_][]const u8{ "pythonwin", "adodbapi" };

/// Windows system libraries the core links against (import libraries from Zig's MinGW-w64).
const system_libraries = [_][]const u8{
    "d3d12",
    "dxgi",
    "dxguid",
    "dbghelp",
    "winmm",
    "xinput1_4",
    "shcore",
    "ole32",
    "shell32",
    "user32",
    "gdi32",
};

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{
        .default_target = .{ .cpu_arch = .x86_64, .os_tag = .windows, .abi = .gnu },
        .whitelist = &.{.{ .cpu_arch = .x86_64, .os_tag = .windows, .abi = .gnu }},
    });
    const optimize = b.standardOptimizeOption(.{});

    // ── uzrendercore: the vendored render core as a static library ──────────────────────────

    const core_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    addCoreIncludePaths(b, core_mod);
    core_mod.addCSourceFiles(.{
        .root = b.path(core_root),
        .files = &core_sources,
        .flags = &cxx_flags,
    });
    core_mod.addCSourceFiles(.{
        .root = b.path(core_root),
        .files = &.{"engine/rhi/dx12/dx12_d3d12ma.cpp"},
        .flags = &d3d12ma_flags,
    });
    core_mod.addCSourceFiles(.{
        .root = b.path("thirdparty/spdlog/src"),
        .files = &spdlog_sources,
        .flags = &cxx_flags,
    });
    // volk's implementation is compiled by `engine/rhi/vulkan/vulkan_device.cpp`, which
    // defines VOLK_IMPLEMENTATION before including volk.h (volk.h then includes volk.c), so
    // volk.c is not compiled on its own.
    core_mod.addCSourceFiles(.{
        .root = b.path("thirdparty/spirv-reflect"),
        .files = &.{"spirv_reflect.c"},
        .flags = &.{"-std=c11"},
    });
    for (system_libraries) |name| core_mod.linkSystemLibrary(name, .{});

    const core_lib = b.addLibrary(.{
        .linkage = .static,
        .name = "uzrendercore",
        .root_module = core_mod,
    });
    const install_core = b.addInstallArtifact(core_lib, .{});
    b.getInstallStep().dependOn(&install_core.step);

    const core_step = b.step("render-core", "Build the vendored render core as a static library");
    core_step.dependOn(&install_core.step);

    // ── Native tests of the local modifications (MODIFICATIONS.md) ───────────────────────────

    const test_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    addCoreIncludePaths(b, test_mod);
    test_mod.addCSourceFiles(.{
        .root = b.path("tests/native"),
        .files = &.{"vendor_modifications_test.cpp"},
        .flags = &cxx_flags,
    });
    test_mod.addCSourceFiles(.{
        .root = b.path(core_root),
        .files = &.{agility_export_source},
        .flags = &cxx_flags,
    });
    test_mod.linkLibrary(core_lib);
    for (system_libraries) |name| test_mod.linkSystemLibrary(name, .{});
    // Module enumeration and file version resources for the Agility SDK check.
    test_mod.linkSystemLibrary("psapi", .{});
    test_mod.linkSystemLibrary("version", .{});

    const test_exe = b.addExecutable(.{
        .name = "uzp-vendor-tests",
        .root_module = test_mod,
    });

    // Run-time files beside the executables, laid out as in the distribution (`13-…` §5).
    var dx_runtime: [dx_runtime_files.len]*std.Build.Step = undefined;
    for (dx_runtime_files, 0..) |file, i| {
        dx_runtime[i] = &b.addInstallBinFile(b.path(file[0]), file[1]).step;
    }

    const tests_step = b.step("native-tests", "Build the native tests of the vendored modifications");
    tests_step.dependOn(&b.addInstallArtifact(test_exe, .{}).step);
    for (dx_runtime) |step| tests_step.dependOn(step);
    b.getInstallStep().dependOn(tests_step);

    // ── UzPainter.exe ────────────────────────────────────────────────────────────────────────

    // The Zig release and build mode are recorded in the `selftest` report.
    const app_defines = [_][]const u8{
        b.fmt("-DUZP_ZIG_VERSION=\"{s}\"", .{builtin.zig_version_string}),
        b.fmt("-DUZP_BUILD_MODE=\"{s}\"", .{@tagName(optimize)}),
    };
    const app_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    addCoreIncludePaths(b, app_mod);
    app_mod.addIncludePath(b.path("src"));
    for (app_thirdparty_include_dirs) |dir| app_mod.addIncludePath(b.path(dir));
    app_mod.addCSourceFiles(.{
        .root = b.path("src"),
        .files = &app_sources,
        .flags = &(cxx_flags ++ [_][]const u8{"-DSPNG_STATIC"} ++ app_defines),
    });
    app_mod.addCSourceFiles(.{
        .root = b.path("src"),
        .files = &render_sources,
        .flags = &(cxx_flags ++ own_warning_flags),
    });
    app_mod.addCSourceFiles(.{
        .root = b.path(core_root),
        .files = &.{agility_export_source},
        .flags = &cxx_flags,
    });
    app_mod.addCSourceFiles(.{
        .root = b.path("thirdparty/zlib"),
        .files = &zlib_sources,
        .flags = &.{"-std=c11"},
    });
    app_mod.addCSourceFiles(.{
        .root = b.path("thirdparty/spng/spng"),
        .files = &.{"spng.c"},
        .flags = &spng_flags,
    });
    app_mod.linkLibrary(core_lib);
    for (system_libraries) |name| app_mod.linkSystemLibrary(name, .{});
    // Module enumeration, file version resources and the registry (OS build) for the report.
    app_mod.linkSystemLibrary("psapi", .{});
    app_mod.linkSystemLibrary("version", .{});
    app_mod.linkSystemLibrary("advapi32", .{});
    // `UzPainter.exe` imports `python313.dll` (the embedded interpreter, `src/python/`).
    app_mod.addObjectFile(b.path(python_import_library));

    const app_exe = b.addExecutable(.{
        .name = "UzPainter",
        .root_module = app_mod,
    });

    const painter_step = b.step("painter", "Build UzPainter.exe with its run-time files");
    painter_step.dependOn(&b.addInstallArtifact(app_exe, .{}).step);
    for (dx_runtime) |step| painter_step.dependOn(step);
    for (embree_runtime_files) |file| {
        painter_step.dependOn(&b.addInstallBinFile(b.path(file[0]), file[1]).step);
    }
    painter_step.dependOn(&b.addInstallDirectory(.{
        .source_dir = b.path(cpython_package_dir),
        .install_dir = .bin,
        .install_subdir = "",
        .exclude_extensions = &cpython_package_excluded,
    }).step);
    painter_step.dependOn(&b.addInstallBinFile(b.path(cpython_pth_file), "python313._pth").step);
    painter_step.dependOn(&InstallWheels.create(b, b.path(wheels_dir), "Lib/site-packages").step);

    // ── Capability manifest (docs/architecture/10-python-api.md §3) ───────────────────────────

    // The generator reads the Tier 0 manifests and the architecture headings it cites, which a
    // directory argument does not hash, so it runs on every build (it takes well under a second).
    const python = b.option([]const u8, "python", "Python 3.13 that runs the capability manifest generator (default: python on PATH)") orelse "python";
    const capabilities_run = b.addSystemCommand(&.{ python, "-I" });
    capabilities_run.setName("generate capabilities.json");
    capabilities_run.addFileArg(b.path("tools/capabilities/generate_capabilities.py"));
    capabilities_run.addArg("--inventory");
    capabilities_run.addFileArg(b.path("tools/capabilities/painter-api-inventory.json"));
    capabilities_run.addArg("--additions");
    capabilities_run.addFileArg(b.path("tools/capabilities/uzpainter-additions.json"));
    capabilities_run.addArg("--compositor");
    capabilities_run.addFileArg(b.path("tools/capabilities/compositor-capabilities.json"));
    capabilities_run.addArg("--repo-root");
    capabilities_run.addDirectoryArg(b.path("."));
    capabilities_run.addArg("--output");
    const capabilities_json = capabilities_run.addOutputFileArg("capabilities.json");
    capabilities_run.has_side_effects = true;
    const capabilities_step = b.step("capabilities", "Generate the capability manifest bin/capabilities.json");
    capabilities_step.dependOn(&b.addInstallBinFile(capabilities_json, "capabilities.json").step);
    painter_step.dependOn(capabilities_step);
    b.getInstallStep().dependOn(painter_step);

    // ── Native tests of the probe decisions (src/selftest/probe_report.h) ─────────────────────

    const probe_tests_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    addCoreIncludePaths(b, probe_tests_mod);
    probe_tests_mod.addIncludePath(b.path("src"));
    probe_tests_mod.addCSourceFiles(.{
        .root = b.path("tests/native"),
        .files = &.{"selftest_probes_test.cpp"},
        .flags = &cxx_flags,
    });
    probe_tests_mod.addCSourceFiles(.{
        .root = b.path("src"),
        .files = &.{"selftest/probe_report.cpp"},
        .flags = &cxx_flags,
    });
    probe_tests_mod.linkLibrary(core_lib);
    for (system_libraries) |name| probe_tests_mod.linkSystemLibrary(name, .{});

    const probe_tests_exe = b.addExecutable(.{
        .name = "uzp-probe-tests",
        .root_module = probe_tests_mod,
    });
    const probe_tests_step = b.step("probe-tests", "Build the native tests of the selftest probe decisions");
    probe_tests_step.dependOn(&b.addInstallArtifact(probe_tests_exe, .{}).step);
    b.getInstallStep().dependOn(probe_tests_step);

    // ── Native tests of the render layer (src/render/, tests/render/) ─────────────────────────

    const render_tests_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    addCoreIncludePaths(b, render_tests_mod);
    render_tests_mod.addIncludePath(b.path("src"));
    render_tests_mod.addCSourceFiles(.{
        .root = b.path("tests/render"),
        .files = &.{
            "render_core_test.cpp",
            "uv_raster_test.cpp",
            "image_passes_test.cpp",
            "reference/image_reference.cpp",
        },
        .flags = &(cxx_flags ++ own_warning_flags),
    });
    render_tests_mod.addCSourceFiles(.{
        .root = b.path("src"),
        .files = &render_sources,
        .flags = &(cxx_flags ++ own_warning_flags),
    });
    render_tests_mod.addCSourceFiles(.{
        .root = b.path(core_root),
        .files = &.{agility_export_source},
        .flags = &cxx_flags,
    });
    render_tests_mod.linkLibrary(core_lib);
    for (system_libraries) |name| render_tests_mod.linkSystemLibrary(name, .{});
    // File version resources (the DXC identity in the kernel cache key).
    render_tests_mod.linkSystemLibrary("version", .{});

    const render_tests_exe = b.addExecutable(.{
        .name = "uzp-render-tests",
        .root_module = render_tests_mod,
    });
    const render_tests_step = b.step("render-tests", "Build the native tests of the render layer");
    render_tests_step.dependOn(&b.addInstallArtifact(render_tests_exe, .{}).step);
    for (dx_runtime) |step| render_tests_step.dependOn(step);
    b.getInstallStep().dependOn(render_tests_step);

    // ── Tangent-frame prototype of the normal-convention fixture (phase0.9) ───────────────────

    const prototype_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    for (prototype_include_dirs) |dir| prototype_mod.addIncludePath(b.path(dir));
    prototype_mod.addCSourceFiles(.{
        .root = b.path("src/prototype"),
        .files = &.{"normal_prototype.cpp"},
        .flags = &(cxx_flags ++ [_][]const u8{"-DSPNG_STATIC"}),
    });
    prototype_mod.addCSourceFiles(.{
        .root = b.path("thirdparty/mikktspace"),
        .files = &.{"mikktspace.c"},
        .flags = &mikktspace_flags,
    });
    prototype_mod.addCSourceFiles(.{
        .root = b.path("thirdparty/zlib"),
        .files = &zlib_sources,
        .flags = &.{"-std=c11"},
    });
    prototype_mod.addCSourceFiles(.{
        .root = b.path("thirdparty/spng/spng"),
        .files = &.{"spng.c"},
        .flags = &spng_flags,
    });
    const prototype_exe = b.addExecutable(.{
        .name = "uzp-normal-prototype",
        .root_module = prototype_mod,
    });
    const prototype_step = b.step("normal-prototype", "Build the tangent-frame prototype of the normal-convention fixture");
    prototype_step.dependOn(&b.addInstallArtifact(prototype_exe, .{}).step);
    b.getInstallStep().dependOn(prototype_step);

    // ── The document model as a static library (phase1.3_document-model) ─────────────────────
    // Only `src/` and the C++ runtime: no render layer, render core, system library or GPU, so
    // it builds and its tests run on the hosted CPU lane.

    const uzp_core_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    uzp_core_mod.addIncludePath(b.path("src"));
    uzp_core_mod.addCSourceFiles(.{
        .root = b.path("src"),
        .files = &uzp_core_sources,
        .flags = &uzp_core_flags,
    });
    const uzp_core_lib = b.addLibrary(.{
        .linkage = .static,
        .name = "uzp_core",
        .root_module = uzp_core_mod,
    });
    const install_uzp_core = b.addInstallArtifact(uzp_core_lib, .{});
    b.getInstallStep().dependOn(&install_uzp_core.step);
    const uzp_core_step = b.step("uzp-core", "Build the document model as a static library");
    uzp_core_step.dependOn(&install_uzp_core.step);

    // ── Native tests of the document model (phase1.1_docmodel-types-manifest) ─────────────────

    const uzp_core_tests_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    uzp_core_tests_mod.addIncludePath(b.path("src"));
    uzp_core_tests_mod.linkLibrary(uzp_core_lib);
    uzp_core_tests_mod.addCSourceFiles(.{
        .root = b.path("tests/uzp_core"),
        .files = &.{"uzp_core_test.cpp"},
        .flags = &uzp_core_flags,
    });
    const uzp_core_tests_exe = b.addExecutable(.{
        .name = "uzp-core-tests",
        .root_module = uzp_core_tests_mod,
    });
    const uzp_core_tests_step = b.step("uzp-core-tests", "Build the native tests of the document model");
    uzp_core_tests_step.dependOn(&b.addInstallArtifact(uzp_core_tests_exe, .{}).step);
    b.getInstallStep().dependOn(uzp_core_tests_step);

    // ── Native tests of transactions and name addressing (phase1.2_docmodel-transactions) ─────

    const uzp_core_txn_tests_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    uzp_core_txn_tests_mod.addIncludePath(b.path("src"));
    uzp_core_txn_tests_mod.linkLibrary(uzp_core_lib);
    uzp_core_txn_tests_mod.addCSourceFiles(.{
        .root = b.path("tests/uzp_core"),
        .files = &.{"transaction_test.cpp"},
        .flags = &uzp_core_flags,
    });
    const uzp_core_txn_tests_exe = b.addExecutable(.{
        .name = "uzp-core-transaction-tests",
        .root_module = uzp_core_txn_tests_mod,
    });
    const uzp_core_txn_tests_step = b.step("uzp-core-transaction-tests", "Build the native tests of transactions and name addressing");
    uzp_core_txn_tests_step.dependOn(&b.addInstallArtifact(uzp_core_txn_tests_exe, .{}).step);
    b.getInstallStep().dependOn(uzp_core_txn_tests_step);

    // ── Mesh importers (phase1.4_mesh-importers) ─────────────────────────────────────────────
    // UzPainter's own OBJ parser and its FBX (ufbx) and glTF (fastgltf on simdjson) loaders, over
    // the document model; CPU only, so the tests run on the hosted CPU lane. `src/mesh/` compiles
    // with `-Wall -Wextra -Werror` including the ufbx and fastgltf headers it uses; the vendored
    // sources keep their own flags.

    const mesh_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    mesh_mod.addIncludePath(b.path("src"));
    for (mesh_thirdparty_include_dirs) |dir| mesh_mod.addIncludePath(b.path(dir));
    mesh_mod.addCSourceFiles(.{
        .root = b.path("src"),
        .files = &mesh_sources,
        .flags = &(uzp_core_flags ++ [_][]const u8{"-DSPNG_STATIC"}),
    });
    mesh_mod.addCSourceFiles(.{
        .root = b.path("thirdparty/mikktspace"),
        .files = &.{"mikktspace.c"},
        .flags = &mikktspace_flags,
    });
    mesh_mod.addCSourceFiles(.{
        .root = b.path("thirdparty/ufbx"),
        .files = &.{"ufbx.c"},
        .flags = &ufbx_flags,
    });
    var gltf_query = target.query;
    gltf_query.cpu_features_add.addFeature(@intFromEnum(std.Target.x86.Feature.crc32));
    gltf_query.cpu_features_add.addFeature(@intFromEnum(std.Target.x86.Feature.evex512));
    const gltf_mod = b.createModule(.{
        .target = b.resolveTargetQuery(gltf_query),
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    gltf_mod.addIncludePath(b.path("thirdparty/fastgltf/include"));
    gltf_mod.addIncludePath(b.path("thirdparty/simdjson/singleheader"));
    gltf_mod.addCSourceFiles(.{
        .root = b.path("thirdparty/simdjson/singleheader"),
        .files = &.{"simdjson.cpp"},
        .flags = &cxx_flags,
    });
    gltf_mod.addCSourceFiles(.{
        .root = b.path("thirdparty/fastgltf/src"),
        .files = &fastgltf_sources,
        .flags = &cxx_flags,
    });
    mesh_mod.linkLibrary(b.addLibrary(.{
        .linkage = .static,
        .name = "uzp_gltf",
        .root_module = gltf_mod,
    }));
    mesh_mod.addCSourceFiles(.{
        .root = b.path("thirdparty/zlib"),
        .files = &zlib_sources,
        .flags = &.{"-std=c11"},
    });
    mesh_mod.addCSourceFiles(.{
        .root = b.path("thirdparty/spng/spng"),
        .files = &.{"spng.c"},
        .flags = &spng_flags,
    });
    mesh_mod.linkLibrary(uzp_core_lib);
    const mesh_lib = b.addLibrary(.{
        .linkage = .static,
        .name = "uzp_mesh",
        .root_module = mesh_mod,
    });

    const mesh_tests_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    mesh_tests_mod.addIncludePath(b.path("src"));
    mesh_tests_mod.linkLibrary(mesh_lib);
    mesh_tests_mod.linkLibrary(uzp_core_lib);
    mesh_tests_mod.addCSourceFiles(.{
        .root = b.path("tests/mesh"),
        .files = &.{"mesh_test.cpp"},
        .flags = &uzp_core_flags,
    });
    const mesh_tests_exe = b.addExecutable(.{
        .name = "uzp-mesh-tests",
        .root_module = mesh_tests_mod,
    });
    const mesh_tests_step = b.step("mesh-tests", "Build the mesh importers and their native tests");
    mesh_tests_step.dependOn(&b.addInstallArtifact(mesh_tests_exe, .{}).step);

    // The mesh reload (phase1.6_mesh-reload): `uzp-mesh-reload-tests.exe`
    // (`tests/mesh/reload_test.cpp`), CPU only.
    const mesh_reload_tests_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    mesh_reload_tests_mod.addIncludePath(b.path("src"));
    mesh_reload_tests_mod.linkLibrary(mesh_lib);
    mesh_reload_tests_mod.linkLibrary(uzp_core_lib);
    mesh_reload_tests_mod.addCSourceFiles(.{
        .root = b.path("tests/mesh"),
        .files = &.{"reload_test.cpp"},
        .flags = &uzp_core_flags,
    });
    const mesh_reload_tests_exe = b.addExecutable(.{
        .name = "uzp-mesh-reload-tests",
        .root_module = mesh_reload_tests_mod,
    });
    mesh_tests_step.dependOn(&b.addInstallArtifact(mesh_reload_tests_exe, .{}).step);

    // The normal-convention fixture re-run with the production tangent frames
    // (phase1.5_mesh-tangents-certificate): the Phase 0 prototype's bake over `src/mesh/`.
    const normal_bake_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    normal_bake_mod.addIncludePath(b.path("src"));
    normal_bake_mod.addIncludePath(b.path("thirdparty/spng/spng"));
    normal_bake_mod.linkLibrary(mesh_lib);
    normal_bake_mod.linkLibrary(uzp_core_lib);
    normal_bake_mod.addCSourceFiles(.{
        .root = b.path("tests/mesh"),
        .files = &.{"normal_bake.cpp"},
        .flags = &(uzp_core_flags ++ [_][]const u8{"-DSPNG_STATIC"}),
    });
    const normal_bake_exe = b.addExecutable(.{
        .name = "uzp-normal-bake",
        .root_module = normal_bake_mod,
    });
    mesh_tests_step.dependOn(&b.addInstallArtifact(normal_bake_exe, .{}).step);
    b.getInstallStep().dependOn(mesh_tests_step);

    // ── Project store (phase1.4_store-container-operations) ──────────────────────────────────
    // The `.uzp` container over the document model: SQLite and zstd compiled in, CPU only, so the
    // tests run on the hosted CPU lane. `sqlite3.h` and `zstd.h` compile warning-free under the
    // store's `-Wall -Wextra -Werror`. The test executable compiles the store sources again with
    // the fault hooks; the library never contains them.

    const store_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    addStoreSources(b, store_mod, &uzp_core_flags);
    store_mod.linkLibrary(uzp_core_lib);
    const store_lib = b.addLibrary(.{
        .linkage = .static,
        .name = "uzp_store",
        .root_module = store_mod,
    });
    const install_store = b.addInstallArtifact(store_lib, .{});
    const store_step = b.step("uzp-store", "Build the project store as a static library");
    store_step.dependOn(&install_store.step);
    b.getInstallStep().dependOn(&install_store.step);

    const store_hook_flags = uzp_core_flags ++ [_][]const u8{"-DUZP_STORE_FAULT_HOOKS=1"};
    const store_tests_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    addStoreSources(b, store_tests_mod, &store_hook_flags);
    store_tests_mod.addCSourceFiles(.{
        .root = b.path("src"),
        .files = &.{store_fault_source},
        .flags = &store_hook_flags,
    });
    store_tests_mod.addCSourceFiles(.{
        .root = b.path("tests/store"),
        .files = &.{"store_test.cpp"},
        .flags = &store_hook_flags,
    });
    store_tests_mod.linkLibrary(uzp_core_lib);
    const store_tests_exe = b.addExecutable(.{
        .name = "uzp-store-tests",
        .root_module = store_tests_mod,
    });
    const store_tests_step = b.step("uzp-store-tests", "Build the native tests of the project store (with its fault hooks)");
    store_tests_step.dependOn(&b.addInstallArtifact(store_tests_exe, .{}).step);
    b.getInstallStep().dependOn(store_tests_step);

    // Saving, retention, compaction, revert and the lock sidecar (phase1.6_store-save-retention):
    // their own test executable, with the same hooked store sources.
    const store_save_tests_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    addStoreSources(b, store_save_tests_mod, &store_hook_flags);
    store_save_tests_mod.addCSourceFiles(.{
        .root = b.path("src"),
        .files = &.{store_fault_source},
        .flags = &store_hook_flags,
    });
    store_save_tests_mod.addCSourceFiles(.{
        .root = b.path("tests/store"),
        .files = &.{"save_test.cpp"},
        .flags = &store_hook_flags,
    });
    store_save_tests_mod.linkLibrary(uzp_core_lib);
    const store_save_tests_exe = b.addExecutable(.{
        .name = "uzp-store-save-tests",
        .root_module = store_save_tests_mod,
    });
    const store_save_tests_step = b.step("uzp-store-save-tests", "Build the native save, retention and lock tests of the project store");
    store_save_tests_step.dependOn(&b.addInstallArtifact(store_save_tests_exe, .{}).step);
    b.getInstallStep().dependOn(store_save_tests_step);

    // `inspect`, `export-bundle` and the size census (phase1.7_store-inspect-census): their own
    // test executable with the same hooked store sources; `UzPainter.exe` gets the store verbs.
    const store_inspect_tests_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    addStoreSources(b, store_inspect_tests_mod, &store_hook_flags);
    store_inspect_tests_mod.addCSourceFiles(.{
        .root = b.path("src"),
        .files = &.{store_fault_source},
        .flags = &store_hook_flags,
    });
    store_inspect_tests_mod.addCSourceFiles(.{
        .root = b.path("tests/store"),
        .files = &.{"inspect_test.cpp"},
        .flags = &store_hook_flags,
    });
    store_inspect_tests_mod.linkLibrary(uzp_core_lib);
    const store_inspect_tests_exe = b.addExecutable(.{
        .name = "uzp-store-inspect-tests",
        .root_module = store_inspect_tests_mod,
    });
    const store_inspect_tests_step = b.step("uzp-store-inspect-tests", "Build the native inspect, bundle and census tests of the project store");
    store_inspect_tests_step.dependOn(&b.addInstallArtifact(store_inspect_tests_exe, .{}).step);
    b.getInstallStep().dependOn(store_inspect_tests_step);

    // The settling evidence of 09 §7 end to end (phase1.8_project-store): its own test executable
    // with the same hooked store sources.
    const store_settle_tests_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    addStoreSources(b, store_settle_tests_mod, &store_hook_flags);
    store_settle_tests_mod.addCSourceFiles(.{
        .root = b.path("src"),
        .files = &.{store_fault_source},
        .flags = &store_hook_flags,
    });
    store_settle_tests_mod.addCSourceFiles(.{
        .root = b.path("tests/store"),
        .files = &.{"settle_test.cpp"},
        .flags = &store_hook_flags,
    });
    store_settle_tests_mod.linkLibrary(uzp_core_lib);
    const store_settle_tests_exe = b.addExecutable(.{
        .name = "uzp-store-settle-tests",
        .root_module = store_settle_tests_mod,
    });
    const store_settle_tests_step = b.step("uzp-store-settle-tests", "Build the native settling-evidence tests of the project store (09 §7)");
    store_settle_tests_step.dependOn(&b.addInstallArtifact(store_settle_tests_exe, .{}).step);
    b.getInstallStep().dependOn(store_settle_tests_step);
    app_mod.linkLibrary(store_lib);

    // ── The compositor (phase1.5_compositor-tile-dag) ─────────────────────────────────────────
    // `src/evaluator/` joins `UzPainter.exe` (over the render layer and the document model) and
    // gets its own test executable; both carry `assets/templates/` beside them.

    app_mod.addCSourceFiles(.{
        .root = b.path("src"),
        .files = &evaluator_sources,
        .flags = &evaluator_flags,
    });
    app_mod.addCSourceFiles(.{
        .root = b.path("src"),
        .files = &export_sources,
        .flags = &evaluator_flags,
    });
    app_mod.addCSourceFiles(.{ .root = b.path("src"), .files = &.{tinyexr_unit}, .flags = &cxx_flags });
    app_mod.linkLibrary(uzp_core_lib);
    const install_templates = b.addInstallDirectory(.{
        .source_dir = b.path(templates_dir),
        .install_dir = .bin,
        .install_subdir = "assets/templates",
    });
    painter_step.dependOn(&install_templates.step);

    const evaluator_tests_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    addCoreIncludePaths(b, evaluator_tests_mod);
    evaluator_tests_mod.addIncludePath(b.path("src"));
    evaluator_tests_mod.addCSourceFiles(.{
        .root = b.path("tests/evaluator"),
        .files = &.{"evaluator_test.cpp"},
        .flags = &evaluator_flags,
    });
    evaluator_tests_mod.addCSourceFiles(.{
        .root = b.path("src"),
        .files = &evaluator_sources,
        .flags = &evaluator_flags,
    });
    evaluator_tests_mod.addCSourceFiles(.{
        .root = b.path("src"),
        .files = &render_sources,
        .flags = &(cxx_flags ++ own_warning_flags),
    });
    evaluator_tests_mod.addCSourceFiles(.{
        .root = b.path(core_root),
        .files = &.{agility_export_source},
        .flags = &cxx_flags,
    });
    evaluator_tests_mod.linkLibrary(core_lib);
    // The PNG decoder of bitmap sources (spng and zlib, compiled into `uzp_mesh`) and the mesh
    // importers of the UV-raster cases.
    evaluator_tests_mod.addIncludePath(b.path("thirdparty/spng/spng"));
    // zlib also inflates the hardware arithmetic tables (`src/evaluator/hwmath.h`).
    evaluator_tests_mod.addIncludePath(b.path("thirdparty/zlib"));
    evaluator_tests_mod.linkLibrary(mesh_lib);
    evaluator_tests_mod.linkLibrary(uzp_core_lib);
    for (system_libraries) |name| evaluator_tests_mod.linkSystemLibrary(name, .{});
    // File version resources (the DXC identity in the kernel cache key).
    evaluator_tests_mod.linkSystemLibrary("version", .{});

    const evaluator_tests_exe = b.addExecutable(.{
        .name = "uzp-evaluator-tests",
        .root_module = evaluator_tests_mod,
    });
    const evaluator_tests_step = b.step("evaluator-tests", "Build the native tests of the compositor's tile DAG");
    evaluator_tests_step.dependOn(&b.addInstallArtifact(evaluator_tests_exe, .{}).step);
    for (dx_runtime) |step| evaluator_tests_step.dependOn(step);
    evaluator_tests_step.dependOn(&install_templates.step);
    b.getInstallStep().dependOn(evaluator_tests_step);

    // ── The export plan compiler (phase1.15_export-plan-compiler) ─────────────────────────────
    // `src/export/` over the evaluator; its tests evaluate on the CPU store only, so they run on
    // hosted runners without a GPU.
    const export_tests_mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = true,
        .link_libcpp = true,
    });
    addCoreIncludePaths(b, export_tests_mod);
    export_tests_mod.addIncludePath(b.path("src"));
    export_tests_mod.addCSourceFiles(.{
        .root = b.path("tests/export"),
        .files = &.{"export_test.cpp"},
        .flags = &evaluator_flags,
    });
    export_tests_mod.addCSourceFiles(.{
        .root = b.path("src"),
        .files = &export_sources,
        .flags = &evaluator_flags,
    });
    export_tests_mod.addCSourceFiles(.{ .root = b.path("src"), .files = &.{tinyexr_unit}, .flags = &cxx_flags });
    export_tests_mod.addCSourceFiles(.{
        .root = b.path("src"),
        .files = &evaluator_sources,
        .flags = &evaluator_flags,
    });
    export_tests_mod.addCSourceFiles(.{
        .root = b.path("src"),
        .files = &render_sources,
        .flags = &(cxx_flags ++ own_warning_flags),
    });
    export_tests_mod.addCSourceFiles(.{
        .root = b.path(core_root),
        .files = &.{agility_export_source},
        .flags = &cxx_flags,
    });
    export_tests_mod.linkLibrary(core_lib);
    export_tests_mod.addIncludePath(b.path("thirdparty/spng/spng"));
    export_tests_mod.addIncludePath(b.path("thirdparty/zlib"));
    export_tests_mod.addIncludePath(b.path("thirdparty/tinyexr"));
    export_tests_mod.linkLibrary(mesh_lib);
    export_tests_mod.linkLibrary(uzp_core_lib);
    for (system_libraries) |name| export_tests_mod.linkSystemLibrary(name, .{});
    export_tests_mod.linkSystemLibrary("version", .{});
    const export_tests_exe = b.addExecutable(.{
        .name = "uzp-export-tests",
        .root_module = export_tests_mod,
    });
    const export_tests_step = b.step("export-tests", "Build the native tests of the export plan compiler");
    export_tests_step.dependOn(&b.addInstallArtifact(export_tests_exe, .{}).step);
    export_tests_step.dependOn(&install_templates.step);
    b.getInstallStep().dependOn(export_tests_step);
}

/// The project store's sources (`store_sources`, compiled with `flags`) with SQLite and zstd.
fn addStoreSources(b: *std.Build, mod: *std.Build.Module, flags: []const []const u8) void {
    mod.addIncludePath(b.path("src"));
    for (store_thirdparty_include_dirs) |dir| mod.addIncludePath(b.path(dir));
    mod.addCSourceFiles(.{ .root = b.path("src"), .files = &store_sources, .flags = flags });
    mod.addCSourceFiles(.{ .root = b.path("thirdparty/sqlite"), .files = &.{"sqlite3.c"}, .flags = &sqlite_flags });
    mod.addCSourceFiles(.{ .root = b.path("thirdparty/zstd/lib"), .files = &zstd_sources, .flags = &zstd_flags });
}

/// Installs every wheel of a folder into `<prefix>/bin/<subdir>` the way an installer lays out a
/// wheel: its archive unpacked as is. The pinned wheels have no installation scheme besides
/// console scripts (`<name>.data/scripts/`, checked by `tools/vendoring/wheels.py`), which are
/// removed, as are `wheel_folders_not_installed`. The destination is emptied first, so files of
/// earlier pins never linger.
const InstallWheels = struct {
    step: std.Build.Step,
    source: std.Build.LazyPath,
    subdir: []const u8,

    fn create(b: *std.Build, source: std.Build.LazyPath, subdir: []const u8) *InstallWheels {
        const self = b.allocator.create(InstallWheels) catch @panic("OOM");
        self.* = .{
            .step = std.Build.Step.init(.{
                .id = .custom,
                .name = b.fmt("install wheels to bin/{s}", .{subdir}),
                .owner = b,
                .makeFn = make,
            }),
            .source = source,
            .subdir = subdir,
        };
        source.addStepDependencies(&self.step);
        return self;
    }

    fn make(step: *std.Build.Step, options: std.Build.Step.MakeOptions) !void {
        _ = options;
        const self: *InstallWheels = @fieldParentPtr("step", step);
        const b = step.owner;
        const dest_path = b.getInstallPath(.bin, self.subdir);
        std.fs.cwd().deleteTree(dest_path) catch |err| {
            return step.fail("cannot empty {s}: {s}", .{ dest_path, @errorName(err) });
        };
        try std.fs.cwd().makePath(dest_path);
        var dest = try std.fs.cwd().openDir(dest_path, .{ .iterate = true });
        defer dest.close();
        var source = try std.fs.cwd().openDir(self.source.getPath2(b, step), .{ .iterate = true });
        defer source.close();
        var wheels = source.iterate();
        while (try wheels.next()) |entry| {
            if (entry.kind != .file or !std.mem.endsWith(u8, entry.name, ".whl")) continue;
            var file = try source.openFile(entry.name, .{});
            defer file.close();
            var buffer: [64 * 1024]u8 = undefined;
            var reader = file.reader(&buffer);
            std.zip.extract(dest, &reader, .{}) catch |err| {
                return step.fail("cannot unpack {s}: {s}", .{ entry.name, @errorName(err) });
            };
        }
        // Console scripts are not installed: drop every `<name>.data` folder.
        var data_dirs: std.ArrayList([]const u8) = .empty;
        var installed = dest.iterate();
        while (try installed.next()) |entry| {
            if (entry.kind == .directory and std.mem.endsWith(u8, entry.name, ".data")) {
                try data_dirs.append(b.allocator, b.dupe(entry.name));
            }
        }
        for (data_dirs.items) |name| try dest.deleteTree(name);
        for (wheel_folders_not_installed) |name| try dest.deleteTree(name);
    }
};

fn addCoreIncludePaths(b: *std.Build, mod: *std.Build.Module) void {
    inline for (core_include_dirs) |dir| mod.addIncludePath(b.path(core_root ++ "/" ++ dir));
    for (thirdparty_include_dirs) |dir| mod.addIncludePath(b.path(dir));
}
