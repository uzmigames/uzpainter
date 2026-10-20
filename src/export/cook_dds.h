#pragma once

#include "export/dds.h"
#include "export/mips.h"

namespace uzp::exporter {

struct DdsSpec {
    BcFormat format = BcFormat::Bc7;
    MipOptions mips;
};

/// Cook the full power-of-two mip chain using the existing mip and BC encoder policies.
/// Colour classes require BC7 sRGB; Linear and Normal require linear storage. Normal input
/// already carries its intended green convention; no channel is flipped here. BC5 normals
/// with negative Z are refused before encoding, because BC5 cannot retain that sign.
/// Invalid input and unsupported combinations throw std::invalid_argument.
[[nodiscard]] Dds CookDds(const BcEncoder& encoder, const Rgba16Image& canonical,
                          const DdsSpec& spec, uint32_t threads);

}  // namespace uzp::exporter
