#pragma once

// The image-pass cases of uzp-render-tests.exe (image_passes_test.cpp).

#include <filesystem>
#include <string_view>

/// Runs case `mode` (`image-reference`, `image-dilation`, `image-resample`, `image-mips`,
/// `image-repeat`, `vulkan-image-passes`) with work folder `dir`; returns its exit code, or -1
/// for another mode.
int RunImagePassCase(std::string_view mode, const std::filesystem::path& dir);
