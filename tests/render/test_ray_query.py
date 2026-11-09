"""Tests of the inline-ray-query layer of phase3.2_vulkan-ray-tracing (decision 372):
`src/render/ray_query.h` over the vendored Vulkan acceleration structures (UZP-MOD-007) and DXR,
through the ray-query cases of `uzp-render-tests.exe` (`tests/render/ray_query_test.cpp`).

`ray-query-reference` needs no GPU. `vulkan-ray-query` and `dx12-ray-query` create a device; they
skip under `UZP_NO_GPU=1` (decision 028) or when the machine has no device of the backend (exit
code 77). They qualify the ray-query path; they are no parity evidence for a Painter output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.render.test_core_device_kernels import NO_GPU, run_case
from tools.parity.raycast import build_report, kernel_sha256, report_problems

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_REPORT = REPO_ROOT / "parity" / "reports" / "phase3" / "ray-cast.json"
FIXTURES = ("plane", "sphere", "bevelled-cube", "opacity-pair")


def _gpu(exe: Path, case: str, work: Path) -> set[str]:
    if NO_GPU:
        pytest.skip(f"UZP_NO_GPU=1: `{case}` needs a GPU (decision 028)")
    passed, _ = run_case(exe, case, work)
    return passed


def test_cpu_reference_and_capability_decision(render_tests: Path) -> None:
    """2.5, 2.7, 2.12, 3.2: the CPU reference gives the hand-computed answers; the instance record
    has the shared 64-byte layout; the differ counts fields and lists rays; a Vulkan record without
    VK_KHR_ray_query (or with the features off) reports inline ray queries unavailable with the
    missing items, also in the capability report's JSON."""
    passed, _ = run_case(render_tests, "ray-query-reference")
    assert {
        "the CPU reference gives the hand-computed answers of the qualification rays",
        "the qualification BLAS has a 20-byte and a 12-byte stride and a non-opaque geometry",
        "the instance record has the 64-byte layout of D3D12_RAYTRACING_INSTANCE_DESC and "
        "VkAccelerationStructureInstanceKHR",
        "the record differ counts each field and lists every differing ray",
        "a non-finite distance or barycentric never compares equal",
        "a device with the three extensions and both features misses nothing",
        "a device without VK_KHR_ray_query reports it missing",
        "features reported false are named",
        "a device without any of them names the three extensions",
        "the Vulkan capability report states ray queries unavailable with the missing list",
        "the Vulkan capability report states ray queries available with nothing missing",
    } <= passed


def _shared(backend: str) -> set[str]:
    return {
        f"{backend}: the ray-cast kernel compiles",
        f"{backend}: the ray-cast compute pipeline is created",
        f"{backend}: the BLAS and TLAS build",
        f"{backend}: the inline queries are traced and read back",
        f"{backend}: every record equals its hand-computed answer",
        f"{backend}: every record equals the CPU reference",
        f"{backend}: a second build and trace gives byte-identical records",
        f"{backend}: a rebuild after a vertex change hits the moved triangles",
        f"{backend}: a 10-byte vertex stride is refused",
        f"{backend}: an index count that is not a multiple of 3 is refused",
        f"{backend}: an index past the vertices is refused",
        f"{backend}: an instance of an unknown mesh is refused",
        f"{backend}: a UzPainter mesh's scene traces as the CPU reference",
        f"{backend}: a singular instance transform is refused",
        f"{backend}: an instance forced both opaque and non-opaque is refused",
    }


def test_vulkan_ray_query(render_tests: Path, tmp_path: Path) -> None:
    """2.1-2.3, 2.6, 2.7, 2.9, 2.11, 3.1, 3.3 (Vulkan): the device enables the three extensions
    and two features its record exposes and the capability query reports them; invalid BLAS/TLAS
    input is refused and a refused build submits nothing; the ray-cast kernel's SPIR-V declares
    SPV_KHR_ray_query and RayQueryKHR (no ray-tracing pipeline) and binds the TLAS at 80; the
    qualification scene (20- and 12-byte strides, a non-opaque geometry, three instances) traces
    every known answer, twice byte-identical, and a rebuild after a vertex change hits the moved
    triangles."""
    passed = _gpu(render_tests, "vulkan-ray-query", tmp_path)
    assert {
        "this machine's Vulkan device qualifies",
        "the qualified Vulkan device is created",
        "the device enabled exactly what its record exposes for inline ray queries",
        "the Vulkan capability query reports inline ray queries",
        "vulkan: buffers with and without AccelerationStructureBuildInput are created",
        "vulkan: a valid BLAS is created with a device address",
        "vulkan: CreateBLAS refuses a stride below 12 bytes",
        "vulkan: CreateBLAS refuses a vertex format other than RGB32Float",
        "vulkan: CreateBLAS refuses a vertex buffer without AccelerationStructureBuildInput",
        "vulkan: CreateBLAS refuses a non-indexed vertex count that is not a multiple of 3",
        "vulkan: CreateBLAS refuses vertices past the end of the buffer",
        "vulkan: CreateBLAS refuses PreferFastTrace with PreferFastBuild",
        "vulkan: CreateBLAS refuses a description without geometry",
        "vulkan: CreateTLAS refuses zero instances",
        "vulkan: a TLAS for one instance is created",
        "vulkan: a TLAS build past its instance count is refused and the list is not submitted",
        "vulkan: a BLAS update without AllowUpdate is refused and the list is not submitted",
        "vulkan: a build in a refused list does not count as built for a later update",
        "vulkan: after a submitted build, an update in a later list runs",
        "vulkan: the SPIR-V declares SPV_KHR_ray_query and RayQueryKHR, no ray-tracing pipeline",
        "vulkan: the TLAS is at binding 80",
        "after its work completed the Vulkan device is destroyed",
    } | _shared("vulkan") <= passed


def test_dx12_ray_query(render_tests: Path, tmp_path: Path) -> None:
    """2.7, 2.11, 3.3 (DXR): the same layer, HLSL, scene and rays on DX12 give the same known
    answers, twice byte-identical; the DX12 capability query reports inline ray queries."""
    passed = _gpu(render_tests, "dx12-ray-query", tmp_path)
    assert {"the DX12 capability query reports inline ray queries"} | _shared("dx12") <= passed


def test_mesh_scene(render_tests: Path) -> None:
    """2.7: a UzPainter mesh gives one BLAS per object with triangles and one geometry per material
    at the 12-byte position stride with the material's opacity; the column-major object transform
    becomes the instance transform; the reference traces it."""
    passed, _ = run_case(render_tests, "ray-query-mesh")
    assert {
        "a mesh gives one BLAS per object with triangles and one geometry per material",
        "each geometry holds its own positions at the 12-byte Float3 stride and its material's "
        "opacity",
        "an object's column-major transform becomes the row-major instance transform, its index "
        "the id",
        "the reference traces the mesh scene: materials, opacity, the translated object, a miss",
    } <= passed


def test_ray_cast_fixtures_on_both_backends(render_tests: Path, tmp_path: Path) -> None:
    """2.10, 2.12, 3.1, 3.3, 3.4: every ray-cast fixture builds and traces on DX12 and Vulkan,
    twice byte-identical on each; interior and miss rays equal the CPU reference, edge and vertex
    rays hit at its distance; the DX12 and Vulkan records are compared field by field and every
    differing ray is listed in a report of numbers, identifiers and digests only."""
    passed = _gpu(render_tests, "ray-cast-fixtures", tmp_path)
    raw = json.loads((tmp_path / "ray-cast-raw.json").read_text(encoding="utf-8"))
    report = build_report(raw, kernel_sha256(), "phase3.2_vulkan-ray-tracing")
    assert report_problems(report) == []
    assert [f["id"] for f in report["fixtures"]] == list(FIXTURES)
    for fixture in FIXTURES:
        for backend in ("dx12", "vulkan"):
            assert {
                f"{backend} {fixture}: two builds and traces give byte-identical records",
                f"{backend} {fixture}: interior and miss rays equal the CPU reference",
                f"{backend} {fixture}: edge and vertex rays hit at the reference distance",
            } <= passed
        assert f"{fixture}: DX12 and Vulkan give the same records" in passed
    assert report["outcome"] == "pass"


def test_committed_ray_cast_report_is_valid() -> None:
    """2.12: the committed report `parity/reports/phase3/ray-cast.json` passes the guard's check,
    names the current kernel and every fixture, and passes."""
    report = json.loads(COMMITTED_REPORT.read_text(encoding="utf-8"))
    assert report_problems(report) == []
    assert report["kernel_sha256"] == kernel_sha256()
    assert [f["id"] for f in report["fixtures"]] == list(FIXTURES)
    assert report["outcome"] == "pass"


def test_vulkan_device_without_ray_query(render_tests: Path, tmp_path: Path) -> None:
    """3.2: a live Vulkan device created without VK_KHR_ray_query (hidden from the vendored device
    on hardware that has it) reports exactly that extension missing in the capability query and
    report; building a scene and casting rays fail before any work as unavailable, naming the
    backend and the extension, and nothing is submitted."""
    passed = _gpu(render_tests, "vulkan-ray-query-hidden", tmp_path)
    assert {
        "this machine's Vulkan device qualifies",
        "the device's record exposes every ray-query item",
        "a Vulkan device is created without VK_KHR_ray_query",
        "the device reports inline ray queries unavailable with exactly VK_KHR_ray_query missing",
        "a ray-query request fails before any work, naming the backend and VK_KHR_ray_query",
        "the capability report states ray queries unavailable with VK_KHR_ray_query missing",
        "building a ray scene is refused as unavailable",
        "casting rays is refused as unavailable",
        "nothing was submitted: no dispatch and no fallback",
        "after its work completed the Vulkan device is destroyed",
    } <= passed


def _bindless(backend: str) -> set[str]:
    return {
        f"{backend}: bindless textures are available",
        f"{backend}: the bindless gather kernel compiles",
        f"{backend}: the bindless gather pipeline is created",
        f"{backend}: 40 tagged textures are created and named",
        f"{backend}: the 40 textures have 40 distinct bindless names",
        f"{backend}: the gather runs",
        f"{backend}: every lookup reads its texel, mip size and level count, bit for bit",
        f"{backend}: a second gather gives byte-identical results",
        f"{backend}: a destroyed texture has no bindless name",
        f"{backend}: a texture created after one is destroyed reads its own texels",
        f"{backend}: a texture without ShaderResource usage has no bindless name",
    }


def test_bindless_textures_on_both_backends(render_tests: Path, tmp_path: Path) -> None:
    """2.4: sampled textures read by bindless name with a per-thread (non-uniform) index from the
    same HLSL: DX12 through the SM 6.6 descriptor heap, Vulkan through the descriptor-indexing set 1
    (UZP-MOD-007). 40 textures (more than the 16 fixed slots) of two mips read back bit for bit with
    their mip sizes and level counts, twice byte-identical; a released Vulkan slot goes to the next
    texture, which reads its own texels; DX12 and Vulkan give byte-identical results."""
    passed = _gpu(render_tests, "bindless-textures", tmp_path)
    assert {
        "the DX12 device is created",
        "this machine's Vulkan device qualifies",
        "the qualified Vulkan device is created",
        "vulkan: the SPIR-V declares RuntimeDescriptorArray and ShaderNonUniform",
        "vulkan: the texture array is in descriptor set 1",
        "vulkan: the destroyed texture's slot is given to the next texture",
        "after its work completed the Vulkan device is destroyed",
        "DX12 and Vulkan gather byte-identical results",
    } | _bindless("dx12") | _bindless("vulkan") <= passed
