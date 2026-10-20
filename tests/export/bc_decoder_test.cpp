#include "bc_decoder_test.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

#include "uze_texture_check.h"
#include "bcdec.h"  // Independent differential oracle, never the decoder under test.

namespace uzp::exporter::testing {
namespace {

using Block = std::array<uint8_t, 16>;

uint32_t Random(uint32_t& state) {
    state ^= state << 13;
    state ^= state >> 17;
    state ^= state << 5;
    return state;
}

void Bits(Block& block, uint32_t start, uint32_t count, uint32_t value) {
    for (uint32_t i = 0; i < count; ++i) {
        const uint32_t bit = start + i;
        const uint8_t mask = static_cast<uint8_t>(1u << (bit % 8));
        block[bit / 8] = static_cast<uint8_t>((block[bit / 8] & ~mask) |
                                            (((value >> i) & 1u) ? mask : 0));
    }
}

std::string Label(const char* name, BcFormat format, int mode, uint32_t seed) {
    return std::string(name) + " format=" + std::string(BcFormatName(format)) +
           " mode=" + std::to_string(mode) + " seed=" + std::to_string(seed);
}

void Equal(const Rgba8Image& image, const std::vector<uint8_t>& expected,
           const std::string& label) {
    if (image.rgba.size() != expected.size()) throw std::runtime_error(label + " size mismatch");
    for (size_t i = 0; i < expected.size(); ++i) {
        if (image.rgba[i] == expected[i]) continue;
        const size_t pixel = i / 4;
        throw std::runtime_error(label + " x=" + std::to_string(pixel % image.width) +
                                 " y=" + std::to_string(pixel / image.width) +
                                 " channel=" + std::to_string(i % 4) +
                                 " expected=" + std::to_string(expected[i]) +
                                 " actual=" + std::to_string(image.rgba[i]));
    }
}

std::array<uint8_t, 64> Oracle(BcFormat format, const uint8_t* bytes) {
    // bcdec reads native words; ensure its input and output have word alignment.
    alignas(8) Block block{};
    std::copy_n(bytes, BcBlockBytes(format), block.begin());
    alignas(8) std::array<uint8_t, 64> rgba{};
    alignas(8) std::array<uint8_t, 32> rg{};
    switch (format) {
        case BcFormat::Bc1:
        case BcFormat::Bc1Srgb: bcdec_bc1(block.data(), rgba.data(), 16); break;
        case BcFormat::Bc3:
        case BcFormat::Bc3Srgb: bcdec_bc3(block.data(), rgba.data(), 16); break;
        case BcFormat::Bc7:
        case BcFormat::Bc7Srgb: bcdec_bc7(block.data(), rgba.data(), 16); break;
        case BcFormat::Bc4:
            bcdec_bc4(block.data(), rg.data(), 4);
            for (size_t i = 0; i < 16; ++i) {
                rgba[i * 4] = rg[i];
                rgba[i * 4 + 3] = 255;
            }
            break;
        case BcFormat::Bc5:
            bcdec_bc5(block.data(), rg.data(), 8);
            for (size_t i = 0; i < 16; ++i) {
                rgba[i * 4] = rg[i * 2];
                rgba[i * 4 + 1] = rg[i * 2 + 1];
                rgba[i * 4 + 3] = 255;
            }
            break;
    }
    return rgba;
}

void Differential(BcFormat format, const std::vector<uint8_t>& blocks,
                  uint32_t width, uint32_t height, const std::string& label) {
    std::vector<uint8_t> expected(static_cast<size_t>(width) * height * 4);
    const uint32_t columns = (width + 3) / 4;
    for (uint32_t by = 0; by < (height + 3) / 4; ++by) {
        for (uint32_t bx = 0; bx < columns; ++bx) {
            const auto rgba = Oracle(format, blocks.data() +
                                    (static_cast<size_t>(by) * columns + bx) * BcBlockBytes(format));
            for (uint32_t y = 0; y < 4 && by * 4 + y < height; ++y)
                for (uint32_t x = 0; x < 4 && bx * 4 + x < width; ++x)
                    std::copy_n(rgba.data() + (y * 4 + x) * 4, 4,
                                expected.data() + (static_cast<size_t>(by * 4 + y) * width + bx * 4 + x) * 4);
        }
    }
    Equal(DecodeBc(format, blocks, width, height), expected, label);
}

void One(BcFormat format, const Block& block, int mode, uint32_t seed, const char* name) {
    Differential(format, {block.begin(), block.begin() + BcBlockBytes(format)}, 4, 4,
                 Label(name, format, mode, seed));
}

void Solid(BcFormat format, const Block& block, const std::array<uint8_t, 4>& pixel,
           const char* name) {
    std::vector<uint8_t> expected;
    for (int i = 0; i < 16; ++i) expected.insert(expected.end(), pixel.begin(), pixel.end());
    Equal(DecodeBc(format, {block.begin(), block.begin() + BcBlockBytes(format)}, 4, 4),
          expected, Label(name, format, -1, 0));
}

void Analytic() {
    Block block{};
    block[2] = block[3] = 255;  // Black <= white: BC1 selector 3 is transparent.
    std::fill(block.begin() + 4, block.begin() + 8, 255);
    Solid(BcFormat::Bc1, block, {0, 0, 0, 0}, "bc1-three-transparent");
    block[0] = block[1] = 255;
    block[2] = block[3] = 0;  // White > black: selector 3 is one-third white.
    Solid(BcFormat::Bc1, block, {85, 85, 85, 255}, "bc1-four-interpolated");
    block.fill(0);
    std::fill(block.begin() + 4, block.begin() + 8, 255);
    Solid(BcFormat::Bc1, block, {0, 0, 0, 0}, "bc1-equal-transparent");
    block.fill(0);
    block[0] = 255;  // Alpha selector 0: opaque.
    block[10] = block[11] = 255;  // Black <= white, but BC3 MUST use four colours.
    std::fill(block.begin() + 12, block.end(), 255);
    Solid(BcFormat::Bc3, block, {170, 170, 170, 255}, "bc3-force-four");
    for (uint32_t index : {6u, 7u}) {
        block.fill(0);
        block[1] = 255;
        for (uint32_t i = 0; i < 16; ++i) Bits(block, 16 + i * 3, 3, index);
        Solid(BcFormat::Bc4, block, {static_cast<uint8_t>(index == 7 ? 255 : 0), 0, 0, 255},
              "bc4-six-endpoints");
    }
    block.fill(0);
    block[0] = 255;
    block[9] = 255;
    for (uint32_t i = 0; i < 16; ++i) Bits(block, 80 + i * 3, 3, 7);
    Solid(BcFormat::Bc5, block, {255, 255, 0, 255}, "bc5-independent-orders");
    block.fill(255);
    block[0] = 0;  // No BC7 mode prefix, regardless of remaining payload.
    Solid(BcFormat::Bc7, block, {0, 0, 0, 0}, "bc7-invalid-prefix");
}

void Bc7Corpus() {
    for (uint32_t mode = 0; mode < 8; ++mode) {
        const uint32_t partitionBits = mode == 0 ? 4 : (mode == 1 || mode == 2 || mode == 3 || mode == 7) ? 6 : 0;
        const uint32_t rotations = mode == 4 || mode == 5 ? 4 : 1;
        const uint32_t selectors = mode == 4 ? 2 : 1;
        for (uint32_t partition = 0; partition < (1u << partitionBits); ++partition)
            for (uint32_t rotation = 0; rotation < rotations; ++rotation)
                for (uint32_t selector = 0; selector < selectors; ++selector)
                    for (uint32_t sample = 0; sample < 20; ++sample) {
                        const uint32_t seed = 0x13579bdu + mode * 1000003u + partition * 1009u +
                                              rotation * 101u + selector * 37u + sample;
                        uint32_t state = seed;
                        Block block{};
                        // Uniform payloads exercise both p-bit values and the min/max anchor
                        // indices of every partition; random payloads vary endpoints independently.
                        for (uint8_t& byte : block)
                            byte = sample == 0 ? 0 : sample == 1 ? 255 : sample == 2 ? 0x55 :
                                   sample == 3 ? 0xaa : static_cast<uint8_t>(Random(state));
                        Bits(block, 0, mode + 1, 1u << mode);
                        if (partitionBits != 0) Bits(block, mode + 1, partitionBits, partition);
                        if (rotations != 1) Bits(block, mode + 1, 2, rotation);
                        if (selectors != 1) Bits(block, mode + 3, 1, selector);
                        One(BcFormat::Bc7, block, static_cast<int>(mode), seed, "bc7-partition-pbits-anchor");
                        const std::vector<uint8_t> bytes(block.begin(), block.end());
                        Equal(DecodeBc(BcFormat::Bc7Srgb, bytes, 4, 4),
                              DecodeBc(BcFormat::Bc7, bytes, 4, 4).rgba,
                              Label("srgb-byte-equivalence", BcFormat::Bc7Srgb, static_cast<int>(mode), seed));
                    }
    }
}

void OtherBlocksAndTiles() {
    for (BcFormat format : {BcFormat::Bc1, BcFormat::Bc3, BcFormat::Bc4, BcFormat::Bc5}) {
        for (uint32_t order = 0; order < 3; ++order) {
            Block block{};
            if (format == BcFormat::Bc1 || format == BcFormat::Bc3) {
                const uint32_t colour = format == BcFormat::Bc3 ? 64 : 0;
                Bits(block, colour, 16, order == 0 ? 0xf800 : 0x001f);
                Bits(block, colour + 16, 16, order == 1 ? 0xf800 : 0x001f);
                for (uint32_t i = 0; i < 16; ++i) Bits(block, colour + 32 + i * 2, 2, i % 4);
                if (format == BcFormat::Bc3) {
                    block[0] = order == 0 ? 211 : 17;
                    block[1] = order == 1 ? 211 : 17;
                    for (uint32_t i = 0; i < 16; ++i) Bits(block, 16 + i * 3, 3, i % 8);
                }
            } else {
                for (uint32_t channel = 0; channel < (format == BcFormat::Bc5 ? 2u : 1u); ++channel) {
                    const uint32_t offset = channel * 64;
                    Bits(block, offset, 8, order == 0 ? 211 : 17);
                    Bits(block, offset + 8, 8, order == 1 ? 211 : 17);
                    for (uint32_t i = 0; i < 16; ++i) Bits(block, offset + 16 + i * 3, 3, (i + channel) % 8);
                }
            }
            One(format, block, -1, order, "endpoint-orders-all-indices");
        }
    }
    for (BcFormat format : {BcFormat::Bc1, BcFormat::Bc1Srgb, BcFormat::Bc3,
                            BcFormat::Bc3Srgb, BcFormat::Bc4, BcFormat::Bc5, BcFormat::Bc7}) {
        for (uint32_t sample = 0; sample < 256; ++sample) {
            const uint32_t seed = 0x2468aceu + sample;
            uint32_t state = seed;
            Block block{};
            for (uint8_t& byte : block) byte = static_cast<uint8_t>(Random(state));
            One(format, block, -1, seed, "random-block");
            if (format == BcFormat::Bc1Srgb || format == BcFormat::Bc3Srgb) {
                const std::vector<uint8_t> bytes(block.begin(), block.begin() + BcBlockBytes(format));
                Equal(DecodeBc(format, bytes, 4, 4),
                      DecodeBc(format == BcFormat::Bc1Srgb ? BcFormat::Bc1 : BcFormat::Bc3, bytes, 4, 4).rgba,
                      Label("srgb-byte-equivalence", format, -1, seed));
            }
        }
        for (const auto& size : {std::array<uint32_t, 2>{1, 1}, {3, 5}, {7, 6}, {9, 2}, {4, 4}}) {
            uint32_t state = 0x10203040u;
            std::vector<uint8_t> bytes(BcEncodedSize(format, size[0], size[1]));
            for (uint8_t& byte : bytes) byte = static_cast<uint8_t>(Random(state));
            Differential(format, bytes, size[0], size[1], Label("partial-tile", format, -1, 0x10203040u));
        }
        for (int delta : {-1, 1}) {
            bool refused = false;
            try {
                (void)DecodeBc(format, std::vector<uint8_t>(static_cast<size_t>(static_cast<int>(BcBlockBytes(format)) + delta)), 4, 4);
            } catch (const std::invalid_argument&) { refused = true; }
            if (!refused) throw std::runtime_error(Label("invalid-size", format, -1, 0));
        }
        for (const auto& size : {std::array<uint32_t, 2>{0, 0}, {0, 4}, {4, 0}}) {
            bool refused = false;
            try { (void)DecodeBc(format, {}, size[0], size[1]); }
            catch (const std::invalid_argument&) { refused = true; }
            if (!refused) throw std::runtime_error(Label("zero-size", format, -1, 0));
        }
        bool refused = false;
        try {
            (void)DecodeBc(format, {}, std::numeric_limits<uint32_t>::max(),
                           std::numeric_limits<uint32_t>::max());
        } catch (const std::invalid_argument&) { refused = true; }
        if (!refused) throw std::runtime_error(Label("overflow-size", format, -1, 0));
    }
    bool refused = false;
    try { (void)DecodeBc(static_cast<BcFormat>(255), std::vector<uint8_t>(16), 4, 4); }
    catch (const std::invalid_argument&) { refused = true; }
    if (!refused) throw std::runtime_error("invalid BC format was not refused");
}

}  // namespace

void RunBcDecoderTests() {
    Analytic();
    Bc7Corpus();
    OtherBlocksAndTiles();
}

}  // namespace uzp::exporter::testing
