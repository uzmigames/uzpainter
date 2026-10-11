#include "evaluator/dag.h"

#include <bit>
#include <string>

#include "evaluator/arith.h"
#include "evaluator/cpu_store.h"
#include "evaluator/error.h"
#include "evaluator/sources.h"
#include "uzp_core/document/nodes.h"

namespace uzp::evaluator {

namespace {

using core::BlendingMode;
using core::ChannelType;
using core::Layer;
using core::LayerKind;

struct Context {
    const core::Project& project;
    const core::Stack& stack;
    ChannelType channel;
    TileFormat tileFormat;
    core::ChannelFormat format;
    std::array<float, 3> base;
    TileGrid grid;
    int depth = 0;
};

constexpr int kMaxInstanceDepth = 64;

/// The seed of every subtree hash: profile, kind, channel, format and the set resolution (a tile
/// of one resolution never serves another: the grid decides the tiles' sizes and, for projected
/// bitmaps, their texel centres).
Digest ContentStartHash(const Context& ctx, std::string_view what) {
    HashWriter writer;
    writer.Str(kEvaluatorProfile).Str(what).U32(static_cast<uint32_t>(ctx.channel));
    writer.U32(static_cast<uint32_t>(ctx.format));
    writer.U32(ctx.grid.width).U32(ctx.grid.height);
    return writer.Finish();
}

/// The blending of `layer` for the channel: the per-channel entry or the default (Normal, 1).
core::Blending BlendingOf(const Layer& layer, ChannelType channel) {
    const auto it = layer.blending.find(channel);
    return it == layer.blending.end() ? core::Blending{} : it->second;
}

render::Result<float> MaskOf(const Layer& layer) {
    if (!layer.geometry_mask.items.empty()) {
        return EvalFail(EvalErrorKind::UnsupportedNode,
                        "geometry masks are evaluated by phase1.11_compositor-mask-effects",
                        layer.uid);
    }
    if (!layer.mask || !layer.mask->enabled) return 1.0f;
    if (!layer.mask->effects.empty()) {
        return EvalFail(EvalErrorKind::UnsupportedNode,
                        "mask effects are evaluated by phase1.11_compositor-mask-effects",
                        layer.uid);
    }
    return layer.mask->background == core::MaskBackground::White ? 1.0f : 0.0f;
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
    if (fill.projection.mode != core::ProjectionMode::Fill &&
        fill.projection.mode != core::ProjectionMode::UV) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        std::string(core::ToString(fill.projection.mode)) +
                            " projection is outside this profile (P3-SMART / P4-NODES)",
                        layer.uid);
    }
    if (fill.symmetry.enabled) {
        return EvalFail(EvalErrorKind::UnsupportedSource, "symmetry is a release gap (P3-SMART)",
                        layer.uid);
    }
    render::Result<void> colour = CheckColourManagement(ctx.project, layer.uid);
    if (!colour) return render::Unexpected(colour.error());
    const core::Source& source = sourceIt->second;
    DagSource result;
    HashWriter writer;
    writer.Sub(ContentStartHash(ctx, "content"));
    switch (source.kind()) {
        case core::SourceKind::uniform_color: {
            const auto& uniform = std::get<core::UniformColorSource>(source.value);
            result.kind = DagSource::Kind::Uniform;
            result.uniform = UniformOperand(uniform.rgb, ctx.tileFormat, ctx.base);
            writer.Str("uniform");
            for (const float component : result.uniform) writer.F32(component);
            break;
        }
        case core::SourceKind::bitmap: {
            const auto& bitmap = std::get<core::BitmapSource>(source.value);
            if (bitmap.resource.sha256.empty()) {
                return EvalFail(EvalErrorKind::MissingResource, "a bitmap source without a hash",
                                layer.uid);
            }
            render::Result<UvProjection> projection = UvProjectionOf(fill.projection, layer.uid);
            if (!projection) return render::Unexpected(projection.error());
            result.kind = DagSource::Kind::Bitmap;
            result.sha256 = bitmap.resource.sha256;
            result.projection = *projection;
            result.signedRange = ctx.channel == ChannelType::Height;
            // Bound by content hash (LAY-13): the alias and, under legacy colour management, the
            // colour-space tag do not change the samples (sources.h).
            writer.Str("bitmap").Str(result.sha256);
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
                            layer.uid);
    }
    result.hash = writer.Finish();
    return std::optional<DagSource>{std::move(result)};
}

render::Result<void> AppendLayers(Context& ctx, const std::vector<Layer>& layersTopFirst,
                                  DagList& list, float opacityScale, float maskScale);

/// Appends `layer` (visible, contributing) to `list`.
render::Result<void> AppendLayer(Context& ctx, const Layer& layer, DagList& list,
                                 float opacityScale, float maskScale) {
    if (!layer.visible) return {};
    if (!layer.content_effects.empty()) {
        return EvalFail(EvalErrorKind::UnsupportedNode,
                        "content effects are evaluated by phase1.11_compositor-mask-effects",
                        layer.uid);
    }
    const core::Blending blending = BlendingOf(layer, ctx.channel);
    if (blending.mode == BlendingMode::Disable) return {};
    render::Result<float> mask = MaskOf(layer);
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
        render::Result<void> ok = AppendLayer(ctx, *source, list, opacityScale, maskScale);
        --ctx.depth;
        return ok;
    }

    DagLayer node;
    node.uid = layer.uid;
    node.mode = blending.mode;
    node.opacity = static_cast<float>(blending.opacity) * opacityScale;
    node.mask = *mask * maskScale;
    HashWriter writer;
    writer.U64(layer.uid).U32(static_cast<uint32_t>(node.mode)).F32(node.opacity).F32(node.mask);

    switch (layer.kind) {
        case LayerKind::fill: {
            if (!layer.fill) {
                return EvalFail(EvalErrorKind::Internal, "a fill layer without content", layer.uid);
            }
            render::Result<std::optional<DagSource>> source = SourceOf(ctx, layer);
            if (!source) return render::Unexpected(source.error());
            if (!*source) return {};
            if (!arith::HasSeparableKernel(node.mode)) {
                return EvalFail(EvalErrorKind::UnsupportedBlendMode,
                                std::string(core::ToString(node.mode)) +
                                    " is a kernel of phase1.10_compositor-blend-kernels",
                                layer.uid);
            }
            writer.Str("fill").Sub((**source).hash);
            node.source = std::move(*source);
            break;
        }
        case LayerKind::group: {
            if (node.mode == BlendingMode::PassThrough) {
                // Children composite directly into the parent list.
                return AppendLayers(ctx, layer.children, list, node.opacity, node.mask);
            }
            if (!arith::HasSeparableKernel(node.mode)) {
                return EvalFail(EvalErrorKind::UnsupportedBlendMode,
                                std::string(core::ToString(node.mode)) +
                                    " is a kernel of phase1.10_compositor-blend-kernels",
                                layer.uid);
            }
            auto group = std::make_unique<DagList>();
            group->owner = layer.uid;
            group->isolated = true;
            group->startHash = ContentStartHash(ctx, "group");
            render::Result<void> ok = AppendLayers(ctx, layer.children, *group, 1.0f, 1.0f);
            if (!ok) return ok;
            if (group->layers.empty()) return {};  // nothing visible: a transparent group
            writer.Str("group").Sub(group->layers.back().prefixHash);
            node.group = std::move(group);
            break;
        }
        case LayerKind::paint:
            return EvalFail(EvalErrorKind::UnsupportedNode,
                            "paint layers are outside this profile (P4-NODES)", layer.uid);
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
                                  DagList& list, float opacityScale, float maskScale) {
    for (auto it = layersTopFirst.rbegin(); it != layersTopFirst.rend(); ++it) {
        render::Result<void> ok = AppendLayer(ctx, *it, list, opacityScale, maskScale);
        if (!ok) return ok;
    }
    return {};
}

}  // namespace

std::array<float, 3> UniformOperand(const std::array<double, 3>& colour, const TileFormat& format,
                                    const std::array<float, 3>& base) {
    std::array<float, 3> result{0.0f, 0.0f, 0.0f};
    std::array<double, 3> components;
    if (format.channels == 1) {
        const double r = static_cast<float>(colour[0]);
        const double g = static_cast<float>(colour[1]);
        const double b = static_cast<float>(colour[2]);
        components = {(r + g + b) / 3.0, 0.0, 0.0};
    } else {
        components = colour;
    }
    for (uint32_t c = 0; c < format.channels; ++c) {
        const float value = static_cast<float>(components[c]);
        // A 32-bit float colour reads back as the channel would export it (blend-modes.json
        // `uniform_operand`: stored like a channel value, 1 + (v - 1) over the white base).
        const uint32_t stored = format.encoding == render::TexelEncoding::Float32
                                    ? std::bit_cast<uint32_t>(arith::Float32Readout(value, base[c]))
                                    : StoreValue(value, format, c);
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
    render::Result<std::array<float, 3>> base = templates.BaseValue(templateId, channel);
    if (!base) return render::Unexpected(base.error());

    ChannelDag dag;
    dag.textureSet = textureSet;
    dag.stack = stack;
    dag.channel = channel;
    dag.format = channelIt->second.format;
    dag.tileFormat = TileFormatOf(dag.format);
    dag.base = *base;
    dag.grid = TileGrid{static_cast<uint32_t>(set->resolution.width),
                        static_cast<uint32_t>(set->resolution.height)};
    dag.templateId = std::string(templateId);
    dag.root.owner = stack;
    dag.root.isolated = false;
    Context ctx{project, *stackPtr, channel, dag.tileFormat, dag.format, dag.base, dag.grid};
    {
        HashWriter writer;
        writer.Sub(ContentStartHash(ctx, "root"));
        for (const float component : dag.base) writer.F32(component);
        dag.root.startHash = writer.Finish();
    }
    render::Result<void> ok = AppendLayers(ctx, stackPtr->root_layers, dag.root, 1.0f, 1.0f);
    if (!ok) return render::Unexpected(ok.error());
    return dag;
}

}  // namespace uzp::evaluator
