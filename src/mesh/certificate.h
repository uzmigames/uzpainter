#pragma once

// The mesh certificate (`docs/architecture/12-mesh-import.md` §4, PRJ-09, PRJ-10): what is wrong
// with a texturing mesh, measured and never repaired. `Certify` reads the mesh (const) and its
// computed tangent frames (`tangents.h`); nothing in the mesh is changed, welded, re-normalled,
// re-triangulated or repacked.
//
// Corner counters (each corner of the mesh once):
// - `non_finite_normals`: a normal component is NaN or infinite;
// - `zero_normals`, `zero_tangents`, `zero_bitangents`: the authored normal, the MikkTSpace
//   tangent or the bitangent sign * cross(n, t) is shorter than `kZeroLength`;
// - `degenerate_tbn`: the frame cannot be inverted: one of N, T, B is non-finite or zero, or the
//   normalized vectors span a volume |T . (B x N)| below `kMinTbnVolume`;
// - `flipped_handedness`: the bitangent sign is -1 (mirrored UVs).
// Face counters (each triangle once):
// - `coincident_opposite`: triangles that overlap another triangle with positive area in the same
//   plane, facing the opposite way (scene space: object transforms applied), whatever their
//   vertices or triangulation (the hat lesson: a double-sided shell bakes from the wrong side);
// - `zero_area_uv`: |UV area| at most `kZeroUvArea` (UV units squared; the 0-1 square is 1);
// - `flipped_uv`: a negative UV area, i.e. clockwise in UV space (v up) for the face's winding;
// - `ngons_triangulated`: polygons fanned at import (`flags.ngons_triangulated`).
// `uv.outside_0_1` counts triangles with a corner outside the closed 0-1 square (tile 1001).
//
// Per-set UV metrics (one set per material, keyed by its name), measured on the
// `width` x `height` texel grid of tile 1001 (texel centres at ((col + 1/2) / W, (row + 1/2) / H)),
// on the CPU:
// - `overlap_px`: texels whose centre more than one triangle of the set covers. Each triangle
//   covers the centres strictly inside it and those on its top or left edges (the top-left rule,
//   evaluated in counter-clockwise order with each edge in one canonical direction), so two
//   triangles sharing an edge never both cover a centre on it;
// - `islands`: connected components of triangles sharing an edge in UV and in scene space (both
//   ends with equal UVs and equal positions, so stacked copies of an island stay separate);
// - `density_px_per_cm`: per triangle sqrt(UV area in px / surface area in cm^2), surface in
//   scene space times `units.scale_to_internal`; min, max and the area-weighted median p50 (the
//   smallest density whose triangles, with every lower one, cover at least half the surface);
//   triangles of zero UV or surface area are left out; null when none is left;
// - `anisotropy_max`: the largest ratio of the singular values of a triangle's map from surface
//   (cm) to UV (px); null when no triangle is measured;
// - `gap_px`: the shortest distance in px between boundary edges (edges one triangle of the
//   island uses) of two different islands; 0 when they touch or cross, null with one island;
// - `border_px`: the shortest distance in px from a boundary edge end to the tile's border,
//   negative outside it; null for an empty set.
//
// `status`: `fail` when any of non_finite_normals, zero_normals, zero_tangents, zero_bitangents,
// degenerate_tbn, coincident_opposite, outside_0_1 is non-zero (frames that cannot shade or
// bake, faces baked from the wrong side, UVs outside the Default workflow's tile); else `warn` when
// any of flipped_handedness, zero_area_uv, flipped_uv, ngons_triangulated or a set's overlap_px is
// non-zero (legitimate layouts such as mirrored or stacked islands, flagged for the pipeline);
// else `pass`. Gap, border, density and anisotropy are measured, not judged.

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <string_view>

#include "mesh/texturing_mesh.h"
#include "uzp_core/manifest/json.h"

namespace uzp::mesh {

inline constexpr float kZeroLength = 1e-6f;
inline constexpr double kMinTbnVolume = 1e-3;
inline constexpr double kZeroUvArea = 1e-12;

enum class CertificateStatus { pass, warn, fail };

std::string_view StatusName(CertificateStatus status);

struct CertificateOptions {
    /// The texel grid of the pixel metrics: the texture sets' resolution.
    int width = 1024;
    int height = 1024;
};

struct DensityStats {
    double min = 0.0;
    double p50 = 0.0;
    double max = 0.0;
    bool operator==(const DensityStats&) const = default;
};

struct UvSetMetrics {
    std::uint64_t overlap_px = 0;
    std::uint64_t islands = 0;
    std::optional<DensityStats> density_px_per_cm;
    std::optional<double> anisotropy_max;
    std::optional<double> gap_px;
    std::optional<double> border_px;
    bool operator==(const UvSetMetrics&) const = default;
};

struct CornerCounts {
    std::uint64_t non_finite_normals = 0;
    std::uint64_t zero_normals = 0;
    std::uint64_t zero_tangents = 0;
    std::uint64_t zero_bitangents = 0;
    std::uint64_t degenerate_tbn = 0;
    std::uint64_t flipped_handedness = 0;
    bool operator==(const CornerCounts&) const = default;
};

struct FaceCounts {
    std::uint64_t coincident_opposite = 0;
    std::uint64_t zero_area_uv = 0;
    std::uint64_t flipped_uv = 0;
    std::uint64_t ngons_triangulated = 0;
    bool operator==(const FaceCounts&) const = default;
};

struct Certificate {
    CornerCounts corners;
    FaceCounts faces;
    std::uint64_t outside_0_1 = 0;
    std::map<std::string, UvSetMetrics> per_set;  ///< by material name, in name order
    CertificateOptions grid;
    CertificateStatus status = CertificateStatus::pass;
};

/// Certifies `mesh` (whose tangents `ComputeTangents` filled) on the texel grid of `options`.
Certificate Certify(const TexturingMesh& mesh, const CertificateOptions& options = {});

/// The §4 JSON: `{corners, faces, uv {outside_0_1, resolution, per_set}, mesh {objects,
/// triangles, materials, units}, hashes, status}`.
core::json::Object CertificateToJson(const Certificate& certificate, const TexturingMesh& mesh);

}  // namespace uzp::mesh
