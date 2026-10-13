#include "evaluator/sources.h"

#include <cstring>
#include <string>
#include <vector>

#include "evaluator/error.h"
#include "spng.h"
#include "uzp_core/manifest/sha256.h"

namespace uzp::evaluator {

BitmapColourSpace BitmapColourSpaceOf(std::string_view tag) {
    if (tag == "sRGB" || tag == "LegacyColorSpace.sRGB") return BitmapColourSpace::Srgb;
    if (tag.empty() || tag == "Raw" || tag == "Data" || tag == "DataSigned" || tag == "NormalXYZLeft" ||
        tag == "Working" || tag == "LegacyColorSpace.Linear") {
        return BitmapColourSpace::Linear;
    }
    return BitmapColourSpace::Unrecorded;
}

render::Result<void> CheckColourManagement(const core::Project& project, core::Id node) {
    const std::string& mode = project.settings.color_management.mode;
    if (mode.empty() || mode == "legacy") return {};
    return EvalFail(EvalErrorKind::UnsupportedSource,
                    "colour management mode '" + mode +
                        "' is outside this profile (sources are fitted under legacy colour "
                        "management)",
                    node);
}

render::Result<DecodedImage> DecodeBitmap(std::string_view bytes) {
    struct Context {
        spng_ctx* ctx = spng_ctx_new(0);
        ~Context() { spng_ctx_free(ctx); }
    } context;
    auto fail = [](const char* what, int code) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        std::string("bitmap PNG ") + what + ": " + spng_strerror(code));
    };
    if (context.ctx == nullptr) {
        return EvalFail(EvalErrorKind::Internal, "cannot create a PNG decoder");
    }
    if (int e = spng_set_png_buffer(context.ctx, bytes.data(), bytes.size())) return fail("buffer", e);
    spng_ihdr ihdr{};
    if (int e = spng_get_ihdr(context.ctx, &ihdr)) return fail("header", e);
    const bool sixteen = ihdr.bit_depth == 16;
    const int format = sixteen ? SPNG_FMT_RGBA16 : SPNG_FMT_RGBA8;
    size_t size = 0;
    if (int e = spng_decoded_image_size(context.ctx, format, &size)) return fail("size", e);
    std::vector<unsigned char> rgba(size);
    // SPNG_FMT_RGBA16 is host-endian; rows come out top first.
    if (int e = spng_decode_image(context.ctx, rgba.data(), size, format, 0)) return fail("decode", e);

    DecodedImage image;
    image.width = ihdr.width;
    image.height = ihdr.height;
    const bool grey = ihdr.color_type == SPNG_COLOR_TYPE_GRAYSCALE ||
                      ihdr.color_type == SPNG_COLOR_TYPE_GRAYSCALE_ALPHA;
    image.channels = grey ? 1 : 3;
    image.encoding = sixteen ? render::TexelEncoding::Unorm16 : render::TexelEncoding::Unorm8;
    const size_t texels = size_t{image.width} * image.height;
    image.values.resize(texels * image.channels);
    for (size_t t = 0; t < texels; ++t) {
        for (uint32_t c = 0; c < image.channels; ++c) {
            uint32_t sample = 0;
            if (sixteen) {
                uint16_t value = 0;
                std::memcpy(&value, rgba.data() + (t * 4 + c) * 2, 2);
                sample = value;
            } else {
                sample = rgba[t * 4 + c];
            }
            image.values[t * image.channels + c] = sample;
        }
    }
    return image;
}

std::shared_ptr<const DecodedImage> DecodingResourceProvider::Fetch(std::string_view sha256) const {
    std::lock_guard<std::mutex> lock(m_mutex);
    const auto it = m_cache.find(sha256);
    if (it != m_cache.end()) return it->second;
    std::optional<std::string> bytes = m_fetch ? m_fetch(sha256) : std::nullopt;
    if (!bytes || core::Sha256Hex(*bytes) != sha256) return nullptr;
    render::Result<DecodedImage> decoded = DecodeBitmap(*bytes);
    if (!decoded) return nullptr;
    auto image = std::make_shared<const DecodedImage>(std::move(*decoded));
    m_cache.emplace(std::string(sha256), image);
    ++m_decodes;
    return image;
}

size_t DecodingResourceProvider::Decodes() const {
    std::lock_guard<std::mutex> lock(m_mutex);
    return m_decodes;
}

}  // namespace uzp::evaluator
