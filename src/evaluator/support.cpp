#include "evaluator/support.h"

#include <algorithm>
#include <vector>

#include "uzp_core/document/nodes.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/errors.h"

namespace uzp::evaluator {

namespace {

using core::ChannelType;
using core::EffectKind;
using core::LayerKind;
using core::ProjectionMode;
using core::SourceKind;

using Gap = std::optional<SupportGap>;

Gap Make(core::Id node, std::string feature, std::string owner) {
    return SupportGap{node, std::move(feature), std::move(owner)};
}

bool LegacyColour(const core::Project& project) {
    const std::string& mode = project.settings.color_management.mode;
    return mode.empty() || mode == "legacy";
}

/// A source of a fill (layer or fill effect), for `channel` (nullopt: a mask's mono source).
Gap SourceGap(const core::Project& project, const core::Source& source, std::optional<ChannelType> channel,
              core::Id node) {
    switch (source.kind()) {
        case SourceKind::uniform_color:
            if (channel == ChannelType::Normal &&
                project.settings.normal_map_format != core::NormalMapFormat::OpenGL) {
                return Make(node, "a uniform colour on the Normal channel of a DirectX project",
                            "phase1.12_compositor-height-normal");
            }
            return std::nullopt;
        case SourceKind::bitmap: return std::nullopt;
        case SourceKind::vector: return Make(node, "a vector source", "phase4.1_nodes-vector-font-sources");
        case SourceKind::font: return Make(node, "a font source", "phase4.1_nodes-vector-font-sources");
        case SourceKind::procedural: return Make(node, "a procedural source", "phase3.3_procedural-families");
        case SourceKind::reference:
            return Make(node, "an anchor reference source", "phase4.1_nodes-instances-anchors");
    }
    return std::nullopt;
}

Gap FillGap(const core::Project& project, const core::FillContent& fill, core::Id node) {
    if (fill.source_mode == core::SourceMode::Material) {
        return Make(node, "the Material source mode", "phase3.2_proc-material-families");
    }
    switch (fill.projection.mode) {
        case ProjectionMode::Fill:
        case ProjectionMode::UV: break;
        case ProjectionMode::Triplanar:
        case ProjectionMode::Planar:
        case ProjectionMode::Spherical:
        case ProjectionMode::Cylindrical:
            return Make(node, "the " + std::string(core::ToString(fill.projection.mode)) + " projection",
                        "phase3.4_smart-projections");
        case ProjectionMode::Warp:
        case ProjectionMode::UVSetToUVSet:
            return Make(node, "the " + std::string(core::ToString(fill.projection.mode)) + " projection",
                        "phase4.1_nodes-projections");
    }
    if (fill.symmetry.enabled) return Make(node, "symmetry", "phase3.4_smart-projections");
    if (fill.projection.mode == ProjectionMode::UV) {
        const core::UVProjectionParams& uv = fill.projection.uv;
        if (uv.uv_transformation.scale_mode == core::ScaleMode::CustomPhysicalSize) {
            return Make(node, "the CustomPhysicalSize UV scale mode", "phase3.4_smart-projections");
        }
        if (uv.uv_transformation.scale_mode == core::ScaleMode::MaterialPhysicalSize) {
            return Make(node, "the MaterialPhysicalSize UV scale mode", "phase3.2_proc-material-families");
        }
        if (uv.uv_wrapping_mode == core::UVWrapMode::RepeatHorizontally ||
            uv.uv_wrapping_mode == core::UVWrapMode::RepeatVertically) {
            return Make(node, "the " + std::string(core::ToString(uv.uv_wrapping_mode)) + " wrap mode",
                        "phase4.2_remaining-nodes");
        }
    }
    const bool hasSource = !fill.sources.empty() || fill.mono_source || fill.material_source;
    if (hasSource && !LegacyColour(project)) {
        return Make(node, "colour management mode '" + project.settings.color_management.mode + "'",
                    "phase1.20_pyapi-facade");
    }
    for (const auto& [channel, source] : fill.sources) {
        if (Gap gap = SourceGap(project, source, channel, node)) return gap;
    }
    if (fill.mono_source) return SourceGap(project, *fill.mono_source, std::nullopt, node);
    return std::nullopt;
}

/// A DirectX project's Normal channel is recorded as one bitmap fill in Normal mode at opacity 1
/// without mask or effects (decision 079): any other layer with a Normal source is a gap (the
/// evaluator refuses a root list of several Normal layers itself).
Gap DirectXNormalGap(const core::Project& project, const core::Layer& layer) {
    if (project.settings.normal_map_format == core::NormalMapFormat::OpenGL || layer.kind != LayerKind::fill ||
        !layer.fill || !layer.fill->sources.contains(ChannelType::Normal)) {
        return std::nullopt;
    }
    const auto blending = layer.blending.find(ChannelType::Normal);
    const bool plain = blending == layer.blending.end() ||
                       (blending->second.mode == core::BlendingMode::Normal && blending->second.opacity == 1.0);
    if (plain && !layer.mask && layer.content_effects.empty()) return std::nullopt;
    return Make(layer.uid, "a Normal-channel layer of a DirectX project other than one bitmap fill at opacity 1",
                "phase1.12_compositor-height-normal");
}

Gap LayerGap(const core::Project& project, const core::Layer& layer) {
    switch (layer.kind) {
        case LayerKind::paint: return Make(layer.uid, "a paint layer", "phase4.1_nodes-paint-layers");
        case LayerKind::instance:
            return Make(layer.uid, "an instance layer", "phase4.1_nodes-instances-anchors");
        case LayerKind::fill:
        case LayerKind::group: break;
    }
    const core::GeometryMask& geometry = layer.geometry_mask;
    if (geometry.inclusion_list || !geometry.items.empty()) {
        if (geometry.type == core::GeometryMaskType::UVTile) {
            return Make(layer.uid, "a UVTile geometry mask", "phase4.5_uv-tiles");
        }
        return Make(layer.uid, "a Mesh geometry mask", "phase4.2_remaining-nodes");
    }
    if (Gap gap = DirectXNormalGap(project, layer)) return gap;
    if (layer.kind == LayerKind::fill && layer.fill) return FillGap(project, *layer.fill, layer.uid);
    return std::nullopt;
}

Gap EffectGap(const core::Project& project, const core::Effect& effect, core::NodeStack stack) {
    switch (effect.kind) {
        case EffectKind::generator: return Make(effect.uid, "a generator effect", "phase3.2_proc-generator-families");
        case EffectKind::filter: return Make(effect.uid, "a filter effect", "phase3.2_proc-filter-families");
        case EffectKind::paint: return Make(effect.uid, "a paint effect", "phase4.1_nodes-paint-layers");
        case EffectKind::compare_mask: return Make(effect.uid, "a compare-mask effect", "phase4.1_nodes-mask-effects");
        case EffectKind::color_selection:
            return Make(effect.uid, "a colour-selection effect", "phase4.1_nodes-mask-effects");
        case EffectKind::anchor: return Make(effect.uid, "an anchor effect", "phase4.1_nodes-instances-anchors");
        case EffectKind::levels:
            if (stack == core::NodeStack::Mask) {
                return Make(effect.uid, "a levels effect in a mask stack", "phase4.2_remaining-nodes");
            }
            return std::nullopt;
        case EffectKind::fill:
            if (stack == core::NodeStack::Content) {
                // Every recorded content-effect order holds the Blur filter (decision 069).
                return Make(effect.uid, "a fill effect in a content stack", "phase3.2_proc-filter-families");
            }
            return effect.fill ? FillGap(project, *effect.fill, effect.uid) : std::nullopt;
    }
    return std::nullopt;
}

}  // namespace

std::string SupportGap::Describe() const {
    return "node=" + std::to_string(node) + ": " + feature + " is a release gap (" + owner + ")";
}

std::optional<SupportGap> NodeGap(const core::Project& project, core::Id uid) {
    Gap found;
    bool seen = false;
    core::ForEachNode(project, [&](const core::NodeVisit& visit) {
        if (seen) return;
        if (visit.layer != nullptr && visit.layer->uid == uid) {
            seen = true;
            found = LayerGap(project, *visit.layer);
        } else if (visit.effect != nullptr && visit.effect->uid == uid) {
            seen = true;
            found = EffectGap(project, *visit.effect, visit.owner_stack);
        }
    });
    return found;
}

std::optional<SupportGap> FirstNewGap(const core::Project& before, const core::Project& after) {
    if (!LegacyColour(after) && after.settings.color_management.mode != before.settings.color_management.mode) {
        return Make(core::kNoId, "colour management mode '" + after.settings.color_management.mode + "'",
                    "phase1.20_pyapi-facade");
    }
    const core::ChangeSet changes = core::Diff(before, after);
    std::vector<core::Id> touched = changes.created;
    touched.insert(touched.end(), changes.modified.begin(), changes.modified.end());
    std::sort(touched.begin(), touched.end());
    for (const core::Id uid : touched) {
        if (Gap gap = NodeGap(after, uid)) return gap;
    }
    return std::nullopt;
}

void RequireSupported(const core::Project& before, const core::Project& after) {
    if (const Gap gap = FirstNewGap(before, after)) throw core::NotYetSupported(gap->Describe());
}

}  // namespace uzp::evaluator
