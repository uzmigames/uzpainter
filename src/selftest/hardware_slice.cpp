// DX12 hardware slice of `selftest`: device, run-time shader compilation and compute readback
// (hardware_slice.h). The PNG and Embree stages are in png16.cpp and embree_stage.cpp.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "hardware_slice.h"

#include "dx12_device.h"
#include "dx12_guids.h"
#include "rhi.h"
#include "rhi_backend.h"
#include "rhi_config.h"
#include "shader_compiler.h"

#include <windows.h>
#include <psapi.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <string>

namespace uzp::selftest {

namespace fs = std::filesystem;
using Microsoft::WRL::ComPtr;

std::vector<uint16_t> ExpectedPattern() {
    std::vector<uint16_t> pattern(static_cast<size_t>(kPatternWidth) * kPatternHeight);
    for (uint32_t y = 0; y < kPatternHeight; ++y) {
        for (uint32_t x = 0; x < kPatternWidth; ++x) {
            pattern[static_cast<size_t>(y) * kPatternWidth + x] = PatternValue(x, y);
        }
    }
    return pattern;
}

void RegisterHardwareSlice(Selftest& selftest) {
    selftest.Add({"dx12-device", true, true, true, {}, RunDx12Device});
    selftest.Add({"shader-compile", true, false, true, {}, RunShaderCompile});
    selftest.Add({"compute-readback", true, true, true, {"dx12-device", "shader-compile"},
                  RunComputeReadback});
    selftest.Add({"png16", true, false, true, {}, RunPng16});
    selftest.Add({"embree", true, false, true, {}, RunEmbree});
}

void TeardownHardwareSlice(SelftestContext& context) { context.device.reset(); }

namespace {

/// The compute kernel of the slice. One source for both targets: the UAV is bound through the
/// render core's UAV descriptor table (root parameter 4, u0) and the size through its root
/// constants (root parameter 0, b0), so no DX12-only bindless syntax is needed for SPIR-V.
constexpr const char* kPatternKernel = R"(
cbuffer Params : register(b0) {
    uint g_width;
    uint g_height;
};
RWTexture2D<float> g_output : register(u0);

// Same function as PatternValue in hardware_slice.h.
uint PatternValue(uint x, uint y) {
    uint v = (x * 0x9E37u + y * 0x7F4Au + 0x1234u) & 0xFFFFu;
    if (((v >> 10) & 0x1Fu) == 0x1Fu) v ^= 0x4000u;
    return v;
}

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    if (id.x >= g_width || id.y >= g_height) return;
    g_output[id.xy] = f16tof32(PatternValue(id.x, id.y));
}
)";

constexpr uint32_t kRootConstantsParam = 0;
constexpr uint32_t kUavTableParam = 4;
constexpr auto kGpuDeadline = std::chrono::seconds(10);

std::string Hex(uint32_t value, int digits = 8) {
    char buf[16];
    std::snprintf(buf, sizeof(buf), "0x%0*X", digits, value);
    return buf;
}

std::string Utf8(const std::wstring& wide) {
    if (wide.empty()) return {};
    const int size = WideCharToMultiByte(CP_UTF8, 0, wide.data(), static_cast<int>(wide.size()),
                                         nullptr, 0, nullptr, nullptr);
    std::string out(static_cast<size_t>(size), '\0');
    WideCharToMultiByte(CP_UTF8, 0, wide.data(), static_cast<int>(wide.size()), out.data(), size,
                        nullptr, nullptr);
    return out;
}

/// Paths of every loaded module whose file name is `name` (case-insensitive).
std::vector<fs::path> LoadedModules(const wchar_t* name) {
    std::vector<fs::path> found;
    HMODULE modules[1024];
    DWORD needed = 0;
    if (!EnumProcessModules(GetCurrentProcess(), modules, sizeof(modules), &needed)) return found;
    const DWORD count = std::min<DWORD>(needed / sizeof(HMODULE), 1024);
    for (DWORD i = 0; i < count; ++i) {
        wchar_t path[MAX_PATH];
        if (GetModuleFileNameW(modules[i], path, MAX_PATH) == 0) continue;
        fs::path p(path);
        if (_wcsicmp(p.filename().c_str(), name) == 0) found.push_back(p);
    }
    return found;
}

/// "a.b.c.d" from a file's version resource, empty if it has none.
std::string FileVersion(const fs::path& file) {
    DWORD handle = 0;
    const DWORD size = GetFileVersionInfoSizeW(file.c_str(), &handle);
    if (size == 0) return {};
    std::vector<unsigned char> data(size);
    if (!GetFileVersionInfoW(file.c_str(), 0, size, data.data())) return {};
    VS_FIXEDFILEINFO* info = nullptr;
    UINT len = 0;
    if (!VerQueryValueW(data.data(), L"\\", reinterpret_cast<void**>(&info), &len) || !info) {
        return {};
    }
    return std::to_string(HIWORD(info->dwFileVersionMS)) + "." +
           std::to_string(LOWORD(info->dwFileVersionMS)) + "." +
           std::to_string(HIWORD(info->dwFileVersionLS)) + "." +
           std::to_string(LOWORD(info->dwFileVersionLS));
}

std::string Paths(const std::vector<fs::path>& paths) {
    if (paths.empty()) return "none";
    std::string out;
    for (const auto& p : paths) out += (out.empty() ? "" : ", ") + p.string();
    return out;
}

}  // namespace

// ── dx12-device ──────────────────────────────────────────────────────────────

StageOutcome RunDx12Device(SelftestContext& context) {
    const fs::path agility = context.exeDir / "D3D12" / "D3D12Core.dll";
    if (!fs::is_regular_file(agility)) {
        return StageOutcome::Fail(
            "Agility SDK runtime missing: " + agility.string() +
            " not found (the DX12 device needs D3D12Core.dll of the Agility SDK, "
            "D3D12_SDK_VERSION " + std::to_string(D3D12_SDK_VERSION) +
            ", in the D3D12 folder beside UzPainter.exe)");
    }

    // The D3D12 loader reads these exports from the executable (dx12_agility.cpp).
    HMODULE exe = GetModuleHandleW(nullptr);
    const auto* sdkPath = reinterpret_cast<const char* const*>(
        reinterpret_cast<void*>(GetProcAddress(exe, "D3D12SDKPath")));
    const auto* sdkVersion = reinterpret_cast<const UINT*>(
        reinterpret_cast<void*>(GetProcAddress(exe, "D3D12SDKVersion")));
    if (!sdkPath || !sdkVersion || std::strcmp(*sdkPath, ".\\D3D12\\") != 0 ||
        *sdkVersion != D3D12_SDK_VERSION) {
        return StageOutcome::Fail(
            "UzPainter.exe does not export D3D12SDKPath \".\\D3D12\\\" and D3D12SDKVersion " +
            std::to_string(D3D12_SDK_VERSION) + " (dx12_agility.cpp not linked into the exe)");
    }

    uz::RHIDeviceDesc desc;
    desc.backend = uz::RHIBackend::DX12;
    desc.adapterIndex = 0;  // the high-performance adapter first (DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE)
    std::unique_ptr<uz::IRHIDevice> device = uz::CreateRHIDevice(desc);
    if (!device) {
        return StageOutcome::Fail(
            "DX12 device creation failed on the high-performance adapter (render core log below)");
    }
    auto* dx12 = static_cast<uz::DX12Device*>(device.get());

    ComPtr<IDXGIAdapter1> adapter;
    // DirectX-Headers declare the struct-returning methods in their out-parameter form for
    // non-MSVC compilers (the ABI MSVC uses for them).
    LUID luid{};
    dx12->GetDevice()->GetAdapterLuid(&luid);
    HRESULT hr = dx12->GetFactory()->EnumAdapterByLuid(luid, IID_PPV_ARGS(&adapter));
    if (FAILED(hr)) {
        return StageOutcome::Fail("EnumAdapterByLuid failed, hr=" + Hex(static_cast<uint32_t>(hr)));
    }
    DXGI_ADAPTER_DESC1 adapterDesc{};
    adapter->GetDesc1(&adapterDesc);
    LARGE_INTEGER umd{};
    std::string driver = "unknown";
    if (SUCCEEDED(adapter->CheckInterfaceSupport(__uuidof(IDXGIDevice), &umd))) {
        const auto hi = static_cast<uint32_t>(umd.HighPart);
        const auto lo = static_cast<uint32_t>(umd.LowPart);
        driver = std::to_string(hi >> 16) + "." + std::to_string(hi & 0xFFFF) + "." +
                 std::to_string(lo >> 16) + "." + std::to_string(lo & 0xFFFF);
    }

    Details details = {
        {"adapter", Utf8(adapterDesc.Description)},
        {"vendor_id", Hex(adapterDesc.VendorId, 4)},
        {"device_id", Hex(adapterDesc.DeviceId, 4)},
        {"dedicated_video_memory_mb",
         std::to_string(adapterDesc.DedicatedVideoMemory / (1024 * 1024))},
        {"driver_version", driver},
        {"feature_level", device->GetFeatureLevel()},
        {"shader_model", uz::ShaderModelToString(device->GetShaderModel())},
        {"agility_sdk_version", std::to_string(D3D12_SDK_VERSION)},
    };
    if ((adapterDesc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) != 0) {
        return StageOutcome::Fail("the selected adapter is a software adapter, not hardware",
                                  details);
    }

    const std::vector<fs::path> cores = LoadedModules(L"D3D12Core.dll");
    bool fromAgility = false;
    for (const fs::path& core : cores) {
        std::error_code ec;
        if (fs::equivalent(core, agility, ec)) fromAgility = true;
    }
    details.emplace_back("d3d12core_loaded", Paths(cores));
    if (!fromAgility) {
        return StageOutcome::Fail("Agility SDK runtime not loaded from " + agility.string() +
                                      " (D3D12Core.dll loaded: " + Paths(cores) + ")",
                                  details);
    }
    details.emplace_back("agility_runtime_file_version", FileVersion(agility));

    context.device = std::move(device);
    return StageOutcome::Pass(std::move(details));
}

// ── shader-compile ───────────────────────────────────────────────────────────

StageOutcome RunShaderCompile(SelftestContext& context) {
    const fs::path dxc = context.exeDir / "dxcompiler.dll";
    uz::ShaderCompiler compiler;
    if (!compiler.Init(dxc.string())) {
        return StageOutcome::Fail("DXC failed to load from " + dxc.string());
    }
    Details details = {{"dxc_version", compiler.GetVersion()},
                       {"dxcompiler", dxc.string()},
                       {"dxcompiler_file_version", FileVersion(dxc)},
                       {"profile", "cs_6_6"}};

    uz::ShaderCompileDesc desc;
    desc.source = kPatternKernel;
    desc.sourceName = "selftest_pattern16.hlsl";
    desc.stage = uz::ShaderStageCompile::Compute;
    desc.model = uz::ShaderModelCompile::SM6_6;

    desc.output = uz::ShaderOutputFormat::DXIL;
    uz::ShaderCompileResult dxil = compiler.Compile(desc);
    if (!dxil.success || dxil.bytecode.size() < 4 ||
        std::memcmp(dxil.bytecode.data(), "DXBC", 4) != 0) {
        return StageOutcome::Fail("HLSL to DXIL failed: " +
                                      (dxil.errors.empty() ? "no DXIL container" : dxil.errors),
                                  details);
    }
    details.emplace_back("dxil_bytes", std::to_string(dxil.bytecode.size()));

    desc.output = uz::ShaderOutputFormat::SPIRV;
    uz::ShaderCompileResult spirv = compiler.Compile(desc);
    uint32_t magic = 0;
    if (spirv.success && spirv.bytecode.size() >= 4) {
        std::memcpy(&magic, spirv.bytecode.data(), 4);
    }
    if (!spirv.success || magic != 0x07230203u) {
        return StageOutcome::Fail("HLSL to SPIR-V failed: " +
                                      (spirv.errors.empty() ? "no SPIR-V module" : spirv.errors),
                                  details);
    }
    details.emplace_back("spirv_bytes", std::to_string(spirv.bytecode.size()));
    // Whether DXC loaded the external validator, measured for the DXC row of 13 §5.
    details.emplace_back("dxil_dll_loaded", Paths(LoadedModules(L"dxil.dll")));

    context.kernelDxil = std::move(dxil.bytecode);
    context.kernelSpirv = std::move(spirv.bytecode);
    return StageOutcome::Pass(std::move(details));
}

// ── compute-readback ─────────────────────────────────────────────────────────

namespace {

/// The slice's GPU objects, destroyed in reverse order unless the GPU is unrecoverable.
struct ComputeObjects {
    uz::IRHIDevice& device;
    bool& unrecoverable;
    uz::RHITextureHandle texture = uz::RHITextureHandle::Invalid();
    uz::RHIShaderHandle shader = uz::RHIShaderHandle::Invalid();
    uz::RHIPipelineHandle pipeline = uz::RHIPipelineHandle::Invalid();
    uz::RHIBufferHandle readback = uz::RHIBufferHandle::Invalid();
    uz::IRHICommandList* commands = nullptr;
    uz::IRHIFence* fence = nullptr;

    ~ComputeObjects() {
        if (unrecoverable) return;
        if (fence) device.DestroyFence(fence);
        if (commands) device.DestroyCommandList(commands);
        if (readback.IsValid()) device.DestroyBuffer(readback);
        if (pipeline.IsValid()) device.DestroyPipeline(pipeline);
        if (shader.IsValid()) device.DestroyShader(shader);
        if (texture.IsValid()) device.DestroyTexture(texture);
    }
};

const char* WaitStatusName(uz::FenceWaitStatus status) {
    switch (status) {
        case uz::FenceWaitStatus::Signaled:   return "signaled";
        case uz::FenceWaitStatus::Timeout:    return "timeout";
        case uz::FenceWaitStatus::DeviceLost: return "device_lost";
    }
    return "unknown";
}

}  // namespace

StageOutcome RunComputeReadback(SelftestContext& context) {
    std::vector<uint16_t> data;
    StageOutcome outcome =
        DispatchPattern16(*context.device, context.kernelDxil, context.gpuUnrecoverable, data);
    if (outcome.status == StageStatus::Passed) context.readback = std::move(data);
    return outcome;
}

StageOutcome DispatchPattern16(uz::IRHIDevice& device, const std::vector<uint8_t>& kernelDxil,
                               bool& unrecoverable, std::vector<uint16_t>& pattern) {
    ComputeObjects gpu{device, unrecoverable};

    uz::RHITextureDesc textureDesc;
    textureDesc.width = kPatternWidth;
    textureDesc.height = kPatternHeight;
    textureDesc.format = uz::RHIFormat::R16Float;
    textureDesc.usage = uz::RHITextureUsage::UnorderedAccess | uz::RHITextureUsage::CopySrc;
    textureDesc.debugName = "selftest_pattern16";
    gpu.texture = device.CreateTexture(textureDesc);
    const uint32_t uav = gpu.texture.IsValid() ? device.GetTextureUAVIndex(gpu.texture) : UINT32_MAX;
    if (uav == UINT32_MAX) return StageOutcome::Fail("R16_FLOAT texture with a UAV not created");

    uz::RHIShaderDesc shaderDesc;
    shaderDesc.bytecode = kernelDxil.data();
    shaderDesc.bytecodeSize = kernelDxil.size();
    shaderDesc.stage = uz::RHIShaderStage::Compute;
    shaderDesc.debugName = "selftest_pattern16";
    gpu.shader = device.CreateShader(shaderDesc);
    uz::RHIComputePipelineDesc pipelineDesc;
    pipelineDesc.computeShader = gpu.shader;
    pipelineDesc.debugName = "selftest_pattern16";
    gpu.pipeline = gpu.shader.IsValid() ? device.CreateComputePipeline(pipelineDesc)
                                        : uz::RHIPipelineHandle::Invalid();
    if (!gpu.pipeline.IsValid()) return StageOutcome::Fail("compute pipeline from the DXIL not created");

    // Readback rows are laid out with D3D12's 256-byte row pitch alignment.
    const uint32_t rowBytes = kPatternWidth * sizeof(uint16_t);
    const uint32_t rowPitch = (rowBytes + D3D12_TEXTURE_DATA_PITCH_ALIGNMENT - 1) /
                              D3D12_TEXTURE_DATA_PITCH_ALIGNMENT *
                              D3D12_TEXTURE_DATA_PITCH_ALIGNMENT;
    uz::RHIBufferDesc bufferDesc;
    bufferDesc.sizeBytes = static_cast<uint64_t>(rowPitch) * kPatternHeight;
    bufferDesc.usage = uz::RHIBufferUsage::CopyDst;
    bufferDesc.memory = uz::RHIMemoryType::Readback;
    bufferDesc.debugName = "selftest_readback";
    gpu.readback = device.CreateBuffer(bufferDesc);
    gpu.commands = device.CreateCommandList(uz::RHIQueueType::Graphics);
    gpu.fence = device.CreateFence();
    if (!gpu.readback.IsValid() || !gpu.commands || !gpu.fence) {
        return StageOutcome::Fail("readback buffer, command list or fence not created");
    }

    const uint32_t constants[2] = {kPatternWidth, kPatternHeight};
    uz::IRHICommandList& cmd = *gpu.commands;
    cmd.Begin();
    uz::RHIBarrierDesc toUav{gpu.texture, uz::RHIBufferHandle::Invalid(),
                             uz::RHIResourceState::Common, uz::RHIResourceState::UnorderedAccess};
    cmd.ResourceBarrier(&toUav, 1);
    cmd.SetPipeline(gpu.pipeline);
    cmd.SetRootConstants(kRootConstantsParam, constants, 2);
    cmd.SetDescriptorTable(kUavTableParam, uav);
    cmd.Dispatch((kPatternWidth + 7) / 8, (kPatternHeight + 7) / 8, 1);
    uz::RHIBarrierDesc toCopy{gpu.texture, uz::RHIBufferHandle::Invalid(),
                              uz::RHIResourceState::UnorderedAccess, uz::RHIResourceState::CopySrc};
    cmd.ResourceBarrier(&toCopy, 1);
    cmd.CopyTextureToBuffer(gpu.texture, 0, gpu.readback, 0, rowPitch);
    cmd.End();
    cmd.Execute();
    gpu.fence->Signal(1);
    const uz::FenceWaitResult wait =
        gpu.fence->WaitCPU(1, std::chrono::steady_clock::now() + kGpuDeadline);
    Details details = {{"width", std::to_string(kPatternWidth)},
                       {"height", std::to_string(kPatternHeight)},
                       {"format", "R16_FLOAT"},
                       {"row_pitch", std::to_string(rowPitch)},
                       {"fence_wait", WaitStatusName(wait.status)}};
    if (wait.status != uz::FenceWaitStatus::Signaled) {
        unrecoverable = true;
        return StageOutcome::Fail(std::string("GPU work did not complete: fence wait ") +
                                      WaitStatusName(wait.status) + ", backend reason " +
                                      Hex(static_cast<uint32_t>(wait.backendReason)),
                                  details);
    }

    const auto* mapped = static_cast<const unsigned char*>(device.MapBuffer(gpu.readback));
    if (!mapped) return StageOutcome::Fail("readback buffer not mapped", details);
    std::vector<uint16_t> data(static_cast<size_t>(kPatternWidth) * kPatternHeight);
    for (uint32_t y = 0; y < kPatternHeight; ++y) {
        std::memcpy(&data[static_cast<size_t>(y) * kPatternWidth],
                    mapped + static_cast<size_t>(y) * rowPitch, rowBytes);
    }
    device.UnmapBuffer(gpu.readback);

    const std::vector<uint16_t> expected = ExpectedPattern();
    size_t mismatches = 0;
    std::string first;
    for (size_t i = 0; i < data.size(); ++i) {
        if (data[i] == expected[i]) continue;
        if (mismatches++ == 0) {
            first = "first at (" + std::to_string(i % kPatternWidth) + ", " +
                    std::to_string(i / kPatternWidth) + "): got " + Hex(data[i], 4) +
                    ", expected " + Hex(expected[i], 4);
        }
    }
    details.emplace_back("mismatches", std::to_string(mismatches));
    if (mismatches != 0) {
        return StageOutcome::Fail(std::to_string(mismatches) +
                                      " read-back values differ from the pattern; " + first,
                                  details);
    }
    pattern = std::move(data);
    return StageOutcome::Pass(std::move(details));
}

}  // namespace uzp::selftest
