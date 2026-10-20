#include "uze_texture_check.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <string>

#include "bcdec.h"

namespace uzp::exporter::testing {

Rgba8Image DecodeBc(BcFormat format, const std::vector<uint8_t>& blocks, uint32_t width,
                    uint32_t height) {
    if (blocks.size() != BcEncodedSize(format, width, height))
        throw std::invalid_argument("DecodeBc: block bytes do not match the size");
    const uint32_t blocksX = (width + 3) / 4;
    const uint32_t blocksY = (height + 3) / 4;
    const uint32_t blockBytes = BcBlockBytes(format);
    Rgba8Image out;
    out.width = width;
    out.height = height;
    out.rgba.assign(uint64_t{width} * height * 4, 0);
    const uint8_t* block = blocks.data();
    for (uint32_t by = 0; by < blocksY; ++by) {
        for (uint32_t bx = 0; bx < blocksX; ++bx, block += blockBytes) {
            uint8_t rgba[16 * 4] = {};
            uint8_t channels[16 * 2] = {};
            switch (format) {
                case BcFormat::Bc1:
                case BcFormat::Bc1Srgb:
                    bcdec_bc1(block, rgba, 16);
                    break;
                case BcFormat::Bc3:
                case BcFormat::Bc3Srgb:
                    bcdec_bc3(block, rgba, 16);
                    break;
                case BcFormat::Bc7:
                case BcFormat::Bc7Srgb:
                    bcdec_bc7(block, rgba, 16);
                    break;
                case BcFormat::Bc4:
                    bcdec_bc4(block, channels, 4);
                    for (int i = 0; i < 16; ++i) {
                        rgba[i * 4] = channels[i];
                        rgba[i * 4 + 3] = 255;
                    }
                    break;
                case BcFormat::Bc5:
                    bcdec_bc5(block, channels, 8);
                    for (int i = 0; i < 16; ++i) {
                        rgba[i * 4] = channels[i * 2];
                        rgba[i * 4 + 1] = channels[i * 2 + 1];
                        rgba[i * 4 + 3] = 255;
                    }
                    break;
            }
            for (uint32_t y = 0; y < 4; ++y) {
                const uint32_t ty = by * 4 + y;
                if (ty >= height) break;
                for (uint32_t x = 0; x < 4; ++x) {
                    const uint32_t tx = bx * 4 + x;
                    if (tx >= width) break;
                    std::memcpy(out.rgba.data() + (uint64_t{ty} * width + tx) * 4,
                                rgba + (y * 4 + x) * 4, 4);
                }
            }
        }
    }
    return out;
}

namespace {

[[noreturn]] void Fail(const std::string& rule) { throw UzTextureReadError(rule); }

uint32_t BlockBytes(uint32_t format) {
    return format == static_cast<uint32_t>(uz::TextureFormat::BC1) ||
                   format == static_cast<uint32_t>(uz::TextureFormat::BC4)
               ? 8
               : 16;
}

}  // namespace

ReadUzTexture ParseUzTexture(const std::vector<uint8_t>& file) {
    ReadUzTexture out;
    // 1. The header fits.
    if (file.size() < sizeof(uz::UzTextureHeader)) Fail("rule 1: file smaller than the header");
    std::memcpy(&out.header, file.data(), sizeof(out.header));
    const uz::UzTextureHeader& h = out.header;
    // 2-4. Magic, version, flags.
    if (h.magic != uz::kUzTextureMagic) Fail("rule 2: magic is not UZTX");
    if (h.version != uz::kUzTextureVersion) Fail("rule 3: version is not 1");
    if (h.flags != 0 && h.flags != uz::kUzTextureFlag_sRGB)
        Fail("rule 4: flags other than the sRGB bit");
    for (uint32_t word : h.reserved)
        if (word != 0) Fail("header: reserved words must be zero");
    // 5-7. Size, mip count, format.
    if (h.width == 0 || h.height == 0) Fail("rule 5: empty size");
    if (h.mipCount < 1 || h.mipCount > FullMipCount(h.width, h.height))
        Fail("rule 6: mip count outside [1, floor(log2(max(w, h))) + 1]");
    if (h.format > static_cast<uint32_t>(uz::TextureFormat::BC4)) Fail("rule 7: unknown format");
    const bool srgb = (h.flags & uz::kUzTextureFlag_sRGB) != 0;
    if (srgb && (h.format == static_cast<uint32_t>(uz::TextureFormat::BC4) ||
                 h.format == static_cast<uint32_t>(uz::TextureFormat::BC5)))
        Fail("format: BC4 and BC5 are always linear");
    // 8. The descriptors fit.
    const uint64_t descriptors = uint64_t{h.mipCount} * sizeof(uz::UzTextureMipLevel);
    if (file.size() < sizeof(uz::UzTextureHeader) + descriptors)
        Fail("rule 8: mip descriptors exceed the file");
    out.mips.resize(h.mipCount);
    std::memcpy(out.mips.data(), file.data() + sizeof(uz::UzTextureHeader), descriptors);
    // 9-10 and the layout: each blob in place, sized by its format and dimensions.
    uint64_t expectedOffset = sizeof(uz::UzTextureHeader) + descriptors;
    for (uint32_t level = 0; level < h.mipCount; ++level) {
        const uz::UzTextureMipLevel& mip = out.mips[level];
        const std::string at = "mip " + std::to_string(level) + ": ";
        if (mip.offset + mip.size > file.size()) Fail("rule 9: " + at + "blob exceeds the file");
        if (mip.width != std::max(1u, h.width >> level) ||
            mip.height != std::max(1u, h.height >> level))
            Fail(at + "dimensions are not max(1, base >> level)");
        const uint64_t size =
            h.format == static_cast<uint32_t>(uz::TextureFormat::Uncompressed_RGBA8)
                ? uint64_t{mip.width} * mip.height * 4
                : uint64_t{(mip.width + 3) / 4} * ((mip.height + 3) / 4) * BlockBytes(h.format);
        if (mip.size != size) Fail("rule 10: " + at + "size does not match its format");
        if (mip.offset != expectedOffset) Fail(at + "blob is not packed after the previous one");
        expectedOffset += mip.size;
        out.blobs.emplace_back(file.begin() + static_cast<std::ptrdiff_t>(mip.offset),
                               file.begin() + static_cast<std::ptrdiff_t>(mip.offset + mip.size));
    }
    if (expectedOffset != file.size()) Fail("layout: bytes after the last mip");
    return out;
}

std::array<ChannelError, 4> LossyDerivativeError(const Rgba16Image& canonical,
                                                 const Rgba8Image& decoded) {
    if (canonical.width != decoded.width || canonical.height != decoded.height ||
        canonical.rgba.size() != decoded.rgba.size())
        throw std::invalid_argument("LossyDerivativeError: sizes differ");
    const uint64_t texels = uint64_t{canonical.width} * canonical.height;
    std::array<ChannelError, 4> result{};
    std::vector<double> errors(texels);
    for (uint32_t c = 0; c < 4; ++c) {
        double sum = 0.0;
        for (uint64_t i = 0; i < texels; ++i) {
            errors[i] = std::fabs(decoded.rgba[i * 4 + c] / 255.0 -
                                  canonical.rgba[i * 4 + c] / 65535.0);
            sum += errors[i];
        }
        std::sort(errors.begin(), errors.end());
        result[c].max = errors.back();
        result[c].mean = sum / static_cast<double>(texels);
        const uint64_t rank = (texels * 99 + 99) / 100;  // ceil(0.99 n), 1-based
        result[c].p99 = errors[rank - 1];
    }
    return result;
}

}  // namespace uzp::exporter::testing
