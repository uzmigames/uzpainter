//! The authored fixture of `tests/vendoring/test_native_input_key.py` (decision 394): a static
//! library `l` (lib/src, lib/include) and an executable `keyed` (app/, lib/include) that links it,
//! keyed by a copy of the repository's `native_input_key.zig` that the test places beside this
//! file, called the way the repository's `build.zig` calls it, with no widening.
//! `-Drefuse=<case>` builds one configuration the key must refuse.

const std = @import("std");
const native_input_key = @import("native_input_key.zig");

const Refusal = enum {
    none,
    include_dir_flag,
    include_file_flag,
    build_root_source,
    zig_out_root,
    zig_cache_root,
    generated_root,
    cwd_relative_root,
    shared_root_module,
};

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const inventory = b.option([]const u8, "inventory", "native input inventory file");
    const refuse = b.option(Refusal, "refuse", "Build a configuration the native input key must refuse") orelse .none;
    defer native_input_key.stampAll(b, .{ .inventory = inventory });

    const lib_mod = b.createModule(.{ .target = target, .optimize = optimize, .link_libc = true });
    lib_mod.addIncludePath(b.path("lib/include"));
    lib_mod.addCSourceFiles(.{
        .root = b.path("lib/src"),
        .files = &.{ "lib1.c", "lib2.c" },
        .flags = switch (refuse) {
            .include_dir_flag => &.{ "-std=c11", "-Iextra" },
            .include_file_flag => &.{ "-std=c11", "-include", "lib.h" },
            else => &.{"-std=c11"},
        },
    });
    const lib = b.addLibrary(.{ .name = "l", .linkage = .static, .root_module = lib_mod });

    const app_mod = b.createModule(.{ .target = target, .optimize = optimize, .link_libc = true });
    app_mod.addIncludePath(b.path("lib/include"));
    app_mod.addCSourceFiles(.{ .root = b.path("app"), .files = &.{ "app.c", "b.c" }, .flags = &.{"-std=c11"} });
    app_mod.linkLibrary(lib);
    switch (refuse) {
        .none, .include_dir_flag, .include_file_flag => {},
        .build_root_source => app_mod.addCSourceFile(.{ .file = b.path("root.c"), .flags = &.{"-std=c11"} }),
        .zig_out_root => app_mod.addIncludePath(b.path("zig-out/include")),
        .zig_cache_root => app_mod.addIncludePath(b.path(".zig-cache/include")),
        .generated_root => app_mod.addIncludePath(b.addWriteFiles().getDirectory()),
        .cwd_relative_root => app_mod.addIncludePath(.{ .cwd_relative = "outside" }),
        .shared_root_module => b.installArtifact(b.addExecutable(.{ .name = "twin", .root_module = app_mod })),
    }
    b.installArtifact(b.addExecutable(.{ .name = "keyed", .root_module = app_mod }));
}
