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

BitmapColourSpace BitmapColourSpaceIn(const core::Project& project, std::string_view tag) {
    if (tag == "OcioColorSpace.sRGB") {
        return PainterOcio(project) ? BitmapColourSpaceOf("sRGB") : BitmapColourSpace::Unrecorded;
    }
    return BitmapColourSpaceOf(tag);
}

namespace {

/// The 16-bit codes at which the stored sRGB8 code steps up (`OcioSrgb16Code`, decision 422).
constexpr uint16_t kOcioSrgb16Breakpoints[255] = {104, 362, 621, 879, 1137, 1396, 1654, 1913, 2171, 2430, 2687, 2980, 3210, 3474, 3724, 4002, 4229, 4518, 4760, 4992, 5247, 5523, 5787, 6041, 6286, 6549, 6802, 7047, 7331, 7605, 7827, 8085, 8376, 8618, 8854, 9121, 9380, 9633, 9879, 10152, 10418, 10678, 10930, 11177, 11418, 11712, 11942, 12223, 12442, 12711, 12973, 13230, 13482, 13728, 14018, 14254, 14531, 14758, 15026, 15288, 15545, 15797, 16045, 16329, 16567, 16841, 17072, 17373, 17596, 17887, 18103, 18385, 18628, 18867, 19136, 19401, 19661, 19918, 20171, 20420, 20665, 20967, 21205, 21439, 21729, 21957, 22238, 22487, 22733, 23003, 23269, 23531, 23790, 24045, 24297, 24546, 24792, 25084, 25323, 25560, 25841, 26072, 26346, 26616, 26839, 27104, 27365, 27623, 27879, 28131, 28381, 28669, 28913, 29194, 29433, 29669, 29941, 30211, 30440, 30704, 30965, 31223, 31479, 31733, 31983, 32267, 32512, 32756, 33031, 33303, 33539, 33773, 34038, 34301, 34560, 34818, 35073, 35325, 35576, 35855, 36131, 36374, 36616, 36855, 37151, 37386, 37648, 37908, 38165, 38420, 38702, 38925, 39201, 39475, 39693, 39962, 40230, 40495, 40758, 40966, 41225, 41482, 41737, 42041, 42291, 42540, 42787, 43032, 43323, 43565, 43804, 44089, 44325, 44606, 44838, 45115, 45343, 45616, 45887, 46111, 46377, 46642, 46905, 47166, 47425, 47683, 47938, 48192, 48434, 48684, 48974, 49221, 49466, 49750, 49992, 50233, 50511, 50748, 51023, 51257, 51528, 51798, 52027, 52294, 52558, 52820, 53081, 53304, 53598, 53818, 54109, 54361, 54613, 54862, 55111, 55393, 55638, 55882, 56159, 56434, 56673, 56911, 57181, 57450, 57717, 57949, 58213, 58443, 58704, 58964, 59222, 59479, 59734, 59987, 60271, 60522, 60803, 61050, 61297, 61542, 61786, 62089, 62331, 62570, 62839, 63106, 63342, 63606, 63869, 64101, 64390, 64620, 64906, 65133, 65416};

}  // namespace

uint32_t OcioSrgb16Code(uint32_t c) {
    return static_cast<uint32_t>(std::upper_bound(std::begin(kOcioSrgb16Breakpoints),
                                                  std::end(kOcioSrgb16Breakpoints), c) -
                                 std::begin(kOcioSrgb16Breakpoints));
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

std::optional<OcioBitmapUse> OcioBitmapUseOf(const core::Project& project, std::string_view tag,
                                             std::optional<core::ChannelFormat> format) {
    const BitmapColourSpace space = BitmapColourSpaceIn(project, tag);
    if (!format) return space == BitmapColourSpace::Linear ? std::optional(OcioBitmapUse::Grey16Mask) : std::nullopt;
    if (*format == core::ChannelFormat::sRGB8) {
        if (space == BitmapColourSpace::Srgb) return OcioBitmapUse::SrgbFill;
        if (tag == "Raw") return OcioBitmapUse::RawFill;
        return std::nullopt;
    }
    if (tag == "Data" || tag == "DataSigned" || tag == "NormalXYZLeft") return OcioBitmapUse::DataFill;
    return std::nullopt;
}

bool OcioBitmapRecorded(OcioBitmapUse use, const UvProjection& projection, uint32_t width, uint32_t height,
                        const BitmapShape& shape) {
    const bool eight = shape.encoding == render::TexelEncoding::Unorm8;
    const bool sixteen = shape.encoding == render::TexelEncoding::Unorm16;
    bool kind = false;
    switch (use) {
        case OcioBitmapUse::SrgbFill: kind = (eight || sixteen) && shape.channels == 3; break;
        case OcioBitmapUse::RawFill: kind = eight && shape.channels == 3; break;
        case OcioBitmapUse::Grey16Mask: kind = sixteen && shape.channels == 1; break;
        case OcioBitmapUse::DataFill: kind = sixteen && (shape.channels == 1 || shape.channels == 3); break;
    }
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
