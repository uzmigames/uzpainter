#pragma once

// Shared assembly of a `TexturingMesh` by the raw loaders: objects, polygons (kept as triangles
// or fanned from their last corner, 12 §3), materials and the UV sets after the first in file
// order.

#include <cstdint>
#include <map>
#include <span>
#include <string>
#include <vector>

#include "mesh/texturing_mesh.h"

namespace uzp::mesh {

/// A face's corners in one UV set after the first: the set (`MeshBuilder::UvSet`) and one UV per
/// corner, in the face's corner order; `missing` of them are (0, 0) because the file gives none.
struct FaceUvs {
    std::uint32_t set = 0;
    std::vector<Float2> uvs;
    std::uint64_t missing = 0;
};

class MeshBuilder {
public:
    explicit MeshBuilder(TexturingMesh& mesh) : mesh_(mesh) {}

    /// Starts a new object; later polygons belong to it.
    void BeginObject(std::string name, const Matrix4& transform = kIdentity);

    /// The provisional id of the source material `key`: `file_order` places it among the
    /// materials (ascending), `name` is its name. Distinct keys are distinct materials, even with
    /// the same name (the duplicate-name rule is applied by `ImportMesh`).
    std::uint32_t Material(std::uint64_t key, std::uint64_t file_order, const std::string& name);

    /// The provisional id of the source UV set `key` (a UV set after the first): `file_order`
    /// places it among `mesh.uv_sets` (ascending), `name` is its name. A set first met after some
    /// corners gives them (0, 0), counted in its `corners_without_uv`.
    std::uint32_t UvSet(std::uint64_t key, std::uint64_t file_order, const std::string& name);

    /// Appends one face of the current object: its corners in file order, each carrying a
    /// provisional material id from `Material`, and `uvs`, the face's UVs in the sets that carry
    /// it (a set it does not carry gives its corners (0, 0), counted in `corners_without_uv`).
    /// Three corners are kept as one triangle; n > 3 corners become the fan from the last corner,
    /// (c[i], c[i+1], c[n-1]) for i = 0 .. n-3, Painter's split
    /// (parity/semantics/polygon-triangulation.json), and count in `flags.ngons_triangulated`.
    /// Throws `std::invalid_argument` for fewer than three corners, without a current object, or
    /// for a set of `uvs` given twice or with another count than the corners.
    void AddPolygon(std::span<const Corner> corners, std::span<const FaceUvs> uvs = {});

    /// Drops objects without triangles, keeps only the materials some corner uses, orders them by
    /// file order, gives them their final indices and remaps every corner; orders the UV sets by
    /// file order.
    void Finish();

private:
    struct Source {
        std::uint64_t file_order = 0;
        std::string name;
    };

    TexturingMesh& mesh_;
    std::map<std::uint64_t, std::uint32_t> ids_;  // source key -> provisional id
    std::vector<Source> sources_;                // by provisional id
    std::map<std::uint64_t, std::uint32_t> uv_ids_;  // source UV set key -> provisional id
    std::vector<std::uint64_t> uv_orders_;           // file order, by provisional id
    bool has_object_ = false;
};

}  // namespace uzp::mesh
