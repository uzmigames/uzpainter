#pragma once

// Frozen procedural snapshots in the project file (`docs/architecture/05-procedural-content.md`
// §4, `09-project-file-format.md` §1, §2; decision 327).
//
// A snapshot is a raster the user's own Painter produced for this project, stored as an
// authoritative raster plane with its exact signature in the manifest. The manifest's top-level
// `procedural_snapshots` object holds one entry per snapshot, keyed by the SHA-256 of the
// signature's canonical JSON:
//
//     "procedural_snapshots": {"<signature sha256>": {
//         "signature": {...},            // procedural/seam.h SignatureJson
//         "project_uuid": "<uuid>",      // the project it was recorded for
//         "plane": <plane_id>,
//         "plane_versions": {"<plane_id>": {"chunk_root": <hex>, "version_id": <n>}},
//         "source_metadata": {...}}}    // optional, see below
//
// `source_metadata` is what the recording observed about the source beyond the signature:
// `{"schema": "uzpainter/procedural-source-metadata/1", "asset": "<asset>@<version>",
// "image_outputs": [...]}`, where `asset` is the signature's exact pin and `image_outputs` the
// source's complete ordered output identifiers (A-PYDOC `SourceSubstance.image_outputs`), which
// include the signature's output id. It is not part of the signature: an absent member means
// "not recorded" and is never written as empty or null, so entries recorded without it keep their
// bytes. Schema `/2` adds optional observations of the same recording: `image_inputs` (the ordered
// input identifiers), `presets` (`get_preset_list()`) and `properties` (each `get_properties()`
// entry described by its documented getters). An absent optional member means "not observed"; an
// empty one is an observation. Metadata with only `image_outputs` is written as `/1`.
//
// The entry holds its plane as a mask-stack paint object does (`plane`, `plane_versions`), so the
// plane rules of planes.h cover it unchanged: its binding travels with the manifest (digest,
// revert, compaction reachability, integrity, `inspect`, `export-bundle` and the bundle import).
// The plane row has no texture set, stack, channel or UV tile (all 0 / NULL): a snapshot belongs
// to the project, not to a node.
//
// Snapshots are project-private: an entry recorded for another project is refused at commit
// (`CheckSnapshots`), reported by the integrity check and never served (SnapshotBackend). The
// document model keeps the key verbatim (`Project::extra`); the store owns it.

#include <expected>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "store/container.h"
#include "store/planes.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/project.h"

namespace uzp::store {

/// The manifest's top-level key of the snapshot entries.
inline constexpr std::string_view kSnapshotsKey = "procedural_snapshots";
/// An entry's optional member of recorded source metadata, and its schema.
inline constexpr std::string_view kSourceMetadataKey = "source_metadata";
inline constexpr std::string_view kSourceMetadataSchema = "uzpainter/procedural-source-metadata/1";
inline constexpr std::string_view kSourceMetadataSchemaV2 = "uzpainter/procedural-source-metadata/2";
inline constexpr std::string_view kSourceMetadataSchemaV3 = "uzpainter/procedural-source-metadata/3";
inline constexpr std::string_view kSourceMetadataSchemaV4 = "uzpainter/procedural-source-metadata/4";
/// `/5` (phase3.3_procedural-families item 2.16): the `/4` members with colour parameters. It is
/// written only when a parameter, preset parameter or property value is a tagged colour, so the
/// bytes of every scalar-only entry are unchanged.
inline constexpr std::string_view kSourceMetadataSchemaV5 = "uzpainter/procedural-source-metadata/5";

/// The ResourceID a recording observed through its documented getters (decision 361): every part
/// as Painter returned it. Provenance only: it never resolves, imports, binds or searches.
struct ObservedResourceId {
    std::string url;
    std::string context;
    std::string name;
    std::string version;

    bool operator==(const ObservedResourceId&) const = default;
};

/// The observations of a recording beside its signature (`source_metadata`, above).
struct SourceMetadata {
    std::vector<std::string> image_outputs;
    std::optional<std::vector<std::string>> image_inputs;
    std::optional<std::vector<std::string>> presets;
    std::optional<core::json::Object> properties;
    /// `/3` (decision 361): the complete raw parameter map `get_parameters` returned, JSON types
    /// kept (an integral float stays a double), and the observed ResourceID.
    std::optional<core::json::Object> typed_effective_parameters;
    std::optional<ObservedResourceId> observed_resource_id;
    /// `/4` (decision 413): per preset, the raw parameter map Painter's own `apply_preset` gave
    /// from the recorded state; each image input's source as read back (`{"raised": {type,
    /// message}}`, `{"class": "SourceUniformColor", "working": [r, g, b]}` or `{"class":
    /// "SourceBitmap", "sha256", "colour_space"}`); and the single and multiple output contexts of
    /// the same state (`{"split": {output_mapping, mask_output}, "material": {output_mapping,
    /// mask_output, active_channels, active_output}}`, each outcome `{"raised": ...}`, `{"returned":
    /// <class>}` or, for the material `active_output`, `{"value": <output>}`).
    std::optional<core::json::Object> preset_parameters = std::nullopt;
    std::optional<core::json::Object> input_sources = std::nullopt;
    std::optional<core::json::Object> contexts = std::nullopt;

    bool operator==(const SourceMetadata&) const = default;
};

/// One entry of `procedural_snapshots`.
struct SnapshotEntry {
    std::string key;  ///< The signature SHA-256 the entry is stored under.
    core::json::Value signature;
    std::string project_uuid;
    core::Id plane_id = core::kNoId;
    std::optional<VersionRef> version;
    /// The entry's parsed `source_metadata`; empty when it has none.
    std::optional<SourceMetadata> source_metadata;
    std::string path;   ///< The JSON path of the entry (`procedural_snapshots.<key>`).
    std::string error;  ///< Why the entry is malformed; empty when it is well-formed.
};

/// The `source_metadata` of a snapshot of `signature`: `/4` when `preset_parameters`,
/// `input_sources` or `contexts` is given, else `/3` when `typed_effective_parameters` or
/// `observed_resource_id` is given, else `/1` when only `image_outputs` is given and `/2` with the
/// optional members that are present otherwise (so `/1`, `/2` and `/3` bytes are unchanged).
core::json::Value SourceMetadataJson(const core::json::Value& signature, const SourceMetadata& metadata);
core::json::Value SourceMetadataJson(const core::json::Value& signature, const std::vector<std::string>& image_outputs);
/// `metadata` read as the `source_metadata` of a snapshot of `signature`, or why it may not be:
/// it is not an object of `schema`, `asset` and `image_outputs` (plus, under `/2` and `/3`, the
/// optional `image_inputs`, `presets` and `properties`, and under `/3` only the optional
/// `typed_effective_parameters` and `observed_resource_id`, at least one of which `/3` holds); its
/// schema is not `/1`, `/2` or `/3`;
/// `asset` is not the signature's `<asset>@<version>`; `image_outputs` is not a nonempty array of
/// distinct nonempty strings that holds the signature's `output.id`; `image_inputs` or `presets`
/// is not an array of distinct nonempty strings; `properties` is not an object of objects;
/// `typed_effective_parameters` is not an object of int64, finite double or string values whose
/// keys are exactly the signature's `params` and whose values equal them by value
/// (`ParamByValue`); or `observed_resource_id` is not exactly four nonempty strings `url`,
/// `context`, `name` and `version` with the signature's pin `uzasset://snapshot/<sha256(url)>@1`.
/// Under `/5` (and only there), a typed parameter, a preset parameter or a property value may also
/// be a tagged colour (`TypedParamByValue`), at least one of them is one, and `contexts.material`
/// also holds `colour_spaces`: the space name the material source reads each colour parameter in,
/// keyed exactly by the colour-valued typed parameters (the capture's split sources read Raw, the
/// material source sRGB, with the same components; item 2.16).
/// Under `/4` only (which holds at least one of them): `preset_parameters` is an object, keyed
/// exactly by the observed `presets` when they are present, of parameter maps keyed exactly by the
/// signature's `params` with int64, finite double or string values; `input_sources` is an object
/// keyed exactly by the observed `image_inputs` when present, each source one of the three forms,
/// a plugged one equal to the signature's plugged input and an unplugged one absent from it;
/// `contexts` holds exactly `split` and `material` as above, the material `output_mapping` from
/// channel type names to listed outputs and `active_channels` distinct channel type names.
std::expected<SourceMetadata, std::string> ParseSourceMetadata(const core::json::Value& signature,
                                                               const core::json::Value& metadata);
/// A scalar parameter as the signature encodes it, by value (procedural/seam.h `ParamJson` for
/// scalars): an integral double inside the int64 range is that integer (-0.0 is 0), any other
/// double stays a double, integers and strings are unchanged; empty for any other value (bool,
/// null, array, object), which a typed parameter map refuses.
std::optional<core::json::Value> ParamByValue(const core::json::Value& value);
/// `ParamByValue`, or a colour parameter as the signature encodes it (procedural/seam.h
/// `ParamJson`): exactly `{"type": "color", "working_space": <nonempty>, "components": [three
/// finite numbers], "alpha": null}`, each component by value. Empty for any other value. A `/5`
/// typed map takes these colours; `/1` to `/4` take scalars only.
std::optional<core::json::Value> TypedParamByValue(const core::json::Value& value);
/// Whether `value` is a tagged colour that `TypedParamByValue` admits.
bool IsColourParam(const core::json::Value& value);
/// The error of `ParseSourceMetadata`, or empty.
std::string SourceMetadataProblem(const core::json::Value& signature, const core::json::Value& metadata);

/// Every entry of the `procedural_snapshots` member `member` (the manifest's, or the value
/// `Project::extra` holds), in key order. A member that is not an object gives one malformed
/// entry.
std::vector<SnapshotEntry> SnapshotEntries(const core::json::Value& member);
/// Every snapshot entry of `manifest` (none when it has no `procedural_snapshots`).
std::vector<SnapshotEntry> ManifestSnapshots(const core::json::Value& manifest);
/// The snapshot entries `project` holds.
std::vector<SnapshotEntry> ProjectSnapshots(const core::Project& project);

/// Why `entry` may not stand in the manifest of project `project_uuid`, or empty: it is
/// malformed, its key is not the SHA-256 of its signature's canonical JSON, or it was recorded
/// for another project.
std::string SnapshotProblem(const SnapshotEntry& entry, std::string_view project_uuid);

/// The commit check: throws `StoreError(conflict)` naming the first entry of `project` with a
/// `SnapshotProblem`, so a snapshot copied from another project is never committed.
void CheckSnapshots(const core::Project& project, std::string_view project_uuid);

/// Stages a snapshot of project `project_uuid` in the edit's working copy: allocates a plane id
/// from the project counter, stages `image` as its first version and adds the entry under the
/// SHA-256 of `signature`'s canonical JSON, with `source_metadata` when `metadata` is given.
/// Returns the plane id. The texels are stored unmodified in the image's plane format. Throws
/// `core::ValueError` when `signature` is not an object, the metadata has a
/// `SourceMetadataProblem`, the project already holds a snapshot with that signature (a snapshot
/// is immutable migration data), or the size is outside 1..`kMaxPlaneEdge` or does not match the
/// texels; `StoreError(conflict)` when the allocated id is already a stored plane.
core::Id StageSnapshot(Container& container, PendingPlanes& pending, core::Edit& edit,
                       std::string_view project_uuid, const core::json::Value& signature, const PlaneImage& image,
                       const std::optional<SourceMetadata>& metadata = std::nullopt);

}  // namespace uzp::store
