#include "render/pathtracer/bsdf.h"

#include <cmath>

namespace uzp::render::pathtracer {
namespace {

constexpr float kInvPi = 0.31830988618379067154f;
constexpr float kPiOver4 = 0.78539816339744830962f;
constexpr float kPiOver2 = 1.57079632679489661923f;

bool SameHemisphere(Vec3 a, Vec3 b) { return a.z * b.z > 0.0f; }

}  // namespace

void SampleUniformDiskConcentric(float u0, float u1, float* x, float* y) {
    // P-PBRT SampleUniformDiskConcentric: map [0, 1)^2 to [-1, 1]^2, then each wedge between
    // the diagonals to a sector of the disk at radius max(|a|, |b|).
    const float a = 2.0f * u0 - 1.0f;
    const float b = 2.0f * u1 - 1.0f;
    if (a == 0.0f && b == 0.0f) {
        *x = 0.0f;
        *y = 0.0f;
        return;
    }
    float r;
    float theta;
    if (std::fabs(a) > std::fabs(b)) {
        r = a;
        theta = kPiOver4 * (b / a);
    } else {
        r = b;
        theta = kPiOver2 - kPiOver4 * (a / b);
    }
    *x = r * std::cos(theta);
    *y = r * std::sin(theta);
}

Vec3 SampleCosineHemisphere(float u0, float u1) {
    // P-PBRT SampleCosineHemisphere (Malley's method): a uniform disk point lifted to the
    // hemisphere has density cos(theta) / pi.
    float x;
    float y;
    SampleUniformDiskConcentric(u0, u1, &x, &y);
    const float z = std::sqrt(std::fmax(0.0f, 1.0f - x * x - y * y));
    return {x, y, z};
}

Rgb LambertBsdf::Evaluate(Vec3 wo, Vec3 wi) const {
    // P-PBRT §9.2 diffuse reflection: f = R / pi.
    if (!SameHemisphere(wo, wi)) return {};
    return {albedo_.r * kInvPi, albedo_.g * kInvPi, albedo_.b * kInvPi};
}

float LambertBsdf::Pdf(Vec3 wo, Vec3 wi) const {
    if (!SameHemisphere(wo, wi)) return 0.0f;
    return std::fabs(wi.z) * kInvPi;
}

bool LambertBsdf::Sample(Vec3 wo, float /*uc: one lobe*/, float u0, float u1,
                         BsdfSample* out) const {
    if (wo.z == 0.0f) return false;
    Vec3 wi = SampleCosineHemisphere(u0, u1);
    if (wo.z < 0.0f) wi.z = -wi.z;
    const float pdf = std::fabs(wi.z) * kInvPi;
    if (!(pdf > 0.0f)) return false;
    out->wi = wi;
    out->f = {albedo_.r * kInvPi, albedo_.g * kInvPi, albedo_.b * kInvPi};
    out->pdf = pdf;
    return true;
}

}  // namespace uzp::render::pathtracer
