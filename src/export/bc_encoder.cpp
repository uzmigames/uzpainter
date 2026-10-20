#include "export/bc_encoder.h"

#include <algorithm>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <thread>

#include "ProcessDxtc.hpp"
#include "bc7enc.h"

namespace uzp::exporter {

uint32_t BcBlockBytes(BcFormat format) {
    switch (format) {
        case BcFormat::Bc1:
        case BcFormat::Bc1Srgb:
        case BcFormat::Bc4:
            return 8;
        case BcFormat::Bc3:
        case BcFormat::Bc3Srgb:
        case BcFormat::Bc5:
        case BcFormat::Bc7:
        case BcFormat::Bc7Srgb:
            return 16;
    }
    throw std::invalid_argument("unknown BC format");
}

bool BcIsSrgb(BcFormat format) {
    return format == BcFormat::Bc1Srgb || format == BcFormat::Bc3Srgb ||
           format == BcFormat::Bc7Srgb;
}

uint64_t BcEncodedSize(BcFormat format, uint32_t width, uint32_t height) {
    if (width == 0 || height == 0)
        throw std::invalid_argument("BcEncodedSize: empty size");
    const uint64_t blocksX = (uint64_t{width} + 3) / 4;
    const uint64_t blocksY = (uint64_t{height} + 3) / 4;
    const uint64_t count = blocksX * blocksY;
    const uint32_t bytes = BcBlockBytes(format);
    if (count > std::numeric_limits<uint64_t>::max() / bytes)
        throw std::invalid_argument("BcEncodedSize: byte size overflows");
    return count * bytes;
}

std::string_view BcFormatName(BcFormat format) {
    switch (format) {
        case BcFormat::Bc1: return "BC1";
        case BcFormat::Bc1Srgb: return "BC1_SRGB";
        case BcFormat::Bc3: return "BC3";
        case BcFormat::Bc3Srgb: return "BC3_SRGB";
        case BcFormat::Bc4: return "BC4";
        case BcFormat::Bc5: return "BC5";
        case BcFormat::Bc7: return "BC7";
        case BcFormat::Bc7Srgb: return "BC7_SRGB";
    }
    throw std::invalid_argument("unknown BC format");
}

namespace {

/// etcpak 2.1. BC1, BC3, BC4 and BC5 have no quality setting: etcpak's single-pass endpoint fit,
/// without dithering. BC7 runs bc7enc with its defaults (`bc7enc_compress_block_params_init`:
/// every mode, 64 partitions, uber level 0, least squares, the mode 1/7 partition filter bank) and
/// perceptual weights (128, 64, 16, 32 in YCbCrA) for the sRGB variant or uniform RGBA weights
/// for the linear one (decision 315).
class Etcpak final : public BcEncoder {
public:
    Etcpak() {
        // Builds bc7enc's global tables; the function-local static of `EtcpakEncoder` runs this
        // once, before any caller can reach `EncodeBlockRows`.
        bc7enc_compress_block_init();
        bc7enc_compress_block_params_init(&perceptual_);
        bc7enc_compress_block_params_init(&linear_);
        bc7enc_compress_block_params_init_linear_weights(&linear_);
    }

    std::string_view Name() const override { return "etcpak 2.1"; }

    std::string_view Settings(BcFormat format) const override {
        switch (format) {
            case BcFormat::Bc7:
                return "bc7enc: all modes, 64 partitions, uber level 0, least squares, mode 1/7 "
                       "filter bank, uniform RGBA weights";
            case BcFormat::Bc7Srgb:
                return "bc7enc: all modes, 64 partitions, uber level 0, least squares, mode 1/7 "
                       "filter bank, perceptual YCbCrA weights 128/64/16/32";
            default:
                return "etcpak: single-pass endpoint fit, no dithering";
        }
    }

    void EncodeBlockRows(BcFormat format, const uint32_t* src, uint32_t paddedWidth,
                         uint32_t blockRows, uint8_t* dst) const override {
        const uint32_t blocks = paddedWidth / 4 * blockRows;
        if (blocks == 0) return;
        auto* out = reinterpret_cast<uint64_t*>(dst);
        switch (format) {
            case BcFormat::Bc1:
            case BcFormat::Bc1Srgb:
                CompressBc1(src, out, blocks, paddedWidth);
                return;
            case BcFormat::Bc3:
            case BcFormat::Bc3Srgb:
                CompressBc3(src, out, blocks, paddedWidth);
                return;
            case BcFormat::Bc4:
                CompressBc4(src, out, blocks, paddedWidth);
                return;
            case BcFormat::Bc5:
                CompressBc5(src, out, blocks, paddedWidth);
                return;
            case BcFormat::Bc7:
                CompressBc7(src, out, blocks, paddedWidth, &linear_);
                return;
            case BcFormat::Bc7Srgb:
                CompressBc7(src, out, blocks, paddedWidth, &perceptual_);
                return;
        }
    }

private:
    bc7enc_compress_block_params perceptual_{};
    bc7enc_compress_block_params linear_{};
};

}  // namespace

const BcEncoder& EtcpakEncoder() {
    static const Etcpak encoder;
    return encoder;
}

uint32_t ResolveBcThreads(uint32_t threads) {
    if (threads != 0) return threads;
    return std::max(1u, std::thread::hardware_concurrency());
}

std::vector<uint8_t> EncodeBc(const BcEncoder& encoder, const Rgba8Image& image,
                              BcFormat format, uint32_t threads) {
    if (image.width == 0 || image.height == 0)
        throw std::invalid_argument("EncodeBc: empty image");
    const uint64_t texels = uint64_t{image.width} * image.height;
    if (texels > std::numeric_limits<size_t>::max() / 4)
        throw std::invalid_argument("EncodeBc: image size overflows");
    if (image.rgba.size() != static_cast<size_t>(texels) * 4)
        throw std::invalid_argument("EncodeBc: texel count does not match the image size");
    if (image.width > std::numeric_limits<uint32_t>::max() - 3 ||
        image.height > std::numeric_limits<uint32_t>::max() - 3)
        throw std::invalid_argument("EncodeBc: padded dimensions overflow");

    const uint32_t paddedWidth = (image.width + 3) / 4 * 4;
    const uint32_t paddedHeight = (image.height + 3) / 4 * 4;
    const uint64_t paddedTexels = uint64_t{paddedWidth} * paddedHeight;
    std::vector<uint32_t> padded;
    if (paddedTexels > padded.max_size())
        throw std::invalid_argument("EncodeBc: padded image exceeds the buffer limit");
    padded.resize(static_cast<size_t>(paddedTexels));
    for (uint32_t y = 0; y < paddedHeight; ++y) {
        const uint8_t* row = image.rgba.data() + uint64_t{std::min(y, image.height - 1)} *
                                                     image.width * 4;
        uint32_t* out = padded.data() + uint64_t{y} * paddedWidth;
        std::memcpy(out, row, uint64_t{image.width} * 4);
        for (uint32_t x = image.width; x < paddedWidth; ++x) out[x] = out[image.width - 1];
    }

    const uint32_t blockRows = paddedHeight / 4;
    const uint64_t rowBytes = uint64_t{paddedWidth / 4} * BcBlockBytes(format);
    std::vector<uint8_t> blocks(rowBytes * blockRows);
    const uint32_t workers = std::min(ResolveBcThreads(threads), blockRows);
    auto encodeRange = [&](uint32_t worker) {
        const uint32_t first = static_cast<uint32_t>(uint64_t{blockRows} * worker / workers);
        const uint32_t end = static_cast<uint32_t>(uint64_t{blockRows} * (worker + 1) / workers);
        encoder.EncodeBlockRows(format, padded.data() + uint64_t{first} * 4 * paddedWidth,
                                paddedWidth, end - first, blocks.data() + first * rowBytes);
    };
    {
        // Joined on every path out of the scope, before `blocks` is returned.
        std::vector<std::jthread> pool;
        pool.reserve(workers - 1);
        for (uint32_t worker = 1; worker < workers; ++worker) pool.emplace_back(encodeRange, worker);
        encodeRange(0);
    }
    return blocks;
}

}  // namespace uzp::exporter
