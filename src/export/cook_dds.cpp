#include "export/cook_dds.h"

#include <limits>
#include <stdexcept>

namespace uzp::exporter {

Dds CookDds(const BcEncoder& encoder, const Rgba16Image& canonical,
            const DdsSpec& spec, uint32_t threads) {
    if (spec.format != BcFormat::Bc5 && spec.format != BcFormat::Bc7 && spec.format != BcFormat::Bc7Srgb) {
        throw std::invalid_argument("CookDds: only BC5 and BC7 linear/sRGB are supported");
    }
    bool colour = false;
    switch (spec.mips.mapClass) {
        case MipClass::Linear:
        case MipClass::Normal: break;
        case MipClass::Colour:
        case MipClass::MaskedColour: colour = true; break;
        default: throw std::invalid_argument("CookDds: invalid mip class");
    }
    if (colour != BcIsSrgb(spec.format)) {
        throw std::invalid_argument("CookDds: colour mips require sRGB; linear and normal mips require linear storage");
    }
    const uint64_t texels = uint64_t{canonical.width} * canonical.height;
    if (texels == 0 || texels > std::numeric_limits<size_t>::max() / 4 ||
        canonical.rgba.size() != static_cast<size_t>(texels) * 4) {
        throw std::invalid_argument("CookDds: empty, overflowing or mismatched image size");
    }
    if (BcEncodedSize(spec.format, canonical.width, canonical.height) > std::numeric_limits<uint32_t>::max()) {
        throw std::invalid_argument("CookDds: top mip exceeds the DDS linear-size field");
    }
    if (spec.mips.mapClass == MipClass::Normal && spec.format == BcFormat::Bc5) {
        for (size_t i = 2; i < canonical.rgba.size(); i += 4) {
            if (canonical.rgba[i] <= 32767) {
                throw std::invalid_argument("CookDds: BC5 normal has negative Z; an RGB format is required to preserve its sign");
            }
        }
    }
    const std::vector<Rgba16Image> chain = GenerateMipChain(canonical, spec.mips);
    std::vector<std::vector<uint8_t>> blobs;
    blobs.reserve(chain.size());
    for (const Rgba16Image& mip : chain) blobs.push_back(EncodeBc(encoder, QuantizeTo8(mip), spec.format, threads));
    return WriteDdsFile(spec.format, canonical.width, canonical.height, blobs);
}

}  // namespace uzp::exporter
