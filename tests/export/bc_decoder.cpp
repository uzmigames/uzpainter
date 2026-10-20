#include "uze_texture_check.h"

#include <algorithm>
#include <array>
#include <cstring>
#include <limits>

#include "bc7_decoder.h"

namespace uzp::exporter::testing {
namespace {

// Test-only integer reconstruction, including the BC1-5 rounding convention
// retained for existing lossy-error reports. Sources and limits: docs/BC-DECODER.md.
uint32_t Bits(const uint8_t* bytes, unsigned start, unsigned count) {
    uint32_t value = 0;
    for (unsigned bit = 0; bit < count; ++bit) {
        const unsigned offset = start + bit;
        value |= uint32_t{(bytes[offset / 8] >> (offset % 8)) & 1u} << bit;
    }
    return value;
}

using Texel = std::array<uint8_t, 4>;

void DecodeColour(const uint8_t* bytes, bool allowTransparency, uint8_t* out) {
    const uint32_t first = Bits(bytes, 0, 16);
    const uint32_t second = Bits(bytes, 16, 16);
    std::array<Texel, 4> palette{};
    constexpr unsigned shifts[] = {11, 5, 0};
    constexpr unsigned maxima[] = {31, 63, 31};
    for (unsigned channel = 0; channel < 3; ++channel) {
        const unsigned mask = maxima[channel];
        palette[0][channel] = static_cast<uint8_t>(
            (((first >> shifts[channel]) & mask) * 255 + mask / 2) / mask);
        palette[1][channel] = static_cast<uint8_t>(
            (((second >> shifts[channel]) & mask) * 255 + mask / 2) / mask);
    }
    palette[0][3] = palette[1][3] = palette[2][3] = 255;
    const bool transparent = allowTransparency && first <= second;
    if (!transparent) palette[3][3] = 255;
    for (unsigned channel = 0; channel < 3; ++channel) {
        const unsigned a = palette[0][channel], b = palette[1][channel];
        palette[2][channel] = static_cast<uint8_t>(
            transparent ? (a + b + 1) / 2 : (2 * a + b + 1) / 3);
        if (!transparent)
            palette[3][channel] = static_cast<uint8_t>((a + 2 * b + 1) / 3);
    }
    for (unsigned texel = 0; texel < 16; ++texel)
        std::memcpy(out + 4 * texel, palette[Bits(bytes, 32 + 2 * texel, 2)].data(), 4);
}

void DecodeScalar(const uint8_t* bytes, unsigned channel, uint8_t* out) {
    const unsigned a = bytes[0], b = bytes[1];
    std::array<uint8_t, 8> palette{bytes[0], bytes[1], 0, 0, 0, 0, 0, 255};
    const unsigned denominator = a > b ? 7 : 5;
    for (unsigned index = 2; index <= denominator; ++index) {
        const unsigned weight = index - 1;
        palette[index] = static_cast<uint8_t>(
            ((denominator - weight) * a + weight * b + 1) / denominator);
    }
    for (unsigned texel = 0; texel < 16; ++texel)
        out[4 * texel + channel] = palette[Bits(bytes, 16 + 3 * texel, 3)];
}

}  // namespace

Rgba8Image DecodeBc(BcFormat format, const std::vector<uint8_t>& blocks, uint32_t width,
                    uint32_t height) {
    if (width == 0 || height == 0)
        throw std::invalid_argument("DecodeBc: empty image");
    const uint32_t blockBytes = BcBlockBytes(format);
    const uint64_t blocksX = (uint64_t{width} + 3) / 4;
    const uint64_t blocksY = (uint64_t{height} + 3) / 4;
    const uint64_t blockCount = blocksX * blocksY;
    const uint64_t texels = uint64_t{width} * height;
    if (blockCount > std::numeric_limits<uint64_t>::max() / blockBytes ||
        blocks.size() != blockCount * blockBytes)
        throw std::invalid_argument("DecodeBc: block bytes do not match the size");
    if (texels > std::numeric_limits<size_t>::max() / 4)
        throw std::invalid_argument("DecodeBc: decoded image size overflows");
    Rgba8Image out{width, height, std::vector<uint8_t>(static_cast<size_t>(texels) * 4)};
    for (uint64_t by = 0; by < blocksY; ++by) {
        for (uint64_t bx = 0; bx < blocksX; ++bx) {
            const uint8_t* block = blocks.data() + (by * blocksX + bx) * blockBytes;
            uint8_t rgba[16 * 4] = {};
            switch (format) {
                case BcFormat::Bc1:
                case BcFormat::Bc1Srgb:
                    DecodeColour(block, true, rgba);
                    break;
                case BcFormat::Bc3:
                case BcFormat::Bc3Srgb:
                    DecodeColour(block + 8, false, rgba);
                    DecodeScalar(block, 3, rgba);
                    break;
                case BcFormat::Bc4:
                case BcFormat::Bc5:
                    for (unsigned i = 0; i < 16; ++i) rgba[4 * i + 3] = 255;
                    DecodeScalar(block, 0, rgba);
                    if (format == BcFormat::Bc5) DecodeScalar(block + 8, 1, rgba);
                    break;
                case BcFormat::Bc7:
                case BcFormat::Bc7Srgb:
                    detail::DecodeBc7Block(block, rgba);
                    break;
            }
            const uint64_t rows = std::min(uint64_t{4}, uint64_t{height} - by * 4);
            const uint64_t columns = std::min(uint64_t{4}, uint64_t{width} - bx * 4);
            for (uint64_t y = 0; y < rows; ++y)
                std::memcpy(out.rgba.data() + ((by * 4 + y) * width + bx * 4) * 4,
                            rgba + y * 16, static_cast<size_t>(columns * 4));
        }
    }
    return out;
}

}  // namespace uzp::exporter::testing
