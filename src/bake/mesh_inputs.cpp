#include "bake/mesh_inputs.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <string>

#include "mesh/fbx_import.h"
#include "mesh/mesh_import.h"
#include "mesh/obj_parser.h"
#include "uzp_core/types/errors.h"

namespace uzp::bake {

using core::NotYetSupported;
using core::ValueError;

mesh::TexturingMesh ReadBakeMeshFile(std::string_view bytes, std::string_view file_name,
                                     const mesh::ExternalFileReader& read) {
    mesh::TexturingMesh out;
    std::vector<mesh::ExternalFile> external;
    switch (mesh::FormatOf(file_name)) {
        case mesh::MeshFormat::obj: mesh::ParseObj(bytes, out); break;
        case mesh::MeshFormat::fbx: mesh::ImportFbx(bytes, out); break;
        case mesh::MeshFormat::gltf:
        case mesh::MeshFormat::glb: mesh::ImportGltf(bytes, read, out, external); break;
    }
    return out;
}

namespace {

bool IsIdentity(const mesh::Matrix4& m) { return m == mesh::kIdentity; }

/// An object's transform to scene space and its normal matrix (the inverse transpose of its 3 x 3
/// part, as the cofactor matrix over the determinant).
struct ObjectFrame {
    const mesh::Matrix4* m = nullptr;
    std::array<double, 9> normal{};  // row-major

    explicit ObjectFrame(const mesh::Object& object) : m(&object.transform) {
        const mesh::Matrix4& t = object.transform;
        // a[r][c] = t[c * 4 + r]
        const auto a = [&t](int r, int c) { return t[c * 4 + r]; };
        const double c00 = a(1, 1) * a(2, 2) - a(1, 2) * a(2, 1);
        const double c01 = a(1, 2) * a(2, 0) - a(1, 0) * a(2, 2);
        const double c02 = a(1, 0) * a(2, 1) - a(1, 1) * a(2, 0);
        const double det = a(0, 0) * c00 + a(0, 1) * c01 + a(0, 2) * c02;
        if (!(std::isfinite(det) && det > 0.0)) {
            throw NotYetSupported("object '" + object.name +
                                  "': a transform that mirrors or is singular (which side is the front "
                                  "is not established; decision 311)");
        }
        const double c10 = a(0, 2) * a(2, 1) - a(0, 1) * a(2, 2);
        const double c11 = a(0, 0) * a(2, 2) - a(0, 2) * a(2, 0);
        const double c12 = a(0, 1) * a(2, 0) - a(0, 0) * a(2, 1);
        const double c20 = a(0, 1) * a(1, 2) - a(0, 2) * a(1, 1);
        const double c21 = a(0, 2) * a(1, 0) - a(0, 0) * a(1, 2);
        const double c22 = a(0, 0) * a(1, 1) - a(0, 1) * a(1, 0);
        normal = {c00 / det, c01 / det, c02 / det, c10 / det, c11 / det, c12 / det, c20 / det, c21 / det, c22 / det};
    }

    Float3 Point(const mesh::Float3& p) const {
        if (IsIdentity(*m)) return {p.x, p.y, p.z};
        const mesh::Matrix4& t = *m;
        const double x = p.x, y = p.y, z = p.z;
        return {static_cast<float>(t[0] * x + t[4] * y + t[8] * z + t[12]),
                static_cast<float>(t[1] * x + t[5] * y + t[9] * z + t[13]),
                static_cast<float>(t[2] * x + t[6] * y + t[10] * z + t[14])};
    }

    Float3 Normal(const mesh::Float3& n) const {
        if (IsIdentity(*m)) return {n.x, n.y, n.z};
        const double x = n.x, y = n.y, z = n.z;
        return {static_cast<float>(normal[0] * x + normal[1] * y + normal[2] * z),
                static_cast<float>(normal[3] * x + normal[4] * y + normal[5] * z),
                static_cast<float>(normal[6] * x + normal[7] * y + normal[8] * z)};
    }
};

std::uint32_t MaterialOf(const mesh::TexturingMesh& source, const mesh::Triangle& triangle) {
    return source.corners[triangle.corners[0]].material;
}

/// The bake mesh of `object`'s triangles that `keep` accepts, one vertex per corner; empty when
/// none is kept.
template <typename Keep>
BakeMesh PartOf(const mesh::TexturingMesh& source, const mesh::Object& object, Keep keep) {
    BakeMesh part;
    part.name = object.name;
    const ObjectFrame frame(object);
    for (const mesh::Triangle& triangle : object.triangles) {
        if (!keep(triangle)) continue;
        for (std::uint32_t corner_id : triangle.corners) {
            const mesh::Corner& corner = source.corners[corner_id];
            part.indices.push_back(static_cast<std::uint32_t>(part.positions.size()));
            part.positions.push_back(frame.Point(source.positions[corner.position]));
            part.normals.push_back(frame.Normal(corner.normal));
            part.uvs.push_back({corner.uv0.u, corner.uv0.v});
        }
    }
    return part;
}

}  // namespace

std::vector<BakeMesh> LowParts(const mesh::TexturingMesh& low, std::uint32_t material) {
    std::vector<BakeMesh> parts;
    for (const mesh::Object& object : low.objects) {
        BakeMesh part = PartOf(low, object, [&](const mesh::Triangle& t) { return MaterialOf(low, t) == material; });
        if (!part.indices.empty()) parts.push_back(std::move(part));
    }
    if (parts.empty()) throw ValueError("no triangle of the mesh uses material " + std::to_string(material));
    return parts;
}

std::vector<BakeMesh> HighMeshes(const mesh::TexturingMesh& high) {
    std::vector<BakeMesh> meshes;
    for (const mesh::Object& object : high.objects) {
        BakeMesh mesh = PartOf(high, object, [](const mesh::Triangle&) { return true; });
        if (!mesh.indices.empty()) meshes.push_back(std::move(mesh));
    }
    return meshes;
}

std::vector<BakeMesh> CageParts(const mesh::TexturingMesh& cage, const mesh::TexturingMesh& low,
                                std::uint32_t material) {
    if (cage.positions.size() != low.positions.size()) {
        throw ValueError("the cage file has " + std::to_string(cage.positions.size()) +
                         " vertices and the mesh " + std::to_string(low.positions.size()) +
                         ": a cage needs the same number of vertices");
    }
    for (const mesh::TexturingMesh* source : {&cage, &low}) {
        for (const mesh::Object& object : source->objects) {
            if (!IsIdentity(object.transform)) {
                throw NotYetSupported("cage file: object '" + object.name +
                                      "' has a transform; which transform carries a cage vertex is not "
                                      "established (decision 311)");
            }
        }
    }
    std::vector<BakeMesh> parts = LowParts(low, material);
    std::size_t next = 0;
    for (const mesh::Object& object : low.objects) {
        bool any = false;
        BakeMesh* part = next < parts.size() ? &parts[next] : nullptr;
        std::size_t vertex = 0;
        for (const mesh::Triangle& triangle : object.triangles) {
            if (MaterialOf(low, triangle) != material) continue;
            any = true;
            for (std::uint32_t corner_id : triangle.corners) {
                const mesh::Float3 p = cage.positions[low.corners[corner_id].position];
                part->positions[vertex++] = {p.x, p.y, p.z};
            }
        }
        if (!any) continue;
        part->name += " (cage)";
        ++next;
    }
    return parts;
}

BoundingBox SceneBounds(const mesh::TexturingMesh& source) {
    bool any = false;
    BoundingBox box;
    for (const mesh::Object& object : source.objects) {
        const ObjectFrame frame(object);
        for (const mesh::Triangle& triangle : object.triangles) {
            for (std::uint32_t corner_id : triangle.corners) {
                const Float3 p = frame.Point(source.positions[source.corners[corner_id].position]);
                if (!any) {
                    box.lower = box.upper = p;
                    any = true;
                    continue;
                }
                box.lower = {std::min(box.lower.x, p.x), std::min(box.lower.y, p.y), std::min(box.lower.z, p.z)};
                box.upper = {std::max(box.upper.x, p.x), std::max(box.upper.y, p.y), std::max(box.upper.z, p.z)};
            }
        }
    }
    if (!any) throw ValueError("the mesh has no triangle: it has no bounding box");
    return box;
}

}  // namespace uzp::bake
