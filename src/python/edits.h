#pragma once

// The native edits the `uzpainter` API (bind_*.cpp) and the worker's typed MCP tools
// (src/supervisor/typed_tools.cpp; task phase2.6_mcp-typed-tool-families, decision 164) share.
// Each function changes the working copy of one transaction (`core::Edit`) or reads what a call
// needs before its transaction; the caller decides how the transaction is submitted: an API call
// with a fresh key (`Session::Mutate`), a typed tool with its client's key and original
// precondition (`Session::Submit`). So a typed tool and the API call it mirrors make the same
// change.
//
// Channel arguments follow Painter's contexts: a node of a content stack needs a channel (none
// raises `EditionContextException`), a node of a mask stack takes none (a channel raises
// `ValueError`).

#include <filesystem>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include "mesh/reload.h"
#include "python/bindings.h"
#include "python/stack_sync.h"
#include "store/project_store.h"
#include "uzp_core/naming/naming.h"
#include "uzp_core/types/validation.h"

namespace uzp::python {

using ChannelArg = std::optional<core::ChannelType>;

// ── Nodes ───────────────────────────────────────────────────────────────────────────────────────

/// Checks a channel argument against the node's context (see above).
void CheckChannel(bool mask, const ChannelArg& channel, core::Id uid);

/// The fill content of a fill layer or fill effect of the working copy; `mask` (when given) tells
/// whether the node is in a mask stack. `ValueError` for a missing node or one that is not a fill.
core::FillContent& EditFill(core::Edit& edit, core::Id uid, bool* mask = nullptr);

/// The source of `channel` (or the mono source) of a fill, which must be of `kind`.
core::Source& EditSource(core::Edit& edit, core::Id uid, const ChannelArg& channel, core::SourceKind kind);

/// The blending of `channel` of a layer or effect (the mono blending of a mask-stack effect).
core::Blending& EditBlending(core::Edit& edit, core::Id uid, const ChannelArg& channel);

/// Whether a node of `type` has blending (anchor point and levels effects have none).
bool HasBlending(core::NodeType type);

/// The name Painter gives a node of `type` inserted without one.
std::string DefaultName(core::NodeType type);

/// The name scope of the list an insert position puts a node into.
core::NameScope ScopeOf(const core::Project& project, const core::InsertPosition& position);

struct Inserted {
    core::Id uid = core::kNoId;
    bool created = false;
};

/// Inserts a node of `type` at `position` (LAY-06): with a name, a node of that name and type
/// already in the position's list is returned instead (`created` false, nothing inserted), a node
/// of that name and another type, or several such nodes (`core::AmbiguousNameError`), fail before
/// anything changes. A created node is passed to `configure`. Records `returned.node` and
/// `returned.created`.
Inserted InsertNode(core::Edit& edit, const core::InsertPosition& position, core::NodeType type,
                    const std::optional<std::string>& name, core::Id instance_source = core::kNoId,
                    const std::function<void(core::Edit&, core::Id)>& configure = nullptr);

/// Painter's effective defaults of a node `InsertNode` just created in a content stack (the
/// inserted nodes of the Tier 0 api-probes; decision 115): a fill, fill effect or group gets
/// Painter's per-channel blending, a fill its recorded default sources (active channels stay
/// empty), and a levels effect, where the stack has BaseColor, affects BaseColor and is named
/// "Levels - Base color" unless the call named it. A node in a mask stack keeps the plain defaults.
void InsertDefaults(core::Edit& edit, core::Id uid, bool named);

/// Whether a levels effect works on an RGB channel (three components) rather than a mono one.
bool RgbChannel(const core::Project& project, const NodeInfo& info, const core::LevelsParams* params);

/// A levels component stored as Painter stores it (float32 values).
core::LevelsComponent Component(double in_min, double in_max, double gamma, double out_min, double out_max, bool clamp);

/// `LevelsEffectNode.affected_channel = channel`: an identity levels gets the channel's arity;
/// mono parameters spread to RGB, RGB keeps its first.
void SetAffectedChannel(core::Edit& edit, core::Id uid, core::ChannelType channel);

/// The reader of `sync_stack`'s images: `<dir>/<name>.png`, nothing when it cannot be read.
ImageReader MaskImageReader(const std::filesystem::path& dir);

/// The bitmap source of `node` for `channel` (none: the mono source of a mask-stack fill).
core::BitmapSource& EditBitmap(core::Edit& edit, core::Id uid, const ChannelArg& channel);

// ── Uniform colours (decision 240) ──────────────────────────────────────────────────────────────
//
// Every path that stores a uniform colour (`FillLayerNode.set_source`, `SourceUniformColor.set_color`,
// the MCP `source_set`, `sync_stack`'s `base`, and the facade through
// `uzpainter.colormanagement._working_value`) stores the float32 working-space value Painter stores,
// in the Working space, computed here once, with the same refusals before any change.

/// Whether `channel` of a stack holding `channels` decodes an sRGB uniform colour to the working
/// space (Painter's colour-managed channel): an sRGB8 channel other than a user channel. A mask's
/// mono source (no channel), a user channel and any other format take a uniform colour as given,
/// whatever its space (decision 115).
bool DecodesColour(const std::map<core::ChannelType, core::Channel>& channels, const ChannelArg& channel);

/// Whether `project`'s colour management is OCIO with Painter's substance config (false: Painter's
/// Legacy mode, an unset mode included); `NotYetSupported` for any other configuration, which is
/// not a pinned colour profile (decisions 107, 190 and 202).
bool OcioColourProfile(const core::Project& project);

/// The float32 working-space value Painter stores for the uniform colour `rgb` given in `space`
/// (none: no colour space) on a channel that `decodes` it or not, under OCIO with Painter's
/// substance config (`ocio`) or Legacy:
/// - no space is sRGB on a decoding channel and Raw elsewhere;
/// - a channel that does not decode takes `rgb` as given, whatever its space, once the space is
///   checked against the profile;
/// - sRGB decodes with `evaluator::PainterLegacySrgbDecode` (Legacy) or reads Painter's measured
///   value `evaluator::PainterOcioSrgbDecode` (OCIO); Working, Linear (Legacy only) and Raw are
///   taken as given.
/// Refusals, each before any change: under OCIO a component the measured table does not record,
/// an sRGB colour on a channel that does not decode it and any other space are `NotYetSupported`
/// (phase1.15 item 2.6, decision 202); in Legacy any other space is `ValueError`.
std::array<double, 3> WorkingColour(const std::array<double, 3>& rgb, const std::optional<std::string>& space,
                                    bool decodes, bool ocio);

/// The uniform colour source a native setter stores on `channel` (none: the mono source) of the fill
/// `uid` of `project`: `WorkingColour` on that channel of the node's stack under the project's
/// colour management (`OcioColourProfile`), in the Working space.
core::UniformColorSource StoredUniformColour(const core::Project& project, core::Id uid, const ChannelArg& channel,
                                            const std::array<double, 3>& rgb, const std::optional<std::string>& space);

// ── Texture sets ────────────────────────────────────────────────────────────────────────────────

core::TextureSet& EditSet(core::Edit& edit, core::Id id);
core::Stack& EditStack(core::Edit& edit, const StackHandle& handle);

/// Removes every per-node entry of `channel` from `layers` (active channels, sources, blending).
void StripChannel(std::vector<core::Layer>& layers, core::ChannelType channel);

/// `TextureSet.set_mesh_map_resource`: binds the project resource `resource` (none unbinds).
void SetMeshMapResource(core::Edit& edit, core::Id set, core::MeshMapUsage usage,
                        const std::optional<ResourceIdHandle>& resource);

// ── Resources ───────────────────────────────────────────────────────────────────────────────────

/// `resource.Usage`.
enum class ResourceUsage { TEXTURE, ENVIRONMENT, COLOR_LUT, GENERATOR, SMART_MATERIAL };

/// A resource file read and checked before its import's transaction.
struct ResourceFile {
    std::string bytes;
    std::string kind;   // TEXTURE or ENVIRONMENT
    std::string mime;
    std::string entry;  // the entry name
    std::string origin;
    std::string file_name;
};

/// Reads `file_path` for `resource.import_project_resource`: a COLOR_LUT is `UnsupportedInUzPainter`
/// (decision 038), GENERATOR and SMART_MATERIAL and a texture that is not a PNG are
/// `NotYetSupported`, an unreadable file `ResourceNotFoundError`, an environment that is not an
/// equirectangular OpenEXR `ValueError`. The entry is `name`, or the file's stem.
ResourceFile ReadResourceFile(const std::string& file_path, ResourceUsage usage, const std::optional<std::string>& name);

/// Imports a read file as a project resource in `edit` (`ImportResource`), with its `group` kept on
/// the entry; returns the SHA-256.
std::string ImportResourceFile(core::Edit& edit, store::ProjectStore& store, const ResourceFile& file,
                               const std::optional<std::string>& group);

/// `resource.update_layer_stack_resource`: rebinds every bitmap source of the layer stacks that
/// binds `from` to `to`; the uids of the rebound nodes. A mesh map bound to `from` is a release gap
/// (recording P22-A, decision 112), refused before any change.
std::vector<core::Id> ReplaceLayerStackResource(core::Edit& edit, const ResourceIdHandle& from, const ResourceIdHandle& to);

// ── Project ─────────────────────────────────────────────────────────────────────────────────────

/// `project.reload_mesh(path)` (`mesh/reload.h`): the constructor reads the new mesh file and the
/// project's template before the transaction, `Apply` runs inside it, `Finish` records the open
/// project's mesh path after the commit.
class MeshReloadCall {
public:
    MeshReloadCall(const std::string& mesh_file_path, std::optional<bool> import_cameras,
                   std::map<std::string, std::string> material_mapping);

    const core::json::Object& arguments() const { return arguments_; }
    void Apply(core::Edit& edit) const;
    void Finish() const;

private:
    std::shared_ptr<OpenProject> project_;
    std::filesystem::path path_;
    std::string bytes_;
    std::optional<bool> import_cameras_;
    mesh::ReloadSettings settings_;
    mesh::ResourceReader read_;
    mesh::MeshSource source_;
    core::json::Object arguments_;
};

}  // namespace uzp::python
