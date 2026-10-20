#pragma once

// The BC encoder adapter (docs/architecture/08-export.md §3, DDS/BC row; task
// phase3.1_uze-uztexture-writer items 2.2 and 3.1, decision 315).
//
// `EncodeBc` turns an RGBA8 image into the blocks of one BC format, mip by mip, for the
// `.uztexture` writer (and the optional DDS variant of phase3.2_unreal-ue56-packed-preset). The
// block encoder behind it is a `BcEncoder` backend; the shipped backend is etcpak 2.1 with its
// bundled bc7enc (`thirdparty/etcpak/`). bc7enc_rdo stays a replacement candidate behind the same
// interface.
//
// Determinism: the output is a function of the image, the format and the backend only.
// - The image is padded to whole 4x4 blocks by repeating its last column and its last row.
// - Blocks are written in row-major order, 4x4 block rows top first, each at the offset its
//   position gives; a worker encodes a contiguous range of whole block rows.
// - Every backend block is a pure function of its 16 texels (etcpak's BC1/BC3/BC4/BC5 keep no
//   state; bc7enc's tables are built once, before any worker starts), so the thread count changes
//   which worker writes a block, never its bytes.
// - The quality settings are fixed per format (`BcEncoder::Settings`); nothing is tuned at run
//   time.

#include <cstdint>
#include <string_view>
#include <vector>

namespace uzp::exporter {

/// The BC formats of the adapter. The sRGB variants hold the same block bytes layout as their
/// UNORM twins; they differ in the format metadata and, for BC7, in the encoder's error weights
/// (perceptual for sRGB colour, uniform for linear data, decision 315). BC4 and BC5 have no sRGB
/// variant.
enum class BcFormat : uint8_t {
    Bc1,
    Bc1Srgb,
    Bc3,
    Bc3Srgb,
    Bc4,
    Bc5,
    Bc7,
    Bc7Srgb,
};

/// Rows top first, 4 bytes (R, G, B, A) per texel.
struct Rgba8Image {
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<uint8_t> rgba;
};

/// 8 for BC1 and BC4, 16 for the others.
[[nodiscard]] uint32_t BcBlockBytes(BcFormat format);
/// True for the sRGB variants.
[[nodiscard]] bool BcIsSrgb(BcFormat format);
/// `ceil(width / 4) * ceil(height / 4) * BcBlockBytes(format)`.
/// Throws std::invalid_argument for empty dimensions, an unknown format or uint64 overflow.
[[nodiscard]] uint64_t BcEncodedSize(BcFormat format, uint32_t width, uint32_t height);
/// "BC1", "BC1_SRGB", …, "BC7_SRGB".
[[nodiscard]] std::string_view BcFormatName(BcFormat format);

/// A block encoder. `EncodeBlockRows` encodes `blockRows` 4x4 block rows of a padded image (rows
/// of `paddedWidth` texels, a multiple of 4, one little-endian RGBA8 `uint32_t` per texel with R
/// in the low byte) starting at `src`, the first texel of the first of those block rows, into
/// `dst`, `paddedWidth / 4 * blockRows` blocks in row-major order. It must be callable from
/// several threads at once and write each block as a function of its texels only.
class BcEncoder {
public:
    virtual ~BcEncoder() = default;
    /// The backend and its version, for receipts ("etcpak 2.1").
    [[nodiscard]] virtual std::string_view Name() const = 0;
    /// The fixed quality settings of `format`, for receipts.
    [[nodiscard]] virtual std::string_view Settings(BcFormat format) const = 0;
    virtual void EncodeBlockRows(BcFormat format, const uint32_t* src, uint32_t paddedWidth,
                                 uint32_t blockRows, uint8_t* dst) const = 0;
};

/// The etcpak 2.1 backend (with bundled bc7enc).
[[nodiscard]] const BcEncoder& EtcpakEncoder();

/// The worker count `threads` resolves to: `threads`, or the hardware's thread count when 0
/// (at least 1).
[[nodiscard]] uint32_t ResolveBcThreads(uint32_t threads);

/// The BC blocks of `image` in `format`: `BcEncodedSize(format, width, height)` bytes. `threads`
/// is the worker count (0: `ResolveBcThreads(0)`); it never changes the bytes. Throws
/// std::invalid_argument for an empty image or a texel count that does not match its size.
/// Overflowing image sizes or padded dimensions are also refused before allocation.
[[nodiscard]] std::vector<uint8_t> EncodeBc(const BcEncoder& encoder, const Rgba8Image& image,
                                            BcFormat format, uint32_t threads);

}  // namespace uzp::exporter
