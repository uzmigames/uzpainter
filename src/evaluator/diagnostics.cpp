#include "evaluator/diagnostics.h"

#include <algorithm>
#include <bit>
#include <charconv>
#include <cmath>
#include <cstring>
#include <map>
#include <string>

#include "evaluator/arith.h"
#include "evaluator/cpu_store.h"
#include "evaluator/dag.h"
#include "evaluator/error.h"
#include "evaluator/evaluator.h"
#include "evaluator/height_to_normal.h"
#include "uzp_core/document/nodes.h"

namespace uzp::evaluator {

namespace {

using core::ChannelType;
using core::Layer;

constexpr std::string_view kVirtualNormalNames[2] = {"Normal_OpenGL", "Normal_DirectX"};
constexpr std::array<std::string_view, 6> kViewNames{"ID", "BaseColor", "Height", "Normal", "Roughness", "Metallic"};
constexpr std::array<ChannelType, 6> kViewChannels{ChannelType::BaseColor, ChannelType::BaseColor,
                                                   ChannelType::Height,    ChannelType::Normal,
                                                   ChannelType::SpecularRoughness, ChannelType::BaseMetalness};
constexpr std::array<std::string_view, 6> kKindNames{"isolated",      "contribution",  "materialMask",
                                                     "materialView",  "materialLeaks", "regionStats"};

core::Stack* MutableStack(core::Project& project, core::Id textureSet, core::Id stack) {
    for (core::TextureSet& set : project.texture_sets) {
        if (set.id != textureSet) continue;
        for (core::Stack& candidate : set.stacks) {
            if (candidate.id == stack) return &candidate;
        }
    }
    return nullptr;
}

const core::TextureSet* FindSet(const core::Project& project, core::Id textureSet) {
    for (const core::TextureSet& set : project.texture_sets) {
        if (set.id == textureSet) return &set;
    }
    return nullptr;
}

render::Unexpected StackNotFound(const DiagnosticRequest& request) {
    return EvalFail(EvalErrorKind::NotFound, "stack " + std::to_string(request.stack) + " is not in texture set " +
                                                 std::to_string(request.textureSet));
}

/// The visibility flag of layer or effect `uid` in `layers` (at any depth), or null.
template <class Layers>
auto VisibilityOf(Layers& layers, core::Id uid) -> decltype(&layers.front().visible) {
    for (auto& layer : layers) {
        if (layer.uid == uid) return &layer.visible;
        for (auto& effect : layer.content_effects) {
            if (effect.uid == uid) return &effect.visible;
        }
        if (layer.mask) {
            for (auto& effect : layer.mask->effects) {
                if (effect.uid == uid) return &effect.visible;
            }
        }
        if (auto found = VisibilityOf(layer.children, uid)) return found;
    }
    return nullptr;
}

/// The layers from the root list down to layer `uid` (the layer last), or false.
bool PathTo(const std::vector<Layer>& layers, core::Id uid, std::vector<const Layer*>& path) {
    for (const Layer& layer : layers) {
        path.push_back(&layer);
        if (layer.uid == uid || PathTo(layer.children, uid, path)) return true;
        path.pop_back();
    }
    return false;
}

/// Hides every layer of `layers` that is neither `uid` nor encloses it; returns whether `layers`
/// holds `uid` at any depth. The material's own subtree is left as it is.
bool KeepOnly(std::vector<Layer>& layers, core::Id uid) {
    bool found = false;
    for (Layer& layer : layers) {
        if (layer.uid == uid || KeepOnly(layer.children, uid)) {
            found = true;
            continue;
        }
        layer.visible = false;
    }
    return found;
}

/// Flushes queued store work and releases the pins of one evaluation (the Evaluator's request
/// ends the same way), so the evaluations of one diagnostic do not accumulate pinned tiles.
render::Result<void> EndEvaluation(ITileStore& store, TileCache& cache) {
    render::Result<void> flushed = store.Flush();
    cache.UnpinAll();
    return flushed;
}

bool SameBits(float a, float b) { return std::bit_cast<uint32_t>(a) == std::bit_cast<uint32_t>(b); }

/// The correctly rounded sum of `values` (Shewchuk's exact partials, then the round-half-even
/// correction across partials; the algorithm of Python's math.fsum).
double ExactSum(const std::vector<double>& values) {
    std::vector<double> partials;
    for (double x : values) {
        size_t i = 0;
        for (double y : partials) {
            if (std::fabs(x) < std::fabs(y)) std::swap(x, y);
            const double hi = x + y;
            const double lo = y - (hi - x);
            if (lo != 0.0) partials[i++] = lo;
            x = hi;
        }
        partials.resize(i);
        partials.push_back(x);
    }
    size_t n = partials.size();
    if (n == 0) return 0.0;
    double hi = partials[--n];
    double lo = 0.0;
    while (n > 0) {
        const double x = hi;
        const double y = partials[--n];
        hi = x + y;
        const double yr = hi - x;
        lo = y - yr;
        if (lo != 0.0) break;
    }
    if (n > 0 && ((lo < 0.0 && partials[n - 1] < 0.0) || (lo > 0.0 && partials[n - 1] > 0.0))) {
        const double y = lo * 2.0;
        const double x = hi + y;
        const double yr = x - hi;
        if (y == yr) hi = x;
    }
    return hi;
}

/// The linear-rule percentile `q` of the sorted, non-empty `sorted`.
double Percentile(const std::vector<double>& sorted, double q) {
    const double h = static_cast<double>(sorted.size() - 1) * q;
    const double lower = std::floor(h);
    const size_t i = static_cast<size_t>(lower);
    if (i + 1 >= sorted.size()) return sorted[i];
    return sorted[i] + (h - lower) * (sorted[i + 1] - sorted[i]);
}

ValueStats StatsOf(std::vector<double> values) {
    ValueStats stats;
    stats.mean = ExactSum(values) / static_cast<double>(values.size());
    std::sort(values.begin(), values.end());
    stats.min = values.front();
    stats.max = values.back();
    stats.p10 = Percentile(values, 0.1);
    stats.p50 = Percentile(values, 0.5);
    stats.p90 = Percentile(values, 0.9);
    return stats;
}

void AppendDouble(std::string& out, double value) {
    char buffer[32];
    const std::to_chars_result written = std::to_chars(buffer, buffer + sizeof(buffer), value);
    out.append(buffer, written.ptr);
}

void AppendStats(std::string& out, const ValueStats& stats) {
    const std::pair<const char*, double> fields[] = {{"min", stats.min}, {"max", stats.max}, {"mean", stats.mean},
                                                     {"p10", stats.p10}, {"p50", stats.p50}, {"p90", stats.p90}};
    out += '{';
    bool first = true;
    for (const auto& [name, value] : fields) {
        if (!first) out += ',';
        first = false;
        out += '"';
        out += name;
        out += "\":";
        AppendDouble(out, value);
    }
    out += '}';
}

/// The effective mask of the material at the end of `path` (its own mask times every enclosing
/// group's, from the material outward), each mask as the engine evaluates it.
render::Result<DiagnosticMap> EffectiveMask(const core::Project& project, const std::vector<const Layer*>& path,
                                            const core::Stack& stack, const DiagnosticRequest& request,
                                            const TemplateLibrary& templates, ITileStore& store, TileCache& cache) {
    if (stack.channels.empty()) {
        return EvalFail(EvalErrorKind::NotFound, "stack " + std::to_string(stack.id) + " has no channel");
    }
    // The mask does not depend on the channel: any channel's DAG gives the grid and the profile.
    render::Result<ChannelDag> frame = BuildDag(project, request.textureSet, request.stack,
                                                stack.channels.begin()->first, templates, request.templateId);
    if (!frame) return render::Unexpected(frame.error());
    const core::TextureSet* set = FindSet(project, request.textureSet);
    render::Result<void> admitted = CheckTextureSet(cache.limits(), *set);
    if (!admitted) return render::Unexpected(admitted.error());
    EvalEnvironment env{store, cache, request.resources.get(), request.geometry.get()};
    DiagnosticMap effective;
    for (auto it = path.rbegin(); it != path.rend(); ++it) {
        render::Result<DagLayer> layer = BuildLayerMask(project, *frame, (*it)->uid);
        if (!layer) return render::Unexpected(layer.error());
        render::Result<ChannelResult> mask = EvaluateLayerMask(*frame, *layer, env);
        render::Result<void> ended = EndEvaluation(store, cache);
        if (!mask) return render::Unexpected(mask.error());
        if (!ended) return render::Unexpected(ended.error());
        DiagnosticMap values = MapOf(*mask);
        if (it == path.rbegin()) {
            effective = std::move(values);
            continue;
        }
        for (size_t i = 0; i < effective.values.size(); ++i) effective.values[i] = effective.values[i] * values.values[i];
    }
    return effective;
}

/// The ID view's map: the bound ID mesh map's codes as operands and the codes themselves, or
/// nothing when the set has no ID mesh map.
struct IdMap {
    DiagnosticMap operands;
    std::vector<std::array<uint32_t, 3>> codes;
};

render::Result<std::optional<IdMap>> IdMeshMap(const core::TextureSet& set, const DiagnosticRequest& request) {
    const auto binding = set.mesh_maps.find(core::MeshMapUsage::ID);
    if (binding == set.mesh_maps.end()) return std::optional<IdMap>{};
    if (request.resources == nullptr) {
        return EvalFail(EvalErrorKind::MissingResource, "no resource provider for the ID mesh map");
    }
    std::shared_ptr<const DecodedImage> image = request.resources->Fetch(binding->second.resource);
    if (!image) {
        return EvalFail(EvalErrorKind::MissingResource, "ID mesh map " + binding->second.resource + " is not available");
    }
    const bool unorm = image->encoding == render::TexelEncoding::Unorm16 ||
                       image->encoding == render::TexelEncoding::Unorm8;
    if (!unorm || image->channels < 3 || image->width != static_cast<uint32_t>(set.resolution.width) ||
        image->height != static_cast<uint32_t>(set.resolution.height)) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "the ID mesh map must be an 8- or 16-bit RGB image at the set resolution");
    }
    const uint32_t bits = image->encoding == render::TexelEncoding::Unorm16 ? 16u : 8u;
    const uint32_t max = (1u << bits) - 1u;
    IdMap id;
    id.operands = {image->width, image->height, 3, {}};
    id.operands.values.resize(size_t{image->width} * image->height * 3);
    id.codes.resize(size_t{image->width} * image->height);
    for (uint32_t y = 0; y < image->height; ++y) {
        for (uint32_t x = 0; x < image->width; ++x) {
            const size_t texel = size_t{y} * image->width + x;
            for (uint32_t c = 0; c < 3; ++c) {
                const uint32_t code = image->At(x, y, c) & max;
                id.codes[texel][c] = code;
                id.operands.values[texel * 3 + c] = arith::UnormOperand(code, bits);
            }
        }
    }
    return std::optional<IdMap>{std::move(id)};
}

DiagnosticMap Blank(const DiagnosticMap& like, uint32_t components) {
    return {like.width, like.height, components, std::vector<float>(size_t{like.width} * like.height * components, 0.0f)};
}

/// The ID view: the ID colours inside the region; a leak is an ID colour other than the modal one.
MaterialView IdView(const IdMap& id, const std::vector<bool>& inside) {
    MaterialView view;
    view.view = MaterialViewKind::ID;
    view.values = Blank(id.operands, 3);
    view.leaks = Blank(id.operands, 1);
    std::map<std::array<uint32_t, 3>, uint64_t> counts;
    for (size_t t = 0; t < inside.size(); ++t) {
        if (inside[t]) ++counts[id.codes[t]];
    }
    if (counts.empty()) return view;
    // The modal colour; ties go to the smallest code triple (the map's first).
    auto modal = counts.begin();
    for (auto it = counts.begin(); it != counts.end(); ++it) {
        if (it->second > modal->second) modal = it;
    }
    size_t modalTexel = 0;
    while (!inside[modalTexel] || id.codes[modalTexel] != modal->first) ++modalTexel;
    const std::array<float, 3> own{id.operands.values[modalTexel * 3], id.operands.values[modalTexel * 3 + 1],
                                   id.operands.values[modalTexel * 3 + 2]};
    view.modalId = own;
    for (size_t t = 0; t < inside.size(); ++t) {
        if (!inside[t]) continue;
        const std::array<float, 3> value{id.operands.values[t * 3], id.operands.values[t * 3 + 1],
                                         id.operands.values[t * 3 + 2]};
        for (uint32_t c = 0; c < 3; ++c) view.values.values[t * 3 + c] = value[c];
        if (id.codes[t] == modal->first) continue;
        view.leaks.values[t] = 1.0f;
        view.leakTexels.push_back({static_cast<uint32_t>(t % id.operands.width),
                                   static_cast<uint32_t>(t / id.operands.width), value, own});
    }
    return view;
}

/// A channel view: the full values inside the region; a leak where they differ from the solo ones.
MaterialView ChannelView(MaterialViewKind kind, const DiagnosticMap& full, const DiagnosticMap& solo,
                         const std::vector<bool>& inside) {
    MaterialView view;
    view.view = kind;
    view.values = Blank(full, full.components);
    view.leaks = Blank(full, 1);
    const uint32_t components = full.components;
    for (size_t t = 0; t < inside.size(); ++t) {
        if (!inside[t]) continue;
        bool leak = false;
        LeakTexel texel{static_cast<uint32_t>(t % full.width), static_cast<uint32_t>(t / full.width), {}, {}};
        for (uint32_t c = 0; c < components; ++c) {
            const float value = full.values[t * components + c];
            const float own = solo.values[t * components + c];
            view.values.values[t * components + c] = value;
            texel.value[c] = value;
            texel.own[c] = own;
            leak = leak || !SameBits(value, own);
        }
        if (!leak) continue;
        view.leaks.values[t] = 1.0f;
        view.leakTexels.push_back(texel);
    }
    return view;
}

struct MaterialContext {
    const core::TextureSet* set = nullptr;
    const core::Stack* stack = nullptr;
    std::vector<const Layer*> path;
};

render::Result<MaterialContext> MaterialOf(const core::Project& project, core::Id material,
                                           const DiagnosticRequest& request) {
    MaterialContext ctx;
    ctx.set = FindSet(project, request.textureSet);
    ctx.stack = core::FindStack(project, request.textureSet, request.stack);
    if (ctx.set == nullptr || ctx.stack == nullptr) return StackNotFound(request);
    if (!PathTo(ctx.stack->root_layers, material, ctx.path)) {
        return EvalFail(EvalErrorKind::NotFound,
                        "material " + std::to_string(material) + " is not a layer of stack " +
                            std::to_string(request.stack));
    }
    if (ctx.path.back()->kind == core::LayerKind::instance) {
        return EvalFail(EvalErrorKind::UnsupportedNode,
                        "an instance layer is not a material (its solo is undefined): name its source", material);
    }
    return ctx;
}

/// The material views of `material`, all of them or only `only` (which then must be available).
render::Result<MaterialViews> MaterialViewsOf(const core::Project& project, std::int64_t revision, core::Id material,
                                              const DiagnosticRequest& request, const TemplateLibrary& templates,
                                              ITileStore& store, TileCache& cache,
                                              std::optional<MaterialViewKind> only) {
    render::Result<MaterialContext> ctx = MaterialOf(project, material, request);
    if (!ctx) return render::Unexpected(ctx.error());
    MaterialViews result;
    result.material = material;
    render::Result<DiagnosticMap> mask =
        EffectiveMask(project, ctx->path, *ctx->stack, request, templates, store, cache);
    if (!mask) return render::Unexpected(mask.error());
    result.mask = std::move(*mask);
    std::vector<bool> inside(result.mask.values.size());
    for (size_t t = 0; t < inside.size(); ++t) {
        inside[t] = result.mask.values[t] >= kInsideThreshold;
        if (inside[t]) ++result.inside;
    }

    auto wanted = [&](MaterialViewKind kind) { return !only || *only == kind; };
    if (wanted(MaterialViewKind::ID)) {
        render::Result<std::optional<IdMap>> id = IdMeshMap(*ctx->set, request);
        if (!id) return render::Unexpected(id.error());
        if (*id) {
            result.views.push_back(IdView(**id, inside));
        } else {
            result.missing.push_back(MaterialViewKind::ID);
        }
    }
    std::optional<core::Project> solo;
    for (size_t k = 1; k < kViewNames.size(); ++k) {
        const auto kind = static_cast<MaterialViewKind>(k);
        if (!wanted(kind)) continue;
        const ChannelType channel = kViewChannels[k];
        if (!ctx->stack->channels.contains(channel)) {
            result.missing.push_back(kind);
            continue;
        }
        if (!solo) {
            solo = project;
            KeepOnly(MutableStack(*solo, request.textureSet, request.stack)->root_layers, material);
        }
        const DiagnosticMapId map = DiagnosticMapId::Channel(channel);
        render::Result<DiagnosticMap> full =
            EvaluateMapOn(project, revision, map, request, templates, store, cache);
        if (!full) return render::Unexpected(full.error());
        render::Result<DiagnosticMap> own = EvaluateMapOn(*solo, revision, map, request, templates, store, cache);
        if (!own) return render::Unexpected(own.error());
        result.views.push_back(ChannelView(kind, *full, *own, inside));
        result.views.back().channel = channel;
    }
    if (only && result.views.empty()) {
        return EvalFail(EvalErrorKind::NotFound, "the " + std::string(MaterialViewName(*only)) +
                                                     " view is not available (no ID mesh map or no such channel)");
    }
    return result;
}

}  // namespace

std::string MapName(const DiagnosticMapId& map) {
    if (map.kind == DiagnosticMapId::Kind::VirtualNormal) {
        return std::string(kVirtualNormalNames[map.convention == core::NormalMapFormat::OpenGL ? 0 : 1]);
    }
    return std::string(core::ToString(map.channel));
}

render::Result<DiagnosticMapId> ParseMapName(std::string_view name) {
    if (name == kVirtualNormalNames[0]) return DiagnosticMapId::VirtualNormal(core::NormalMapFormat::OpenGL);
    if (name == kVirtualNormalNames[1]) return DiagnosticMapId::VirtualNormal(core::NormalMapFormat::DirectX);
    if (const std::optional<ChannelType> channel = core::FromString<ChannelType>(name)) {
        return DiagnosticMapId::Channel(*channel);
    }
    return EvalFail(EvalErrorKind::NotFound, "no map named \"" + std::string(name) + "\"");
}

DiagnosticMap MapOf(const ChannelResult& result) {
    const TileFormat& format = result.tileFormat;
    const uint32_t channels = format.channels;
    const uint32_t bytes = format.BytesPerChannel();
    DiagnosticMap map{result.width, result.height, channels, {}};
    map.values.resize(size_t{result.width} * result.height * channels);
    for (const TileResult& tile : result.tiles) {
        for (uint32_t y = 0; y < tile.height; ++y) {
            for (uint32_t x = 0; x < tile.width; ++x) {
                for (uint32_t c = 0; c < channels; ++c) {
                    float value = 0.0f;
                    if (tile.constant) {
                        value = (*tile.constant)[c];
                    } else {
                        uint32_t stored = 0;
                        std::memcpy(&stored, tile.texels.data() + ((size_t{y} * tile.width + x) * channels + c) * bytes,
                                    bytes);
                        value = format.encoding == render::TexelEncoding::Float16
                                    ? arith::HalfToFloat(static_cast<uint16_t>(stored))
                                    : OperandOf(stored, format, c);
                    }
                    map.values[((size_t{tile.y0} + y) * result.width + tile.x0 + x) * channels + c] = value;
                }
            }
        }
    }
    return map;
}

render::Result<core::Project> HiddenCopy(const core::Project& project, core::Id textureSet, core::Id stack,
                                         std::span<const core::Id> nodes) {
    core::Project copy = project;
    core::Stack* target = MutableStack(copy, textureSet, stack);
    if (target == nullptr) {
        return EvalFail(EvalErrorKind::NotFound, "stack " + std::to_string(stack) + " is not in texture set " +
                                                     std::to_string(textureSet));
    }
    for (const core::Id node : nodes) {
        bool* visible = VisibilityOf(target->root_layers, node);
        if (visible == nullptr) {
            return EvalFail(EvalErrorKind::NotFound,
                            "node " + std::to_string(node) + " is not in stack " + std::to_string(stack));
        }
        *visible = false;
    }
    return copy;
}

render::Result<DiagnosticMap> EvaluateMapOn(const core::Project& project, std::int64_t revision,
                                            const DiagnosticMapId& map, const DiagnosticRequest& request,
                                            const TemplateLibrary& templates, ITileStore& store, TileCache& cache) {
    if (map.kind == DiagnosticMapId::Kind::VirtualNormal) {
        VirtualNormalRequest normal;
        normal.textureSet = request.textureSet;
        normal.stack = request.stack;
        normal.kind = NormalSourceKind::Combined;
        normal.convention = map.convention;
        normal.templateId = request.templateId;
        normal.resources = request.resources;
        normal.geometry = request.geometry;
        render::Result<VirtualNormalResult> result =
            EvaluateVirtualNormalOn(project, revision, normal, templates, store, cache);
        render::Result<void> ended = EndEvaluation(store, cache);
        if (!result) return render::Unexpected(result.error());
        if (!ended) return render::Unexpected(ended.error());
        return DiagnosticMap{result->width, result->height, 3, std::move(result->texels)};
    }
    EvaluateRequest channel;
    channel.textureSet = request.textureSet;
    channel.stack = request.stack;
    channel.channel = map.channel;
    channel.templateId = request.templateId;
    channel.resources = request.resources;
    channel.geometry = request.geometry;
    render::Result<ChannelResult> result = EvaluateOn(project, channel, templates, store, cache);
    render::Result<void> ended = EndEvaluation(store, cache);
    if (!result) return render::Unexpected(result.error());
    if (!ended) return render::Unexpected(ended.error());
    return MapOf(*result);
}

render::Result<IsolationResult> IsolateOn(const core::Project& project, std::int64_t revision,
                                          const DiagnosticMapId& map, core::Id node, const DiagnosticRequest& request,
                                          const TemplateLibrary& templates, ITileStore& store, TileCache& cache) {
    const core::Id nodes[1] = {node};
    render::Result<core::Project> hidden = HiddenCopy(project, request.textureSet, request.stack, nodes);
    if (!hidden) return render::Unexpected(hidden.error());
    IsolationResult result;
    result.node = node;
    // The copy found the node in the stack, so the revision holds it too.
    result.wasVisible = *VisibilityOf(core::FindStack(project, request.textureSet, request.stack)->root_layers, node);
    render::Result<DiagnosticMap> isolated = EvaluateMapOn(*hidden, revision, map, request, templates, store, cache);
    if (!isolated) return render::Unexpected(isolated.error());
    result.map = std::move(*isolated);
    return result;
}

render::Result<ContributionResult> ContributionOn(const core::Project& project, std::int64_t revision,
                                                  const DiagnosticMapId& map, core::Id node,
                                                  const DiagnosticRequest& request, const TemplateLibrary& templates,
                                                  ITileStore& store, TileCache& cache) {
    render::Result<IsolationResult> isolated = IsolateOn(project, revision, map, node, request, templates, store, cache);
    if (!isolated) return render::Unexpected(isolated.error());
    render::Result<DiagnosticMap> full = EvaluateMapOn(project, revision, map, request, templates, store, cache);
    if (!full) return render::Unexpected(full.error());
    ContributionResult result;
    result.node = node;
    result.full = std::move(*full);
    result.isolated = std::move(isolated->map);
    result.difference = Blank(result.full, result.full.components);
    for (size_t i = 0; i < result.full.values.size(); ++i) {
        result.difference.values[i] = result.full.values[i] - result.isolated.values[i];
    }
    return result;
}

std::string_view MaterialViewName(MaterialViewKind view) { return kViewNames[static_cast<size_t>(view)]; }

ChannelType MaterialViewChannel(MaterialViewKind view) { return kViewChannels[static_cast<size_t>(view)]; }

std::optional<MaterialViewKind> ParseMaterialView(std::string_view name) {
    for (size_t k = 0; k < kViewNames.size(); ++k) {
        if (kViewNames[k] == name) return static_cast<MaterialViewKind>(k);
    }
    return std::nullopt;
}

render::Result<MaterialViews> MaterialViewsOn(const core::Project& project, std::int64_t revision, core::Id material,
                                              const DiagnosticRequest& request, const TemplateLibrary& templates,
                                              ITileStore& store, TileCache& cache) {
    return MaterialViewsOf(project, revision, material, request, templates, store, cache, std::nullopt);
}

render::Result<DiagnosticMap> MaterialMaskOn(const core::Project& project, core::Id material,
                                             const DiagnosticRequest& request, const TemplateLibrary& templates,
                                             ITileStore& store, TileCache& cache) {
    render::Result<MaterialContext> ctx = MaterialOf(project, material, request);
    if (!ctx) return render::Unexpected(ctx.error());
    return EffectiveMask(project, ctx->path, *ctx->stack, request, templates, store, cache);
}

render::Result<RegionStats> ComputeRegionStats(const DiagnosticMap& map, const DiagnosticMap& mask) {
    if (mask.components != 1 || mask.width != map.width || mask.height != map.height ||
        map.values.size() != size_t{map.width} * map.height * map.components ||
        mask.values.size() != size_t{mask.width} * mask.height) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "region statistics need a one-component mask of the map's size");
    }
    RegionStats stats;
    stats.texels = size_t{map.width} * map.height;
    std::vector<double> maskValues(mask.values.begin(), mask.values.end());
    for (const double m : maskValues) {
        if (!std::isfinite(m)) return EvalFail(EvalErrorKind::UnsupportedSource, "a mask value is not finite");
    }
    stats.maskMean = stats.texels == 0 ? 0.0 : ExactSum(maskValues) / static_cast<double>(stats.texels);
    const uint32_t components = map.components;
    std::vector<std::vector<double>> values(components);
    std::vector<double> luminance;
    std::vector<double> saturation;
    for (size_t t = 0; t < stats.texels; ++t) {
        if (!(mask.values[t] >= kInsideThreshold)) continue;
        ++stats.inside;
        for (uint32_t c = 0; c < components; ++c) {
            const double v = map.values[t * components + c];
            if (!std::isfinite(v)) {
                return EvalFail(EvalErrorKind::UnsupportedSource, "a map value inside the mask is not finite");
            }
            values[c].push_back(v);
        }
        if (components == 3) {
            const double r = map.values[t * 3];
            const double g = map.values[t * 3 + 1];
            const double b = map.values[t * 3 + 2];
            luminance.push_back(((r + g) + b) / 3.0);
            const double high = std::max(std::max(r, g), b);
            const double low = std::min(std::min(r, g), b);
            saturation.push_back(high > 0.0 ? (high - low) / high : 0.0);
        }
    }
    stats.coverage = stats.texels == 0 ? 0.0 : static_cast<double>(stats.inside) / static_cast<double>(stats.texels);
    if (stats.inside == 0) return stats;
    for (uint32_t c = 0; c < components; ++c) stats.components.push_back(StatsOf(std::move(values[c])));
    if (components == 3) {
        stats.luminance = StatsOf(std::move(luminance));
        stats.saturation = StatsOf(std::move(saturation));
    }
    return stats;
}

std::string RegionStatsJson(const RegionStats& stats) {
    std::string out = "{\"texels\":" + std::to_string(stats.texels) + ",\"inside\":" + std::to_string(stats.inside) +
                      ",\"coverage\":";
    AppendDouble(out, stats.coverage);
    out += ",\"mask_mean\":";
    AppendDouble(out, stats.maskMean);
    out += ",\"components\":[";
    for (size_t c = 0; c < stats.components.size(); ++c) {
        if (c != 0) out += ',';
        AppendStats(out, stats.components[c]);
    }
    out += "],\"luminance\":";
    if (stats.luminance) {
        AppendStats(out, *stats.luminance);
    } else {
        out += "null";
    }
    out += ",\"saturation\":";
    if (stats.saturation) {
        AppendStats(out, *stats.saturation);
    } else {
        out += "null";
    }
    out += '}';
    return out;
}

std::string SourceName(const DiagnosticSource& source) {
    const std::string kind(kKindNames[static_cast<size_t>(source.kind)]);
    const std::string node = std::to_string(source.node);
    switch (source.kind) {
        case DiagnosticSource::Kind::MaterialMask: return kind + "/" + node;
        case DiagnosticSource::Kind::MaterialView:
        case DiagnosticSource::Kind::MaterialLeaks:
            return kind + "/" + std::string(MaterialViewName(source.view)) + "/" + node;
        case DiagnosticSource::Kind::Isolated:
        case DiagnosticSource::Kind::Contribution:
        case DiagnosticSource::Kind::RegionStats: return kind + "/" + MapName(source.map) + "/" + node;
    }
    return kind;
}

render::Result<DiagnosticSource> ParseSourceName(std::string_view name) {
    auto malformed = [&](const std::string& why) {
        return EvalFail(EvalErrorKind::NotFound, "diagnostic source \"" + std::string(name) + "\": " + why);
    };
    std::vector<std::string_view> parts;
    for (size_t start = 0;;) {
        const size_t slash = name.find('/', start);
        parts.push_back(name.substr(start, slash == std::string_view::npos ? std::string_view::npos : slash - start));
        if (slash == std::string_view::npos) break;
        start = slash + 1;
    }
    DiagnosticSource source;
    size_t k = 0;
    while (k < kKindNames.size() && kKindNames[k] != parts[0]) ++k;
    if (k == kKindNames.size()) return malformed("unknown kind");
    source.kind = static_cast<DiagnosticSource::Kind>(k);
    const size_t expected = source.kind == DiagnosticSource::Kind::MaterialMask ? 2 : 3;
    if (parts.size() != expected) return malformed("expected " + std::to_string(expected) + " parts");
    const std::string_view uid = parts.back();
    const std::from_chars_result parsed = std::from_chars(uid.data(), uid.data() + uid.size(), source.node);
    if (uid.empty() || parsed.ec != std::errc{} || parsed.ptr != uid.data() + uid.size() || uid[0] == '0' ||
        source.node > core::kMaxId) {
        return malformed("the uid is not a positive decimal id");
    }
    switch (source.kind) {
        case DiagnosticSource::Kind::MaterialMask: break;
        case DiagnosticSource::Kind::MaterialView:
        case DiagnosticSource::Kind::MaterialLeaks: {
            const std::optional<MaterialViewKind> view = ParseMaterialView(parts[1]);
            if (!view) return malformed("unknown material view");
            source.view = *view;
            break;
        }
        case DiagnosticSource::Kind::Isolated:
        case DiagnosticSource::Kind::Contribution:
        case DiagnosticSource::Kind::RegionStats: {
            render::Result<DiagnosticMapId> map = ParseMapName(parts[1]);
            if (!map) return malformed("unknown map");
            source.map = *map;
            break;
        }
    }
    return source;
}

render::Result<DiagnosticOutput> EvaluateDiagnosticOn(const core::Project& project, std::int64_t revision,
                                                      const DiagnosticSource& source, const DiagnosticRequest& request,
                                                      const TemplateLibrary& templates, ITileStore& store,
                                                      TileCache& cache) {
    DiagnosticOutput output;
    output.source = source;
    output.revision = revision;
    switch (source.kind) {
        case DiagnosticSource::Kind::Isolated: {
            render::Result<IsolationResult> isolated =
                IsolateOn(project, revision, source.map, source.node, request, templates, store, cache);
            if (!isolated) return render::Unexpected(isolated.error());
            output.map = std::move(isolated->map);
            break;
        }
        case DiagnosticSource::Kind::Contribution: {
            render::Result<ContributionResult> contribution =
                ContributionOn(project, revision, source.map, source.node, request, templates, store, cache);
            if (!contribution) return render::Unexpected(contribution.error());
            output.map = std::move(contribution->difference);
            break;
        }
        case DiagnosticSource::Kind::MaterialMask: {
            render::Result<DiagnosticMap> mask = MaterialMaskOn(project, source.node, request, templates, store, cache);
            if (!mask) return render::Unexpected(mask.error());
            output.map = std::move(*mask);
            break;
        }
        case DiagnosticSource::Kind::MaterialView:
        case DiagnosticSource::Kind::MaterialLeaks: {
            render::Result<MaterialViews> views =
                MaterialViewsOf(project, revision, source.node, request, templates, store, cache, source.view);
            if (!views) return render::Unexpected(views.error());
            MaterialView& view = views->views.front();
            output.map = std::move(source.kind == DiagnosticSource::Kind::MaterialView ? view.values : view.leaks);
            break;
        }
        case DiagnosticSource::Kind::RegionStats: {
            render::Result<DiagnosticMap> mask = MaterialMaskOn(project, source.node, request, templates, store, cache);
            if (!mask) return render::Unexpected(mask.error());
            render::Result<DiagnosticMap> map = EvaluateMapOn(project, revision, source.map, request, templates, store, cache);
            if (!map) return render::Unexpected(map.error());
            render::Result<RegionStats> stats = ComputeRegionStats(*map, *mask);
            if (!stats) return render::Unexpected(stats.error());
            output.stats = std::move(*stats);
            break;
        }
    }
    return output;
}

}  // namespace uzp::evaluator
