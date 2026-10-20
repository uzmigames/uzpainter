#include "uze_texture_check.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <string>

namespace uzp::exporter::testing {

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
        if (mip.offset > file.size() || mip.size > file.size() - mip.offset)
            Fail("rule 9: " + at + "blob exceeds the file");
        if (mip.width != std::max(1u, h.width >> level) ||
            mip.height != std::max(1u, h.height >> level))
            Fail(at + "dimensions are not max(1, base >> level)");
        const bool rgba = h.format == static_cast<uint32_t>(uz::TextureFormat::Uncompressed_RGBA8);
        const uint64_t units = rgba ? uint64_t{mip.width} * mip.height
                                   : ((uint64_t{mip.width} + 3) / 4) *
                                         ((uint64_t{mip.height} + 3) / 4);
        const uint32_t bytesPerUnit = rgba ? 4 : BlockBytes(h.format);
        if (units > std::numeric_limits<uint64_t>::max() / bytesPerUnit)
            Fail("rule 10: " + at + "size overflows");
        const uint64_t size = units * bytesPerUnit;
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
    if (texels == 0)
        throw std::invalid_argument("LossyDerivativeError: empty image");
    if (texels > std::numeric_limits<size_t>::max() / 4)
        throw std::invalid_argument("LossyDerivativeError: image size overflows");
    if (canonical.rgba.size() != static_cast<size_t>(texels) * 4)
        throw std::invalid_argument("LossyDerivativeError: pixels do not match dimensions");
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
        const uint64_t rank = texels - texels / 100;  // ceil(0.99 n), 1-based, without overflow
        result[c].p99 = errors[rank - 1];
    }
    return result;
}

}  // namespace uzp::exporter::testing
