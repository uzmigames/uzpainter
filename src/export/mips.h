#pragma once

// Mip generation for the UzEngine textures (docs/architecture/08-export.md §4; task
// phase3.1_uze-uztexture-writer items 2.3, 2.4, 2.5, 3.2, 3.3 and 3.4, decision 315).
//
// The chain is full: level n is max(1, width >> n) by max(1, height >> n), down to 1x1. Each
// level is computed from the level above it, at 16 bits per channel, and is quantised to 8 bits
// only for the block encoder (`QuantizeTo8`). The filter is the 2x2 box of the level above: texel
// (x, y) of level n reads texels (2x, 2y), (2x + 1, 2y), (2x, 2y + 1) and (2x + 1, 2y + 1) of
// level n - 1, a side that is already 1 reading its single texel twice. Both sides must be powers
// of two; other sizes are refused (a 2x2 box does not tile them).
//
// Per map class:
// - `Linear` (ORM, height, data): each channel the integer mean of its four codes, rounded half up.
// - `Colour` (sRGB-encoded RGB, linear alpha): R, G and B decoded with the sRGB transfer function
//   (IEC 61966-2-1) to linear values, averaged, and encoded back to the 16-bit code whose decoded
//   interval holds the mean; alpha as `Linear`.
// - `Normal` (RGB = vector * 0.5 + 0.5): the vectors decoded, summed and renormalised at every
//   level, level 0 included; a sum of length 0 becomes (0, 0, 1); alpha as `Linear`.
// - `MaskedColour` (masked albedo): RGB as `Colour`; alpha box-filtered, then scaled so that the
//   share of texels whose 8-bit alpha exceeds `alphaThreshold` stays the share of level 0, as
//   closely as the level's texel count allows (alpha-coverage preservation).
//
// Every operation is integer or correctly rounded IEEE double arithmetic (the sRGB transfer uses
// no `pow`: its x^2.4 is a fixed Newton iteration, decision 315), so the chain does not depend on
// the C runtime or on the CPU.

#include <cstdint>
#include <vector>

#include "export/bc_encoder.h"

namespace uzp::exporter {

/// Rows top first, 4 channels (R, G, B, A) per texel, 16-bit UNORM codes. An 8-bit map enters as
/// code * 257.
struct Rgba16Image {
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<uint16_t> rgba;
};

enum class MipClass : uint8_t { Linear, Colour, Normal, MaskedColour };

struct MipOptions {
    MipClass mapClass = MipClass::Linear;
    /// `MaskedColour` only: a texel is covered when its 8-bit alpha / 255 exceeds this value.
    double alphaThreshold = 0.5;
};

/// floor(log2(max(width, height))) + 1.
[[nodiscard]] uint32_t FullMipCount(uint32_t width, uint32_t height);

/// The full chain of `base`, level 0 first (level 0 is `base`, renormalised for `Normal`). Throws
/// std::invalid_argument for an empty image, a texel count that does not match its size, a side
/// that is not a power of two, or an `alphaThreshold` outside [0, 1).
[[nodiscard]] std::vector<Rgba16Image> GenerateMipChain(const Rgba16Image& base,
                                                        const MipOptions& options);

/// The 8-bit code of each 16-bit code: round(code / 257).
[[nodiscard]] Rgba8Image QuantizeTo8(const Rgba16Image& image);

/// The sRGB transfer function on 16-bit codes, as the chain uses it: the linear value of `code`,
/// and the code whose decoded interval [decode(code - 0.5), decode(code + 0.5)) holds `linear`.
[[nodiscard]] double SrgbDecode16(uint16_t code);
[[nodiscard]] uint16_t SrgbEncode16(double linear);

/// The texels whose 8-bit alpha / 255 exceeds `threshold`.
[[nodiscard]] uint64_t CoveredTexels(const Rgba16Image& image, double threshold);

}  // namespace uzp::exporter
