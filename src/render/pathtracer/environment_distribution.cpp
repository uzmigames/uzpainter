#include "render/pathtracer/environment_distribution.h"

#include <algorithm>
#include <cmath>

namespace uzp::render::pathtracer {
namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr double kTwoPiSquared = 2.0 * kPi * kPi;

// IEC 61966-2-1 (BT.709 primaries) luminance row, as tools/parity/render_fits/environment.py.
constexpr double kLuminanceR = 0.2126;
constexpr double kLuminanceG = 0.7152;
constexpr double kLuminanceB = 0.0722;

// The interval i of a non-decreasing CDF with cdf[i] <= x < cdf[i + 1], clamped to
// [0, count - 1] (P-PBRT FindInterval).
uint32_t FindInterval(const double* cdf, uint32_t count, double x) {
    const double* upper = std::upper_bound(cdf, cdf + count + 1, x);
    const auto index = static_cast<int64_t>(upper - cdf) - 1;
    return static_cast<uint32_t>(std::clamp<int64_t>(index, 0, int64_t(count) - 1));
}

// The offset of x inside [low, high), or the interval's middle when it is empty.
double Offset(double x, double low, double high) {
    return high > low ? (x - low) / (high - low) : 0.5;
}

uint32_t Cell(double t, uint32_t count) {
    const double scaled = std::floor(t * double(count));
    if (!(scaled > 0.0)) return 0;
    return static_cast<uint32_t>(std::min(scaled, double(count - 1)));
}

double SolidAngleDensity(double pdf_uv, double v) {
    const double sin_theta = std::sin(v * kPi);
    return sin_theta > 0.0 ? pdf_uv / (kTwoPiSquared * sin_theta) : 0.0;
}

}  // namespace

void DirectionToUv(DirectionD d, double rotation_degrees, double* u, double* v) {
    double turns = std::atan2(-d.x, d.z) / (2.0 * kPi) + 0.25 + rotation_degrees / 360.0;
    turns -= std::floor(turns);
    if (turns >= 1.0) turns = 0.0;
    *u = turns;
    *v = std::acos(std::clamp(d.y, -1.0, 1.0)) / kPi;
}

DirectionD UvToDirection(double u, double v, double rotation_degrees) {
    const double phi = (u - 0.25 - rotation_degrees / 360.0) * 2.0 * kPi;
    const double theta = v * kPi;
    const double sin_theta = std::sin(theta);
    // atan2(-x, z) = phi  =>  x = -sin(phi) sin(theta), z = cos(phi) sin(theta).
    return {-std::sin(phi) * sin_theta, std::cos(theta), std::cos(phi) * sin_theta};
}

std::optional<EnvironmentDistribution> EnvironmentDistribution::Build(
    uint32_t width, uint32_t height, const float* rgb, double rotation_degrees,
    std::string* error) {
    auto fail = [error](const char* message) -> std::optional<EnvironmentDistribution> {
        if (error != nullptr) *error = message;
        return std::nullopt;
    };
    if (width == 0 || height == 0 || rgb == nullptr) return fail("the environment map is empty");
    if (!std::isfinite(rotation_degrees)) return fail("the environment rotation is not finite");

    EnvironmentDistribution dist;
    dist.width_ = width;
    dist.height_ = height;
    dist.rotation_degrees_ = rotation_degrees;
    dist.marginal_cdf_.assign(size_t(height) + 1, 0.0);
    dist.conditional_cdf_.assign(size_t(height) * (size_t(width) + 1), 0.0);
    dist.density_.assign(size_t(height) * width, 0.0);

    std::vector<double> weight(size_t(height) * width, 0.0);
    double total = 0.0;
    for (uint32_t row = 0; row < height; ++row) {
        const double sin_theta = std::sin((double(row) + 0.5) / double(height) * kPi);
        double* cdf = &dist.conditional_cdf_[size_t(row) * (size_t(width) + 1)];
        double running = 0.0;
        for (uint32_t col = 0; col < width; ++col) {
            const float* texel = rgb + (size_t(row) * width + col) * 3;
            if (!std::isfinite(texel[0]) || !std::isfinite(texel[1]) || !std::isfinite(texel[2])) {
                return fail("the environment map has a non-finite texel");
            }
            const double luminance = kLuminanceR * double(texel[0]) +
                                     kLuminanceG * double(texel[1]) +
                                     kLuminanceB * double(texel[2]);
            const double w = std::max(luminance, 0.0) * sin_theta;
            weight[size_t(row) * width + col] = w;
            running += w;
            cdf[col + 1] = running;
        }
        // The row's last entry is its sum, so the normalised CDF ends at exactly 1.
        if (running > 0.0) {
            for (uint32_t col = 1; col <= width; ++col) cdf[col] /= running;
        }
        total += running;
        dist.marginal_cdf_[row + 1] = total;
    }
    if (!(total > 0.0) || !std::isfinite(total)) {
        return fail("the environment map has no finite positive luminance");
    }
    for (uint32_t row = 1; row <= height; ++row) dist.marginal_cdf_[row] /= total;
    const double cells = double(width) * double(height);
    for (size_t i = 0; i < weight.size(); ++i) dist.density_[i] = weight[i] / total * cells;
    return dist;
}

EnvironmentSample EnvironmentDistribution::Sample(double xi0, double xi1) const {
    EnvironmentSample s;
    s.row = FindInterval(marginal_cdf_.data(), height_, xi1);
    const double dv = Offset(xi1, marginal_cdf_[s.row], marginal_cdf_[s.row + 1]);
    const double* cdf = &conditional_cdf_[size_t(s.row) * (size_t(width_) + 1)];
    s.column = FindInterval(cdf, width_, xi0);
    const double du = Offset(xi0, cdf[s.column], cdf[s.column + 1]);
    s.u = (double(s.column) + du) / double(width_);
    s.v = (double(s.row) + dv) / double(height_);
    s.direction = UvToDirection(s.u, s.v, rotation_degrees_);
    s.pdf_uv = density_[size_t(s.row) * width_ + s.column];
    s.pdf_solid_angle = SolidAngleDensity(s.pdf_uv, s.v);
    return s;
}

double EnvironmentDistribution::PdfUv(double u, double v) const {
    return density_[size_t(Cell(v, height_)) * width_ + Cell(u, width_)];
}

double EnvironmentDistribution::Pdf(DirectionD d) const {
    double u;
    double v;
    DirectionToUv(d, rotation_degrees_, &u, &v);
    return SolidAngleDensity(PdfUv(u, v), v);
}

double EnvironmentDistribution::TexelProbability(uint32_t row, uint32_t column) const {
    return density_[size_t(row) * width_ + column] / (double(width_) * double(height_));
}

}  // namespace uzp::render::pathtracer
