#include "evaluator/sources.h"

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
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

bool SrgbL8MaterialChannel(core::ChannelType channel, core::ChannelFormat format) {
    return format == core::ChannelFormat::L8 &&
           (channel == core::ChannelType::BaseColor || channel == core::ChannelType::Specular ||
            channel == core::ChannelType::Emissive);
}

bool PainterOcio(const core::Project& project) {
    const core::ColorManagement& cm = project.settings.color_management;
    return cm.mode == "ocio" && cm.config_hash == kPainterOcioConfigSha256;
}

namespace {

/// {component bits, working-value bits}, sorted by component bits (sources.h).
constexpr std::array<uint32_t, 2> kOcioSrgbDecode[] = {
#include "evaluator/ocio_srgb_table.inc"
};

}  // namespace

std::optional<float> PainterOcioSrgbDecode(float component) {
    const uint32_t bits = std::bit_cast<uint32_t>(component);
    const auto* end = std::end(kOcioSrgbDecode);
    const auto* it = std::lower_bound(std::begin(kOcioSrgbDecode), end, bits,
                                      [](const std::array<uint32_t, 2>& entry, uint32_t key) { return entry[0] < key; });
    if (it == end || (*it)[0] != bits) return std::nullopt;
    return std::bit_cast<float>((*it)[1]);
}

float PainterLegacySrgbDecode(float component) {
    constexpr float kInv1292 = 1.0f / 12.92f;  // the float32 quotients Painter multiplies by
    constexpr float kInv1055 = 1.0f / 1.055f;
    const float x = component;
    if (x <= 0.04045f) return x * kInv1292;
    const float base = (x + 0.055f) * kInv1055;
    return static_cast<float>(std::pow(static_cast<double>(base), static_cast<double>(2.4f)));
}

render::Result<void> CheckColourManagement(const core::Project& project, core::Id node) {
    const std::string& mode = project.settings.color_management.mode;
    if (mode.empty() || mode == "legacy" || PainterOcio(project)) return {};
    return EvalFail(EvalErrorKind::UnsupportedSource,
                    "colour management mode '" + mode +
                        "' with this configuration is outside this profile (sources are fitted under "
                        "legacy colour management and OCIO with Painter's substance config, decision 190)",
                    node);
}

namespace {

struct PngContext {
    spng_ctx* ctx = spng_ctx_new(0);
    ~PngContext() { spng_ctx_free(ctx); }
};

/// The shape `DecodeBitmap` gives an image of header `ihdr` (sources.h `BitmapShape`).
BitmapShape ShapeOf(const spng_ihdr& ihdr) {
    const bool grey =
        ihdr.color_type == SPNG_COLOR_TYPE_GRAYSCALE || ihdr.color_type == SPNG_COLOR_TYPE_GRAYSCALE_ALPHA;
    return BitmapShape{ihdr.width, ihdr.height, grey ? 1u : 3u,
                       ihdr.bit_depth == 16 ? render::TexelEncoding::Unorm16 : render::TexelEncoding::Unorm8};
}

}  // namespace

std::optional<BitmapShape> BitmapShapeOf(std::string_view bytes) {
    PngContext context;
    spng_ihdr ihdr{};
    if (context.ctx == nullptr || spng_set_png_buffer(context.ctx, bytes.data(), bytes.size()) != 0 ||
        spng_get_ihdr(context.ctx, &ihdr) != 0) {
        return std::nullopt;
    }
    return ShapeOf(ihdr);
}

bool OcioBitmapRecorded(bool mask, const UvProjection& projection, uint32_t width, uint32_t height,
                        const BitmapShape& shape) {
    const bool kind = mask ? shape.encoding == render::TexelEncoding::Unorm16 && shape.channels == 1
                           : shape.encoding == render::TexelEncoding::Unorm8 && shape.channels == 3;
    const bool oneToOne = shape.width == width && shape.height == height && projection.scale[0] == 1.0 &&
                          projection.scale[1] == 1.0 && projection.cosR == 1.0 && projection.sinR == 0.0 &&
                          projection.offset[0] == 0.0 && projection.offset[1] == 0.0;
    return kind && oneToOne;
}

render::Result<DecodedImage> DecodeBitmap(std::string_view bytes) {
    PngContext context;
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

    const BitmapShape shape = ShapeOf(ihdr);
    DecodedImage image;
    image.width = shape.width;
    image.height = shape.height;
    image.channels = shape.channels;
    image.encoding = shape.encoding;
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

bool DecodingResourceProvider::Available(std::string_view sha256) const {
    std::lock_guard<std::mutex> lock(m_mutex);
    if (m_cache.contains(sha256) || m_available.contains(sha256)) return true;
    std::optional<std::string> bytes = m_fetch ? m_fetch(sha256) : std::nullopt;
    if (!bytes || core::Sha256Hex(*bytes) != sha256) return false;
    m_available.emplace(sha256);
    return true;
}

size_t DecodingResourceProvider::Decodes() const {
    std::lock_guard<std::mutex> lock(m_mutex);
    return m_decodes;
}

}  // namespace uzp::evaluator
