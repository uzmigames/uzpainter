#pragma once

// glTF 2.0 / GLB import over fastgltf (`thirdparty/fastgltf/`, `docs/architecture/12-mesh-import.md`
// §2).
//
// - The default scene's node tree (scene 0 when none is the default; every root node when the
//   file has no scene) is walked depth first in order; each node with a mesh is one object, named
//   by the node (else its mesh, else `node<index>`), with its world transform. An instanced mesh
//   gives one object per node; its positions are added once.
// - Corners are the primitives' indices in order (non-indexed primitives: their vertices in
//   order); `positions[]` holds every primitive's `POSITION` values.
// - `NORMAL` is kept as stored; `TEXCOORD_0` is used with v flipped (glTF's v grows downwards:
//   v = 1 - v_gltf, recorded as `v_flip`); later `TEXCOORD_n` are recorded; stored `TANGENT`s are
//   counted but not used (tangents are regenerated, 12 §2).
// - Materials are ordered as the file lists them, named by their name or `material<index>`;
//   primitives without a material use the material `default`, ordered after the file's.
// - `TRIANGLES` primitives are imported; `POINTS` and `LINES*` are skipped and counted;
//   `TRIANGLE_STRIP` and `TRIANGLE_FAN` are refused (`parse_error`).
// - glTF's unit is the metre.

#include <filesystem>
#include <functional>
#include <string>
#include <string_view>
#include <vector>

#include "mesh/texturing_mesh.h"

namespace uzp::mesh {

/// A file a glTF reads beside it: an external buffer, under the URI the glTF writes.
struct ExternalFile {
    std::string uri;
    std::string bytes;
};

/// The bytes of the external buffer `uri` (as the glTF writes it; `path` is its decoded relative
/// path). Throws `ImportError` or `core::ValueError` when it cannot give them.
using ExternalFileReader = std::function<std::string(const std::string& uri, const std::filesystem::path& path)>;

/// Parses glTF JSON or GLB `bytes` into `mesh` (empty on entry). Every external buffer is read
/// through `read` and appended to `external`, in buffer order, so the caller can store it with the
/// mesh (SAV-01); images are never read (the texturing mesh does not use them). Throws
/// `ImportError` (`parse_error`) with fastgltf's description, for a buffer that is not a local
/// file, and for a file shorter than the buffer the glTF declares.
void ImportGltf(std::string_view bytes, const ExternalFileReader& read, TexturingMesh& mesh,
                std::vector<ExternalFile>& external);

}  // namespace uzp::mesh
