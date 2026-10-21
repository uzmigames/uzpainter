#pragma once

// The texturing mesh (`docs/architecture/12-mesh-import.md` §1, §3): what UzPainter's own raw
// loaders (`obj_parser.h`, `fbx_import.h`, `gltf_import.h`) produce from a mesh file, corner by
// corner, without re-triangulating, welding, re-normalling or repacking anything.
//
// - `positions[]` are the file's vertex positions in file order and file units, in the space the
//   file authors them (an OBJ's coordinates; an FBX or glTF mesh's own space). Nothing is welded:
//   an unused position stays, a duplicated one stays duplicated.
// - `corners[]` are triangle corners as authored: one per face corner of the file (an OBJ `f`
//   reference, an FBX polygon vertex, a glTF index), in file order, each with its position id,
//   its authored normal (never recomputed), its first UV set and its material. The tangent slot is
//   filled by the tangent stage (`tangents.h`, run by `ImportMesh`), never by a loader.
// - `objects[]` are the file's objects (OBJ `o`/`g` sections, FBX and glTF mesh nodes; one per
//   instance), each with its transform to the file's scene space and its triangles. A triangle of
//   an already-triangulated face keeps the face's corners in their order; a polygon of n > 3
//   corners becomes the fan (c[i], c[i+1], c[n-1]), i = 0..n-3, from its last corner, and is
//   counted in `ngons_triangulated` (the documented rule, 12 §3: Painter's split, Tier 0
//   `parity/semantics/polygon-triangulation.json`).
// - `materials[]` are the materials faces use, in file order: one texture set each (PRJ-02).
//   Material identity (name + index) is separate from object identity.
// - `uv_sets[]` are the file's UV sets after the first (FBX layers after the first, glTF
//   `TEXCOORD_n` for n >= 1; an OBJ has one), one UV per corner each, beside `uv0` and never used
//   for texturing; a mesh with one UV set has none.
// - UVs follow the OpenGL/OBJ convention: v grows upwards, the 0-1 square is UDIM tile 1001.
//
// The content hashes are SHA-256 (lower-case hex) of little-endian byte streams defined in
// `ComputeHashes`; a reload compares them (PRJ-08).

#include <array>
#include <cstdint>
#include <string>
#include <vector>

#include "uzp_core/manifest/json.h"

namespace uzp::mesh {

struct Float2 {
    float u = 0.0f;
    float v = 0.0f;
    bool operator==(const Float2&) const = default;
};

struct Float3 {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
    bool operator==(const Float3&) const = default;
};

/// A column-major 4x4 matrix (element [c * 4 + r] is row r of column c), as glTF stores it.
using Matrix4 = std::array<double, 16>;
inline constexpr Matrix4 kIdentity = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};

struct Corner {
    std::uint32_t position = 0;  ///< index into `TexturingMesh::positions`
    Float3 normal;               ///< as authored; (0, 0, 0) when the file has none (flagged)
    Float2 uv0;                  ///< the first UV set; (0, 0) when the file has none (flagged)
    /// MikkTSpace tangent xyz and bitangent sign (`ComputeTangents`); zero until it runs.
    std::array<float, 4> tangent{};
    std::uint32_t material = 0;  ///< index into `TexturingMesh::materials`
    bool operator==(const Corner&) const = default;
};

struct Triangle {
    std::array<std::uint32_t, 3> corners{};
    bool operator==(const Triangle&) const = default;
};

struct Object {
    std::string name;
    Matrix4 transform = kIdentity;  ///< object space -> the file's scene space (file units)
    std::vector<Triangle> triangles;
    bool operator==(const Object&) const = default;
};

/// Material identity: the name the file gives and the index in file order (the texture set
/// order).
struct Material {
    std::string name;
    std::uint32_t index = 0;
    bool operator==(const Material&) const = default;
};

/// `units {source, scale_to_internal}` (12 §3, PRJ-07). Painter's unit is the centimetre:
/// `scale_to_internal` is centimetres per file unit, the effective scale every receipt carries.
struct Units {
    std::string source;                ///< e.g. "centimeter", "meter", "unspecified"
    double source_meters_per_unit = 0; ///< 0 when the format states no unit (OBJ)
    double scale_to_internal = 1.0;    ///< centimetres per file unit, effective
    /// "file" when `scale_to_internal` follows the file unit (`mesh_unit_scale` 0/None),
    /// "mesh_unit_scale" when the caller's scale was used.
    std::string from = "file";
    bool operator==(const Units&) const = default;
};

/// A UV set after the first: its name and one UV per corner (`uvs[i]` belongs to `corners[i]`),
/// in tile-indexed UV space like `uv0`; (0, 0) for a corner whose face does not carry the set.
struct UvSet {
    std::string name;
    std::vector<Float2> uvs;
    std::uint64_t corners_without_uv = 0;  ///< corners left (0, 0)
    bool operator==(const UvSet&) const = default;
};

struct Hashes {
    std::string positions;
    std::string uvs;
    std::string corner_normals;
    std::string triangulation;
    std::string materials;
    std::string secondary_uvs;  ///< of `uv_sets`; empty for a mesh with one UV set
    bool operator==(const Hashes&) const = default;
};

/// What the import noticed without changing anything (the certificate's input; 12 §4).
struct ImportFlags {
    std::uint64_t ngons_triangulated = 0;          ///< polygons of more than 3 corners (fanned)
    std::uint64_t corners_without_normal = 0;      ///< corner normal left (0, 0, 0)
    std::uint64_t corners_without_uv = 0;          ///< corner uv0 left (0, 0)
    std::uint64_t skipped_non_surface_elements = 0; ///< points and lines (no surface to paint)
    std::string uv_set;                            ///< the UV set used, by name ("" if unnamed)
    bool v_flip = false;                           ///< true when the format's v was flipped
    std::uint64_t stored_tangents = 0;             ///< corners with a file tangent (recorded only)
    core::json::Object format_details;             ///< format-specific records (axes, mtllib, ...)
    bool operator==(const ImportFlags&) const = default;
};

struct TexturingMesh {
    std::vector<Object> objects;
    std::vector<Corner> corners;
    std::vector<Float3> positions;
    std::vector<Material> materials;
    std::vector<UvSet> uv_sets;  ///< the UV sets after the first, in file order
    Units units;
    Hashes hashes;
    ImportFlags flags;

    std::size_t TriangleCount() const;
};

/// The hashes of `mesh`, each the SHA-256 of a little-endian byte stream:
/// - positions: every position as 3 x float32, then every object's transform as 16 x float64;
/// - uvs: every corner's uv0 as 2 x float32;
/// - corner_normals: every corner's normal as 3 x float32;
/// - triangulation: per object, its triangle count as uint32 and its triangles' corner ids as
///   3 x uint32; then every corner's position id as uint32;
/// - materials: per material, its index as uint32, its UTF-8 name and a 0 byte; then every
///   corner's material id as uint32;
/// - secondary_uvs, only when `uv_sets` is not empty (else ""): per set, its UTF-8 name and a 0
///   byte, then every corner's UV in it as 2 x float32.
Hashes ComputeHashes(const TexturingMesh& mesh);

/// `{corner_normals, materials, positions, triangulation, uvs}`, and `secondary_uvs` when the
/// mesh has more than one UV set.
core::json::Object HashesToJson(const Hashes& hashes);

/// The tile of the UV square cell (`fu`, `fv`) (the floor of u and v): its UDIM number when it
/// has one (1001 + fu + 10 fv for fu in 0-9, fv in 0-99), else "u<fu>_v<fv>".
core::json::Value TileOf(double fu, double fv);

}  // namespace uzp::mesh
