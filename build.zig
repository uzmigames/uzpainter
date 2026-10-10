//! UzPainter build (`docs/architecture/13-engine-integration.md` §4.2).
//!
//! `zig build` builds `uzrendercore`, the vendored UzEngine render core
//! (`thirdparty/uzengine-render-core/`, local modifications in its `MODIFICATIONS.md`) as a static
//! library, and the native tests of those modifications. Steps:
//!
//! - `zig build render-core`  the static library only (`zig-out/lib/uzrendercore.lib`)
//! - `zig build native-tests` the test executable with `dxcompiler.dll`, `dxil.dll` and the
//!   Agility SDK's `D3D12\D3D12Core.dll` beside it (`zig-out/bin/`)
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

    const tests_step = b.step("native-tests", "Build the native tests of the vendored modifications");
    tests_step.dependOn(&b.addInstallArtifact(test_exe, .{}).step);
    // Run-time files beside the executable, laid out as in the distribution (`13-…` §5).
    tests_step.dependOn(&b.addInstallBinFile(
        b.path("thirdparty/dxc/bin/x64/dxcompiler.dll"),
        "dxcompiler.dll",
    ).step);
    tests_step.dependOn(&b.addInstallBinFile(b.path("thirdparty/dxc/bin/x64/dxil.dll"), "dxil.dll").step);
    tests_step.dependOn(&b.addInstallBinFile(
        b.path("thirdparty/agility/build/native/bin/x64/D3D12Core.dll"),
        "D3D12/D3D12Core.dll",
    ).step);
    b.getInstallStep().dependOn(tests_step);
}

fn addCoreIncludePaths(b: *std.Build, mod: *std.Build.Module) void {
    inline for (core_include_dirs) |dir| mod.addIncludePath(b.path(core_root ++ "/" ++ dir));
    for (thirdparty_include_dirs) |dir| mod.addIncludePath(b.path(dir));
}
