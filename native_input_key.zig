//! The native input key (decision 394): one generated C stamp per native artifact.
//!
//! Zig 0.15.2 keys an executable or a static library on a whole-entry manifest. After a relink it
//! rewrites that manifest with its C sources and the depfile headers of only the objects it
//! recompiled in that run (INFERRED from the manifests; the compiler source is not shipped). A
//! later edit to a header that only reused objects include does not change the entry's inputs, so
//! the old binary is served without its objects being checked. `stampAll` gives every artifact a
//! stamp source whose text carries a SHA-256 over every regular file under the source and include
//! roots it declares: any edit there changes the stamp, the artifact's entry misses, every object
//! is checked against its own (truthful) manifest, and only the stamp and the objects that read
//! the edited file recompile.
//!
//! Collection, hashing and stamping are separate passes over the whole Compile graph, so no stamp
//! is ever an input of a digest. Unsupported paths fail the configuration instead of being left
//! out of the key.

const std = @import("std");
const Build = std.Build;
const Compile = Build.Step.Compile;
const Module = Build.Module;
const LazyPath = Build.LazyPath;
const Sha256 = std.crypto.hash.sha2.Sha256;

pub const Options = struct {
    /// Root widening patterns, build-root relative with `/` separators: a root whose leading
    /// components match a pattern becomes that prefix, and `*` matches any one component
    /// (`"thirdparty/*"` widens `thirdparty/zstd/lib` to `thirdparty/zstd`).
    widen: []const []const u8 = &.{},
    /// Files a compiled source reads that may lie outside every root (its `#embed` targets), keyed
    /// by the source's build-root relative path.
    extra_inputs: ?*const std.StringHashMapUnmanaged([]const []const u8) = null,
    /// Build-root relative file that receives each artifact's digest, roots and inputs, if set.
    inventory: ?[]const u8 = null,
};

/// Directories under a root that hold caches, not native inputs.
const cache_dir_names = [_][]const u8{ "__pycache__", ".zig-cache", "zig-cache", ".pytest_cache", ".mypy_cache", ".ruff_cache" };
/// Path components a root may not contain: generated output, never a source.
const output_dir_names = [_][]const u8{ ".zig-cache", "zig-cache", "zig-out" };
/// Per-source flag prefixes that name a file or directory: `-I`, every `-i…` preprocessor path
/// option (`-isystem`, `-iquote`, `-idirafter`, `-include`, `-imacros`, `-isysroot`, …), framework,
/// program and library paths, every long option (`--sysroot`, `--embed-dir`, …), response files,
/// pass-through options and module, profile and sanitizer list files.
const path_flag_prefixes = [_][]const u8{
    "-I",             "-i",      "-F",                   "-B",
    "-L",             "--",      "@",                    "-Xclang",
    "-Xpreprocessor", "-Wp,",    "-fmodule",             "-fprebuilt-module-path",
    "-fprofile",      "-fembed", "-fsanitize-blacklist", "-fsanitize-ignorelist",
};

const Artifact = struct {
    compile: *Compile,
    roots: std.StringArrayHashMapUnmanaged(void) = .empty,
    files: std.StringArrayHashMapUnmanaged(void) = .empty,
    entries: []const []const u8 = &.{},
    digest: [Sha256.digest_length]u8 = undefined,
};

const State = struct {
    b: *Build,
    options: Options,
    /// Build-root relative directories (the cache roots and the install prefix) inside the build
    /// root, case-folded: no root may be at or under one, and the walk skips them.
    excluded: []const []const u8,
    extra_inputs: std.StringHashMapUnmanaged([]const []const u8) = .empty,
    /// The regular files under each root, null for a root missing on disk.
    root_files: std.StringHashMapUnmanaged(?[]const []const u8) = .empty,
    /// The SHA-256 of each file read so far: each file is read once per configure.
    file_digests: std.StringHashMapUnmanaged([Sha256.digest_length]u8) = .empty,
};

/// Stamps every executable and library reachable from the top-level steps. Call it once, when
/// `build()` returns: the module graphs (`Module.getGraph`, cached on its first call) and the link
/// objects must be final.
pub fn stampAll(b: *Build, options: Options) void {
    const gpa = b.allocator;
    var state: State = .{ .b = b, .options = options, .excluded = excludedDirs(b) };
    if (options.extra_inputs) |extra| {
        var it = extra.iterator();
        while (it.next()) |entry| {
            state.extra_inputs.put(gpa, normalize(b, entry.key_ptr.*, "an #embed source"), entry.value_ptr.*) catch @panic("OOM");
        }
    }

    // Phase 0: every Compile reachable from the top-level steps, plus every linked Compile (the
    // module dependency edges are only wired after `build()` returns, so the link objects are
    // chased here as `Compile.getCompileDependencies` does).
    var steps: std.AutoArrayHashMapUnmanaged(*Build.Step, void) = .empty;
    for (b.top_level_steps.values()) |tls| steps.put(gpa, &tls.step, {}) catch @panic("OOM");
    var compiles: std.AutoArrayHashMapUnmanaged(*Compile, void) = .empty;
    var step_index: usize = 0;
    while (step_index < steps.count()) : (step_index += 1) {
        const step = steps.keys()[step_index];
        for (step.dependencies.items) |dependency| steps.put(gpa, dependency, {}) catch @panic("OOM");
        if (step.cast(Compile)) |compile| compiles.put(gpa, compile, {}) catch @panic("OOM");
    }
    var compile_index: usize = 0;
    while (compile_index < compiles.count()) : (compile_index += 1) {
        for (compiles.keys()[compile_index].root_module.getGraph().modules) |mod| {
            for (mod.link_objects.items) |link_object| switch (link_object) {
                .other_step => |other| compiles.put(gpa, other, {}) catch @panic("OOM"),
                else => {},
            };
        }
    }

    // Phase 1: the roots and explicit files of every artifact, all collected before any read.
    var root_owner: std.AutoHashMapUnmanaged(*Module, *Compile) = .empty;
    const artifacts = gpa.alloc(Artifact, compiles.count()) catch @panic("OOM");
    for (artifacts, compiles.keys()) |*artifact, compile| {
        const gop = root_owner.getOrPut(gpa, compile.root_module) catch @panic("OOM");
        if (gop.found_existing) std.process.fatal(
            "native input key: {s} and {s} share a root module; each artifact needs its own for its stamp (decision 394)",
            .{ gop.value_ptr.*.name, compile.name },
        );
        gop.value_ptr.* = compile;
        artifact.* = .{ .compile = compile };
        collect(&state, artifact);
    }
    // The inventory is a receipt, never an input: it may not lie under a root or be a file input.
    if (options.inventory) |path| {
        const inventory = normalize(b, path, "the inventory");
        if (inventory.len == 0) std.process.fatal("native input key: the inventory {s} names the build root (decision 394)", .{path});
        for (artifacts) |*artifact| {
            for (artifact.roots.keys()) |root| {
                if (isWithin(inventory, root)) std.process.fatal(
                    "native input key: the inventory {s} lies under the input root {s} of {s} (decision 394)",
                    .{ inventory, root, artifact.compile.name },
                );
            }
            for (artifact.files.keys()) |file| {
                if (std.ascii.eqlIgnoreCase(inventory, file)) std.process.fatal(
                    "native input key: the inventory {s} is an input of {s} (decision 394)",
                    .{ inventory, artifact.compile.name },
                );
            }
        }
    }

    // Phase 2: every digest, before any stamp exists.
    for (artifacts) |*artifact| hashArtifact(&state, artifact);

    // Phase 3: the stamps. Each is a C source with no symbol; its path and bytes are inputs of
    // its artifact's cache entry.
    for (artifacts) |*artifact| {
        const hex = std.fmt.bytesToHex(artifact.digest, .lower);
        const files = b.addWriteFiles();
        const stamp = files.add(
            b.fmt("{s}-native-inputs.c", .{artifact.compile.name}),
            b.fmt("/* UzPainter native input key v1: {s} */\ntypedef int uzp_native_input_key;\n", .{&hex}),
        );
        artifact.compile.root_module.addCSourceFile(.{ .file = stamp, .language = .c, .flags = &.{"-std=c11"} });
    }

    if (options.inventory) |path| writeInventory(b, artifacts, path);
}

/// Phase 1 for one artifact: its declared roots (widened) and explicit files.
fn collect(state: *State, artifact: *Artifact) void {
    const b = state.b;
    const compile = artifact.compile;
    if (compile.step.owner != b) fatal(compile, "is owned by a dependency's build", .{});
    switch (compile.kind) {
        .exe, .lib => {},
        else => fatal(compile, "is a {s}; only executables and libraries are keyed", .{@tagName(compile.kind)}),
    }
    if (compile.linker_script != null) fatal(compile, "has a linker script", .{});
    if (compile.version_script != null) fatal(compile, "has a version script", .{});
    if (compile.libc_file != null) fatal(compile, "has a libc file", .{});
    if (compile.entitlements != null) fatal(compile, "has an entitlements file", .{});
    if (compile.win32_manifest) |manifest| addFile(state, artifact, srcPath(state, compile, manifest, "its Win32 manifest"));

    for (compile.root_module.getGraph().modules) |mod| {
        if (mod.root_source_file != null) fatal(compile, "has a Zig root source file", .{});
        if (mod.lib_paths.items.len != 0) fatal(compile, "has library paths", .{});
        if (mod.rpaths.items.len != 0) fatal(compile, "has rpaths", .{});
        if (mod.frameworks.count() != 0) fatal(compile, "links frameworks", .{});
        for (mod.include_dirs.items) |include_dir| switch (include_dir) {
            .path, .path_system, .path_after => |path| addRoot(state, artifact, srcPath(state, compile, path, "an include directory")),
            // `linkLibrary` adds the library's installed-header tree; it is empty unless the
            // library installs headers, which would be generated copies.
            .other_step => |other| if (other.installed_headers.items.len != 0)
                fatal(compile, "includes the installed headers of {s}", .{other.name}),
            else => fatal(compile, "has a {s} include directory", .{@tagName(include_dir)}),
        };
        for (mod.link_objects.items) |link_object| switch (link_object) {
            .c_source_file => |source| {
                const path = srcPath(state, compile, source.file, "a C source file");
                checkFlags(compile, path, source.flags);
                addSource(state, artifact, path);
            },
            .c_source_files => |sources| {
                const root = srcPath(state, compile, sources.root, "a C source root");
                addRoot(state, artifact, root);
                for (sources.files) |file| {
                    const path = normalize(b, b.fmt("{s}/{s}", .{ root, file }), "a C source file");
                    checkFlags(compile, path, sources.flags);
                    addSource(state, artifact, path);
                }
            },
            .static_path => |path| addFile(state, artifact, srcPath(state, compile, path, "an object file")),
            .other_step, .system_lib => {},
            else => fatal(compile, "has a {s} link object", .{@tagName(link_object)}),
        };
    }
}

/// Refuses per-source flags that name files or directories the compiler reads (include paths,
/// forced includes, response files, sysroots, module maps, profiles): those files would not be in
/// the key. This is a list of the common path-bearing flags, not a full parser of compiler flags.
fn checkFlags(compile: *Compile, source: []const u8, flags: []const []const u8) void {
    for (flags) |flag| {
        for (path_flag_prefixes) |prefix| {
            if (std.mem.startsWith(u8, flag, prefix)) fatal(
                compile,
                "compiles {s} with the path-bearing flag {s}, which the key does not cover",
                .{ source, flag },
            );
        }
    }
}

/// A compiled source: its directory is a root, and its extra inputs are files.
fn addSource(state: *State, artifact: *Artifact, path: []const u8) void {
    const dir = std.fs.path.dirnamePosix(path) orelse "";
    addRoot(state, artifact, dir);
    if (state.extra_inputs.get(path)) |targets| {
        for (targets) |target| addFile(state, artifact, normalize(state.b, target, "an #embed target"));
    }
}

fn addRoot(state: *State, artifact: *Artifact, declared: []const u8) void {
    checkPath(state, artifact.compile, declared, "root");
    const root = widen(state.options.widen, declared);
    checkPath(state, artifact.compile, root, "widened root");
    artifact.roots.put(state.b.allocator, root, {}) catch @panic("OOM");
}

fn addFile(state: *State, artifact: *Artifact, path: []const u8) void {
    checkPath(state, artifact.compile, path, "input file");
    artifact.files.put(state.b.allocator, path, {}) catch @panic("OOM");
}

/// Refuses the build root itself and any generated or output location, before any traversal.
fn checkPath(state: *State, compile: *Compile, path: []const u8, what: []const u8) void {
    if (path.len == 0) fatal(compile, "has the build root itself as a {s}", .{what});
    var components = std.mem.splitScalar(u8, path, '/');
    while (components.next()) |component| {
        for (output_dir_names) |name| {
            if (std.ascii.eqlIgnoreCase(component, name)) fatal(compile, "has a {s} in an output directory: {s}", .{ what, path });
        }
    }
    for (state.excluded) |excluded| {
        if (isWithin(path, excluded)) fatal(compile, "has a {s} in the cache or install directory: {s}", .{ what, path });
    }
}

/// Phase 2 for one artifact: SHA-256 over the version tag, then each input in path order, as its
/// path, a zero byte and its SHA-256. A root or file missing on disk enters as `missing:<path>`
/// and a zero byte.
fn hashArtifact(state: *State, artifact: *Artifact) void {
    const b = state.b;
    const gpa = b.allocator;
    var entries: std.StringArrayHashMapUnmanaged(void) = .empty;
    for (outermost(b, artifact.roots.keys())) |root| {
        if (listRoot(state, root)) |files| {
            for (files) |file| entries.put(gpa, file, {}) catch @panic("OOM");
        } else entries.put(gpa, b.fmt("missing:{s}", .{root}), {}) catch @panic("OOM");
    }
    for (artifact.files.keys()) |file| {
        const stat = b.build_root.handle.statFile(file) catch |err| switch (err) {
            error.FileNotFound => {
                entries.put(gpa, b.fmt("missing:{s}", .{file}), {}) catch @panic("OOM");
                continue;
            },
            else => std.process.fatal("native input key: cannot stat {s}: {s}", .{ file, @errorName(err) }),
        };
        if (stat.kind != .file) std.process.fatal("native input key: {s} is not a regular file", .{file});
        entries.put(gpa, file, {}) catch @panic("OOM");
    }
    const sorted = gpa.dupe([]const u8, entries.keys()) catch @panic("OOM");
    std.mem.sort([]const u8, sorted, {}, lessThan);

    var hasher = Sha256.init(.{});
    hasher.update("uzp-native-input-key-v1\x00");
    for (sorted) |entry| {
        hasher.update(entry);
        hasher.update("\x00");
        if (!std.mem.startsWith(u8, entry, "missing:")) hasher.update(&fileDigest(state, entry));
    }
    hasher.final(&artifact.digest);
    artifact.entries = sorted;
}

/// The roots that are not inside another root of the same list.
fn outermost(b: *Build, roots: []const []const u8) []const []const u8 {
    var result: std.ArrayList([]const u8) = .empty;
    for (roots) |root| {
        const nested = for (roots) |other| {
            if (!std.ascii.eqlIgnoreCase(other, root) and isWithin(root, other)) break true;
        } else false;
        if (!nested) result.append(b.allocator, root) catch @panic("OOM");
    }
    return result.items;
}

/// The regular files under `root`, build-root relative; null when `root` does not exist.
fn listRoot(state: *State, root: []const u8) ?[]const []const u8 {
    const b = state.b;
    const gop = state.root_files.getOrPut(b.allocator, root) catch @panic("OOM");
    if (gop.found_existing) return gop.value_ptr.*;
    var dir = b.build_root.handle.openDir(root, .{ .iterate = true }) catch |err| switch (err) {
        error.FileNotFound => {
            gop.value_ptr.* = null;
            return null;
        },
        else => std.process.fatal("native input key: cannot open the root {s}/: {s}", .{ root, @errorName(err) }),
    };
    defer dir.close();
    var files: std.ArrayList([]const u8) = .empty;
    walk(state, dir, root, &files);
    gop.value_ptr.* = files.items;
    return files.items;
}

fn walk(state: *State, dir: std.fs.Dir, rel: []const u8, files: *std.ArrayList([]const u8)) void {
    const b = state.b;
    var it = dir.iterate();
    while (it.next() catch |err| std.process.fatal("native input key: cannot list {s}/: {s}", .{ rel, @errorName(err) })) |entry| {
        const child = b.fmt("{s}/{s}", .{ rel, entry.name });
        switch (entry.kind) {
            .file => files.append(b.allocator, child) catch @panic("OOM"),
            .directory => {
                const skipped = for (cache_dir_names) |name| {
                    if (std.ascii.eqlIgnoreCase(entry.name, name)) break true;
                } else for (state.excluded) |excluded| {
                    if (isWithin(child, excluded)) break true;
                } else false;
                if (skipped) continue;
                var sub = dir.openDir(entry.name, .{ .iterate = true }) catch |err|
                    std.process.fatal("native input key: cannot open {s}/: {s}", .{ child, @errorName(err) });
                defer sub.close();
                walk(state, sub, child, files);
            },
            else => std.process.fatal(
                "native input key: {s} is a {s}; a native input root may hold only regular files and directories (decision 394)",
                .{ child, @tagName(entry.kind) },
            ),
        }
    }
}

fn fileDigest(state: *State, path: []const u8) [Sha256.digest_length]u8 {
    const gop = state.file_digests.getOrPut(state.b.allocator, path) catch @panic("OOM");
    if (gop.found_existing) return gop.value_ptr.*;
    var file = state.b.build_root.handle.openFile(path, .{}) catch |err|
        std.process.fatal("native input key: cannot open {s}: {s}", .{ path, @errorName(err) });
    defer file.close();
    var hasher = Sha256.init(.{});
    var buffer: [64 * 1024]u8 = undefined;
    while (true) {
        const n = file.read(&buffer) catch |err| std.process.fatal("native input key: cannot read {s}: {s}", .{ path, @errorName(err) });
        if (n == 0) break;
        hasher.update(buffer[0..n]);
    }
    hasher.final(gop.value_ptr);
    return gop.value_ptr.*;
}

/// The build-root relative path of a source LazyPath of this build; anything else fails.
fn srcPath(state: *State, compile: *Compile, path: LazyPath, what: []const u8) []const u8 {
    return switch (path) {
        .src_path => |src| if (src.owner == state.b)
            normalize(state.b, src.sub_path, what)
        else
            fatal(compile, "has {s} owned by another build: {s}", .{ what, src.sub_path }),
        .generated => fatal(compile, "has a generated {s}", .{what}),
        .cwd_relative => |cwd| fatal(compile, "has {s} outside the build root: {s}", .{ what, cwd }),
        .dependency => |dep| fatal(compile, "has {s} from a dependency: {s}", .{ what, dep.sub_path }),
    };
}

/// `path` with `/` separators and no `.`, `..` or empty components; it must stay in the build root.
fn normalize(b: *Build, path: []const u8, what: []const u8) []const u8 {
    if (std.fs.path.isAbsolute(path)) std.process.fatal("native input key: {s} is absolute: {s}", .{ what, path });
    var components: std.ArrayList([]const u8) = .empty;
    var it = std.mem.tokenizeAny(u8, path, "/\\");
    while (it.next()) |component| {
        if (std.mem.eql(u8, component, ".")) continue;
        if (std.mem.eql(u8, component, "..")) {
            if (components.pop() == null) std.process.fatal("native input key: {s} leaves the build root: {s}", .{ what, path });
            continue;
        }
        components.append(b.allocator, component) catch @panic("OOM");
    }
    return std.mem.join(b.allocator, "/", components.items) catch @panic("OOM");
}

fn widen(patterns: []const []const u8, root: []const u8) []const u8 {
    for (patterns) |pattern| {
        var pattern_components = std.mem.splitScalar(u8, pattern, '/');
        var root_components = std.mem.splitScalar(u8, root, '/');
        var len: usize = 0;
        const matched = while (pattern_components.next()) |want| {
            const have = root_components.next() orelse break false;
            if (!std.mem.eql(u8, want, "*") and !std.mem.eql(u8, want, have)) break false;
            len += @intFromBool(len != 0) + have.len;
        } else true;
        if (matched) return root[0..len];
    }
    return root;
}

/// True when `path` is `dir` or inside it (both build-root relative, compared without case).
fn isWithin(path: []const u8, dir: []const u8) bool {
    if (path.len < dir.len or !std.ascii.eqlIgnoreCase(path[0..dir.len], dir)) return false;
    return path.len == dir.len or path[dir.len] == '/';
}

/// The cache roots and the install prefix, when they are strictly inside the build root.
fn excludedDirs(b: *Build) []const []const u8 {
    const gpa = b.allocator;
    const build_root = b.build_root.handle.realpathAlloc(gpa, ".") catch |err|
        std.process.fatal("native input key: cannot resolve the build root: {s}", .{@errorName(err)});
    const cwd = std.process.getCwdAlloc(gpa) catch |err|
        std.process.fatal("native input key: cannot read the working directory: {s}", .{@errorName(err)});
    const candidates = [_][]const u8{
        b.cache_root.handle.realpathAlloc(gpa, ".") catch |err|
            std.process.fatal("native input key: cannot resolve the cache root: {s}", .{@errorName(err)}),
        b.graph.global_cache_root.handle.realpathAlloc(gpa, ".") catch |err|
            std.process.fatal("native input key: cannot resolve the global cache root: {s}", .{@errorName(err)}),
        std.fs.path.resolve(gpa, &.{ cwd, b.install_prefix }) catch @panic("OOM"),
    };
    var result: std.ArrayList([]const u8) = .empty;
    for (candidates) |candidate| {
        const rel = std.fs.path.relative(gpa, build_root, candidate) catch @panic("OOM");
        if (rel.len == 0 or std.fs.path.isAbsolute(rel) or std.mem.startsWith(u8, rel, "..")) continue;
        result.append(gpa, normalize(b, rel, "the cache or install directory")) catch @panic("OOM");
    }
    return result.items;
}

fn writeInventory(b: *Build, artifacts: []const Artifact, path: []const u8) void {
    var text: std.ArrayList(u8) = .empty;
    for (artifacts) |artifact| {
        const hex = std.fmt.bytesToHex(artifact.digest, .lower);
        text.appendSlice(b.allocator, b.fmt("artifact {s} {s} {s}\n", .{ artifact.compile.name, @tagName(artifact.compile.kind), &hex })) catch @panic("OOM");
        for (artifact.roots.keys()) |root| text.appendSlice(b.allocator, b.fmt("root {s}\n", .{root})) catch @panic("OOM");
        for (artifact.entries) |entry| text.appendSlice(b.allocator, b.fmt("input {s}\n", .{entry})) catch @panic("OOM");
    }
    b.build_root.handle.writeFile(.{ .sub_path = path, .data = text.items }) catch |err|
        std.process.fatal("native input key: cannot write {s}: {s}", .{ path, @errorName(err) });
}

fn lessThan(_: void, a: []const u8, b: []const u8) bool {
    return std.mem.lessThan(u8, a, b);
}

fn fatal(compile: *Compile, comptime format: []const u8, args: anytype) noreturn {
    std.process.fatal("native input key: {s} " ++ format ++ " (decision 394)", .{compile.name} ++ args);
}
