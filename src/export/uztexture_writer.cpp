#include "export/uztexture_writer.h"

#include <algorithm>
#include <bit>
#include <cstring>
#include <limits>
#include <utility>

namespace uzp::exporter {

static_assert(std::endian::native == std::endian::little,
              "the .uztexture structs are copied as little-endian bytes");

namespace {

void ValidateImage(const Rgba16Image& image, const char* caller) {
    const uint64_t texels = uint64_t{image.width} * image.height;
    if (texels == 0)
        throw std::invalid_argument(std::string(caller) + ": empty image");
    if (texels > std::numeric_limits<size_t>::max() / 4)
        throw std::invalid_argument(std::string(caller) + ": image size overflows");
    if (image.rgba.size() != static_cast<size_t>(texels) * 4)
        throw std::invalid_argument(std::string(caller) + ": texel count does not match the image size");
}

bool KnownFormat(uz::TextureFormat format) {
    switch (format) {
        case uz::TextureFormat::Uncompressed_RGBA8:
        case uz::TextureFormat::BC1:
        case uz::TextureFormat::BC3:
        case uz::TextureFormat::BC5:
        case uz::TextureFormat::BC7:
        case uz::TextureFormat::BC4:
            return true;
    }
    return false;
}

BcFormat ToBcFormat(uz::TextureFormat format, bool srgb) {
    switch (format) {
        case uz::TextureFormat::BC1: return srgb ? BcFormat::Bc1Srgb : BcFormat::Bc1;
        case uz::TextureFormat::BC3: return srgb ? BcFormat::Bc3Srgb : BcFormat::Bc3;
        case uz::TextureFormat::BC4: return BcFormat::Bc4;
        case uz::TextureFormat::BC5: return BcFormat::Bc5;
        case uz::TextureFormat::BC7: return srgb ? BcFormat::Bc7Srgb : BcFormat::Bc7;
        case uz::TextureFormat::Uncompressed_RGBA8: break;
    }
    throw std::invalid_argument("not a block-compressed .uztexture format");
}

std::string NegativeZMessage(const std::string& binding, const NegativeZ& found) {
    return "normal map '" + binding + "': " + std::to_string(found.count) +
           " texel(s) with negative Z (first at " + std::to_string(found.firstX) + ", " +
           std::to_string(found.firstY) +
           "); BC5 keeps X and Y only, so the export must fail or route the map to an RGB "
           "format (08-export.md §4)";
}

}  // namespace

uint64_t UzTextureMipBytes(uz::TextureFormat format, uint32_t width, uint32_t height) {
    if (width == 0 || height == 0)
        throw std::invalid_argument("UzTextureMipBytes: empty size");
    if (format == uz::TextureFormat::Uncompressed_RGBA8) {
        const uint64_t texels = uint64_t{width} * height;
        if (texels > std::numeric_limits<uint64_t>::max() / 4)
            throw std::invalid_argument("UzTextureMipBytes: byte size overflows");
        return texels * 4;
    }
    return BcEncodedSize(ToBcFormat(format, false), width, height);
}

UzTexture WriteUzTextureFile(std::string binding, uz::TextureFormat format, bool srgb,
                             uint32_t width, uint32_t height,
                             const std::vector<std::vector<uint8_t>>& mips) {
    if (width == 0 || height == 0)
        throw std::invalid_argument("WriteUzTextureFile: empty size");
    if (!KnownFormat(format))
        throw std::invalid_argument("WriteUzTextureFile: format " +
                                    std::to_string(static_cast<uint32_t>(format)) +
                                    " is not a uz::TextureFormat");
    if (srgb && (format == uz::TextureFormat::BC4 || format == uz::TextureFormat::BC5))
        throw std::invalid_argument(
            "WriteUzTextureFile: BC4 and BC5 are always linear (TextureFormatToRHI)");
    const uint32_t full = FullMipCount(width, height);
    if (mips.empty() || mips.size() > full)
        throw std::invalid_argument("WriteUzTextureFile: " + std::to_string(mips.size()) +
                                    " mips, expected 1.." + std::to_string(full));

    UzTexture out;
    UzTextureMetadata& meta = out.metadata;
    meta.binding = std::move(binding);
    meta.format = format;
    meta.srgb = srgb;
    meta.width = width;
    meta.height = height;

    const uint32_t count = static_cast<uint32_t>(mips.size());
    uint64_t offset = sizeof(uz::UzTextureHeader) + uint64_t{count} * sizeof(uz::UzTextureMipLevel);
    for (uint32_t level = 0; level < count; ++level) {
        UzTextureMip mip;
        mip.width = std::max(1u, width >> level);
        mip.height = std::max(1u, height >> level);
        mip.size = UzTextureMipBytes(format, mip.width, mip.height);
        if (mips[level].size() != mip.size)
            throw std::invalid_argument("WriteUzTextureFile: mip " + std::to_string(level) +
                                        " holds " + std::to_string(mips[level].size()) +
                                        " bytes, expected " + std::to_string(mip.size));
        mip.offset = offset;
        if (mip.size > std::numeric_limits<uint64_t>::max() - offset)
            throw std::invalid_argument("WriteUzTextureFile: file size overflows");
        offset += mip.size;
        meta.mips.push_back(mip);
    }

    uz::UzTextureHeader header;
    header.magic = uz::kUzTextureMagic;
    header.version = uz::kUzTextureVersion;
    header.width = width;
    header.height = height;
    header.mipCount = count;
    header.format = static_cast<uint32_t>(format);
    header.flags = srgb ? uz::kUzTextureFlag_sRGB : 0u;

    if (offset > out.bytes.max_size())
        throw std::invalid_argument("WriteUzTextureFile: file exceeds the byte buffer limit");
    out.bytes.resize(static_cast<size_t>(offset));
    std::memcpy(out.bytes.data(), &header, sizeof(header));
    for (uint32_t level = 0; level < count; ++level) {
        uz::UzTextureMipLevel descriptor;
        descriptor.offset = meta.mips[level].offset;
        descriptor.size = meta.mips[level].size;
        descriptor.width = meta.mips[level].width;
        descriptor.height = meta.mips[level].height;
        std::memcpy(out.bytes.data() + sizeof(header) + uint64_t{level} * sizeof(descriptor),
                    &descriptor, sizeof(descriptor));
        if (!mips[level].empty())
            std::memcpy(out.bytes.data() + descriptor.offset, mips[level].data(),
                        mips[level].size());
    }
    return out;
}

NegativeZ FindNegativeZ(const Rgba16Image& normal) {
    ValidateImage(normal, "FindNegativeZ");
    NegativeZ found;
    for (uint64_t i = 0; i < uint64_t{normal.width} * normal.height; ++i) {
        if (normal.rgba[i * 4 + 2] > 32767) continue;
        if (found.count == 0) {
            found.firstX = static_cast<uint32_t>(i % normal.width);
            found.firstY = static_cast<uint32_t>(i / normal.width);
        }
        ++found.count;
    }
    return found;
}

NegativeZNormal::NegativeZNormal(const std::string& binding, const NegativeZ& negative)
    : std::runtime_error(NegativeZMessage(binding, negative)), found(negative) {}

UzTexture CookUzTexture(const BcEncoder& encoder, const Rgba16Image& canonical,
                        const UzTextureSpec& spec, uint32_t threads) {
    ValidateImage(canonical, "CookUzTexture");
    if (spec.mips.mapClass == MipClass::Normal && spec.srgb)
        throw std::invalid_argument("CookUzTexture: normal maps must be linear, not sRGB");
    if (spec.mips.mapClass == MipClass::Normal && spec.format == uz::TextureFormat::BC5) {
        const NegativeZ negative = FindNegativeZ(canonical);
        if (negative.count != 0) throw NegativeZNormal(spec.binding, negative);
    }
    if (!KnownFormat(spec.format))
        throw std::invalid_argument("CookUzTexture: unknown format");
    if (spec.srgb && (spec.format == uz::TextureFormat::BC4 || spec.format == uz::TextureFormat::BC5))
        throw std::invalid_argument("CookUzTexture: BC4 and BC5 are always linear");

    const std::vector<Rgba16Image> chain = GenerateMipChain(canonical, spec.mips);
    std::vector<std::vector<uint8_t>> blobs;
    blobs.reserve(chain.size());
    for (const Rgba16Image& level : chain) {
        Rgba8Image texels = QuantizeTo8(level);
        if (spec.format == uz::TextureFormat::Uncompressed_RGBA8)
            blobs.push_back(std::move(texels.rgba));
        else
            blobs.push_back(EncodeBc(encoder, texels, ToBcFormat(spec.format, spec.srgb), threads));
    }
    return WriteUzTextureFile(spec.binding, spec.format, spec.srgb, canonical.width,
                              canonical.height, blobs);
}

}  // namespace uzp::exporter
