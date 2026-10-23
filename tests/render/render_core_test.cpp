// Native tests of the render layer's device, engine thread, kernel cache and capability query
// (src/render/, rulebook task phase1.1_core-device-kernels) and of its texture readback
// (phase1.2_core-readback). Built by `zig build render-tests` and driven by
// tests/render/test_core_device_kernels.py and tests/render/test_core_readback.py.
//
// Usage: uzp-render-tests <case> <work-dir>
//   xxhash          XXH64 against reference digests
//   admission       the admission budget derivation on synthetic capabilities
//   kernel-cache    HLSL to DXIL and SPIR-V (IEEE-strict); cache hits and misses per key part
//   dispatch        a cached DXIL kernel dispatched by the engine thread, read back exactly
//   deadline        a stalled GPU queue: the wait returns `timeout` within the deadline
//   device-removed  `ID3D12Device5::RemoveDevice`, then `device_removed {backend: dx12, ...}`
//   unavailable     Vulkan and a missing DX12 adapter: `gpu_backend_unavailable`, no work run
//   capabilities    the DX12 capability report and the derived admission budget
//   readback-layout  readback row pitch and texel layouts; the RHI's 16-bit unorm formats
//   readback-pitch   widths 1, 3, 1023 and 4097 texels read back with unshifted rows
//   readback-exact   every readable format (and a lower mip) read back bit-identical
//   readback-drain   64 readbacks in flight drained in submission order, no staging left
//   readback-failure device removal and a stalled queue under pending readbacks
//   readback-kernel  a kernel compiled through the cache, dispatched, then 64 readbacks drained
//                    (phase1.4_render-core-layer)
//   uv-raster-*      the UV-space raster pass (phase1.3_core-uv-raster, uv_raster_test.cpp)
//   vulkan-*         the Vulkan device qualification (phase3.1 slice, decision 310, vulkan_test.cpp)
//   image-*          the image passes (phase1.3_core-image-passes, image_passes_test.cpp)
//
// Output: `PASS <check>` / `FAIL <check>: <detail>` lines, `INFO` lines and, for
// `capabilities`, one `REPORT <json>` line. Exit code 0 when every check passed, 1 when one
// failed, 2 on a usage error, 77 when the case needs a DX12 hardware adapter and there is none.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "render/backend.h"
#include "render/capabilities.h"
#include "render/device.h"
#include "render/engine_thread.h"
#include "render/kernel_cache.h"
#include "render/texture_readback.h"
#include "render/xxhash64.h"

#include "image_passes_test.h"

#include "D3D12MemAlloc.h"
#include "dx12_device.h"
#include "dx12_guids.h"
#include "dx12_resource_creation.h"
#include "dx12_resources.h"
#include "log.h"

#include <windows.h>

#include <algorithm>
#include <atomic>
#include <bit>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <memory>
#include <mutex>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

namespace {

using namespace uzp::render;
using Microsoft::WRL::ComPtr;
namespace fs = std::filesystem;
using Ms = std::chrono::milliseconds;

constexpr int kExitSkip = 77;
int g_failures = 0;

void Check(bool ok, std::string_view name, const std::string& detail = {}) {
    if (ok) {
        std::printf("PASS %.*s\n", static_cast<int>(name.size()), name.data());
    } else {
        std::printf("FAIL %.*s: %s\n", static_cast<int>(name.size()), name.data(), detail.c_str());
        ++g_failures;
    }
    std::fflush(stdout);
}

void Info(const std::string& text) {
    std::printf("INFO %s\n", text.c_str());
    std::fflush(stdout);
}

int Finish() { return g_failures == 0 ? 0 : 1; }

std::string Describe(const std::optional<Error>& error) {
    return error ? error->Describe() : std::string("no error");
}

template <class T>
std::string Describe(const Result<T>& result) {
    return result ? std::string("success") : result.error().Describe();
}

std::string Hex64(uint64_t value) {
    char buf[24];
    std::snprintf(buf, sizeof(buf), "0x%016llx", static_cast<unsigned long long>(value));
    return buf;
}

/// Number of `OpDecorate <id> NoContraction` instructions in a SPIR-V module.
int NoContractionCount(const std::vector<uint8_t>& spirv) {
    std::vector<uint32_t> words(spirv.size() / 4);
    std::memcpy(words.data(), spirv.data(), words.size() * 4);
    int count = 0;
    for (size_t i = 5; i < words.size();) {
        const uint32_t length = words[i] >> 16;
        if (length == 0) break;
        if ((words[i] & 0xFFFF) == 71 && i + 2 < words.size() && words[i + 2] == 42) ++count;
        i += length;
    }
    return count;
}

// ── xxhash ───────────────────────────────────────────────────────────────────

int RunXxhash() {
    // Reference digests (python-xxhash 3.6.0, xxh64) of bytes (i * 31 + 7) & 0xFF, i = 0..n-1.
    struct Vector {
        size_t length;
        uint64_t seed0;
        uint64_t seedGolden;
    };
    constexpr uint64_t kGolden = 0x9E3779B97F4A7C15ull;
    constexpr Vector kVectors[] = {
        {0, 0xef46db3751d8e999ull, 0xc4349fc93c010000ull},
        {1, 0xa96c7f0ce858bbb7ull, 0x585882422a6165e7ull},
        {3, 0x56e6957632a487f9ull, 0x5acb303e78133c22ull},
        {4, 0xc60d15b1e3ff8f04ull, 0x7d51d5e2461732b3ull},
        {7, 0xafbefc3d6c6f9a8eull, 0x2ce9adec2b2c8104ull},
        {8, 0x3da5c7aa269683e0ull, 0x758848f033fa76a2ull},
        {9, 0x4b17a9ba9e215c09ull, 0xd4576cf554b7d929ull},
        {15, 0xae2a37eb9357caa7ull, 0xa18d5c90d722cee3ull},
        {31, 0x4a74f3a1a39ad4a1ull, 0x8137041f5af88413ull},
        {32, 0x8d57d6a4671cc43dull, 0x184ebcf3745cd46cull},
        {33, 0x62c9fd21ed857664ull, 0x52fac3c981f3cc2eull},
        {63, 0x5c320a0d2707057full, 0x64ef99a2e94cc7bdull},
        {64, 0x7bbabbc45729d17eull, 0xf7f22435fe1ab128ull},
        {100, 0xefa0ad2d3e70c151ull, 0xbc7ab33be7528c18ull},
        {1000, 0x99594f4828043d35ull, 0xda717f741f399f3full},
    };
    std::vector<std::byte> data(1000);
    for (size_t i = 0; i < data.size(); ++i) data[i] = static_cast<std::byte>((i * 31 + 7) & 0xFF);
    bool all = true;
    for (const Vector& v : kVectors) {
        const std::span<const std::byte> part(data.data(), v.length);
        const uint64_t h0 = Xxh64(part, 0);
        const uint64_t hg = Xxh64(part, kGolden);
        if (h0 != v.seed0 || hg != v.seedGolden) {
            all = false;
            Check(false, "xxh64 of " + std::to_string(v.length) + " bytes",
                  "got " + Hex64(h0) + "/" + Hex64(hg));
        }
    }
    Check(all, "xxh64 matches the reference digests (0..1000 bytes, two seeds)");
    const std::string_view text = "Nobody inspects the spammish repetition";
    const uint64_t h = Xxh64(std::as_bytes(std::span<const char>(text.data(), text.size())));
    Check(h == 0xfbcea83c8a378bf1ull, "xxh64 of the python-xxhash example", Hex64(h));
    return Finish();
}

// ── kernel-cache ─────────────────────────────────────────────────────────────

constexpr const char* kCommonInclude = R"(
float Ramp(uint x, uint y, float s, float t) {
    float a = float(x) * s;
    float b = float(y) * t;
    return a + b;
}
)";

/// The kernel of the cache and dispatch cases: an R32Float ramp a*x + b*y + revision.
constexpr const char* kRampKernel = R"(
#include "ramp/common.hlsl"
cbuffer Params : register(b0) {
    uint g_width;
    uint g_height;
    float g_s;
    float g_t;
    float g_revision;
};
RWTexture2D<float> g_output : register(u0);

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_width || id.y >= g_height) return;
    g_output[id.xy] = Ramp(id.x, id.y, g_s, g_t) + g_revision * RAMP_REVISION_SCALE;
}
)";

KernelSource RampSource() {
    KernelSource source;
    source.name = "test_ramp";
    source.hlsl = kRampKernel;
    source.defines = {"RAMP_REVISION_SCALE=1.0"};
    source.includes = {{"ramp/common.hlsl", kCommonInclude}};
    return source;
}

/// Counts the compilations the cache asks for; can report another compiler version.
class CountingCompiler final : public IKernelCompiler {
public:
    CountingCompiler(IKernelCompiler& inner, std::string version)
        : m_inner(inner), m_version(std::move(version)) {}
    std::string Version() const override {
        return m_version.empty() ? m_inner.Version() : m_version;
    }
    Result<std::vector<uint8_t>> Compile(const KernelSource& source, KernelTarget target,
                                         const fs::path& includeDir) override {
        ++compiles;
        return m_inner.Compile(source, target, includeDir);
    }
    int compiles = 0;

private:
    IKernelCompiler& m_inner;
    std::string m_version;
};

int RunKernelCache(const fs::path& dir) {
    Result<std::unique_ptr<DxcKernelCompiler>> dxc = DxcKernelCompiler::Load(DefaultDxcompilerPath());
    Check(dxc.has_value(), "DXC loads from beside the executable", Describe(dxc));
    if (!dxc) return Finish();
    Info("compiler " + (*dxc)->Version());

    const fs::path root = dir / "kernel-cache";
    std::error_code ec;
    fs::remove_all(root, ec);
    CountingCompiler counting(**dxc, {});
    KernelCache cache(counting, root);
    const KernelSource base = RampSource();

    // 3.1: one source, both targets.
    Result<CompiledKernel> dxil = cache.Get(base, KernelTarget::Dxil);
    Check(dxil && dxil->bytecode.size() > 4 && std::memcmp(dxil->bytecode.data(), "DXBC", 4) == 0,
          "the kernel compiles to a DXIL container", Describe(dxil));
    Result<CompiledKernel> spirv = cache.Get(base, KernelTarget::Spirv);
    uint32_t magic = 0;
    if (spirv && spirv->bytecode.size() >= 4) std::memcpy(&magic, spirv->bytecode.data(), 4);
    Check(spirv && magic == 0x07230203u, "the same kernel compiles to a SPIR-V module",
          Describe(spirv));
    if (!dxil || !spirv) return Finish();
    Check(NoContractionCount(spirv->bytecode) >= 3,
          "SPIR-V arithmetic is IEEE-strict (NoContraction decorations)",
          std::to_string(NoContractionCount(spirv->bytecode)) + " decorations");
    Check(!dxil->cacheHit && !spirv->cacheHit && counting.compiles == 2,
          "first requests miss and compile", std::to_string(counting.compiles) + " compiles");
    Check(dxil->key != spirv->key, "the target is part of the key");

    // 3.2: identical keys hit, in this cache and in a new one over the same folder.
    Result<CompiledKernel> again = cache.Get(base, KernelTarget::Dxil);
    Check(again && again->cacheHit && counting.compiles == 2 && again->bytecode == dxil->bytecode,
          "an identical key hits without compiling", Describe(again));
    CountingCompiler counting2(**dxc, {});
    KernelCache reopened(counting2, root);
    Result<CompiledKernel> fromDisk = reopened.Get(base, KernelTarget::Dxil);
    Check(fromDisk && fromDisk->cacheHit && counting2.compiles == 0 &&
              fromDisk->bytecode == dxil->bytecode,
          "an identical key hits from disk in a new cache", Describe(fromDisk));
    Check(fs::is_regular_file(cache.EntryPath(dxil->key, KernelTarget::Dxil)),
          "the entry is a file under the cache folder");

    std::set<uint64_t> keys = {dxil->key, spirv->key};
    const auto expectMiss = [&](KernelCache& c, CountingCompiler& counter, const KernelSource& s,
                                KernelTarget target, const std::string& what) {
        const int before = counter.compiles;
        Result<CompiledKernel> miss = c.Get(s, target);
        Check(miss && !miss->cacheHit && counter.compiles == before + 1,
              "a changed " + what + " misses and recompiles", Describe(miss));
        Result<CompiledKernel> hit = c.Get(s, target);
        Check(hit && hit->cacheHit && counter.compiles == before + 1,
              "the changed " + what + " then hits", Describe(hit));
        if (miss) keys.insert(miss->key);
    };
    KernelSource changed = base;
    changed.hlsl += "\n// changed\n";
    expectMiss(cache, counting, changed, KernelTarget::Dxil, "source");
    changed = base;
    changed.includes[0].text += "\n// changed\n";
    expectMiss(cache, counting, changed, KernelTarget::Dxil, "include");
    changed = base;
    changed.defines = {"RAMP_REVISION_SCALE=2.0"};
    expectMiss(cache, counting, changed, KernelTarget::Dxil, "define");
    changed = base;
    changed.defines = {"RAMP_REVISION_SCALE=1.0", "UNUSED=1"};
    expectMiss(cache, counting, changed, KernelTarget::Dxil, "define list");
    {
        // The target: a fresh cache folder, so the earlier SPIR-V entry cannot hit.
        CountingCompiler fresh(**dxc, {});
        KernelCache other(fresh, dir / "kernel-cache-target");
        fs::remove_all(other.Root(), ec);
        Result<CompiledKernel> d = other.Get(base, KernelTarget::Dxil);
        expectMiss(other, fresh, base, KernelTarget::Spirv, "target");
        Check(d && d->key == dxil->key, "the key does not depend on the cache folder");
    }
    CountingCompiler newer(**dxc, "dxc 1.9, dxcompiler.dll 1.9.9999.0");
    KernelCache newerCache(newer, root);
    expectMiss(newerCache, newer, base, KernelTarget::Dxil, "DXC version");
    // DXIL, SPIR-V, then source, include, define, define list and DXC version (the target case
    // repeats the SPIR-V key).
    Check(keys.size() == 7, "every changed key part gives a distinct key",
          std::to_string(keys.size()) + " distinct keys");

    // Include order is not part of the key; define order is.
    KernelSource twoIncludes = base;
    twoIncludes.includes.push_back({"ramp/unused.hlsl", "// unused\n"});
    KernelSource swapped = twoIncludes;
    std::swap(swapped.includes[0], swapped.includes[1]);
    Check(KernelKey(twoIncludes, KernelTarget::Dxil, "v") ==
              KernelKey(swapped, KernelTarget::Dxil, "v"),
          "include declaration order does not change the key");
    KernelSource defineOrder = base;
    defineOrder.defines = {"A=1", "B=2"};
    KernelSource defineOrder2 = base;
    defineOrder2.defines = {"B=2", "A=1"};
    Check(KernelKey(defineOrder, KernelTarget::Dxil, "v") !=
              KernelKey(defineOrder2, KernelTarget::Dxil, "v"),
          "define order changes the key");

    // A damaged entry is recompiled and rewritten, never returned.
    const fs::path entry = cache.EntryPath(dxil->key, KernelTarget::Dxil);
    {
        std::fstream file(entry, std::ios::in | std::ios::out | std::ios::binary);
        file.seekp(-1, std::ios::end);
        file.put('\x5A');
    }
    const int beforeCorrupt = counting.compiles;
    Result<CompiledKernel> repaired = cache.Get(base, KernelTarget::Dxil);
    Check(repaired && !repaired->cacheHit && repaired->bytecode == dxil->bytecode &&
              counting.compiles == beforeCorrupt + 1 && cache.GetStats().corruptEntries == 1,
          "a damaged entry is recompiled", Describe(repaired));
    Result<CompiledKernel> rehit = cache.Get(base, KernelTarget::Dxil);
    Check(rehit && rehit->cacheHit, "the rewritten entry hits");

    // Kernels see only their declared includes.
    KernelSource undeclared = base;
    undeclared.includes.clear();
    Result<CompiledKernel> missing = cache.Get(undeclared, KernelTarget::Dxil);
    Check(!missing && missing.error().code == ErrorCode::KernelCompileFailed,
          "an undeclared include fails to compile", Describe(missing));
    KernelSource escaping = base;
    escaping.includes = {{"../outside.hlsl", "// no"}};
    Result<CompiledKernel> escaped = cache.Get(escaping, KernelTarget::Dxil);
    Check(!escaped && escaped.error().code == ErrorCode::KernelCompileFailed,
          "an include name outside the include folder is rejected", Describe(escaped));
    KernelSource broken = base;
    broken.hlsl += "\nthis is not HLSL\n";
    Result<CompiledKernel> rejected = cache.Get(broken, KernelTarget::Dxil);
    Check(!rejected && rejected.error().code == ErrorCode::KernelCompileFailed &&
              rejected.error().reason.find("test_ramp") != std::string::npos,
          "a DXC error is reported as kernel_compile_failed", Describe(rejected));

    // Includes and atomic-write temporary names must work beyond legacy Win32 MAX_PATH.
    // This process has the same manifest/CRT as the export harness; Python's IO alone would
    // not reproduce the failure because python.exe is long-path aware.
    const fs::path deepRoot = dir / std::string(90, 'a') / std::string(90, 'b') / std::string(90, 'c');
    CountingCompiler deepCompiler(**dxc, {});
    KernelCache deepCache(deepCompiler, deepRoot);
    for (const KernelTarget target : {KernelTarget::Dxil, KernelTarget::Spirv}) {
        const auto compiled = deepCache.Get(base, target);
        Check(compiled.has_value(), "declared includes compile under a cache path longer than MAX_PATH", Describe(compiled));
        if (!compiled) continue;
        KernelCache reopened(deepCompiler, deepRoot);
        const int before = deepCompiler.compiles;
        const auto hit = reopened.Get(base, target);
        Check(hit && hit->cacheHit && hit->bytecode == compiled->bytecode && deepCompiler.compiles == before,
              "a deep cache entry is persisted and reused by a fresh cache", Describe(hit));
    }

    // The default folder is under the user's local app-data folder.
    const fs::path defaultRoot = DefaultKernelCacheRoot();
    wchar_t localAppData[MAX_PATH] = {};
    GetEnvironmentVariableW(L"LOCALAPPDATA", localAppData, MAX_PATH);
    Check(!defaultRoot.empty() && defaultRoot == fs::path(localAppData) / "UzPainter" / "kernel-cache",
          "the default cache folder is %LOCALAPPDATA%\\UzPainter\\kernel-cache",
          defaultRoot.string());
    Info("default kernel cache " + defaultRoot.string());
    return Finish();
}

// ── GPU helpers ──────────────────────────────────────────────────────────────

struct TestSnapshot {
    uint64_t revision = 0;
    float s = 0.0f;
    float t = 0.0f;
};

constexpr uint32_t kWidth = 100;
constexpr uint32_t kHeight = 64;

/// The ramp the kernel writes, with the rounding of IEEE-strict arithmetic: each product and
/// each sum rounded to float on its own (separate statements, so the host compiler cannot fuse
/// them either).
float ExpectedRamp(uint32_t x, uint32_t y, const TestSnapshot& snapshot) {
    const float a = static_cast<float>(x) * snapshot.s;
    const float b = static_cast<float>(y) * snapshot.t;
    const float ramp = a + b;
    const float revision = static_cast<float>(snapshot.revision) * 1.0f;
    const float value = ramp + revision;
    return value;
}

/// Writes the ramp with the cached kernel and reads it back; destroys what it created.
Result<std::vector<float>> DispatchRamp(EngineContext& context, const TestSnapshot& snapshot) {
    IDevice& device = context.Device();
    Result<ComputeKernel> kernel = context.Kernel(RampSource());
    if (!kernel) return Unexpected(kernel.error());

    uz::RHITextureDesc textureDesc;
    textureDesc.width = kWidth;
    textureDesc.height = kHeight;
    textureDesc.format = uz::RHIFormat::R32Float;
    textureDesc.usage = uz::RHITextureUsage::UnorderedAccess | uz::RHITextureUsage::CopySrc;
    textureDesc.debugName = "test_ramp";
    Result<uz::RHITextureHandle> texture = device.CreateTexture(textureDesc);
    if (!texture) return Unexpected(texture.error());

    const uint32_t rowBytes = kWidth * sizeof(float);
    const uint32_t rowPitch = (rowBytes + 255) / 256 * 256;
    uz::RHIBufferDesc bufferDesc;
    bufferDesc.sizeBytes = static_cast<uint64_t>(rowPitch) * kHeight;
    bufferDesc.usage = uz::RHIBufferUsage::CopyDst;
    bufferDesc.memory = uz::RHIMemoryType::Readback;
    bufferDesc.debugName = "test_ramp_readback";
    Result<uz::RHIBufferHandle> readback = device.CreateBuffer(bufferDesc);
    if (!readback) {
        device.DestroyTexture(*texture);
        return Unexpected(readback.error());
    }

    const uint32_t uav = device.Rhi().GetTextureUAVIndex(*texture);
    uint32_t constants[5] = {kWidth, kHeight, std::bit_cast<uint32_t>(snapshot.s),
                             std::bit_cast<uint32_t>(snapshot.t),
                             std::bit_cast<uint32_t>(static_cast<float>(snapshot.revision))};
    const uz::RHIPipelineHandle pipeline = kernel->pipeline;
    const uz::RHITextureHandle target = *texture;
    const uz::RHIBufferHandle staging = *readback;
    Result<void> done = context.SubmitAndWait([&](uz::IRHICommandList& cmd) {
        uz::RHIBarrierDesc toUav{target, uz::RHIBufferHandle::Invalid(),
                                 uz::RHIResourceState::Common,
                                 uz::RHIResourceState::UnorderedAccess};
        cmd.ResourceBarrier(&toUav, 1);
        cmd.SetPipeline(pipeline);
        cmd.SetRootConstants(kRootConstantsParam, constants, 5);
        cmd.SetDescriptorTable(kUavTableParam, uav);
        cmd.Dispatch((kWidth + 7) / 8, (kHeight + 7) / 8, 1);
        uz::RHIBarrierDesc toCopy{target, uz::RHIBufferHandle::Invalid(),
                                  uz::RHIResourceState::UnorderedAccess,
                                  uz::RHIResourceState::CopySrc};
        cmd.ResourceBarrier(&toCopy, 1);
        cmd.CopyTextureToBuffer(target, 0, staging, 0, rowPitch);
    });
    std::vector<float> values;
    if (done) {
        const auto* mapped = static_cast<const unsigned char*>(device.Rhi().MapBuffer(staging));
        if (mapped) {
            values.resize(static_cast<size_t>(kWidth) * kHeight);
            for (uint32_t y = 0; y < kHeight; ++y) {
                std::memcpy(&values[static_cast<size_t>(y) * kWidth],
                            mapped + static_cast<size_t>(y) * rowPitch, rowBytes);
            }
            device.Rhi().UnmapBuffer(staging);
        }
    }
    device.DestroyBuffer(staging);
    device.DestroyTexture(target);
    if (!done) return Unexpected(done.error());
    if (values.empty()) {
        return Fail(ErrorCode::RequestFailed, device.GetBackend(), "readback buffer not mapped");
    }
    return values;
}

size_t Mismatches(const std::vector<float>& values, const TestSnapshot& snapshot,
                  std::string& first) {
    size_t mismatches = 0;
    for (uint32_t y = 0; y < kHeight; ++y) {
        for (uint32_t x = 0; x < kWidth; ++x) {
            const float got = values[static_cast<size_t>(y) * kWidth + x];
            const float want = ExpectedRamp(x, y, snapshot);
            if (std::bit_cast<uint32_t>(got) == std::bit_cast<uint32_t>(want)) continue;
            if (mismatches++ == 0) {
                char buf[128];
                std::snprintf(buf, sizeof(buf), "first at (%u, %u): got %08X, expected %08X", x, y,
                              std::bit_cast<uint32_t>(got), std::bit_cast<uint32_t>(want));
                first = buf;
            }
        }
    }
    return mismatches;
}

EngineOptions TestOptions(const fs::path& dir) {
    EngineOptions options;
    options.kernelCacheRoot = dir / "kernel-cache";
    return options;
}

/// Exit code 77 when the engine has no DX12 device (no hardware adapter on this machine).
bool NoAdapter(const Engine& engine) {
    if (!engine.DeviceError()) return false;
    std::printf("SKIP no DX12 device: %s\n", engine.DeviceError()->Describe().c_str());
    return true;
}

template <class T>
Result<T> Get(std::future<Result<T>>& future) {
    if (future.wait_for(std::chrono::seconds(120)) != std::future_status::ready) {
        return Fail(ErrorCode::RequestFailed, std::nullopt, "no result within 120 s");
    }
    return future.get();
}

// ── dispatch ─────────────────────────────────────────────────────────────────

int RunDispatch(const fs::path& dir) {
    Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    Info("adapter " + engine.Capabilities().value_or(CapabilityReport{}).adapter);

    const std::thread::id caller = std::this_thread::get_id();
    std::atomic<bool> onEngineThread{false};
    auto snapshot = std::make_shared<const TestSnapshot>(TestSnapshot{7, 0.1f, 0.7f});
    auto future = engine.Submit(
        snapshot, [&](EngineContext& context, const TestSnapshot& s) -> Result<std::vector<float>> {
            onEngineThread = std::this_thread::get_id() == engine.ThreadId() &&
                             std::this_thread::get_id() != caller;
            return DispatchRamp(context, s);
        });
    Result<std::vector<float>> values = Get(future);
    Check(onEngineThread, "the request ran on the engine thread, not the caller's");
    Check(values.has_value(), "the DXIL kernel dispatches and reads back", Describe(values));
    if (!values) return Finish();
    std::string first;
    const size_t mismatches = Mismatches(*values, *snapshot, first);
    Check(mismatches == 0, "written values equal the expected IEEE-strict values bit for bit",
          std::to_string(mismatches) + " mismatches; " + first);

    // A second revision through the same queue: the kernel is reused, the data follows the
    // snapshot.
    auto snapshot2 = std::make_shared<const TestSnapshot>(TestSnapshot{8, 0.3f, 0.11f});
    auto future2 = engine.Submit(snapshot2, [](EngineContext& context, const TestSnapshot& s) {
        return DispatchRamp(context, s);
    });
    Result<std::vector<float>> values2 = Get(future2);
    first.clear();
    Check(values2 && Mismatches(*values2, *snapshot2, first) == 0,
          "a later revision's snapshot is evaluated exactly", Describe(values2) + " " + first);

    // The same source compiles to SPIR-V through a cache over the same folder.
    Result<std::unique_ptr<DxcKernelCompiler>> dxc = DxcKernelCompiler::Load(DefaultDxcompilerPath());
    if (dxc) {
        KernelCache cache(**dxc, dir / "kernel-cache");
        Result<CompiledKernel> dxil = cache.Get(RampSource(), KernelTarget::Dxil);
        Result<CompiledKernel> spirv = cache.Get(RampSource(), KernelTarget::Spirv);
        Check(dxil && dxil->cacheHit, "the dispatched DXIL kernel is in the cache folder",
              Describe(dxil));
        Check(spirv && spirv->bytecode.size() > 4, "the same source compiles to SPIR-V",
              Describe(spirv));
    }
    return Finish();
}

// ── deadline ─────────────────────────────────────────────────────────────────

int RunDeadline(const fs::path& dir) {
    constexpr Ms kDeadline{300};
    EngineOptions options = TestOptions(dir);
    options.requestDeadline = kDeadline;
    Engine engine(options);
    if (NoAdapter(engine)) return kExitSkip;

    Ms waited{0};
    bool released = false;
    auto snapshot = std::make_shared<const TestSnapshot>();
    auto stalled = engine.Submit(snapshot, [&](EngineContext& context, const TestSnapshot&)
                                               -> Result<void> {
        auto& device = static_cast<Dx12Device&>(context.Device());
        // The direct queue waits on a fence nothing has signalled, so the next submission
        // cannot complete: a stalled GPU queue.
        ComPtr<ID3D12Fence> blocker;
        if (FAILED(device.D3D12()->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&blocker)))) {
            return Fail(ErrorCode::ResourceCreationFailed, Backend::Dx12, "blocker fence");
        }
        device.Native().GetDirectQueue()->Wait(blocker.Get(), 1);
        const auto start = Clock::now();
        Result<void> result = context.SubmitAndWait([](uz::IRHICommandList&) {});
        waited = std::chrono::duration_cast<Ms>(Clock::now() - start);
        // Release the queue so the device can be torn down normally at the end.
        released = SUCCEEDED(blocker->Signal(1));
        return result;
    });
    Result<void> result = Get(stalled);
    Info("wait returned after " + std::to_string(waited.count()) + " ms (deadline " +
         std::to_string(kDeadline.count()) + " ms)");
    Check(!result && result.error().code == ErrorCode::Timeout &&
              result.error().backend == Backend::Dx12,
          "the stalled wait returns timeout", Describe(result));
    Check(waited >= kDeadline - Ms(20) && waited <= kDeadline + Ms(2000),
          "the wait ends at the deadline, not later",
          std::to_string(waited.count()) + " ms");
    Check(released, "the test released the stalled queue");

    bool ran = false;
    auto after = engine.Submit(snapshot, [&](EngineContext&, const TestSnapshot&) -> Result<void> {
        ran = true;
        return {};
    });
    Result<void> later = Get(after);
    Check(!later && later.error().code == ErrorCode::Timeout && !ran,
          "later requests fail with the timeout without running", Describe(later));
    const auto stopStart = Clock::now();
    engine.Stop();
    Info("engine stopped after " +
         std::to_string(std::chrono::duration_cast<Ms>(Clock::now() - stopStart).count()) + " ms");
    return Finish();
}

// ── device-removed ───────────────────────────────────────────────────────────

int RunDeviceRemoved(const fs::path& dir) {
    Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    auto snapshot = std::make_shared<const TestSnapshot>(TestSnapshot{1, 0.25f, 0.5f});

    auto first = engine.Submit(snapshot, [](EngineContext& context, const TestSnapshot& s) {
        return DispatchRamp(context, s);
    });
    Result<std::vector<float>> before = Get(first);
    Check(before.has_value(), "a request succeeds before the removal", Describe(before));

    auto inject = engine.Submit(snapshot, [](EngineContext& context, const TestSnapshot&)
                                              -> Result<void> {
        auto& device = static_cast<Dx12Device&>(context.Device());
        ComPtr<ID3D12Device5> device5;
        if (FAILED(device.D3D12()->QueryInterface(IID_PPV_ARGS(&device5)))) {
            return Fail(ErrorCode::RequestFailed, Backend::Dx12, "no ID3D12Device5");
        }
        device5->RemoveDevice();
        return {};
    });
    Result<void> injected = Get(inject);
    Check(injected.has_value(), "ID3D12Device5::RemoveDevice was called", Describe(injected));

    bool ran = false;
    auto next = engine.Submit(snapshot, [&](EngineContext& context, const TestSnapshot& s) {
        ran = true;
        return DispatchRamp(context, s);
    });
    Result<std::vector<float>> after = Get(next);
    Info(Describe(after));
    Check(!after && after.error().code == ErrorCode::DeviceRemoved &&
              after.error().backend == Backend::Dx12 && !after.error().reason.empty(),
          "the next request fails with device_removed {backend: dx12, reason}", Describe(after));
    Check(!after && after.error().Describe().starts_with("device_removed {backend: dx12, reason: "),
          "the error is reported as device_removed {backend: dx12, reason: ...}",
          Describe(after));
    Check(!ran, "the request's work did not run on the removed device");
    engine.Stop();
    return Finish();
}

// ── unavailable ──────────────────────────────────────────────────────────────

bool Loaded(const wchar_t* module) { return GetModuleHandleW(module) != nullptr; }

// Two cases, neither a stand-in for the other: a DX12 adapter index that does not exist (the
// deterministic unavailable-device fixture) and a Vulkan request, which the product path refuses
// by design (decision 310) without loading the Vulkan loader. The qualified Vulkan device and its
// refusal of an unqualified device are the `vulkan-*` cases (vulkan_test.cpp).
int RunUnavailable(const fs::path& dir) {
    Check(!Loaded(L"D3D12Core.dll") && !Loaded(L"vulkan-1.dll"),
          "no GPU runtime is loaded before the test");
    struct Case {
        const char* name;
        DeviceOptions device;
        Backend backend;
        const char* reasonPart;
    };
    DeviceOptions vulkan;
    vulkan.backend = Backend::Vulkan;
    DeviceOptions missingAdapter;
    missingAdapter.backend = Backend::Dx12;
    missingAdapter.adapterIndex = 64;
    const Case cases[] = {
        {"vulkan", vulkan, Backend::Vulkan, "DX12 is not used"},
        {"dx12 adapter 64", missingAdapter, Backend::Dx12, "no DXGI adapter at index 64"},
    };
    for (const Case& c : cases) {
        EngineOptions options = TestOptions(dir);
        options.device = c.device;
        Engine engine(options);
        const std::string name = c.name;
        const std::optional<Error>& error = engine.DeviceError();
        Check(error && error->code == ErrorCode::GpuBackendUnavailable && error->backend == c.backend &&
                  error->reason.find(c.reasonPart) != std::string::npos,
              name + ": the engine reports gpu_backend_unavailable for the requested backend",
              Describe(error));
        bool ran = false;
        auto snapshot = std::make_shared<const TestSnapshot>();
        auto future = engine.Submit(snapshot, [&](EngineContext&, const TestSnapshot&) -> Result<void> {
            ran = true;
            return {};
        });
        Result<void> result = Get(future);
        Check(!result && result.error().code == ErrorCode::GpuBackendUnavailable &&
                  result.error().backend == c.backend && !ran,
              name + ": a request fails with gpu_backend_unavailable before its work runs",
              Describe(result));
        Result<CapabilityReport> capabilities = engine.Capabilities();
        Check(!capabilities && capabilities.error().code == ErrorCode::GpuBackendUnavailable,
              name + ": no capability report", Describe(capabilities));
        Info(name + ": " + Describe(error));
    }
    // Neither request created a device of any backend.
    Check(!Loaded(L"D3D12Core.dll"), "no DX12 device was created (D3D12Core.dll not loaded)");
    Check(!Loaded(L"vulkan-1.dll"), "no Vulkan device was created (vulkan-1.dll not loaded)");
    return Finish();
}

// ── capabilities ─────────────────────────────────────────────────────────────

int RunCapabilities(const fs::path& dir) {
    Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    Result<CapabilityReport> report = engine.Capabilities();
    Check(report.has_value(), "the capability query runs at startup", Describe(report));
    if (!report) return Finish();
    std::printf("REPORT %s\n", report->ToJson().c_str());
    Check(report->backend == Backend::Dx12 && !report->adapter.empty(),
          "the report names the DX12 adapter", report->adapter);
    Check(!report->softwareAdapter, "the adapter is a hardware adapter");
    Check(report->formats.size() == 31, "every RHI format is reported",
          std::to_string(report->formats.size()));
    const FormatCapability* rgba16 = report->Find(uz::RHIFormat::RGBA16Float);
    Check(rgba16 && rgba16->texture2D && rgba16->shaderResource && rgba16->unorderedAccess,
          "RGBA16Float supports copy, shader_resource and unordered_access");
    const FormatCapability* depth = report->Find(uz::RHIFormat::D32Float);
    Check(depth && depth->depthStencil && !depth->unorderedAccess,
          "D32Float is a depth format without UAV");
    Check(report->vram.budgetBytes > 0 && report->vram.budgetBytes >= report->vram.usageBytes,
          "the VRAM budget is reported", std::to_string(report->vram.budgetBytes));
    Check(report->descriptors.shaderResources > 0 && report->descriptors.samplers > 0,
          "descriptor capacities are reported");
    const AdmissionBudget derived =
        DeriveAdmissionBudget(report->vram, report->descriptors, report->policy);
    Check(report->admission.bytes == derived.bytes && report->admission.bytes > 0 &&
              report->admission.maxTilesByDescriptors == derived.maxTilesByDescriptors,
          "the admission budget is derived from the reported budget",
          std::to_string(report->admission.bytes));
    // A 256x256 RGBA16Float tile.
    const uint64_t tileBytes = 256ull * 256 * 8;
    Info("admission: " + std::to_string(report->admission.bytes >> 20) + " MiB, " +
         std::to_string(report->admission.MaxLiveTiles(tileBytes)) +
         " live 256x256 RGBA16Float tiles; ray query " + (report->rayQuery ? "yes" : "no"));
    Check(report->admission.MaxLiveTiles(tileBytes) > 0, "at least one tile is admitted");
    return Finish();
}

// ── admission ────────────────────────────────────────────────────────────────

int RunAdmission() {
    constexpr uint64_t kMiB = 1ull << 20;
    VramReport vram;
    vram.budgetBytes = 22000 * kMiB;
    vram.usageBytes = 1000 * kMiB;
    DescriptorCapacities descriptors;
    descriptors.shaderResources = 1'000'000;
    const AdmissionPolicy policy;  // 50 %, 512 MiB reserve, 4096 descriptors, 2 per tile
    const AdmissionBudget budget = DeriveAdmissionBudget(vram, descriptors, policy);
    Check(budget.bytes == (22000 - 1000 - 512) * kMiB / 2,
          "admission = (budget - usage - reserve) x 50 %", std::to_string(budget.bytes));
    Check(budget.maxTilesByDescriptors == (1'000'000 - 4096) / 2,
          "descriptor bound = (capacity - reserved) / descriptors per tile",
          std::to_string(budget.maxTilesByDescriptors));
    const uint64_t tile = 256ull * 256 * 8;
    Check(budget.MaxLiveTiles(tile) == budget.bytes / tile, "live tiles bounded by bytes");
    Check(budget.MaxLiveTiles(1) == budget.maxTilesByDescriptors,
          "live tiles bounded by descriptors");
    Check(budget.MaxLiveTiles(0) == 0, "zero-byte tiles admit nothing");
    vram.usageBytes = vram.budgetBytes + kMiB;
    Check(DeriveAdmissionBudget(vram, descriptors, policy).bytes == 0,
          "usage above the budget admits nothing");
    vram.usageBytes = vram.budgetBytes - 100 * kMiB;
    Check(DeriveAdmissionBudget(vram, descriptors, policy).bytes == 0,
          "free memory below the reserve admits nothing");
    return Finish();
}

// ── readback helpers ─────────────────────────────────────────────────────────

/// Every format `ReadbackLayout` accepts.
constexpr uz::RHIFormat kReadableFormats[] = {
    uz::RHIFormat::R8Unorm,     uz::RHIFormat::RG8Unorm,    uz::RHIFormat::RGBA8Unorm,
    uz::RHIFormat::RGBA8Srgb,   uz::RHIFormat::BGRA8Unorm,  uz::RHIFormat::BGRA8Srgb,
    uz::RHIFormat::R16Unorm,    uz::RHIFormat::RG16Unorm,   uz::RHIFormat::RGBA16Unorm,
    uz::RHIFormat::R16Float,    uz::RHIFormat::RG16Float,   uz::RHIFormat::RGBA16Float,
    uz::RHIFormat::R32Float,    uz::RHIFormat::RG32Float,   uz::RHIFormat::RGB32Float,
    uz::RHIFormat::RGBA32Float, uz::RHIFormat::R32Uint,     uz::RHIFormat::RG32Uint,
    uz::RHIFormat::RGBA32Uint,
};

std::string Name(uz::RHIFormat format) { return std::string(FormatName(format)); }

/// Deterministic bytes (xorshift64*): every bit pattern of a channel, NaNs and denormals of the
/// float formats included, occurs.
std::vector<std::byte> PatternBytes(size_t count, uint64_t seed) {
    std::vector<std::byte> bytes(count);
    uint64_t state = seed * 0x9E3779B97F4A7C15ull + 1;
    for (std::byte& b : bytes) {
        state ^= state >> 12;
        state ^= state << 25;
        state ^= state >> 27;
        b = static_cast<std::byte>((state * 0x2545F4914F6CDD1Dull) >> 56);
    }
    return bytes;
}

/// The first `channels` channels of every texel of tightly packed `texels`.
std::vector<std::byte> FirstChannels(const std::vector<std::byte>& texels, TexelLayout layout,
                                     uint32_t channels) {
    const size_t in = layout.BytesPerTexel();
    const size_t out = size_t{channels} * layout.bytesPerChannel;
    std::vector<std::byte> result;
    result.reserve(texels.size() / in * out);
    for (size_t offset = 0; offset < texels.size(); offset += in) {
        result.insert(result.end(), texels.begin() + static_cast<ptrdiff_t>(offset),
                      texels.begin() + static_cast<ptrdiff_t>(offset + out));
    }
    return result;
}

/// Empty when `image` holds exactly `expected` with `width` x `height` texels; else the first
/// difference.
std::string Compare(const Result<ReadbackImage>& image, const std::vector<std::byte>& expected,
                    uint32_t width, uint32_t height) {
    if (!image) return image.error().Describe();
    if (image->width != width || image->height != height) {
        return "size " + std::to_string(image->width) + "x" + std::to_string(image->height);
    }
    if (image->texels.size() != expected.size()) {
        return std::to_string(image->texels.size()) + " bytes, expected " +
               std::to_string(expected.size());
    }
    const size_t row = image->RowBytes();
    for (size_t i = 0; i < expected.size(); ++i) {
        if (image->texels[i] == expected[i]) continue;
        return "first difference in row " + std::to_string(i / row) + " at byte " +
               std::to_string(i % row);
    }
    return {};
}

uz::DX12Device& NativeOf(IDevice& device) { return static_cast<Dx12Device&>(device).Native(); }

/// Live D3D12MA allocations of the device (textures and buffers).
uint64_t LiveAllocations(IDevice& device) {
    D3D12MA::TotalStatistics stats{};
    NativeOf(device).GetAllocator()->CalculateStatistics(&stats);
    return stats.Total.Stats.AllocationCount;
}

/// The copyable footprint D3D12 itself reports for one mip level.
struct Footprint {
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT layout{};
    UINT rows = 0;
    UINT64 rowBytes = 0;
    UINT64 totalBytes = 0;
};

std::optional<Footprint> CopyFootprint(IDevice& device, uz::RHITextureHandle texture,
                                       uint32_t mip) {
    uz::DX12Texture* entry = NativeOf(device).GetTexturePool().Get(texture.index, texture.generation);
    if (!entry || !entry->resource) return std::nullopt;
    D3D12_RESOURCE_DESC desc{};
    entry->resource->GetDesc(&desc);
    Footprint footprint;
    static_cast<Dx12Device&>(device).D3D12()->GetCopyableFootprints(
        &desc, mip, 1, 0, &footprint.layout, &footprint.rows, &footprint.rowBytes,
        &footprint.totalBytes);
    return footprint;
}

Result<uz::RHITextureHandle> MakeTexture(IDevice& device, uz::RHIFormat format, uint32_t width,
                                         uint32_t height, uint16_t mips = 1,
                                         uz::RHITextureUsage usage = uz::RHITextureUsage::CopySrc |
                                                                     uz::RHITextureUsage::CopyDst) {
    uz::RHITextureDesc desc;
    desc.width = width;
    desc.height = height;
    desc.mipLevels = mips;
    desc.format = format;
    desc.usage = usage;
    desc.debugName = "readback_test";
    return device.CreateTexture(desc);
}

/// Writes tightly packed `texels` to mip `mip` through an upload buffer laid out at the footprint
/// D3D12 reports (independent of `TextureReadback`'s own pitch). The texture ends in `Common`.
Result<void> Upload(EngineContext& context, uz::RHITextureHandle texture, uint32_t mip,
                    const std::vector<std::byte>& texels) {
    IDevice& device = context.Device();
    const std::optional<Footprint> footprint = CopyFootprint(device, texture, mip);
    if (!footprint || footprint->rowBytes * footprint->rows != texels.size()) {
        return Fail(ErrorCode::RequestFailed, Backend::Dx12, "upload data does not fit the mip");
    }
    uz::RHIBufferDesc desc;
    desc.sizeBytes = footprint->totalBytes;
    desc.usage = uz::RHIBufferUsage::CopySrc;
    desc.memory = uz::RHIMemoryType::Upload;
    desc.debugName = "readback_test_upload";
    Result<uz::RHIBufferHandle> buffer = device.CreateBuffer(desc);
    if (!buffer) return Unexpected(buffer.error());
    auto* mapped = static_cast<std::byte*>(device.Rhi().MapBuffer(*buffer));
    if (!mapped) {
        device.DestroyBuffer(*buffer);
        return Fail(ErrorCode::RequestFailed, Backend::Dx12, "upload buffer not mapped");
    }
    for (UINT y = 0; y < footprint->rows; ++y) {
        std::memcpy(mapped + footprint->layout.Offset + uint64_t{footprint->layout.Footprint.RowPitch} * y,
                    texels.data() + footprint->rowBytes * y, footprint->rowBytes);
    }
    device.Rhi().UnmapBuffer(*buffer);
    const uz::RHIBufferHandle source = *buffer;
    const uint32_t pitch = footprint->layout.Footprint.RowPitch;
    Result<void> done = context.SubmitAndWait([&](uz::IRHICommandList& cmd) {
        const uz::RHIBarrierDesc toCopy{texture, uz::RHIBufferHandle::Invalid(),
                                        uz::RHIResourceState::Common,
                                        uz::RHIResourceState::CopyDst};
        cmd.ResourceBarrier(&toCopy, 1);
        cmd.CopyBufferToTexture(source, 0, pitch, texture, mip, 0);
        const uz::RHIBarrierDesc back{texture, uz::RHIBufferHandle::Invalid(),
                                      uz::RHIResourceState::CopyDst,
                                      uz::RHIResourceState::Common};
        cmd.ResourceBarrier(&back, 1);
    });
    device.DestroyBuffer(source);
    return done;
}

/// A texture filled with pattern bytes; destroyed by its owner.
struct Filled {
    uz::RHITextureHandle texture = uz::RHITextureHandle::Invalid();
    uz::RHIFormat format = uz::RHIFormat::Unknown;
    TexelLayout layout;
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<std::byte> texels;
};

Result<Filled> MakeFilled(EngineContext& context, uz::RHIFormat format, uint32_t width,
                          uint32_t height, uint64_t seed) {
    Filled filled;
    filled.format = format;
    filled.layout = ReadbackLayout(format).value_or(TexelLayout{});
    filled.width = width;
    filled.height = height;
    filled.texels = PatternBytes(size_t{width} * height * filled.layout.BytesPerTexel(), seed);
    Result<uz::RHITextureHandle> texture = MakeTexture(context.Device(), format, width, height);
    if (!texture) return Unexpected(texture.error());
    filled.texture = *texture;
    Result<void> uploaded = Upload(context, filled.texture, 0, filled.texels);
    if (!uploaded) {
        context.Device().DestroyTexture(filled.texture);
        return Unexpected(uploaded.error());
    }
    return filled;
}

/// The formats of `kReadableFormats` the adapter supports as 2D textures.
std::vector<uz::RHIFormat> TextureFormats(const Engine& engine) {
    const Result<CapabilityReport> report = engine.Capabilities();
    std::vector<uz::RHIFormat> formats;
    for (const uz::RHIFormat format : kReadableFormats) {
        const FormatCapability* capability = report ? report->Find(format) : nullptr;
        if (capability && capability->texture2D) {
            formats.push_back(format);
        } else {
            Info(Name(format) + " is not a 2D texture format on this adapter; not tested");
        }
    }
    return formats;
}

// ── readback-layout ──────────────────────────────────────────────────────────

int RunReadbackLayout() {
    Check(ReadbackRowPitch(1) == 256 && ReadbackRowPitch(256) == 256 &&
              ReadbackRowPitch(257) == 512 && ReadbackRowPitch(1023 * 8) == 8192 &&
              ReadbackRowPitch(4097 * 2) == 8448,
          "row pitch is the row size rounded up to 256 bytes");
    {
        // Texel-aware pitch: a multiple of 256 and of the texel size, the 12-byte RGB32F texel
        // included, for odd widths (supervisor audit SUP-044 item 1).
        bool whole = true;
        for (const uint32_t texel : {1u, 2u, 4u, 8u, 12u, 16u}) {
            for (const uint32_t width : {1u, 3u, 5u, 1023u, 4097u}) {
                const uint64_t rowBytes = uint64_t{width} * texel;
                const uint64_t pitch = ReadbackRowPitch(rowBytes, texel);
                const bool ok = pitch >= rowBytes && pitch % 256 == 0 && pitch % texel == 0 &&
                                pitch - rowBytes < 256u * texel &&
                                (std::has_single_bit(texel) ? pitch == ReadbackRowPitch(rowBytes) : true);
                if (!ok) {
                    whole = false;
                    Check(false, "texel " + std::to_string(texel) + " width " + std::to_string(width) +
                                     ": pitch " + std::to_string(pitch));
                }
            }
        }
        Check(whole, "row pitch is a multiple of 256 bytes and of the texel size, for odd widths");
        Check(ReadbackRowPitch(12, 12) == 768 && ReadbackRowPitch(1023 * 12, 12) == 12288,
              "RGB32F rows are a whole number of 12-byte texels (768-byte steps)");
    }
    bool sized = true;
    for (const uz::RHIFormat format : kReadableFormats) {
        const std::optional<TexelLayout> layout = ReadbackLayout(format);
        if (!layout || layout->BytesPerTexel() != uz::BytesPerTexel(format) ||
            layout->channels < 1 || layout->channels > 4) {
            sized = false;
            Check(false, "layout of " + Name(format));
        }
    }
    Check(sized, "every readable format's layout matches the RHI's bytes per texel");
    Check(ReadbackLayout(uz::RHIFormat::R16Unorm) == TexelLayout{1, 2} &&
              ReadbackLayout(uz::RHIFormat::RG16Unorm) == TexelLayout{2, 2} &&
              ReadbackLayout(uz::RHIFormat::RGBA16Unorm) == TexelLayout{4, 2},
          "16-bit unorm formats read back as 2-byte channels");
    Check(uz::BytesPerTexel(uz::RHIFormat::R16Unorm) == 2 &&
              uz::BytesPerTexel(uz::RHIFormat::RG16Unorm) == 4 &&
              uz::BytesPerTexel(uz::RHIFormat::RGBA16Unorm) == 8,
          "UZP-MOD-009: the RHI sizes the 16-bit unorm formats");
    Check(uz::ToDxgiFormat(uz::RHIFormat::R16Unorm) == DXGI_FORMAT_R16_UNORM &&
              uz::ToDxgiFormat(uz::RHIFormat::RG16Unorm) == DXGI_FORMAT_R16G16_UNORM &&
              uz::ToDxgiFormat(uz::RHIFormat::RGBA16Unorm) == DXGI_FORMAT_R16G16B16A16_UNORM,
          "UZP-MOD-009: the 16-bit unorm formats map to their DXGI formats");
    const uz::RHIFormat unreadable[] = {uz::RHIFormat::Unknown, uz::RHIFormat::BC1Unorm,
                                        uz::RHIFormat::BC7Srgb, uz::RHIFormat::D16Unorm,
                                        uz::RHIFormat::D32Float, uz::RHIFormat::D24UnormS8Uint};
    bool rejected = true;
    for (const uz::RHIFormat format : unreadable) rejected = rejected && !ReadbackLayout(format);
    Check(rejected, "block-compressed, depth and unknown formats are not read back");
    return Finish();
}

// ── readback-pitch ───────────────────────────────────────────────────────────

int RunReadbackPitch(const fs::path& dir) {
    Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    struct Case {
        uz::RHIFormat format;
        uint32_t channels;  // 0: all
        const char* label;
    };
    std::vector<Case> cases = {
        {uz::RHIFormat::R8Unorm, 0, "L8 (R8Unorm)"},
        {uz::RHIFormat::RGBA8Unorm, 3, "RGB8 (RGBA8Unorm, 3 channels)"},
        {uz::RHIFormat::R16Unorm, 0, "L16 (R16Unorm)"},
        {uz::RHIFormat::RGBA16Unorm, 3, "RGB16 (RGBA16Unorm, 3 channels)"},
        {uz::RHIFormat::RGBA16Float, 3, "RGB16F (RGBA16Float, 3 channels)"},
        {uz::RHIFormat::R32Float, 0, "L32F (R32Float)"},
        {uz::RHIFormat::RGBA32Float, 0, "RGBA32Float"},
    };
    const std::vector<uz::RHIFormat> supported = TextureFormats(engine);
    if (std::find(supported.begin(), supported.end(), uz::RHIFormat::RGB32Float) != supported.end()) {
        cases.push_back({uz::RHIFormat::RGB32Float, 0, "RGB32F (RGB32Float)"});
    }
    constexpr uint32_t kWidths[] = {1, 3, 1023, 4097};
    constexpr uint32_t kRows = 5;

    auto snapshot = std::make_shared<const TestSnapshot>();
    auto future = engine.Submit(snapshot, [&](EngineContext& context, const TestSnapshot&)
                                              -> Result<void> {
        IDevice& device = context.Device();
        bool allRows = true;
        bool allPitches = true;
        uint64_t seed = 1;
        for (const Case& c : cases) {
            for (const uint32_t width : kWidths) {
                const std::string what =
                    std::string(c.label) + ", width " + std::to_string(width);
                Result<Filled> filled = MakeFilled(context, c.format, width, kRows, seed++);
                if (!filled) {
                    allRows = false;
                    Check(false, what + ": texture uploaded", filled.error().Describe());
                    continue;
                }
                // The pitch the readback uses holds the D3D12 copy footprint's row, is a multiple
                // of 256 and a whole number of texels (Vulkan counts rows in texels): for
                // power-of-two texels it is the footprint's own pitch.
                const uint32_t texel = filled->layout.BytesPerTexel();
                const uint64_t rowBytes = uint64_t{width} * texel;
                const uint64_t pitch = ReadbackRowPitch(rowBytes, texel);
                const std::optional<Footprint> footprint = CopyFootprint(device, filled->texture, 0);
                const bool pitchOk =
                    footprint && pitch % kReadbackPitchAlignment == 0 && pitch % texel == 0 &&
                    pitch >= footprint->layout.Footprint.RowPitch &&
                    (std::has_single_bit(texel) ? pitch == footprint->layout.Footprint.RowPitch : true);
                allPitches = allPitches && pitchOk;
                if (!pitchOk) Check(false, what + ": readback pitch fits the D3D12 footprint and the texel");
                Info(what + ": row " + std::to_string(rowBytes) + " bytes, pitch " + std::to_string(pitch));

                TextureReadback readback(context);
                ReadbackDesc desc;
                desc.texture = filled->texture;
                desc.channels = c.channels;
                Result<ReadbackId> id = readback.Request(desc);
                Result<ReadbackImage> image =
                    id ? readback.Complete(*id) : Result<ReadbackImage>(Unexpected(id.error()));
                const uint32_t channels = c.channels == 0 ? filled->layout.channels : c.channels;
                const std::string diff =
                    Compare(image, FirstChannels(filled->texels, filled->layout, channels), width,
                            kRows);
                Check(diff.empty(), what + ": every row reads back unshifted", diff);
                allRows = allRows && diff.empty();
                device.DestroyTexture(filled->texture);
            }
        }
        Check(allPitches, "the readback pitch equals D3D12's copy footprint for every width");
        Check(allRows,
              "widths 1, 3, 1023 and 4097 read back with correct rows for every tested format");
        return {};
    });
    Result<void> result = Get(future);
    Check(result.has_value(), "the pitch request ran", Describe(result));
    return Finish();
}

// ── readback-exact ───────────────────────────────────────────────────────────

int RunReadbackExact(const fs::path& dir) {
    Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    const std::vector<uz::RHIFormat> formats = TextureFormats(engine);
    constexpr uint32_t kW = 1023;
    constexpr uint32_t kH = 7;

    auto snapshot = std::make_shared<const TestSnapshot>();
    auto future = engine.Submit(snapshot, [&](EngineContext& context, const TestSnapshot&)
                                              -> Result<void> {
        IDevice& device = context.Device();
        bool all = true;
        uint64_t seed = 100;
        for (const uz::RHIFormat format : formats) {
            Result<Filled> filled = MakeFilled(context, format, kW, kH, seed++);
            if (!filled) {
                all = false;
                Check(false, Name(format) + " reads back bit-identical", filled.error().Describe());
                continue;
            }
            TextureReadback readback(context);
            ReadbackDesc desc;
            desc.texture = filled->texture;
            Result<ReadbackId> id = readback.Request(desc);
            Result<ReadbackImage> image =
                id ? readback.Complete(*id) : Result<ReadbackImage>(Unexpected(id.error()));
            std::string diff = Compare(image, filled->texels, kW, kH);
            if (diff.empty() && (image->format != format ||
                                 image->channels != filled->layout.channels ||
                                 image->bytesPerChannel != filled->layout.bytesPerChannel)) {
                diff = "image format fields differ";
            }
            Check(diff.empty(), Name(format) + " reads back bit-identical", diff);
            all = all && diff.empty();

            // The spec's scenario: an RGB16 channel (RGBA16Unorm storage) 1023 texels wide.
            if (format == uz::RHIFormat::RGBA16Unorm) {
                desc.channels = 3;
                Result<ReadbackId> rgb = readback.Request(desc);
                Result<ReadbackImage> rgbImage = rgb ? readback.Complete(*rgb)
                                                     : Result<ReadbackImage>(Unexpected(rgb.error()));
                const std::string rgbDiff = Compare(
                    rgbImage, FirstChannels(filled->texels, filled->layout, 3), kW, kH);
                Check(rgbDiff.empty() && rgbImage->channels == 3 && rgbImage->bytesPerChannel == 2,
                      "an RGB16 texture 1023 texels wide reads back every texel unchanged",
                      rgbDiff);
                all = all && rgbDiff.empty();
            }
            device.DestroyTexture(filled->texture);
        }
        Check(all, "every supported format reads back bit-identical");

        // A lower mip level of a mipmapped texture: its own size, its own texels.
        Result<uz::RHITextureHandle> mipped =
            MakeTexture(device, uz::RHIFormat::RGBA16Unorm, 64, 40, 3);
        if (!mipped) return Unexpected(mipped.error());
        const std::vector<std::byte> mip2 = PatternBytes(size_t{16} * 10 * 8, 7);
        Result<void> uploaded = Upload(context, *mipped, 2, mip2);
        if (uploaded) {
            TextureReadback readback(context);
            ReadbackDesc desc;
            desc.texture = *mipped;
            desc.mipLevel = 2;
            Result<ReadbackId> id = readback.Request(desc);
            Result<ReadbackImage> image =
                id ? readback.Complete(*id) : Result<ReadbackImage>(Unexpected(id.error()));
            const std::string diff = Compare(image, mip2, 16, 10);
            Check(diff.empty(), "mip level 2 (16x10) reads back bit-identical", diff);
        } else {
            Check(false, "mip level 2 uploaded", uploaded.error().Describe());
        }
        device.DestroyTexture(*mipped);
        return {};
    });
    Result<void> result = Get(future);
    Check(result.has_value(), "the exactness request ran", Describe(result));
    return Finish();
}

// ── readback-drain ───────────────────────────────────────────────────────────

int RunReadbackDrain(const fs::path& dir) {
    Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    constexpr size_t kRequests = 64;
    auto snapshot = std::make_shared<const TestSnapshot>();
    uint64_t atStart = 0;
    uint64_t atEnd = 0;

    auto future = engine.Submit(snapshot, [&](EngineContext& context, const TestSnapshot&)
                                              -> Result<void> {
        IDevice& device = context.Device();
        atStart = LiveAllocations(device);
        const uz::RHIFormat formats[] = {uz::RHIFormat::R16Unorm, uz::RHIFormat::RGBA16Unorm,
                                         uz::RHIFormat::R8Unorm, uz::RHIFormat::RGBA8Unorm,
                                         uz::RHIFormat::R16Float, uz::RHIFormat::RGBA16Float,
                                         uz::RHIFormat::R32Float, uz::RHIFormat::RGBA32Float};
        const uint32_t widths[] = {1, 3, 255, 1023, 64, 513, 4097, 17};
        std::vector<Filled> textures;
        for (size_t i = 0; i < std::size(formats); ++i) {
            Result<Filled> filled = MakeFilled(context, formats[i], widths[i], 9, 1000 + i);
            if (!filled) return Unexpected(filled.error());
            textures.push_back(std::move(*filled));
        }
        const uint64_t baseline = LiveAllocations(device);

        // A burst of requests, all in flight before any is completed.
        std::vector<ReadbackId> ids;
        std::vector<size_t> sources;
        {
            TextureReadback readback(context);
            for (size_t i = 0; i < kRequests; ++i) {
                const size_t source = (i * 5) % textures.size();
                ReadbackDesc desc;
                desc.texture = textures[source].texture;
                Result<ReadbackId> id = readback.Request(desc);
                if (!id) return Unexpected(id.error());
                ids.push_back(*id);
                sources.push_back(source);
            }
            Check(readback.Outstanding() == kRequests && readback.StagingBuffers() == kRequests,
                  "64 readback requests are outstanding, each with its own staging buffer",
                  std::to_string(readback.StagingBuffers()) + " staging buffers");
            Check(LiveAllocations(device) == baseline + kRequests,
                  "the device holds one staging allocation per outstanding request",
                  std::to_string(LiveAllocations(device) - baseline) + " allocations");
            Check(std::is_sorted(ids.begin(), ids.end()) &&
                      std::adjacent_find(ids.begin(), ids.end()) == ids.end(),
                  "request ids increase in submission order");

            std::vector<ReadbackOutcome> outcomes = readback.Drain();
            bool order = outcomes.size() == kRequests;
            bool exact = order;
            std::string first;
            for (size_t i = 0; order && i < outcomes.size(); ++i) {
                order = outcomes[i].id == ids[i];
                const Filled& source = textures[sources[i]];
                const std::string diff =
                    Compare(outcomes[i].image, source.texels, source.width, source.height);
                if (!diff.empty() && first.empty()) first = "request " + std::to_string(i) + ": " + diff;
                exact = exact && diff.empty();
            }
            Check(order, "the drain reports every request in submission order",
                  std::to_string(outcomes.size()) + " outcomes");
            Check(exact, "every drained request returns its texture's texels", first);
            Check(readback.Outstanding() == 0 && readback.StagingBuffers() == 0,
                  "after the drain no request is outstanding and no staging buffer is held");
            Check(LiveAllocations(device) == baseline,
                  "after the drain no staging buffer remains allocated on the device",
                  std::to_string(LiveAllocations(device)) + " allocations, baseline " +
                      std::to_string(baseline));
        }

        // Out-of-order completion and the destructor's drain.
        {
            TextureReadback readback(context);
            Result<ReadbackId> a = readback.Request({textures[0].texture});
            Result<ReadbackId> b = readback.Request({textures[1].texture});
            Result<ReadbackId> c = readback.Request({textures[2].texture});
            if (!a || !b || !c) return Fail(ErrorCode::RequestFailed, Backend::Dx12, "request");
            const bool cFirst =
                Compare(readback.Complete(*c), textures[2].texels, textures[2].width, 9).empty();
            const bool aSecond =
                Compare(readback.Complete(*a), textures[0].texels, textures[0].width, 9).empty();
            Check(cFirst && aSecond && readback.Outstanding() == 1,
                  "a later request can be completed before earlier ones");
            Result<ReadbackImage> again = readback.Complete(*a);
            Check(!again && again.error().code == ErrorCode::RequestFailed,
                  "completing a request twice fails with request_failed", Describe(again));
            for (size_t i = 0; i < 16; ++i) {
                static_cast<void>(readback.Request({textures[i % textures.size()].texture}));
            }
            Check(readback.StagingBuffers() == 17, "17 requests outstanding before destruction",
                  std::to_string(readback.StagingBuffers()));
        }
        Check(LiveAllocations(device) == baseline,
              "destroying a TextureReadback drains it and releases its staging buffers",
              std::to_string(LiveAllocations(device)) + " allocations, baseline " +
                  std::to_string(baseline));

        // Invalid requests fail before anything is allocated.
        {
            TextureReadback readback(context);
            Result<uz::RHITextureHandle> bc = MakeTexture(device, uz::RHIFormat::BC1Unorm, 64, 64);
            Result<uz::RHITextureHandle> noCopy =
                MakeTexture(device, uz::RHIFormat::R16Unorm, 8, 8, 1, uz::RHITextureUsage::ShaderResource);
            Result<uz::RHITextureHandle> gone = MakeTexture(device, uz::RHIFormat::R16Unorm, 8, 8);
            if (!bc || !noCopy || !gone) return Fail(ErrorCode::RequestFailed, Backend::Dx12, "textures");
            device.DestroyTexture(*gone);
            const uint64_t before = LiveAllocations(device);
            ReadbackDesc fiveChannels{textures[1].texture};
            fiveChannels.channels = 5;
            ReadbackDesc badMip{textures[0].texture};
            badMip.mipLevel = 1;
            ReadbackDesc badSlice{textures[0].texture};
            badSlice.arraySlice = 1;
            const struct {
                ReadbackDesc desc;
                const char* what;
            } invalid[] = {
                {ReadbackDesc{*bc}, "a block-compressed texture"},
                {ReadbackDesc{*noCopy}, "a texture without CopySrc usage"},
                {ReadbackDesc{*gone}, "a destroyed texture"},
                {ReadbackDesc{uz::RHITextureHandle::Invalid()}, "an invalid handle"},
                {fiveChannels, "five channels of RGBA16Unorm"},
                {badMip, "a mip level the texture lacks"},
                {badSlice, "an array slice the texture lacks"},
            };
            bool allRejected = true;
            for (const auto& entry : invalid) {
                Result<ReadbackId> id = readback.Request(entry.desc);
                const bool rejected = !id && id.error().code == ErrorCode::RequestFailed;
                Check(rejected, std::string("a readback of ") + entry.what + " is rejected",
                      Describe(id));
                if (!id) Info(id.error().Describe());
                allRejected = allRejected && rejected;
            }
            Check(allRejected && readback.StagingBuffers() == 0 && LiveAllocations(device) == before,
                  "rejected requests allocate nothing");
            device.DestroyTexture(*bc);
            device.DestroyTexture(*noCopy);
        }
        for (const Filled& filled : textures) device.DestroyTexture(filled.texture);
        return {};
    });
    Result<void> result = Get(future);
    Check(result.has_value(), "the drain request ran", Describe(result));

    // Readback requests from four threads at once: the engine thread serves them in turn.
    std::vector<std::future<Result<void>>> futures;
    std::vector<std::thread> threads;
    std::mutex futuresMutex;
    for (int t = 0; t < 4; ++t) {
        threads.emplace_back([&, t] {
            auto f = engine.Submit(snapshot, [t](EngineContext& context, const TestSnapshot&)
                                                 -> Result<void> {
                std::vector<Filled> textures;
                for (int i = 0; i < 4; ++i) {
                    Result<Filled> filled = MakeFilled(context, uz::RHIFormat::RGBA16Unorm,
                                                       static_cast<uint32_t>(97 + 64 * i), 6,
                                                       static_cast<uint64_t>(5000 + t * 10 + i));
                    if (!filled) return Unexpected(filled.error());
                    textures.push_back(std::move(*filled));
                }
                TextureReadback readback(context);
                for (int i = 0; i < 16; ++i) {
                    Result<ReadbackId> id = readback.Request({textures[static_cast<size_t>(i % 4)].texture});
                    if (!id) return Unexpected(id.error());
                }
                std::vector<ReadbackOutcome> outcomes = readback.Drain();
                for (size_t i = 0; i < outcomes.size(); ++i) {
                    const Filled& source = textures[i % 4];
                    const std::string diff =
                        Compare(outcomes[i].image, source.texels, source.width, source.height);
                    if (!diff.empty()) {
                        return Fail(ErrorCode::RequestFailed, Backend::Dx12, "outcome " + std::to_string(i) + ": " + diff);
                    }
                }
                for (const Filled& filled : textures) context.Device().DestroyTexture(filled.texture);
                return {};
            });
            std::lock_guard<std::mutex> lock(futuresMutex);
            futures.push_back(std::move(f));
        });
    }
    for (std::thread& thread : threads) thread.join();
    bool allThreads = futures.size() == 4;
    std::string firstError;
    for (auto& f : futures) {
        Result<void> r = Get(f);
        if (!r && firstError.empty()) firstError = r.error().Describe();
        allThreads = allThreads && r.has_value();
    }
    Check(allThreads, "readback bursts submitted from four threads all drain exactly", firstError);
    auto count = engine.Submit(snapshot, [&](EngineContext& context, const TestSnapshot&)
                                             -> Result<void> {
        atEnd = LiveAllocations(context.Device());
        return {};
    });
    Result<void> counted = Get(count);
    Check(counted && atEnd == atStart,
          "after every request the device holds no more allocations than before the first",
          std::to_string(atEnd) + " allocations, " + std::to_string(atStart) + " at the start");
    return Finish();
}

// ── readback-failure ─────────────────────────────────────────────────────────

int RunReadbackFailure(const fs::path& dir) {
    auto snapshot = std::make_shared<const TestSnapshot>();
    {
        Engine engine(TestOptions(dir));
        if (NoAdapter(engine)) return kExitSkip;
        auto future = engine.Submit(snapshot, [&](EngineContext& context, const TestSnapshot&)
                                                  -> Result<void> {
            IDevice& device = context.Device();
            Result<Filled> filled = MakeFilled(context, uz::RHIFormat::R16Unorm, 1023, 5, 77);
            if (!filled) return Unexpected(filled.error());
            TextureReadback readback(context);
            Result<ReadbackId> first = readback.Request({filled->texture});
            Result<ReadbackImage> before =
                first ? readback.Complete(*first) : Result<ReadbackImage>(Unexpected(first.error()));
            Check(Compare(before, filled->texels, 1023, 5).empty(),
                  "a readback succeeds before the removal", Describe(before));

            // New contents, then two readbacks in flight and the device removed under them.
            const std::vector<std::byte> newer = PatternBytes(filled->texels.size(), 78);
            Result<void> uploaded = Upload(context, filled->texture, 0, newer);
            if (!uploaded) return Unexpected(uploaded.error());
            Result<ReadbackId> pending = readback.Request({filled->texture});
            Result<ReadbackId> pending2 = readback.Request({filled->texture});
            Check(pending && pending2 && readback.Outstanding() == 2,
                  "two readbacks are pending when the device is removed");
            ComPtr<ID3D12Device5> device5;
            if (FAILED(static_cast<Dx12Device&>(device).D3D12()->QueryInterface(IID_PPV_ARGS(&device5)))) {
                return Fail(ErrorCode::RequestFailed, Backend::Dx12, "no ID3D12Device5");
            }
            device5->RemoveDevice();

            Result<ReadbackImage> after =
                pending ? readback.Complete(*pending) : Result<ReadbackImage>(Unexpected(pending.error()));
            Info(Describe(after));
            Check(!after && after.error().code == ErrorCode::DeviceRemoved &&
                      after.error().Describe().starts_with(
                          "device_removed {backend: dx12, reason: DXGI_ERROR_DEVICE_REMOVED"),
                  "the pending readback fails with device_removed {backend: dx12, reason}",
                  Describe(after));
            Check(!after.has_value(), "no texels are returned, neither previous nor new");
            std::vector<ReadbackOutcome> drained = readback.Drain();
            Check(drained.size() == 1 && drained[0].id == *pending2 && !drained[0].image &&
                      drained[0].image.error().code == ErrorCode::DeviceRemoved,
                  "the drain fails the other pending readback with device_removed");
            Result<ReadbackId> later = readback.Request({filled->texture});
            Check(!later && later.error().code == ErrorCode::DeviceRemoved,
                  "a readback requested after the removal fails with device_removed",
                  Describe(later));
            Check(readback.Outstanding() == 0 && readback.StagingBuffers() == 0,
                  "the failed readbacks hold no staging buffer");
            device.DestroyTexture(filled->texture);
            return {};
        });
        Result<void> result = Get(future);
        Check(result.has_value(), "the removal request ran", Describe(result));
        bool ran = false;
        auto next = engine.Submit(snapshot, [&](EngineContext&, const TestSnapshot&) -> Result<void> {
            ran = true;
            return {};
        });
        Result<void> after = Get(next);
        Check(!after && after.error().code == ErrorCode::DeviceRemoved && !ran,
              "later requests fail with device_removed without running", Describe(after));
        engine.Stop();
    }

    // A readback whose copy is stuck behind a stalled queue: the wait's timeout, no texels, and
    // the staging buffer is kept until the copy has completed.
    EngineOptions options = TestOptions(dir);
    options.requestDeadline = Ms{300};
    Engine engine(options);
    if (NoAdapter(engine)) return kExitSkip;
    auto future = engine.Submit(snapshot, [&](EngineContext& context, const TestSnapshot&)
                                              -> Result<void> {
        auto& device = static_cast<Dx12Device&>(context.Device());
        Result<Filled> filled = MakeFilled(context, uz::RHIFormat::RGBA16Unorm, 300, 4, 91);
        if (!filled) return Unexpected(filled.error());
        ComPtr<ID3D12Fence> blocker;
        if (FAILED(device.D3D12()->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&blocker)))) {
            return Fail(ErrorCode::ResourceCreationFailed, Backend::Dx12, "blocker fence");
        }
        device.Native().GetDirectQueue()->Wait(blocker.Get(), 1);
        TextureReadback readback(context);
        Result<ReadbackId> id = readback.Request({filled->texture});
        Result<ReadbackImage> image =
            id ? readback.Complete(*id) : Result<ReadbackImage>(Unexpected(id.error()));
        Check(!image && image.error().code == ErrorCode::Timeout,
              "a readback behind a stalled queue fails with timeout and no texels", Describe(image));
        Check(readback.Outstanding() == 0 && readback.StagingBuffers() == 1,
              "its staging buffer is held while the GPU may still write it");
        const bool released = SUCCEEDED(blocker->Signal(1));
        const auto until = Clock::now() + std::chrono::seconds(10);
        while (device.Queue().Completed() < device.Queue().LastSubmitted() && Clock::now() < until) {
            std::this_thread::sleep_for(Ms{5});
        }
        static_cast<void>(readback.Drain());
        Check(released && readback.StagingBuffers() == 0,
              "once the copy has completed the drain releases the held staging buffer");
        device.DestroyTexture(filled->texture);
        return {};
    });
    Result<void> result = Get(future);
    Check(result.has_value(), "the timeout request ran", Describe(result));
    engine.Stop();
    return Finish();
}

// ── readback-kernel (phase1.4_render-core-layer) ─────────────────────────────

/// End to end through the render layer: the ramp kernel compiled through the engine's kernel
/// cache, dispatched into eight R32Float textures in one submission, and 64 readbacks of them in
/// flight at once, drained in submission order with every texel equal to the IEEE-strict CPU
/// value; no staging buffer survives the drain, and the dispatched kernel is in the cache folder.
int RunReadbackKernel(const fs::path& dir) {
    Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    constexpr size_t kRequests = 64;
    struct Target {
        uint32_t width = 0, height = 0;
        TestSnapshot snapshot;
        uz::RHITextureHandle texture = uz::RHITextureHandle::Invalid();
    };
    auto snapshot = std::make_shared<const TestSnapshot>();
    auto future = engine.Submit(snapshot, [&](EngineContext& context, const TestSnapshot&)
                                              -> Result<void> {
        IDevice& device = context.Device();
        Result<ComputeKernel> kernel = context.Kernel(RampSource());
        Check(kernel.has_value(), "the ramp kernel compiles through the kernel cache",
              Describe(kernel));
        if (!kernel) return Unexpected(kernel.error());

        const uint32_t widths[] = {1, 3, 100, 255, 1023, 4097, 64, 17};
        std::vector<Target> targets;
        const auto destroy = [&] {
            for (const Target& t : targets) device.DestroyTexture(t.texture);
        };
        for (size_t i = 0; i < std::size(widths); ++i) {
            Target t;
            t.width = widths[i];
            t.height = 5 + static_cast<uint32_t>(i);
            t.snapshot = TestSnapshot{20 + i, 0.1f * static_cast<float>(i + 1),
                                      0.37f / static_cast<float>(i + 1)};
            uz::RHITextureDesc desc;
            desc.width = t.width;
            desc.height = t.height;
            desc.format = uz::RHIFormat::R32Float;
            desc.usage = uz::RHITextureUsage::UnorderedAccess | uz::RHITextureUsage::CopySrc;
            desc.debugName = "readback_kernel_target";
            Result<uz::RHITextureHandle> texture = device.CreateTexture(desc);
            if (!texture) {
                destroy();
                return Unexpected(texture.error());
            }
            t.texture = *texture;
            targets.push_back(t);
        }
        const uint64_t baseline = LiveAllocations(device);

        // One submission dispatches the kernel into every target; nothing waits for it before
        // the readbacks are requested (they follow it on the same queue).
        const uz::RHIPipelineHandle pipeline = kernel->pipeline;
        Result<uint64_t> dispatched = context.Submit([&](uz::IRHICommandList& cmd) {
            for (const Target& t : targets) {
                uz::RHIBarrierDesc toUav{t.texture, uz::RHIBufferHandle::Invalid(),
                                         uz::RHIResourceState::Common,
                                         uz::RHIResourceState::UnorderedAccess};
                cmd.ResourceBarrier(&toUav, 1);
                uint32_t constants[5] = {
                    t.width, t.height, std::bit_cast<uint32_t>(t.snapshot.s),
                    std::bit_cast<uint32_t>(t.snapshot.t),
                    std::bit_cast<uint32_t>(static_cast<float>(t.snapshot.revision))};
                cmd.SetPipeline(pipeline);
                cmd.SetRootConstants(kRootConstantsParam, constants, 5);
                cmd.SetDescriptorTable(kUavTableParam, device.Rhi().GetTextureUAVIndex(t.texture));
                cmd.Dispatch((t.width + 7) / 8, (t.height + 7) / 8, 1);
            }
        });
        Check(dispatched.has_value(), "the cached kernel is dispatched into eight textures",
              Describe(dispatched));
        if (!dispatched) {
            destroy();
            return Unexpected(dispatched.error());
        }

        {
            TextureReadback readback(context);
            std::vector<ReadbackId> ids;
            std::vector<size_t> sources;
            for (size_t i = 0; i < kRequests; ++i) {
                const size_t source = (i * 3) % targets.size();
                ReadbackDesc desc;
                desc.texture = targets[source].texture;
                desc.state = uz::RHIResourceState::UnorderedAccess;
                Result<ReadbackId> id = readback.Request(desc);
                if (!id) {
                    Check(false, "every readback request is accepted", Describe(id));
                    break;
                }
                ids.push_back(*id);
                sources.push_back(source);
            }
            Check(readback.Outstanding() == kRequests && readback.StagingBuffers() == kRequests,
                  "64 readbacks of the dispatched textures are in flight at once",
                  std::to_string(readback.Outstanding()) + " outstanding");
            std::vector<ReadbackOutcome> outcomes = readback.Drain();
            bool order = outcomes.size() == ids.size();
            size_t mismatches = 0;
            std::string first;
            for (size_t i = 0; order && i < outcomes.size(); ++i) {
                order = outcomes[i].id == ids[i];
                const Target& t = targets[sources[i]];
                const Result<ReadbackImage>& image = outcomes[i].image;
                if (!image || image->format != uz::RHIFormat::R32Float || image->width != t.width ||
                    image->height != t.height || image->texels.size() != size_t{t.width} * t.height * 4) {
                    if (mismatches++ == 0) {
                        first = "request " + std::to_string(i) + ": " +
                                (image ? std::string("wrong image shape") : image.error().Describe());
                    }
                    continue;
                }
                for (uint32_t y = 0; y < t.height; ++y) {
                    for (uint32_t x = 0; x < t.width; ++x) {
                        uint32_t got = 0;
                        std::memcpy(&got, image->texels.data() + (size_t{y} * t.width + x) * 4, 4);
                        const uint32_t want = std::bit_cast<uint32_t>(ExpectedRamp(x, y, t.snapshot));
                        if (got != want && mismatches++ == 0) {
                            char buf[160];
                            std::snprintf(buf, sizeof(buf),
                                          "request %zu at (%u, %u): got %08X, expected %08X", i, x,
                                          y, got, want);
                            first = buf;
                        }
                    }
                }
            }
            Check(order, "the drain reports every request in submission order",
                  std::to_string(outcomes.size()) + " outcomes");
            Check(mismatches == 0,
                  "every drained texel equals the IEEE-strict CPU value bit for bit",
                  std::to_string(mismatches) + " mismatches; " + first);
            Check(readback.Outstanding() == 0 && readback.StagingBuffers() == 0 &&
                      LiveAllocations(device) == baseline,
                  "after the drain no request is outstanding and no staging buffer remains",
                  std::to_string(LiveAllocations(device)) + " allocations, baseline " +
                      std::to_string(baseline));
        }
        destroy();
        return {};
    });
    Result<void> result = Get(future);
    Check(result.has_value(), "the end-to-end request ran", Describe(result));
    engine.Stop();

    // The dispatched kernel came from the cache folder the engine was given.
    Result<std::unique_ptr<DxcKernelCompiler>> dxc = DxcKernelCompiler::Load(DefaultDxcompilerPath());
    Check(dxc.has_value(), "DXC loads", Describe(dxc));
    if (dxc) {
        KernelCache cache(**dxc, dir / "kernel-cache");
        Result<CompiledKernel> dxil = cache.Get(RampSource(), KernelTarget::Dxil);
        Check(dxil && dxil->cacheHit, "the dispatched DXIL kernel is in the kernel cache folder",
              Describe(dxil));
    }
    return Finish();
}

}  // namespace

/// The `uv-raster-*` cases (tests/render/uv_raster_test.cpp); -1 for any other mode.
int RunUvRasterCase(std::string_view mode, const fs::path& dir);
/// The `vulkan-*` cases (tests/render/vulkan_test.cpp); -1 for any other mode.
int RunVulkanCase(std::string_view mode, const fs::path& dir);

int main(int argc, char** argv) {
    const std::string_view mode = argc > 1 ? argv[1] : "";
    if (mode == "xxhash") return RunXxhash();
    if (mode == "admission") return RunAdmission();
    if (mode == "readback-layout") return RunReadbackLayout();
    if (mode == "image-reference") return RunImagePassCase(mode, {});
    if (mode == "vulkan-qualify") return RunVulkanCase(mode, {});
    if (argc < 3) {
        std::fprintf(stderr,
                     "usage: uzp-render-tests xxhash | admission | readback-layout | kernel-cache | "
                     "dispatch | deadline | device-removed | unavailable | capabilities | "
                     "readback-pitch | readback-exact | readback-drain | readback-failure | "
                     "readback-kernel | uv-raster-* | vulkan-qualify | vulkan-device | vulkan-faults | vulkan-readback | "
                     "vulkan-uv-raster | vulkan-image-passes | "
                     "image-* "
                     "<work-dir>\n");
        return 2;
    }
    const fs::path dir = argv[2];
    std::error_code ec;
    fs::create_directories(dir, ec);
    uz::LogInit((dir / ("render-tests-" + std::string(mode) + ".log")).string().c_str());
    uz::LogSuppressConsole();
    int code = 2;
    if (mode == "kernel-cache") code = RunKernelCache(dir);
    else if (mode == "dispatch") code = RunDispatch(dir);
    else if (mode == "deadline") code = RunDeadline(dir);
    else if (mode == "device-removed") code = RunDeviceRemoved(dir);
    else if (mode == "unavailable") code = RunUnavailable(dir);
    else if (mode == "capabilities") code = RunCapabilities(dir);
    else if (mode == "readback-pitch") code = RunReadbackPitch(dir);
    else if (mode == "readback-exact") code = RunReadbackExact(dir);
    else if (mode == "readback-drain") code = RunReadbackDrain(dir);
    else if (mode == "readback-failure") code = RunReadbackFailure(dir);
    else if (mode == "readback-kernel") code = RunReadbackKernel(dir);
    else if (const int uv = RunUvRasterCase(mode, dir); uv >= 0) code = uv;
    else if (const int vulkan = RunVulkanCase(mode, dir); vulkan >= 0) code = vulkan;
    else if (const int image = RunImagePassCase(mode, dir); image >= 0) code = image;
    else std::fprintf(stderr, "unknown case %.*s\n", static_cast<int>(mode.size()), mode.data());
    uz::LogShutdown();
    return code;
}
