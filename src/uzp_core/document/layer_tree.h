#pragma once

// Layer-tree snapshots and their structural diff (`docs/architecture/11-mcp-server.md` §2
// Diagnostics, `snapshot_layer_tree` and `diff_snapshots`; task phase2.1_recipe-diagnostic-views,
// decision 136). Technical facts only: a diff grants no approval (QG-04).
//
// A snapshot is `{schema, revision, stacks, nodes}`:
// - `stacks`: one `{texture_set, texture_set_name, stack, stack_name}` per stack, in project order.
// - `nodes`: one record per node of every stack (layers, content effects and mask effects), in the
//   order of `ForEachNode` (root layers top first; for each layer its content effects, its mask
//   effects, then its sub-layers):
//   `{uid, node: "layer"|"effect", kind, name, visible, texture_set, stack, parent, slot, index,
//   params}`. `parent` is the uid of the layer holding the node (null for a root layer), `slot`
//   the list holding it (`Substack`, `Content` or `Mask`) and `index` its position there (top
//   first). `params` is the node's manifest object (`LayerToJson`, `EffectToJson`) without `uid`,
//   `kind`, `name` and `visible`; a layer's `content_effects` and `children` become lists of uids,
//   and its mask's `effects` too.
//
// `DiffSnapshots(before, after)` matches nodes by uid and stacks by their stack uid (ids are
// persistent and never reused within a project): `added` and `removed` hold the whole records,
// `modified` holds `{uid, changes}` (`{stack, changes}` for stacks), each change `{path, before,
// after}` with `path` a JSON pointer into the record. Objects are compared key by key; arrays and
// scalars are compared whole, so a reorder changes the `index` of every shifted sibling and the
// uid list of the parent. A key present on one side only omits the other side's member. Every
// list is sorted by uid (stack uid), changes by path. The revisions are reported, not compared:
// identical trees at two revisions give an empty diff.

#include <cstdint>
#include <string_view>

#include "uzp_core/manifest/json.h"
#include "uzp_core/types/project.h"

namespace uzp::core {

inline constexpr std::string_view kLayerTreeSchema = "uzpainter/layer-tree/1";
inline constexpr std::string_view kLayerTreeDiffSchema = "uzpainter/layer-tree-diff/1";

/// The layer-tree snapshot of `project` at `revision` (see above).
json::Object SnapshotLayerTree(const Project& project, std::int64_t revision);

/// The structural diff of two snapshots (see above). Throws `ValueError` when either is not a
/// snapshot of `kLayerTreeSchema` (a missing or mistyped member, a repeated uid or stack).
json::Object DiffSnapshots(const json::Value& before, const json::Value& after);

}  // namespace uzp::core
