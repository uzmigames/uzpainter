#include "mesh/mask_image.h"

#include <algorithm>
#include <cmath>
#include <memory>
#include <string>

#include "mesh/import_error.h"
#include "spng.h"

namespace uzp::mesh {

namespace {

[[noreturn]] void Fail(const char* what, int code) {
    throw ImportError(ImportErrorKind::parse_error,
                      std::string("PNG: ") + what + ": " + spng_strerror(code));
}

}  // namespace

std::array<std::uint16_t, 4> ImageRgba16::At(std::uint32_t col, std::uint32_t row) const {
    const std::size_t i = (static_cast<std::size_t>(row) * width + col) * 4;
    return {rgba.at(i), rgba.at(i + 1), rgba.at(i + 2), rgba.at(i + 3)};
}

ImageRgba16 DecodePng(std::string_view bytes) {
    std::unique_ptr<spng_ctx, decltype(&spng_ctx_free)> ctx(spng_ctx_new(0), &spng_ctx_free);
    if (!ctx) throw ImportError(ImportErrorKind::parse_error, "PNG: cannot create a decoder");
    if (int e = spng_set_png_buffer(ctx.get(), bytes.data(), bytes.size())) Fail("buffer", e);
    spng_ihdr ihdr{};
    if (int e = spng_get_ihdr(ctx.get(), &ihdr)) Fail("header", e);
    std::size_t size = 0;
    if (int e = spng_decoded_image_size(ctx.get(), SPNG_FMT_RGBA16, &size)) Fail("size", e);
    ImageRgba16 image;
    image.width = ihdr.width;
    image.height = ihdr.height;
    image.bit_depth = ihdr.bit_depth;
    image.color_type = ihdr.color_type;
    image.rgba.resize(size / sizeof(std::uint16_t));
    // SPNG_FMT_RGBA16 is host-endian; rows come out in file order (top first).
    if (int e = spng_decode_image(ctx.get(), image.rgba.data(), size, SPNG_FMT_RGBA16, 0)) Fail("decode", e);
    return image;
}

Texel TexelAt(Float2 uv, std::uint32_t width, std::uint32_t height) {
    const double col = std::floor(static_cast<double>(uv.u) * width);
    const double row = std::floor((1.0 - static_cast<double>(uv.v)) * height);
    return Texel{static_cast<std::uint32_t>(std::clamp(col, 0.0, width - 1.0)),
                 static_cast<std::uint32_t>(std::clamp(row, 0.0, height - 1.0))};
}

}  // namespace uzp::mesh
