#pragma once

// Shared assembly of a `TexturingMesh` by the raw loaders: objects, polygons (kept as triangles
// or fanned from their last corner, 12 §3) and materials in file order.

#include <cstdint>
#include <map>
#include <span>
#include <string>

#include "mesh/texturing_mesh.h"

namespace uzp::mesh {

class MeshBuilder {
public:
    explicit MeshBuilder(TexturingMesh& mesh) : mesh_(mesh) {}

    /// Starts a new object; later polygons belong to it.
    void BeginObject(std::string name, const Matrix4& transform = kIdentity);

    /// The provisional id of the source material `key`: `file_order` places it among the
    /// materials (ascending), `name` is its name. Distinct keys are distinct materials, even with
    /// the same name (the duplicate-name rule is applied by `ImportMesh`).
    std::uint32_t Material(std::uint64_t key, std::uint64_t file_order, const std::string& name);

    /// Appends one face of the current object: its corners in file order, each carrying a
    /// provisional material id from `Material`. Three corners are kept as one triangle; n > 3
    /// corners become the fan from the last corner, (c[i], c[i+1], c[n-1]) for i = 0 .. n-3,
    /// Painter's split (parity/semantics/polygon-triangulation.json), and count in
    /// `flags.ngons_triangulated`. Throws
    /// `std::invalid_argument` for fewer than three corners or without a current object.
    void AddPolygon(std::span<const Corner> corners);

    /// Drops objects without triangles, keeps only the materials some corner uses, orders them by
    /// file order, gives them their final indices and remaps every corner.
    void Finish();

private:
    struct Source {
        std::uint64_t file_order = 0;
        std::string name;
    };

    TexturingMesh& mesh_;
    std::map<std::uint64_t, std::uint32_t> ids_;  // source key -> provisional id
    std::vector<Source> sources_;                // by provisional id
    bool has_object_ = false;
};

}  // namespace uzp::mesh
