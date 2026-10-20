#pragma once

// Test-only readers of the UzEngine textures (task phase3.1_uze-uztexture-writer items 2.8 and
// 3.7, decision 315): UzPainter's own BC decoder and `.uztexture` reader, and the
// lossy-derivative error of `docs/architecture/14-parity-testing.md` §4. Compiled into
// `uzp-texture-tests.exe` only; never a UzEngine substitute, and the vendored header's
// `ReadUzTexture` stays unimplemented.

#include <array>
#include <cstdint>
#include <stdexcept>
#include <vector>

#include "engine/asset/formats/uztexture_format.h"
#include "export/bc_encoder.h"
#include "export/mips.h"

namespace uzp::exporter::testing {

/// The texels of `blocks` (BC `format`, `width` x `height`). BC4 decodes to (R, 0, 0, 255), BC5
/// to (R, G, 0, 255). Integer reconstruction and provenance: docs/BC-DECODER.md.
/// Throws std::invalid_argument for empty dimensions or a mismatched block size.
[[nodiscard]] Rgba8Image DecodeBc(BcFormat format, const std::vector<uint8_t>& blocks,
                                  uint32_t width, uint32_t height);

class UzTextureReadError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

struct ReadUzTexture {
    uz::UzTextureHeader header;
    std::vector<uz::UzTextureMipLevel> mips;
    std::vector<std::vector<uint8_t>> blobs;
};

/// Parses a `.uztexture` file against the vendored format definition, in the header's
/// validation order (with the flags and format rules of decision 315: flags 0 or
/// `kUzTextureFlag_sRGB`, format 0..5), plus the layout rules the header states: descriptor sizes
/// by format, mip dimensions max(1, base >> level), blobs tightly packed after the descriptors,
/// largest first, ending at the end of the file. Throws `UzTextureReadError` naming the rule.
[[nodiscard]] ReadUzTexture ParseUzTexture(const std::vector<uint8_t>& file);

/// Decoded error of one channel of a derivative against its canonical map, in [0, 1] units.
struct ChannelError {
    double max = 0.0;
    double mean = 0.0;
    double p99 = 0.0;
};

/// |decoded / 255 - canonical / 65535| per channel over every texel (the lossy-derivative
/// contract: a measurement, never authoring equality).
[[nodiscard]] std::array<ChannelError, 4> LossyDerivativeError(const Rgba16Image& canonical,
                                                               const Rgba8Image& decoded);

}  // namespace uzp::exporter::testing
