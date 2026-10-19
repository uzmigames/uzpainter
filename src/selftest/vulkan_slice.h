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
//
// The slice is reported apart from the DX12 hardware slice and from the `vulkan-availability`
// probe (`vulkan_hardware_slice` in the report). No stage is mandatory, so the slice never changes
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

}  // namespace uzp::selftest
