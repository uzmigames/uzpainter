// Modified by UzmiGames for UzPainter — see thirdparty/uzengine-render-core/MODIFICATIONS.md UZP-MOD-007, UZP-MOD-013. Original: UzEngine runtime/engine/rhi/vulkan/vulkan_resources.cpp at 380c142e481d56fe16b045f63315b42359e86a7d. Licensed under the Apache License, Version 2.0.

/// Vulkan Resource Operations — Buffer, Texture, Shader, Pipeline, Sampler
///
/// Split from vulkan_device.cpp to keep file sizes under ~1000 lines.
/// All methods are VulkanDevice members — this file is a separate TU for
/// the same class. volk.h and vk_mem_alloc.h are included WITHOUT
/// _IMPLEMENTATION defines (those live in vulkan_device.cpp).

#define VK_NO_PROTOTYPES
#ifdef _WIN32
#define VK_USE_PLATFORM_WIN32_KHR
#elif defined(__linux__)
#define VK_USE_PLATFORM_XLIB_KHR
#endif

#include <volk.h>
#include <vk_mem_alloc.h>

#include "vulkan_device.h"
#include "vulkan_format_helpers.h"

#include "log.h"
#include "profiler.h"

#include <algorithm>
#include <string>
#include <vector>

namespace uz {

using namespace uz::vk; // Format/state conversion helpers from vulkan_format_helpers.h

// ─────────────────────────────────────────────────────────────────────────────
// Buffer Operations
// ─────────────────────────────────────────────────────────────────────────────

RHIBufferHandle VulkanDevice::CreateBuffer(const RHIBufferDesc& desc) {
    UZ_PROFILE_FUNCTION();

    VkBufferCreateInfo bufferCI = {};
    bufferCI.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bufferCI.size = desc.sizeBytes;
    bufferCI.sharingMode = VK_SHARING_MODE_EXCLUSIVE;

    // Map usage flags to VkBufferUsageFlags
    VkBufferUsageFlags usageFlags = 0;
    if (HasFlag(desc.usage, RHIBufferUsage::VertexBuffer))     usageFlags |= VK_BUFFER_USAGE_VERTEX_BUFFER_BIT;
    if (HasFlag(desc.usage, RHIBufferUsage::IndexBuffer))      usageFlags |= VK_BUFFER_USAGE_INDEX_BUFFER_BIT;
    if (HasFlag(desc.usage, RHIBufferUsage::ConstantBuffer))   usageFlags |= VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT;
    if (HasFlag(desc.usage, RHIBufferUsage::StructuredBuffer)) usageFlags |= VK_BUFFER_USAGE_STORAGE_BUFFER_BIT;
    if (HasFlag(desc.usage, RHIBufferUsage::UnorderedAccess))  usageFlags |= VK_BUFFER_USAGE_STORAGE_BUFFER_BIT;
    if (HasFlag(desc.usage, RHIBufferUsage::IndirectArgs))     usageFlags |= VK_BUFFER_USAGE_INDIRECT_BUFFER_BIT;
    if (HasFlag(desc.usage, RHIBufferUsage::CopySrc))          usageFlags |= VK_BUFFER_USAGE_TRANSFER_SRC_BIT;
    if (HasFlag(desc.usage, RHIBufferUsage::CopyDst))          usageFlags |= VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    // UZP-MOD-007: BLAS vertex/index data and TLAS instance records (needs the extension enabled).
    if (HasFlag(desc.usage, RHIBufferUsage::AccelerationStructureBuildInput)) {
        if (!m_supportsAccelerationStructures) {
            UZ_LOG(RHI, Error, "CreateBuffer '{}': acceleration-structure build input on a device without "
                   "acceleration structures", desc.debugName ? desc.debugName : "");
            return RHIBufferHandle::Invalid();
        }
        usageFlags |= VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_BUILD_INPUT_READ_ONLY_BIT_KHR;
    }

    // Always add transfer bits for flexibility
    usageFlags |= VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT;

    // Enable buffer device address for GPU virtual address queries
    usageFlags |= VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT;

    bufferCI.usage = usageFlags;

    // Map memory type to VMA
    VmaAllocationCreateInfo allocCI = {};
    switch (desc.memory) {
        case RHIMemoryType::Default:
            allocCI.usage = VMA_MEMORY_USAGE_GPU_ONLY;
            break;
        case RHIMemoryType::Upload:
            allocCI.usage = VMA_MEMORY_USAGE_CPU_TO_GPU;
            allocCI.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT;
            break;
        case RHIMemoryType::Readback:
            allocCI.usage = VMA_MEMORY_USAGE_GPU_TO_CPU;
            allocCI.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT;
            break;
    }

    VkBuffer buffer = VK_NULL_HANDLE;
    VmaAllocation allocation = nullptr;
    VmaAllocationInfo allocInfo = {};
    VkResult result = vmaCreateBuffer(m_allocator, &bufferCI, &allocCI, &buffer, &allocation, &allocInfo);
    if (result != VK_SUCCESS) {
        UZ_LOG(RHI, Error, "vmaCreateBuffer failed: size={}, result={}",
               desc.sizeBytes, static_cast<int>(result));
        return RHIBufferHandle::Invalid();
    }

    // Debug name via VK_EXT_debug_utils
    if (desc.debugName && vkSetDebugUtilsObjectNameEXT) {
        VkDebugUtilsObjectNameInfoEXT nameInfo = {};
        nameInfo.sType = VK_STRUCTURE_TYPE_DEBUG_UTILS_OBJECT_NAME_INFO_EXT;
        nameInfo.objectType = VK_OBJECT_TYPE_BUFFER;
        nameInfo.objectHandle = reinterpret_cast<uint64_t>(buffer);
        nameInfo.pObjectName = desc.debugName;
        vkSetDebugUtilsObjectNameEXT(m_device, &nameInfo);
    }

    uint32_t generation = 0;
    uint32_t index = m_bufferPool.Allocate(generation);
    VulkanBuffer* slot = m_bufferPool.Get(index, generation);
    if (!slot) {
        vmaDestroyBuffer(m_allocator, buffer, allocation);
        UZ_LOG(RHI, Error, "CreateBuffer: pool allocation failed");
        return RHIBufferHandle::Invalid();
    }

    slot->buffer = buffer;
    slot->allocation = allocation;
    slot->desc = desc;
    slot->generation = generation;
    slot->mappedPtr = allocInfo.pMappedData;

    // Cache the buffer device address for GPU address lookups
    {
        VkBufferDeviceAddressInfo addrInfo = {};
        addrInfo.sType = VK_STRUCTURE_TYPE_BUFFER_DEVICE_ADDRESS_INFO;
        addrInfo.buffer = buffer;
        slot->gpuAddress = vkGetBufferDeviceAddress(m_device, &addrInfo);
    }

    // Assign logical SRV index for structured buffers
    if (HasFlag(desc.usage, RHIBufferUsage::StructuredBuffer) && desc.stride > 0) {
        slot->srvIndex = m_nextSrvIndex++;
    }

    // Assign logical UAV index for storage/unordered access buffers
    if (HasFlag(desc.usage, RHIBufferUsage::UnorderedAccess)) {
        slot->uavIndex = m_nextSrvIndex++;
    }

    UZ_LOG(RHI, Debug, "CreateBuffer: size={}, stride={} (name='{}')",
           desc.sizeBytes, desc.stride, desc.debugName ? desc.debugName : "");

    return {index, generation};
}

void VulkanDevice::DestroyBuffer(RHIBufferHandle handle) {
    UZ_PROFILE_FUNCTION();
    VulkanBuffer* buf = m_bufferPool.Get(handle.index, handle.generation);
    if (!buf) {
        UZ_LOG(RHI, Warning, "DestroyBuffer: invalid handle (idx={}, gen={})",
               handle.index, handle.generation);
        return;
    }
    if (buf->bufferView != VK_NULL_HANDLE) {
        vkDestroyBufferView(m_device, buf->bufferView, nullptr);
        buf->bufferView = VK_NULL_HANDLE;
    }
    if (buf->buffer != VK_NULL_HANDLE) {
        vmaDestroyBuffer(m_allocator, buf->buffer, buf->allocation);
        buf->buffer = VK_NULL_HANDLE;
        buf->allocation = nullptr;
    }
    buf->mappedPtr = nullptr;
    m_bufferPool.Free(handle.index);
}

void* VulkanDevice::MapBuffer(RHIBufferHandle handle) {
    VulkanBuffer* buf = m_bufferPool.Get(handle.index, handle.generation);
    if (!buf) return nullptr;

    // VMA persistent mapping — already mapped at creation for Upload/Readback
    if (buf->mappedPtr) return buf->mappedPtr;

    // Not a mappable buffer
    if (buf->desc.memory == RHIMemoryType::Default) return nullptr;

    // Fallback: map explicitly (should not normally happen for Upload/Readback)
    void* data = nullptr;
    VkResult result = vmaMapMemory(m_allocator, buf->allocation, &data);
    if (result != VK_SUCCESS) {
        UZ_LOG(RHI, Error, "MapBuffer: vmaMapMemory failed, result={}", static_cast<int>(result));
        return nullptr;
    }
    return data;
}

void VulkanDevice::UnmapBuffer(RHIBufferHandle handle) {
    // All mappable Vulkan buffers use VMA_ALLOCATION_CREATE_MAPPED_BIT (persistent mapping).
    // Explicit unmap is not needed — VMA manages the mapping lifetime.
    // UZP-MOD-013: the host writes are flushed, so the GPU sees them on memory that is not
    // HOST_COHERENT too (a no-op on coherent memory).
    VulkanBuffer* buf = m_bufferPool.Get(handle.index, handle.generation);
    if (buf && buf->allocation && buf->desc.memory != RHIMemoryType::Default) {
        vmaFlushAllocation(m_allocator, buf->allocation, 0, VK_WHOLE_SIZE);
    }
}

uint32_t VulkanDevice::GetBufferSRVIndex(RHIBufferHandle handle) const {
    const VulkanBuffer* buf = m_bufferPool.Get(handle.index, handle.generation);
    if (!buf) return UINT32_MAX;
    return buf->srvIndex;
}

uint32_t VulkanDevice::GetBufferUAVIndex(RHIBufferHandle handle) const {
    const VulkanBuffer* buf = m_bufferPool.Get(handle.index, handle.generation);
    if (!buf) return UINT32_MAX;
    return buf->uavIndex;
}

uint64_t VulkanDevice::GetBufferGPUAddress(RHIBufferHandle handle) const {
    const VulkanBuffer* buf = m_bufferPool.Get(handle.index, handle.generation);
    if (!buf || buf->buffer == VK_NULL_HANDLE) return 0;
    return buf->gpuAddress;
}

VulkanDevice::BufferAddressLookup VulkanDevice::FindBufferByGPUAddress(uint64_t gpuAddress) const {
    const auto& slots = m_bufferPool.Slots();
    for (const auto& buf : slots) {
        if (buf.buffer == VK_NULL_HANDLE || buf.gpuAddress == 0 || buf.generation == 0) continue;
        const uint64_t bufEnd = buf.gpuAddress + buf.desc.sizeBytes;
        if (gpuAddress >= buf.gpuAddress && gpuAddress < bufEnd) {
            return { buf.buffer, gpuAddress - buf.gpuAddress, buf.desc.sizeBytes };
        }
    }
    return {};
}

// ─────────────────────────────────────────────────────────────────────────────
// Texture Operations
// ─────────────────────────────────────────────────────────────────────────────

RHITextureHandle VulkanDevice::CreateTexture(const RHITextureDesc& desc) {
    UZ_PROFILE_FUNCTION();

    VkImageCreateInfo imageCI = {};
    imageCI.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    imageCI.imageType = desc.is3D ? VK_IMAGE_TYPE_3D : VK_IMAGE_TYPE_2D;
    imageCI.format = ToVkFormat(desc.format);
    imageCI.extent = {desc.width, desc.height, desc.is3D ? static_cast<uint32_t>(desc.depthOrArraySize) : 1u};
    imageCI.mipLevels = desc.mipLevels;
    imageCI.arrayLayers = desc.is3D ? 1u : static_cast<uint32_t>(desc.depthOrArraySize);
    imageCI.samples = VK_SAMPLE_COUNT_1_BIT;
    imageCI.tiling = VK_IMAGE_TILING_OPTIMAL;
    imageCI.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    imageCI.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;

    // Map usage flags
    VkImageUsageFlags usageFlags = 0;
    if (HasFlag(desc.usage, RHITextureUsage::ShaderResource))  usageFlags |= VK_IMAGE_USAGE_SAMPLED_BIT;
    if (HasFlag(desc.usage, RHITextureUsage::RenderTarget))    usageFlags |= VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
    if (HasFlag(desc.usage, RHITextureUsage::DepthStencil))    usageFlags |= VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT;
    if (HasFlag(desc.usage, RHITextureUsage::UnorderedAccess)) usageFlags |= VK_IMAGE_USAGE_STORAGE_BIT;
    if (HasFlag(desc.usage, RHITextureUsage::CopySrc))         usageFlags |= VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
    if (HasFlag(desc.usage, RHITextureUsage::CopyDst))         usageFlags |= VK_IMAGE_USAGE_TRANSFER_DST_BIT;

    // Always add transfer bits for flexibility
    usageFlags |= VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;

    imageCI.usage = usageFlags;

    // Cube map flag
    if (desc.depthOrArraySize == 6) {
        imageCI.flags |= VK_IMAGE_CREATE_CUBE_COMPATIBLE_BIT;
    }

    VmaAllocationCreateInfo allocCI = {};
    allocCI.usage = VMA_MEMORY_USAGE_GPU_ONLY;

    VkImage image = VK_NULL_HANDLE;
    VmaAllocation allocation = nullptr;
    VkResult result = vmaCreateImage(m_allocator, &imageCI, &allocCI, &image, &allocation, nullptr);
    if (result != VK_SUCCESS) {
        UZ_LOG(RHI, Error, "vmaCreateImage failed: {}x{}, result={}",
               desc.width, desc.height, static_cast<int>(result));
        return RHITextureHandle::Invalid();
    }

    // Debug name
    if (desc.debugName && vkSetDebugUtilsObjectNameEXT) {
        VkDebugUtilsObjectNameInfoEXT nameInfo = {};
        nameInfo.sType = VK_STRUCTURE_TYPE_DEBUG_UTILS_OBJECT_NAME_INFO_EXT;
        nameInfo.objectType = VK_OBJECT_TYPE_IMAGE;
        nameInfo.objectHandle = reinterpret_cast<uint64_t>(image);
        nameInfo.pObjectName = desc.debugName;
        vkSetDebugUtilsObjectNameEXT(m_device, &nameInfo);
    }

    // Create image view
    VkImageViewCreateInfo viewCI = {};
    viewCI.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    viewCI.image = image;
    viewCI.format = ToVkFormat(desc.format);
    viewCI.subresourceRange.baseMipLevel = 0;
    viewCI.subresourceRange.levelCount = desc.mipLevels;
    viewCI.subresourceRange.baseArrayLayer = 0;
    viewCI.subresourceRange.layerCount = desc.is3D ? 1u : static_cast<uint32_t>(desc.depthOrArraySize);

    if (IsDepthFormat(desc.format)) {
        viewCI.subresourceRange.aspectMask = VK_IMAGE_ASPECT_DEPTH_BIT;
        if (HasStencil(desc.format)) {
            viewCI.subresourceRange.aspectMask |= VK_IMAGE_ASPECT_STENCIL_BIT;
        }
    } else {
        viewCI.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    }

    if (desc.is3D) {
        viewCI.viewType = VK_IMAGE_VIEW_TYPE_3D;
    } else if (desc.depthOrArraySize == 6) {
        viewCI.viewType = VK_IMAGE_VIEW_TYPE_CUBE;
    } else if (desc.depthOrArraySize > 1) {
        viewCI.viewType = VK_IMAGE_VIEW_TYPE_2D_ARRAY;
    } else {
        viewCI.viewType = VK_IMAGE_VIEW_TYPE_2D;
    }

    VkImageView imageView = VK_NULL_HANDLE;
    result = vkCreateImageView(m_device, &viewCI, nullptr, &imageView);
    if (result != VK_SUCCESS) {
        UZ_LOG(RHI, Error, "vkCreateImageView failed, result={}", static_cast<int>(result));
        vmaDestroyImage(m_allocator, image, allocation);
        return RHITextureHandle::Invalid();
    }

    uint32_t generation = 0;
    uint32_t index = m_texturePool.Allocate(generation);
    VulkanTexture* slot = m_texturePool.Get(index, generation);
    if (!slot) {
        vkDestroyImageView(m_device, imageView, nullptr);
        vmaDestroyImage(m_allocator, image, allocation);
        UZ_LOG(RHI, Error, "CreateTexture: pool allocation failed");
        return RHITextureHandle::Invalid();
    }

    slot->image = image;
    slot->allocation = allocation;
    slot->imageView = imageView;
    slot->currentLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    slot->desc = desc;
    slot->generation = generation;
    slot->ownsImage = true;

    // Assign logical descriptor indices
    if (HasFlag(desc.usage, RHITextureUsage::ShaderResource)) {
        slot->srvIndex = m_nextSrvIndex++;
    }
    if (HasFlag(desc.usage, RHITextureUsage::RenderTarget)) {
        slot->rtvIndex = m_nextSrvIndex++;
    }
    if (HasFlag(desc.usage, RHITextureUsage::DepthStencil)) {
        slot->dsvIndex = m_nextSrvIndex++;
    }
    AssignBindlessSlot(*slot);  // UZP-MOD-007

    UZ_LOG(RHI, Debug, "CreateTexture: {}x{}, mips={} (name='{}')",
           desc.width, desc.height, desc.mipLevels,
           desc.debugName ? desc.debugName : "");

    return {index, generation};
}

void VulkanDevice::DestroyTexture(RHITextureHandle handle) {
    UZ_PROFILE_FUNCTION();
    VulkanTexture* tex = m_texturePool.Get(handle.index, handle.generation);
    if (!tex) {
        UZ_LOG(RHI, Warning, "DestroyTexture: invalid handle (idx={}, gen={})",
               handle.index, handle.generation);
        return;
    }
    if (tex->imageView != VK_NULL_HANDLE) {
        vkDestroyImageView(m_device, tex->imageView, nullptr);
        tex->imageView = VK_NULL_HANDLE;
    }
    if (tex->ownsImage && tex->image != VK_NULL_HANDLE) {
        vmaDestroyImage(m_allocator, tex->image, tex->allocation);
        tex->image = VK_NULL_HANDLE;
        tex->allocation = nullptr;
    }
    // UZP-MOD-007: the bindless slot is released; partially bound, it is not read until a later
    // texture takes it and writes its own view there.
    if (tex->bindlessIndex != UINT32_MAX) {
        m_bindlessFree.push_back(tex->bindlessIndex);
        tex->bindlessIndex = UINT32_MAX;
    }
    m_texturePool.Free(handle.index);
}

uint32_t VulkanDevice::GetTextureBindlessIndex(RHITextureHandle handle) const {  // UZP-MOD-007
    const VulkanTexture* tex = m_texturePool.Get(handle.index, handle.generation);
    return tex ? tex->bindlessIndex : UINT32_MAX;
}

uint32_t VulkanDevice::GetTextureSRVIndex(RHITextureHandle handle) const {
    const VulkanTexture* tex = m_texturePool.Get(handle.index, handle.generation);
    if (!tex) return UINT32_MAX;
    return tex->srvIndex;
}

uint32_t VulkanDevice::GetTextureUAVIndex(RHITextureHandle handle) const {
    const auto* tex = m_texturePool.Get(handle.index, handle.generation);
    if (!tex || !tex->imageView) return UINT32_MAX;
    // Vulkan doesn't use bindless descriptor indices for UAV.
    // Return pool index as sentinel so callers detect "UAV available".
    return handle.index;
}

RHITextureDesc VulkanDevice::GetTextureDesc(RHITextureHandle handle) const {
    const VulkanTexture* tex = m_texturePool.Get(handle.index, handle.generation);
    if (!tex) return {};
    return tex->desc;
}

// ─────────────────────────────────────────────────────────────────────────────
// Shader Operations
// ─────────────────────────────────────────────────────────────────────────────

RHIShaderHandle VulkanDevice::CreateShader(const RHIShaderDesc& desc) {
    UZ_PROFILE_FUNCTION();
    if (!desc.bytecode || desc.bytecodeSize == 0) {
        UZ_LOG(RHI, Error, "CreateShader: null/empty bytecode (name='{}')",
               desc.debugName ? desc.debugName : "");
        return RHIShaderHandle::Invalid();
    }

    VkShaderModuleCreateInfo moduleCI = {};
    moduleCI.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
    moduleCI.codeSize = static_cast<size_t>(desc.bytecodeSize);
    moduleCI.pCode = reinterpret_cast<const uint32_t*>(desc.bytecode);

    VkShaderModule shaderModule = VK_NULL_HANDLE;
    VkResult result = vkCreateShaderModule(m_device, &moduleCI, nullptr, &shaderModule);
    if (result != VK_SUCCESS) {
        UZ_LOG(RHI, Error, "vkCreateShaderModule failed, result={} (name='{}')",
               static_cast<int>(result), desc.debugName ? desc.debugName : "");
        return RHIShaderHandle::Invalid();
    }

    // Debug name
    if (desc.debugName && vkSetDebugUtilsObjectNameEXT) {
        VkDebugUtilsObjectNameInfoEXT nameInfo = {};
        nameInfo.sType = VK_STRUCTURE_TYPE_DEBUG_UTILS_OBJECT_NAME_INFO_EXT;
        nameInfo.objectType = VK_OBJECT_TYPE_SHADER_MODULE;
        nameInfo.objectHandle = reinterpret_cast<uint64_t>(shaderModule);
        nameInfo.pObjectName = desc.debugName;
        vkSetDebugUtilsObjectNameEXT(m_device, &nameInfo);
    }

    uint32_t generation = 0;
    uint32_t index = m_shaderPool.Allocate(generation);
    VulkanShader* slot = m_shaderPool.Get(index, generation);
    if (!slot) {
        vkDestroyShaderModule(m_device, shaderModule, nullptr);
        UZ_LOG(RHI, Error, "CreateShader: pool allocation failed");
        return RHIShaderHandle::Invalid();
    }

    slot->module = shaderModule;
    slot->bytecode.assign(
        static_cast<const uint8_t*>(desc.bytecode),
        static_cast<const uint8_t*>(desc.bytecode) + desc.bytecodeSize);
    slot->stage = desc.stage;
    slot->generation = generation;

    UZ_LOG(RHI, Debug, "CreateShader: stage={}, size={} (name='{}')",
           static_cast<int>(desc.stage), desc.bytecodeSize,
           desc.debugName ? desc.debugName : "");

    return {index, generation};
}

void VulkanDevice::DestroyShader(RHIShaderHandle handle) {
    UZ_PROFILE_FUNCTION();
    VulkanShader* shader = m_shaderPool.Get(handle.index, handle.generation);
    if (!shader) {
        UZ_LOG(RHI, Warning, "DestroyShader: invalid handle (idx={}, gen={})",
               handle.index, handle.generation);
        return;
    }
    if (shader->module != VK_NULL_HANDLE) {
        vkDestroyShaderModule(m_device, shader->module, nullptr);
        shader->module = VK_NULL_HANDLE;
    }
    shader->bytecode.clear();
    m_shaderPool.Free(handle.index);
}

// ─────────────────────────────────────────────────────────────────────────────
// Pipeline Operations
// ─────────────────────────────────────────────────────────────────────────────

RHIPipelineHandle VulkanDevice::CreateGraphicsPipeline(const RHIGraphicsPipelineDesc& desc) {
    UZ_PROFILE_FUNCTION();

    // Shader stages
    std::vector<VkPipelineShaderStageCreateInfo> shaderStages;

    VulkanShader* vsShader = m_shaderPool.Get(desc.vertexShader.index, desc.vertexShader.generation);
    if (!vsShader || vsShader->module == VK_NULL_HANDLE) {
        UZ_LOG(RHI, Error, "CreateGraphicsPipeline: invalid vertex shader");
        return RHIPipelineHandle::Invalid();
    }

    VkPipelineShaderStageCreateInfo vsStage = {};
    vsStage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    vsStage.stage = VK_SHADER_STAGE_VERTEX_BIT;
    vsStage.module = vsShader->module;
    vsStage.pName = "main";
    shaderStages.push_back(vsStage);

    if (desc.pixelShader.IsValid()) {
        VulkanShader* psShader = m_shaderPool.Get(desc.pixelShader.index, desc.pixelShader.generation);
        if (psShader && psShader->module != VK_NULL_HANDLE) {
            VkPipelineShaderStageCreateInfo psStage = {};
            psStage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
            psStage.stage = VK_SHADER_STAGE_FRAGMENT_BIT;
            psStage.module = psShader->module;
            psStage.pName = "main";
            shaderStages.push_back(psStage);
        }
    }

    // Vertex input
    VkPipelineVertexInputStateCreateInfo vertexInputCI = {};
    vertexInputCI.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;

    VkVertexInputBindingDescription bindingDesc = {};
    std::vector<VkVertexInputAttributeDescription> attributeDescs;

    if (desc.inputElementCount > 0 && desc.inputElements) {
        bindingDesc.binding = 0;
        bindingDesc.stride = desc.vertexStride;
        bindingDesc.inputRate = VK_VERTEX_INPUT_RATE_VERTEX;

        attributeDescs.resize(desc.inputElementCount);
        for (uint32_t i = 0; i < desc.inputElementCount; ++i) {
            const auto& elem = desc.inputElements[i];
            attributeDescs[i].binding = elem.inputSlot;
            attributeDescs[i].location = i;
            attributeDescs[i].format = ToVkFormat(elem.format);
            attributeDescs[i].offset = elem.byteOffset;
        }

        vertexInputCI.vertexBindingDescriptionCount = 1;
        vertexInputCI.pVertexBindingDescriptions = &bindingDesc;
        vertexInputCI.vertexAttributeDescriptionCount = static_cast<uint32_t>(attributeDescs.size());
        vertexInputCI.pVertexAttributeDescriptions = attributeDescs.data();
    }

    // Input assembly
    VkPipelineInputAssemblyStateCreateInfo inputAssemblyCI = {};
    inputAssemblyCI.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
    inputAssemblyCI.topology = ToVkTopology(desc.topology);
    inputAssemblyCI.primitiveRestartEnable = VK_FALSE;

    // Viewport/scissor — dynamic state
    VkPipelineViewportStateCreateInfo viewportCI = {};
    viewportCI.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
    viewportCI.viewportCount = 1;
    viewportCI.scissorCount = 1;

    // Rasterizer
    VkPipelineRasterizationStateCreateInfo rasterizerCI = {};
    rasterizerCI.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
    rasterizerCI.depthClampEnable = VK_FALSE;
    rasterizerCI.rasterizerDiscardEnable = VK_FALSE;
    rasterizerCI.polygonMode = (desc.rasterizer.fillMode == RHIFillMode::Wireframe)
                                   ? VK_POLYGON_MODE_LINE : VK_POLYGON_MODE_FILL;
    rasterizerCI.cullMode = ToVkCullMode(desc.rasterizer.cullMode);
    rasterizerCI.frontFace = desc.rasterizer.frontCounterClockwise
                                 ? VK_FRONT_FACE_COUNTER_CLOCKWISE : VK_FRONT_FACE_CLOCKWISE;
    rasterizerCI.depthBiasEnable = (desc.rasterizer.depthBias != 0.0f || desc.rasterizer.slopeScaledDepthBias != 0.0f)
                                       ? VK_TRUE : VK_FALSE;
    rasterizerCI.depthBiasConstantFactor = desc.rasterizer.depthBias;
    rasterizerCI.depthBiasSlopeFactor = desc.rasterizer.slopeScaledDepthBias;
    rasterizerCI.lineWidth = 1.0f;

    // Multisample — no MSAA
    VkPipelineMultisampleStateCreateInfo msCI = {};
    msCI.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
    msCI.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;

    // Depth-stencil
    VkPipelineDepthStencilStateCreateInfo depthStencilCI = {};
    depthStencilCI.sType = VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO;
    depthStencilCI.depthTestEnable = desc.depthStencil.depthEnable ? VK_TRUE : VK_FALSE;
    depthStencilCI.depthWriteEnable = desc.depthStencil.depthWrite ? VK_TRUE : VK_FALSE;
    depthStencilCI.depthCompareOp = ToVkCompareOp(desc.depthStencil.depthFunc);

    // Color blend
    VkPipelineColorBlendAttachmentState blendAttachments[8] = {};
    for (uint32_t i = 0; i < desc.renderTargetCount; ++i) {
        const auto& blend = desc.renderTargetBlend[i];
        blendAttachments[i].colorWriteMask = VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT
                                           | VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT;
        blendAttachments[i].blendEnable = blend.blendEnable ? VK_TRUE : VK_FALSE;
        blendAttachments[i].srcColorBlendFactor = ToVkBlendFactor(blend.srcColor);
        blendAttachments[i].dstColorBlendFactor = ToVkBlendFactor(blend.dstColor);
        blendAttachments[i].colorBlendOp = ToVkBlendOp(blend.colorOp);
        blendAttachments[i].srcAlphaBlendFactor = ToVkBlendFactor(blend.srcAlpha);
        blendAttachments[i].dstAlphaBlendFactor = ToVkBlendFactor(blend.dstAlpha);
        blendAttachments[i].alphaBlendOp = ToVkBlendOp(blend.alphaOp);
    }

    VkPipelineColorBlendStateCreateInfo colorBlendCI = {};
    colorBlendCI.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
    colorBlendCI.attachmentCount = desc.renderTargetCount;
    colorBlendCI.pAttachments = blendAttachments;

    // Dynamic state: viewport and scissor
    VkDynamicState dynamicStates[] = {VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR};
    VkPipelineDynamicStateCreateInfo dynamicStateCI = {};
    dynamicStateCI.sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO;
    dynamicStateCI.dynamicStateCount = 2;
    dynamicStateCI.pDynamicStates = dynamicStates;

    // Dynamic rendering — specify color attachment formats in pNext chain
    std::vector<VkFormat> colorFormats;
    colorFormats.reserve(desc.renderTargetCount);
    for (uint32_t i = 0; i < desc.renderTargetCount; ++i) {
        colorFormats.push_back(ToVkFormat(desc.renderTargetFormats[i]));
    }

    VkPipelineRenderingCreateInfo renderingCI = {};
    renderingCI.sType = VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO;
    renderingCI.colorAttachmentCount = static_cast<uint32_t>(colorFormats.size());
    renderingCI.pColorAttachmentFormats = colorFormats.data();
    renderingCI.depthAttachmentFormat = (desc.depthStencilFormat != RHIFormat::Unknown)
                                            ? ToVkFormat(desc.depthStencilFormat) : VK_FORMAT_UNDEFINED;
    renderingCI.stencilAttachmentFormat = HasStencil(desc.depthStencilFormat)
                                              ? ToVkFormat(desc.depthStencilFormat) : VK_FORMAT_UNDEFINED;

    // Create the pipeline
    VkGraphicsPipelineCreateInfo pipelineCI = {};
    pipelineCI.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
    pipelineCI.pNext = &renderingCI;
    pipelineCI.stageCount = static_cast<uint32_t>(shaderStages.size());
    pipelineCI.pStages = shaderStages.data();
    pipelineCI.pVertexInputState = &vertexInputCI;
    pipelineCI.pInputAssemblyState = &inputAssemblyCI;
    pipelineCI.pViewportState = &viewportCI;
    pipelineCI.pRasterizationState = &rasterizerCI;
    pipelineCI.pMultisampleState = &msCI;
    pipelineCI.pDepthStencilState = &depthStencilCI;
    pipelineCI.pColorBlendState = &colorBlendCI;
    pipelineCI.pDynamicState = &dynamicStateCI;
    pipelineCI.layout = m_pipelineLayout;
    pipelineCI.renderPass = VK_NULL_HANDLE; // Dynamic rendering — no render pass

    VkPipeline pipeline = VK_NULL_HANDLE;
    VkResult pipelineResult = vkCreateGraphicsPipelines(
        m_device, VK_NULL_HANDLE, 1, &pipelineCI, nullptr, &pipeline);
    if (pipelineResult != VK_SUCCESS) {
        UZ_LOG(RHI, Error, "vkCreateGraphicsPipelines failed, result={} (name='{}')",
               static_cast<int>(pipelineResult), desc.debugName ? desc.debugName : "");
        return RHIPipelineHandle::Invalid();
    }

    // Debug name
    if (desc.debugName && vkSetDebugUtilsObjectNameEXT) {
        VkDebugUtilsObjectNameInfoEXT nameInfo = {};
        nameInfo.sType = VK_STRUCTURE_TYPE_DEBUG_UTILS_OBJECT_NAME_INFO_EXT;
        nameInfo.objectType = VK_OBJECT_TYPE_PIPELINE;
        nameInfo.objectHandle = reinterpret_cast<uint64_t>(pipeline);
        nameInfo.pObjectName = desc.debugName;
        vkSetDebugUtilsObjectNameEXT(m_device, &nameInfo);
    }

    uint32_t generation = 0;
    uint32_t index = m_pipelinePool.Allocate(generation);
    VulkanPipeline* slot = m_pipelinePool.Get(index, generation);
    if (!slot) {
        vkDestroyPipeline(m_device, pipeline, nullptr);
        UZ_LOG(RHI, Error, "CreateGraphicsPipeline: pool allocation failed");
        return RHIPipelineHandle::Invalid();
    }

    slot->pipeline = pipeline;
    slot->pipelineLayout = m_pipelineLayout;
    slot->topology = desc.topology;
    slot->generation = generation;
    slot->desc = desc;

    UZ_LOG(RHI, Debug, "CreateGraphicsPipeline: {} RT(s) (name='{}')",
           desc.renderTargetCount, desc.debugName ? desc.debugName : "");

    return {index, generation};
}

RHIPipelineHandle VulkanDevice::CreateComputePipeline(const RHIComputePipelineDesc& desc) {
    UZ_PROFILE_FUNCTION();

    // Resolve compute shader module from pool
    VulkanShader* csShader = m_shaderPool.Get(desc.computeShader.index, desc.computeShader.generation);
    if (!csShader || csShader->module == VK_NULL_HANDLE) {
        UZ_LOG(RHI, Error, "CreateComputePipeline: invalid compute shader handle (name='{}')",
               desc.debugName ? desc.debugName : "");
        return RHIPipelineHandle::Invalid();
    }

    VkPipelineShaderStageCreateInfo stageCI = {};
    stageCI.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stageCI.stage = VK_SHADER_STAGE_COMPUTE_BIT;
    stageCI.module = csShader->module;
    stageCI.pName = "main";

    VkComputePipelineCreateInfo pipelineCI = {};
    pipelineCI.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO;
    pipelineCI.stage = stageCI;
    pipelineCI.layout = m_pipelineLayout;

    VkPipeline pipeline = VK_NULL_HANDLE;
    VkResult result = vkCreateComputePipelines(m_device, VK_NULL_HANDLE, 1, &pipelineCI, nullptr, &pipeline);
    if (result != VK_SUCCESS) {
        UZ_LOG(RHI, Error, "vkCreateComputePipelines failed, result={} (name='{}')",
               static_cast<int>(result), desc.debugName ? desc.debugName : "");
        return RHIPipelineHandle::Invalid();
    }

    // Debug name
    if (desc.debugName && vkSetDebugUtilsObjectNameEXT) {
        VkDebugUtilsObjectNameInfoEXT nameInfo = {};
        nameInfo.sType = VK_STRUCTURE_TYPE_DEBUG_UTILS_OBJECT_NAME_INFO_EXT;
        nameInfo.objectType = VK_OBJECT_TYPE_PIPELINE;
        nameInfo.objectHandle = reinterpret_cast<uint64_t>(pipeline);
        nameInfo.pObjectName = desc.debugName;
        vkSetDebugUtilsObjectNameEXT(m_device, &nameInfo);
    }

    uint32_t generation = 0;
    uint32_t index = m_pipelinePool.Allocate(generation);
    VulkanPipeline* slot = m_pipelinePool.Get(index, generation);
    if (!slot) {
        vkDestroyPipeline(m_device, pipeline, nullptr);
        UZ_LOG(RHI, Error, "CreateComputePipeline: pool allocation failed (name='{}')",
               desc.debugName ? desc.debugName : "");
        return RHIPipelineHandle::Invalid();
    }

    slot->pipeline = pipeline;
    slot->pipelineLayout = m_pipelineLayout;
    slot->isCompute = true;
    slot->generation = generation;

    UZ_LOG(RHI, Debug, "CreateComputePipeline: created (name='{}')",
           desc.debugName ? desc.debugName : "");

    return {index, generation};
}

void VulkanDevice::DestroyPipeline(RHIPipelineHandle handle) {
    UZ_PROFILE_FUNCTION();
    VulkanPipeline* pipeline = m_pipelinePool.Get(handle.index, handle.generation);
    if (!pipeline) {
        UZ_LOG(RHI, Warning, "DestroyPipeline: invalid handle (idx={}, gen={})",
               handle.index, handle.generation);
        return;
    }
    if (pipeline->pipeline != VK_NULL_HANDLE) {
        vkDestroyPipeline(m_device, pipeline->pipeline, nullptr);
        pipeline->pipeline = VK_NULL_HANDLE;
    }
    m_pipelinePool.Free(handle.index);
}

std::vector<uint8_t> VulkanDevice::GetPipelineCachedBlob(RHIPipelineHandle /*handle*/) {
    // Vulkan uses VkPipelineCache for disk persistence natively
    return {};
}

// ─────────────────────────────────────────────────────────────────────────────
// Sampler Operations
// ─────────────────────────────────────────────────────────────────────────────

RHISamplerHandle VulkanDevice::CreateSampler(const RHISamplerDesc& desc) {
    UZ_PROFILE_FUNCTION();

    VkSamplerCreateInfo samplerCI = {};
    samplerCI.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO;

    switch (desc.filter) {
        case RHIFilterMode::Point:
            samplerCI.magFilter = VK_FILTER_NEAREST;
            samplerCI.minFilter = VK_FILTER_NEAREST;
            samplerCI.mipmapMode = VK_SAMPLER_MIPMAP_MODE_NEAREST;
            break;
        case RHIFilterMode::Linear:
            samplerCI.magFilter = VK_FILTER_LINEAR;
            samplerCI.minFilter = VK_FILTER_LINEAR;
            samplerCI.mipmapMode = VK_SAMPLER_MIPMAP_MODE_LINEAR;
            break;
        case RHIFilterMode::Anisotropic:
            samplerCI.magFilter = VK_FILTER_LINEAR;
            samplerCI.minFilter = VK_FILTER_LINEAR;
            samplerCI.mipmapMode = VK_SAMPLER_MIPMAP_MODE_LINEAR;
            samplerCI.anisotropyEnable = VK_TRUE;
            samplerCI.maxAnisotropy = static_cast<float>(desc.maxAnisotropy);
            break;
    }

    samplerCI.addressModeU = ToVkAddressMode(desc.addressU);
    samplerCI.addressModeV = ToVkAddressMode(desc.addressV);
    samplerCI.addressModeW = ToVkAddressMode(desc.addressW);
    samplerCI.mipLodBias = desc.mipLodBias;
    samplerCI.compareEnable = (desc.compareFunc != RHICompareFunc::Never) ? VK_TRUE : VK_FALSE;
    samplerCI.compareOp = ToVkCompareOp(desc.compareFunc);
    samplerCI.minLod = desc.minLod;
    samplerCI.maxLod = desc.maxLod;
    samplerCI.borderColor = VK_BORDER_COLOR_FLOAT_OPAQUE_BLACK;

    VkSampler sampler = VK_NULL_HANDLE;
    VkResult result = vkCreateSampler(m_device, &samplerCI, nullptr, &sampler);
    if (result != VK_SUCCESS) {
        UZ_LOG(RHI, Error, "vkCreateSampler failed, result={}", static_cast<int>(result));
        return RHISamplerHandle::Invalid();
    }

    uint32_t generation = 0;
    uint32_t index = m_samplerPool.Allocate(generation);
    VulkanSampler* slot = m_samplerPool.Get(index, generation);
    if (!slot) {
        vkDestroySampler(m_device, sampler, nullptr);
        UZ_LOG(RHI, Error, "CreateSampler: pool allocation failed");
        return RHISamplerHandle::Invalid();
    }

    slot->sampler = sampler;
    slot->samplerIndex = m_nextSamplerIndex++;
    slot->generation = generation;

    UZ_LOG(RHI, Debug, "CreateSampler: index={} (name='{}')",
           slot->samplerIndex, desc.debugName ? desc.debugName : "");

    return {index, generation};
}

void VulkanDevice::DestroySampler(RHISamplerHandle handle) {
    UZ_PROFILE_FUNCTION();
    VulkanSampler* sampler = m_samplerPool.Get(handle.index, handle.generation);
    if (!sampler) {
        UZ_LOG(RHI, Warning, "DestroySampler: invalid handle (idx={}, gen={})",
               handle.index, handle.generation);
        return;
    }
    if (sampler->sampler != VK_NULL_HANDLE) {
        vkDestroySampler(m_device, sampler->sampler, nullptr);
        sampler->sampler = VK_NULL_HANDLE;
    }
    m_samplerPool.Free(handle.index);
}

uint32_t VulkanDevice::GetSamplerIndex(RHISamplerHandle handle) const {
    const VulkanSampler* sampler = m_samplerPool.Get(handle.index, handle.generation);
    if (!sampler) return UINT32_MAX;
    return sampler->samplerIndex;
}

// ─────────────────────────────────────────────────────────────────────────────
// UZP-MOD-007: Acceleration structures (VK_KHR_acceleration_structure)
// ─────────────────────────────────────────────────────────────────────────────

namespace {

VkBuildAccelerationStructureFlagsKHR ToVkASBuildFlags(RHIASBuildFlags flags) {
    VkBuildAccelerationStructureFlagsKHR out = 0;
    if (HasFlag(flags, RHIASBuildFlags::AllowUpdate))     out |= VK_BUILD_ACCELERATION_STRUCTURE_ALLOW_UPDATE_BIT_KHR;
    if (HasFlag(flags, RHIASBuildFlags::AllowCompaction)) out |= VK_BUILD_ACCELERATION_STRUCTURE_ALLOW_COMPACTION_BIT_KHR;
    if (HasFlag(flags, RHIASBuildFlags::PreferFastTrace)) out |= VK_BUILD_ACCELERATION_STRUCTURE_PREFER_FAST_TRACE_BIT_KHR;
    if (HasFlag(flags, RHIASBuildFlags::PreferFastBuild)) out |= VK_BUILD_ACCELERATION_STRUCTURE_PREFER_FAST_BUILD_BIT_KHR;
    return out;
}

/// Releases what `CreateASStorage` created, in reverse order, and clears the fields.
template <class AS>
void DestroyASStorage(VkDevice device, VmaAllocator allocator, AS& as) {
    if (as.handle != VK_NULL_HANDLE) vkDestroyAccelerationStructureKHR(device, as.handle, nullptr);
    if (as.resultBuffer != VK_NULL_HANDLE) vmaDestroyBuffer(allocator, as.resultBuffer, as.resultAllocation);
    if (as.scratchBuffer != VK_NULL_HANDLE) vmaDestroyBuffer(allocator, as.scratchBuffer, as.scratchAllocation);
    as.handle = VK_NULL_HANDLE;
    as.resultBuffer = VK_NULL_HANDLE;
    as.resultAllocation = nullptr;
    as.scratchBuffer = VK_NULL_HANDLE;
    as.scratchAllocation = nullptr;
}

/// The storage buffer (the structure at offset 0), the acceleration structure, its device address
/// and a scratch buffer for a build and, with `allowUpdate`, an update, whose device address is a
/// multiple of `scratchAlignment`. Empty on success; on failure nothing is left allocated.
template <class AS>
std::string CreateASStorage(VkDevice device, VmaAllocator allocator, uint32_t scratchAlignment,
                            VkAccelerationStructureTypeKHR type,
                            const VkAccelerationStructureBuildSizesInfoKHR& sizes, bool allowUpdate, AS& as) {
    if (sizes.accelerationStructureSize == 0) return "the driver reported a zero acceleration-structure size";
    VmaAllocationCreateInfo gpuOnly = {};
    gpuOnly.usage = VMA_MEMORY_USAGE_GPU_ONLY;

    VkBufferCreateInfo resultCI = {};
    resultCI.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    resultCI.size = sizes.accelerationStructureSize;
    resultCI.usage = VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_STORAGE_BIT_KHR | VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT;
    resultCI.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    VkResult result = vmaCreateBuffer(allocator, &resultCI, &gpuOnly, &as.resultBuffer, &as.resultAllocation, nullptr);
    if (result != VK_SUCCESS) {
        as.resultBuffer = VK_NULL_HANDLE;
        return "the storage buffer of " + std::to_string(sizes.accelerationStructureSize) +
               " bytes was not allocated, result=" + std::to_string(static_cast<int>(result));
    }
    as.resultSizeBytes = sizes.accelerationStructureSize;

    VkAccelerationStructureCreateInfoKHR createCI = {};
    createCI.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_CREATE_INFO_KHR;
    createCI.buffer = as.resultBuffer;
    createCI.offset = 0;
    createCI.size = sizes.accelerationStructureSize;
    createCI.type = type;
    result = vkCreateAccelerationStructureKHR(device, &createCI, nullptr, &as.handle);
    if (result != VK_SUCCESS) {
        as.handle = VK_NULL_HANDLE;
        DestroyASStorage(device, allocator, as);
        return "vkCreateAccelerationStructureKHR failed, result=" + std::to_string(static_cast<int>(result));
    }
    VkAccelerationStructureDeviceAddressInfoKHR addressInfo = {};
    addressInfo.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_DEVICE_ADDRESS_INFO_KHR;
    addressInfo.accelerationStructure = as.handle;
    as.deviceAddress = vkGetAccelerationStructureDeviceAddressKHR(device, &addressInfo);

    as.buildScratchBytes = sizes.buildScratchSize;
    as.updateScratchBytes = allowUpdate ? sizes.updateScratchSize : 0;
    as.scratchSizeBytes = std::max<uint64_t>({sizes.buildScratchSize, as.updateScratchBytes, uint64_t{1}});
    const uint64_t alignment = std::max<uint64_t>(scratchAlignment, 1);
    VkBufferCreateInfo scratchCI = {};
    scratchCI.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    scratchCI.size = as.scratchSizeBytes;
    scratchCI.usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT;
    scratchCI.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    result = vmaCreateBufferWithAlignment(allocator, &scratchCI, &gpuOnly, alignment, &as.scratchBuffer,
                                          &as.scratchAllocation, nullptr);
    if (result != VK_SUCCESS) {
        as.scratchBuffer = VK_NULL_HANDLE;
        DestroyASStorage(device, allocator, as);
        return "the scratch buffer of " + std::to_string(as.scratchSizeBytes) +
               " bytes was not allocated, result=" + std::to_string(static_cast<int>(result));
    }
    VkBufferDeviceAddressInfo scratchAddress = {};
    scratchAddress.sType = VK_STRUCTURE_TYPE_BUFFER_DEVICE_ADDRESS_INFO;
    scratchAddress.buffer = as.scratchBuffer;
    as.scratchAddress = vkGetBufferDeviceAddress(device, &scratchAddress);
    if (as.deviceAddress == 0 || as.scratchAddress % alignment != 0) {
        DestroyASStorage(device, allocator, as);
        return "the scratch address is not a multiple of minAccelerationStructureScratchOffsetAlignment (" +
               std::to_string(alignment) + ") or the structure has no device address";
    }
    return {};
}

bool BothPreferences(RHIASBuildFlags flags) {
    return HasFlag(flags, RHIASBuildFlags::PreferFastTrace) && HasFlag(flags, RHIASBuildFlags::PreferFastBuild);
}

}  // namespace

RHIBLASHandle VulkanDevice::CreateBLAS(const RHIBLASDesc& desc) {
    UZ_PROFILE_FUNCTION();
    const char* name = desc.debugName ? desc.debugName : "(unnamed)";
    const auto refuse = [&](const std::string& why) {
        UZ_LOG(RHI, Error, "CreateBLAS '{}': {}", name, why);
        return RHIBLASHandle::Invalid();
    };
    if (!m_supportsAccelerationStructures) return refuse("acceleration structures are not enabled on this device");
    if (!desc.geometries || desc.geometryCount == 0) return refuse("no geometry");
    if (desc.geometryCount > m_asMaxGeometryCount) {
        return refuse(std::to_string(desc.geometryCount) + " geometries exceed maxGeometryCount " +
                      std::to_string(m_asMaxGeometryCount));
    }
    if (BothPreferences(desc.buildFlags)) return refuse("PreferFastTrace and PreferFastBuild are exclusive");

    VulkanBLAS blas;
    blas.buildFlags = ToVkASBuildFlags(desc.buildFlags);
    uint64_t totalPrimitives = 0;
    for (uint32_t i = 0; i < desc.geometryCount; ++i) {
        const RHIRTGeometryDesc& src = desc.geometries[i];
        const std::string geometry = "geometry " + std::to_string(i) + ": ";
        if (src.vertexFormat != RHIFormat::RGB32Float) return refuse(geometry + "the vertex format is not RGB32Float");
        if (src.vertexStride < 12 || src.vertexStride % 4 != 0) {
            return refuse(geometry + "vertex stride " + std::to_string(src.vertexStride) +
                          " is below 12 bytes or not a multiple of 4");
        }
        if (src.vertexCount == 0) return refuse(geometry + "no vertices");
        const VulkanBuffer* vb = m_bufferPool.Get(src.vertexBuffer.index, src.vertexBuffer.generation);
        if (!vb || vb->buffer == VK_NULL_HANDLE) return refuse(geometry + "the vertex buffer is not live");
        if (!HasFlag(vb->desc.usage, RHIBufferUsage::AccelerationStructureBuildInput)) {
            return refuse(geometry + "the vertex buffer lacks AccelerationStructureBuildInput");
        }
        const uint64_t vertexBytes = uint64_t{src.vertexCount - 1} * src.vertexStride + 12;
        if (vertexBytes > vb->desc.sizeBytes || vb->gpuAddress % 4 != 0) {
            return refuse(geometry + "the vertex buffer is smaller than " + std::to_string(vertexBytes) +
                          " bytes or its address is not 4-byte aligned");
        }

        VkAccelerationStructureGeometryKHR g = {};
        g.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_KHR;
        g.geometryType = VK_GEOMETRY_TYPE_TRIANGLES_KHR;
        g.flags = src.isOpaque ? VK_GEOMETRY_OPAQUE_BIT_KHR : 0;
        auto& tri = g.geometry.triangles;
        tri.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_TRIANGLES_DATA_KHR;
        tri.vertexFormat = VK_FORMAT_R32G32B32_SFLOAT;
        tri.vertexData.deviceAddress = vb->gpuAddress;
        tri.vertexStride = src.vertexStride;
        tri.maxVertex = src.vertexCount - 1;
        tri.transformData.deviceAddress = 0;
        uint32_t primitives = 0;
        if (src.indexCount > 0) {
            // As on DX12, an index buffer is used only with a non-zero index count.
            const VulkanBuffer* ib = m_bufferPool.Get(src.indexBuffer.index, src.indexBuffer.generation);
            if (!ib || ib->buffer == VK_NULL_HANDLE) return refuse(geometry + "the index buffer is not live");
            if (!HasFlag(ib->desc.usage, RHIBufferUsage::AccelerationStructureBuildInput)) {
                return refuse(geometry + "the index buffer lacks AccelerationStructureBuildInput");
            }
            const uint32_t indexSize = src.indexFormat == RHIIndexFormat::Uint16 ? 2 : 4;
            if (src.indexCount % 3 != 0) return refuse(geometry + "the index count is not a multiple of 3");
            if (uint64_t{src.indexCount} * indexSize > ib->desc.sizeBytes || ib->gpuAddress % indexSize != 0) {
                return refuse(geometry + "the index buffer is too small or misaligned");
            }
            tri.indexType = indexSize == 2 ? VK_INDEX_TYPE_UINT16 : VK_INDEX_TYPE_UINT32;
            tri.indexData.deviceAddress = ib->gpuAddress;
            primitives = src.indexCount / 3;
        } else {
            if (src.vertexCount % 3 != 0) return refuse(geometry + "the vertex count is not a multiple of 3");
            tri.indexType = VK_INDEX_TYPE_NONE_KHR;
            primitives = src.vertexCount / 3;
        }
        totalPrimitives += primitives;
        blas.geometries.push_back(g);
        blas.primitiveCounts.push_back(primitives);
    }
    if (totalPrimitives > m_asMaxPrimitiveCount) {
        return refuse(std::to_string(totalPrimitives) + " triangles exceed maxPrimitiveCount " +
                      std::to_string(m_asMaxPrimitiveCount));
    }

    VkAccelerationStructureBuildGeometryInfoKHR build = {};
    build.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_GEOMETRY_INFO_KHR;
    build.type = VK_ACCELERATION_STRUCTURE_TYPE_BOTTOM_LEVEL_KHR;
    build.flags = blas.buildFlags;
    build.mode = VK_BUILD_ACCELERATION_STRUCTURE_MODE_BUILD_KHR;
    build.geometryCount = static_cast<uint32_t>(blas.geometries.size());
    build.pGeometries = blas.geometries.data();
    VkAccelerationStructureBuildSizesInfoKHR sizes = {};
    sizes.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_SIZES_INFO_KHR;
    vkGetAccelerationStructureBuildSizesKHR(m_device, VK_ACCELERATION_STRUCTURE_BUILD_TYPE_DEVICE_KHR, &build,
                                            blas.primitiveCounts.data(), &sizes);
    const std::string error =
        CreateASStorage(m_device, m_allocator, m_asScratchAlignment, VK_ACCELERATION_STRUCTURE_TYPE_BOTTOM_LEVEL_KHR,
                        sizes, HasFlag(desc.buildFlags, RHIASBuildFlags::AllowUpdate), blas);
    if (!error.empty()) return refuse(error);

    uint32_t generation = 0;
    const uint32_t index = m_blasPool.Allocate(generation);
    VulkanBLAS* slot = m_blasPool.Get(index, generation);
    if (!slot) {
        DestroyASStorage(m_device, m_allocator, blas);
        return refuse("pool allocation failed");
    }
    *slot = std::move(blas);
    slot->generation = generation;
    UZ_LOG(RHI, Info, "Created BLAS '{}': {} geometries, result={}B, scratch={}B", name, slot->geometries.size(),
           slot->resultSizeBytes, slot->scratchSizeBytes);
    return {index, generation};
}

void VulkanDevice::DestroyBLAS(RHIBLASHandle handle) {
    VulkanBLAS* blas = m_blasPool.Get(handle.index, handle.generation);
    if (!blas || blas->handle == VK_NULL_HANDLE) return;  // invalid or already destroyed
    DestroyASStorage(m_device, m_allocator, *blas);
    const uint32_t generation = blas->generation;
    *blas = VulkanBLAS{};
    blas->generation = generation;
    m_blasPool.Free(handle.index);
}

uint64_t VulkanDevice::GetBLASGPUAddress(RHIBLASHandle handle) const {
    const VulkanBLAS* blas = m_blasPool.Get(handle.index, handle.generation);
    return blas && blas->handle != VK_NULL_HANDLE ? blas->deviceAddress : 0;
}

RHITLASHandle VulkanDevice::CreateTLAS(const RHITLASDesc& desc) {
    UZ_PROFILE_FUNCTION();
    const char* name = desc.debugName ? desc.debugName : "(unnamed)";
    const auto refuse = [&](const std::string& why) {
        UZ_LOG(RHI, Error, "CreateTLAS '{}': {}", name, why);
        return RHITLASHandle::Invalid();
    };
    if (!m_supportsAccelerationStructures) return refuse("acceleration structures are not enabled on this device");
    if (desc.maxInstanceCount == 0 || desc.maxInstanceCount > m_asMaxInstanceCount) {
        return refuse("maxInstanceCount " + std::to_string(desc.maxInstanceCount) + " is 0 or above " +
                      std::to_string(m_asMaxInstanceCount));
    }
    if (BothPreferences(desc.buildFlags)) return refuse("PreferFastTrace and PreferFastBuild are exclusive");

    VulkanTLAS tlas;
    tlas.buildFlags = ToVkASBuildFlags(desc.buildFlags);
    tlas.maxInstanceCount = desc.maxInstanceCount;
    VkAccelerationStructureGeometryKHR g = {};
    g.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_KHR;
    g.geometryType = VK_GEOMETRY_TYPE_INSTANCES_KHR;
    g.geometry.instances.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_GEOMETRY_INSTANCES_DATA_KHR;
    g.geometry.instances.arrayOfPointers = VK_FALSE;
    VkAccelerationStructureBuildGeometryInfoKHR build = {};
    build.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_GEOMETRY_INFO_KHR;
    build.type = VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR;
    build.flags = tlas.buildFlags;
    build.mode = VK_BUILD_ACCELERATION_STRUCTURE_MODE_BUILD_KHR;
    build.geometryCount = 1;
    build.pGeometries = &g;
    VkAccelerationStructureBuildSizesInfoKHR sizes = {};
    sizes.sType = VK_STRUCTURE_TYPE_ACCELERATION_STRUCTURE_BUILD_SIZES_INFO_KHR;
    vkGetAccelerationStructureBuildSizesKHR(m_device, VK_ACCELERATION_STRUCTURE_BUILD_TYPE_DEVICE_KHR, &build,
                                            &desc.maxInstanceCount, &sizes);
    const std::string error =
        CreateASStorage(m_device, m_allocator, m_asScratchAlignment, VK_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL_KHR,
                        sizes, HasFlag(desc.buildFlags, RHIASBuildFlags::AllowUpdate), tlas);
    if (!error.empty()) return refuse(error);

    uint32_t generation = 0;
    const uint32_t index = m_tlasPool.Allocate(generation);
    VulkanTLAS* slot = m_tlasPool.Get(index, generation);
    if (!slot) {
        DestroyASStorage(m_device, m_allocator, tlas);
        return refuse("pool allocation failed");
    }
    *slot = tlas;
    slot->generation = generation;
    UZ_LOG(RHI, Info, "Created TLAS '{}': maxInstances={}, result={}B, scratch={}B", name, desc.maxInstanceCount,
           slot->resultSizeBytes, slot->scratchSizeBytes);
    return {index, generation};
}

void VulkanDevice::DestroyTLAS(RHITLASHandle handle) {
    VulkanTLAS* tlas = m_tlasPool.Get(handle.index, handle.generation);
    if (!tlas || tlas->handle == VK_NULL_HANDLE) return;  // invalid or already destroyed
    DestroyASStorage(m_device, m_allocator, *tlas);
    const uint32_t generation = tlas->generation;
    *tlas = VulkanTLAS{};
    tlas->generation = generation;
    m_tlasPool.Free(handle.index);
}

} // namespace uz
