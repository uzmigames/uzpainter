// Modified by UzmiGames for UzPainter — see thirdparty/uzengine-render-core/MODIFICATIONS.md UZP-MOD-003. Original: UzEngine runtime/engine/rhi/vulkan/vulkan_fence.cpp at 380c142e481d56fe16b045f63315b42359e86a7d. Licensed under the Apache License, Version 2.0.

/// Vulkan Fence Implementation
///
/// Uses VK_KHR_timeline_semaphore for native timeline fence support.
/// Signal submits a timeline semaphore signal via vkQueueSubmit2.
/// WaitCPU uses vkWaitSemaphores with the time left until the caller's deadline.
/// IsComplete/GetCompletedValue use vkGetSemaphoreCounterValue.

#define VK_NO_PROTOTYPES
#ifdef _WIN32
#define VK_USE_PLATFORM_WIN32_KHR
#endif
#include <volk.h>

#include "vulkan_fence.h"
#include "vulkan_device.h"

#include "log.h"
#include "profiler.h"

#include <chrono>

namespace uz {

VulkanFence::~VulkanFence() {
    if (m_device && m_timelineSemaphore != VK_NULL_HANDLE) {
        vkDestroySemaphore(m_device->GetVkDevice(), m_timelineSemaphore, nullptr);
    }
}

bool VulkanFence::Init(VulkanDevice* device) {
    UZ_PROFILE_FUNCTION();
    if (!device) {
        UZ_LOG(RHI, Error, "VulkanFence::Init -- null device");
        return false;
    }

    m_device = device;

    // Create timeline semaphore with initial value 0
    VkSemaphoreTypeCreateInfo timelineCI = {};
    timelineCI.sType = VK_STRUCTURE_TYPE_SEMAPHORE_TYPE_CREATE_INFO;
    timelineCI.semaphoreType = VK_SEMAPHORE_TYPE_TIMELINE;
    timelineCI.initialValue = 0;

    VkSemaphoreCreateInfo semCI = {};
    semCI.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;
    semCI.pNext = &timelineCI;

    VkResult result = vkCreateSemaphore(device->GetVkDevice(), &semCI, nullptr, &m_timelineSemaphore);
    if (result != VK_SUCCESS) {
        UZ_LOG(RHI, Error, "vkCreateSemaphore (timeline) failed, result={}", static_cast<int>(result));
        return false;
    }

    UZ_LOG(RHI, Trace, "VulkanFence created (timeline semaphore)");
    return true;
}

// -----------------------------------------------------------------------------
// IRHIFence implementation
// -----------------------------------------------------------------------------

void VulkanFence::Signal(uint64_t value) {
    UZ_PROFILE_FUNCTION();
    if (!m_device || m_timelineSemaphore == VK_NULL_HANDLE) return;

    // Submit an empty command with a timeline semaphore signal
    VkTimelineSemaphoreSubmitInfo timelineInfo = {};
    timelineInfo.sType = VK_STRUCTURE_TYPE_TIMELINE_SEMAPHORE_SUBMIT_INFO;
    timelineInfo.signalSemaphoreValueCount = 1;
    timelineInfo.pSignalSemaphoreValues = &value;

    VkSubmitInfo submitInfo = {};
    submitInfo.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submitInfo.pNext = &timelineInfo;
    submitInfo.signalSemaphoreCount = 1;
    submitInfo.pSignalSemaphores = &m_timelineSemaphore;

    VkResult result = vkQueueSubmit(m_device->GetGraphicsQueue(), 1, &submitInfo, VK_NULL_HANDLE);
    if (result != VK_SUCCESS) {
        UZ_LOG(RHI, Error, "VulkanFence::Signal -- vkQueueSubmit failed, result={}", static_cast<int>(result));
    }
}

FenceWaitResult VulkanFence::WaitCPU(uint64_t value, FenceDeadline deadline) {
    UZ_PROFILE_FUNCTION();
    if (!m_device || m_timelineSemaphore == VK_NULL_HANDLE) {
        UZ_LOG(RHI, Error, "VulkanFence::WaitCPU -- fence not initialized, cannot wait for value {}", value);
        return {FenceWaitStatus::DeviceLost, static_cast<int32_t>(VK_ERROR_INITIALIZATION_FAILED)};
    }

    VkSemaphoreWaitInfo waitInfo = {};
    waitInfo.sType = VK_STRUCTURE_TYPE_SEMAPHORE_WAIT_INFO;
    waitInfo.semaphoreCount = 1;
    waitInfo.pSemaphores = &m_timelineSemaphore;
    waitInfo.pValues = &value;

    // Waits for the time left until the deadline (0 polls without blocking). A driver may
    // report VK_TIMEOUT slightly before the deadline; the wait then resumes, so `Timeout`
    // always means the deadline has passed.
    VkResult result = VK_TIMEOUT;
    for (;;) {
        const auto now = std::chrono::steady_clock::now();
        const uint64_t timeoutNs = deadline > now
            ? static_cast<uint64_t>(std::chrono::ceil<std::chrono::nanoseconds>(deadline - now).count())
            : 0;
        result = vkWaitSemaphores(m_device->GetVkDevice(), &waitInfo, timeoutNs);
        if (result != VK_TIMEOUT || std::chrono::steady_clock::now() >= deadline) {
            break;
        }
    }
    switch (result) {
        case VK_SUCCESS:
            return {FenceWaitStatus::Signaled, 0};
        case VK_TIMEOUT:
            UZ_LOG(RHI, Warning, "VulkanFence::WaitCPU -- deadline passed waiting for value {}", value);
            return {FenceWaitStatus::Timeout, 0};
        default:
            UZ_LOG(RHI, Error, "VulkanFence::WaitCPU -- vkWaitSemaphores failed waiting for value {}, result={}",
                   value, static_cast<int>(result));
            return {FenceWaitStatus::DeviceLost, static_cast<int32_t>(result)};
    }
}

bool VulkanFence::IsComplete(uint64_t value) const {
    if (!m_device || m_timelineSemaphore == VK_NULL_HANDLE) return false;

    uint64_t completedValue = 0;
    VkResult result = vkGetSemaphoreCounterValue(m_device->GetVkDevice(), m_timelineSemaphore, &completedValue);
    if (result != VK_SUCCESS) return false;
    return completedValue >= value;
}

uint64_t VulkanFence::GetCompletedValue() const {
    if (!m_device || m_timelineSemaphore == VK_NULL_HANDLE) return 0;

    uint64_t completedValue = 0;
    VkResult result = vkGetSemaphoreCounterValue(m_device->GetVkDevice(), m_timelineSemaphore, &completedValue);
    if (result != VK_SUCCESS) return 0;
    return completedValue;
}

} // namespace uz
