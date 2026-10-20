#include "bake/bake_request.h"

#include <algorithm>
#include <bit>
#include <cmath>

#include "uzp_core/types/errors.h"

namespace uzp::bake {

using core::NotYetSupported;
using core::ValueError;

const char* UsageName(MeshMapUsage usage) {
    switch (usage) {
        case MeshMapUsage::Normal: return "Normal";
        case MeshMapUsage::WorldSpaceNormal: return "WorldSpaceNormal";
        case MeshMapUsage::ID: return "ID";
        case MeshMapUsage::AO: return "AO";
        case MeshMapUsage::Curvature: return "Curvature";
        case MeshMapUsage::Position: return "Position";
        case MeshMapUsage::Thickness: return "Thickness";
        case MeshMapUsage::Height: return "Height";
        case MeshMapUsage::BentNormals: return "BentNormals";
        case MeshMapUsage::Opacity: return "Opacity";
    }
    return "unknown";
}

std::string UsageOwnerTask(MeshMapUsage usage) {
    switch (usage) {
        case MeshMapUsage::Normal: return "phase3.2_baker-normal";
        case MeshMapUsage::WorldSpaceNormal: return "phase3.4_baker-world-space-normal";
        case MeshMapUsage::ID: return "phase3.4_baker-id";
        case MeshMapUsage::AO: return "phase3.4_baker-ao";
        case MeshMapUsage::Curvature: return "phase3.4_baker-curvature";
        case MeshMapUsage::Position: return "phase3.4_baker-position";
        case MeshMapUsage::Thickness: return "phase3.4_baker-thickness";
        case MeshMapUsage::Height: return "phase3.4_baker-height";
        case MeshMapUsage::BentNormals: return "phase3.4_baker-bent-normals";
        case MeshMapUsage::Opacity: return "phase3.4_baker-opacity";
    }
    return "phase3.5_embree-bakers";
}

DistanceRecord EffectiveDistances(const BakeRequest& request) {
    DistanceRecord d;
    const double scale = request.scale_to_internal;
    if (!(std::isfinite(scale) && scale > 0.0)) {
        throw ValueError(
            "the request needs the mesh's scale_to_internal (centimetres per mesh unit, finite and > 0; "
            "docs/architecture/12-mesh-import.md section 3)");
    }
    d.scale_to_internal = scale;
    d.detail_relative = request.detail.relative_to_bounding_box;
    d.ao_relative = request.ao.relative_to_bounding_box;
    if (d.detail_relative || d.ao_relative) {
        if (!request.project_bounds) {
            throw ValueError("a distance relative to the bounding box needs the project mesh's bounds");
        }
        const BoundingBox& box = *request.project_bounds;
        const double ex = static_cast<double>(box.upper.x) - box.lower.x;
        const double ey = static_cast<double>(box.upper.y) - box.lower.y;
        const double ez = static_cast<double>(box.upper.z) - box.lower.z;
        if (!(std::isfinite(ex) && std::isfinite(ey) && std::isfinite(ez)) || ex < 0.0 || ey < 0.0 || ez < 0.0) {
            throw ValueError("the project mesh's bounds need finite corners with lower <= upper");
        }
        if (!request.box_size_metric) {
            throw NotYetSupported(
                "the size of the bounding box a relative distance is measured against (its diagonal or its "
                "largest extent) is not established: a Painter recording settles it (decision 311; "
                "phase3.1_baker-request-model item 2.5)");
        }
        d.box_size_metric = *request.box_size_metric;
        d.box_size = d.box_size_metric == BoxSizeMetric::Diagonal ? std::sqrt(ex * ex + ey * ey + ez * ez)
                                                                  : std::max({ex, ey, ez});
        if (!(d.box_size > 0.0)) throw ValueError("the project mesh's bounding box has size 0");
    }
    const auto effective = [&](float value, bool relative, const char* name) {
        const double mesh_units = relative ? static_cast<double>(value) * d.box_size : static_cast<double>(value) / scale;
        const auto out = static_cast<float>(mesh_units);
        if (!std::isfinite(out)) throw ValueError(std::string(name) + " is out of range in mesh units");
        return out;
    };
    d.max_height = effective(request.detail.max_height, d.detail_relative, "max_height");
    d.max_depth = effective(request.detail.max_depth, d.detail_relative, "max_depth");
    d.ao_min_distance = effective(request.ao.min_distance, d.ao_relative, "min_distance");
    d.ao_max_distance = effective(request.ao.max_distance, d.ao_relative, "max_distance");
    return d;
}

namespace {

void PutLe(std::string& out, std::uint64_t value, int bytes) {
    for (int i = 0; i < bytes; ++i) out.push_back(static_cast<char>((value >> (8 * i)) & 0xFFu));
}

}  // namespace

std::string SerializeResult(const BakeResult& result) {
    std::string out = "UZPBAKE3";
    PutLe(out, result.width, 4);
    PutLe(out, result.height, 4);
    PutLe(out, result.tile_size, 4);
    PutLe(out, result.rays_per_texel, 4);
    PutLe(out, result.subsampling, 4);
    PutLe(out, result.dilation_width, 4);
    for (std::uint16_t v : result.ao) PutLe(out, v, 2);
    for (std::uint16_t v : result.ao_raw) PutLe(out, v, 2);
    for (std::uint8_t v : result.texel_class) PutLe(out, v, 1);
    for (std::uint8_t v : result.coverage) PutLe(out, v, 1);
    for (std::uint8_t v : result.subsample_hits) PutLe(out, v, 1);
    for (std::uint16_t v : result.back_face_rays) PutLe(out, v, 2);
    for (std::uint16_t v : result.self_hit_rays) PutLe(out, v, 2);
    const TexelClassCounts& t = result.texels;
    for (std::uint64_t v : {t.uncovered, t.straight_hit, t.back_face_hit, t.centre_miss, t.cage_hit, t.hidden}) {
        PutLe(out, v, 8);
    }
    const SubsampleCounts& s = result.subsamples;
    for (std::uint64_t v : {s.covered, s.hit, s.back_face_hit, s.centre_miss, s.hidden}) PutLe(out, v, 8);
    const RayClassCounts& r = result.rays;
    for (std::uint64_t v : {r.escaped, r.front_hit, r.back_face_hit, r.self_hit}) PutLe(out, v, 8);
    PutLe(out, result.dilated_texels, 8);
    const DistanceRecord& d = result.distances;
    PutLe(out, std::bit_cast<std::uint64_t>(d.scale_to_internal), 8);
    PutLe(out, d.detail_relative ? 1 : 0, 1);
    PutLe(out, d.ao_relative ? 1 : 0, 1);
    PutLe(out, static_cast<std::uint64_t>(d.box_size_metric), 1);
    PutLe(out, std::bit_cast<std::uint64_t>(d.box_size), 8);
    for (float v : {d.max_height, d.max_depth, d.ao_min_distance, d.ao_max_distance}) {
        PutLe(out, std::bit_cast<std::uint32_t>(v), 4);
    }
    return out;
}

}  // namespace uzp::bake
