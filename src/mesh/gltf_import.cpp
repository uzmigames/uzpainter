#include "mesh/gltf_import.h"

#include <cstddef>
#include <cstring>
#include <map>
#include <string>
#include <utility>
#include <vector>

#include "fastgltf/core.hpp"
#include "fastgltf/tools.hpp"
#include "mesh/import_error.h"
#include "mesh/mesh_builder.h"

namespace uzp::mesh {

namespace {

constexpr std::uint64_t kDefaultMaterialKey = ~std::uint64_t{0};

[[noreturn]] void Fail(const std::string& message) {
    throw ImportError(ImportErrorKind::parse_error, "glTF: " + message);
}

[[noreturn]] void Fail(fastgltf::Error error) {
    Fail(std::string(fastgltf::getErrorMessage(error)));
}

Matrix4 Multiply(const Matrix4& a, const Matrix4& b) {
    Matrix4 r{};
    for (int c = 0; c < 4; ++c) {
        for (int row = 0; row < 4; ++row) {
            double sum = 0.0;
            for (int k = 0; k < 4; ++k) sum += a[k * 4 + row] * b[c * 4 + k];
            r[c * 4 + row] = sum;
        }
    }
    return r;
}

/// The node's local matrix (column-major): its `matrix`, or T * R * S.
Matrix4 LocalMatrix(const fastgltf::Node& node) {
    if (const auto* m = std::get_if<fastgltf::math::fmat4x4>(&node.transform)) {
        Matrix4 r{};
        for (std::size_t c = 0; c < 4; ++c) {
            for (std::size_t row = 0; row < 4; ++row) r[c * 4 + row] = (*m).col(c)[row];
        }
        return r;
    }
    const auto& trs = std::get<fastgltf::TRS>(node.transform);
    const double x = trs.rotation[0], y = trs.rotation[1], z = trs.rotation[2], w = trs.rotation[3];
    const double sx = trs.scale[0], sy = trs.scale[1], sz = trs.scale[2];
    return {(1 - 2 * (y * y + z * z)) * sx, (2 * (x * y + z * w)) * sx,     (2 * (x * z - y * w)) * sx,     0.0,
            (2 * (x * y - z * w)) * sy,     (1 - 2 * (x * x + z * z)) * sy, (2 * (y * z + x * w)) * sy,     0.0,
            (2 * (x * z + y * w)) * sz,     (2 * (y * z - x * w)) * sz,     (1 - 2 * (x * x + y * y)) * sz, 0.0,
            trs.translation[0],             trs.translation[1],             trs.translation[2],             1.0};
}

class Importer {
public:
    Importer(const fastgltf::Asset& asset, TexturingMesh& mesh) : asset_(asset), mesh_(mesh), builder_(mesh) {}

    void Run() {
        std::vector<std::size_t> roots;
        if (!asset_.scenes.empty()) {
            const std::size_t scene = asset_.defaultScene ? *asset_.defaultScene : 0;
            for (std::size_t n : asset_.scenes.at(scene).nodeIndices) roots.push_back(n);
        } else {
            std::vector<bool> child(asset_.nodes.size(), false);
            for (const fastgltf::Node& node : asset_.nodes) {
                for (std::size_t c : node.children) child.at(c) = true;
            }
            for (std::size_t n = 0; n < asset_.nodes.size(); ++n) {
                if (!child[n]) roots.push_back(n);
            }
        }
        for (std::size_t root : roots) Visit(root, kIdentity, 0);
        builder_.Finish();
        mesh_.units = Units{"meter", 1.0, 100.0, "file"};
        mesh_.flags.v_flip = true;
        mesh_.flags.uv_set = uv_set_;
        for (const auto& [index, name] : ignored_uv_sets_) mesh_.flags.ignored_uv_sets.push_back(name);
    }

private:
    void Visit(std::size_t index, const Matrix4& parent, int depth) {
        if (depth > static_cast<int>(asset_.nodes.size())) Fail("the node hierarchy has a cycle");
        const fastgltf::Node& node = asset_.nodes.at(index);
        const Matrix4 world = Multiply(parent, LocalMatrix(node));
        if (node.meshIndex) AddMesh(index, *node.meshIndex, world);
        for (std::size_t c : node.children) Visit(c, world, depth + 1);
    }

    std::string ObjectName(std::size_t node_index, std::size_t mesh_index) const {
        const fastgltf::Node& node = asset_.nodes[node_index];
        if (!node.name.empty()) return std::string(node.name);
        const fastgltf::Mesh& m = asset_.meshes.at(mesh_index);
        if (!m.name.empty()) return std::string(m.name);
        return "node" + std::to_string(node_index);
    }

    std::uint32_t MaterialOf(const fastgltf::Primitive& primitive) {
        if (!primitive.materialIndex) return builder_.Material(kDefaultMaterialKey, kDefaultMaterialKey, "default");
        const std::size_t i = *primitive.materialIndex;
        const fastgltf::Material& material = asset_.materials.at(i);
        const std::string name = material.name.empty() ? "material" + std::to_string(i) : std::string(material.name);
        return builder_.Material(i, i, name);
    }

    const fastgltf::Accessor& Accessor(const fastgltf::Primitive& p, std::string_view name) const {
        return asset_.accessors.at(p.findAttribute(name)->accessorIndex);
    }

    bool Has(const fastgltf::Primitive& p, std::string_view name) const {
        return p.findAttribute(name) != p.attributes.cend();
    }

    void AddMesh(std::size_t node_index, std::size_t mesh_index, const Matrix4& world) {
        const fastgltf::Mesh& gmesh = asset_.meshes.at(mesh_index);
        builder_.BeginObject(ObjectName(node_index, mesh_index), world);
        for (std::size_t p = 0; p < gmesh.primitives.size(); ++p) {
            const fastgltf::Primitive& primitive = gmesh.primitives[p];
            switch (primitive.type) {
                case fastgltf::PrimitiveType::Triangles: break;
                case fastgltf::PrimitiveType::TriangleStrip:
                case fastgltf::PrimitiveType::TriangleFan:
                    Fail("mesh " + std::to_string(mesh_index) + " primitive " + std::to_string(p) +
                         ": triangle strips and fans are not imported");
                default: ++mesh_.flags.skipped_non_surface_elements; continue;
            }
            if (!Has(primitive, "POSITION")) Fail("a triangle primitive without POSITION");
            const fastgltf::Accessor& positions = Accessor(primitive, "POSITION");
            const auto [offset_it, first_use] =
                offsets_.try_emplace({mesh_index, p}, static_cast<std::uint32_t>(mesh_.positions.size()));
            if (first_use) {
                fastgltf::iterateAccessor<fastgltf::math::fvec3>(asset_, positions, [&](fastgltf::math::fvec3 v) {
                    mesh_.positions.push_back(Float3{v[0], v[1], v[2]});
                });
            }
            const std::uint32_t offset = offset_it->second;
            std::vector<Float3> normals;
            if (Has(primitive, "NORMAL")) {
                fastgltf::iterateAccessor<fastgltf::math::fvec3>(asset_, Accessor(primitive, "NORMAL"),
                                                                 [&](fastgltf::math::fvec3 v) {
                                                                     normals.push_back(Float3{v[0], v[1], v[2]});
                                                                 });
            }
            std::vector<Float2> uvs;
            if (Has(primitive, "TEXCOORD_0")) {
                uv_set_ = "TEXCOORD_0";
                fastgltf::iterateAccessor<fastgltf::math::fvec2>(asset_, Accessor(primitive, "TEXCOORD_0"),
                                                                 [&](fastgltf::math::fvec2 v) {
                                                                     uvs.push_back(Float2{v[0], 1.0f - v[1]});
                                                                 });
            }
            for (const fastgltf::Attribute& attribute : primitive.attributes) {
                const std::string_view name = attribute.name;
                if (name.starts_with("TEXCOORD_") && name != "TEXCOORD_0") {
                    ignored_uv_sets_.emplace(std::stoi(std::string(name.substr(9))), std::string(name));
                }
            }
            const bool tangents = Has(primitive, "TANGENT");
            std::vector<std::uint32_t> indices;
            if (primitive.indicesAccessor) {
                fastgltf::iterateAccessor<std::uint32_t>(asset_, asset_.accessors.at(*primitive.indicesAccessor),
                                                         [&](std::uint32_t i) { indices.push_back(i); });
            } else {
                for (std::uint32_t i = 0; i < positions.count; ++i) indices.push_back(i);
            }
            if (indices.size() % 3 != 0) {
                Fail("mesh " + std::to_string(mesh_index) + " primitive " + std::to_string(p) + " has " +
                     std::to_string(indices.size()) + " indices, not a multiple of 3");
            }
            const std::uint32_t material = MaterialOf(primitive);
            std::vector<Corner> corners(3);
            for (std::size_t t = 0; t < indices.size(); t += 3) {
                for (std::size_t k = 0; k < 3; ++k) {
                    const std::uint32_t v = indices[t + k];
                    if (v >= positions.count) Fail("an index beyond its POSITION accessor");
                    Corner& c = corners[k];
                    c = Corner{};
                    c.position = offset + v;
                    c.material = material;
                    if (v < normals.size()) {
                        c.normal = normals[v];
                    } else {
                        ++mesh_.flags.corners_without_normal;
                    }
                    if (v < uvs.size()) {
                        c.uv0 = uvs[v];
                    } else {
                        ++mesh_.flags.corners_without_uv;
                    }
                    if (tangents) ++mesh_.flags.stored_tangents;
                }
                builder_.AddPolygon(corners);
            }
        }
    }

    const fastgltf::Asset& asset_;
    TexturingMesh& mesh_;
    MeshBuilder builder_;
    std::map<std::pair<std::size_t, std::size_t>, std::uint32_t> offsets_;
    std::map<int, std::string> ignored_uv_sets_;
    std::string uv_set_;
};

}  // namespace

void ImportGltf(std::string_view bytes, const ExternalFileReader& read, TexturingMesh& mesh,
                std::vector<ExternalFile>& external) {
    auto data = fastgltf::GltfDataBuffer::FromBytes(reinterpret_cast<const std::byte*>(bytes.data()), bytes.size());
    if (data.error() != fastgltf::Error::None) Fail(data.error());
    fastgltf::Parser parser(fastgltf::Extensions::KHR_mesh_quantization);
    // External buffers stay URIs: they are read here, through `read`, so the caller sees (and
    // stores) every byte the mesh is derived from.
    auto asset = parser.loadGltf(data.get(), std::filesystem::path(), fastgltf::Options::None);
    if (asset.error() != fastgltf::Error::None) Fail(asset.error());
    for (fastgltf::Buffer& buffer : asset.get().buffers) {
        const auto* source = std::get_if<fastgltf::sources::URI>(&buffer.data);
        if (source == nullptr) continue;
        const std::string uri(source->uri.string());
        if (!source->uri.isLocalPath()) Fail("the buffer '" + uri + "' is not a local file");
        std::string file = read(uri, source->uri.fspath());
        if (file.size() < buffer.byteLength) {
            Fail("the buffer '" + uri + "' holds " + std::to_string(file.size()) + " bytes; the file declares " +
                 std::to_string(buffer.byteLength));
        }
        fastgltf::sources::Vector loaded;
        loaded.bytes.resize(file.size());
        if (!file.empty()) std::memcpy(loaded.bytes.data(), file.data(), file.size());
        loaded.mimeType = source->mimeType;
        external.push_back({uri, std::move(file)});
        buffer.data = std::move(loaded);
    }
    Importer(asset.get(), mesh).Run();
}

}  // namespace uzp::mesh
