#pragma once

// Probe stages of `selftest` (phase0.7_toolchain-probes; docs/architecture/13-engine-integration.md
// §4.2), run after the DX12 hardware slice, in this order:
//
//   dx12-ray-query       DXR Tier 1.1 and SM 6.6 on the hardware device of `dx12-device`
//   vulkan-availability  system Vulkan loader through volk, a Vulkan 1.2 instance, every physical
//                        device's API version, driver, extensions and features
//   vulkan-ray-query     VK_KHR_acceleration_structure, VK_KHR_deferred_host_operations,
//                        VK_KHR_ray_query, features accelerationStructure and rayQuery
//   warp                 a DX12 device on the WARP adapter and the compute-path checks of the
//                        hardware slice on it; the checks that pass form the hosted WARP lane
//
// Each stage writes a probe report (probe_report.h) into the `probes` array of the selftest report
// and passes when its probe completed, whatever it found. No probe stage is mandatory or part of
// the hardware slice, so a Vulkan or WARP result never fails G0; a probe that cannot complete is
// reported as `probe not completed` with its error. All four need a GPU and are skipped with the
// reason under `--no-gpu` / `UZP_NO_GPU=1` (hosted CI, decision 028).

#include "harness.h"
#include "probe_report.h"

namespace uzp::selftest {

void RegisterProbes(Selftest& selftest);

/// Runs a probe, turning an exception into `probe not completed`, stores its report in the
/// context and returns the stage outcome.
StageOutcome RecordProbe(SelftestContext& context, const char* probe, const char* backend,
                         ProbeReport (*run)(SelftestContext&));

ProbeReport ProbeDx12RayQuery(SelftestContext& context);
ProbeReport ProbeVulkanAvailability(SelftestContext& context);
ProbeReport ProbeVulkanRayQuery(SelftestContext& context);
ProbeReport ProbeWarp(SelftestContext& context);

}  // namespace uzp::selftest
