#pragma once

// The synthetic meshes of uv_raster_test.cpp (plane, UV sphere, bevelled cube) and an engine on
// the qualified Vulkan device, shared by the cross-backend cases of the image passes
// (phase3.1_vulkan-compute-parity items 2.5 and 3.2): `vulkan-uv-raster` (uv_raster_test.cpp)
// and `vulkan-image-passes` (image_passes_test.cpp).

#include "render/engine_thread.h"
#include "render/uv_raster.h"

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

struct UvRasterFixture {
    std::string name;
    std::vector<std::vector<std::byte>> storage;  ///< The corner bytes (interleaved layout).
    std::vector<uint32_t> triangles;
    uzp::render::CornerBuffers corners;  ///< Points into `storage` and `triangles`.
};

/// "plane" (a 5 x 5 quad grid), "sphere" (24 segments, 12 rings) and "bevelled cube", in the
/// interleaved corner layout of uv_raster_test.cpp.
[[nodiscard]] std::vector<std::unique_ptr<UvRasterFixture>> SyntheticUvRasterFixtures();

/// Options of an engine on the qualified Vulkan device of adapter index 0, through the
/// native-test seam `EngineOptions::createDevice` (product paths refuse Vulkan, decision 310),
/// with its kernel cache under `dir`.
[[nodiscard]] uzp::render::EngineOptions VulkanTestEngineOptions(const std::filesystem::path& dir);

/// True, after printing why, when this machine has no Vulkan physical device.
[[nodiscard]] bool VulkanDeviceMissing();
