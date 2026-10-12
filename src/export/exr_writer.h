#pragma once

// The export's OpenEXR writer (docs/architecture/08-export.md §3; task
// phase1.16_export-processing-encoders, decision 089), over the vendored tinyexr
// (`thirdparty/tinyexr/`, with its recorded local change: OpenEXR's Huffman heap tie-break). It
// writes the files Painter 12.1.5 writes byte for byte: every one of the 216 distinct OpenEXR
// files of the Tier 0 corpus is reproduced from its decoded values.
//
// The encoding (measured on Painter's files, parity/reports/phase1/export-processing-encoders.md):
// a single-part scanline image, version field 2; the attributes channels, compression (PIZ),
// dataWindow and displayWindow (0, 0, width - 1, height - 1), lineOrder (increasing y),
// pixelAspectRatio 1, screenWindowCenter (0, 0) and screenWindowWidth 1, in that order; FLOAT
// samples; a grey image has the one channel `Y`, an RGB image the channels `B`, `G`, `R`
// (alphabetical, as OpenEXR lists them).
//
// Only the recorded layouts are written: 32-bit float, grey or RGB (decision 090; half floats and
// the alpha layouts wait for recording R-090). The output depends on nothing but the image.

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace uzp::exporter {

/// float32 samples of one image, rows top first, `channels` interleaved samples per pixel
/// (L, or R, G, B).
struct ExrImage {
    uint32_t width = 0;
    uint32_t height = 0;
    /// 1 (grey) or 3 (RGB).
    uint32_t channels = 0;
    std::vector<float> values;
};

/// The OpenEXR file of `image`. Throws std::invalid_argument for an empty image, a layout other than
/// the recorded ones or a value count that does not match the size, std::runtime_error when tinyexr
/// fails.
[[nodiscard]] std::string EncodeExr(const ExrImage& image);

/// Reads back a file EncodeExr writes (a FLOAT scanline image of channel `Y` or `B`, `G`, `R`):
/// its values in the layout of ExrImage. Throws std::runtime_error for any other file.
[[nodiscard]] ExrImage DecodeExr(std::string_view file);

}  // namespace uzp::exporter
