// Measurement probe of the recording GPU's texture unit through Vulkan (decision 056; task
// phase1.9_compositor-resample-gaps). Painter 12 renders through Vulkan; the render layer is DX12
// only until Phase 3, so this standalone program samples a float32 or UNORM16 RGBA texture with
// a mip chain through one VkSampler from an HLSL compute kernel (compiled to SPIR-V by the
// vendored dxcompiler.dll) and writes the RGBA32F result. Driven by measure.py in this folder.
//
// Input folder: probe.bin = 8 uint32 (width, height, mip levels, output width, output height,
// filter 0 nearest / 1 linear / 2 anisotropic, maxAnisotropy, flags: 1 clamp, 2 UNORM16,
// 4 nearest mip), 3 float32 (LOD bias, min LOD, max LOD), then each level's texels with rows
// padded to 256 bytes and levels to 512 bytes; probe.hlsl = the kernel (t0 texture `src`, s1
// sampler `s`, u2 output `dst`, t3 `StructuredBuffer<float4> params`, entry `main`, cs_6_6);
// optional params.bin = the contents of `params` (designed per-sample inputs). Output: out.bin.
//
// Build: zig c++ -std=c++20 -O2 -fms-extensions -I thirdparty/volk
//        -I thirdparty/vulkan-headers/include -I thirdparty/dxc/inc
//        tools/parity/vk_sampler_probe/vkprobe.cpp -o <work>/vkprobe.exe -lole32
#include <unknwn.h>
#define NOMINMAX
#include <windows.h>
#define VOLK_IMPLEMENTATION
#include "volk.h"
#undef CROSS_PLATFORM_UUIDOF
#define CROSS_PLATFORM_UUIDOF(iface, spec) struct iface;
#include "dxcapi.h"
static const GUID kIIDCompiler3 = {0x228B4687, 0x5A6A, 0x4730, {0x90, 0x0C, 0x97, 0x02, 0xB2, 0x20, 0x3F, 0x54}};
static const GUID kIIDResult = {0x58346CDA, 0xDDE7, 0x4497, {0x94, 0x61, 0x6F, 0x87, 0xAF, 0x5E, 0x06, 0x59}};
static const GUID kIIDBlobUtf8 = {0x3DA636C9, 0xBA71, 0x4024, {0xA3, 0x01, 0x30, 0xCB, 0xF1, 0x25, 0x30, 0x5B}};
static const GUID kIIDBlob = {0x8BA5FB08, 0x5195, 0x40e2, {0xAC, 0x58, 0x0D, 0x98, 0x9C, 0x3A, 0x01, 0x02}};

#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#define CHECK(x)                                                                 \
    do {                                                                         \
        VkResult r_ = (x);                                                       \
        if (r_ != VK_SUCCESS) {                                                  \
            std::fprintf(stderr, "FAIL %s -> %d (line %d)\n", #x, r_, __LINE__); \
            std::exit(1);                                                        \
        }                                                                        \
    } while (0)

static std::vector<char> ReadAll(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    return std::vector<char>((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

static std::vector<uint32_t> CompileSpirv(const std::string& dxcPath, const std::string& hlsl) {
    HMODULE module = LoadLibraryA(dxcPath.c_str());
    if (!module) { std::fprintf(stderr, "FAIL load dxcompiler\n"); std::exit(1); }
    auto create = reinterpret_cast<DxcCreateInstanceProc>(GetProcAddress(module, "DxcCreateInstance"));
    IDxcCompiler3* compiler = nullptr;
    create(CLSID_DxcCompiler, kIIDCompiler3, reinterpret_cast<void**>(&compiler));
    DxcBuffer source{hlsl.data(), hlsl.size(), DXC_CP_UTF8};
    const wchar_t* args[] = {L"-E", L"main", L"-T", L"cs_6_6", L"-spirv", L"-fspv-target-env=vulkan1.2", L"-O3", L"-Gis"};
    IDxcResult* result = nullptr;
    compiler->Compile(&source, args, sizeof(args) / sizeof(args[0]), nullptr, kIIDResult, reinterpret_cast<void**>(&result));
    HRESULT status;
    result->GetStatus(&status);
    IDxcBlobUtf8* errors = nullptr;
    result->GetOutput(DXC_OUT_ERRORS, kIIDBlobUtf8, reinterpret_cast<void**>(&errors), nullptr);
    if (FAILED(status)) {
        std::fprintf(stderr, "FAIL compile: %s\n", errors ? errors->GetStringPointer() : "?");
        std::exit(1);
    }
    IDxcBlob* object = nullptr;
    result->GetOutput(DXC_OUT_OBJECT, kIIDBlob, reinterpret_cast<void**>(&object), nullptr);
    std::vector<uint32_t> words(object->GetBufferSize() / 4);
    std::memcpy(words.data(), object->GetBufferPointer(), words.size() * 4);
    return words;
}

int main(int argc, char** argv) {
    if (argc < 3) { std::fprintf(stderr, "usage: vkprobe <dxcompiler.dll> <dir>\n"); return 2; }
    const std::string dir = argv[2];
    std::vector<char> blob = ReadAll(dir + "/probe.bin");
    std::vector<char> hlslBytes = ReadAll(dir + "/probe.hlsl");
    const std::string hlsl(hlslBytes.begin(), hlslBytes.end());
    uint32_t h[8];
    float f[3];
    std::memcpy(h, blob.data(), sizeof h);
    std::memcpy(f, blob.data() + sizeof h, sizeof f);
    const uint32_t width = h[0], height = h[1], mips = h[2], outW = h[3], outH = h[4], filter = h[5], aniso = h[6], flags = h[7];
    const bool unorm16 = (flags & 2) != 0;
    const size_t dataOffset = sizeof h + sizeof f;
    const size_t dataSize = blob.size() - dataOffset;
    const std::vector<uint32_t> spirv = CompileSpirv(argv[1], hlsl);
    std::vector<char> params = ReadAll(dir + "/params.bin");
    if (params.empty()) params.assign(16, 0);

    CHECK(volkInitialize());
    VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
    app.apiVersion = VK_API_VERSION_1_2;
    VkInstanceCreateInfo ici{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    ici.pApplicationInfo = &app;
    VkInstance instance;
    CHECK(vkCreateInstance(&ici, nullptr, &instance));
    volkLoadInstance(instance);
    uint32_t count = 0;
    vkEnumeratePhysicalDevices(instance, &count, nullptr);
    std::vector<VkPhysicalDevice> physicals(count);
    vkEnumeratePhysicalDevices(instance, &count, physicals.data());
    VkPhysicalDevice physical = VK_NULL_HANDLE;
    for (VkPhysicalDevice p : physicals) {
        VkPhysicalDeviceProperties props;
        vkGetPhysicalDeviceProperties(p, &props);
        if (props.vendorID == 0x10de) { physical = p; std::fprintf(stderr, "INFO device %s\n", props.deviceName); }
    }
    if (!physical) { std::fprintf(stderr, "FAIL no NVIDIA device\n"); return 1; }
    uint32_t qcount = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &qcount, nullptr);
    std::vector<VkQueueFamilyProperties> qprops(qcount);
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &qcount, qprops.data());
    uint32_t family = 0;
    for (uint32_t i = 0; i < qcount; ++i) if (qprops[i].queueFlags & VK_QUEUE_COMPUTE_BIT) { family = i; break; }
    const float priority = 1.0f;
    VkDeviceQueueCreateInfo qci{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
    qci.queueFamilyIndex = family;
    qci.queueCount = 1;
    qci.pQueuePriorities = &priority;
    VkPhysicalDeviceFeatures features{};
    features.samplerAnisotropy = VK_TRUE;
    features.shaderFloat64 = VK_TRUE;
    VkDeviceCreateInfo dci{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
    dci.queueCreateInfoCount = 1;
    dci.pQueueCreateInfos = &qci;
    dci.pEnabledFeatures = &features;
    VkDevice device;
    CHECK(vkCreateDevice(physical, &dci, nullptr, &device));
    volkLoadDevice(device);
    VkQueue queue;
    vkGetDeviceQueue(device, family, 0, &queue);
    VkPhysicalDeviceMemoryProperties memProps;
    vkGetPhysicalDeviceMemoryProperties(physical, &memProps);
    auto memType = [&](uint32_t bits, VkMemoryPropertyFlags want) {
        for (uint32_t i = 0; i < memProps.memoryTypeCount; ++i)
            if ((bits & (1u << i)) && (memProps.memoryTypes[i].propertyFlags & want) == want) return i;
        std::fprintf(stderr, "FAIL memory type\n");
        std::exit(1);
    };
    auto makeBuffer = [&](VkDeviceSize size, VkBufferUsageFlags usage, VkBuffer& buffer, VkDeviceMemory& memory) {
        VkBufferCreateInfo bci{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
        bci.size = size;
        bci.usage = usage;
        CHECK(vkCreateBuffer(device, &bci, nullptr, &buffer));
        VkMemoryRequirements req;
        vkGetBufferMemoryRequirements(device, buffer, &req);
        VkMemoryAllocateInfo mai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
        mai.allocationSize = req.size;
        mai.memoryTypeIndex = memType(req.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
        CHECK(vkAllocateMemory(device, &mai, nullptr, &memory));
        CHECK(vkBindBufferMemory(device, buffer, memory, 0));
    };
    auto makeImage = [&](uint32_t w, uint32_t hh, uint32_t levels, VkFormat format, VkImageUsageFlags usage, VkImage& image,
                         VkDeviceMemory& memory) {
        VkImageCreateInfo ii{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
        ii.imageType = VK_IMAGE_TYPE_2D;
        ii.format = format;
        ii.extent = {w, hh, 1};
        ii.mipLevels = levels;
        ii.arrayLayers = 1;
        ii.samples = VK_SAMPLE_COUNT_1_BIT;
        ii.tiling = VK_IMAGE_TILING_OPTIMAL;
        ii.usage = usage;
        CHECK(vkCreateImage(device, &ii, nullptr, &image));
        VkMemoryRequirements req;
        vkGetImageMemoryRequirements(device, image, &req);
        VkMemoryAllocateInfo mai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
        mai.allocationSize = req.size;
        mai.memoryTypeIndex = memType(req.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
        CHECK(vkAllocateMemory(device, &mai, nullptr, &memory));
        CHECK(vkBindImageMemory(device, image, memory, 0));
    };
    const VkFormat srcFormat = unorm16 ? VK_FORMAT_R16G16B16A16_UNORM : VK_FORMAT_R32G32B32A32_SFLOAT;
    const uint32_t texelBytes = unorm16 ? 8 : 16;
    VkImage src, dst;
    VkDeviceMemory srcMem, dstMem;
    makeImage(width, height, mips, srcFormat, VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT, src, srcMem);
    makeImage(outW, outH, 1, VK_FORMAT_R32G32B32A32_SFLOAT, VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT, dst, dstMem);
    VkBuffer staging, readback;
    VkDeviceMemory stagingMem, readbackMem;
    makeBuffer(dataSize, VK_BUFFER_USAGE_TRANSFER_SRC_BIT, staging, stagingMem);
    makeBuffer(VkDeviceSize{outW} * outH * 16, VK_BUFFER_USAGE_TRANSFER_DST_BIT, readback, readbackMem);
    VkBuffer paramBuffer;
    VkDeviceMemory paramMem;
    makeBuffer(params.size(), VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, paramBuffer, paramMem);
    void* mapped;
    vkMapMemory(device, stagingMem, 0, dataSize, 0, &mapped);
    std::memcpy(mapped, blob.data() + dataOffset, dataSize);
    vkUnmapMemory(device, stagingMem);
    vkMapMemory(device, paramMem, 0, params.size(), 0, &mapped);
    std::memcpy(mapped, params.data(), params.size());
    vkUnmapMemory(device, paramMem);

    VkImageViewCreateInfo vci{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
    vci.image = src;
    vci.viewType = VK_IMAGE_VIEW_TYPE_2D;
    vci.format = srcFormat;
    vci.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, mips, 0, 1};
    VkImageView srcView, dstView;
    CHECK(vkCreateImageView(device, &vci, nullptr, &srcView));
    vci.image = dst;
    vci.format = VK_FORMAT_R32G32B32A32_SFLOAT;
    vci.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    CHECK(vkCreateImageView(device, &vci, nullptr, &dstView));

    VkSamplerCreateInfo sci{VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO};
    sci.magFilter = sci.minFilter = filter == 0 ? VK_FILTER_NEAREST : VK_FILTER_LINEAR;
    sci.mipmapMode = (flags & 4) != 0 ? VK_SAMPLER_MIPMAP_MODE_NEAREST
                                      : (filter == 0 ? VK_SAMPLER_MIPMAP_MODE_NEAREST : VK_SAMPLER_MIPMAP_MODE_LINEAR);
    sci.addressModeU = sci.addressModeV = sci.addressModeW =
        (flags & 1) != 0 ? VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE : VK_SAMPLER_ADDRESS_MODE_REPEAT;
    sci.mipLodBias = f[0];
    sci.anisotropyEnable = filter == 2 ? VK_TRUE : VK_FALSE;
    sci.maxAnisotropy = static_cast<float>(aniso);
    sci.minLod = f[1];
    sci.maxLod = f[2];
    VkSampler sampler;
    CHECK(vkCreateSampler(device, &sci, nullptr, &sampler));

    VkDescriptorSetLayoutBinding bindings[4] = {
        {0, VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
        {1, VK_DESCRIPTOR_TYPE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
        {2, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},
        {3, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr}};
    VkDescriptorSetLayoutCreateInfo dslci{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
    dslci.bindingCount = 4;
    dslci.pBindings = bindings;
    VkDescriptorSetLayout setLayout;
    CHECK(vkCreateDescriptorSetLayout(device, &dslci, nullptr, &setLayout));
    VkPipelineLayoutCreateInfo plci{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    plci.setLayoutCount = 1;
    plci.pSetLayouts = &setLayout;
    VkPipelineLayout pipelineLayout;
    CHECK(vkCreatePipelineLayout(device, &plci, nullptr, &pipelineLayout));
    VkShaderModuleCreateInfo smci{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    smci.codeSize = spirv.size() * 4;
    smci.pCode = spirv.data();
    VkShaderModule shader;
    CHECK(vkCreateShaderModule(device, &smci, nullptr, &shader));
    VkComputePipelineCreateInfo cpci{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};
    cpci.stage = {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, nullptr, 0, VK_SHADER_STAGE_COMPUTE_BIT, shader, "main", nullptr};
    cpci.layout = pipelineLayout;
    VkPipeline pipeline;
    CHECK(vkCreateComputePipelines(device, VK_NULL_HANDLE, 1, &cpci, nullptr, &pipeline));
    VkDescriptorPoolSize sizes[4] = {{VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, 1}, {VK_DESCRIPTOR_TYPE_SAMPLER, 1},
                                     {VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1}, {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1}};
    VkDescriptorPoolCreateInfo dpci{VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};
    dpci.maxSets = 1;
    dpci.poolSizeCount = 4;
    dpci.pPoolSizes = sizes;
    VkDescriptorPool pool;
    CHECK(vkCreateDescriptorPool(device, &dpci, nullptr, &pool));
    VkDescriptorSetAllocateInfo dsai{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};
    dsai.descriptorPool = pool;
    dsai.descriptorSetCount = 1;
    dsai.pSetLayouts = &setLayout;
    VkDescriptorSet set;
    CHECK(vkAllocateDescriptorSets(device, &dsai, &set));
    VkDescriptorImageInfo srcInfo{VK_NULL_HANDLE, srcView, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL};
    VkDescriptorImageInfo sampInfo{sampler, VK_NULL_HANDLE, VK_IMAGE_LAYOUT_UNDEFINED};
    VkDescriptorImageInfo dstInfo{VK_NULL_HANDLE, dstView, VK_IMAGE_LAYOUT_GENERAL};
    VkDescriptorBufferInfo paramInfo{paramBuffer, 0, VK_WHOLE_SIZE};
    VkWriteDescriptorSet writes[4] = {};
    for (int i = 0; i < 4; ++i) {
        writes[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        writes[i].dstSet = set;
        writes[i].dstBinding = static_cast<uint32_t>(i);
        writes[i].descriptorCount = 1;
        writes[i].descriptorType = bindings[i].descriptorType;
    }
    writes[0].pImageInfo = &srcInfo;
    writes[1].pImageInfo = &sampInfo;
    writes[2].pImageInfo = &dstInfo;
    writes[3].pBufferInfo = &paramInfo;
    vkUpdateDescriptorSets(device, 4, writes, 0, nullptr);

    VkCommandPoolCreateInfo cpi{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
    cpi.queueFamilyIndex = family;
    VkCommandPool cmdPool;
    CHECK(vkCreateCommandPool(device, &cpi, nullptr, &cmdPool));
    VkCommandBufferAllocateInfo cbai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
    cbai.commandPool = cmdPool;
    cbai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    cbai.commandBufferCount = 1;
    VkCommandBuffer cmd;
    CHECK(vkAllocateCommandBuffers(device, &cbai, &cmd));
    VkCommandBufferBeginInfo cbbi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    CHECK(vkBeginCommandBuffer(cmd, &cbbi));
    auto barrier = [&](VkImage image, uint32_t levels, VkImageLayout from, VkImageLayout to) {
        VkImageMemoryBarrier b{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER};
        b.srcAccessMask = VK_ACCESS_MEMORY_WRITE_BIT;
        b.dstAccessMask = VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT;
        b.oldLayout = from;
        b.newLayout = to;
        b.srcQueueFamilyIndex = b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        b.image = image;
        b.subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, levels, 0, 1};
        vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, 0, nullptr, 0, nullptr, 1, &b);
    };
    barrier(src, mips, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    uint64_t offset = 0;
    for (uint32_t m = 0; m < mips; ++m) {
        const uint32_t w = std::max(width >> m, 1u), hh = std::max(height >> m, 1u);
        const uint32_t pitch = (w * texelBytes + 255u) & ~255u;
        VkBufferImageCopy region{};
        region.bufferOffset = offset;
        region.bufferRowLength = pitch / texelBytes;
        region.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, m, 0, 1};
        region.imageExtent = {w, hh, 1};
        vkCmdCopyBufferToImage(cmd, staging, src, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region);
        offset = (offset + uint64_t{pitch} * hh + 511u) & ~uint64_t{511};
    }
    barrier(src, mips, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
    barrier(dst, 1, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL);
    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
    vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, pipelineLayout, 0, 1, &set, 0, nullptr);
    vkCmdDispatch(cmd, (outW + 7) / 8, (outH + 7) / 8, 1);
    barrier(dst, 1, VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
    VkBufferImageCopy out{};
    out.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};
    out.imageExtent = {outW, outH, 1};
    vkCmdCopyImageToBuffer(cmd, dst, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, readback, 1, &out);
    CHECK(vkEndCommandBuffer(cmd));
    VkSubmitInfo si{VK_STRUCTURE_TYPE_SUBMIT_INFO};
    si.commandBufferCount = 1;
    si.pCommandBuffers = &cmd;
    CHECK(vkQueueSubmit(queue, 1, &si, VK_NULL_HANDLE));
    CHECK(vkQueueWaitIdle(queue));
    vkMapMemory(device, readbackMem, 0, VK_WHOLE_SIZE, 0, &mapped);
    std::ofstream o(dir + "/out.bin", std::ios::binary);
    o.write(static_cast<const char*>(mapped), static_cast<std::streamsize>(size_t{outW} * outH * 16));
    vkUnmapMemory(device, readbackMem);
    vkDeviceWaitIdle(device);
    vkDestroyDevice(device, nullptr);
    vkDestroyInstance(instance, nullptr);
    return 0;
}
