#include "export/dds.h"

#include <algorithm>
#include <cstddef>
#include <limits>
#include <stdexcept>
#include <string>

#include "export/mips.h"

namespace uzp::exporter {
namespace {

uint32_t DxgiFormat(BcFormat format) {
    switch (format) {
        case BcFormat::Bc5: return 83;
        case BcFormat::Bc7: return 98;
        case BcFormat::Bc7Srgb: return 99;
        default: throw std::invalid_argument("WriteDdsFile: only BC5 and BC7 linear/sRGB are supported");
    }
}

void Put32(std::vector<uint8_t>& bytes, size_t offset, uint32_t value) {
    for (unsigned i = 0; i < 4; ++i) bytes[offset + i] = static_cast<uint8_t>(value >> (8 * i));
}

}  // namespace

Dds WriteDdsFile(BcFormat format, uint32_t width, uint32_t height,
                 const std::vector<std::vector<uint8_t>>& mips) {
    const uint32_t dxgi = DxgiFormat(format);
    if (width == 0 || height == 0) throw std::invalid_argument("WriteDdsFile: empty dimensions");
    if (mips.empty() || mips.size() > FullMipCount(width, height)) {
        throw std::invalid_argument("WriteDdsFile: mip count must be between 1 and the full chain length");
    }
    const uint64_t top_size = BcEncodedSize(format, width, height);
    if (top_size > std::numeric_limits<uint32_t>::max()) {
        throw std::invalid_argument("WriteDdsFile: top mip exceeds the DDS linear-size field");
    }
    Dds out;
    out.metadata.format = format;
    out.metadata.srgb = BcIsSrgb(format);
    out.metadata.width = width;
    out.metadata.height = height;
    uint64_t offset = 148;
    for (size_t level = 0; level < mips.size(); ++level) {
        DdsMip mip;
        mip.width = std::max(1u, width >> level);
        mip.height = std::max(1u, height >> level);
        mip.size = BcEncodedSize(format, mip.width, mip.height);
        if (mips[level].size() != mip.size) {
            throw std::invalid_argument("WriteDdsFile: mip " + std::to_string(level) + " has an invalid byte size");
        }
        mip.offset = offset;
        if (mip.size > std::numeric_limits<uint64_t>::max() - offset) {
            throw std::invalid_argument("WriteDdsFile: file size overflows");
        }
        offset += mip.size;
        out.metadata.mips.push_back(mip);
    }
    if (offset > out.bytes.max_size()) throw std::invalid_argument("WriteDdsFile: file exceeds the byte buffer limit");
    out.bytes.assign(static_cast<size_t>(offset), 0);
    // DDS_HEADER follows the magic; DDS_HEADER_DXT10 starts at byte 128.
    Put32(out.bytes, 0, 0x20534444);
    Put32(out.bytes, 4, 124);
    const bool has_mips = mips.size() > 1;
    Put32(out.bytes, 8, 0x00081007u | (has_mips ? 0x00020000u : 0u));
    Put32(out.bytes, 12, height);
    Put32(out.bytes, 16, width);
    Put32(out.bytes, 20, static_cast<uint32_t>(top_size));
    Put32(out.bytes, 28, static_cast<uint32_t>(mips.size()));
    Put32(out.bytes, 76, 32);
    Put32(out.bytes, 80, 0x4);
    Put32(out.bytes, 84, 0x30315844);
    Put32(out.bytes, 108, 0x1000u | (has_mips ? 0x00400008u : 0u));
    Put32(out.bytes, 128, dxgi);
    Put32(out.bytes, 132, 3);  // D3D10_RESOURCE_DIMENSION_TEXTURE2D
    Put32(out.bytes, 140, 1);  // one array element; alpha mode remains UNKNOWN
    for (size_t level = 0; level < mips.size(); ++level) {
        std::copy(mips[level].begin(), mips[level].end(),
                  out.bytes.begin() + static_cast<std::ptrdiff_t>(out.metadata.mips[level].offset));
    }
    return out;
}

}  // namespace uzp::exporter
