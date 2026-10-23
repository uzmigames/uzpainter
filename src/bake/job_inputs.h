#pragma once

// The inputs of a bake job read from a project (phase3.3_baker-evidence-publication items 2.6 and
// 2.7; decision 355): one `SetBake` per texture set, built from the revision the job reads.
//
// - The low parts are the project mesh re-derived from its stored bytes (`mesh::RederiveMesh`),
//   split by the texture set's material (`LowParts`); its unit scale and scene bounds are the
//   request's `scale_to_internal` and `project_bounds`.
// - The high meshes are the files the common `HipolyMesh` parameter names (`file:///` URLs joined
//   by `|`, as `bake_set_mesh_inputs` stores them), unless `LowAsHigh`; the custom cage is the file
//   `CageMesh` names, with `CageMode` "Custom file"; "Automatic (experimental)" is refused
//   (`NotYetSupported`, decision 323). A glTF's external buffers are read beside it.
// - Every other setting is `RequestFromParameters`'s; the Normal convention is the project's.
// - The usages are the caller's, or the texture set's enabled bakers (Painter's documented "current
//   baking configuration"). A usage whose map no binding can hold yet is refused here, before any
//   work (`PublishedFormat`, naming its owner task). No call stores a texture set's baking state yet
//   (decision 323), so every texture set is enabled, as a fresh one is.
// Parity with Painter is not claimed.

#include <cstdint>
#include <set>
#include <string>
#include <vector>

#include "bake/job.h"
#include "mesh/reload.h"
#include "uzp_core/types/project.h"

namespace uzp::bake {

struct PreparedBakes {
    std::vector<SetBake> sets;
    /// SHA-256 of every file the bakes read: project/high/cage meshes and their external buffers.
    std::set<std::string> input_resources;
};

/// The bakes of `texture_sets` (every texture set, in project order, when empty) of `project` at
/// `revision`. Raises `uzp::core::ValueError` (an unknown texture set, a missing mesh or file),
/// `uzp::core::NotYetSupported` (an unbindable usage, a parameter without an established value)
/// and the mesh readers' errors.
PreparedBakes PrepareBakes(const core::Project& project, std::int64_t revision, const mesh::ResourceReader& read,
                           const std::vector<std::string>& texture_sets, const std::vector<MeshMapUsage>& usages);

/// The usage named `name` (Painter's `MeshMapUsage` member name); `ValueError` otherwise.
MeshMapUsage UsageNamed(const std::string& name);

}  // namespace uzp::bake
