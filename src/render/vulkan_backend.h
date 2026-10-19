#pragma once

// The Vulkan implementation of the backend-neutral interfaces of backend.h over the vendored
// `uz::VulkanDevice`, for the device qualification of phase3.1_vulkan-compute-parity (items 2.1,
// 2.2 and 2.8; decision 310).
//
// Reach: `render::CreateDevice` still refuses Vulkan, so no product path (`run`, the MCP worker,
// the preview, export) runs on this device. Only the `selftest` Vulkan slice and the native tests
// create it, through the three steps below, until phase3.1 has qualified Vulkan outputs:
//
//   SurveyVulkan                  the capability record: loader, a pre-check Vulkan 1.2 instance
//                                 and every physical device; no logical device is created
//   QualifyVulkan                 the criteria of vulkan_qualification.h on the device at the
//                                 requested adapter index of the vendored order
//   CreateQualifiedVulkanDevice   refuses an unqualified device before any work
//                                 (`gpu_backend_unavailable {backend: vulkan, reason}` naming every
//                                 unmet criterion); otherwise creates the vendored device and checks
//                                 that it took the judged physical device (UUID) and queue family
//
// Waits: every wait is the vendored timeline-semaphore wait with a deadline (UZP-MOD-003):
// `signaled`, `timeout` or `device_lost`. A submission the queue refuses (`vkQueueSubmit` failing,
// read back through UZP-MOD-011) fails `Submit` at once: `device_removed` for
// `VK_ERROR_DEVICE_LOST`, `request_failed` otherwise; a refused fence signal fails every later wait
// on its value at once, never by a timeout. A submission is one command list, then the host
// barrier, then the fence signal. Only a refused command list means nothing reached the GPU. A
// refusal after it (barrier or signal) is a partial submission: the work may still run, so the
// device is failed for good — every `Destroy*` keeps its object, every `Create*` and `Submit`
// fails, and teardown abandons the device without waiting.
//
// Teardown (`Shutdown`): the device first waits for its last submission until the deadline. Only
// after that wait signalled are its objects destroyed; the vendored destructor then calls
// `vkDeviceWaitIdle`, which has no timeout and is not bounded by that deadline — it is reached
// only once every submission of the device's one queue has completed. After a timeout, a device
// loss or a refused submission the device is abandoned: nothing of it is destroyed or waited on
// again, and its memory stays allocated until the process ends.
//
// Host reads: each submission is followed on the same queue by a memory barrier from every
// command's writes to host reads, and `MapReadback` invalidates the buffer's allocation before
// returning it, so a readback is correct on non-coherent memory too.
//
// Threading: as for every `IDevice`, one thread uses the device and its queue.

#include "render/backend.h"
#include "render/vulkan_qualification.h"

#include <chrono>
#include <functional>
#include <memory>
#include <string>

namespace uz {
class VulkanDevice;
}

namespace uzp::render {

/// Loads the system loader through volk, creates a Vulkan 1.2 pre-check instance without layers
/// or extensions, records every physical device and destroys the instance. Creates no logical
/// device. It reloads volk's instance-level function table (the loader's instance-independent
/// entry points), so it may run while a vendored Vulkan device is alive.
[[nodiscard]] VulkanSurvey SurveyVulkan();

struct VulkanDeviceOptions {
    /// Vulkan validation layer when installed (development only).
    bool enableValidation = false;
    /// How long the destructor's `Shutdown` waits for the last submission.
    std::chrono::milliseconds teardownDeadline{10000};
};

/// How a device ended: still alive, destroyed after its work completed, or abandoned.
enum class VulkanTeardown : uint8_t { Live, Destroyed, Abandoned };

/// "live", "destroyed" or "abandoned".
[[nodiscard]] std::string_view VulkanTeardownName(VulkanTeardown teardown);

class VulkanQueue;

/// The Vulkan device: the vendored `uz::VulkanDevice` and its one queue.
class VulkanDevice final : public IDevice {
public:
    ~VulkanDevice() override;
    VulkanDevice(const VulkanDevice&) = delete;
    VulkanDevice& operator=(const VulkanDevice&) = delete;

    Backend GetBackend() const override { return Backend::Vulkan; }
    const std::string& AdapterName() const override { return m_record.name; }
    KernelTarget NativeKernelTarget() const override { return KernelTarget::Spirv; }
    IQueue& Queue() override;

    Result<uz::RHIBufferHandle> CreateBuffer(const uz::RHIBufferDesc& desc) override;
    void DestroyBuffer(uz::RHIBufferHandle buffer) override;
    Result<uz::RHITextureHandle> CreateTexture(const uz::RHITextureDesc& desc) override;
    void DestroyTexture(uz::RHITextureHandle texture) override;
    std::optional<uz::RHITextureDesc> TextureDesc(uz::RHITextureHandle texture) const override;
    Result<ComputeKernel> CreateComputeKernel(std::span<const uint8_t> bytecode,
                                              const std::string& name) override;
    void DestroyComputeKernel(const ComputeKernel& kernel) override;

    /// Valid until `Shutdown` destroyed the device (an abandoned device keeps it).
    uz::IRHIDevice& Rhi() override;
    /// `device_removed {backend: vulkan, reason}` once a wait or a submission reported
    /// `VK_ERROR_DEVICE_LOST`, or the device was abandoned; empty otherwise.
    std::optional<Error> CheckRemoved() const override;
    Error WaitFailure(const WaitResult& wait) const override;

    /// The capability record and the qualification the device was created on.
    [[nodiscard]] const VulkanDeviceRecord& Record() const { return m_record; }
    [[nodiscard]] const VulkanQualification& Qualification() const { return m_qualification; }

    /// The host view of a readback buffer whose copy has completed (its fence value waited on):
    /// the allocation is invalidated for host reads first. Null for a buffer that is not
    /// host-visible, or once the device failed.
    [[nodiscard]] const void* MapReadback(uz::RHIBufferHandle buffer);

    /// Waits for the last submission until `deadline`; destroys the device when that wait
    /// signalled and nothing failed before, abandons it otherwise. Idempotent: later calls return
    /// the first outcome.
    VulkanTeardown Shutdown(Deadline deadline);
    [[nodiscard]] VulkanTeardown Teardown() const { return m_teardown; }

    /// Fault injection for the stall tests: the next submission's host barrier waits on a
    /// semaphore that only the returned function signals, so that submission and every later
    /// fence value stay pending. The function stays callable after the device is abandoned.
    [[nodiscard]] Result<std::function<void()>> InjectQueueStall();

private:
    friend Result<std::unique_ptr<VulkanDevice>> CreateQualifiedVulkanDevice(
        const VulkanSurvey& survey, const VulkanQualification& qualification,
        const VulkanDeviceOptions& options);
    VulkanDevice(std::unique_ptr<uz::IRHIDevice> rhi, VulkanDeviceRecord record,
                 VulkanQualification qualification, const VulkanDeviceOptions& options);
    [[nodiscard]] bool Usable() const;

    std::unique_ptr<uz::IRHIDevice> m_rhi;
    uz::VulkanDevice* m_native = nullptr;
    std::unique_ptr<VulkanQueue> m_queue;
    VulkanDeviceRecord m_record;
    VulkanQualification m_qualification;
    VulkanDeviceOptions m_options;
    VulkanTeardown m_teardown = VulkanTeardown::Live;
};

/// The device of a qualified survey, or `gpu_backend_unavailable {backend: vulkan, reason}`:
/// before any device is created when `qualification` is not qualified (the reason names every
/// unmet criterion), after creation when the vendored backend took another physical device or
/// queue family than the one judged.
[[nodiscard]] Result<std::unique_ptr<VulkanDevice>> CreateQualifiedVulkanDevice(
    const VulkanSurvey& survey, const VulkanQualification& qualification,
    const VulkanDeviceOptions& options = {});

}  // namespace uzp::render
