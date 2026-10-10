// DX12 probes of `selftest`: inline ray queries on the hardware device and the WARP probe
// (probes.h).

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "probes.h"

#include "hardware_slice.h"

#include "dx12_device.h"
#include "dx12_guids.h"
#include "rhi.h"
#include "rhi_backend.h"
#include "rhi_config.h"

#include <windows.h>

#include <cstdio>
#include <memory>
#include <string>
#include <vector>

namespace uzp::selftest {

using Microsoft::WRL::ComPtr;

namespace {

/// The WARP adapter's PCI identity (Microsoft Basic Render Driver).
constexpr UINT kWarpVendorId = 0x1414;
constexpr UINT kWarpDeviceId = 0x008C;

std::string HexValue(uint32_t value) {
    char buf[16];
    std::snprintf(buf, sizeof(buf), "0x%08X", value);
    return buf;
}

std::string Narrow(const wchar_t* wide) {
    const int size = WideCharToMultiByte(CP_UTF8, 0, wide, -1, nullptr, 0, nullptr, nullptr);
    if (size <= 1) return {};
    std::string out(static_cast<size_t>(size - 1), '\0');
    WideCharToMultiByte(CP_UTF8, 0, wide, -1, out.data(), size, nullptr, nullptr);
    return out;
}

struct AdapterIdentity {
    std::string name;
    std::string driver = "unknown";
    bool software = false;
};

/// Name, user-mode driver version and software flag of the adapter a device was created on.
AdapterIdentity Identify(uz::DX12Device& device) {
    AdapterIdentity identity;
    LUID luid{};
    device.GetDevice()->GetAdapterLuid(&luid);
    ComPtr<IDXGIAdapter1> adapter;
    if (FAILED(device.GetFactory()->EnumAdapterByLuid(luid, IID_PPV_ARGS(&adapter)))) return identity;
    DXGI_ADAPTER_DESC1 desc{};
    adapter->GetDesc1(&desc);
    identity.name = Narrow(desc.Description);
    identity.software = (desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) != 0;
    LARGE_INTEGER umd{};
    if (SUCCEEDED(adapter->CheckInterfaceSupport(__uuidof(IDXGIDevice), &umd))) {
        const auto hi = static_cast<uint32_t>(umd.HighPart);
        const auto lo = static_cast<uint32_t>(umd.LowPart);
        identity.driver = std::to_string(hi >> 16) + "." + std::to_string(hi & 0xFFFF) + "." +
                          std::to_string(lo >> 16) + "." + std::to_string(lo & 0xFFFF);
    }
    return identity;
}

/// The highest shader model the device reports, probed from the top down as the vendored device
/// does (an older runtime rejects shader models it does not know).
D3D_SHADER_MODEL HighestShaderModel(ID3D12Device* device) {
    static constexpr D3D_SHADER_MODEL kProbe[] = {
        D3D_SHADER_MODEL_6_9, D3D_SHADER_MODEL_6_8, D3D_SHADER_MODEL_6_7, D3D_SHADER_MODEL_6_6,
        D3D_SHADER_MODEL_6_5, D3D_SHADER_MODEL_6_4, D3D_SHADER_MODEL_6_3, D3D_SHADER_MODEL_6_2,
        D3D_SHADER_MODEL_6_1, D3D_SHADER_MODEL_6_0, D3D_SHADER_MODEL_5_1,
    };
    for (const D3D_SHADER_MODEL probe : kProbe) {
        D3D12_FEATURE_DATA_SHADER_MODEL data{probe};
        if (SUCCEEDED(device->CheckFeatureSupport(D3D12_FEATURE_SHADER_MODEL, &data, sizeof(data)))) {
            return data.HighestShaderModel;
        }
    }
    return D3D_SHADER_MODEL_5_1;
}

/// The device's DXR tier; `hr` says whether the query succeeded.
D3D12_RAYTRACING_TIER RaytracingTier(ID3D12Device* device, HRESULT& hr) {
    D3D12_FEATURE_DATA_D3D12_OPTIONS5 options5{};
    hr = device->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS5, &options5, sizeof(options5));
    return SUCCEEDED(hr) ? options5.RaytracingTier : D3D12_RAYTRACING_TIER_NOT_SUPPORTED;
}

std::string LogLines() {
    std::string lines;
    for (const std::string& line : DrainLogProblems()) lines += (lines.empty() ? "" : " | ") + line;
    return lines.empty() ? "no render-core log line" : lines;
}

}  // namespace

// ── dx12-ray-query ───────────────────────────────────────────────────────────

ProbeReport ProbeDx12RayQuery(SelftestContext& context) {
    if (!context.device) {
        return NotCompleted("dx12-ray-query", "dx12",
                            "no DX12 hardware device: stage dx12-device did not pass");
    }
    auto& dx12 = static_cast<uz::DX12Device&>(*context.device);
    ID3D12Device* device = dx12.GetDevice();
    HRESULT hr = S_OK;
    const D3D12_RAYTRACING_TIER tier = RaytracingTier(device, hr);
    if (FAILED(hr)) {
        return NotCompleted("dx12-ray-query", "dx12",
                            "CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS5) failed, hr=" +
                                HexValue(static_cast<uint32_t>(hr)));
    }
    const AdapterIdentity adapter = Identify(dx12);
    ProbeReport report = EvaluateDx12RayQuery(static_cast<uint32_t>(tier),
                                              static_cast<uint32_t>(HighestShaderModel(device)),
                                              adapter.name, adapter.driver);
    report.facts.emplace_back("device_supports_inline_ray_query",
                              dx12.SupportsInlineRayQuery() ? "yes" : "no");
    report.facts.emplace_back("device_supports_ray_tracing", dx12.SupportsRayTracing() ? "yes" : "no");
    return report;
}

// ── warp ─────────────────────────────────────────────────────────────────────

namespace {

/// Index of the WARP adapter in the order the vendored device enumerates adapters
/// (`EnumAdapterByGpuPreference`, high performance); -1 when there is none.
int WarpAdapterIndex(std::string& error) {
    ComPtr<IDXGIFactory6> factory;
    const HRESULT hr = CreateDXGIFactory2(0, IID_PPV_ARGS(&factory));
    if (FAILED(hr)) {
        error = "CreateDXGIFactory2 failed, hr=" + HexValue(static_cast<uint32_t>(hr));
        return -1;
    }
    for (UINT i = 0;; ++i) {
        ComPtr<IDXGIAdapter1> adapter;
        if (FAILED(factory->EnumAdapterByGpuPreference(i, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,
                                                       IID_PPV_ARGS(&adapter)))) {
            break;
        }
        DXGI_ADAPTER_DESC1 desc{};
        adapter->GetDesc1(&desc);
        if ((desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) != 0 && desc.VendorId == kWarpVendorId &&
            desc.DeviceId == kWarpDeviceId) {
            return static_cast<int>(i);
        }
    }
    error = "DXGI enumerates no WARP adapter (Microsoft Basic Render Driver, vendor 0x1414, "
            "device 0x008C)";
    return -1;
}

/// The capabilities of the WARP device that matter to UzPainter's compute path, each either
/// supported or unsupported with the value WARP reports.
void RecordWarpCapabilities(uz::DX12Device& dx12, ProbeReport& report) {
    ID3D12Device* device = dx12.GetDevice();
    auto add = [&report](bool ok, const std::string& item, const std::string& value) {
        if (ok) {
            // The value is shown only when it adds to the item ("DXR Tier 1.1 (Tier 1.2)").
            const bool plain = value == "supported" || item.find(value) != std::string::npos;
            report.supported.push_back(plain ? item : item + " (" + value + ")");
        } else {
            report.unsupported.push_back({item, "WARP reports " + value});
        }
    };
    report.supported.push_back(std::string("feature level ") + dx12.GetFeatureLevel());
    const D3D_SHADER_MODEL highest = HighestShaderModel(device);
    add(highest >= D3D_SHADER_MODEL_6_6, "Shader Model 6.6",
        "highest shader model " + ShaderModelName(static_cast<uint32_t>(highest)));

    D3D12_FEATURE_DATA_D3D12_OPTIONS options{};
    if (SUCCEEDED(device->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS, &options, sizeof(options)))) {
        add(options.ResourceBindingTier >= D3D12_RESOURCE_BINDING_TIER_3, "resource binding tier 3",
            "tier " + std::to_string(static_cast<int>(options.ResourceBindingTier)));
        add(options.TypedUAVLoadAdditionalFormats != 0, "typed UAV loads of additional formats",
            options.TypedUAVLoadAdditionalFormats ? "supported" : "not supported");
    }
    D3D12_FEATURE_DATA_D3D12_OPTIONS1 options1{};
    if (SUCCEEDED(device->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS1, &options1, sizeof(options1)))) {
        add(options1.WaveOps != 0, "wave operations",
            options1.WaveOps ? "lanes " + std::to_string(options1.WaveLaneCountMin) + "-" +
                                   std::to_string(options1.WaveLaneCountMax)
                             : "not supported");
    }
    D3D12_FEATURE_DATA_D3D12_OPTIONS4 options4{};
    if (SUCCEEDED(device->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS4, &options4, sizeof(options4)))) {
        add(options4.Native16BitShaderOpsSupported != 0, "native 16-bit shader operations",
            options4.Native16BitShaderOpsSupported ? "supported" : "not supported");
    }
    HRESULT hr = S_OK;
    const D3D12_RAYTRACING_TIER tier = RaytracingTier(device, hr);
    if (SUCCEEDED(hr)) {
        add(tier >= D3D12_RAYTRACING_TIER_1_1, "DXR Tier 1.1", DxrTierName(tier));
        add(dx12.SupportsInlineRayQuery(), "inline ray queries (DXR Tier 1.1 + SM 6.6)",
            dx12.SupportsInlineRayQuery() ? "supported" : "not supported");
    }
    D3D12_FEATURE_DATA_FORMAT_SUPPORT r16{DXGI_FORMAT_R16_FLOAT, {}, {}};
    if (SUCCEEDED(device->CheckFeatureSupport(D3D12_FEATURE_FORMAT_SUPPORT, &r16, sizeof(r16)))) {
        const bool store = (r16.Support2 & D3D12_FORMAT_SUPPORT2_UAV_TYPED_STORE) != 0;
        add(store, "R16_FLOAT typed UAV store", store ? "supported" : "not supported");
    }
}

}  // namespace

ProbeReport ProbeWarp(SelftestContext& context) {
    ProbeReport report;
    report.probe = "warp";
    report.backend = "dx12-warp";
    report.completed = true;
    std::vector<WarpCheck> checks = {{"dx12-device"}, {"shader-compile"}, {"compute-readback"},
                                     {"png16"}};
    WarpCheck& deviceCheck = checks[0];
    WarpCheck& compileCheck = checks[1];
    WarpCheck& readbackCheck = checks[2];
    WarpCheck& pngCheck = checks[3];
    auto notRun = [](WarpCheck& check, const std::string& needed) {
        check.status = CheckStatus::NotRun;
        check.detail = "needs check " + needed + ", which did not pass";
    };

    // dx12-device: the vendored DX12 device on the WARP adapter.
    std::string error;
    const int index = WarpAdapterIndex(error);
    std::unique_ptr<uz::IRHIDevice> device;
    if (index < 0) {
        deviceCheck = {"dx12-device", CheckStatus::Failed, error};
    } else {
        uz::RHIDeviceDesc desc;
        desc.backend = uz::RHIBackend::DX12;
        desc.adapterIndex = static_cast<uint32_t>(index);
        DrainLogProblems();
        device = uz::CreateRHIDevice(desc);
        if (!device) {
            deviceCheck = {"dx12-device", CheckStatus::Failed,
                           "DX12 device creation on the WARP adapter failed: " + LogLines()};
        }
    }
    uz::DX12Device* dx12 = device ? static_cast<uz::DX12Device*>(device.get()) : nullptr;
    if (dx12) {
        const AdapterIdentity adapter = Identify(*dx12);
        report.adapter = adapter.name;
        report.driver = adapter.driver;
        report.facts = {{"adapter_index", std::to_string(index)},
                        {"feature_level", dx12->GetFeatureLevel()},
                        {"shader_model", uz::ShaderModelToString(dx12->GetShaderModel())}};
        if (!adapter.software) {
            deviceCheck = {"dx12-device", CheckStatus::Failed,
                           "the device was created on " + adapter.name + ", not on WARP"};
        } else {
            deviceCheck = {"dx12-device", CheckStatus::Passed,
                           adapter.name + ", feature level " + dx12->GetFeatureLevel()};
            RecordWarpCapabilities(*dx12, report);
        }
    }
    const bool deviceOk = deviceCheck.status == CheckStatus::Passed;

    // shader-compile: the slice's cs_6_6 DXIL (compiled by DXC on the CPU in stage shader-compile)
    // is usable on WARP when WARP's shader model reaches 6.6.
    if (context.kernelDxil.empty()) {
        compileCheck = {"shader-compile", CheckStatus::NotRun,
                        "stage shader-compile produced no DXIL kernel"};
    } else if (!deviceOk) {
        notRun(compileCheck, "dx12-device");
    } else {
        const D3D_SHADER_MODEL highest = HighestShaderModel(dx12->GetDevice());
        const std::string detail = "cs_6_6 DXIL, " + std::to_string(context.kernelDxil.size()) +
                                   " bytes; WARP highest shader model " +
                                   ShaderModelName(static_cast<uint32_t>(highest));
        compileCheck = {"shader-compile",
                        highest >= D3D_SHADER_MODEL_6_6 ? CheckStatus::Passed : CheckStatus::Failed,
                        detail};
    }

    // compute-readback: the DXIL kernel dispatched on WARP, the pattern read back bit for bit.
    std::vector<uint16_t> pattern;
    bool unrecoverable = false;
    if (compileCheck.status != CheckStatus::Passed) {
        notRun(readbackCheck, "shader-compile");
    } else {
        DrainLogProblems();
        const StageOutcome outcome =
            DispatchPattern16(*device, context.kernelDxil, unrecoverable, pattern);
        readbackCheck.status =
            outcome.status == StageStatus::Passed ? CheckStatus::Passed : CheckStatus::Failed;
        readbackCheck.detail = outcome.status == StageStatus::Passed
                                   ? std::to_string(kPatternWidth) + "x" +
                                         std::to_string(kPatternHeight) +
                                         " R16_FLOAT pattern read back, 0 mismatches"
                                   : outcome.reason;
    }

    // png16: the WARP readback written as a 16-bit PNG and decoded back equal.
    if (readbackCheck.status != CheckStatus::Passed) {
        notRun(pngCheck, "compute-readback");
    } else {
        const auto file = context.options.outDir / "selftest-warp-pattern16.png";
        const StageOutcome outcome = Png16RoundTrip(pattern, "warp-readback", file);
        pngCheck.status =
            outcome.status == StageStatus::Passed ? CheckStatus::Passed : CheckStatus::Failed;
        pngCheck.detail = outcome.status == StageStatus::Passed
                              ? "16-bit grayscale PNG decoded back equal (" + file.filename().string() + ")"
                              : outcome.reason;
    }

    ConcludeWarp(report, checks);
    if (unrecoverable) {
        // A timed-out or lost device is not torn down (its teardown waits for it); the run ends
        // right after the report is written.
        static_cast<void>(device.release());
        context.gpuUnrecoverable = true;
    }
    return report;
}

}  // namespace uzp::selftest
