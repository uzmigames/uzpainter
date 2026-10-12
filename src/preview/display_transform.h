#pragma once

// The display transform of the preview viewport (`painter_viewport`, docs/architecture/
// 07-preview-and-render-parity.md §3.4, §6; task phase2.1_preview-viewport-window item 2.3;
// decisions 038, 042 and 134).
//
// One display configuration is supported: OCIO colour management with Painter's substance config,
// identified by its SHA-256 (`kSubstanceConfigSha256`), and the view `Default - sRGB`. It is
// realised as the calibrated model of that view (parity/semantics/iray.json `display-encoding`):
//
//   code = round(65535 * encode(binary16(clamp(L, 0, 1))))
//
// with `encode` the IEC 61966-2-1 sRGB encoding, computed in double on the CPU into a table of the
// 65536 binary16 bit patterns (`DisplayTable`). The GPU pass converts each linear value to binary16
// (round to nearest even) and looks its code up in the same table, so GPU and CPU codes are equal
// by construction. NaN maps to 0, negative values and -0 to 0, values above 1 and +infinity to
// 65535. OpenColorIO is not linked and Painter's config file is never read: the configuration is
// identified by `{mode, config hash, view}` (decision 134).
//
// Every other configuration fails before rendering with an `unsupported_configuration` error that
// names the part that differs and decision 038: Legacy colour management (tone mapping `Linear` or
// `ACES`), ACE mode, OCIO with another config or no config hash, another view.

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "python/display.h"

namespace uzp::core {
struct Project;
}

namespace uzp::preview {

/// SHA-256 of Painter 12.1.5's `resources/ocio/substance/config.ocio`, the display presets' pin
/// (src/python/display.h; parity/reports/phase0/iray-capture-procedure.md).
inline constexpr std::string_view kSubstanceConfigSha256 = python::display::kOcioConfigSha256;
/// The one supported OCIO view.
inline constexpr std::string_view kDefaultSrgbView = "Default - sRGB";
/// The colour-management mode of an OCIO project.
inline constexpr std::string_view kOcioMode = "ocio";

/// What a render is asked to display: the project's colour management and the requested view.
struct DisplayConfiguration {
    /// The project's `settings.color_management.mode` ("" and "legacy" are Legacy).
    std::string mode;
    /// `settings.color_management.config_hash` ("" when none).
    std::string configHash;
    /// Legacy only: the project's tone mapping, "Linear" or "ACES".
    std::string toneMapping;
    /// The OCIO view to display through; Painter does not save it with the project.
    std::string view{kDefaultSrgbView};

    friend bool operator==(const DisplayConfiguration&, const DisplayConfiguration&) = default;
};

/// The pinned configuration: OCIO, Painter's substance config, `Default - sRGB`.
[[nodiscard]] DisplayConfiguration PinnedConfiguration();

/// The configuration of `project` displayed through `view`.
[[nodiscard]] DisplayConfiguration ConfigurationOf(const core::Project& project,
                                                   std::string_view view = kDefaultSrgbView);

/// Empty for the pinned configuration; otherwise the message of the `unsupported_configuration`
/// error, which names what differs and decision 038, e.g. "unsupported_configuration: Legacy colour
/// management with tone mapping ACES is pinned out of the display transform (decision 038); the only
/// supported configuration is OCIO with Painter's substance config (sha256 15059d4b...) and the view
/// 'Default - sRGB'".
[[nodiscard]] std::optional<std::string> UnsupportedConfiguration(const DisplayConfiguration& config);

/// IEC 61966-2-1 sRGB encoding of a linear value in [0, 1], in double.
[[nodiscard]] double SrgbEncode(double linear);

/// The value of a binary16 bit pattern.
[[nodiscard]] float HalfToFloat(uint16_t bits);
/// `value` rounded to binary16, nearest even (overflow to infinity, NaN kept as a quiet NaN).
[[nodiscard]] uint16_t FloatToHalf(float value);

/// The 16-bit display code of each binary16 bit pattern (index = the pattern).
[[nodiscard]] const std::vector<uint16_t>& DisplayTable();

/// The 16-bit display code of the linear value `linear` (through its binary16 rounding).
[[nodiscard]] uint16_t DisplayCode(float linear);

/// The 8-bit code closest to a 16-bit display code (`round(code / 257)`), for 8-bit windows.
[[nodiscard]] constexpr uint8_t DisplayCode8(uint16_t code) {
    return static_cast<uint8_t>((code + 128u) / 257u);
}

}  // namespace uzp::preview
