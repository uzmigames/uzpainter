#include "export/virtual_maps.h"

#include "evaluator/arith.h"
#include "evaluator/cpu_store.h"
#include "evaluator/dag.h"
#include "evaluator/error.h"
#include "evaluator/evaluator.h"
#include "evaluator/formats.h"
#include "evaluator/sources.h"
#include "export/padding.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <exception>
#include <filesystem>
#include <fstream>
#include <variant>

namespace uzp::exporter {

namespace {

using evaluator::EvalErrorKind;
using evaluator::EvalFail;

/// The combined virtual normal on UV islands as Painter computes it (virtual_maps.h, decision
/// 308): the diagnostic measure export, and production under EXC-014 (decision 417). `normal` is
/// the whole-tile request.
render::Result<VirtualMapResult> IslandNormalOn(const core::Project& project, std::int64_t revision,
                                                const evaluator::VirtualNormalRequest& normal,
                                                const Coverage& coverage,
                                                const evaluator::TemplateLibrary& templates,
                                                evaluator::ITileStore& store, evaluator::TileCache& cache) {
    const core::TextureSet* set = nullptr;
    for (const core::TextureSet& candidate : project.texture_sets) {
        if (candidate.id == normal.textureSet) set = &candidate;
    }
    if (set == nullptr) return EvalFail(EvalErrorKind::NotFound, "the texture set of the island normal is not in the project");
    // The Height's stored format: the operands its padding reads (encode.h, decision 274).
    std::optional<core::ChannelFormat> heightFormat;
    for (const core::Stack& stack : set->stacks) {
        if (stack.id != normal.stack) continue;
        if (const auto it = stack.channels.find(core::ChannelType::Height); it != stack.channels.end()) {
            heightFormat = it->second.format;
        }
    }
    const size_t texels = coverage.covered.size();
    // 1. The Height the stencil reads: the read-out where covered, else the padding of the stored
    // operands without the 1 - (1 - m) step (decisions 263, 288 (a)).
    // A measurement may ask for the float32 Height the stencil reads, before and after the padding
    // (raw float32, rows top first): `UZP_DIAGNOSTIC_NORMAL_DUMP` names a directory. Only this
    // island path reads it.
    const char* dump = std::getenv("UZP_DIAGNOSTIC_NORMAL_DUMP");
    const auto write = [&](const std::string& name, const std::vector<float>& data) {
        if (dump == nullptr || *dump == '\0') return;
        std::ofstream(std::filesystem::path(dump) / (set->name + "-" + name + ".f32"), std::ios::binary)
            .write(reinterpret_cast<const char*>(data.data()), static_cast<std::streamsize>(data.size() * sizeof(float)));
    };
    evaluator::VirtualNormalRequest padded = normal;
    padded.heightPadding = [&coverage, heightFormat, texels, &write](std::vector<float>& heights) {
        write("height-readout", heights);
        std::vector<float> operands(heights);
        if (heightFormat) {
            const evaluator::TileFormat tile = evaluator::TileFormatOf(*heightFormat);
            for (float& v : operands) v = evaluator::OperandOf(evaluator::StoreValue(v, tile, 0), tile, 0);
        }
        PadIslandHeight(coverage, operands);
        for (size_t t = 0; t < texels; ++t) {
            if (coverage.covered[t] == 0) heights[t] = operands[t];
        }
        write("height-padded", heights);
    };
    const bool mesh = set->mesh_maps.contains(core::MeshMapUsage::Normal);
    try {
        // 2. The covered texels.
        render::Result<evaluator::VirtualNormalResult> combined =
            evaluator::EvaluateVirtualNormalOn(project, revision, padded, templates, store, cache);
        if (!combined) return render::Unexpected(combined.error());
        // 3. Pad unit Hn/C separately with a mesh map; otherwise copy the encoded normal.
        std::vector<float> free;
        std::vector<float> heightNormals, channelNormals;
        if (mesh) {
            evaluator::VirtualNormalRequest request = padded;
            request.withoutMesh = true;
            request.component = evaluator::VirtualNormalComponent::Height;
            render::Result<evaluator::VirtualNormalResult> heightPart =
                evaluator::EvaluateVirtualNormalOn(project, revision, request, templates, store, cache);
            if (!heightPart) return render::Unexpected(heightPart.error());
            heightNormals = std::move(heightPart->texels);
            request.component = evaluator::VirtualNormalComponent::Channel;
            render::Result<evaluator::VirtualNormalResult> channelPart =
                evaluator::EvaluateVirtualNormalOn(project, revision, request, templates, store, cache);
            if (!channelPart) return render::Unexpected(channelPart.error());
            channelNormals = std::move(channelPart->texels);
        } else {
            free = combined->texels;
        }
        if (mesh) {
            // Across-border-only ring texels retain flat Hn and their own C (decision 287).
            // Other ring texels copy a covered pair before the common clamped flood.
            for (size_t t = 0; t < texels; ++t) {
                if (coverage.covered[t] == 0) {
                    heightNormals[t * 3] = 0.0f;
                    heightNormals[t * 3 + 1] = 0.0f;
                    heightNormals[t * 3 + 2] = 1.0f;
                }
            }
            PadIslandNormal(coverage, heightNormals);
            PadIslandNormal(coverage, channelNormals);
        } else if (NormalRingAcrossBorder(coverage)) {
            // A flat height normal combined with the Normal channel (decision 287 §4).
            evaluator::VirtualNormalRequest request = normal;
            request.withoutMesh = true;
            request.heightPadding = [](std::vector<float>& heights) { std::fill(heights.begin(), heights.end(), 0.0f); };
            render::Result<evaluator::VirtualNormalResult> flat =
                evaluator::EvaluateVirtualNormalOn(project, revision, request, templates, store, cache);
            if (!flat) return render::Unexpected(flat.error());
            for (size_t t = 0; t < texels; ++t) {
                if (coverage.covered[t] == 0) std::copy_n(flat->texels.begin() + static_cast<std::ptrdiff_t>(t * 3), 3,
                                                          free.begin() + static_cast<std::ptrdiff_t>(t * 3));
            }
        }
        if (!mesh) PadIslandNormal(coverage, free);
        // 4. The uncovered texels: the padded normal, under the mesh map at the texel when one is bound.
        std::shared_ptr<const evaluator::DecodedImage> meshImage;
        if (mesh && normal.resources) {
            meshImage = normal.resources->Fetch(set->mesh_maps.at(core::MeshMapUsage::Normal).resource);
        }
        if (mesh && !meshImage) {
            return EvalFail(EvalErrorKind::MissingResource, "the Normal mesh map of the island normal is not available");
        }
        // EvaluateVirtualNormalOn refused a mesh map in another convention than the project's.
        const bool meshDirectX = project.settings.normal_map_format == core::NormalMapFormat::DirectX;
        VirtualMapResult result;
        result.values = {combined->width, combined->height, 3, std::move(combined->texels)};
        result.tag = combined->tag;
        result.padded = true;
        std::vector<float>& out = result.values.values;
        for (size_t t = 0; t < texels; ++t) {
            if (coverage.covered[t] != 0) continue;
            std::array<float, 3> e{};
            if (mesh) {
                const auto x = static_cast<uint32_t>(t % coverage.width);
                const auto y = static_cast<uint32_t>(t / coverage.width);
                std::array<float, 3> f{};
                for (uint32_t c = 0; c < 3; ++c) f[c] = evaluator::arith::UnormOperand(meshImage->At(x, y, c) & 0xFFFFu, 16);
                const std::array<float, 3> h{heightNormals[t * 3], heightNormals[t * 3 + 1], heightNormals[t * 3 + 2]};
                const std::array<float, 3> c{channelNormals[t * 3], channelNormals[t * 3 + 1], channelNormals[t * 3 + 2]};
                e = evaluator::MeshOnPaddedNormal(f, meshDirectX, h, c, normal.convention);
                // Preserve the diagnostic marker until the Height-ring and border evidence closes.
                ++result.undecided;
            } else {
                e = {free[t * 3], free[t * 3 + 1], free[t * 3 + 2]};
            }
            std::copy(e.begin(), e.end(), out.begin() + static_cast<std::ptrdiff_t>(t * 3));
        }
        return result;
    } catch (const std::exception& e) {
        return EvalFail(EvalErrorKind::Internal, std::string("the island normal (decision 308): ") + e.what());
    }
}

constexpr std::array<std::string_view, kVirtualMapCount> kNames{
    "Normal_OpenGL", "Normal_DirectX", "AO_Mixed",   "Diffuse", "Specular", "Glossiness", "Unity4Diff",
    "Unity4Gloss",   "reflection",     "1/ior",      "Glossiness2", "f0",   "View_2D",
};

/// The goldens AO_Mixed equals (decision 411).
constexpr std::string_view kAoMixedEvidence =
    "tier0/semantics/ao-mixed, ao-mixed-opacity and its OpenEXR 32f twin, ao-mixed-isolation, -float, -8bit, "
    "ao-mixed-grid, ao-mixed-grid-l32f, ao-mixed-grid-l16-reopen3, ao-mixed-mesh-float-product, "
    "ao-mixed-precomposed-half-l32f, ao-mixed-precomposed-half-y-l32f and ao-mixed-operand-probe: every r1 texel at "
    "PNG 8, PNG 16 and OpenEXR 32f (phase3.2_unreal-ue56-packed-preset item 2.10, decision 411)";
/// The owners of the virtual maps not reproduced exactly (decision 092).
constexpr std::string_view kConvertedOwner =
    "phase1.18_export-engine: fitted, but it needs each channel's per-texel coverage from the evaluator "
    "and the uncovered constants of Tier 0 recording R-092 (decision 092)";
constexpr std::string_view kView2dOwner =
    "a reproduction of Painter's 2D view render, which no task owns yet (decision 092)";

constexpr core::ChannelType kAo = core::ChannelType::AO;

/// float32 fma with one rounding: x y is exact in double, and a double sum that falls on a float32
/// midpoint is moved by the sum's rounding error (arith::Fma rounds twice there).
float FmaOnce(float x, float y, float z) {
    const double s = static_cast<double>(x) * static_cast<double>(y);
    const double t = s + static_cast<double>(z);
    const double back = t - s;
    const double error = (s - (t - back)) + (static_cast<double>(z) - back);
    const float r = static_cast<float>(t);
    const bool above = static_cast<double>(r) > t;
    const float lo = above ? std::nextafter(r, -INFINITY) : r;
    const float hi = above ? r : std::nextafter(r, INFINITY);
    if (error != 0.0 && t == (static_cast<double>(lo) + static_cast<double>(hi)) / 2.0) return error > 0.0 ? hi : lo;
    return r;
}

bool EffectTouchesAo(const core::Effect& effect) {
    if (!effect.visible) return false;
    if (effect.active_channels.contains(kAo)) return true;
    if (effect.fill && effect.fill->active_channels.contains(kAo)) return true;
    return effect.paint && effect.paint->planes.contains(kAo);
}

/// Whether `layer` can change the AO channel.
bool TouchesAo(const core::Layer& layer) {
    if (!layer.visible || core::IsEmptyPaintLayer(layer)) return false;
    switch (layer.kind) {
        case core::LayerKind::fill:
            if (layer.fill && layer.fill->active_channels.contains(kAo)) return true;
            break;
        case core::LayerKind::paint:
            if (layer.paint && layer.paint->planes.contains(kAo)) return true;
            break;
        case core::LayerKind::group:
            for (const core::Layer& child : layer.children) {
                if (TouchesAo(child)) return true;
            }
            break;
        case core::LayerKind::instance: return true;
    }
    return std::any_of(layer.content_effects.begin(), layer.content_effects.end(), EffectTouchesAo);
}

/// The AO fill of `stack` in AO_Mixed's scope (null: no AO layer), or why it is outside it.
std::variant<const core::Layer*, std::string> AoMixedFill(const core::Project& project, const core::TextureSet& set,
                                                          const core::Stack& stack) {
    using Fill = std::variant<const core::Layer*, std::string>;
    const std::string& mode = project.settings.color_management.mode;
    const bool ocio = evaluator::PainterOcio(project);
    if (!mode.empty() && mode != "legacy" && !ocio) {
        return Fill(std::string("under legacy colour management or OCIO with Painter's substance config only"));
    }
    const auto mesh = set.mesh_maps.find(core::MeshMapUsage::AO);
    if (mesh == set.mesh_maps.end() || mesh->second.invalid) {
        return Fill(std::string("with a valid AO mesh map bound only"));
    }
    // Without an AO channel the channel operand is 1, as with no AO layer (decision 418).
    const auto channel = stack.channels.find(kAo);
    if (channel == stack.channels.end()) return Fill(static_cast<const core::Layer*>(nullptr));
    if (channel->second.format != core::ChannelFormat::L16 && channel->second.format != core::ChannelFormat::L32F) {
        return Fill("on an L16 or L32F AO channel only, not " + std::string(core::ToString(channel->second.format)));
    }
    const core::Layer* fill = nullptr;
    for (const core::Layer& layer : stack.root_layers) {
        if (!TouchesAo(layer)) continue;
        if (fill != nullptr || layer.kind != core::LayerKind::fill) {
            return Fill(std::string("with no AO layer or one root fill layer on AO only"));
        }
        fill = &layer;
    }
    if (fill == nullptr) return Fill(fill);
    const core::FillContent& content = *fill->fill;
    if (fill->mask || !fill->content_effects.empty() || fill->geometry_mask.inclusion_list ||
        !fill->geometry_mask.items.empty()) {
        return Fill(std::string("for a fill without a mask, content effects or a geometry mask only"));
    }
    const core::Blending blending = evaluator::EffectiveBlending(*fill, kAo);
    if (blending.mode != core::BlendingMode::Normal || !(blending.opacity >= 0.0 && blending.opacity <= 1.0)) {
        return Fill(std::string("for a fill in Normal with an opacity in [0, 1] only"));
    }
    const auto source = content.sources.find(kAo);
    if (content.source_mode != core::SourceMode::Split || source == content.sources.end()) {
        return Fill(std::string("for a fill with its own AO source only"));
    }
    // Under OCIO only R-314's fill is recorded: a 16-bit grey bitmap (checked when it is read) on an
    // L16 channel at opacity 1 (decision 418).
    if (ocio && (channel->second.format != core::ChannelFormat::L16 || blending.opacity != 1.0 ||
                 !std::holds_alternative<core::BitmapSource>(source->second.value))) {
        return Fill(std::string("under OCIO for a 16-bit grey bitmap fill on an L16 AO channel at opacity 1 only"));
    }
    const std::string sourceScope = "for a grey linear uniform colour or bitmap source only";
    if (const auto* uniform = std::get_if<core::UniformColorSource>(&source->second.value)) {
        const bool grey = uniform->rgb[0] == uniform->rgb[1] && uniform->rgb[0] == uniform->rgb[2];
        if (!grey || evaluator::BitmapColourSpaceOf(uniform->color_space) != evaluator::BitmapColourSpace::Linear) {
            return Fill(sourceScope);
        }
        return Fill(fill);
    }
    const auto* bitmap = std::get_if<core::BitmapSource>(&source->second.value);
    if (bitmap == nullptr || bitmap->resource.sha256.empty() ||
        evaluator::BitmapColourSpaceIn(project, bitmap->color_space) != evaluator::BitmapColourSpace::Linear) {
        return Fill(sourceScope);
    }
    const core::Projection& projection = content.projection;
    const core::UVTransformation& uv = projection.uv.uv_transformation;
    const bool identity = uv.scale_mode == core::ScaleMode::Factors && uv.scale[0] == 1.0 && uv.scale[1] == 1.0 &&
                          uv.rotation == 0.0 && uv.offset[0] == 0.0 && uv.offset[1] == 0.0;
    const core::FilteringMode filtering = projection.uv.filtering_mode;
    const core::UVWrapMode wrap = projection.uv.uv_wrapping_mode;
    if (projection.mode != core::ProjectionMode::UV || content.symmetry.enabled || !identity ||
        (filtering != core::FilteringMode::Nearest && filtering != core::FilteringMode::BilinearHQ) ||
        (wrap != core::UVWrapMode::Repeat && wrap != core::UVWrapMode::RepeatNone)) {
        return Fill(std::string("for a bitmap under the identity UV projection with Nearest or BilinearHQ filtering, "
                                "Repeat or RepeatNone only"));
    }
    return Fill(fill);
}

/// The operands of an 8- or 16-bit grey image at `width` x `height`, or nothing.
std::optional<std::vector<float>> GreyOperands(const evaluator::DecodedImage* image, uint32_t width, uint32_t height) {
    if (image == nullptr || image->channels != 1 || image->srgb8 || image->width != width || image->height != height) {
        return std::nullopt;
    }
    uint32_t bits = 0;
    if (image->encoding == render::TexelEncoding::Unorm16) bits = 16;
    if (image->encoding == render::TexelEncoding::Unorm8) bits = 8;
    if (bits == 0) return std::nullopt;
    const uint32_t max = (1u << bits) - 1u;
    std::vector<float> out;
    out.reserve(image->values.size());
    for (const uint32_t code : image->values) out.push_back(evaluator::arith::UnormOperand(code & max, bits));
    return out;
}

/// The layer opacity on an L16 channel: its 16-bit code, ties down.
float L16Opacity(double opacity) {
    const double scaled = opacity * 65535.0;
    const double code = scaled - std::floor(scaled) == 0.5 ? std::floor(scaled) : std::round(scaled);
    return evaluator::arith::UnormOperand(static_cast<uint32_t>(code), 16);
}

/// AO_Mixed (virtual_maps.h, decision 411).
render::Result<VirtualMapResult> AoMixedOn(const core::Project& project, const VirtualMapRequest& request) {
    const core::TextureSet* set = nullptr;
    const core::Stack* stack = nullptr;
    for (const core::TextureSet& candidate : project.texture_sets) {
        if (candidate.id != request.textureSet) continue;
        set = &candidate;
        for (const core::Stack& s : candidate.stacks) {
            if (s.id == request.stack) stack = &s;
        }
    }
    if (set == nullptr || stack == nullptr) {
        return EvalFail(EvalErrorKind::NotFound, "the stack of AO_Mixed is not in the project");
    }
    const std::string scope = "AO_Mixed is reproduced ";
    const std::variant<const core::Layer*, std::string> fill = AoMixedFill(project, *set, *stack);
    if (const std::string* refusal = std::get_if<std::string>(&fill)) {
        return EvalFail(EvalErrorKind::UnsupportedSource, scope + *refusal + " (decision 411)");
    }
    if (request.templateId != evaluator::kDefaultTemplateId) {
        return EvalFail(EvalErrorKind::UnsupportedSource, scope + "on the default template only (decision 411)");
    }
    const auto width = static_cast<uint32_t>(set->resolution.width);
    const auto height = static_cast<uint32_t>(set->resolution.height);
    // Every texel takes the operator; on incomplete UV coverage the export pads the uncovered ones
    // under `infinite` (EXC-013), the covered ones being exact (decision 418).
    const size_t texels = size_t{width} * height;
    const auto fetch = [&](const std::string& sha) -> std::shared_ptr<const evaluator::DecodedImage> {
        return request.resources ? request.resources->Fetch(sha) : nullptr;
    };
    const std::shared_ptr<const evaluator::DecodedImage> meshImage =
        fetch(set->mesh_maps.at(core::MeshMapUsage::AO).resource);
    const std::optional<std::vector<float>> mesh = GreyOperands(meshImage.get(), width, height);
    if (!mesh) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        scope + "with an 8- or 16-bit grey AO mesh map at the set's resolution only (decision 411)");
    }
    std::vector<float> channel(texels, 1.0f);
    if (const core::Layer* layer = std::get<const core::Layer*>(fill)) {
        const core::ChannelFormat format = stack->channels.at(kAo).format;
        const core::Source& source = layer->fill->sources.at(kAo);
        std::vector<float> values;
        if (const auto* uniform = std::get_if<core::UniformColorSource>(&source.value)) {
            values.assign(texels, static_cast<float>(uniform->rgb[0]));
        } else {
            const std::shared_ptr<const evaluator::DecodedImage> image =
                fetch(std::get<core::BitmapSource>(source.value).resource.sha256);
            std::optional<std::vector<float>> operands = GreyOperands(image.get(), width, height);
            if (!operands) {
                return EvalFail(EvalErrorKind::UnsupportedSource,
                                scope + "with an 8- or 16-bit grey bitmap at the set's resolution only (decision 411)");
            }
            if (evaluator::PainterOcio(project) && image->encoding != render::TexelEncoding::Unorm16) {
                return EvalFail(EvalErrorKind::UnsupportedSource,
                                scope + "under OCIO with a 16-bit grey bitmap only (decision 418)");
            }
            values = std::move(*operands);
        }
        const double opacity = evaluator::EffectiveBlending(*layer, kAo).opacity;
        const float alpha = format == core::ChannelFormat::L16 ? L16Opacity(opacity) : static_cast<float>(opacity);
        for (size_t t = 0; t < texels; ++t) {
            float s = values[t];
            if (!(s >= 0.0f && s <= 1.0f)) {
                return EvalFail(EvalErrorKind::UnsupportedSource, scope + "for a source in [0, 1] only (decision 411)");
            }
            if (format == core::ChannelFormat::L16) {
                s = evaluator::arith::UnormOperand(evaluator::arith::WriteUnorm(s, 16), 16);
            }
            channel[t] = FmaOnce(s, alpha, 1.0f) - alpha;
        }
    }
    VirtualMapResult result;
    result.values.width = width;
    result.values.height = height;
    result.values.components = 1;
    result.values.values.resize(texels);
    for (size_t t = 0; t < texels; ++t) {
        const float a = (1.0f + (*mesh)[t]) - 1.0f;
        const float v = a * channel[t];
        const float w = (v - 1.0f) + 1.0f;
        result.values.values[t] = evaluator::arith::UnormOperand(evaluator::arith::WriteUnorm(w, 8), 8);
    }
    return result;
}

}  // namespace

std::optional<uint32_t> PassThroughComponents(core::MeshMapUsage usage) {
    switch (usage) {
        case core::MeshMapUsage::AO:
        case core::MeshMapUsage::Curvature: return 1;
        case core::MeshMapUsage::Position: return 3;
        default: return std::nullopt;
    }
}

render::Result<VirtualMapResult> PassThroughMeshMap(const core::Project& project, core::MeshMapUsage usage,
                                                    const VirtualMapRequest& request) {
    const std::string name(core::ToString(usage));
    const std::optional<uint32_t> components = PassThroughComponents(usage);
    if (!components) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "exporting the " + name +
                            " mesh map is not recorded (recording R-090 P7 shows AO, Curvature and Position; decision 103)");
    }
    const core::TextureSet* set = nullptr;
    for (const core::TextureSet& candidate : project.texture_sets) {
        if (candidate.id == request.textureSet) set = &candidate;
    }
    if (set == nullptr) return EvalFail(EvalErrorKind::Internal, "the texture set of the mesh map is not in the project");
    const auto binding = set->mesh_maps.find(usage);
    if (binding == set->mesh_maps.end()) {
        return EvalFail(EvalErrorKind::MissingResource, "texture set " + set->name + " has no " + name + " mesh map");
    }
    const std::shared_ptr<const evaluator::DecodedImage> image =
        request.resources ? request.resources->Fetch(binding->second.resource) : nullptr;
    if (!image) {
        return EvalFail(EvalErrorKind::MissingResource,
                        "the " + name + " mesh map's image " + binding->second.resource + " is not available");
    }
    const bool unorm = image->encoding == render::TexelEncoding::Unorm16 ||
                       image->encoding == render::TexelEncoding::Unorm8;
    if (!unorm || image->channels != *components || image->width != static_cast<uint32_t>(set->resolution.width) ||
        image->height != static_cast<uint32_t>(set->resolution.height)) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "the " + name + " mesh map is recorded as an 8- or 16-bit " +
                            (*components == 1 ? "grey" : "RGB") +
                            " image at the set resolution only (a pass-through does not resample; decision 103)");
    }
    const uint32_t bits = image->encoding == render::TexelEncoding::Unorm16 ? 16u : 8u;
    const uint32_t max = (1u << bits) - 1u;
    VirtualMapResult result;
    result.values.width = image->width;
    result.values.height = image->height;
    result.values.components = *components;
    result.values.values.reserve(image->values.size());
    for (const uint32_t code : image->values) result.values.values.push_back(evaluator::arith::UnormOperand(code & max, bits));
    return result;
}

std::string_view VirtualMapName(VirtualMap map) { return kNames[static_cast<size_t>(map)]; }

std::optional<VirtualMap> ParseVirtualMap(std::string_view name) {
    for (size_t i = 0; i < kNames.size(); ++i) {
        if (kNames[i] == name) return static_cast<VirtualMap>(i);
    }
    return std::nullopt;
}

std::vector<std::string> VirtualMapNames() { return {kNames.begin(), kNames.end()}; }

VirtualMapSupport Support(VirtualMap map) {
    switch (map) {
        case VirtualMap::Normal_OpenGL:
        case VirtualMap::Normal_DirectX:
            return {true, 3,
                    "tier0/semantics/height-normal-plane-amplitudes, height-normal-sphere, height-normal-bevelled-cube, "
                    "blend-normal-channel and the semantics-ui height-normal goldens (phase1.12, decisions 064, 065)"};
        case VirtualMap::AO_Mixed: return {true, 1, std::string(kAoMixedEvidence)};
        case VirtualMap::Diffuse:
        case VirtualMap::Specular:
        case VirtualMap::reflection:
        case VirtualMap::f0:
        case VirtualMap::Unity4Diff: return {false, 3, std::string(kConvertedOwner)};
        case VirtualMap::View_2D: return {false, 3, std::string(kView2dOwner)};
        case VirtualMap::Glossiness:
        case VirtualMap::Glossiness2:
        case VirtualMap::Unity4Gloss:
        case VirtualMap::OneOverIor: return {false, 1, std::string(kConvertedOwner)};
    }
    return {};
}

std::optional<std::string> AoMixedRefusal(const core::Project& project, const core::TextureSet& set,
                                          const core::Stack& stack) {
    const std::variant<const core::Layer*, std::string> fill = AoMixedFill(project, set, stack);
    if (const std::string* refusal = std::get_if<std::string>(&fill)) return *refusal;
    return std::nullopt;
}

render::Result<VirtualMapResult> EvaluateVirtualMapOn(const core::Project& project, std::int64_t revision,
                                                      VirtualMap map, const VirtualMapRequest& request,
                                                      const evaluator::TemplateLibrary& templates,
                                                      evaluator::ITileStore& store, evaluator::TileCache& cache) {
    if (!Support(map).supported) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "the virtual map " + std::string(VirtualMapName(map)) + " is a release gap (" +
                            Support(map).evidenceOrOwner + ")");
    }
    if (map == VirtualMap::AO_Mixed) return AoMixedOn(project, request);
    // The other supported maps are the combined normals.
    evaluator::VirtualNormalRequest normal;
    normal.textureSet = request.textureSet;
    normal.stack = request.stack;
    normal.kind = evaluator::NormalSourceKind::Combined;
    normal.convention = map == VirtualMap::Normal_OpenGL ? core::NormalMapFormat::OpenGL : core::NormalMapFormat::DirectX;
    normal.templateId = request.templateId;
    normal.resources = request.resources;
    normal.procedurals = request.procedurals;
    normal.geometry = request.geometry;
    if (request.islandNormal != nullptr && !request.islandNormal->Complete()) {
        return IslandNormalOn(project, revision, normal, *request.islandNormal, templates, store, cache);
    }
    render::Result<evaluator::VirtualNormalResult> evaluated =
        evaluator::EvaluateVirtualNormalOn(project, revision, normal, templates, store, cache);
    if (!evaluated) return render::Unexpected(evaluated.error());
    VirtualMapResult result;
    result.values = {evaluated->width, evaluated->height, 3, std::move(evaluated->texels)};
    result.tag = evaluated->tag;
    return result;
}

render::Result<VirtualMapResult> EvaluateMeshMapOn(const core::Project& project, std::int64_t revision,
                                                   core::MeshMapUsage usage, const VirtualMapRequest& request,
                                                   const evaluator::TemplateLibrary& templates,
                                                   evaluator::ITileStore& store, evaluator::TileCache& cache) {
    if (usage != core::MeshMapUsage::Normal) return PassThroughMeshMap(project, usage, request);
    evaluator::VirtualNormalRequest normal;
    normal.textureSet = request.textureSet;
    normal.stack = request.stack;
    normal.kind = evaluator::NormalSourceKind::GeometryOnly;
    normal.convention = project.settings.normal_map_format;
    normal.templateId = request.templateId;
    normal.resources = request.resources;
    normal.procedurals = request.procedurals;
    normal.geometry = request.geometry;
    render::Result<evaluator::VirtualNormalResult> evaluated =
        evaluator::EvaluateVirtualNormalOn(project, revision, normal, templates, store, cache);
    if (!evaluated) return render::Unexpected(evaluated.error());
    VirtualMapResult result;
    result.values = {evaluated->width, evaluated->height, 3, std::move(evaluated->texels)};
    result.tag = evaluated->tag;
    return result;
}

}  // namespace uzp::exporter
