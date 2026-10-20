#pragma once

// The `.uztexture` writer (docs/architecture/08-export.md §4, 13-engine-integration.md §2.1;
// task phase3.1_uze-uztexture-writer items 2.6 and 2.7, decision 315).
//
// UzPainter's own writer of the format the vendored header `engine/asset/formats/uztexture_format.h`
// defines (its constants, `UzTextureHeader` and `UzTextureMipLevel`); the header's
// `WriteUzTexture` and `ReadUzTexture` declarations stay unimplemented in UzPainter's build. The
// file is the 64-byte header, `mipCount` 24-byte mip descriptors, then the mip blobs, largest
// first, tightly packed, every field little-endian:
// - header: magic `kUzTextureMagic`, version `kUzTextureVersion`, the base size, the mip count,
//   the `TextureFormat`, flags `kUzTextureFlag_sRGB` for sRGB-encoded data or 0, nine reserved
//   zero words;
// - mip n: absolute offset, byte size, max(1, width >> n) by max(1, height >> n).
//
// Where the header's comments disagree with its own declarations, the declarations win (decision
// 315): its validation list says `flags == 0` and `format` 0..4, while the header defines the sRGB
// flag bit and `TextureFormat::BC4 = 5`, and `TextureFormatToRHI` reads both. BC4 and BC5 are
// always linear there, so an sRGB BC4 or BC5 texture is refused instead of written with a flag the
// engine ignores.
//
// Each written texture also yields its metadata (format, colour space, engine binding and mips) for
// the receipt of the UzEngine preset (EXP-10).

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

#include "engine/asset/formats/uztexture_format.h"
#include "export/bc_encoder.h"
#include "export/mips.h"

namespace uzp::exporter {

struct UzTextureMip {
    uint64_t offset = 0;
    uint64_t size = 0;
    uint32_t width = 0;
    uint32_t height = 0;
};

/// What a written `.uztexture` holds, as the receipt records it.
struct UzTextureMetadata {
    /// The engine slot the texture feeds ("albedo", "normal", "orm", "emissive", "height", …).
    std::string binding;
    uz::TextureFormat format = uz::TextureFormat::Uncompressed_RGBA8;
    /// True when the texels are sRGB-encoded (the header's `kUzTextureFlag_sRGB`), else linear.
    bool srgb = false;
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<UzTextureMip> mips;
};

struct UzTexture {
    std::vector<uint8_t> bytes;
    UzTextureMetadata metadata;
};

/// The byte size of one mip of `format`: width * height * 4 for RGBA8, else
/// ceil(width / 4) * ceil(height / 4) * the block size (8 for BC1 and BC4, 16 otherwise).
[[nodiscard]] uint64_t UzTextureMipBytes(uz::TextureFormat format, uint32_t width, uint32_t height);

/// The `.uztexture` file of the mip blobs `mips` (level 0 first). Throws std::invalid_argument for
/// an empty size, a mip count outside [1, FullMipCount(width, height)], a format outside the
/// header's enum, an sRGB BC4 or BC5, or a blob whose size is not `UzTextureMipBytes` of its level.
[[nodiscard]] UzTexture WriteUzTextureFile(std::string binding, uz::TextureFormat format,
                                           bool srgb, uint32_t width, uint32_t height,
                                           const std::vector<std::vector<uint8_t>>& mips);

/// Negative-Z texels of a normal map (Z = B code / 65535 * 2 - 1 < 0, i.e. B <= 32767).
struct NegativeZ {
    uint64_t count = 0;
    uint32_t firstX = 0;
    uint32_t firstY = 0;
};
[[nodiscard]] NegativeZ FindNegativeZ(const Rgba16Image& normal);

/// A BC5 normal map that holds negative-Z texels: BC5 keeps X and Y only and the engine
/// reconstructs a positive Z, so writing it would silently change those texels.
class NegativeZNormal : public std::runtime_error {
public:
    NegativeZNormal(const std::string& binding, const NegativeZ& negative);
    NegativeZ found;
};

/// One texture of the UzEngine preset: its binding, stored format and colour space, and the
/// mip rules of its map class.
struct UzTextureSpec {
    std::string binding;
    uz::TextureFormat format = uz::TextureFormat::BC7;
    bool srgb = false;
    MipOptions mips;
};

/// The canonical map `canonical` as a `.uztexture`: its full mip chain (`GenerateMipChain`),
/// each level quantised to 8 bits and stored as `spec.format` (BC through `encoder`, RGBA8 as
/// is) with `threads` workers, then written. A `Normal` map stored as BC5 is checked first and
/// refused with `NegativeZNormal` when any texel has a negative Z; nothing is encoded then.
[[nodiscard]] UzTexture CookUzTexture(const BcEncoder& encoder, const Rgba16Image& canonical,
                                      const UzTextureSpec& spec, uint32_t threads);

}  // namespace uzp::exporter
