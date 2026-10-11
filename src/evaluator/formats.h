#pragma once

// Tile formats of the compositor (docs/architecture/04-layer-stack-and-compositing.md §4, §7):
// how a channel's `ChannelFormat` is held in a tile, the GPU format behind it and the bytes it
// costs the admission budget.
//
// A channel is stored at its own precision: 8- and 16-bit UNORM, 16- and 32-bit float. Grey
// channels take a one-channel format; colour channels (and the intermediates of isolated groups,
// which carry their coverage in a fourth plane) the four-channel format of the same depth, since
// no three-channel GPU format exists. sRGB8 channels hold their codes in an 8-bit UNORM format and
// are decoded in the kernels (no hardware sRGB conversion, 04 §4).

#include <cstdint>

#include "render/image_pass.h"
#include "uzp_core/types/enums.h"

namespace uzp::evaluator {

/// Tiles are 1024 x 1024 texels; a texture set at or below 1024 is one tile (04 §2).
inline constexpr uint32_t kTileSize = 1024;

struct TileFormat {
    render::TexelEncoding encoding = render::TexelEncoding::Unorm16;
    /// Logical channels: 1 (grey) or 3 (colour).
    uint8_t channels = 3;
    /// The channel is sRGB8: codes are decoded to linear for blending and encoded on write.
    bool srgb = false;
    /// A fourth plane holds the coverage (alpha) of an isolated group's intermediate.
    bool alpha = false;
    /// The coverage plane is written through binary16 first (round to nearest even), then with
    /// the plane's write rule: the sRGB8 intermediates of profiles with
    /// `EvaluatorProfile::srgb8HalfCoverage` (profile.h). No effect without `alpha`.
    bool halfCoverage = false;

    /// Planes the texture stores: 1, or 4 for colour and for intermediates with coverage.
    [[nodiscard]] uint32_t StoredChannels() const { return channels == 1 && !alpha ? 1u : 4u; }
    [[nodiscard]] uint32_t BytesPerChannel() const {
        switch (encoding) {
            case render::TexelEncoding::Unorm8: return 1;
            case render::TexelEncoding::Unorm16: return 2;
            case render::TexelEncoding::Float16: return 2;
            case render::TexelEncoding::Float32: return 4;
        }
        return 0;
    }
    [[nodiscard]] uint32_t BytesPerTexel() const { return StoredChannels() * BytesPerChannel(); }
    [[nodiscard]] bool IsUnorm() const {
        return encoding == render::TexelEncoding::Unorm8 ||
               encoding == render::TexelEncoding::Unorm16;
    }
    [[nodiscard]] uint32_t UnormBits() const {
        return encoding == render::TexelEncoding::Unorm8 ? 8u : 16u;
    }

    friend bool operator==(const TileFormat&, const TileFormat&) = default;
};

/// The tile format of a channel format; `alpha` adds the coverage plane.
[[nodiscard]] constexpr TileFormat TileFormatOf(core::ChannelFormat format, bool alpha = false) {
    using F = core::ChannelFormat;
    using E = render::TexelEncoding;
    switch (format) {
        case F::sRGB8: return {E::Unorm8, 3, true, alpha};
        case F::L8: return {E::Unorm8, 1, false, alpha};
        case F::RGB8: return {E::Unorm8, 3, false, alpha};
        case F::L16: return {E::Unorm16, 1, false, alpha};
        case F::RGB16: return {E::Unorm16, 3, false, alpha};
        case F::L16F: return {E::Float16, 1, false, alpha};
        case F::RGB16F: return {E::Float16, 3, false, alpha};
        case F::L32F: return {E::Float32, 1, false, alpha};
        case F::RGB32F: return {E::Float32, 3, false, alpha};
    }
    return {E::Unorm16, 3, false, alpha};
}

/// The GPU format a tile of `format` is created with.
[[nodiscard]] constexpr uz::RHIFormat RhiFormatOf(const TileFormat& format) {
    using E = render::TexelEncoding;
    const bool four = format.StoredChannels() == 4;
    switch (format.encoding) {
        case E::Unorm8: return four ? uz::RHIFormat::RGBA8Unorm : uz::RHIFormat::R8Unorm;
        case E::Unorm16: return four ? uz::RHIFormat::RGBA16Unorm : uz::RHIFormat::R16Unorm;
        case E::Float16: return four ? uz::RHIFormat::RGBA16Float : uz::RHIFormat::R16Float;
        case E::Float32: return four ? uz::RHIFormat::RGBA32Float : uz::RHIFormat::R32Float;
    }
    return uz::RHIFormat::Unknown;
}

/// Bytes a tile of `width` x `height` texels of `format` occupies.
[[nodiscard]] constexpr uint64_t TileBytes(const TileFormat& format, uint32_t width,
                                          uint32_t height) {
    return uint64_t{width} * height * format.BytesPerTexel();
}

/// The tile grid of a texture set resolution: tiles of at most `kTileSize` on each axis.
struct TileGrid {
    uint32_t width = 0;
    uint32_t height = 0;

    [[nodiscard]] uint32_t TilesX() const { return (width + kTileSize - 1) / kTileSize; }
    [[nodiscard]] uint32_t TilesY() const { return (height + kTileSize - 1) / kTileSize; }
    [[nodiscard]] uint32_t Count() const { return TilesX() * TilesY(); }
    [[nodiscard]] uint32_t TileWidth(uint32_t tx) const {
        const uint32_t x0 = tx * kTileSize;
        return x0 + kTileSize <= width ? kTileSize : width - x0;
    }
    [[nodiscard]] uint32_t TileHeight(uint32_t ty) const {
        const uint32_t y0 = ty * kTileSize;
        return y0 + kTileSize <= height ? kTileSize : height - y0;
    }
};

}  // namespace uzp::evaluator
