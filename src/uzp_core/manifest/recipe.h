#pragma once

// The recipe dump (`docs/architecture/03-project-model.md` §5, §7; task
// phase2.1_recipe-dump-manifest-blocks, decision 122; SAV-03, SAV-04, INT-20, ARC-11): the part of a
// project revision that determines its output, with a deterministic digest, and the rebuild of a
// project from it. Key reference in `src/uzp_core/MANIFEST.md` §8; JSON Schema
// `src/uzp_core/schema/recipe.schema.json`.
//
// A dump splits the revision's id-less document (its manifest without ids, `next_id`, the version
// bookkeeping and the keys this version does not know) in two:
//
// - `recipe`, the body: the output-determining state, everything evaluation, export or mesh
//   derivation reads. The digest is the SHA-256 of its canonical JSON (`json::WriteCanonical`).
//   - A reference source's `anchor` and an instance layer's `instance_source` are JSON pointers
//     into the node's texture set (`/stacks/0/root_layers/2/content_effects/1`), so ids never
//     reach it.
//   - A paint node's planes are their content, `{chunk_root}` of the bound plane version (null
//     when none is bound), instead of plane ids.
//   - Each stack channel carries `base`, the float32 backdrop the evaluator reads from the
//     project's template (the effective default the manifest does not store), and `settings`
//     always names `template`.
//   - `resources` lists the hashes the body references (mesh, the files the mesh reads beside
//     it, mesh maps, source and procedural image bindings), each `{mime, size}`.
// - `rebuild`, outside the digest: `{<pointer into the document>: value}` for the state only a
//   rebuild needs (`RebuildOnly` in recipe.cpp): `display`, `export_defaults`, `metadata`,
//   `painter_reference`, `resource_catalog` (every stored resource entry without its id),
//   `mesh.source`, the settings `default_resolution`, `mesh_unit_scale`, `import_cameras` and
//   `auto_unwrap`, a texture set's `description` and `bake_settings`, a mesh map's
//   `invalid_report` and provenance other than `kind` and `declared_convention`, a channel's
//   `label`, a node's `collapsed` and `preset_ref`.
//
// The ARC-11 header wraps both, outside the digest: the revision moves on inert commits, and the
// app version and compatibility profile do not change the output.

#include <array>
#include <cstdint>
#include <functional>
#include <set>
#include <string>
#include <string_view>

#include "uzp_core/manifest/json.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/project.h"

namespace uzp::core {

/// The dump's `schema` key.
inline constexpr std::string_view kRecipeSchema = "uzpainter/recipe/1";

/// The float32 backdrop of channel `type` stored as `format` in a stack of a project created from
/// `template_id` (the template's entry, else the channel default, which can depend on the format:
/// decision 126, and on `colour`, the colour management of that project, null when the recipe
/// names none). Throws when the host does not know it.
using BaseValueFn = std::function<std::array<float, 3>(std::string_view template_id, ChannelType type,
                                                       ChannelFormat format, const ColorManagement* colour)>;

/// What the running application supplies: its version (ARC-11) and its template base values.
struct RecipeHost {
    std::string app_version;
    BaseValueFn base_value;
};

/// The recipe body of `project` (see above). Throws `ValueError` for a reference whose target is
/// not a node of the same texture set, and what `base_value` throws.
json::Object RecipeBody(const Project& project, const BaseValueFn& base_value);

/// SHA-256 of the canonical JSON of `body`.
std::string RecipeDigest(const json::Object& body);

/// The SHA-256 of the mesh file and of every file it reads beside it (its import report's
/// `kMeshExternalFiles`), empty without a mesh: what the texturing mesh is derived from. Throws
/// `ManifestError` for a malformed list.
std::set<std::string> MeshResourceHashes(const Project& project);

/// The SHA-256 of every resource `project`'s body references (mesh, the files the mesh reads beside
/// it, mesh maps, source and procedural image bindings), sorted.
std::set<std::string> RecipeResourceHashes(const Project& project);

/// `{schema, revision, evaluator_profile, compat_profile, app_version, resource_hashes, recipe,
/// digest}` of `project` at `revision`.
json::Object DumpRecipe(const Project& project, std::int64_t revision, const RecipeHost& host);

/// The project a dump describes, with fresh ids, ready to be committed into a new project: the
/// body with the `rebuild` block's values in place (a key the block does not give takes the
/// default of a new project; a baked mesh map's provenance has none):
/// - `ManifestError` when the dump is not a recipe dump, its digest does not match its body, a key
///   is missing or mistyped, its header is not a complete ARC-11 header (`HeaderFromJson`), its
///   compatibility profile is not `kCompatProfile`, or its evaluator profile or resource hashes
///   differ from the body's, or the `rebuild` block names output-determining state or a place the
///   body does not hold;
/// - `ValueError` when a channel's `base` differs from `host.base_value` (this build would
///   evaluate the channel differently), a pointer names no node, or the model is invalid;
/// - `NotYetSupported` for a paint node with a bound plane (plane content is not a resource, and
///   paint layers are a release gap: phase4.1_nodes-paint-layers).
/// Resource entries are named after the mesh file (the mesh) or their hash, with usage "mesh" or
/// "TEXTURE", and an empty origin and import time for the caller to fill, when the block has no
/// `resource_catalog`. The rebuilt project's body equals the dump's body, so its digest is the
/// dump's digest, and it holds every value the `rebuild` block gives. The files a mesh reads beside
/// it are resources of the body (`kMeshExternalFiles`), so the caller re-derives the mesh from the
/// stored bytes alone.
Project ProjectFromRecipe(const json::Value& dump, const RecipeHost& host);

}  // namespace uzp::core
