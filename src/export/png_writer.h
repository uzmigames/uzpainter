#pragma once

// The export's PNG writer (docs/architecture/08-export.md §3; task
// phase1.16_export-processing-encoders, decision 089). UzPainter's own encoder over the vendored
// zlib (ISO/IEC 15948 chunks), writing the files Painter 12.1.5 writes byte for byte: every one
// of the 984 distinct PNG files of the Tier 0 corpus is reproduced from its decoded samples.
//
// The encoding (measured on Painter's files, parity/reports/phase1/export-processing-encoders.md):
//
// - Chunks: the signature, IHDR (non-interlaced), pHYs (2835 pixels per metre on both axes, unit
//   metre), the IDAT chunks, IEND.
// - Rows: each row is filtered with the filter, among None, Sub and Paeth only, whose filtered
//   bytes have the smallest sum of min(b, 256 - b); a tie keeps the earlier of None, Sub, Paeth.
//   The row above the first row is zero.
// - Compression: one zlib stream over every filtered row (level 6, window bits 15, memory level 8,
//   strategy Z_FILTERED), split into IDAT chunks of 8192 bytes, the last one shorter.
//
// Only the recorded layouts are written: 16 bits per sample, grey (L) or RGB (decision 090; 8 bits
// and the alpha layouts wait for recording R-090). The output depends on nothing but the image.

#include <cstdint>
#include <string>
#include <vector>

namespace uzp::exporter {

/// Integer samples of one image, rows top first, `channels` samples per pixel.
struct PngImage {
    uint32_t width = 0;
    uint32_t height = 0;
    /// 1 (grey) or 3 (RGB).
    uint32_t channels = 0;
    /// 16.
    uint32_t bitDepth = 16;
    std::vector<uint16_t> samples;
};

/// The PNG file of `image`. Throws std::invalid_argument for an empty image, a layout or bit depth
/// other than the recorded ones, or a sample count that does not match the size.
[[nodiscard]] std::string EncodePng(const PngImage& image);

}  // namespace uzp::exporter
