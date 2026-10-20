#pragma once

#include <cstdint>
#include <vector>

#include "export/bc_encoder.h"

namespace uzp::exporter {

struct DdsMip {
    uint64_t offset = 0;
    uint64_t size = 0;
    uint32_t width = 0;
    uint32_t height = 0;
};

struct DdsMetadata {
    BcFormat format = BcFormat::Bc7;
    bool srgb = false;
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<DdsMip> mips;
};

struct Dds {
    std::vector<uint8_t> bytes;
    DdsMetadata metadata;
};

/// A single 2D DDS texture with a DX10 header, BC5 or BC7 (linear or sRGB).
/// Format source: S-DDS-MS in docs/approved-sources.md (Microsoft DDS structures and guide).
/// Mips are largest first, tightly packed, with dimensions max(1, base >> level).
/// Partial chains and non-power-of-two dimensions are accepted. Invalid formats, dimensions,
/// mip counts, blob lengths and sizes exceeding the header or buffer limits throw invalid_argument.
[[nodiscard]] Dds WriteDdsFile(BcFormat format, uint32_t width, uint32_t height,
                               const std::vector<std::vector<uint8_t>>& mips);

}  // namespace uzp::exporter
