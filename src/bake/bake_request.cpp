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

double BoundingBoxSize(const BakeRequest& request) {
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
            "largest extent) is not established: a Painter recording settles it (decision 311; owner "
            "phase3.5_embree-bakers, decision 323)");
    }
    const double size = *request.box_size_metric == BoxSizeMetric::Diagonal ? std::sqrt(ex * ex + ey * ey + ez * ez)
                                                                           : std::max({ex, ey, ez});
    if (!(size > 0.0)) throw ValueError("the project mesh's bounding box has size 0");
    return size;
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
    const bool has_ao = std::find(request.usages.begin(), request.usages.end(), MeshMapUsage::AO) != request.usages.end();
    d.ao_relative = has_ao && request.ao.relative_to_bounding_box;
    if (d.detail_relative || d.ao_relative) {
        d.box_size = BoundingBoxSize(request);
        d.box_size_metric = *request.box_size_metric;
    }
    const auto effective = [&](float value, bool relative, const char* name) {
        const double mesh_units = relative ? static_cast<double>(value) * d.box_size : static_cast<double>(value) / scale;
        const auto out = static_cast<float>(mesh_units);
        if (!std::isfinite(out)) throw ValueError(std::string(name) + " is out of range in mesh units");
        return out;
    };
    d.max_height = effective(request.detail.max_height, d.detail_relative, "max_height");
    d.max_depth = effective(request.detail.max_depth, d.detail_relative, "max_depth");
    if (has_ao) {
        d.ao_min_distance = effective(request.ao.min_distance, d.ao_relative, "min_distance");
        d.ao_max_distance = effective(request.ao.max_distance, d.ao_relative, "max_distance");
    }
    return d;
}

namespace {

void PutLe(std::string& out, std::uint64_t value, int bytes) {
    for (int i = 0; i < bytes; ++i) out.push_back(static_cast<char>((value >> (8 * i)) & 0xFFu));
}

}  // namespace

std::string SerializeResult(const BakeResult& result) {
    const bool has_normal = !result.normal_raw.empty();
    std::string out = has_normal ? "UZPBAKE4" : "UZPBAKE3";
    if (has_normal) {
        PutLe(out, (!result.ao_raw.empty() ? 1u : 0u) | 2u, 1);
        PutLe(out, result.tangent_space == core::TangentSpace::PerVertex ? 0u : 1u, 1);
        PutLe(out, result.normal_format == core::NormalMapFormat::OpenGL ? 0u : 1u, 1);
        PutLe(out, result.normal_raw.size(), 8);
        for (std::uint16_t v : result.normal_raw) PutLe(out, v, 2);
        PutLe(out, result.normal.size(), 8);
        for (std::uint16_t v : result.normal) PutLe(out, v, 2);
    }
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
    if (!result.world_normal.empty()) {
        out += "WSN1";
        PutLe(out, result.world_normal.size(), 8);
        for (float v : result.world_normal) PutLe(out, std::bit_cast<std::uint32_t>(v), 4);
    }
    if (!result.position.empty()) {
        const PositionNormalizationRecord& p = result.position_normalization;
        out += "POS1";
        PutLe(out, static_cast<std::uint64_t>(p.settings.mode), 1);
        PutLe(out, static_cast<std::uint64_t>(p.settings.axis), 1);
        PutLe(out, static_cast<std::uint64_t>(p.settings.normalization), 1);
        PutLe(out, static_cast<std::uint64_t>(p.settings.scale), 1);
        PutLe(out, p.bounds_applied ? 1 : 0, 1);
        PutLe(out, p.channels, 4);
        PutLe(out, std::bit_cast<std::uint64_t>(p.scale_to_internal), 8);
        PutLe(out, result.position.size(), 8);
        for (float v : result.position) PutLe(out, std::bit_cast<std::uint32_t>(v), 4);
    }
    if (!result.id_labels.empty()) {
        out += "IDM1";
        PutLe(out, result.id_labels.size(), 8);
        for (std::uint16_t v : result.id_labels) PutLe(out, v, 2);
        PutLe(out, result.id_label_meshes.size(), 8);
        for (const std::string& name : result.id_label_meshes) {
            PutLe(out, name.size(), 8);
            out += name;
        }
    }
    if (!result.opacity.empty()) {
        out += "OPA1";
        PutLe(out, result.opacity.size(), 8);
        for (float v : result.opacity) PutLe(out, std::bit_cast<std::uint32_t>(v), 4);
    }
    if (!result.height_map.empty()) {
        const HeightNormalizationRecord& h = result.height_normalization;
        out += "HGT1";
        PutLe(out, h.settings.normalization ? 1u + static_cast<std::uint64_t>(*h.settings.normalization) : 0u, 1);
        PutLe(out, std::bit_cast<std::uint32_t>(h.settings.divisor), 4);
        PutLe(out, h.normalization_applied ? 1 : 0, 1);
        PutLe(out, h.divisor_applied ? 1 : 0, 1);
        PutLe(out, std::bit_cast<std::uint64_t>(h.scale_to_internal), 8);
        PutLe(out, result.height_map.size(), 8);
        for (float v : result.height_map) PutLe(out, std::bit_cast<std::uint32_t>(v), 4);
    }
    if (!result.thickness_ray_class.empty()) {
        const ThicknessRecord& t = result.thickness;
        out += "THK1";
        PutLe(out, t.settings.secondary_rays, 4);
        PutLe(out, t.settings.distribution == Distribution::Cosine ? 1 : 0, 1);
        PutLe(out, t.settings.relative_to_bounding_box ? 1 : 0, 1);
        PutLe(out, t.settings.normalization ? 1u + static_cast<std::uint64_t>(*t.settings.normalization) : 0u, 1);
        for (float v : {t.settings.min_distance, t.settings.max_distance, t.min_distance, t.max_distance}) {
            PutLe(out, std::bit_cast<std::uint32_t>(v), 4);
        }
        PutLe(out, std::bit_cast<std::uint64_t>(t.box_size), 8);
        PutLe(out, std::bit_cast<std::uint64_t>(t.scale_to_internal), 8);
        for (std::uint64_t v : {t.rays.escaped, t.rays.front_hit, t.rays.back_face_hit, t.rays.self_hit}) {
            PutLe(out, v, 8);
        }
        PutLe(out, result.thickness_ray_class.size(), 8);
        for (std::uint8_t v : result.thickness_ray_class) PutLe(out, v, 1);
        for (float v : result.thickness_ray_distance) PutLe(out, std::bit_cast<std::uint32_t>(v), 4);
    }
    return out;
}

}  // namespace uzp::bake
