#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace uzp::exporter {

/// Already quantized bytes, top row first, interleaved L, LA, RGB or RGBA.
/// No colour conversion, quantization, alpha removal or Painter parity is implied.
struct TgaImage {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t channels = 0;
    std::vector<uint8_t> samples;
};

/// Deterministic RLE TGA8 through pinned stb. Preserves every sample and alpha.
/// Rejects zero/over-65535 dimensions, unsupported layouts, mismatched samples,
/// and rasters exceeding stb's signed-int indexing domain, before invoking stb.
[[nodiscard]] std::string EncodeTga(const TgaImage& image);

}  // namespace uzp::exporter
