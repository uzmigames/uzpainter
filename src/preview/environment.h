#pragma once

// Image-based lighting of the preview viewport (docs/architecture/07-preview-and-render-parity.md
// §6; task phase2.1_preview-viewport-window item 2.1), precomputed on the CPU from the project's
// environment:
//
// - SH irradiance (Ramamoorthi and Hanrahan 2001): the radiance projected on the nine real
//   spherical harmonics of bands 0-2 and convolved with the clamped cosine, so the irradiance at a
//   unit normal n is `E(n) = sum_i sh[i] Y_i(n)`.
// - Split-sum specular (Karis 2013): the environment prefiltered with the GGX lobe (alpha =
//   roughness^2, n = v = r) at `kRadianceLevels` roughness steps, and a directional-albedo table
//   over (n.v, roughness) with the height-correlated Smith masking (Heitz 2014) and Schlick's
//   Fresnel (1994): `A` and `B` with `F0 A + B` the specular albedo. Its third column `D` is the
//   directional albedo of Burley's diffuse lobe (2012) under uniform lighting, which scales the
//   SH irradiance.
//
// Environment images are equirectangular, row 0 at +Y (up), with the direction mapping of
// parity/semantics/iray.json `environment-mapping`: u = frac(atan2(-d.x, d.z) / (2 pi) + 1/4 +
// rotation / 360), v = acos(d.y) / pi; bilinear on texel centres, u wrapping, v clamped.
//
// Every function is deterministic: fixed sample sequences (Hammersley), fixed summation order,
// double accumulation.

#include <array>
#include <cstdint>
#include <expected>
#include <string>
#include <string_view>
#include <vector>

namespace uzp::preview {

/// An equirectangular linear-RGB image, rows top first (row 0 = +Y), three floats per texel.
struct EnvironmentImage {
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<float> rgb;
};

/// Decodes an environment file: OpenEXR (tinyexr; RGB or RGBA, half or float) or Radiance HDR
/// (RGBE, flat or run-length encoded, `-Y <h> +X <w>`). Any other encoding, a malformed file or a
/// non-finite or negative texel is an error naming the reason.
[[nodiscard]] std::expected<EnvironmentImage, std::string> DecodeEnvironment(std::string_view bytes);

/// A uniform environment of `width` x `height` texels (tests).
[[nodiscard]] EnvironmentImage UniformEnvironment(float r, float g, float b, uint32_t width = 64,
                                                  uint32_t height = 32);

/// The prefiltered radiance levels: level l has roughness l / (kRadianceLevels - 1) and is
/// `kRadianceWidth >> l` x `kRadianceWidth >> (l + 1)` texels.
inline constexpr uint32_t kRadianceLevels = 6;
inline constexpr uint32_t kRadianceWidth = 512;
/// GGX importance samples per prefiltered texel (levels 1 and up; level 0 is the mirror lobe).
inline constexpr uint32_t kPrefilterSamples = 256;
/// The albedo table is `kBrdfTableSize` x `kBrdfTableSize`: column i at n.v = (i + 1/2) / size,
/// row j at roughness = j / (size - 1).
inline constexpr uint32_t kBrdfTableSize = 32;
inline constexpr uint32_t kBrdfSamples = 512;

struct RadianceLevel {
    uint32_t width = 0;
    uint32_t height = 0;
    float roughness = 0.0f;
    std::vector<float> rgb;
};

struct EnvironmentLighting {
    /// sh[3 i + c]: coefficient i (Y00, Y1-1, Y10, Y11, Y2-2, Y2-1, Y20, Y21, Y22) of channel c,
    /// already convolved with the clamped cosine (A0 = pi, A1 = 2 pi / 3, A2 = pi / 4).
    std::array<float, 27> sh{};
    std::vector<RadianceLevel> radiance;
    /// (A, B, D) per entry, rows by roughness, columns by n.v (see `kBrdfTableSize`).
    std::vector<float> brdf;
};

/// The direction of equirectangular coordinates (u, v) at rotation 0 (the inverse of the mapping
/// above).
[[nodiscard]] std::array<double, 3> DirectionOf(double u, double v);

/// The bilinear sample of `image` in direction `d` (unit) rotated by `rotationDegrees`.
[[nodiscard]] std::array<float, 3> SampleDirection(const EnvironmentImage& image, const std::array<double, 3>& d,
                                                   double rotationDegrees = 0.0);

/// The lighting of `image`; the radiance is used as stored (exposure and intensity apply at
/// shading time).
[[nodiscard]] EnvironmentLighting PrecomputeLighting(const EnvironmentImage& image);

/// The lighting of the environment file `bytes`, whose SHA-256 is `sha256` (bytes the caller has
/// checked against it): from the persistent caches (render/disk_cache.h, area `lighting`;
/// decision 253) when they hold it, else decoded and precomputed (`PrecomputeLighting`), then
/// stored. The key covers `sha256`, the sampling constants above, the build fingerprint and the
/// MXCSR control bits; the payload is every float of the result, bit for bit. A decode failure is
/// the error.
[[nodiscard]] std::expected<EnvironmentLighting, std::string> LightingOf(std::string_view sha256, std::string_view bytes);

/// The SH irradiance at the unit normal `n` (the CPU reference of the shader's evaluation).
[[nodiscard]] std::array<float, 3> Irradiance(const EnvironmentLighting& lighting, const std::array<double, 3>& n);

/// The table entry (A, B, D) at column `nv` and row `roughness`.
[[nodiscard]] std::array<float, 3> BrdfEntry(const EnvironmentLighting& lighting, uint32_t nv, uint32_t roughness);

}  // namespace uzp::preview
