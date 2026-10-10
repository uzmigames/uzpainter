"""Check (d) of `13-engine-integration.md` §3.1: the upstream behaviours cited in §2.2, §2.3 and
§3.4, each pinned to a line range and a pattern that must occur inside it.

These citations describe upstream files at the candidate commit; they are checked against an
exported upstream tree, not against the vendored folder (whose files later modifications change).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Citation:
    """`path:start-end` (root-relative, 1-based, inclusive) must contain `pattern` (regex)."""

    section: str
    path: str
    start: int
    end: int
    pattern: str
    behaviour: str

    @property
    def location(self) -> str:
        span = f"{self.start}" if self.start == self.end else f"{self.start}-{self.end}"
        return f"{self.path}:{span}"


CITATIONS: tuple[Citation, ...] = (
    Citation(
        "2.2",
        "engine/rhi/rhi_config.cpp",
        139,
        139,
        r"RHIConfig ResolveRHIConfig\(const Config& config\)",
        "ResolveRHIConfig(const Config&) pulls in engine config",
    ),
    Citation(
        "2.2",
        "engine/rhi/rhi_factory.cpp",
        13,
        24,
        r'#include "dx11/dx11_device\.h"[\s\S]*#include "metal/metal_device\.h"',
        "factory includes the DX11 and Metal backends",
    ),
    Citation(
        "2.2",
        "engine/rhi/dx12/dx12_device.h",
        31,
        31,
        r"#include <tracy/TracyD3D12\.hpp>",
        "Tracy D3D12 header included unconditionally",
    ),
    Citation(
        "2.2",
        "engine/rhi/dx12/dx12_swapchain.cpp",
        15,
        15,
        r"#include <tracy/TracyD3D12\.hpp>",
        "Tracy D3D12 header included unconditionally",
    ),
    Citation(
        "2.2",
        "engine/profiling/profiler.h",
        49,
        49,
        r"#if defined\(UZ_PROFILING_ENABLED\)",
        "profiling macros compile to stubs without UZ_PROFILING_ENABLED",
    ),
    Citation(
        "2.3",
        "engine/rhi/dx12/dx12_command_list.cpp",
        887,
        887,
        r"void DX12CommandList::CopyTextureToBuffer\(",
        "DX12 texture-to-buffer copy",
    ),
    Citation(
        "2.3",
        "engine/rhi/rhi_command_list.h",
        386,
        387,
        r"256 bytes for DX12",
        "readback row pitch must be 256-byte aligned on DX12",
    ),
    Citation(
        "2.3",
        "engine/rhi/dx12/dx12_device.cpp",
        1036,
        1036,
        r"void\* DX12Device::MapBuffer\(",
        "DX12 buffer map",
    ),
    Citation(
        "2.3",
        "engine/rhi/vulkan/vulkan_command_list.cpp",
        1141,
        1141,
        r"void VulkanCommandList::CopyTextureToBuffer\(",
        "Vulkan texture-to-buffer copy",
    ),
    Citation(
        "2.3",
        "engine/rhi/vulkan/vulkan_resources.cpp",
        157,
        157,
        r"void\* VulkanDevice::MapBuffer\(",
        "Vulkan buffer map",
    ),
    Citation(
        "2.3",
        "engine/rhi/dx12/dx12_device.cpp",
        1558,
        1558,
        r"RHIBLASHandle DX12Device::CreateBLAS\(",
        "DX12 BLAS creation",
    ),
    Citation(
        "2.3",
        "engine/rhi/dx12/dx12_device.cpp",
        1691,
        1691,
        r"RHITLASHandle DX12Device::CreateTLAS\(",
        "DX12 TLAS creation",
    ),
    Citation(
        "2.3",
        "engine/rhi/dx12/dx12_command_list.cpp",
        1093,
        1093,
        r"void DX12CommandList::BuildBLAS\(",
        "DX12 BLAS build",
    ),
    Citation(
        "2.3",
        "engine/rhi/dx12/dx12_command_list.cpp",
        1131,
        1131,
        r"void DX12CommandList::BuildTLAS\(",
        "DX12 TLAS build",
    ),
    Citation(
        "2.3",
        "engine/rhi/rhi_device.h",
        292,
        361,
        r"CreateBLAS[\s\S]*RHIBLASHandle::Invalid\(\)[\s\S]*"
        r"virtual bool SupportsRayTracing\(\) const \{ return false; \}",
        "RHI defaults return invalid handles; SupportsRayTracing() is false",
    ),
    Citation(
        "2.3",
        "engine/rhi/dx12/dx12_device.cpp",
        336,
        336,
        r"RaytracingTier >= D3D12_RAYTRACING_TIER_1_0",
        "DX12 ray tracing reported for DXR Tier >= 1.0 only",
    ),
    Citation(
        "2.3",
        "engine/rhi/dx12/dx12_device.cpp",
        1819,
        1819,
        r"RHIRTPipelineHandle DX12Device::CreateRaytracingPipeline\(",
        "DX12 ray-tracing pipeline creation (unused by UzPainter)",
    ),
    Citation(
        "2.3",
        "engine/rhi/dx12/dx12_command_list.cpp",
        1176,
        1176,
        r"void DX12CommandList::DispatchRays\(",
        "DX12 DispatchRays (unused by UzPainter)",
    ),
    Citation(
        "2.3",
        "engine/rhi/dx12/dx12_pso_creation.cpp",
        172,
        172,
        r"ID3D12RootSignature\* CreateBindlessRootSignature\(",
        "SM 6.6 bindless root signature",
    ),
    Citation(
        "2.3",
        "engine/rhi/vulkan/vulkan_device.cpp",
        748,
        756,
        r"kMaxTextureBindings = 16[\s\S]*kMaxUAVBindings = 16",
        "Vulkan fixed layout of 16 slots per register class",
    ),
    Citation(
        "2.3",
        "engine/rhi/vulkan/vulkan_device.cpp",
        532,
        562,
        r"descriptor indexing capabilities[\s\S]*m_bindlessSupported",
        "Vulkan descriptor indexing queried and logged only",
    ),
    Citation(
        "2.3",
        "engine/shader/shader_reflection.h",
        3,
        5,
        r"DXIL reflection will be",
        "DXIL reflection not wired",
    ),
    Citation(
        "2.3",
        "engine/rhi/dx12/dx12_fence.cpp",
        83,
        96,
        r"never gives up[\s\S]*while \(WaitForSingleObject\(m_event, kGpuWaitWatchdogMs\)",
        "DX12 fence waits forever, logging every watchdog period",
    ),
    Citation(
        "2.3",
        "engine/rhi/dx12/dx12_fence.h",
        19,
        19,
        r"kGpuWaitWatchdogMs = 10000",
        "DX12 watchdog period is 10 s",
    ),
    Citation(
        "2.3",
        "engine/rhi/vulkan/vulkan_fence.cpp",
        93,
        100,
        r"kTimeoutNs = 5'000'000'000ULL[\s\S]*VK_TIMEOUT",
        "Vulkan fence gives up after 5 s and only logs",
    ),
    Citation(
        "3.4",
        "engine/rhi/dx12/dx12_agility.cpp",
        17,
        17,
        r'D3D12SDKPath = "\.\\\\D3D12\\\\"',
        "exported Agility path is the D3D12 subfolder",
    ),
    Citation(
        "3.4",
        "engine/rhi/dx12/dx12_device.cpp",
        419,
        419,
        r'sdkPath = GetExeDir\(\)\.string\(\) \+ "\\\\"',
        "TryLoadAgilitySdk uses the executable folder itself",
    ),
    Citation(
        "3.4",
        "engine/rhi/vulkan/vulkan_device.cpp",
        215,
        215,
        r"requestedVersion = VK_API_VERSION_1_2",
        "Vulkan 1.2 instance requested",
    ),
    Citation(
        "3.4",
        "engine/shader/shader_compiler.cpp",
        241,
        241,
        r"-fspv-target-env=vulkan1\.3",
        "SPIR-V compiled for vulkan1.3",
    ),
    Citation(
        "3.4",
        "engine/rhi/dx12/dx12_command_list.cpp",
        1068,
        1086,
        r"DX12CommandList::FatalErrorLoop[\s\S]*std::abort\(\)",
        "FatalErrorLoop aborts after repeated RHI errors",
    ),
    Citation(
        "3.4",
        "engine/shader/shader_compiler.cpp",
        122,
        122,
        r"SetDllDirectoryW\(",
        "ShaderCompiler::Init sets the DLL directory to DXC's folder",
    ),
)


def citation_holds(root: Path, citation: Citation) -> bool:
    """True if the cited line range exists under `root` and contains the pattern."""
    path = root / citation.path
    if not path.is_file():
        return False
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if citation.start < 1 or citation.end > len(lines) or citation.start > citation.end:
        return False
    excerpt = "\n".join(lines[citation.start - 1 : citation.end])
    return re.search(citation.pattern, excerpt) is not None


def failing_citations(root: Path, citations: tuple[Citation, ...] = CITATIONS) -> list[Citation]:
    """The citations that do not hold under `root`."""
    return [c for c in citations if not citation_holds(root, c)]
