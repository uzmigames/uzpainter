#pragma once

// Layer, effect and source model (`docs/architecture/04-layer-stack-and-compositing.md` §1).
//
// Every struct keeps the manifest keys this version does not know in `extra`; the writer emits
// them unchanged, so a newer file survives a load/save cycle (`09-project-file-format.md` §5).
// Mask-stack nodes are mono-channel: they use `mono_blending`, `FillContent::mono_source` and
// `PaintContent::mono_plane` instead of the per-channel maps.

#include <array>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <variant>
#include <vector>

#include "uzp_core/manifest/json.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/ids.h"

namespace uzp::core {

struct Resolution {
    int width = 1024;
    int height = 1024;
    json::Object extra;

    bool operator==(const Resolution&) const = default;
};

struct Blending {
    BlendingMode mode = BlendingMode::Normal;
    double opacity = 1.0;
    json::Object extra;

    bool operator==(const Blending&) const = default;
};
using ChannelBlending = std::map<ChannelType, Blending>;

/// A per-node binding to resource content: its SHA-256 and an optional alias (LAY-13).
struct ResourceBinding {
    std::string sha256;
    std::optional<std::string> alias;
    json::Object extra;

    bool operator==(const ResourceBinding&) const = default;
};

struct LevelsComponent {
    double input_min = 0.0;
    double input_max = 1.0;
    double gamma = 1.0;
    double output_min = 0.0;
    double output_max = 1.0;
    bool clamp = false;
    json::Object extra;

    bool operator==(const LevelsComponent&) const = default;
};

/// Levels: one component for a mono channel or a mask, three for an RGB channel.
struct LevelsParams {
    std::optional<ChannelType> affected_channel;  // none in a mask stack
    std::vector<LevelsComponent> components;
    json::Object extra;

    bool operator==(const LevelsParams&) const = default;
};

/// A procedural asset use (`05-procedural-content.md`): `asset` is a pinned
/// `uzasset://<family>/<id>@<version>` URL.
struct ProceduralRef {
    std::string asset;
    json::Object params;
    std::optional<std::string> preset;
    std::map<std::string, ResourceBinding> image_inputs;
    std::map<std::string, std::string> output_mapping;  // channel name -> asset output
    std::optional<std::string> mask_output;
    std::optional<Resolution> resolution_override;
    json::Object extra;

    bool operator==(const ProceduralRef&) const = default;
};

struct UniformColorSource {
    std::array<double, 3> rgb{0.0, 0.0, 0.0};
    std::string color_space;
    json::Object extra;

    bool operator==(const UniformColorSource&) const = default;
};

struct BitmapSource {
    ResourceBinding resource;
    std::string color_space;
    json::Object extra;

    bool operator==(const BitmapSource&) const = default;
};

/// Vector and font sources (release gaps, `10-python-api.md` §3) keep their resource and
/// parameters so a project that uses them round-trips.
struct VectorSource {
    ResourceBinding resource;
    json::Object params;
    json::Object extra;

    bool operator==(const VectorSource&) const = default;
};

struct FontSource {
    ResourceBinding resource;
    json::Object params;
    json::Object extra;

    bool operator==(const FontSource&) const = default;
};

struct ProceduralSource {
    ProceduralRef ref;

    bool operator==(const ProceduralSource&) const = default;
};

/// A reference to an anchor point effect: the anchor's uid, then either a channel mapping
/// (multichannel use) or one referenced channel.
struct ReferenceSource {
    Id anchor = kNoId;
    std::map<ChannelType, ChannelType> channel_mapping;
    std::optional<ChannelType> referenced_channel;
    bool alpha_matte = false;
    std::optional<LevelsParams> levels;
    json::Object extra;

    bool operator==(const ReferenceSource&) const = default;
};

/// Alternatives in `SourceKind` order.
struct Source {
    std::variant<UniformColorSource, BitmapSource, VectorSource, FontSource, ProceduralSource,
                 ReferenceSource>
        value;

    SourceKind kind() const { return static_cast<SourceKind>(value.index()); }
    bool operator==(const Source&) const = default;
};

struct UVTransformation {
    ScaleMode scale_mode = ScaleMode::Factors;
    std::array<double, 2> scale{1.0, 1.0};
    double rotation = 0.0;
    std::array<double, 2> offset{0.0, 0.0};
    json::Object extra;

    bool operator==(const UVTransformation&) const = default;
};

struct UVProjectionParams {
    FilteringMode filtering_mode = FilteringMode::BilinearHQ;
    UVWrapMode uv_wrapping_mode = UVWrapMode::Repeat;
    UVTransformation uv_transformation;
    json::Object extra;

    bool operator==(const UVProjectionParams&) const = default;
};

/// `uv` holds the documented UV parameters; `params` the parameters of the 3D modes
/// (hardness, 3D transform, culling, crop), whose semantics are fitted from Tier 0 goldens.
struct Projection {
    ProjectionMode mode = ProjectionMode::UV;
    UVProjectionParams uv;
    json::Object params;
    json::Object extra;

    bool operator==(const Projection&) const = default;
};

struct Symmetry {
    bool enabled = false;
    json::Object params;
    json::Object extra;

    bool operator==(const Symmetry&) const = default;
};

/// Content of a fill layer or a fill effect.
struct FillContent {
    SourceMode source_mode = SourceMode::Split;
    std::map<ChannelType, Source> sources;  // content stacks
    std::optional<Source> mono_source;      // mask stacks
    std::optional<Source> material_source;  // SourceMode::Material
    std::set<ChannelType> active_channels;  // content stacks
    Projection projection;
    Symmetry symmetry;
    json::Object extra;

    bool operator==(const FillContent&) const = default;
};

/// Content of a paint layer or a paint effect: one authoritative raster plane per channel,
/// referenced by `plane_id` (`09-project-file-format.md` §1).
struct PaintContent {
    std::map<ChannelType, Id> planes;  // content stacks
    std::optional<Id> mono_plane;      // mask stacks
    json::Object extra;

    bool operator==(const PaintContent&) const = default;
};

/// Provenance of a node expanded from a smart material (a group) or a smart mask (a mask
/// effect); never read by evaluation.
struct PresetRef {
    PresetKind kind = PresetKind::smart_material;
    std::string asset;  // uzasset://<family>/<id>@<version>
    json::Object extra;

    bool operator==(const PresetRef&) const = default;
};

struct Effect {
    Id uid = kNoId;
    EffectKind kind = EffectKind::fill;
    std::string name;
    bool visible = true;
    ChannelBlending blending;              // content stacks
    std::optional<Blending> mono_blending;  // mask stacks
    std::set<ChannelType> active_channels;  // generator and filter effects in content stacks
    std::optional<FillContent> fill;        // fill
    std::optional<PaintContent> paint;      // paint
    std::optional<ProceduralRef> procedural;  // generator, filter
    std::optional<LevelsParams> levels;       // levels
    std::optional<json::Object> compare_mask;     // compare_mask parameters
    std::optional<json::Object> color_selection;  // color_selection parameters
    std::optional<std::string> anchor_name;       // anchor
    std::optional<PresetRef> preset_ref;          // smart-mask provenance
    json::Object extra;

    NodeType type() const { return NodeTypeOf(kind); }
    bool operator==(const Effect&) const = default;
};

struct Mask {
    MaskBackground background = MaskBackground::White;
    bool enabled = true;
    Blending blending;
    std::vector<Effect> effects;
    json::Object extra;

    bool operator==(const Mask&) const = default;
};

struct GeometryMask {
    GeometryMaskType type = GeometryMaskType::Mesh;
    bool inclusion_list = false;  // true: only `items` are included; false: `items` are excluded
    std::vector<std::string> items;
    json::Object extra;

    bool operator==(const GeometryMask&) const = default;
};

struct Layer {
    Id uid = kNoId;
    LayerKind kind = LayerKind::fill;
    std::string name;
    bool visible = true;
    ChannelBlending blending;
    std::vector<Effect> content_effects;
    std::optional<Mask> mask;
    GeometryMask geometry_mask;
    std::optional<FillContent> fill;    // fill
    std::optional<PaintContent> paint;  // paint
    std::vector<Layer> children;        // group: sub-layers, top first
    Id instance_source = kNoId;         // instance: the uid of the instanced layer
    bool collapsed = false;             // group: inert UI state, kept as state
    std::optional<PresetRef> preset_ref;  // smart-material provenance
    json::Object extra;

    NodeType type() const { return NodeTypeOf(kind); }
    bool operator==(const Layer&) const = default;
};

}  // namespace uzp::core
