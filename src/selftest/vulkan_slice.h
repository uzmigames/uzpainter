#pragma once

// The Vulkan hardware slice of `selftest` (phase3.1_vulkan-compute-parity items 2.8 and 3.8,
// decision 310), run after the probes, in this order:
//
//   vulkan-device           the capability record of every physical device (render::SurveyVulkan),
//                           the qualification of the device at adapter index 0 of the vendored
//                           order and, only when it qualifies, the vendored Vulkan device; an
//                           unqualified device is refused before any work, naming every unmet
//                           criterion
//   vulkan-compute-readback the qualification kernels (render/vulkan_kernels.h) compiled by DXC to
//                           SPIR-V, dispatched, read back and compared bit for bit with their CPU
//                           references; the 16-bit pattern also against the DX12 slice's
//   vulkan-png16            the Vulkan 16-bit pattern written as a 16-bit PNG and decoded back equal
//   vulkan-ray-query-trace  the ray-query qualification (phase3.2_vulkan-ray-tracing item 2.9,
//                           decision 372): what the created device enabled for inline ray queries
//                           (refused before any work, naming every missing item, when it lacks
//                           one); the ray-cast kernel compiled to SPIR-V declaring SPV_KHR_ray_query
//                           and RayQueryKHR without any ray-tracing-pipeline capability; a BLAS of
//                           two geometries (20-byte and 12-byte strides, one non-opaque) and a TLAS
//                           of three instances built; nine inline queries traced and every record
//                           compared with its hand-computed answer and with the CPU reference
//                           (render/ray_query.h)
//
// The slice is reported apart from the DX12 hardware slice and from the `vulkan-availability`
// and `vulkan-ray-query` probes (`vulkan_hardware_slice` in the report). No stage is mandatory, so the slice never changes
// the exit code; it becomes a gate with phase3.1's acceptance. All three need a GPU and skip
// under `--no-gpu` / `UZP_NO_GPU=1`. Passing it qualifies the Vulkan compute path on this
// machine; it is no parity evidence for any Painter-visible output.

#include "harness.h"

namespace uzp::selftest {

void RegisterVulkanSlice(Selftest& selftest);

/// Shuts the Vulkan device down with its bounded drain (abandoned, never waited on, when its work
/// did not complete).
void TeardownVulkanSlice(SelftestContext& context);

StageOutcome RunVulkanDevice(SelftestContext& context);
StageOutcome RunVulkanComputeReadback(SelftestContext& context);
StageOutcome RunVulkanPng16(SelftestContext& context);
StageOutcome RunVulkanRayQueryTrace(SelftestContext& context);

}  // namespace uzp::selftest
