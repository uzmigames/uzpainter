#include "evaluator/dag.h"

#include <bit>
#include <string>

#include "evaluator/arith.h"
#include "evaluator/cpu_store.h"
#include "evaluator/error.h"
#include "evaluator/sources.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/json.h"

namespace uzp::evaluator {

namespace {

using core::BlendingMode;
using core::ChannelType;
using core::Layer;
using core::LayerKind;

struct Context {
    const core::Project& project;
    std::string_view profile;
    const core::TextureSet& set;
    const core::Stack& stack;
    ChannelType channel;
    TileFormat tileFormat;
    core::ChannelFormat format;
    std::array<float, 3> base;
    TileGrid grid;
    int depth = 0;
    /// The profile's `float32UniformPlain` (UniformOperand).
    bool float32UniformPlain = false;
    /// The profile's `uniformGreyUnrounded` (UniformOperand).
    bool uniformGreyUnrounded = false;
};

constexpr int kMaxInstanceDepth = 64;

/// The seed of every subtree hash: the project's profile, kind, channel, format and the set
/// resolution (tiles of two profiles never serve each other; a tile
/// of one resolution never serves another: the grid decides the tiles' sizes and, for projected
/// bitmaps, their texel centres).
Digest ContentStartHash(const Context& ctx, std::string_view what) {
    HashWriter writer;
    writer.Str(ctx.profile).Str(what).U32(static_cast<uint32_t>(ctx.channel));
    writer.U32(static_cast<uint32_t>(ctx.format));
    writer.U32(ctx.grid.width).U32(ctx.grid.height);
    return writer.Finish();
}

/// What the texturing mesh of `project` is derived from (`mesh::RederiveMesh`): the mesh file and
/// its import report but the report's `source` (the file's name and size beside its hash, the
/// resource). The report holds what else the derivation reads and gives: the stored files beside
/// the mesh (a glTF's external buffers, `kMeshExternalFiles`, by hash), the import settings
/// (`units`, `merged_materials`), the objects and materials a geometry mask selects by name and the
/// geometry hashes the derivation is checked against. So two meshes that share a file but not its
/// buffers or settings never share a geometry mask (decision 253).
void MeshIdentity(HashWriter& writer, const core::Project& project) {
    if (!project.mesh) {
        writer.Str(std::string());
        return;
    }
    writer.Str(project.mesh->resource);
    for (const auto& [name, value] : project.mesh->import_report) {
        if (name != "source") writer.Str(name).Str(core::json::WriteCanonical(value));
    }
}

/// The seed of a mask's hashes: the profile and the set resolution. A mask does not depend on the
/// channel, so every channel of a layer shares its mask tiles.
Digest MaskStartHash(const Context& ctx) {
    HashWriter writer;
    writer.Str(ctx.profile).Str("mask").U32(static_cast<uint32_t>(kMaskFormat));
    writer.U32(ctx.grid.width).U32(ctx.grid.height);
    return writer.Finish();
}

/// A fill (a layer or a fill effect) source for the channel, or, with `mask`, for a mask (the
/// mono value stored at 16 bits; a uniform colour takes the mean of its components).
render::Result<DagSource> ResolveSource(const Context& ctx, const core::FillContent& fill,
                                        const core::Source& source, core::Id uid, bool mask) {
    if (fill.projection.mode != core::ProjectionMode::Fill &&
        fill.projection.mode != core::ProjectionMode::UV) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        std::string(core::ToString(fill.projection.mode)) +
                            " projection is outside this profile (P3-SMART / P4-NODES)",
                        uid);
    }
    if (fill.symmetry.enabled) {
        return EvalFail(EvalErrorKind::UnsupportedSource, "symmetry is a release gap (P3-SMART)", uid);
    }
    render::Result<void> colour = CheckColourManagement(ctx.project, uid);
    if (!colour) return render::Unexpected(colour.error());
    DagSource result;
    HashWriter writer;
    writer.Sub(mask ? MaskStartHash(ctx) : ContentStartHash(ctx, "content"));
    switch (source.kind()) {
        case core::SourceKind::uniform_color: {
            const auto& uniform = std::get<core::UniformColorSource>(source.value);
            result.kind = DagSource::Kind::Uniform;
            result.uniform = mask ? UniformOperand(uniform.rgb, TileFormatOf(kMaskFormat), {0.0f, 0.0f, 0.0f})
                                  : UniformOperand(uniform.rgb, ctx.tileFormat, ctx.base, ctx.float32UniformPlain,
                                                   ctx.uniformGreyUnrounded);
            writer.Str("uniform");
            for (const float component : result.uniform) writer.F32(component);
            break;
        }
        case core::SourceKind::bitmap: {
            const auto& bitmap = std::get<core::BitmapSource>(source.value);
            if (bitmap.resource.sha256.empty()) {
                return EvalFail(EvalErrorKind::MissingResource, "a bitmap source without a hash", uid);
            }
            render::Result<UvProjection> projection = UvProjectionOf(fill.projection, uid);
            if (!projection) return render::Unexpected(projection.error());
            result.kind = DagSource::Kind::Bitmap;
            result.sha256 = bitmap.resource.sha256;
            result.projection = *projection;
            result.signedRange = !mask && ctx.channel == ChannelType::Height;
            result.greyTexture =
                mask || ctx.format == core::ChannelFormat::L8 || ctx.format == core::ChannelFormat::L16F;
            if (!mask && ctx.channel == ChannelType::Normal) {
                // The Normal channel stores an imported normal map with its green codes inverted
                // in OpenGL and DirectX projects alike (blend-modes.json
                // `blend-normal-channel-import`; height-to-normal.json
                // `height-normal-channel-import`: a DirectX project's export of the channel
                // inverts the stored green again); a grey bitmap is not inverted (decision 226).
                result.invertGreen = true;
                result.p20aNormal = ctx.format == core::ChannelFormat::RGB16F &&
                                    ctx.project.settings.normal_map_format == core::NormalMapFormat::OpenGL;
            }
            switch (BitmapColourSpaceOf(bitmap.color_space)) {
                case BitmapColourSpace::Linear: break;
                case BitmapColourSpace::Srgb:
                    // sRGB8 channels, and an L8 BaseColor, Specular or Emissive (its image checked at
                    // evaluation); Painter refuses the space on other user channels and on a mask's source,
                    // and on any other channel it is not recorded (sources.h).
                    if (!mask && SrgbL8MaterialChannel(ctx.channel, ctx.format)) {
                        result.l8Material = true;
                    } else if (mask || (!ctx.tileFormat.srgb && core::ToString(ctx.channel).starts_with("User"))) {
                        return EvalFail(EvalErrorKind::UnsupportedSource,
                                        "an sRGB bitmap on a user channel that is not sRGB8 or as a mask source: "
                                        "Painter refuses the space there (decision 174)",
                                        uid);
                    } else if (!ctx.tileFormat.srgb) {
                        return EvalFail(EvalErrorKind::UnsupportedSource,
                                        "an sRGB bitmap on the " + std::string(core::ToString(ctx.format)) + " channel " +
                                            std::string(core::ToString(ctx.channel)) +
                                            " is not recorded (Painter reads one decoded on sRGB8 channels and on an L8 "
                                            "BaseColor, Specular or Emissive; phase1.15_compositor-colour-fits, decision 208)",
                                        uid);
                    }
                    result.srgbDecode = true;
                    break;
                case BitmapColourSpace::Unrecorded:
                    return EvalFail(EvalErrorKind::UnsupportedSource,
                                    "the bitmap colour space '" + bitmap.color_space +
                                        "' is not recorded (phase1.15_compositor-colour-fits)",
                                    uid);
            }
            if (PainterOcio(ctx.project)) {
                // Session O records three bitmap uses under OCIO (sources.h, decision 190).
                if (mask) {
                    result.ocio = DagSource::Ocio::Grey16Mask;
                } else if (ctx.tileFormat.srgb && result.srgbDecode) {
                    result.ocio = DagSource::Ocio::Srgb8Fill;
                } else if (ctx.tileFormat.srgb && bitmap.color_space == "Raw") {
                    result.ocio = DagSource::Ocio::Raw8Fill;
                } else {
                    return EvalFail(EvalErrorKind::UnsupportedSource,
                                    "under OCIO, a bitmap in the colour space '" + bitmap.color_space +
                                        "' on the channel " + std::string(core::ToString(ctx.channel)) +
                                        " is not recorded (Session O records sRGB and Raw on an sRGB8 channel; "
                                        "phase1.15_compositor-colour-fits, decision 190)",
                                    uid);
                }
            }
            // Bound by content hash (LAY-13: the alias plays no part); the linear colour spaces
            // give the same samples (sources.h).
            writer.Str("bitmap").Str(result.sha256);
            if (result.srgbDecode) writer.Str("srgb");
            // What the Normal channel admits depends on the project's normal convention, which the
            // start hash does not hold (evaluate.cpp CheckNormalTexture, decision 249).
            if (result.invertGreen) writer.Str("normal").U32(result.p20aNormal ? 1u : 0u);
            // The OCIO use is checked when its content tile is made (evaluate.cpp CheckOcioBitmap):
            // a tile cached under legacy or under another use never serves it.
            if (result.ocio != DagSource::Ocio::None) writer.Str("ocio").U32(static_cast<uint32_t>(result.ocio));
            writer.U32(static_cast<uint32_t>(result.projection.filter));
            writer.U32(static_cast<uint32_t>(result.projection.wrap));
            for (const double value : {result.projection.cosR, result.projection.sinR,
                                       result.projection.scale[0], result.projection.scale[1],
                                       result.projection.offset[0], result.projection.offset[1]}) {
                writer.U64(std::bit_cast<uint64_t>(value));
            }
            break;
        }
        case core::SourceKind::vector:
        case core::SourceKind::font:
        case core::SourceKind::procedural:
        case core::SourceKind::reference:
            return EvalFail(EvalErrorKind::UnsupportedSource,
                            std::string(core::ToString(source.kind())) +
                                " sources are outside this profile (P3-PROC / P4-NODES)",
                            uid);
    }
    result.hash = writer.Finish();
    return result;
}

render::Result<std::optional<DagSource>> SourceOf(const Context& ctx, const Layer& layer) {
    const core::FillContent& fill = *layer.fill;
    if (fill.source_mode == core::SourceMode::Material) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "Material source mode is a release gap (P3-PROC)", layer.uid);
    }
    if (!fill.active_channels.contains(ctx.channel)) return std::optional<DagSource>{};
    const auto sourceIt = fill.sources.find(ctx.channel);
    if (sourceIt == fill.sources.end()) return std::optional<DagSource>{};
    render::Result<DagSource> source = ResolveSource(ctx, fill, sourceIt->second, layer.uid, false);
    if (!source) return render::Unexpected(source.error());
    return std::optional<DagSource>{std::move(*source)};
}

/// The float32 parameters Painter stores for one levels component.
arith::LevelsComponent LevelsOf(const core::LevelsComponent& c) {
    return {static_cast<float>(c.input_min), static_cast<float>(c.input_max),
            static_cast<float>(c.gamma),     static_cast<float>(c.output_min),
            static_cast<float>(c.output_max), c.clamp};
}

/// The failure of an effect kind outside this profile.
render::Unexpected UnsupportedEffect(const core::Effect& effect, bool mask) {
    std::string owner;
    switch (effect.kind) {
        case core::EffectKind::generator:
        case core::EffectKind::filter: owner = "P3-PROC"; break;
        case core::EffectKind::paint:
        case core::EffectKind::compare_mask:
        case core::EffectKind::color_selection:
        case core::EffectKind::anchor: owner = "P4-NODES"; break;
        case core::EffectKind::fill:
        case core::EffectKind::levels: owner = "phase1.11_compositor-mask-effects"; break;
    }
    return EvalFail(EvalErrorKind::UnsupportedNode,
                    std::string(core::ToString(effect.kind)) + " effects in " +
                        (mask ? "mask" : "content") + " stacks are outside this profile (" + owner + ")",
                    effect.uid);
}

/// Why a content filter effect is not the one recorded configuration of the starter-asset Blur
/// (DagEffect::Kind::RecordedBlur, decision 346), or empty when it is. Every other filter, Blur
/// parameter, blending, channel format, resolution and colour management stays outside the
/// profile: nothing else is evaluated as the content rounded to binary16.
std::optional<std::string> RecordedBlurRefusal(const Context& ctx, const core::Effect& effect) {
    const std::string owner = " (phase3.2_proc-filter-families item 2.5, decision 346)";
    if (!effect.procedural || effect.procedural->asset != kRecordedBlurAsset) {
        return "filter effects in content stacks are outside this profile (P3-PROC)";
    }
    const core::ProceduralRef& ref = *effect.procedural;
    if (!ref.params.empty() || ref.preset || !ref.image_inputs.empty() || !ref.output_mapping.empty() ||
        ref.mask_output || ref.resolution_override) {
        return "the Blur filter with parameters, a preset, inputs, an output mapping or a resolution "
               "override is not recorded" + owner;
    }
    const auto blendIt = effect.blending.find(ctx.channel);
    const core::Blending blending = blendIt == effect.blending.end() ? core::Blending{} : blendIt->second;
    if (blending.mode != BlendingMode::Normal || blending.opacity != 1.0) {
        return "the Blur filter blended other than Normal at opacity 1 is not recorded" + owner;
    }
    if (ctx.format != core::ChannelFormat::RGB16 && ctx.format != core::ChannelFormat::sRGB8) {
        return std::string("the Blur filter on a ") + std::string(core::ToString(ctx.format)) +
               " channel is not recorded" + owner;
    }
    if (ctx.grid.width != kRecordedBlurResolution || ctx.grid.height != kRecordedBlurResolution) {
        return "the Blur filter at " + std::to_string(ctx.grid.width) + " x " + std::to_string(ctx.grid.height) +
               " is not recorded" + owner;
    }
    const std::string& colour = ctx.project.settings.color_management.mode;
    if (!colour.empty() && colour != "legacy") {
        return "the Blur filter under colour management '" + colour + "' is not recorded" + owner;
    }
    return std::nullopt;
}

/// Appends `effect` to `chain` with its hash chained from `previous`.
void Chain(DagEffect& effect, const Digest& previous, std::vector<DagEffect>& chain) {
    HashWriter writer;
    writer.Sub(previous).U64(effect.uid).U32(static_cast<uint32_t>(effect.kind));
    if (effect.kind == DagEffect::Kind::Fill) {
        writer.Str("fill").U32(static_cast<uint32_t>(effect.mode)).F32(effect.opacity);
        writer.Sub(effect.source->hash);
    } else if (effect.kind == DagEffect::Kind::RecordedBlur) {
        writer.Str("filter").Str(kRecordedBlurAsset);
    } else {
        writer.Str("levels");
        for (const arith::LevelsComponent& c : effect.levels) {
            writer.F32(c.inMin).F32(c.inMax).F32(c.gamma).F32(c.outMin).F32(c.outMax);
            writer.U32(c.clamp ? 1u : 0u);
        }
    }
    effect.hash = writer.Finish();
    chain.push_back(std::move(effect));
}

/// The content effects of a fill layer that touch the channel, bottom-up, chained from the
/// source's hash. Storage keeps Painter's top-first order.
render::Result<std::vector<DagEffect>> ContentEffectsOf(const Context& ctx, const Layer& layer,
                                                        const Digest& start) {
    std::vector<DagEffect> chain;
    for (auto it = layer.content_effects.rbegin(); it != layer.content_effects.rend(); ++it) {
        const core::Effect& effect = *it;
        if (!effect.visible) continue;
        DagEffect node;
        node.uid = effect.uid;
        if (effect.kind == core::EffectKind::fill) {
            if (!effect.fill) return EvalFail(EvalErrorKind::Internal, "a fill effect without content", effect.uid);
            const core::FillContent& fill = *effect.fill;
            if (fill.source_mode == core::SourceMode::Material) {
                return EvalFail(EvalErrorKind::UnsupportedSource,
                                "Material source mode is a release gap (P3-PROC)", effect.uid);
            }
            if (!fill.active_channels.contains(ctx.channel)) continue;
            const auto sourceIt = fill.sources.find(ctx.channel);
            if (sourceIt == fill.sources.end()) continue;
            const auto blendIt = effect.blending.find(ctx.channel);
            const core::Blending blending = blendIt == effect.blending.end() ? core::Blending{} : blendIt->second;
            if (blending.mode == BlendingMode::Disable) continue;
            if (!arith::HasKernel(blending.mode)) {
                return EvalFail(EvalErrorKind::UnsupportedBlendMode,
                                std::string(core::ToString(blending.mode)) + " has no blend kernel",
                                effect.uid);
            }
            render::Result<DagSource> source = ResolveSource(ctx, fill, sourceIt->second, effect.uid, false);
            if (!source) return render::Unexpected(source.error());
            node.kind = DagEffect::Kind::Fill;
            node.mode = blending.mode;
            node.opacity = static_cast<float>(blending.opacity);
            node.source = std::move(*source);
        } else if (effect.kind == core::EffectKind::levels) {
            if (!effect.levels || effect.levels->components.empty()) {
                return EvalFail(EvalErrorKind::Internal, "a levels effect without parameters", effect.uid);
            }
            if (!effect.levels->affected_channel) {
                return EvalFail(EvalErrorKind::UnsupportedNode,
                                "a content levels effect without an affected channel", effect.uid);
            }
            if (*effect.levels->affected_channel != ctx.channel) continue;
            node.kind = DagEffect::Kind::Levels;
            const std::vector<core::LevelsComponent>& components = effect.levels->components;
            for (size_t c = 0; c < 3; ++c) {
                node.levels[c] = LevelsOf(components[components.size() == 3 ? c : 0]);
            }
        } else if (effect.kind == core::EffectKind::filter) {
            // Any filter but the recorded Blur stays outside the profile whatever its channels.
            if (!effect.procedural || effect.procedural->asset != kRecordedBlurAsset) {
                return EvalFail(EvalErrorKind::UnsupportedNode,
                                "filter effects in content stacks are outside this profile (P3-PROC)", effect.uid);
            }
            if (!effect.active_channels.contains(ctx.channel)) continue;
            if (std::optional<std::string> refusal = RecordedBlurRefusal(ctx, effect)) {
                return EvalFail(EvalErrorKind::UnsupportedNode, *refusal, effect.uid);
            }
            node.kind = DagEffect::Kind::RecordedBlur;
        } else {
            return UnsupportedEffect(effect, false);
        }
        Chain(node, chain.empty() ? start : chain.back().hash, chain);
    }
    return chain;
}

/// The mask of `layer`: a constant (`constant`, with no `DagMask`) or a `DagMask`. A missing or
/// disabled mask counts as 1; a mask without effects is its background; a `Mesh` geometry mask
/// multiplies the result.
render::Result<std::optional<DagMask>> MaskOf(const Context& ctx, const Layer& layer, float& constant) {
    constant = 1.0f;
    const core::GeometryMask& geometry = layer.geometry_mask;
    const bool geometryApplies = geometry.inclusion_list || !geometry.items.empty();
    if (geometryApplies && geometry.type == core::GeometryMaskType::UVTile) {
        return EvalFail(EvalErrorKind::UnsupportedNode,
                        "UVTile geometry masks are a release gap (UV-tile workflow)", layer.uid);
    }
    DagMask mask;
    if (layer.mask && layer.mask->enabled) {
        mask.background = layer.mask->background == core::MaskBackground::White ? 1.0f : 0.0f;
        constant = mask.background;
        HashWriter start;
        start.Sub(MaskStartHash(ctx)).F32(mask.background);
        const Digest startHash = start.Finish();
        const std::vector<core::Effect>& effects = layer.mask->effects;
        for (auto it = effects.rbegin(); it != effects.rend(); ++it) {
            const core::Effect& effect = *it;
            if (!effect.visible) continue;
            DagEffect node;
            node.uid = effect.uid;
            if (effect.kind == core::EffectKind::fill) {
                if (!effect.fill) return EvalFail(EvalErrorKind::Internal, "a fill effect without content", effect.uid);
                if (!effect.fill->mono_source) continue;
                const core::Blending blending = effect.mono_blending.value_or(core::Blending{});
                if (blending.mode == BlendingMode::Disable) continue;
                if (!arith::HasKernel(blending.mode)) {
                    return EvalFail(EvalErrorKind::UnsupportedBlendMode,
                                    std::string(core::ToString(blending.mode)) + " has no blend kernel",
                                    effect.uid);
                }
                render::Result<DagSource> source =
                    ResolveSource(ctx, *effect.fill, *effect.fill->mono_source, effect.uid, true);
                if (!source) return render::Unexpected(source.error());
                node.kind = DagEffect::Kind::Fill;
                node.mode = blending.mode;
                node.opacity = static_cast<float>(blending.opacity);
                node.source = std::move(*source);
            } else if (effect.kind == core::EffectKind::levels) {
                if (!effect.levels || effect.levels->components.empty()) {
                    return EvalFail(EvalErrorKind::Internal, "a levels effect without parameters", effect.uid);
                }
                node.kind = DagEffect::Kind::Levels;
                for (arith::LevelsComponent& c : node.levels) c = LevelsOf(effect.levels->components[0]);
            } else {
                return UnsupportedEffect(effect, true);
            }
            Chain(node, mask.effects.empty() ? startHash : mask.effects.back().hash, mask.effects);
        }
        mask.hash = mask.effects.empty() ? startHash : mask.effects.back().hash;
    } else {
        HashWriter start;
        start.Sub(MaskStartHash(ctx)).F32(1.0f);
        mask.hash = start.Finish();
    }
    if (geometryApplies) {
        DagGeometry g;
        g.query.material = ctx.set.material_id;
        g.query.inclusionList = geometry.inclusion_list;
        g.query.items = geometry.items;
        g.query.width = ctx.grid.width;
        g.query.height = ctx.grid.height;
        HashWriter writer;
        writer.Str("geometry");
        MeshIdentity(writer, ctx.project);
        writer.Str(g.query.material).U32(g.query.inclusionList ? 1u : 0u);
        writer.U32(static_cast<uint32_t>(g.query.items.size()));
        for (const std::string& item : g.query.items) writer.Str(item);
        writer.U32(g.query.width).U32(g.query.height);
        g.hash = writer.Finish();
        HashWriter combined;
        combined.Sub(mask.hash).Sub(g.hash);
        mask.hash = combined.Finish();
        mask.geometry = std::move(g);
    }
    if (mask.effects.empty() && !mask.geometry) return std::optional<DagMask>{};
    return std::optional<DagMask>{std::move(mask)};
}

render::Result<void> AppendLayers(Context& ctx, const std::vector<Layer>& layersTopFirst,
                                  DagList& list);

/// Appends `layer` (visible, contributing) to `list`.
render::Result<void> AppendLayer(Context& ctx, const Layer& layer, DagList& list) {
    if (!layer.visible) return {};
    if (!layer.content_effects.empty() && layer.kind == LayerKind::group) {
        return EvalFail(EvalErrorKind::UnsupportedNode, "a group has no content stack", layer.uid);
    }
    const core::Blending blending = EffectiveBlending(layer, ctx.channel);
    if (blending.mode == BlendingMode::Disable) return {};
    if (layer.kind == LayerKind::paint) {
        // An empty paint layer (no plane, no content effect) is transparent and contributes
        // nothing, whatever its mode, opacity and mask: Painter's empty "Layer 1" sits under every
        // Tier 0 golden (decision 348). Plane content is outside this profile.
        if (!core::IsEmptyPaintLayer(layer)) {
            return EvalFail(EvalErrorKind::UnsupportedNode,
                            "paint plane content and content effects on a paint layer are outside this profile "
                            "(phase4.1_nodes-paint-layers)",
                            layer.uid);
        }
        return {};
    }
    float constantMask = 1.0f;
    render::Result<std::optional<DagMask>> mask = MaskOf(ctx, layer, constantMask);
    if (!mask) return render::Unexpected(mask.error());

    if (layer.kind == LayerKind::instance) {
        if (ctx.depth >= kMaxInstanceDepth) {
            return EvalFail(EvalErrorKind::UnsupportedNode, "instance chain too deep", layer.uid);
        }
        const Layer* source = core::FindLayer(ctx.stack, layer.instance_source);
        if (source == nullptr) {
            return EvalFail(EvalErrorKind::NotFound,
                            "instance source " + std::to_string(layer.instance_source) +
                                " is not in the stack",
                            layer.uid);
        }
        ++ctx.depth;
        render::Result<void> ok = AppendLayer(ctx, *source, list);
        --ctx.depth;
        return ok;
    }

    DagLayer node;
    node.uid = layer.uid;
    node.mode = blending.mode;
    node.opacity = static_cast<float>(blending.opacity);
    node.mask = constantMask;
    node.maskStack = std::move(*mask);
    HashWriter writer;
    writer.U64(layer.uid).U32(static_cast<uint32_t>(node.mode)).F32(node.opacity).F32(node.mask);
    if (node.maskStack) writer.Str("mask").Sub(node.maskStack->hash);

    switch (layer.kind) {
        case LayerKind::fill: {
            if (!layer.fill) {
                return EvalFail(EvalErrorKind::Internal, "a fill layer without content", layer.uid);
            }
            render::Result<std::optional<DagSource>> source = SourceOf(ctx, layer);
            if (!source) return render::Unexpected(source.error());
            if (!*source) return {};
            if (!arith::HasKernel(node.mode)) {
                return EvalFail(EvalErrorKind::UnsupportedBlendMode,
                                std::string(core::ToString(node.mode)) +
                                    " has no blend kernel (a group placement)",
                                layer.uid);
            }
            render::Result<std::vector<DagEffect>> effects = ContentEffectsOf(ctx, layer, (**source).hash);
            if (!effects) return render::Unexpected(effects.error());
            writer.Str("fill").Sub(effects->empty() ? (**source).hash : effects->back().hash);
            node.source = std::move(*source);
            node.effects = std::move(*effects);
            break;
        }
        case LayerKind::group: {
            const bool passThrough = node.mode == BlendingMode::PassThrough;
            if (!passThrough && !arith::HasKernel(node.mode)) {
                return EvalFail(EvalErrorKind::UnsupportedBlendMode,
                                std::string(core::ToString(node.mode)) +
                                    " has no blend kernel (a group placement)",
                                layer.uid);
            }
            auto group = std::make_unique<DagList>();
            group->owner = layer.uid;
            if (passThrough) {
                // The children composite onto a copy of the accumulator below the group: their
                // chain starts from its prefix, in its format.
                group->isolated = list.isolated;
                group->fromBackdrop = true;
                HashWriter start;
                start.Str("passthrough").Sub(list.layers.empty() ? list.startHash : list.layers.back().prefixHash);
                group->startHash = start.Finish();
            } else {
                group->isolated = true;
                group->startHash = ContentStartHash(ctx, "group");
            }
            render::Result<void> ok = AppendLayers(ctx, layer.children, *group);
            if (!ok) return ok;
            if (group->layers.empty()) return {};  // nothing visible: a transparent group
            writer.Str("group").Sub(group->layers.back().prefixHash);
            node.group = std::move(group);
            break;
        }
        case LayerKind::paint:  // handled above
        case LayerKind::instance:
            break;  // handled above
    }
    node.hash = writer.Finish();
    HashWriter prefix;
    prefix.Sub(list.layers.empty() ? list.startHash : list.layers.back().prefixHash);
    prefix.Sub(node.hash);
    node.prefixHash = prefix.Finish();
    list.layers.push_back(std::move(node));
    return {};
}

render::Result<void> AppendLayers(Context& ctx, const std::vector<Layer>& layersTopFirst,
                                  DagList& list) {
    for (auto it = layersTopFirst.rbegin(); it != layersTopFirst.rend(); ++it) {
        render::Result<void> ok = AppendLayer(ctx, *it, list);
        if (!ok) return ok;
    }
    return {};
}

}  // namespace

core::Blending EffectiveBlending(const core::Layer& layer, core::ChannelType channel) {
    const auto it = layer.blending.find(channel);
    return it == layer.blending.end() ? core::Blending{} : it->second;
}

std::array<float, 3> UniformOperand(const std::array<double, 3>& colour, const TileFormat& format,
                                    const std::array<float, 3>& base, bool float32Plain,
                                    bool greyUnrounded) {
    std::array<float, 3> result{0.0f, 0.0f, 0.0f};
    std::array<double, 3> components;
    if (format.channels == 1) {
        const double r = greyUnrounded ? colour[0] : static_cast<float>(colour[0]);
        const double g = greyUnrounded ? colour[1] : static_cast<float>(colour[1]);
        const double b = greyUnrounded ? colour[2] : static_cast<float>(colour[2]);
        components = {(r + g + b) / 3.0, 0.0, 0.0};
    } else {
        components = colour;
    }
    for (uint32_t c = 0; c < format.channels; ++c) {
        const float value = static_cast<float>(components[c]);
        // A 32-bit float colour is its float32 value (`float32Plain`, profile.h), or, under the
        // earlier profiles, reads back as the channel would export it (blend-modes.json
        // `uniform_operand`: stored like a channel value, 1 + (v - 1) over the white base).
        const uint32_t stored = format.encoding != render::TexelEncoding::Float32
                                    ? StoreValue(value, format, c)
                                : float32Plain ? std::bit_cast<uint32_t>(arith::Float32Store(value))
                                               : std::bit_cast<uint32_t>(arith::Float32Readout(value, base[c]));
        result[c] = OperandOf(stored, format, c);
    }
    return result;
}

render::Result<ChannelDag> BuildDag(const core::Project& project, core::Id textureSet,
                                    core::Id stack, ChannelType channel,
                                    const TemplateLibrary& templates, std::string_view templateId) {
    const core::TextureSet* set = nullptr;
    for (const core::TextureSet& candidate : project.texture_sets) {
        if (candidate.id == textureSet) set = &candidate;
    }
    if (set == nullptr) {
        return EvalFail(EvalErrorKind::NotFound,
                        "texture set " + std::to_string(textureSet) + " is not in the project");
    }
    const core::Stack* stackPtr = core::FindStack(project, textureSet, stack);
    if (stackPtr == nullptr) {
        return EvalFail(EvalErrorKind::NotFound, "stack " + std::to_string(stack) +
                                                     " is not in texture set " +
                                                     std::to_string(textureSet));
    }
    const auto channelIt = stackPtr->channels.find(channel);
    if (channelIt == stackPtr->channels.end()) {
        return EvalFail(EvalErrorKind::NotFound, "channel " + std::string(core::ToString(channel)) +
                                                     " is not in stack " + std::to_string(stack));
    }
    render::Result<std::array<float, 3>> base = templates.BaseValue(templateId, channel, channelIt->second.format);
    if (!base) return render::Unexpected(base.error());
    render::Result<EvaluatorProfile> profile = FindProfile(project.versions.evaluator_profile);
    if (!profile) return render::Unexpected(profile.error());

    ChannelDag dag;
    dag.textureSet = textureSet;
    dag.stack = stack;
    dag.channel = channel;
    dag.format = channelIt->second.format;
    dag.tileFormat = TileFormatOf(dag.format);
    dag.base = *base;
    dag.readoutBase = channel == ChannelType::Normal ? std::array<float, 3>{0.5f, 0.5f, 1.0f} : *base;
    dag.grid = TileGrid{static_cast<uint32_t>(set->resolution.width),
                        static_cast<uint32_t>(set->resolution.height)};
    dag.templateId = std::string(templateId);
    dag.profile = std::move(*profile);
    dag.tileFormat.halfCoverage = dag.profile.srgb8HalfCoverage && dag.tileFormat.srgb;
    dag.tileFormat.halfCoverageFromHalf = dag.profile.srgb8HalfCoverageFromHalf && dag.tileFormat.halfCoverage;
    dag.root.owner = stack;
    dag.root.isolated = dag.profile.root == RootComposite::Isolated;
    Context ctx{project,        dag.profile.id, *set,     *stackPtr, channel,
                dag.tileFormat, dag.format,     dag.base, dag.grid};
    ctx.float32UniformPlain = dag.profile.float32UniformPlain;
    ctx.uniformGreyUnrounded = dag.profile.uniformGreyUnrounded;
    {
        HashWriter writer;
        writer.Sub(ContentStartHash(ctx, "root"));
        for (const float component : dag.base) writer.F32(component);
        dag.root.startHash = writer.Finish();
    }
    render::Result<void> ok = AppendLayers(ctx, stackPtr->root_layers, dag.root);
    if (!ok) return render::Unexpected(ok.error());
    if (channel == ChannelType::Normal && project.settings.normal_map_format != core::NormalMapFormat::OpenGL &&
        !dag.root.layers.empty()) {
        // A DirectX project's Normal channel is recorded as one bitmap fill in Normal mode at
        // opacity 1, without mask or effects (decision 079); other stacks are not.
        const DagLayer& only = dag.root.layers.front();
        const bool recorded = dag.root.layers.size() == 1 && !only.group && only.mode == core::BlendingMode::Normal &&
                              only.opacity == 1.0f && only.mask == 1.0f && !only.maskStack && only.effects.empty() &&
                              only.source && only.source->kind == DagSource::Kind::Bitmap;
        if (!recorded) {
            return EvalFail(EvalErrorKind::UnsupportedSource,
                            "a DirectX project's Normal channel is recorded as one bitmap fill in Normal mode at "
                            "opacity 1 without mask or effects only (phase1.12_compositor-height-normal)");
        }
    }
    if (dag.root.isolated && !dag.root.layers.empty()) {
        HashWriter writer;
        writer.Sub(dag.root.layers.back().prefixHash).Str("readout");
        dag.readoutHash = writer.Finish();
    }
    return dag;
}

render::Result<DagLayer> BuildLayerMask(const core::Project& project, const ChannelDag& frame, core::Id uid) {
    const core::TextureSet* set = nullptr;
    for (const core::TextureSet& candidate : project.texture_sets) {
        if (candidate.id == frame.textureSet) set = &candidate;
    }
    const core::Stack* stack = core::FindStack(project, frame.textureSet, frame.stack);
    if (set == nullptr || stack == nullptr) {
        return EvalFail(EvalErrorKind::NotFound, "stack " + std::to_string(frame.stack) +
                                                     " is not in texture set " +
                                                     std::to_string(frame.textureSet));
    }
    const Layer* layer = core::FindLayer(*stack, uid);
    if (layer == nullptr) {
        return EvalFail(EvalErrorKind::NotFound,
                        "layer " + std::to_string(uid) + " is not in stack " + std::to_string(frame.stack));
    }
    for (int depth = 0; layer->kind == LayerKind::instance; ++depth) {
        const Layer* source = depth < kMaxInstanceDepth ? core::FindLayer(*stack, layer->instance_source) : nullptr;
        if (source == nullptr) {
            return EvalFail(EvalErrorKind::NotFound,
                            "instance source " + std::to_string(layer->instance_source) + " is not in the stack",
                            layer->uid);
        }
        layer = source;
    }
    Context ctx{project,          frame.profile.id, *set,       *stack,    frame.channel,
                frame.tileFormat, frame.format,     frame.base, frame.grid};
    DagLayer node;
    node.uid = layer->uid;
    render::Result<std::optional<DagMask>> mask = MaskOf(ctx, *layer, node.mask);
    if (!mask) return render::Unexpected(mask.error());
    node.maskStack = std::move(*mask);
    return node;
}

}  // namespace uzp::evaluator
