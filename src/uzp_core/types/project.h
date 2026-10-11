#pragma once

// Project model (`docs/architecture/03-project-model.md` §1-§4): settings, mesh reference,
// texture sets with their UV tiles, mesh-map bindings, bake settings and stacks, resources,
// display state, export defaults, metadata and versions. The manifest written from a `Project`
// is the public schema of the `.uzp` file (`09-project-file-format.md` §1,
// `src/uzp_core/schema/manifest.schema.json`).

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <variant>
#include <vector>

#include "uzp_core/manifest/json.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/layers.h"

namespace uzp::core {

/// Manifest format written by this version (semver, `09-…` §5).
inline constexpr std::string_view kFormatVersion = "1.0.0";
/// The manifest's `schema` key.
inline constexpr std::string_view kManifestSchema = "uzpainter/manifest/1";
/// The compatibility profile (`10-python-api.md` §1).
inline constexpr std::string_view kCompatProfile = "painter-12.1-api-0.3.7";

struct ColorManagement {
    std::string mode;           // e.g. "legacy" or "ocio"
    std::string config_hash;    // SHA-256 of the pinned configuration, "" when none
    std::string working_space;
    json::Array io_rules;       // input/output colour-space rules, in order
    json::Object extra;

    bool operator==(const ColorManagement&) const = default;
};

struct ProjectSettings {
    NormalMapFormat normal_map_format = NormalMapFormat::OpenGL;
    /// Unset = `PerVertex`, Painter 12.1.0's observed default; `PerFragment` when the caller sets
    /// it, as the Assets3D pipeline does (decision 031).
    TangentSpace tangent_space = TangentSpace::PerVertex;
    ProjectWorkflow workflow = ProjectWorkflow::Default;
    Resolution default_resolution;
    double mesh_unit_scale = 1.0;
    ColorManagement color_management;
    bool import_cameras = false;
    bool auto_unwrap = false;  // recorded; rejected at import (release gap)
    json::Object extra;

    bool operator==(const ProjectSettings&) const = default;
};

/// The imported mesh: its original bytes as a resource, and the import report. Texturing-mesh
/// data is re-derived, never stored.
struct MeshReference {
    std::string resource;  // SHA-256 of the original file
    json::Object import_report;
    json::Object extra;

    bool operator==(const MeshReference&) const = default;
};

/// A UV tile of a texture set; `udim` = 1001 + u + 10 v. The Default workflow has the single
/// tile 1001.
struct UVTile {
    Id id = kNoId;
    int udim = 1001;
    json::Object extra;

    bool operator==(const UVTile&) const = default;
};

struct ImportedProvenance {
    std::string source_path;
    std::string source_sha256;
    MeshMapRole declared_role = MeshMapRole::geometry_only;
    NormalMapFormat declared_convention = NormalMapFormat::OpenGL;
    std::string units;
    json::Object extra;

    bool operator==(const ImportedProvenance&) const = default;
};

struct MeshHashes {
    std::string positions;
    std::string uvs;
    std::string corner_normals;
    std::string triangulation;
    json::Object extra;

    bool operator==(const MeshHashes&) const = default;
};

struct BakedProvenance {
    std::string baker_version;
    BakerBackend backend = BakerBackend::embree;
    std::string settings_hash;
    std::vector<std::string> high_meshes;  // SHA-256 of each high-poly mesh
    std::optional<std::string> cage;       // SHA-256 of the cage mesh
    MeshHashes mesh_hashes;
    json::Object effective_normalization;  // e.g. the curvature bounds actually used
    json::Object extra;

    bool operator==(const BakedProvenance&) const = default;
};

/// `03-…` §4. A mesh reload whose hashes differ marks the binding `invalid` (kept, flagged,
/// never deleted) with the changed-region report.
struct MeshMapBinding {
    std::string resource;  // SHA-256 of the map's bytes
    ChannelFormat format = ChannelFormat::RGB16;
    std::string color_space;
    std::variant<ImportedProvenance, BakedProvenance> provenance;  // MeshMapProvenanceKind order
    bool invalid = false;
    std::optional<json::Object> invalid_report;
    json::Object extra;

    MeshMapProvenanceKind provenance_kind() const {
        return static_cast<MeshMapProvenanceKind>(provenance.index());
    }
    bool operator==(const MeshMapBinding&) const = default;
};

struct BakeSettings {
    json::Object common;
    json::Object detail;
    std::map<std::string, json::Object> per_baker;
    json::Object extra;

    bool operator==(const BakeSettings&) const = default;
};

struct Channel {
    ChannelFormat format = ChannelFormat::sRGB8;
    std::string label;
    json::Object extra;

    bool operator==(const Channel&) const = default;
};

/// A layer stack; `name` is "" for the ordinary stack. At most one channel per `ChannelType`
/// (the map key). Root layers are stored top first, as Painter lists them.
struct Stack {
    Id id = kNoId;
    std::string name;
    std::map<ChannelType, Channel> channels;
    std::vector<Layer> root_layers;
    json::Object extra;

    bool operator==(const Stack&) const = default;
};

struct TextureSet {
    Id id = kNoId;
    std::string name;
    std::string original_name;
    std::string description;
    std::string material_id;
    Resolution resolution;
    std::vector<UVTile> uv_tiles;
    std::map<MeshMapUsage, MeshMapBinding> mesh_maps;
    BakeSettings bake_settings;
    /// Optional in the manifest: a file without it holds the default, `Sharp`.
    HeightToNormalMethod height_to_normal_method = HeightToNormalMethod::Sharp;
    std::vector<Stack> stacks;
    json::Object extra;

    bool operator==(const TextureSet&) const = default;
};

/// One named entry for stored bytes. Identical bytes imported twice share one blob (the
/// `Project::resources` key) and keep one entry per name.
struct ResourceMeta {
    Id id = kNoId;
    std::string name;
    std::string mime;
    std::int64_t size = 0;
    std::string usage;
    std::string origin;
    std::string imported_at;  // RFC 3339 UTC
    std::string color_space;
    bool session = false;  // `ResourceID.from_session`: stored, flagged non-persistent
    json::Object extra;

    bool operator==(const ResourceMeta&) const = default;
};

struct Environment {
    std::optional<std::string> resource;  // SHA-256 of the HDRI
    double rotation = 0.0;
    double exposure = 0.0;
    double opacity = 1.0;
    double blur = 0.0;
    json::Object extra;

    bool operator==(const Environment&) const = default;
};

struct ShaderState {
    std::string id;
    std::string hash;
    json::Object parameters;
    json::Object extra;

    bool operator==(const ShaderState&) const = default;
};

struct DisplayState {
    Environment environment;
    std::optional<std::string> color_lut;  // SHA-256 of the LUT
    ToneMapping tone_mapping = ToneMapping::Linear;
    ShaderState shader;
    json::Array cameras;
    json::Object background;
    bool shadows = false;
    json::Object post_effects;  // all off by default
    json::Object extra;

    bool operator==(const DisplayState&) const = default;
};

struct PainterReference {
    std::string build;          // e.g. "12.1.0"
    std::string recorded_from;  // where the reference behaviour was recorded
    json::Object extra;

    bool operator==(const PainterReference&) const = default;
};

struct Versions {
    std::string format_version{kFormatVersion};
    std::string app_version;
    std::string evaluator_profile;
    std::string compat_profile{kCompatProfile};
    PainterReference painter_reference;
    json::Object extra;

    bool operator==(const Versions&) const = default;
};

struct Project {
    Versions versions;
    Id next_id = 1;  // the next persistent id to hand out
    ProjectSettings settings;
    std::optional<MeshReference> mesh;
    std::vector<TextureSet> texture_sets;  // mesh material order
    std::map<std::string, std::vector<ResourceMeta>> resources;  // SHA-256 -> named entries
    DisplayState display;
    json::Object export_defaults;
    std::map<std::string, json::Object> metadata;  // context -> {key -> json}
    json::Object extra;

    /// Hands out the next persistent id.
    Id AllocateId();

    bool operator==(const Project&) const = default;
};

}  // namespace uzp::core
