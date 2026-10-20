#include "bake/thickness_baker.h"

#include <cmath>
#include <cstdint>
#include <string>

#include "uzp_core/types/errors.h"

namespace uzp::bake {

namespace {

/// The evidence bound: texels x rays, 64 Mi slots (1024 x 1024 texels at 64 rays).
constexpr std::uint64_t kMaxEvidenceRays = std::uint64_t{1} << 26;

const char* NormalizationLabel(ThicknessNormalization normalization) {
    switch (normalization) {
        case ThicknessNormalization::RelativeToRayDistances: return "Relative to ray distances";
        case ThicknessNormalization::RelativeToMinMax: return "Relative to min/max (per UV tile)";
        case ThicknessNormalization::None: return "None";
    }
    return "unknown";
}

struct Distances {
    double box_size = 0.0;
    float min = 0.0f;
    float max = 0.0f;
};

/// The effective mesh-unit distances: centimetres over the unit scale, or fractions of the box size
/// (decision 311's rule, with `BoundingBoxSize`).
Distances Effective(const BakeRequest& request) {
    const ThicknessSettings& t = request.thickness;
    Distances d;
    if (t.relative_to_bounding_box) d.box_size = BoundingBoxSize(request);
    const auto effective = [&](float value, const char* name) {
        const double mesh_units = t.relative_to_bounding_box ? static_cast<double>(value) * d.box_size
                                                             : static_cast<double>(value) / request.scale_to_internal;
        const auto out = static_cast<float>(mesh_units);
        if (!std::isfinite(out)) throw core::ValueError(std::string("Thickness ") + name + " is out of range in mesh units");
        return out;
    };
    d.min = effective(t.min_distance, "min_distance");
    d.max = effective(t.max_distance, "max_distance");
    if (!(d.min < d.max)) throw core::ValueError("Thickness distances need min_distance < max_distance in mesh units");
    return d;
}

}  // namespace

void ValidateThickness(const BakeRequest& request) {
    const std::string owner = UsageOwnerTask(MeshMapUsage::Thickness) + ", decision 341";
    const ThicknessSettings& t = request.thickness;
    if (t.normalization) {
        const ThicknessNormalization normalization = *t.normalization;
        if (normalization != ThicknessNormalization::RelativeToRayDistances &&
            normalization != ThicknessNormalization::RelativeToMinMax && normalization != ThicknessNormalization::None) {
            throw core::ValueError("invalid Thickness MaximizeRange");
        }
        throw core::NotYetSupported(std::string("Thickness MaximizeRange '") + NormalizationLabel(normalization) +
                                    "': a texel's thickness (how its rays' distances combine, what an escaped ray "
                                    "counts, which hits count) is not recorded, so neither is its normalisation; a "
                                    "Thickness golden settles it (" + owner + ")");
    }
    if (t.distribution != Distribution::Cosine && t.distribution != Distribution::Uniform) {
        throw core::ValueError("invalid Thickness Distribution");
    }
    if (t.secondary_rays == 0 || t.secondary_rays > 65535) {
        throw core::ValueError("Thickness secondary_rays must be in [1, 65535]");
    }
    if (!(std::isfinite(t.min_distance) && std::isfinite(t.max_distance) && t.min_distance >= 0.0f &&
          t.min_distance < t.max_distance)) {
        throw core::ValueError("Thickness distances need 0 <= min_distance < max_distance, finite");
    }
    if (request.detail.subsampling != 1) {
        throw core::NotYetSupported("Thickness SubSampling > 1 has no established resolve rule (" + owner + ")");
    }
    if (request.common.dilation_width != 0) {
        throw core::NotYetSupported("Thickness DilationWidth > 0 has no established padding rule (" + owner + ")");
    }
    // Sizes above the baker's maximum and an invalid unit scale are refused by the request's own checks.
    if (request.output_size_log2[0] < 32 && request.output_size_log2[1] < 32) {
        const std::uint64_t texels = (std::uint64_t{1} << request.output_size_log2[0]) << request.output_size_log2[1];
        if (texels > kMaxEvidenceRays / t.secondary_rays) {
            throw core::NotYetSupported("the per-ray Thickness evidence holds at most 2^26 rays (texels x NbSecondary); "
                                        "a full-size map waits on the recorded thickness value (" + owner + ")");
        }
    }
    if (std::isfinite(request.scale_to_internal) && request.scale_to_internal > 0.0) Effective(request);
}

void PrepareThickness(const BakeRequest& request, BakeResult& result) {
    ThicknessRecord& record = result.thickness;
    const Distances d = Effective(request);
    record.settings = request.thickness;
    record.scale_to_internal = request.scale_to_internal;
    record.box_size = d.box_size;
    record.min_distance = d.min;
    record.max_distance = d.max;
    const std::size_t slots = static_cast<std::size_t>(result.width) * result.height * record.settings.secondary_rays;
    result.thickness_ray_class.assign(slots, static_cast<std::uint8_t>(ThicknessRayClass::NotCast));
    result.thickness_ray_distance.assign(slots, 0.0f);
}

void CastThickness(BakeResult& result, std::size_t texel, const Vec3d& point, const Vec3d& normal,
                   const SecondaryCaster& cast) {
    const ThicknessRecord& record = result.thickness;
    const std::uint32_t rays = record.settings.secondary_rays;
    const Vec3d inward{-normal.x, -normal.y, -normal.z};
    for (std::uint32_t s = 0; s < rays; ++s) {
        const Vec3d direction = HemisphereDirection(record.settings.distribution, TexelSample(texel, s, rays), inward);
        const SecondaryHit hit = cast(point, direction, record.min_distance, record.max_distance);
        const std::size_t slot = texel * rays + s;
        result.thickness_ray_class[slot] = static_cast<std::uint8_t>(hit.cls);
        result.thickness_ray_distance[slot] =
            hit.cls == ThicknessRayClass::Escaped ? 0.0f : static_cast<float>(static_cast<double>(hit.t) * record.scale_to_internal);
    }
}

void CountThickness(BakeResult& result) {
    RayClassCounts& counts = result.thickness.rays;
    counts = {};
    for (std::uint8_t cls : result.thickness_ray_class) {
        switch (static_cast<ThicknessRayClass>(cls)) {
            case ThicknessRayClass::NotCast: break;
            case ThicknessRayClass::Escaped: ++counts.escaped; break;
            case ThicknessRayClass::FrontHit: ++counts.front_hit; break;
            case ThicknessRayClass::BackFaceHit: ++counts.back_face_hit; break;
            case ThicknessRayClass::SelfHit: ++counts.self_hit; break;
        }
    }
}

core::json::Object ThicknessRecordJson(const ThicknessRecord& record) {
    const ThicknessSettings& s = record.settings;
    return core::json::Object{
        {"usage", std::string("Thickness")},
        {"MaximizeRange", s.normalization ? core::json::Value(std::string(NormalizationLabel(*s.normalization)))
                                          : core::json::Value{}},
        {"NbSecondary", static_cast<std::int64_t>(s.secondary_rays)},
        {"Distribution", std::string(s.distribution == Distribution::Cosine ? "Cosine" : "Uniform")},
        {"MaxDistanceRelativeScale", s.relative_to_bounding_box},
        {"MinDistance", static_cast<double>(s.min_distance)},
        {"MaxDistance", static_cast<double>(s.max_distance)},
        {"effective_min_distance", static_cast<double>(record.min_distance)},
        {"effective_max_distance", static_cast<double>(record.max_distance)},
        {"box_size", record.box_size},
        {"scale_to_internal", record.scale_to_internal},
        {"unit", std::string("centimetre")},
        {"value", core::json::Value{}},
        {"range", core::json::Value{}},
        {"decision", std::string("341")},
    };
}

}  // namespace uzp::bake
