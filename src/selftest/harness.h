#pragma once

// The `UzPainter.exe selftest` harness (docs/architecture/13-engine-integration.md §4.2): ordered
// stages, a result per stage, a machine-readable report and a non-zero exit when a mandatory stage
// fails. The DX12 hardware slice (hardware_slice.h) registers its stages here; later stages (the
// probes of phase0.7_toolchain-probes, the CPython stages of phase0.7_toolchain-cpython) are added
// the same way, through `Selftest::Add`, with their own fields in `SelftestContext`.

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <functional>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace uz {
class IRHIDevice;
}

namespace uzp::render {
class VulkanDevice;
}

namespace uzp::selftest {

struct VulkanProbeState;

/// Process exit codes of `selftest`.
inline constexpr int kExitPassed = 0;      ///< Every executed mandatory stage passed.
inline constexpr int kExitFailed = 1;      ///< A mandatory stage failed.
inline constexpr int kExitUsage = 2;       ///< The command line could not be parsed.

enum class StageStatus { Passed, Failed, Skipped };

const char* StatusName(StageStatus status);

/// Ordered key/value facts a stage records (adapter, versions, sizes, ...).
using Details = std::vector<std::pair<std::string, std::string>>;

struct StageOutcome {
    StageStatus status = StageStatus::Passed;
    std::string reason;  ///< Why the stage failed or was skipped; empty when it passed.
    Details details;

    static StageOutcome Pass(Details details = {});
    static StageOutcome Fail(std::string reason, Details details = {});
};

struct Options {
    std::filesystem::path outDir;      ///< Report, log and PNG output folder.
    std::filesystem::path reportPath;  ///< Machine-readable report (JSON).
    bool noGpu = false;                ///< Skip the stages that need a GPU.
    std::string noGpuReason;           ///< Why, recorded in the report and per skipped stage.
};

/// State shared by the stages of one run. Stages add what later stages consume.
struct SelftestContext {
    explicit SelftestContext(Options opts);
    ~SelftestContext();
    SelftestContext(const SelftestContext&) = delete;
    SelftestContext& operator=(const SelftestContext&) = delete;

    Options options;
    std::filesystem::path exeDir;

    /// DX12 device on the hardware adapter (stage `dx12-device`).
    std::unique_ptr<uz::IRHIDevice> device;
    /// Set when the GPU timed out or was lost: the device is then not torn down (its
    /// teardown waits for the GPU) and the process exits right after the report is written.
    bool gpuUnrecoverable = false;

    /// Compute kernel compiled by DXC (stage `shader-compile`).
    std::vector<uint8_t> kernelDxil;
    std::vector<uint8_t> kernelSpirv;

    /// The 16-bit pattern read back from the GPU (stage `compute-readback`), row-major.
    std::vector<uint16_t> readback;

    /// The qualified Vulkan device (stage `vulkan-device`, vulkan_slice.h) and the 16-bit pattern
    /// its compute readback returned (stage `vulkan-compute-readback`).
    std::unique_ptr<uzp::render::VulkanDevice> vulkanDevice;
    std::vector<uint16_t> vulkanReadback;

    /// What the Vulkan availability probe gathered (stage `vulkan-availability`, probes.h).
    std::shared_ptr<VulkanProbeState> vulkan;
    /// The probe reports of the run as JSON objects (probe_report.h), written as the report's
    /// `probes` array.
    std::vector<std::string> probeReports;
};

using StageFn = std::function<StageOutcome(SelftestContext&)>;

struct StageSpec {
    std::string name;
    bool mandatory = true;          ///< A failure fails `selftest`.
    bool needsGpu = false;          ///< Skipped, with the reason, when the run has no GPU.
    bool hardwareSlice = false;     ///< Part of the DX12 hardware slice (13 §4.2).
    std::vector<std::string> dependsOn;  ///< Skipped when one of these did not pass.
    StageFn run;
    bool vulkanHardwareSlice = false;  ///< Part of the Vulkan hardware slice (vulkan_slice.h).
};

struct StageRecord {
    StageSpec spec;
    StageOutcome outcome;
    double durationMs = 0.0;
};

/// Facts about the machine and the build, recorded at the top of the report.
Details EnvironmentFacts(const SelftestContext& context);

/// The render core's warning and error log lines since the last call (at most 32); the runner
/// adds them to the details of a failed stage.
std::vector<std::string> DrainLogProblems();

class Selftest {
public:
    void Add(StageSpec stage);

    /// Runs every stage in order, writes the report and returns the process exit code.
    int Run(SelftestContext& context);

    const std::vector<StageRecord>& Records() const { return m_records; }

private:
    std::vector<StageSpec> m_stages;
    std::vector<StageRecord> m_records;
};

/// `UzPainter.exe selftest [--out-dir <dir>] [--report <file>] [--no-gpu]`.
int RunSelftestCommand(const std::vector<std::string>& args);

}  // namespace uzp::selftest
