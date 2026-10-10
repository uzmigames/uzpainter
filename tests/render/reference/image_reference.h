#pragma once

// CPU references of UzPainter's GPU image passes (src/render/dilation.h, resample.h, mips.h):
// the same arithmetic written independently on the CPU, for exact comparison in
// tests/render/image_passes_test.cpp. Unorm channels are held as integer codes, float channels
// as the float32 bits of their value (16-bit floats as the float32 of the half value).
//
// Independent of the GPU code paths: the write rule divides with 128-bit integers instead of the
// kernels' quotient/remainder split, half rounding uses the compiler's `_Float16` conversion
// instead of the kernels' bit manipulation, and the sRGB tables are recomputed here. Float sums
// are evaluated with contraction off, in the kernels' order.

#include <cstddef>
#include <cstdint>
#include <vector>

namespace uzp::render::reference {

enum class Encoding : uint8_t { Unorm8, Unorm16, Float16, Float32 };

struct Image {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t channels = 0;
    Encoding encoding = Encoding::Unorm8;
    /// width x height x channels values, rows top to bottom, channels interleaved.
    std::vector<uint32_t> values;

    [[nodiscard]] uint32_t& At(uint32_t x, uint32_t y, uint32_t c) {
        return values[(size_t{y} * width + x) * channels + c];
    }
    [[nodiscard]] uint32_t At(uint32_t x, uint32_t y, uint32_t c) const {
        return values[(size_t{y} * width + x) * channels + c];
    }
    friend bool operator==(const Image&, const Image&) = default;
};

[[nodiscard]] bool IsUnorm(Encoding encoding);
[[nodiscard]] uint32_t UnormBits(Encoding encoding);
[[nodiscard]] uint32_t UnormMax(Encoding encoding);
[[nodiscard]] uint32_t BytesPerChannel(Encoding encoding);

/// An image of `width` x `height` x `channels` values of `encoding`, all zero.
[[nodiscard]] Image MakeImage(uint32_t width, uint32_t height, uint32_t channels,
                              Encoding encoding);

/// The texel bytes a GPU texture of the image's format stores (little-endian channels).
[[nodiscard]] std::vector<std::byte> ToBytes(const Image& image);
/// The image of tightly packed texel bytes (the inverse of `ToBytes`).
[[nodiscard]] Image FromBytes(uint32_t width, uint32_t height, uint32_t channels,
                              Encoding encoding, const std::vector<std::byte>& bytes);

/// The float32 bits of the half nearest to `value` (ties to even), as a float32.
[[nodiscard]] uint32_t RoundToHalfBits(float value);

/// Write rule of s / (t M): V = floor(s 2^(n+4) / (t M)), code = floor((V M + 2^(n+3) - 1) /
/// 2^(n+4)).
[[nodiscard]] uint32_t WriteRatio(uint64_t s, uint64_t t, uint32_t bits);
/// Write rule of a float value (clamped to [0, 1], NaN to 0).
[[nodiscard]] uint32_t WriteValue(float value, uint32_t bits);

/// The resampling.json BilinearHQ storage formula for 16-bit codes, literally:
/// V = floor(S 2^20 / (256 x 65535)), code = floor((V 65535 + 2^19 - 1) / 2^20).
[[nodiscard]] uint32_t PainterBilinearStore16(uint64_t weightedSum);

/// float32 of the IEC 61966-2-1 decode of code / 255.
[[nodiscard]] float SrgbDecode(uint32_t code);
/// The sRGB code of a linear value: the largest k in 0..255 with value >= float32 of
/// decode((k - 0.5) / 255).
[[nodiscard]] uint32_t SrgbEncode(float linear);

// ── Dilation ─────────────────────────────────────────────────────────────────

/// Jump-flood dilation with the steps 1, N/2, ..., 1 (src/render/dilation.h), ties to the
/// smaller linear index; `covered` has one entry per texel.
[[nodiscard]] Image DilateJumpFlood(const Image& colour, const std::vector<uint8_t>& covered,
                                    uint32_t maxDistance);
/// The exact nearest covered texel by brute force (smallest squared distance, then smallest
/// linear index), with the same distance limit and the same copy rule.
[[nodiscard]] Image DilateBruteForce(const Image& colour, const std::vector<uint8_t>& covered,
                                     uint32_t maxDistance);

// ── Resampling and mips ──────────────────────────────────────────────────────

enum class Filter : uint8_t { Nearest, Bilinear, Box };
enum class Wrap : uint8_t { Clamp, Repeat };
enum class Colour : uint8_t { Linear, Srgb, Normal };

[[nodiscard]] Image Resample(const Image& source, uint32_t width, uint32_t height, Filter filter,
                             Wrap wrap, Colour colour);

/// Levels 0 .. levels - 1 (level 0 = `base`), each box-filtered from the previous stored level;
/// with `coverageCutoff` > 0 (a code K) alpha coverage is preserved.
[[nodiscard]] std::vector<Image> MipChain(const Image& base, uint32_t levels, Colour colour,
                                          uint32_t coverageCutoff);

/// Texels whose channel 3 code is >= `cutoff`.
[[nodiscard]] uint64_t CoveredTexels(const Image& image, uint32_t cutoff);

}  // namespace uzp::render::reference
