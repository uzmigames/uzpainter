// Native tests of the render layer's device, engine thread, kernel cache and capability query
// (src/render/, rulebook task phase1.1_core-device-kernels). Built by `zig build render-tests`
// and driven by tests/render/test_core_device_kernels.py.
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
#include "render/xxhash64.h"

#include "dx12_device.h"
#include "dx12_guids.h"
#include "log.h"

#include <windows.h>

#include <atomic>
#include <bit>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <memory>
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
    Check(report->formats.size() == 28, "every RHI format is reported",
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

}  // namespace

int main(int argc, char** argv) {
    const std::string_view mode = argc > 1 ? argv[1] : "";
    if (mode == "xxhash") return RunXxhash();
    if (mode == "admission") return RunAdmission();
    if (argc < 3) {
        std::fprintf(stderr,
                     "usage: uzp-render-tests xxhash | admission | kernel-cache | dispatch | deadline | "
                     "device-removed | unavailable | capabilities <work-dir>\n");
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
    else std::fprintf(stderr, "unknown case %.*s\n", static_cast<int>(mode.size()), mode.data());
    uz::LogShutdown();
    return code;
}
