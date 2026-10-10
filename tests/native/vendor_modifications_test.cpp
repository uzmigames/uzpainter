// Native tests of the local modifications of the vendored UzEngine render core
// (thirdparty/uzengine-render-core/MODIFICATIONS.md). Built by `zig build native-tests` and
// driven by tests/vendoring/test_modifications.py.
//
// Usage: uzp-vendor-tests <case> [args]
//   factory              UZP-MOD-001/002: only DX12 and Vulkan are created
//   fence dx12|vulkan    UZP-MOD-003: timeout, signaled and device_lost on one backend
//   rayquery-decision    UZP-MOD-004: DXR tier / shader model decision
//   agility              UZP-MOD-005: Agility SDK runtime loaded from D3D12\ beside the exe
//   spirv <out-dir>      UZP-MOD-006: writes plain.spv and rayquery.spv for inspection
//   ieee <out-dir>       UZP-MOD-008: writes one float kernel compiled with and without
//                        `ieeeStrict` as DXIL (with DXC's disassembly) and as SPIR-V
//
// Output: one line per check, `PASS <check>` or `FAIL <check>: <detail>`, plus `INFO` lines.
// Exit code 0 when every check passed, 1 when one failed, 2 on a usage error, 77 when the
// hardware a case needs (a DX12 or Vulkan adapter) is absent.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define VK_NO_PROTOTYPES
#define VK_USE_PLATFORM_WIN32_KHR
#include <volk.h>

#include "dx12_device.h"
#include "dx12_guids.h"
#include "log.h"
#include "paths.h"
#include "rhi.h"
#include "rhi_backend.h"
#include "rhi_config.h"
#include "shader_compiler.h"
#include "vulkan_device.h"

#include <spdlog/sinks/callback_sink.h>

#include <windows.h>
#include <psapi.h>
#include <unknwn.h>

#include <chrono>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <memory>
#include <mutex>
#include <string>
#include <string_view>
#include <vector>

namespace {

using namespace uz;
using Clock = std::chrono::steady_clock;

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

/// Every log message of the render core, kept for checks on what it reported.
class LogCapture {
public:
    LogCapture() {
        LogInit("uzp-vendor-tests.log");
        LogSuppressConsole();
        LogSetLevel(LogLevel::Info);
        m_sink = std::make_shared<spdlog::sinks::callback_sink_mt>(
            [this](const spdlog::details::log_msg& msg) {
                std::lock_guard<std::mutex> lock(m_mutex);
                m_lines.emplace_back(msg.payload.data(), msg.payload.size());
            });
        LogAddSink(m_sink);
    }
    ~LogCapture() {
        LogRemoveSink(m_sink);
        LogShutdown();
    }
    bool Contains(std::string_view text) const {
        std::lock_guard<std::mutex> lock(m_mutex);
        for (const auto& line : m_lines) {
            if (line.find(text) != std::string::npos) return true;
        }
        return false;
    }

private:
    std::shared_ptr<spdlog::sinks::callback_sink_mt> m_sink;
    mutable std::mutex m_mutex;
    std::vector<std::string> m_lines;
};

std::string Hex(int32_t value) {
    char buf[16];
    std::snprintf(buf, sizeof(buf), "0x%08X", static_cast<uint32_t>(value));
    return buf;
}

const char* StatusName(FenceWaitStatus status) {
    switch (status) {
        case FenceWaitStatus::Signaled:   return "signaled";
        case FenceWaitStatus::Timeout:    return "timeout";
        case FenceWaitStatus::DeviceLost: return "device_lost";
    }
    return "unknown";
}

std::unique_ptr<IRHIDevice> CreateDevice(RHIBackend backend) {
    RHIConfig config;
    config.backend = backend;
    return CreateRHIDevice(ToDeviceDesc(config));
}

// ── UZP-MOD-001/002 ──────────────────────────────────────────────────────────

int RunFactory() {
    LogCapture log;
    for (RHIBackend backend : {RHIBackend::DX11, RHIBackend::Metal, RHIBackend::Null}) {
        const std::string name = RHIBackendToString(backend);
        auto device = CreateDevice(backend);
        Check(device == nullptr, "factory rejects " + name, "a device was created");
        const std::string expected =
            "CreateRHIDevice: backend " + name + " is not supported (DX12 and Vulkan only)";
        Check(log.Contains(expected), "factory reports " + name + " as unsupported",
              "no log line '" + expected + "'");
    }
    for (RHIBackend backend : {RHIBackend::DX12, RHIBackend::Vulkan}) {
        const std::string name = RHIBackendToString(backend);
        auto device = CreateDevice(backend);
        Check(device != nullptr, "factory creates " + name, "device creation failed (see log)");
        Check(device == nullptr || device->GetBackend() == backend,
              "factory " + name + " device reports its backend");
        Check(!log.Contains("backend " + name + " is not supported"),
              "factory does not reject " + name);
    }
    return g_failures == 0 ? 0 : 1;
}

// ── UZP-MOD-003 ──────────────────────────────────────────────────────────────

/// Waits for `value` with a deadline `budget` from now; returns the result and the time taken.
FenceWaitResult TimedWait(IRHIFence* fence, uint64_t value, std::chrono::milliseconds budget,
                          std::chrono::microseconds& elapsed) {
    const auto start = Clock::now();
    const FenceWaitResult result = fence->WaitCPU(value, start + budget);
    elapsed = std::chrono::duration_cast<std::chrono::microseconds>(Clock::now() - start);
    return result;
}

std::string Ms(std::chrono::microseconds elapsed) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%.3f ms", static_cast<double>(elapsed.count()) / 1000.0);
    return buf;
}

/// Checks shared by both backends: a never-signalled fence times out at its one-second
/// deadline, a signalled fence returns `signaled`.
void CheckTimeoutAndSignal(IRHIDevice& device, const std::string& backend) {
    using namespace std::chrono_literals;
    std::chrono::microseconds elapsed{};

    IRHIFence* idle = device.CreateFence();
    Check(idle != nullptr, backend + " fence created");
    if (!idle) return;
    FenceWaitResult r = TimedWait(idle, 1, 1000ms, elapsed);
    Info(backend + " never-signalled wait: " + StatusName(r.status) + " after " +
         Ms(elapsed));
    Check(r.status == FenceWaitStatus::Timeout, backend + " never-signalled fence returns timeout",
          std::string("got ") + StatusName(r.status));
    Check(elapsed >= 1000ms && elapsed <= 1250ms,
          backend + " timeout returns at the one-second deadline",
          "returned after " + Ms(elapsed));

    idle->Signal(1);
    r = TimedWait(idle, 1, 5000ms, elapsed);
    Check(r.status == FenceWaitStatus::Signaled, backend + " signalled fence returns signaled",
          std::string("got ") + StatusName(r.status));
    Check(elapsed < 5000ms, backend + " signalled fence returns before the deadline",
          "returned after " + Ms(elapsed));
    device.DestroyFence(idle);
}

int RunFenceDX12() {
    using namespace std::chrono_literals;
    LogCapture log;
    auto device = CreateDevice(RHIBackend::DX12);
    if (!device) {
        Info("no DX12 device");
        return kExitSkip;
    }
    CheckTimeoutAndSignal(*device, "dx12");

    // Device loss: ID3D12Device5::RemoveDevice, then a wait on a never-signalled fence.
    auto* dx12 = static_cast<DX12Device*>(device.get());
    ComPtr<ID3D12Device5> device5;
    const HRESULT qi = dx12->GetDevice()->QueryInterface(IID_PPV_ARGS(&device5));
    Check(SUCCEEDED(qi), "dx12 ID3D12Device5 available", "QueryInterface hr=" + Hex(qi));
    if (FAILED(qi)) return 1;

    IRHIFence* pending = device->CreateFence();
    Check(pending != nullptr, "dx12 fence created before removal");
    if (!pending) return 1;
    device5->RemoveDevice();
    std::chrono::microseconds elapsed{};
    const FenceWaitResult r = TimedWait(pending, 1, 5000ms, elapsed);
    const HRESULT removed = dx12->GetDevice()->GetDeviceRemovedReason();
    Info("dx12 wait after RemoveDevice: " + std::string(StatusName(r.status)) + ", reason " +
         Hex(r.backendReason) + ", GetDeviceRemovedReason " + Hex(removed) + ", " +
         Ms(elapsed));
    Check(r.status == FenceWaitStatus::DeviceLost, "dx12 removed device returns device_lost",
          std::string("got ") + StatusName(r.status));
    Check(FAILED(static_cast<HRESULT>(r.backendReason)) && r.backendReason == removed,
          "dx12 device_lost carries the device-removed reason",
          "reason " + Hex(r.backendReason) + ", device reports " + Hex(removed));
    Check(elapsed < 5000ms, "dx12 device_lost returns before the deadline",
          "returned after " + Ms(elapsed));
    device->DestroyFence(pending);
    return g_failures == 0 ? 0 : 1;
}

/// Stand-in for vkWaitSemaphores installed in volk's function table.
VKAPI_ATTR VkResult VKAPI_CALL LostWaitSemaphores(VkDevice, const VkSemaphoreWaitInfo*, uint64_t) {
    return VK_ERROR_DEVICE_LOST;
}

int RunFenceVulkan() {
    using namespace std::chrono_literals;
    LogCapture log;
    auto device = CreateDevice(RHIBackend::Vulkan);
    if (!device) {
        Info("no Vulkan device");
        return kExitSkip;
    }
    CheckTimeoutAndSignal(*device, "vulkan");

    // Device loss: VK_ERROR_DEVICE_LOST injected through volk's global function table.
    IRHIFence* pending = device->CreateFence();
    Check(pending != nullptr, "vulkan fence created before injection");
    if (!pending) return 1;
    const PFN_vkWaitSemaphores original = vkWaitSemaphores;
    vkWaitSemaphores = &LostWaitSemaphores;
    std::chrono::microseconds elapsed{};
    const FenceWaitResult r = TimedWait(pending, 1, 5000ms, elapsed);
    vkWaitSemaphores = original;
    Info("vulkan wait with injected VK_ERROR_DEVICE_LOST: " + std::string(StatusName(r.status)) +
         ", reason " + std::to_string(r.backendReason));
    Check(r.status == FenceWaitStatus::DeviceLost, "vulkan VK_ERROR_DEVICE_LOST returns device_lost",
          std::string("got ") + StatusName(r.status));
    Check(r.backendReason == static_cast<int32_t>(VK_ERROR_DEVICE_LOST),
          "vulkan device_lost carries VK_ERROR_DEVICE_LOST",
          "reason " + std::to_string(r.backendReason));
    Check(elapsed < 5000ms, "vulkan device_lost returns before the deadline",
          "returned after " + Ms(elapsed));
    device->DestroyFence(pending);
    return g_failures == 0 ? 0 : 1;
}

// ── UZP-MOD-004 ──────────────────────────────────────────────────────────────

int RunRayQueryDecision() {
    struct Case {
        D3D12_RAYTRACING_TIER tier;
        D3D_SHADER_MODEL sm;
        bool expected;
        const char* name;
    };
    const Case cases[] = {
        {D3D12_RAYTRACING_TIER_1_1, D3D_SHADER_MODEL_6_6, true, "Tier 1.1 + SM 6.6"},
        {D3D12_RAYTRACING_TIER_1_1, D3D_SHADER_MODEL_6_8, true, "Tier 1.1 + SM 6.8"},
        {D3D12_RAYTRACING_TIER_1_0, D3D_SHADER_MODEL_6_6, false, "Tier 1.0 + SM 6.6"},
        {D3D12_RAYTRACING_TIER_1_0, D3D_SHADER_MODEL_6_8, false, "Tier 1.0 + SM 6.8"},
        {D3D12_RAYTRACING_TIER_NOT_SUPPORTED, D3D_SHADER_MODEL_6_6, false, "no DXR + SM 6.6"},
        {D3D12_RAYTRACING_TIER_1_1, D3D_SHADER_MODEL_6_5, false, "Tier 1.1 + SM 6.5"},
        {D3D12_RAYTRACING_TIER_1_1, D3D_SHADER_MODEL_6_0, false, "Tier 1.1 + SM 6.0"},
    };
    for (const Case& c : cases) {
        const bool got = DX12SupportsInlineRayQuery(c.tier, c.sm);
        Check(got == c.expected,
              std::string("ray query ") + (c.expected ? "reported for " : "not reported for ") + c.name,
              std::string("decision returned ") + (got ? "true" : "false"));
    }
    return g_failures == 0 ? 0 : 1;
}

// ── UZP-MOD-005 ──────────────────────────────────────────────────────────────

/// Paths of every module named D3D12Core.dll loaded in this process.
std::vector<std::filesystem::path> LoadedD3D12Core() {
    std::vector<std::filesystem::path> found;
    HMODULE modules[1024];
    DWORD needed = 0;
    if (!EnumProcessModules(GetCurrentProcess(), modules, sizeof(modules), &needed)) return found;
    const DWORD count = std::min<DWORD>(needed / sizeof(HMODULE), 1024);
    for (DWORD i = 0; i < count; ++i) {
        wchar_t path[MAX_PATH];
        if (GetModuleFileNameW(modules[i], path, MAX_PATH) == 0) continue;
        std::filesystem::path p(path);
        if (_wcsicmp(p.filename().c_str(), L"D3D12Core.dll") == 0) found.push_back(p);
    }
    return found;
}

/// "major.minor.build.revision" from a file's version resource, empty if it has none.
std::string FileVersion(const std::filesystem::path& file) {
    DWORD handle = 0;
    const DWORD size = GetFileVersionInfoSizeW(file.c_str(), &handle);
    if (size == 0) return {};
    std::vector<unsigned char> data(size);
    if (!GetFileVersionInfoW(file.c_str(), 0, size, data.data())) return {};
    VS_FIXEDFILEINFO* info = nullptr;
    UINT len = 0;
    if (!VerQueryValueW(data.data(), L"\\", reinterpret_cast<void**>(&info), &len) || !info) return {};
    return std::to_string(HIWORD(info->dwFileVersionMS)) + "." +
           std::to_string(LOWORD(info->dwFileVersionMS)) + "." +
           std::to_string(HIWORD(info->dwFileVersionLS)) + "." +
           std::to_string(LOWORD(info->dwFileVersionLS));
}

int RunAgility() {
    LogCapture log;
    const std::filesystem::path agilityDir = GetExeDir() / "D3D12";
    const std::filesystem::path agilityCore = agilityDir / "D3D12Core.dll";
    Check(std::filesystem::is_regular_file(agilityCore), "D3D12Core.dll is in D3D12\\ beside the exe",
          agilityCore.string() + " missing");
    Check(!std::filesystem::exists(GetExeDir() / "D3D12Core.dll"),
          "no D3D12Core.dll in the exe folder itself");

    // The loader's exports (dx12_agility.cpp) name the same folder as the device factory.
    HMODULE exe = GetModuleHandleW(nullptr);
    const auto* sdkPath = reinterpret_cast<const char* const*>(GetProcAddress(exe, "D3D12SDKPath"));
    const auto* sdkVersion = reinterpret_cast<const UINT*>(GetProcAddress(exe, "D3D12SDKVersion"));
    Check(sdkPath && std::string_view(*sdkPath) == ".\\D3D12\\", "exe exports D3D12SDKPath .\\D3D12\\",
          sdkPath ? std::string("exported ") + *sdkPath : "not exported");
    Check(sdkVersion && *sdkVersion == D3D12_SDK_VERSION, "exe exports D3D12SDKVersion",
          sdkVersion ? "exported " + std::to_string(*sdkVersion) : "not exported");

    auto device = CreateDevice(RHIBackend::DX12);
    if (!device) {
        Info("no DX12 device");
        return kExitSkip;
    }

    const std::string expectedLog = "Agility SDK loaded via CreateDeviceFactory (version=" +
                                    std::to_string(D3D12_SDK_VERSION) + ", path='" +
                                    (agilityDir.string() + "\\") + "')";
    Check(log.Contains(expectedLog), "device factory created from D3D12\\",
          "no log line \"" + expectedLog + "\"");
    Info("D3D12_SDK_VERSION " + std::to_string(D3D12_SDK_VERSION));

    bool fromSubfolder = false;
    for (const auto& path : LoadedD3D12Core()) {
        Info("loaded D3D12Core.dll: " + path.string() + " version " + FileVersion(path));
        std::error_code ec;
        if (std::filesystem::equivalent(path, agilityCore, ec)) {
            fromSubfolder = true;
            Info("AGILITY_VERSION " + FileVersion(path));
        }
    }
    Check(fromSubfolder, "Agility runtime loaded from D3D12\\D3D12Core.dll",
          "D3D12Core.dll from D3D12\\ is not loaded");
    return g_failures == 0 ? 0 : 1;
}

// ── UZP-MOD-006 ──────────────────────────────────────────────────────────────

constexpr const char* kPlainKernel = R"(
RWStructuredBuffer<uint> output : register(u0);

[numthreads(64, 1, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    output[id.x] = id.x * 2u + 1u;
}
)";

constexpr const char* kRayQueryKernel = R"(
RaytracingAccelerationStructure scene : register(t0);
RWStructuredBuffer<uint> hits : register(u0);

[numthreads(64, 1, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    RayDesc ray;
    ray.Origin = float3(float(id.x), 0.0f, -1.0f);
    ray.Direction = float3(0.0f, 0.0f, 1.0f);
    ray.TMin = 0.0f;
    ray.TMax = 100.0f;
    RayQuery<RAY_FLAG_NONE> query;
    query.TraceRayInline(scene, RAY_FLAG_NONE, 0xFF, ray);
    query.Proceed();
    hits[id.x] = query.CommittedStatus() == COMMITTED_TRIANGLE_HIT ? 1u : 0u;
}
)";

bool CompileTo(ShaderCompiler& compiler, const char* source, bool rayQuery,
               const std::filesystem::path& out, const std::string& name) {
    ShaderCompileDesc desc;
    desc.source = source;
    desc.sourceName = name + ".hlsl";
    desc.stage = ShaderStageCompile::Compute;
    desc.model = ShaderModelCompile::SM6_6;
    desc.output = ShaderOutputFormat::SPIRV;
    desc.enableRayQuery = rayQuery;
    const ShaderCompileResult result = compiler.Compile(desc);
    Check(result.success && !result.bytecode.empty(), name + " compiles to SPIR-V", result.errors);
    if (!result.success) return false;
    std::ofstream file(out, std::ios::binary);
    file.write(reinterpret_cast<const char*>(result.bytecode.data()),
               static_cast<std::streamsize>(result.bytecode.size()));
    Check(static_cast<bool>(file), name + " written", out.string());
    Info("SPIRV " + name + " " + out.string());
    return true;
}

int RunSpirv(const std::filesystem::path& outDir) {
    LogCapture log;
    ShaderCompiler compiler;
    const bool ready = compiler.Init("dxcompiler.dll");
    Check(ready, "DXC loads from beside the exe");
    if (!ready) return 1;
    Info("DXC " + compiler.GetVersion());
    std::filesystem::create_directories(outDir);
    CompileTo(compiler, kPlainKernel, false, outDir / "plain.spv", "plain");
    CompileTo(compiler, kRayQueryKernel, true, outDir / "rayquery.spv", "rayquery");
    return g_failures == 0 ? 0 : 1;
}

// ── UZP-MOD-008 ──────────────────────────────────────────────────────────────

/// DXC's interface ids, parsed from the `CROSS_PLATFORM_UUIDOF` strings of dxcapi.h (zig's
/// clang has no `__declspec(uuid)`; the same approach as shader_compiler.cpp).
constexpr uint8_t HexDigit(char c) {
    return (c >= '0' && c <= '9')   ? static_cast<uint8_t>(c - '0')
           : (c >= 'a' && c <= 'f') ? static_cast<uint8_t>(c - 'a' + 10)
           : (c >= 'A' && c <= 'F') ? static_cast<uint8_t>(c - 'A' + 10)
                                    : 0;
}
constexpr uint8_t HexPair(const char* s, int i) {
    return static_cast<uint8_t>(HexDigit(s[i]) << 4 | HexDigit(s[i + 1]));
}
constexpr GUID ParseGuid(const char* s) {
    uint32_t d1 = 0;
    for (int i = 0; i < 8; ++i) d1 = d1 << 4 | HexDigit(s[i]);
    uint16_t d2 = 0, d3 = 0;
    for (int i = 9; i < 13; ++i) d2 = static_cast<uint16_t>(d2 << 4 | HexDigit(s[i]));
    for (int i = 14; i < 18; ++i) d3 = static_cast<uint16_t>(d3 << 4 | HexDigit(s[i]));
    return GUID{d1, d2, d3,
                {HexPair(s, 19), HexPair(s, 21), HexPair(s, 24), HexPair(s, 26), HexPair(s, 28),
                 HexPair(s, 30), HexPair(s, 32), HexPair(s, 34)}};
}

} // namespace

#undef CROSS_PLATFORM_UUIDOF
#define CROSS_PLATFORM_UUIDOF(iface, spec) \
    struct iface;                          \
    static constexpr IID IID_##iface = ParseGuid(spec);
#include "dxcapi.h"

namespace {

/// One multiply-add DXC contracts or marks `fast` unless arithmetic is IEEE-strict.
constexpr const char* kFloatKernel = R"(
cbuffer Params : register(b0) {
    float g_a;
    float g_b;
    float g_c;
};
RWStructuredBuffer<float> output : register(u0);

[numthreads(64, 1, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    output[id.x] = g_a * float(id.x) + g_b * g_c;
}
)";

/// DXC's text disassembly of a DXIL container, empty when it cannot be produced.
std::string DisassembleDxil(const std::vector<uint8_t>& dxil) {
    HMODULE dxc = GetModuleHandleW(L"dxcompiler.dll");
    auto create = dxc ? reinterpret_cast<DxcCreateInstanceProc>(
                            reinterpret_cast<void*>(GetProcAddress(dxc, "DxcCreateInstance")))
                      : nullptr;
    IDxcCompiler3* compiler = nullptr;
    if (!create || FAILED(create(CLSID_DxcCompiler, IID_IDxcCompiler3,
                                 reinterpret_cast<void**>(&compiler)))) {
        return {};
    }
    std::string text;
    const DxcBuffer buffer{dxil.data(), dxil.size(), 0};
    IDxcResult* result = nullptr;
    if (SUCCEEDED(compiler->Disassemble(&buffer, IID_IDxcResult,
                                        reinterpret_cast<void**>(&result)))) {
        IDxcBlobUtf8* blob = nullptr;
        result->GetOutput(DXC_OUT_DISASSEMBLY, IID_IDxcBlobUtf8, reinterpret_cast<void**>(&blob),
                          nullptr);
        if (blob) {
            text.assign(blob->GetStringPointer(), blob->GetStringLength());
            blob->Release();
        }
        result->Release();
    }
    compiler->Release();
    return text;
}

void WriteFile(const std::filesystem::path& path, const void* data, size_t size) {
    std::ofstream file(path, std::ios::binary);
    file.write(static_cast<const char*>(data), static_cast<std::streamsize>(size));
    Check(static_cast<bool>(file), path.filename().string() + " written", path.string());
}

int RunIeee(const std::filesystem::path& outDir) {
    LogCapture log;
    ShaderCompiler compiler;
    const bool ready = compiler.Init("dxcompiler.dll");
    Check(ready, "DXC loads from beside the exe");
    if (!ready) return 1;
    std::filesystem::create_directories(outDir);
    for (const bool strict : {false, true}) {
        const std::string name = strict ? "ieee-on" : "ieee-off";
        ShaderCompileDesc desc;
        desc.source = kFloatKernel;
        desc.sourceName = name + ".hlsl";
        desc.stage = ShaderStageCompile::Compute;
        desc.model = ShaderModelCompile::SM6_6;
        desc.ieeeStrict = strict;
        for (const ShaderOutputFormat output :
             {ShaderOutputFormat::DXIL, ShaderOutputFormat::SPIRV}) {
            const bool dxil = output == ShaderOutputFormat::DXIL;
            desc.output = output;
            const ShaderCompileResult result = compiler.Compile(desc);
            const std::string target = dxil ? "DXIL" : "SPIR-V";
            Check(result.success && !result.bytecode.empty(), name + " compiles to " + target,
                  result.errors);
            if (!result.success) continue;
            WriteFile(outDir / (name + (dxil ? ".dxil" : ".spv")), result.bytecode.data(),
                      result.bytecode.size());
            if (dxil) {
                const std::string text = DisassembleDxil(result.bytecode);
                Check(!text.empty(), name + " DXIL disassembles");
                WriteFile(outDir / (name + ".dxil.txt"), text.data(), text.size());
            }
        }
    }
    return g_failures == 0 ? 0 : 1;
}

} // namespace

int main(int argc, char** argv) {
    const std::string_view mode = argc > 1 ? argv[1] : "";
    if (mode == "factory") return RunFactory();
    if (mode == "fence" && argc > 2 && std::string_view(argv[2]) == "dx12") return RunFenceDX12();
    if (mode == "fence" && argc > 2 && std::string_view(argv[2]) == "vulkan") return RunFenceVulkan();
    if (mode == "rayquery-decision") return RunRayQueryDecision();
    if (mode == "agility") return RunAgility();
    if (mode == "spirv" && argc > 2) return RunSpirv(argv[2]);
    if (mode == "ieee" && argc > 2) return RunIeee(argv[2]);
    std::fprintf(stderr,
                 "usage: uzp-vendor-tests factory | fence dx12|vulkan | rayquery-decision | "
                 "agility | spirv <out-dir> | ieee <out-dir>\n");
    return 2;
}
