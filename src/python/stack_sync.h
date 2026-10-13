#pragma once

// The native composite `layerstack.sync_stack` (LAY-07; docs/architecture/10-python-api.md §6,
// task phase1.19_pyapi-native-module item 2.11) and the node edits the API shares with it.
//
// `SyncStack` rebuilds one root group of a stack from the Assets3D stack JSON, the format of
// `A3D\Pipeline\painting\painter_layer_stack.py sync`:
//
//   {"title": "<root group name>",
//    "groups": [{"key", "name", "mask"?: "<mask name>" | null, "replace_height"?: bool}],
//    "layers": [{"group": "<group key>", "name", "mask"?: "<mask name>" | null,
//                "base"?: [r, g, b] sRGB (0-1, or 0-255 when any component > 1) | "base_tex"?: "<image name>",
//                "rough"?, "metal"?, "spec"?, "height"?: number, "op"?: BaseColor opacity}]}
//
// Groups and the layers of a group are listed bottom to top. Each layer is a fill layer whose
// active channels are exactly the channels it names (BaseColor; SpecularRoughness for `rough`,
// BaseMetalness for `metal`, SpecularWeight for `spec`, Height for `height`): `base` an sRGB
// uniform colour, stored as the facade stores it (its float32 working value on an sRGB8
// BaseColor), `base_tex` the image `<name>` as an sRGB bitmap in UV projection (BilinearHQ, no
// repeat, unit scale, no rotation or offset), the others uniform values as given; `op` is the
// BaseColor opacity (1 when absent). A `mask` adds a black mask holding one fill effect whose
// source is the image `<mask name>` (Data colour space) in UV projection. Every node starts with
// Painter's insert defaults (`ApplyDefaultBlending`, `ApplyDefaultSources`), as the script's
// inserted nodes do, so Height adds unless `replace_height` blends the group's Height as Normal;
// the result is the document the script builds (decision 115). Unknown keys are ignored, as the
// pipeline script ignores them; the JSON is read, never changed.
//
// In one transaction: every image the stack names is imported (bytes already stored are noted as
// skipped), the root group is built detached and attached at the top of the stack in one step
// (`core::Edit::Attach`), the earlier root groups with the title are deleted (they are the group
// being rebuilt), and every other visible root layer is hidden, never deleted, unless its name
// starts with one of the keep-visible prefixes. A stack the JSON does not describe completely,
// an image that cannot be read or a channel the stack lacks fails the call before anything
// changes.

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include "store/project_store.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/ids.h"

namespace uzp::python {

/// Removes the layer or effect `uid` (with its subtree) from `project`; `ValueError` when there is
/// no such node.
void RemoveNode(core::Project& project, core::Id uid);

/// Painter's per-channel blending of a new fill, fill effect or group in a content stack (the
/// effective defaults of every inserted node in the Tier 0 api-probes; decision 115): Height blends
/// LinearDodge and Normal NormalMapDetail where the stack has the channel; every other channel
/// keeps the default `core::Blending`, Normal at opacity 1.
void ApplyDefaultBlending(core::ChannelBlending& blending, const std::map<core::ChannelType, core::Channel>& channels);

/// The sources Painter's new fill in a content stack holds, its active channels empty (decision
/// 115): BaseColor uniform 0.8 and Height 0, working-space values, where the stack has the
/// channel. Painter's default of every other channel is unrecorded (recording P20-A): no source.
void ApplyDefaultSources(core::FillContent& fill, const std::map<core::ChannelType, core::Channel>& channels);

/// The bytes of the image `<name>` (a PNG), or nullopt when it cannot be read.
using ImageReader = std::function<std::optional<std::string>(const std::string& name)>;

/// Imports `bytes` as a project resource named `name` within `edit`: stages the bytes in `store`
/// and adds the named entry unless the same bytes already carry that name (then the hash is noted
/// as skipped). Returns the SHA-256.
std::string ImportResource(core::Edit& edit, store::ProjectStore& store, std::string bytes, const std::string& name,
                           const std::string& mime, const std::string& usage, const std::string& origin);

struct SyncOptions {
    core::Id texture_set = core::kNoId;
    core::Id stack = core::kNoId;
    std::vector<std::string> keep_visible;
    /// The resource entry of the image `<name>` is named `<resource_prefix><name>` and carries
    /// `resource_group` as its group when one is given (`painter_layer_stack.py sync
    /// --resource-prefix --resource-group`; the MCP `sync_stack`, decision 164). The reports list
    /// image names.
    std::string resource_prefix;
    std::optional<std::string> resource_group;
};

/// Rebuilds the stack's group (see above) inside `edit`; returns
/// `{root_uid, layers [{group, name, uid}], groups [{key, name, uid}], imported [names],
///   skipped [names], deleted [uids], hidden [{name, uid}]}`.
core::json::Object SyncStack(core::Edit& edit, store::ProjectStore& store, const core::json::Object& stack_json,
                             const ImageReader& read, const SyncOptions& options);

}  // namespace uzp::python
