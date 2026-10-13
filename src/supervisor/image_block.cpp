// The image content block of `capture` over MCP (image_block.h).

#include "supervisor/image_block.h"

#include <algorithm>
#include <stdexcept>
#include <vector>

#include <pybind11/embed.h>

#include "evaluator/sources.h"
#include "export/png_writer.h"

namespace uzp::supervisor {

namespace {

std::uint32_t BigEndian32(std::string_view bytes, std::size_t at) {
    std::uint32_t value = 0;
    for (std::size_t i = 0; i < 4; ++i) value = (value << 8) | static_cast<unsigned char>(bytes[at + i]);
    return value;
}

}  // namespace

std::string PreviewPng(std::string_view png, std::uint32_t max_edge) {
    if (max_edge == 0) throw std::invalid_argument("max_edge must be at least 1");
    if (png.size() > kPreviewSourceBytes) throw std::invalid_argument("the PNG is over the size limit");
    // The size comes from IHDR before anything is decoded (the first chunk of every PNG).
    constexpr std::string_view kSignature("\x89PNG\r\n\x1a\n", 8);
    if (png.size() < 24 || png.substr(0, 8) != kSignature || png.substr(12, 4) != "IHDR") {
        throw std::invalid_argument("the file is not a PNG");
    }
    const std::uint32_t width = BigEndian32(png, 16);
    const std::uint32_t height = BigEndian32(png, 20);
    if (width == 0 || height == 0 || width > kPreviewSourceSide || height > kPreviewSourceSide) {
        throw std::invalid_argument("the PNG's size is outside 1 to 16384 pixels per side");
    }
    render::Result<evaluator::DecodedImage> decoded = evaluator::DecodeBitmap(png);
    if (!decoded) throw std::invalid_argument("the PNG does not decode: " + decoded.error().reason);
    const evaluator::DecodedImage& image = *decoded;
    const std::uint64_t maximum = image.encoding == render::TexelEncoding::Unorm16 ? 65535 : 255;
    const std::uint32_t edge = std::max(image.width, image.height);
    const std::uint32_t k = (edge + max_edge - 1) / max_edge;
    const std::uint32_t out_width = (image.width + k - 1) / k;
    const std::uint32_t out_height = (image.height + k - 1) / k;
    exporter::PngImage out{out_width, out_height, image.channels, 8, {}};
    out.samples.reserve(std::size_t{out_width} * out_height * image.channels);
    for (std::uint32_t oy = 0; oy < out_height; ++oy) {
        const std::uint32_t y_end = std::min(image.height, (oy + 1) * k);
        for (std::uint32_t ox = 0; ox < out_width; ++ox) {
            const std::uint32_t x_end = std::min(image.width, (ox + 1) * k);
            const std::uint64_t count = std::uint64_t{y_end - oy * k} * (x_end - ox * k);
            for (std::uint32_t c = 0; c < image.channels; ++c) {
                std::uint64_t sum = 0;
                for (std::uint32_t y = oy * k; y < y_end; ++y) {
                    for (std::uint32_t x = ox * k; x < x_end; ++x) sum += image.At(x, y, c);
                }
                // round(sum / count * 255 / maximum), half up, in integers.
                const std::uint64_t denominator = count * maximum;
                out.samples.push_back(static_cast<std::uint16_t>((sum * 255 * 2 + denominator) / (2 * denominator)));
            }
        }
    }
    return exporter::EncodePng(out);
}

}  // namespace uzp::supervisor

PYBIND11_EMBEDDED_MODULE(_uzpainter_image, m) {
    m.doc() = "The supervisor's image helper: the downscaled PNG of a capture's image block (decision 165).";
    m.def(
        "preview_png",
        [](const pybind11::bytes& png, std::uint32_t max_edge) {
            const std::string source = png;
            std::string preview;
            {
                pybind11::gil_scoped_release release;
                preview = uzp::supervisor::PreviewPng(source, max_edge);
            }
            return pybind11::bytes(preview);
        },
        pybind11::arg("png"), pybind11::arg("max_edge"),
        "The PNG `png` averaged over k x k blocks so its long edge is at most `max_edge`, as an 8-bit PNG "
        "(ValueError for a file that is not a decodable PNG within the limits).");
}
