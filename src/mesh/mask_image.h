#pragma once

// Orientation of imported images (`docs/architecture/12-mesh-import.md` §3, INT-12): the
// pipeline's `M_*.png` masks and `T_*.png` textures are read in PNG order, so row 0 of an image
// is the PNG's first (top) row, which lies at v = 1 of tile 1001. Texel (col, row) of a W x H
// image covers u in [col/W, (col+1)/W] and v in [1 - (row+1)/H, 1 - row/H]; its centre is
// ((col + 1/2)/W, 1 - (row + 1/2)/H), the convention of the UV raster (`render/uv_raster.h`).

#include <array>
#include <cstdint>
#include <string_view>
#include <vector>

#include "mesh/texturing_mesh.h"

namespace uzp::mesh {

struct ImageRgba16 {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::uint8_t bit_depth = 0;   ///< of the PNG file
    std::uint8_t color_type = 0;  ///< of the PNG file (0 grey, 2 RGB, 3 palette, 4 grey+alpha, 6 RGBA)
    /// Row-major RGBA, 16 bits per sample (8-bit files scaled by 257), row 0 = the PNG's top row.
    std::vector<std::uint16_t> rgba;

    std::array<std::uint16_t, 4> At(std::uint32_t col, std::uint32_t row) const;
};

/// Decodes a PNG of any colour type and bit depth. Throws `ImportError` (`parse_error`).
ImageRgba16 DecodePng(std::string_view bytes);

struct Texel {
    std::uint32_t col = 0;
    std::uint32_t row = 0;
    bool operator==(const Texel&) const = default;
};

/// The texel of a `width` x `height` image of tile 1001 that contains `uv` (edges clamped).
Texel TexelAt(Float2 uv, std::uint32_t width, std::uint32_t height);

}  // namespace uzp::mesh
