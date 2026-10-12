#include "preview/display_transform.h"

#include <bit>
#include <cmath>

#include "uzp_core/types/project.h"

namespace uzp::preview {

namespace {

std::string Supported() {
    return "the only supported configuration is OCIO with Painter's substance config (sha256 " +
           std::string(kSubstanceConfigSha256) + ") and the view '" + std::string(kDefaultSrgbView) + "'";
}

std::string Unsupported(const std::string& what) {
    return "unsupported_configuration: " + what + " is pinned out of the display transform (decision 038); " +
           Supported();
}

}  // namespace

DisplayConfiguration PinnedConfiguration() {
    return DisplayConfiguration{std::string(kOcioMode), std::string(kSubstanceConfigSha256), "",
                                std::string(kDefaultSrgbView)};
}

DisplayConfiguration ConfigurationOf(const core::Project& project, std::string_view view) {
    DisplayConfiguration config;
    config.mode = project.settings.color_management.mode;
    config.configHash = project.settings.color_management.config_hash;
    if (config.mode.empty() || config.mode == "legacy") {
        config.toneMapping = std::string(core::ToString(project.display.tone_mapping));
    }
    config.view = std::string(view);
    return config;
}

std::optional<std::string> UnsupportedConfiguration(const DisplayConfiguration& config) {
    if (config.mode.empty() || config.mode == "legacy") {
        return Unsupported("Legacy colour management with tone mapping " +
                           (config.toneMapping.empty() ? std::string("Linear") : config.toneMapping));
    }
    if (config.mode == "ace") return Unsupported("ACE colour management");
    if (config.mode != kOcioMode) return Unsupported("the colour-management mode '" + config.mode + "'");
    if (config.configHash.empty()) return Unsupported("an OCIO project without a config hash");
    if (config.configHash != kSubstanceConfigSha256) {
        return Unsupported("the OCIO config sha256 " + config.configHash);
    }
    if (config.view != kDefaultSrgbView) return Unsupported("the OCIO view '" + config.view + "'");
    return std::nullopt;
}

double SrgbEncode(double linear) {
    return linear <= 0.0031308 ? linear * 12.92 : 1.055 * std::pow(linear, 1.0 / 2.4) - 0.055;
}

float HalfToFloat(uint16_t bits) {
    const uint32_t sign = static_cast<uint32_t>(bits & 0x8000u) << 16;
    const uint32_t exponent = (bits >> 10) & 0x1Fu;
    const uint32_t mantissa = bits & 0x3FFu;
    if (exponent == 0x1Fu) return std::bit_cast<float>(sign | 0x7F800000u | (mantissa << 13));
    if (exponent == 0) {
        // Subnormal: mantissa * 2^-24, exact in float.
        const float magnitude = static_cast<float>(mantissa) * 0x1p-24f;
        return sign ? -magnitude : magnitude;
    }
    return std::bit_cast<float>(sign | ((exponent + 112u) << 23) | (mantissa << 13));
}

uint16_t FloatToHalf(float value) {
    const uint32_t f = std::bit_cast<uint32_t>(value);
    const uint16_t sign = static_cast<uint16_t>((f >> 16) & 0x8000u);
    const uint32_t magnitude = f & 0x7FFFFFFFu;
    if (magnitude > 0x7F800000u) return static_cast<uint16_t>(sign | 0x7E00u);  // NaN
    if (magnitude >= 0x477FF000u) return static_cast<uint16_t>(sign | 0x7C00u);  // rounds to infinity
    if (magnitude < 0x38800000u) {
        // Below the smallest normal half: a subnormal (or zero), magnitude / 2^-24 rounded to even.
        const float scaled = std::bit_cast<float>(magnitude) * 0x1p24f;  // exact
        return static_cast<uint16_t>(sign | static_cast<uint16_t>(std::nearbyint(scaled)));
    }
    const uint32_t rounded = magnitude + 0xFFFu + ((magnitude >> 13) & 1u);
    return static_cast<uint16_t>(sign | ((rounded - 0x38000000u) >> 13));
}

const std::vector<uint16_t>& DisplayTable() {
    static const std::vector<uint16_t> table = [] {
        std::vector<uint16_t> codes(65536);
        for (uint32_t bits = 0; bits < 65536; ++bits) {
            const float value = HalfToFloat(static_cast<uint16_t>(bits));
            double linear = std::isnan(value) ? 0.0 : static_cast<double>(value);
            linear = linear < 0.0 ? 0.0 : (linear > 1.0 ? 1.0 : linear);
            codes[bits] = static_cast<uint16_t>(std::lround(65535.0 * SrgbEncode(linear)));
        }
        return codes;
    }();
    return table;
}

uint16_t DisplayCode(float linear) { return DisplayTable()[FloatToHalf(linear)]; }

}  // namespace uzp::preview
