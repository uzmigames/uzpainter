#pragma once

// The BSDF interface of the `painter_iray` path tracer and its Lambert lobe, the
// transport-verification BSDF (rulebook task phase3.4_path-tracer-transport item 2.8;
// docs/architecture/07-preview-and-render-parity.md §3.2, §3.3). The layered material model of
// phase3.5_path-tracer-materials implements the same interface. CPU reference: the transport
// kernel's HLSL mirror is written and checked against it with item 2.7.
//
// Sources (docs/approved-sources.md): P-PBRT, *Physically Based Rendering* 4th ed.: the BxDF
// interface (f, Sample_f, PDF) in the local shading frame, the diffuse BxDF of §9.2
// (f = R / pi in the hemisphere of wo), cosine-weighted hemisphere sampling by Malley's method
// over the concentric disk mapping (`SampleUniformDiskConcentric`, `SampleCosineHemisphere`,
// density cos(theta) / pi). P-KAJIYA: the reflected radiance integral the estimator f cos / pdf
// samples.
//
// Directions are unit vectors in the local shading frame, the normal along +z, both pointing
// away from the surface. Arithmetic is binary32 (the transport is RGB fp32) with contraction
// off (build.zig `pathtracer_flags`).

#include <cstdint>

namespace uzp::render::pathtracer {

struct Vec3 {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};

struct Rgb {
    float r = 0.0f;
    float g = 0.0f;
    float b = 0.0f;
};

/// One sampled incident direction: `f` the BSDF value toward it (without the cosine) and `pdf`
/// its solid-angle density.
struct BsdfSample {
    Vec3 wi;
    Rgb f;
    float pdf = 0.0f;
};

class Bsdf {
public:
    virtual ~Bsdf() = default;

    /// f(wo, wi), without the cosine factor.
    virtual Rgb Evaluate(Vec3 wo, Vec3 wi) const = 0;

    /// Solid-angle density with which `Sample` returns `wi` for `wo`.
    virtual float Pdf(Vec3 wo, Vec3 wi) const = 0;

    /// Samples wi for `wo` from three uniform numbers in [0, 1): `uc` selects a lobe (layered
    /// models), (u0, u1) the direction inside it. Returns false, leaving `out` unchanged, when
    /// no direction carries energy.
    virtual bool Sample(Vec3 wo, float uc, float u0, float u1, BsdfSample* out) const = 0;
};

/// Lambertian reflection of albedo R: f = R / pi when wo and wi lie in the same hemisphere of
/// the normal, 0 otherwise; sampled cosine-weighted into the hemisphere of wo, so
/// f cos(theta_i) / pdf = R for every sample.
class LambertBsdf final : public Bsdf {
public:
    explicit LambertBsdf(Rgb albedo) : albedo_(albedo) {}

    Rgb Evaluate(Vec3 wo, Vec3 wi) const override;
    float Pdf(Vec3 wo, Vec3 wi) const override;
    bool Sample(Vec3 wo, float uc, float u0, float u1, BsdfSample* out) const override;

private:
    Rgb albedo_;
};

/// Uniform point of the unit disk for (u0, u1) in [0, 1)^2, Shirley and Chiu's area-preserving
/// concentric mapping (P-PBRT `SampleUniformDiskConcentric`).
void SampleUniformDiskConcentric(float u0, float u1, float* x, float* y);

/// Cosine-weighted direction of the +z hemisphere (Malley's method, P-PBRT
/// `SampleCosineHemisphere`); its density is z / pi.
Vec3 SampleCosineHemisphere(float u0, float u1);

}  // namespace uzp::render::pathtracer
