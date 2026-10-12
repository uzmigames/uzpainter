#pragma once

// The export's PNG writer (docs/architecture/08-export.md §3; task
// phase1.16_export-processing-encoders, decision 089). UzPainter's own encoder over the vendored
// zlib (ISO/IEC 15948 chunks), writing the files Painter 12.1.5 writes byte for byte: every
// distinct PNG file of the Tier 0 corpus is reproduced from its decoded samples (decision 103).
//
// The encoding (measured on Painter's files, parity/reports/phase1/export-processing-encoders.md):
//
// - Chunks: the signature, IHDR (non-interlaced; grey, RGB or RGBA), pHYs (2835 pixels per metre
//   on both axes, unit metre), the IDAT chunks, IEND.
// - Rows: each row is filtered with the filter whose filtered bytes have the smallest sum of
//   min(b, 256 - b); a tie keeps the earlier filter type. 8-bit grey chooses among all five filters
//   (None, Sub, Up, Average, Paeth); every other layout among None, Sub and Paeth only. The row
//   above the first row is zero.
// - Compression: one zlib stream over every filtered row (level 6, window bits 15, memory level 8;
//   strategy Z_DEFAULT_STRATEGY for 8-bit grey, Z_FILTERED otherwise), split into IDAT chunks of
//   8192 bytes, the last one shorter.
//
// The recorded layouts are written: grey (L), RGB and RGBA at 8 or 16 bits per sample, and grey
// and alpha (L+A) at 16 bits (8-bit L+A has no recording). The output depends on nothing but the
// image.

#include <cstdint>
#include <string>
#include <vector>

namespace uzp::exporter {

/// Integer samples of one image, rows top first, `channels` samples per pixel.
struct PngImage {
    uint32_t width = 0;
    uint32_t height = 0;
    /// 1 (grey), 2 (grey and alpha), 3 (RGB) or 4 (RGBA).
    uint32_t channels = 0;
    /// 8 or 16; 8-bit samples are below 256.
    uint32_t bitDepth = 16;
    std::vector<uint16_t> samples;
};

/// The PNG file of `image`. Throws std::invalid_argument for an empty image, a layout or bit depth
/// other than the recorded ones (8-bit L+A included), a sample count that does not match the size
/// or an 8-bit sample above 255.
[[nodiscard]] std::string EncodePng(const PngImage& image);

}  // namespace uzp::exporter
