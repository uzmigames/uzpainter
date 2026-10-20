#pragma once

// Per-corner tangent frames (`docs/architecture/12-mesh-import.md` §3, PRJ-04, decision 031).
//
// `ComputeTangents` runs Mikkelsen's reference MikkTSpace (`thirdparty/mikktspace/`,
// `genTangSpaceDefault`) once per object over the object's triangles in order, from each corner's
// position (in the object's own space, as its normal is), authored normal and `uv0`, and stores
// the result in the corner's tangent slot: xyz = the unit tangent, w = the bitangent sign (+1 or
// -1). The mesh is otherwise unchanged.
//
// A frame at a point of a triangle interpolates the corners' frames with the point's barycentric
// weights w_i (unnormalized): vT = sum w_i t_i, vN = sum w_i n_i, and
//   PerVertex    vB = sum w_i sign_i cross(n_i, t_i)       (the bitangent interpolated)
//   PerFragment  vB = sign cross(vN, vT), sign = the sign of sum w_i sign_i   (rebuilt per texel)
// `PerVertex` is used when the project does not set the mode (Painter 12.1.0's observed default),
// `PerFragment` when the caller sets it, as the Assets3D pipeline does (decision 031). A
// world-space normal is expressed in a frame by the exact inverse of the shading transform
// normalize(x vT + y vB + z vN) that `mikktspace.h` prescribes for normal-map samplers. The
// result is in the OpenGL convention of the Assets3D contract: +y (green) points along +v, the
// direction in which v grows (P0-NORMAL, `parity/semantics/tangent-frame.json`); the DirectX
// format is the green code inverted (65535 - g at 16 bits), applied where maps are encoded.
// With these rules the Phase 0 bakes equal Painter's to within 1 code at 16 bits
// (`parity/reports/phase0/normal-convention.md`).

#include <array>
#include <cmath>

#include "mesh/texturing_mesh.h"
#include "uzp_core/types/enums.h"

namespace uzp::mesh {

/// The tangent space of a project that does not set one (decision 031).
inline constexpr core::TangentSpace kDefaultTangentSpace = core::TangentSpace::PerVertex;

/// Float3 arithmetic in single precision, one IEEE operation per step in a fixed order, so a
/// frame is the same on every machine.
namespace v3 {
inline Float3 Add(const Float3& a, const Float3& b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
inline Float3 Sub(const Float3& a, const Float3& b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
inline Float3 Scale(const Float3& a, float s) { return {a.x * s, a.y * s, a.z * s}; }
inline float Dot(const Float3& a, const Float3& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
inline Float3 Cross(const Float3& a, const Float3& b) {
    return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}
inline Float3 Normalize(const Float3& a) { return Scale(a, 1.0f / std::sqrt(Dot(a, a))); }
}  // namespace v3

/// Fills every corner's tangent slot with its MikkTSpace frame (see above). Corners no triangle
/// uses keep a zero slot.
void ComputeTangents(TexturingMesh& mesh);

/// The corner's tangent xyz.
inline Float3 CornerTangent(const Corner& c) { return {c.tangent[0], c.tangent[1], c.tangent[2]}; }

/// The corner's bitangent, sign * cross(n, t).
inline Float3 CornerBitangent(const Corner& c) {
    return v3::Scale(v3::Cross(c.normal, CornerTangent(c)), c.tangent[3]);
}

/// A frame at a point of a triangle: unnormalized tangent, bitangent of the mode, and normal.
struct Frame {
    Float3 t;
    Float3 b;
    Float3 n;
};

/// The frame of `triangle` at barycentric `weights` (one per corner, in the triangle's order) in
/// `mode`; unset = `PerVertex`.
Frame InterpolateFrame(const TexturingMesh& mesh, const Triangle& triangle, const std::array<float, 3>& weights,
                       core::TangentSpace mode = kDefaultTangentSpace);

/// The same interpolation for three retained corners, without a temporary mesh allocation.
Frame InterpolateFrame(const std::array<Corner, 3>& corners, const std::array<float, 3>& weights,
                       core::TangentSpace mode = kDefaultTangentSpace);

/// `normal` (world space) in `frame`: the exact inverse of `FromTangentSpace`, normalized.
Float3 ToTangentSpace(const Frame& frame, const Float3& normal);

/// The shading transform of a tangent-space normal: normalize(x vT + y vB + z vN).
Float3 FromTangentSpace(const Frame& frame, const Float3& tangent_normal);

}  // namespace uzp::mesh
