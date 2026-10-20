#pragma once

#include <cstdint>

namespace uzp::exporter::testing::detail {

// Decode one 16-byte BC7 block into 16 row-major RGBA8 texels (64 bytes).
// A reserved all-zero mode prefix produces transparent black.
void DecodeBc7Block(const uint8_t* block, uint8_t* rgba);

}  // namespace uzp::exporter::testing::detail
