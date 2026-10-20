#pragma once

// The CPU baker's mesh inputs (phase3.1_baker-request-model item 2.5, decision 311): bake meshes
// built from a texturing mesh (`src/mesh/`), and the custom cage read from a cage file.
//
// - A mesh file (the low mesh, a high mesh or a cage) is read by UzPainter's own loaders (OBJ,
//   FBX, glTF/GLB) as authored: no UV-tile check, no tangents, no unit conversion. Every mesh of a
//   bake is used in its own file units; the request's `scale_to_internal` converts distances.
// - A bake mesh has one vertex per triangle corner (nothing welded), in triangle order, with the
//   corner's position in the file's scene space (the object's transform applied), its authored
//   normal (transformed by the inverse transpose) and its first UV set.
// - Low parts: one per object of the texture set's material, in object order, named after the
//   object. High meshes: one per object, every triangle.
// - Cage parts: Adobe's page states only that an imported cage has the same number of vertices
//   as the base mesh. UzPainter's reading (pending-evidence): the cage file's vertex i is the low
//   file's vertex i, so a low corner's cage point is the cage file's position of the corner's
//   position index. Both files must have identity object transforms (which transform carries a
//   vertex shared between objects is not established).
// Parity with Painter is not claimed.

#include <string_view>
#include <vector>

#include "bake/bake_request.h"
#include "mesh/gltf_import.h"
#include "mesh/tangents.h"
#include "mesh/texturing_mesh.h"

namespace uzp::bake {

/// Reads `bytes`, the content of the mesh file `file_name` (the format by its extension), with a
/// glTF's external buffers read through `read`. Throws `mesh::ImportError`.
mesh::TexturingMesh ReadBakeMeshFile(std::string_view bytes, std::string_view file_name,
                                     const mesh::ExternalFileReader& read);

/// The low parts of the texture set of material index `material`. Throws `core::ValueError` when
/// no triangle uses it and `core::NotYetSupported` for an object transform that mirrors or is
/// singular. MikkTSpace runs on each complete object before the material split; each retained
/// triangle corner keeps that tangent. Normal baking currently requires identity transforms.
std::vector<BakeMesh> LowParts(const mesh::TexturingMesh& low, std::uint32_t material);

/// For a validated, complete native low object, compute missing per-corner MikkTSpace tangents.
/// Existing tangents from LowParts are retained, never recomputed after the material split.
void EnsureNormalTangents(BakeMesh& low);

/// Interpolate the retained low corners using the texturing mesh's frame operation.
mesh::Frame InterpolateBakeFrame(const BakeMesh& low, std::uint32_t triangle,
                                const std::array<float, 3>& weights, core::TangentSpace mode);

/// One high mesh per object of `high` with at least one triangle.
std::vector<BakeMesh> HighMeshes(const mesh::TexturingMesh& high);

/// The cage of every part `LowParts(low, material)` returns, from the cage file `cage`, in the
/// same order. Throws `core::ValueError` when the vertex counts differ and
/// `core::NotYetSupported` when either file has an object transform other than the identity.
std::vector<BakeMesh> CageParts(const mesh::TexturingMesh& cage, const mesh::TexturingMesh& low,
                                std::uint32_t material);

/// The axis-aligned bounding box of every triangle corner of `mesh` in scene space (the project
/// mesh's bounds, for relative distances). Throws `core::ValueError` for a mesh without triangles.
BoundingBox SceneBounds(const mesh::TexturingMesh& mesh);

}  // namespace uzp::bake
