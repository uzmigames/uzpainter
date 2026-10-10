// Registration of the probe stages of `selftest` (probes.h).

#include "probes.h"

#include <exception>
#include <string>

namespace uzp::selftest {

StageOutcome RecordProbe(SelftestContext& context, const char* probe, const char* backend,
                         ProbeReport (*run)(SelftestContext&)) {
    ProbeReport report;
    try {
        report = run(context);
    } catch (const std::exception& error) {
        report = NotCompleted(probe, backend, std::string("exception: ") + error.what());
    }
    context.probeReports.push_back(report.ToJson("    "));
    return ProbeOutcome(report);
}

void RegisterProbes(Selftest& selftest) {
    // name, mandatory, needsGpu, hardwareSlice, dependsOn, run. The probes check their inputs
    // themselves, so a missing input is reported in the probe, not as a skipped stage.
    selftest.Add({"dx12-ray-query", false, true, false, {}, [](SelftestContext& context) {
                      return RecordProbe(context, "dx12-ray-query", "dx12", ProbeDx12RayQuery);
                  }});
    selftest.Add({"vulkan-availability", false, true, false, {}, [](SelftestContext& context) {
                      return RecordProbe(context, "vulkan-availability", "vulkan",
                                         ProbeVulkanAvailability);
                  }});
    selftest.Add({"vulkan-ray-query", false, true, false, {}, [](SelftestContext& context) {
                      return RecordProbe(context, "vulkan-ray-query", "vulkan", ProbeVulkanRayQuery);
                  }});
    selftest.Add({"warp", false, true, false, {}, [](SelftestContext& context) {
                      return RecordProbe(context, "warp", "dx12-warp", ProbeWarp);
                  }});
}

}  // namespace uzp::selftest
