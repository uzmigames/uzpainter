#pragma once

// Generated compute kernels: HLSL compiled to DXIL and to SPIR-V through the vendored
// `uz::ShaderCompiler` (DXC) with IEEE-strict arithmetic (`-Gis`, UZP-MOD-008: no fast-math, no
// contraction), and a disk cache keyed by XXH64 over source, includes, defines, target and DXC
// version (docs/architecture/13-engine-integration.md §2.4, 04-layer-stack-and-compositing.md §7).
//
// The cache lives under the user's local app-data folder (`%LOCALAPPDATA%\UzPainter\
// kernel-cache`), never in the install folder. A `KernelCache` and its compiler belong to one
// thread (the engine thread); several processes may share the folder, entries are written
// atomically.

#include "render/backend.h"

#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace uz {
class ShaderCompiler;
}

namespace uzp::render {

/// A file the kernel may `#include "<name>"`. Kernels see only their declared includes, so the
/// cache key covers everything DXC reads.
struct KernelInclude {
    std::string name;  ///< Relative path, '/'-separated, no `..`.
    std::string text;
};

/// One compute kernel as generated: HLSL text, entry point, defines and includes. Compiled as
/// `cs_6_6`.
struct KernelSource {
    std::string name;  ///< Diagnostic name (error messages, debug names).
    std::string hlsl;
    std::string entryPoint = "main";
    std::vector<std::string> defines;  ///< `NAME` or `NAME=VALUE`, in order.
    std::vector<KernelInclude> includes;
};

/// The compiler the cache drives; `DxcKernelCompiler` in the product.
class IKernelCompiler {
public:
    virtual ~IKernelCompiler() = default;
    /// The compiler identity in the cache key (DXC version and `dxcompiler.dll` file version).
    [[nodiscard]] virtual std::string Version() const = 0;
    /// Compiles `source` for `target`; `includeDir` (possibly empty) holds its includes.
    virtual Result<std::vector<uint8_t>> Compile(const KernelSource& source, KernelTarget target,
                                                 const std::filesystem::path& includeDir) = 0;
};

/// DXC loaded from `dxcompiler.dll` through the vendored `uz::ShaderCompiler`.
class DxcKernelCompiler final : public IKernelCompiler {
public:
    /// Loads DXC; `kernel_compile_failed` when it cannot be loaded.
    static Result<std::unique_ptr<DxcKernelCompiler>> Load(const std::filesystem::path& dxcompiler);
    ~DxcKernelCompiler() override;

    std::string Version() const override { return m_version; }
    Result<std::vector<uint8_t>> Compile(const KernelSource& source, KernelTarget target,
                                         const std::filesystem::path& includeDir) override;

private:
    DxcKernelCompiler() = default;
    std::unique_ptr<uz::ShaderCompiler> m_compiler;
    std::string m_version;
};

/// The shader profile and code-generation flags every kernel is compiled with; part of the key.
inline constexpr std::string_view kKernelCompileFlags = "cs_6_6 -Gis";

/// XXH64 of the canonical encoding of everything that determines a kernel's bytecode: source,
/// entry point, defines (in order), includes (by name), target, compile flags and compiler
/// version.
[[nodiscard]] uint64_t KernelKey(const KernelSource& source, KernelTarget target,
                                 std::string_view compilerVersion);

/// `%LOCALAPPDATA%\UzPainter\kernel-cache`; empty when the folder cannot be resolved.
[[nodiscard]] std::filesystem::path DefaultKernelCacheRoot();

/// `dxcompiler.dll` beside the running executable.
[[nodiscard]] std::filesystem::path DefaultDxcompilerPath();

struct CompiledKernel {
    uint64_t key = 0;
    KernelTarget target = KernelTarget::Dxil;
    std::vector<uint8_t> bytecode;
    bool cacheHit = false;
};

class KernelCache {
public:
    struct Stats {
        uint64_t hits = 0;
        uint64_t misses = 0;
        /// Entries that could not be written (the kernel was still returned).
        uint64_t writeFailures = 0;
        /// Entries present but unreadable or inconsistent (recompiled and rewritten).
        uint64_t corruptEntries = 0;
    };

    KernelCache(IKernelCompiler& compiler, std::filesystem::path root);

    /// The kernel's bytecode for `target`: from the cache when its key is present, otherwise
    /// compiled and stored.
    Result<CompiledKernel> Get(const KernelSource& source, KernelTarget target);

    /// The cache file of a key.
    [[nodiscard]] std::filesystem::path EntryPath(uint64_t key, KernelTarget target) const;
    [[nodiscard]] const std::filesystem::path& Root() const { return m_root; }
    [[nodiscard]] const Stats& GetStats() const { return m_stats; }
    [[nodiscard]] std::string CompilerVersion() const { return m_compiler.Version(); }

private:
    Result<std::filesystem::path> MaterialiseIncludes(const KernelSource& source);

    IKernelCompiler& m_compiler;
    std::filesystem::path m_root;
    Stats m_stats;
};

}  // namespace uzp::render
