#include "mesh/fbx_import.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "mesh/import_error.h"
#include "mesh/mesh_builder.h"
#include "ufbx.h"

namespace uzp::mesh {

namespace {

constexpr std::uint64_t kDefaultMaterialKey = ~std::uint64_t{0};

std::string Text(const ufbx_string& s) { return std::string(s.data, s.length); }

Matrix4 ToMatrix4(const ufbx_matrix& m) {
    return {m.m00, m.m10, m.m20, 0.0, m.m01, m.m11, m.m21, 0.0, m.m02, m.m12, m.m22, 0.0, m.m03, m.m13, m.m23, 1.0};
}

std::string AxisName(ufbx_coordinate_axis axis) {
    switch (axis) {
        case UFBX_COORDINATE_AXIS_POSITIVE_X: return "+x";
        case UFBX_COORDINATE_AXIS_NEGATIVE_X: return "-x";
        case UFBX_COORDINATE_AXIS_POSITIVE_Y: return "+y";
        case UFBX_COORDINATE_AXIS_NEGATIVE_Y: return "-y";
        case UFBX_COORDINATE_AXIS_POSITIVE_Z: return "+z";
        case UFBX_COORDINATE_AXIS_NEGATIVE_Z: return "-z";
        default: return "unknown";
    }
}

/// The name of a common length unit of `meters` per unit, else "custom".
std::string UnitName(double meters) {
    static const std::pair<double, const char*> kUnits[] = {
        {0.001, "millimeter"}, {0.01, "centimeter"}, {0.1, "decimeter"}, {1.0, "meter"},
        {1000.0, "kilometer"}, {0.0254, "inch"},     {0.3048, "foot"},   {0.9144, "yard"},
    };
    for (const auto& [value, name] : kUnits) {
        if (std::fabs(meters - value) <= 1e-9 * value) return name;
    }
    return "custom";
}

Float3 ToFloat3(const ufbx_vec3& v) {
    return Float3{static_cast<float>(v.x), static_cast<float>(v.y), static_cast<float>(v.z)};
}

}  // namespace

void ImportFbx(std::string_view bytes, TexturingMesh& mesh) {
    ufbx_load_opts opts{};  // no unit, axis or handedness conversion; no generated normals
    ufbx_error error{};
    std::unique_ptr<ufbx_scene, decltype(&ufbx_free_scene)> scene(
        ufbx_load_memory(bytes.data(), bytes.size(), &opts, &error), &ufbx_free_scene);
    if (!scene) {
        char text[1024];
        ufbx_format_error(text, sizeof(text), &error);
        throw ImportError(ImportErrorKind::parse_error, std::string("FBX: ") + text);
    }

    MeshBuilder builder(mesh);
    std::map<const ufbx_mesh*, std::uint32_t> position_offsets;
    std::vector<std::string> ignored_uv_sets;
    std::string uv_set;
    std::vector<Corner> corners;
    for (const ufbx_node* node : scene->nodes) {
        const ufbx_mesh* fbx = node->mesh;
        if (fbx == nullptr) continue;
        const auto [offset_it, first_use] =
            position_offsets.try_emplace(fbx, static_cast<std::uint32_t>(mesh.positions.size()));
        if (first_use) {
            for (const ufbx_vec3& p : fbx->vertices) mesh.positions.push_back(ToFloat3(p));
            for (std::size_t s = 1; s < fbx->uv_sets.count; ++s) {
                const std::string name = Text(fbx->uv_sets.data[s].name);
                if (std::find(ignored_uv_sets.begin(), ignored_uv_sets.end(), name) == ignored_uv_sets.end()) {
                    ignored_uv_sets.push_back(name);
                }
            }
            if (fbx->uv_sets.count > 0 && uv_set.empty()) uv_set = Text(fbx->uv_sets.data[0].name);
        }
        const std::uint32_t offset = offset_it->second;
        builder.BeginObject(Text(node->name), ToMatrix4(node->geometry_to_world));
        for (std::size_t f = 0; f < fbx->faces.count; ++f) {
            const ufbx_face face = fbx->faces.data[f];
            if (face.num_indices < 3) {
                ++mesh.flags.skipped_non_surface_elements;
                continue;
            }
            const ufbx_material* material = nullptr;
            if (fbx->face_material.count > f) {
                const std::uint32_t slot = fbx->face_material.data[f];
                if (slot < node->materials.count) {
                    material = node->materials.data[slot];
                } else if (slot < fbx->materials.count) {
                    material = fbx->materials.data[slot];
                }
            }
            std::uint32_t material_id = 0;
            if (material == nullptr) {
                material_id = builder.Material(kDefaultMaterialKey, kDefaultMaterialKey, "default");
            } else {
                std::string name = Text(material->name);
                if (name.empty()) name = "material" + std::to_string(material->typed_id);
                material_id = builder.Material(material->element_id, material->typed_id, name);
            }
            corners.clear();
            for (std::uint32_t k = 0; k < face.num_indices; ++k) {
                const std::uint32_t index = face.index_begin + k;
                Corner corner;
                corner.position = offset + fbx->vertex_indices.data[index];
                corner.material = material_id;
                if (fbx->vertex_normal.exists) {
                    corner.normal = ToFloat3(fbx->vertex_normal.values.data[fbx->vertex_normal.indices.data[index]]);
                } else {
                    ++mesh.flags.corners_without_normal;
                }
                if (fbx->vertex_uv.exists) {
                    const ufbx_vec2 uv = fbx->vertex_uv.values.data[fbx->vertex_uv.indices.data[index]];
                    corner.uv0 = Float2{static_cast<float>(uv.x), static_cast<float>(uv.y)};
                } else {
                    ++mesh.flags.corners_without_uv;
                }
                if (fbx->vertex_tangent.exists) ++mesh.flags.stored_tangents;
                corners.push_back(corner);
            }
            builder.AddPolygon(corners);
        }
    }
    builder.Finish();

    const double meters = scene->settings.unit_meters;
    mesh.units = Units{UnitName(meters), meters, meters * 100.0, "file"};
    mesh.flags.uv_set = uv_set;
    mesh.flags.ignored_uv_sets = std::move(ignored_uv_sets);
    mesh.flags.v_flip = false;  // FBX stores v growing upwards, as UzPainter does
    const ufbx_coordinate_axes& axes = scene->settings.axes;
    mesh.flags.format_details = core::json::Object{
        {"axes", core::json::Object{{"front", AxisName(axes.front)},
                                    {"right", AxisName(axes.right)},
                                    {"up", AxisName(axes.up)}}},
        {"fbx_version", static_cast<std::int64_t>(scene->metadata.version)},
        {"ascii", scene->metadata.ascii},
    };
}

}  // namespace uzp::mesh
