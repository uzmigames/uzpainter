"""Local modifications of the vendored render core (`13-engine-integration.md` §3.3, §3.4).

`thirdparty/uzengine-render-core/MODIFICATIONS.md` logs every change as a `## UZP-MOD-nnn`
section with a two-column field table. This module parses that log, holds the upstream
behaviours its entries cite (checked against the selected commit like `citations.py`), checks
the Apache-2.0 §4(b) notice of every modified file against the log and `MANIFEST.json`, and
updates the manifest entries of modified files.

Run `python -m tools.vendoring.modifications` after changing a vendored file: it rewrites the
manifest entries named by the log (`status: modified`, ids, `vendored_sha256`) and prints any
remaining problem.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from tools.vendoring.citations import Citation
from tools.vendoring.hashing import sha256_hex
from tools.vendoring.manifest import Manifest, ManifestEntry, load, save
from tools.vendoring.subset import VENDORED_DIR

LOG_NAME = "MODIFICATIONS.md"
REASONS = frozenset({"defect", "trim", "platform", "capability"})
FIELDS = (
    "Id",
    "Files",
    "Reason",
    "Description",
    "Upstream behaviour",
    "Date",
    "Author",
    "Covering test",
)

ID_RE = re.compile(r"UZP-MOD-\d{3}")
HEADING_RE = re.compile(r"^## (UZP-MOD-\d{3})\b.*$", re.MULTILINE)
ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*$")
CODE_RE = re.compile(r"`([^`]+)`")
CITATION_RE = re.compile(r"^(?P<path>[\w./-]+):(?P<start>\d+)(?:-(?P<end>\d+))?$")
TEST_RE = re.compile(r"^(?P<file>tests/[\w./-]+\.py)::(?P<func>test_\w+)$")
NOTICE_PREFIX = "// Modified by UzmiGames for UzPainter"


@dataclass(frozen=True)
class Modification:
    """One logged change. `files` are relative to the vendored folder (= to UzEngine
    `runtime/`); `upstream` are `path:line` or `path:start-end` citations at the selected
    commit; `covering_tests` are pytest node ids `tests/<file>.py::test_<name>`."""

    id: str
    files: tuple[str, ...]
    reason: str
    description: str
    upstream: tuple[str, ...]
    date: str
    author: str
    covering_tests: tuple[str, ...]


def notice(ids: Sequence[str], upstream_path: str, commit: str) -> str:
    """The Apache-2.0 §4(b) notice line a modified file starts with (`13-…` §3.3)."""
    return (
        f"{NOTICE_PREFIX} — see {VENDORED_DIR}/{LOG_NAME} {', '.join(ids)}. "
        f"Original: UzEngine {upstream_path} at {commit}. "
        "Licensed under the Apache License, Version 2.0."
    )


def parse_log(text: str) -> list[Modification]:
    """Parse the `## UZP-MOD-nnn` sections; raise `ValueError` on a malformed entry."""
    headings = list(HEADING_RE.finditer(text))
    entries: list[Modification] = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        body = text[heading.end() : end]
        # A later `## ` section that is not an entry ends this one.
        stop = re.search(r"^## ", body, re.MULTILINE)
        if stop:
            body = body[: stop.start()]
        fields: dict[str, str] = {}
        for line in body.splitlines():
            row = ROW_RE.match(line)
            if row and row.group(1) in FIELDS:
                fields[row.group(1)] = row.group(2)
        missing = [f for f in FIELDS if f not in fields]
        mod_id = heading.group(1)
        if missing:
            raise ValueError(f"{mod_id}: missing fields {missing}")
        if fields["Id"].strip("`") != mod_id:
            raise ValueError(f"{mod_id}: Id field {fields['Id']!r} differs from the heading")
        reason = fields["Reason"].strip("`")
        if reason not in REASONS:
            raise ValueError(f"{mod_id}: reason {reason!r} not in {sorted(REASONS)}")
        entries.append(
            Modification(
                id=mod_id,
                files=tuple(CODE_RE.findall(fields["Files"])),
                reason=reason,
                description=fields["Description"],
                upstream=tuple(
                    c for c in CODE_RE.findall(fields["Upstream behaviour"]) if CITATION_RE.match(c)
                ),
                date=fields["Date"],
                author=fields["Author"],
                covering_tests=tuple(CODE_RE.findall(fields["Covering test"])),
            )
        )
    return entries


def load_log(repo_root: Path) -> list[Modification]:
    return parse_log((repo_root / VENDORED_DIR / LOG_NAME).read_text(encoding="utf-8"))


def ids_by_file(log: Sequence[Modification]) -> dict[str, list[str]]:
    """Vendored-folder-relative path → sorted modification ids touching it."""
    result: dict[str, list[str]] = {}
    for mod in log:
        for path in mod.files:
            result.setdefault(path, []).append(mod.id)
    return {path: sorted(ids) for path, ids in result.items()}


def apply_to_manifest(repo_root: Path, manifest: Manifest, log: Sequence[Modification]) -> Manifest:
    """Manifest with every logged file marked `modified` with its ids and current hash.

    Entries the log does not name are left as they are."""
    by_file = ids_by_file(log)
    prefix = f"{VENDORED_DIR}/"
    files: list[ManifestEntry] = []
    for entry in manifest.files:
        ids = by_file.get(entry.vendored_path.removeprefix(prefix))
        if ids:
            data = (repo_root / entry.vendored_path).read_bytes()
            entry = replace(
                entry, status="modified", modifications=ids, vendored_sha256=sha256_hex(data)
            )
        files.append(entry)
    return replace(manifest, files=files)


def problems(repo_root: Path, manifest: Manifest, log: Sequence[Modification]) -> list[str]:
    """Consistency of the log, the manifest, the notices and the covering tests.

    - every logged id is unique, has files, upstream citations from `UPSTREAM_CITATIONS` and
      covering tests that exist;
    - every logged file is in the manifest as `modified` with exactly the ids that log it;
    - every `modified` manifest entry is logged and starts with its §4(b) notice line;
    - no `verbatim` file carries a notice."""
    found: list[str] = []
    seen: set[str] = set()
    known = {c.location for c in UPSTREAM_CITATIONS}
    for mod in log:
        if mod.id in seen:
            found.append(f"{mod.id}: logged twice")
        seen.add(mod.id)
        if not mod.files:
            found.append(f"{mod.id}: no files")
        if not mod.upstream:
            found.append(f"{mod.id}: no upstream behaviour cited as path:line")
        found += [
            f"{mod.id}: citation {c} is not in UPSTREAM_CITATIONS"
            for c in mod.upstream
            if c not in known
        ]
        if not mod.covering_tests:
            found.append(f"{mod.id}: no covering test")
        for test in mod.covering_tests:
            match = TEST_RE.match(test)
            if not match:
                found.append(f"{mod.id}: covering test {test!r} is not a pytest node id")
                continue
            test_file = repo_root / match.group("file")
            if not test_file.is_file() or not re.search(
                rf"^def {match.group('func')}\(",
                test_file.read_text(encoding="utf-8"),
                re.MULTILINE,
            ):
                found.append(f"{mod.id}: covering test {test} does not exist")

    by_file = ids_by_file(log)
    entries = manifest.by_vendored_path()
    prefix = f"{VENDORED_DIR}/"
    for path, ids in sorted(by_file.items()):
        entry = entries.get(prefix + path)
        if entry is None:
            found.append(f"{path}: logged but not in the manifest")
        elif entry.status != "modified" or entry.modifications != ids:
            found.append(
                f"{path}: manifest says {entry.status} {entry.modifications}, log says {ids}"
            )
    for entry in manifest.files:
        rel = entry.vendored_path.removeprefix(prefix)
        data = (repo_root / entry.vendored_path).read_bytes()
        first = data.split(b"\n", 1)[0].decode("utf-8", errors="replace")
        if entry.status == "modified":
            if rel not in by_file:
                found.append(f"{rel}: modified in the manifest but not logged")
            expected = notice(entry.modifications, entry.upstream_path, entry.upstream_commit)
            if first != expected:
                found.append(f"{rel}: first line is not the notice {expected!r}")
        elif first.startswith(NOTICE_PREFIX):
            found.append(f"{rel}: verbatim but carries a modification notice")
    return found


def _cite(path: str, start: int, end: int, pattern: str, behaviour: str) -> Citation:
    return Citation("MODIFICATIONS.md", path, start, end, pattern, behaviour)


# Upstream behaviours the log cites, at the selected commit (paths relative to `runtime/`).
# Checked against an exported upstream tree with `citations.failing_citations`.
UPSTREAM_CITATIONS: tuple[Citation, ...] = (
    # UZP-MOD-001
    _cite(
        "engine/rhi/rhi_factory.cpp",
        13,
        24,
        r'#include "dx11/dx11_device\.h"[\s\S]*#include "metal/metal_device\.h"',
        "factory includes the DX11 and Metal backends",
    ),
    _cite(
        "engine/rhi/rhi_factory.cpp",
        50,
        59,
        r"case RHIBackend::DX11:[\s\S]*std::make_unique<DX11Device>\(\)",
        "factory case creating a DX11 device",
    ),
    _cite(
        "engine/rhi/rhi_factory.cpp",
        73,
        87,
        r"case RHIBackend::Metal:[\s\S]*Metal backend requires macOS or iOS",
        "factory cases for Metal",
    ),
    _cite(
        "engine/rhi/rhi_factory.cpp",
        89,
        92,
        r"unsupported backend \{\}",
        "default case logs the backend as a number",
    ),
    # UZP-MOD-002
    _cite(
        "engine/rhi/rhi_config.cpp",
        8,
        8,
        r'#include "config\.h"',
        "rhi_config.cpp includes the engine config",
    ),
    _cite(
        "engine/rhi/rhi_config.cpp",
        77,
        133,
        r"bool ParseBackend[\s\S]*RHIBackend PlatformDefaultBackend\(\)",
        "parsing helpers used only by ResolveRHIConfig",
    ),
    _cite(
        "engine/rhi/rhi_config.cpp",
        139,
        189,
        r'RHIConfig ResolveRHIConfig\(const Config& config\)[\s\S]*config\.GetString\("rhi"',
        "ResolveRHIConfig reads the backend from CLI, .uzproject and CVars",
    ),
    _cite("engine/rhi/rhi_config.h", 15, 15, r"class Config;", "forward declaration of Config"),
    _cite(
        "engine/rhi/rhi_config.h",
        67,
        67,
        r"RHIConfig ResolveRHIConfig\(const Config& config\);",
        "ResolveRHIConfig declaration",
    ),
    # UZP-MOD-003
    _cite(
        "engine/rhi/rhi_fence.h",
        56,
        56,
        r"virtual void WaitCPU\(uint64_t value\) = 0;",
        "fence wait has no deadline and no result",
    ),
    _cite(
        "engine/rhi/dx12/dx12_fence.cpp",
        72,
        74,
        r"if \(m_fence->GetCompletedValue\(\) >= value\)",
        "DX12 completed-value check reads a removed device (UINT64_MAX) as signalled",
    ),
    _cite(
        "engine/rhi/dx12/dx12_fence.cpp",
        76,
        81,
        r"SetEventOnCompletion[\s\S]*return;",
        "DX12 wait returns silently when SetEventOnCompletion fails",
    ),
    _cite(
        "engine/rhi/dx12/dx12_fence.cpp",
        83,
        96,
        r"while \(WaitForSingleObject\(m_event, kGpuWaitWatchdogMs\) == WAIT_TIMEOUT\)",
        "DX12 fence waits forever, logging each watchdog period",
    ),
    _cite(
        "engine/rhi/dx12/dx12_fence.h",
        19,
        19,
        r"kGpuWaitWatchdogMs = 10000",
        "watchdog period 10 s",
    ),
    _cite(
        "engine/rhi/vulkan/vulkan_fence.cpp",
        85,
        85,
        r"if \(!m_device \|\| m_timelineSemaphore == VK_NULL_HANDLE\) return;",
        "Vulkan wait on an uninitialised fence returns silently",
    ),
    _cite(
        "engine/rhi/vulkan/vulkan_fence.cpp",
        93,
        100,
        r"kTimeoutNs = 5'000'000'000ULL[\s\S]*vkWaitSemaphores failed",
        "Vulkan fence gives up after 5 s and only logs, device loss included",
    ),
    # UZP-MOD-004
    _cite(
        "engine/rhi/dx12/dx12_device.cpp",
        336,
        336,
        r"RaytracingTier >= D3D12_RAYTRACING_TIER_1_0",
        "ray tracing reported for DXR Tier >= 1.0 only",
    ),
    _cite(
        "engine/rhi/dx12/dx12_device.h",
        183,
        183,
        r"bool SupportsRayTracing\(\) const override",
        "the only ray-tracing capability query",
    ),
    # UZP-MOD-005
    _cite(
        "engine/rhi/dx12/dx12_agility.cpp",
        17,
        17,
        r'D3D12SDKPath = "\.\\\\D3D12\\\\"',
        "exported Agility path is the D3D12 subfolder",
    ),
    _cite(
        "engine/rhi/dx12/dx12_device.cpp",
        419,
        419,
        r'sdkPath = GetExeDir\(\)\.string\(\) \+ "\\\\"',
        "TryLoadAgilitySdk uses the executable folder itself",
    ),
    # UZP-MOD-006
    _cite(
        "engine/shader/shader_compiler.cpp",
        241,
        241,
        r"-fspv-target-env=vulkan1\.3",
        "SPIR-V target vulkan1.3",
    ),
    _cite(
        "engine/shader/shader_compiler.h",
        10,
        10,
        r"-fspv-target-env=vulkan1\.3",
        "documented SPIR-V target vulkan1.3",
    ),
    _cite(
        "engine/rhi/vulkan/vulkan_device.cpp",
        215,
        215,
        r"requestedVersion = VK_API_VERSION_1_2",
        "Vulkan 1.2 instance requested",
    ),
    # UZP-MOD-008
    _cite(
        "engine/shader/shader_compiler.h",
        84,
        95,
        r"struct ShaderCompileDesc \{[\s\S]*bool disableOptimizations = false;[^\n]*\n\};",
        "the compile description has no request for IEEE-strict arithmetic",
    ),
    _cite(
        "engine/shader/shader_compiler.cpp",
        261,
        263,
        r'if \(desc\.disableOptimizations\) \{\s*args\.push_back\(L"-Od"\);',
        "the last code-generation flag BuildArguments passes; `-Gis` is never passed",
    ),
    # UZP-MOD-009
    _cite(
        "engine/rhi/rhi_types.h",
        166,
        205,
        r"enum class RHIFormat : uint8_t \{(?:(?!R16Unorm|RG16Unorm|RGBA16Unorm)[\s\S])*"
        r"D32FloatS8Uint,[^\n]*\n\};",
        "RHIFormat has no 16-bit unorm color format",
    ),
    _cite(
        "engine/rhi/rhi_types.h",
        262,
        263,
        r"case RHIFormat::D32FloatS8Uint: return 8;\s*default:\s*return 0;",
        "BytesPerTexel ends at D32FloatS8Uint",
    ),
    _cite(
        "engine/rhi/dx12/dx12_texture_creation.cpp",
        59,
        60,
        r"return DXGI_FORMAT_BC7_UNORM_SRGB;\s*default:\s*return DXGI_FORMAT_UNKNOWN;",
        "the texture-creation format map ends at BC7Srgb",
    ),
    _cite(
        "engine/rhi/dx12/dx12_command_list.cpp",
        882,
        883,
        r"return DXGI_FORMAT_BC7_UNORM_SRGB;\s*default:\s*return DXGI_FORMAT_UNKNOWN;",
        "the copy-footprint format map ends at BC7Srgb",
    ),
    _cite(
        "engine/rhi/vulkan/vulkan_format_helpers.h",
        53,
        54,
        r"return VK_FORMAT_BC7_SRGB_BLOCK;\s*default:\s*return VK_FORMAT_UNDEFINED;",
        "the Vulkan format map ends at BC7Srgb",
    ),
    # UZP-MOD-010
    _cite(
        "platform/windows/crash_handler.cpp",
        59,
        59,
        r"char g_crashBaseDir\[MAX_PATH\] = \{\};",
        "the crash directory is kept as an ANSI char buffer",
    ),
    _cite(
        "platform/windows/crash_handler.cpp",
        110,
        113,
        r"bool WriteMiniDump\(const char\* path[\s\S]*CreateFileA\(",
        "the minidump is created through CreateFileA",
    ),
    _cite(
        "platform/windows/crash_handler.cpp",
        143,
        146,
        r"void WriteTextReport\(const char\* path[\s\S]*CreateFileA\(",
        "the text report is created through CreateFileA",
    ),
    _cite(
        "platform/windows/crash_handler.cpp",
        263,
        266,
        r"void WriteJsonReport\(const char\* path[\s\S]*CreateFileA\(",
        "the JSON report is created through CreateFileA",
    ),
    _cite(
        "platform/windows/crash_handler.cpp",
        416,
        452,
        r"char exeDirBuf\[MAX_PATH\];[\s\S]*GetModuleFileNameA\([\s\S]*"
        r"CreateDirectoryA\(crashDir, nullptr\);",
        "the report folder is built in ANSI buffers and created through CreateDirectoryA",
    ),
    _cite(
        "platform/windows/crash_handler.cpp",
        579,
        587,
        r"void CrashHandler_SetCrashDir\(const char\* dir\)[\s\S]*"
        r"std::strncpy\(g_crashBaseDir, dir, MAX_PATH - 1\);",
        "CrashHandler_SetCrashDir copies the ANSI path, truncated at MAX_PATH",
    ),
    _cite(
        "engine/logging/log.cpp",
        63,
        63,
        r'std::getenv\("LOCALAPPDATA"\)',
        "the default log folder comes from the narrow environment",
    ),
    _cite(
        "engine/logging/log.cpp",
        99,
        99,
        r"return logFile\.string\(\);",
        "the default log path is narrowed to the ANSI code page",
    ),
    _cite(
        "engine/logging/log.cpp",
        133,
        134,
        r"rotating_file_sink_mt>\(\s*resolvedPath, 10 \* 1024 \* 1024, 3\);",
        "the file sink is opened with the narrow path",
    ),
    # UZP-MOD-011
    _cite(
        "engine/rhi/vulkan/vulkan_command_list.cpp",
        270,
        273,
        r"VkResult result = vkQueueSubmit\(m_device->GetGraphicsQueue\(\)[\s\S]*"
        r"vkQueueSubmit failed, result=",
        "a failed command-list submission is only logged",
    ),
    _cite(
        "engine/rhi/vulkan/vulkan_fence.cpp",
        77,
        80,
        r"VkResult result = vkQueueSubmit\(m_device->GetGraphicsQueue\(\)[\s\S]*"
        r"VulkanFence::Signal -- vkQueueSubmit failed",
        "a failed fence-signal submission is only logged",
    ),
    _cite(
        "engine/rhi/vulkan/vulkan_fence.cpp",
        63,
        63,
        r"if \(!m_device \|\| m_timelineSemaphore == VK_NULL_HANDLE\) return;",
        "a signal on an uninitialised fence returns silently",
    ),
    # UZP-MOD-012
    _cite(
        "engine/rhi/vulkan/vulkan_command_list.cpp",
        860,
        860,
        r"vkCmdPipelineBarrier2\(m_commandBuffers",
        "barriers through the core 1.3 entry point",
    ),
    _cite(
        "engine/rhi/vulkan/vulkan_command_list.cpp",
        1333,
        1333,
        r"vkCmdBeginRendering\(m_commandBuffers",
        "dynamic rendering through the core 1.3 entry point",
    ),
    _cite(
        "engine/rhi/vulkan/vulkan_device.cpp",
        499,
        501,
        r"VkPhysicalDeviceFeatures deviceFeatures = \{\};[\s\S]*samplerAnisotropy = VK_TRUE;",
        "only fillModeNonSolid and samplerAnisotropy are enabled",
    ),
    # UZP-MOD-013
    _cite(
        "engine/rhi/vulkan/vulkan_device.cpp",
        744,
        747,
        r"binding 0\.\.15  = SAMPLED_IMAGE[\s\S]*binding 48\.\.63 = STORAGE_IMAGE",
        "the layout has no storage-buffer binding",
    ),
    _cite(
        "engine/rhi/vulkan/vulkan_command_list.cpp",
        688,
        688,
        r"return m_descriptorSets\[m_frameIndex\]; // fallback to shared set",
        "a failed snapshot allocation silently binds the shared working set",
    ),
    _cite(
        "engine/rhi/vulkan/vulkan_command_list.cpp",
        657,
        657,
        r"writes\[1\]\.dstBinding = 16 \+ slot;",
        "every texture binding also writes a sampler at 16 + slot",
    ),
    _cite(
        "engine/rhi/vulkan/vulkan_resources.cpp",
        177,
        179,
        r"void VulkanDevice::UnmapBuffer\(RHIBufferHandle /\*handle\*/\) \{[\s\S]*"
        r"Explicit unmap is not needed",
        "unmapping flushes nothing",
    ),
    # Kept on purpose
    _cite(
        "engine/rhi/dx12/dx12_command_list.cpp",
        1068,
        1086,
        r"DX12CommandList::FatalErrorLoop[\s\S]*std::abort\(\)",
        "FatalErrorLoop aborts after repeated RHI errors",
    ),
    _cite(
        "engine/shader/shader_compiler.cpp",
        122,
        122,
        r"SetDllDirectoryW\(",
        "ShaderCompiler::Init sets the DLL directory to DXC's folder",
    ),
)


def cited_locations(text: str) -> list[str]:
    """Every backticked `path:line` citation in the log, the kept-on-purpose section included."""
    return [c for c in CODE_RE.findall(text) if CITATION_RE.match(c) and "/" in c]


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    repo_root = Path(__file__).resolve().parents[2]
    manifest_path = repo_root / VENDORED_DIR / "MANIFEST.json"
    log = load_log(repo_root)
    manifest = apply_to_manifest(repo_root, load(manifest_path), log)
    save(manifest_path, manifest)
    found = problems(repo_root, manifest, log)
    for line in found:
        print(line, file=sys.stderr)
    print(
        f"{len(log)} modifications, {sum(e.status == 'modified' for e in manifest.files)} "
        f"modified files, {len(found)} problems"
    )
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
