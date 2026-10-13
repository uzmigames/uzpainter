#include "evaluator/support.h"

#include <algorithm>
#include <vector>

#include "evaluator/sources.h"
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

/// Legacy colour management, or OCIO with Painter's substance config (sources.h, decision 190).
bool LegacyColour(const core::Project& project) {
    const std::string& mode = project.settings.color_management.mode;
    return mode.empty() || mode == "legacy" || PainterOcio(project);
}

/// Under OCIO with Painter's substance config, a bitmap whose use Session O does not record
/// (sources.h): only sRGB and Raw on an sRGB8 channel, and a linear space as a mask source. The
/// image's kind and its 1:1 sampling are checked at evaluation.
Gap OcioBitmapGap(const core::Project& project, const core::Stack* stack, const core::BitmapSource& bitmap,
                  std::optional<ChannelType> channel, core::Id node) {
    if (!PainterOcio(project)) return std::nullopt;
    const BitmapColourSpace space = BitmapColourSpaceOf(bitmap.color_space);
    if (!channel) {
        if (space == BitmapColourSpace::Linear) return std::nullopt;
    } else if (stack != nullptr) {
        const auto it = stack->channels.find(*channel);
        if (it == stack->channels.end()) return std::nullopt;
        if (it->second.format == core::ChannelFormat::sRGB8 &&
            (space == BitmapColourSpace::Srgb || bitmap.color_space == "Raw")) {
            return std::nullopt;
        }
    } else {
        return std::nullopt;
    }
    return Make(node,
                "under OCIO, a bitmap in the colour space '" + bitmap.color_space + "' " +
                    (channel ? "on the channel " + std::string(core::ToString(*channel)) : std::string("as a mask source")),
                "phase1.15_compositor-colour-fits");
}

/// The fill content of the node of `visit` (a fill layer or a fill effect), or nullptr.
const core::FillContent* FillOf(const core::NodeVisit& visit) {
    if (visit.layer != nullptr) return visit.layer->fill ? &*visit.layer->fill : nullptr;
    return visit.effect->fill ? &*visit.effect->fill : nullptr;
}

core::Id UidOf(const core::NodeVisit& visit) { return visit.layer != nullptr ? visit.layer->uid : visit.effect->uid; }

/// Under OCIO with Painter's substance config, a bitmap of the fill of `visit`'s node whose image
/// is not a use Session O records (sources.h `OcioBitmapRecorded`): the image's kind and its 1:1
/// sampling on the node's texture set in `project`, read from its PNG header as the evaluation
/// checks them (evaluate.cpp `CheckOcioBitmap`). Bitmaps whose bytes `shapes` does not have, and
/// channels the stack lacks, are left to the evaluation.
Gap OcioImageGap(const core::Project& project, const core::NodeVisit& visit, const BitmapShapes& shapes) {
    const core::FillContent* fill = FillOf(visit);
    if (!shapes || fill == nullptr || !PainterOcio(project)) return std::nullopt;
    const core::Id node = UidOf(visit);
    const core::Stack* stack = core::FindStack(project, visit.texture_set, visit.stack);
    const auto set = std::find_if(project.texture_sets.begin(), project.texture_sets.end(),
                                  [&](const core::TextureSet& s) { return s.id == visit.texture_set; });
    if (stack == nullptr || set == project.texture_sets.end()) return std::nullopt;
    const render::Result<UvProjection> projection = UvProjectionOf(fill->projection, node);
    if (!projection) return std::nullopt;  // FillGap refuses these projections
    const auto width = static_cast<uint32_t>(set->resolution.width);
    const auto height = static_cast<uint32_t>(set->resolution.height);
    const auto check = [&](const core::Source& source, std::optional<ChannelType> channel) -> Gap {
        if (source.kind() != SourceKind::bitmap) return std::nullopt;
        if (channel && !stack->channels.contains(*channel)) return std::nullopt;
        const std::optional<BitmapShape> shape = shapes(std::get<core::BitmapSource>(source.value).resource.sha256);
        if (!shape || OcioBitmapRecorded(!channel, *projection, width, height, *shape)) return std::nullopt;
        return Make(node,
                    "under OCIO, a " + std::to_string(shape->width) + "x" + std::to_string(shape->height) + " " +
                        (shape->encoding == render::TexelEncoding::Unorm16 ? "16" : "8") + "-bit " +
                        (shape->channels == 1 ? "grey" : "colour") + " bitmap " +
                        (channel ? "on the channel " + std::string(core::ToString(*channel))
                                 : std::string("as a mask source")) +
                        " of a " + std::to_string(width) + "x" + std::to_string(height) +
                        " texture set (Session O records " +
                        (channel ? "an 8-bit colour bitmap on an sRGB8 channel" : "a 16-bit grey mask source") +
                        " sampled 1:1 only)",
                    "phase1.15_compositor-colour-fits, decision 190");
    };
    for (const auto& [channel, source] : fill->sources) {
        if (Gap gap = check(source, channel)) return gap;
    }
    if (fill->mono_source) return check(*fill->mono_source, std::nullopt);
    return std::nullopt;
}

/// Every OCIO bitmap gap of the fill of `visit`'s node on its stack in `project`: its colour spaces
/// and channels (`OcioBitmapGap`), then its images (`OcioImageGap`).
Gap OcioGap(const core::Project& project, const core::NodeVisit& visit, const BitmapShapes& shapes) {
    const core::FillContent* fill = FillOf(visit);
    if (fill == nullptr || !PainterOcio(project)) return std::nullopt;
    const core::Stack* stack = core::FindStack(project, visit.texture_set, visit.stack);
    const auto bitmap = [&](const core::Source& source, std::optional<ChannelType> channel) -> Gap {
        if (source.kind() != SourceKind::bitmap) return std::nullopt;
        return OcioBitmapGap(project, stack, std::get<core::BitmapSource>(source.value), channel, UidOf(visit));
    };
    for (const auto& [channel, source] : fill->sources) {
        if (Gap gap = bitmap(source, channel)) return gap;
    }
    if (fill->mono_source) {
        if (Gap gap = bitmap(*fill->mono_source, std::nullopt)) return gap;
    }
    return OcioImageGap(project, visit, shapes);
}

/// The colour space of a bitmap source in `stack` for `channel` (sources.h): an sRGB bitmap
/// exists on sRGB8 channels and on an L8 BaseColor, Specular or Emissive (decision 208; the image's
/// kind and its 1:1 sampling are checked at evaluation). Painter refuses the space on a user
/// channel in any other format and on a mask's mono source (decision 174); on any other channel,
/// and for tags outside sources.h, it is not recorded. A channel the stack lacks is never
/// evaluated.
Gap BitmapColourSpaceGap(const core::Stack* stack, const core::BitmapSource& bitmap, std::optional<ChannelType> channel,
                         core::Id node) {
    switch (BitmapColourSpaceOf(bitmap.color_space)) {
        case BitmapColourSpace::Linear: return std::nullopt;
        case BitmapColourSpace::Srgb: {
            if (!channel) return Make(node, "an sRGB bitmap as a mask source (Painter refuses it)", "decision 174");
            if (stack == nullptr) return std::nullopt;
            const auto it = stack->channels.find(*channel);
            if (it == stack->channels.end() || it->second.format == core::ChannelFormat::sRGB8 ||
                SrgbL8MaterialChannel(*channel, it->second.format)) {
                return std::nullopt;
            }
            const std::string format(core::ToString(it->second.format));
            if (core::ToString(*channel).starts_with("User")) {
                return Make(node, "an sRGB bitmap on a " + format + " user channel (Painter refuses it)", "decision 174");
            }
            return Make(node,
                        "an sRGB bitmap on the " + format + " channel " + std::string(core::ToString(*channel)),
                        "phase1.15_compositor-colour-fits, decision 208");
        }
        case BitmapColourSpace::Unrecorded:
            return Make(node, "the bitmap colour space '" + bitmap.color_space + "'",
                        "phase1.15_compositor-colour-fits");
    }
    return std::nullopt;
}

/// A source of a fill (layer or fill effect) in `stack`, for `channel` (nullopt: a mask's mono
/// source).
Gap SourceGap(const core::Project& project, const core::Stack* stack, const core::Source& source,
              std::optional<ChannelType> channel, core::Id node) {
    switch (source.kind()) {
        case SourceKind::uniform_color:
            if (channel == ChannelType::Normal &&
                project.settings.normal_map_format != core::NormalMapFormat::OpenGL) {
                return Make(node, "a uniform colour on the Normal channel of a DirectX project",
                            "phase1.12_compositor-height-normal");
            }
            return std::nullopt;
        case SourceKind::bitmap: {
            const auto& bitmap = std::get<core::BitmapSource>(source.value);
            if (Gap gap = BitmapColourSpaceGap(stack, bitmap, channel, node)) return gap;
            return OcioBitmapGap(project, stack, bitmap, channel, node);
        }
        case SourceKind::vector: return Make(node, "a vector source", "phase4.1_nodes-vector-font-sources");
        case SourceKind::font: return Make(node, "a font source", "phase4.1_nodes-vector-font-sources");
        case SourceKind::procedural: return Make(node, "a procedural source", "phase3.3_procedural-families");
        case SourceKind::reference:
            return Make(node, "an anchor reference source", "phase4.1_nodes-instances-anchors");
    }
    return std::nullopt;
}

Gap FillGap(const core::Project& project, const core::Stack* stack, const core::FillContent& fill, core::Id node) {
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
                    "phase1.15_compositor-colour-fits");
    }
    for (const auto& [channel, source] : fill.sources) {
        if (Gap gap = SourceGap(project, stack, source, channel, node)) return gap;
    }
    if (fill.mono_source) return SourceGap(project, stack, *fill.mono_source, std::nullopt, node);
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

Gap LayerGap(const core::Project& project, const core::Stack* stack, const core::Layer& layer) {
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
    if (layer.kind == LayerKind::fill && layer.fill) return FillGap(project, stack, *layer.fill, layer.uid);
    return std::nullopt;
}

Gap EffectGap(const core::Project& project, const core::Stack* layers, const core::Effect& effect,
              core::NodeStack stack) {
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
            return effect.fill ? FillGap(project, layers, *effect.fill, effect.uid) : std::nullopt;
    }
    return std::nullopt;
}

}  // namespace

std::string SupportGap::Describe() const {
    return "node=" + std::to_string(node) + ": " + feature + " is a release gap (" + owner + ")";
}

std::optional<SupportGap> NodeGap(const core::Project& project, core::Id uid, const BitmapShapes& shapes) {
    Gap found;
    bool seen = false;
    core::ForEachNode(project, [&](const core::NodeVisit& visit) {
        if (seen) return;
        if (visit.layer != nullptr && visit.layer->uid == uid) {
            seen = true;
            found = LayerGap(project, core::FindStack(project, visit.texture_set, visit.stack), *visit.layer);
        } else if (visit.effect != nullptr && visit.effect->uid == uid) {
            seen = true;
            found = EffectGap(project, core::FindStack(project, visit.texture_set, visit.stack), *visit.effect,
                              visit.owner_stack);
        }
        if (seen && !found) found = OcioImageGap(project, visit, shapes);
    });
    return found;
}

std::optional<SupportGap> FirstNewGap(const core::Project& before, const core::Project& after,
                                      const BitmapShapes& shapes) {
    if (!LegacyColour(after) && after.settings.color_management.mode != before.settings.color_management.mode) {
        return Make(core::kNoId, "colour management mode '" + after.settings.color_management.mode + "'",
                    "phase1.15_compositor-colour-fits");
    }
    const core::ChangeSet changes = core::Diff(before, after);
    std::vector<core::Id> touched = changes.created;
    touched.insert(touched.end(), changes.modified.begin(), changes.modified.end());
    std::sort(touched.begin(), touched.end());
    for (const core::Id uid : touched) {
        if (Gap gap = NodeGap(after, uid, shapes)) return gap;
    }
    if (!PainterOcio(after)) return std::nullopt;
    // Under OCIO a set's resolution and channels decide whether its bitmaps are a recorded use: a
    // change of them refuses a use it makes unrecorded in a node it does not touch.
    const auto changed = [&before](const core::TextureSet& set) {
        for (const core::TextureSet& old : before.texture_sets) {
            if (old.id != set.id) continue;
            if (old.resolution != set.resolution || old.stacks.size() != set.stacks.size()) return true;
            for (std::size_t s = 0; s < set.stacks.size(); ++s) {
                if (old.stacks[s].channels != set.stacks[s].channels) return true;
            }
            return false;
        }
        return false;  // a created set: its nodes are created too
    };
    Gap found;
    core::ForEachNode(after, [&](const core::NodeVisit& visit) {
        if (found || std::binary_search(touched.begin(), touched.end(), UidOf(visit))) return;
        const auto set = std::find_if(after.texture_sets.begin(), after.texture_sets.end(),
                                      [&](const core::TextureSet& s) { return s.id == visit.texture_set; });
        if (set == after.texture_sets.end() || !changed(*set)) return;
        // The node is untouched, so `visit`'s fill is also its fill in `before`.
        if (Gap gap = OcioGap(after, visit, shapes); gap && !OcioGap(before, visit, shapes)) found = gap;
    });
    return found;
}

void RequireSupported(const core::Project& before, const core::Project& after, const BitmapShapes& shapes) {
    if (const Gap gap = FirstNewGap(before, after, shapes)) throw core::NotYetSupported(gap->Describe());
}

}  // namespace uzp::evaluator
