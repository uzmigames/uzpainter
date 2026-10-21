#pragma once

// Importance sampling of the infinite-sphere environment of the `painter_iray` path tracer: a
// piecewise-constant 2D distribution over the texels of the latitude-longitude radiance map, and
// the solid-angle density it induces (rulebook task phase3.4_path-tracer-transport, the CPU
// distribution and density of item 2.6; docs/architecture/07-preview-and-render-parity.md
// §3.2, §3.4). The environment's identity, exposure and dome (decision 038) and the kernel's
// GPU tables come with the rest of item 2.6.
//
// Sources (docs/approved-sources.md): P-PBRT, *Physically Based Rendering* 4th ed.: the
// piecewise-constant 1D and 2D distributions (`PiecewiseConstant1D`, `PiecewiseConstant2D`:
// the marginal density of the rows, the conditional density of the columns of the chosen row,
// each sampled by inverting its CDF with a continuous offset inside the interval) and the image
// infinite light of §12.5; the change of variables of the latitude-longitude parameterisation,
// d(omega) = 2 pi^2 sin(theta) du dv, so p(omega) = p(u, v) / (2 pi^2 sin(theta)).
//
// Direction to texel coordinates (Y up), parity/semantics/iray.json entry
// `environment-mapping`: u = frac(atan2(-x, z) / (2 pi) + 1/4 + rotation / 360),
// v = acos(y) / pi, u along the image row, v down the image (row 0 is +Y).
//
// Texel (row r, column c) weighs max(Y, 0) sin(theta_r), Y the BT.709 luminance
// 0.2126 R + 0.7152 G + 0.0722 B and theta_r = (r + 0.5) pi / H its row centre, as in the Phase 0
// render prototype (tools/parity/render_fits/environment.py). Tables are binary64.

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace uzp::render::pathtracer {

struct DirectionD {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

/// Texel coordinates (u, v) in [0, 1)^2 of a unit direction under `rotation_degrees`.
void DirectionToUv(DirectionD d, double rotation_degrees, double* u, double* v);

/// The unit direction of texel coordinates (u, v) under `rotation_degrees`.
DirectionD UvToDirection(double u, double v, double rotation_degrees);

struct EnvironmentSample {
    double u = 0.0;
    double v = 0.0;
    uint32_t row = 0;
    uint32_t column = 0;
    DirectionD direction;
    double pdf_uv = 0.0;           // density over [0, 1)^2
    double pdf_solid_angle = 0.0;  // density over directions; 0 at the poles
};

class EnvironmentDistribution {
public:
    /// The distribution of a `width` x `height` RGB map, `rgb` row-major from row 0 (+Y), three
    /// floats per texel. Fails on an empty map, a non-finite texel or no positive weight.
    static std::optional<EnvironmentDistribution> Build(uint32_t width, uint32_t height,
                                                        const float* rgb,
                                                        double rotation_degrees,
                                                        std::string* error);

    uint32_t Width() const { return width_; }
    uint32_t Height() const { return height_; }

    /// Samples a direction from two uniform numbers in [0, 1): xi1 picks the row, xi0 the
    /// column inside it.
    EnvironmentSample Sample(double xi0, double xi1) const;

    /// Density over [0, 1)^2 of the texel holding (u, v).
    double PdfUv(double u, double v) const;

    /// Solid-angle density with which `Sample` returns the unit direction `d`.
    double Pdf(DirectionD d) const;

    /// Probability of texel (row, column): its weight over the total weight.
    double TexelProbability(uint32_t row, uint32_t column) const;

private:
    EnvironmentDistribution() = default;

    uint32_t width_ = 0;
    uint32_t height_ = 0;
    double rotation_degrees_ = 0.0;
    std::vector<double> marginal_cdf_;     // height + 1 entries, 0 to 1
    std::vector<double> conditional_cdf_;  // height rows of width + 1 entries, 0 to 1
    std::vector<double> density_;          // height x width, weight / total x width x height
};

}  // namespace uzp::render::pathtracer
