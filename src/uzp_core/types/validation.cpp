#include "uzp_core/types/validation.h"

#include <cmath>
#include <map>
#include <set>
#include <type_traits>
#include <utility>
#include <variant>
#include <vector>

#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/resource_url.h"

namespace uzp::core {

Id Project::AllocateId() {
    if (next_id == kNoId || next_id > kMaxId) throw ValueError("the project's id space is exhausted");
    return next_id++;
}

namespace {

[[noreturn]] void Fail(const std::string& message) { throw ValueError(message); }

bool PowerOfTwoInRange(int value) {
    return value >= 128 && value <= 8192 && (value & (value - 1)) == 0;
}

std::string Label(Id uid, const std::string& name) {
    return "node " + std::to_string(uid) + " ('" + name + "')";
}

bool MaskOnly(NodeType type) {
    return type == NodeType::CompareMaskEffect || type == NodeType::ColorSelectionEffect;
}

void CheckResolution(const Resolution& resolution, const std::string& what) {
    if (!PowerOfTwoInRange(resolution.width) || !PowerOfTwoInRange(resolution.height)) {
        Fail(what + ": resolution " + std::to_string(resolution.width) + "x" +
             std::to_string(resolution.height) + " is not a power of two between 128 and 8192");
    }
}

void CheckFinite(double value, const std::string& what) {
    if (!std::isfinite(value)) Fail(what + " is not a finite number");
}

void CheckHash(const std::string& hash, const std::string& what) {
    if (!IsSha256Hex(hash)) Fail(what + " is not a lower-case SHA-256: '" + hash + "'");
}

void CheckAsset(const std::string& url, const std::string& what) {
    try {
        ParseAssetUrl(url);
    } catch (const ValueError& error) {
        Fail(what + ": " + error.what());
    }
}

/// Structural checks of one project, collecting ids and plane ids on the way.
class Checker {
public:
    explicit Checker(const Project& project) : project_(project) {}

    void Run() {
        const Versions& v = project_.versions;
        if (v.format_version.empty() || v.app_version.empty() || v.evaluator_profile.empty() ||
            v.compat_profile.empty()) {
            Fail("versions: format_version, app_version, evaluator_profile and compat_profile are required");
        }
        if (project_.next_id == kNoId || project_.next_id - 1 > kMaxId) {
            Fail("next_id " + std::to_string(project_.next_id) + " is outside 1.." +
                 std::to_string(kMaxId) + "+1");
        }
        const ProjectSettings& s = project_.settings;
        CheckResolution(s.default_resolution, "settings.default_resolution");
        CheckFinite(s.mesh_unit_scale, "settings.mesh_unit_scale");
        if (s.mesh_unit_scale <= 0.0) Fail("settings.mesh_unit_scale must be positive");
        if (!s.color_management.config_hash.empty()) {
            CheckHash(s.color_management.config_hash, "settings.color_management.config_hash");
        }
        CheckResources();
        if (project_.mesh) Resource(project_.mesh->resource, "mesh.resource");
        if (project_.display.environment.resource) {
            Resource(*project_.display.environment.resource, "display.environment.resource");
        }
        if (project_.display.color_lut) Resource(*project_.display.color_lut, "display.color_lut");
        std::set<std::string> set_names;
        for (const TextureSet& set : project_.texture_sets) {
            if (!set_names.insert(set.name).second) Fail("texture set name '" + set.name + "' is not unique");
            CheckTextureSet(set);
        }
    }

private:
    void AddId(Id id, const std::string& what) {
        if (id == kNoId || id > kMaxId) Fail(what + " has no valid id");
        if (id >= project_.next_id) {
            Fail(what + " has id " + std::to_string(id) + ", not below next_id " +
                 std::to_string(project_.next_id));
        }
        if (!ids_.insert(id).second) Fail(what + " reuses id " + std::to_string(id));
    }

    void Resource(const std::string& hash, const std::string& what) {
        CheckHash(hash, what);
        if (!project_.resources.contains(hash)) Fail(what + " names resource " + hash + ", which is not stored");
    }

    void Binding(const ResourceBinding& binding, const std::string& what) {
        Resource(binding.sha256, what);
        if (binding.alias && binding.alias->empty()) Fail(what + ": an alias must not be empty");
    }

    void CheckResources() {
        for (const auto& [hash, entries] : project_.resources) {
            CheckHash(hash, "resources key");
            if (entries.empty()) Fail("resource " + hash + " has no entry");
            std::set<std::string> names;
            for (const ResourceMeta& meta : entries) {
                const std::string what = "resource " + hash + " entry '" + meta.name + "'";
                AddId(meta.id, what);
                if (meta.name.empty()) Fail("resource " + hash + " has an entry without a name");
                if (!names.insert(meta.name).second) Fail(what + " is listed twice");
                if (meta.size < 0) Fail(what + ": size is negative");
                if (meta.mime != entries.front().mime || meta.size != entries.front().size) {
                    Fail("resource " + hash + ": entries disagree on mime or size of the shared bytes");
                }
            }
        }
    }

    void CheckTextureSet(const TextureSet& set) {
        const std::string what = "texture set '" + set.name + "'";
        AddId(set.id, what);
        if (set.name.empty()) Fail("a texture set needs a name");
        CheckResolution(set.resolution, what);
        if (set.uv_tiles.empty()) Fail(what + " has no UV tile");
        std::set<int> udims;
        for (const UVTile& tile : set.uv_tiles) {
            AddId(tile.id, what + " UV tile " + std::to_string(tile.udim));
            const int index = tile.udim - 1001;
            if (index < 0 || index > 999) {
                Fail(what + ": UV tile " + std::to_string(tile.udim) + " is not a UDIM tile");
            }
            if (!udims.insert(tile.udim).second) Fail(what + ": UV tile " + std::to_string(tile.udim) + " is listed twice");
        }
        if (project_.settings.workflow == ProjectWorkflow::Default &&
            (set.uv_tiles.size() != 1 || set.uv_tiles.front().udim != 1001)) {
            Fail(what + ": the Default workflow has the single UV tile 1001");
        }
        for (const auto& [usage, binding] : set.mesh_maps) {
            const std::string map = what + " mesh map " + std::string(ToString(usage));
            Resource(binding.resource, map + " resource");
            if (const auto* imported = std::get_if<ImportedProvenance>(&binding.provenance)) {
                CheckHash(imported->source_sha256, map + " source_sha256");
            } else {
                const auto& baked = std::get<BakedProvenance>(binding.provenance);
                if (baked.baker_version.empty()) Fail(map + ": baker_version is required");
                CheckHash(baked.settings_hash, map + " settings_hash");
                for (const std::string& hash : baked.high_meshes) CheckHash(hash, map + " high_meshes");
                if (baked.cage) CheckHash(*baked.cage, map + " cage");
                CheckHash(baked.mesh_hashes.positions, map + " mesh_hashes.positions");
                CheckHash(baked.mesh_hashes.uvs, map + " mesh_hashes.uvs");
                CheckHash(baked.mesh_hashes.corner_normals, map + " mesh_hashes.corner_normals");
                CheckHash(baked.mesh_hashes.triangulation, map + " mesh_hashes.triangulation");
            }
            if (binding.invalid_report && !binding.invalid) Fail(map + ": invalid_report without the invalid flag");
        }
        if (set.stacks.empty()) Fail(what + " has no stack");
        std::set<std::string> stack_names;
        for (const Stack& stack : set.stacks) {
            if (!stack_names.insert(stack.name).second) Fail(what + ": stack name '" + stack.name + "' is not unique");
            AddId(stack.id, what + " stack '" + stack.name + "'");
            stack_ = &stack;
            for (const Layer& layer : stack.root_layers) CheckLayer(layer);
        }
    }

    void Channel(ChannelType channel, const std::string& what) {
        if (!stack_->channels.contains(channel)) {
            Fail(what + ": channel " + std::string(ToString(channel)) + " is not a channel of stack '" +
                 stack_->name + "'");
        }
    }

    void Opacity(const Blending& blending, const std::string& what) {
        if (!(blending.opacity >= 0.0 && blending.opacity <= 1.0)) Fail(what + ": opacity outside 0..1");
    }

    void PerChannel(const ChannelBlending& blending, const std::string& what) {
        for (const auto& [channel, value] : blending) {
            Channel(channel, what + " blending");
            Opacity(value, what);
        }
    }

    void Levels(const LevelsParams& levels, bool mask, const std::string& what) {
        if (mask) {
            if (levels.affected_channel) Fail(what + ": a mask-stack levels effect has no affected channel");
            if (levels.components.size() != 1) Fail(what + ": a mask-stack levels effect has one component");
        } else {
            if (levels.affected_channel) Channel(*levels.affected_channel, what + " affected_channel");
            if (levels.components.size() != 1 && levels.components.size() != 3) {
                Fail(what + ": levels have one (mono) or three (RGB) components");
            }
        }
        for (const LevelsComponent& c : levels.components) {
            for (const double value : {c.input_min, c.input_max, c.gamma, c.output_min, c.output_max}) {
                CheckFinite(value, what + " levels value");
            }
            if (c.gamma <= 0.0) Fail(what + ": levels gamma must be positive");
        }
    }

    void Procedural(const ProceduralRef& ref, bool mask, const std::string& what) {
        CheckAsset(ref.asset, what + " asset");
        for (const auto& [input, binding] : ref.image_inputs) Binding(binding, what + " image input '" + input + "'");
        for (const auto& [channel, output] : ref.output_mapping) {
            const auto type = FromString<ChannelType>(channel);
            if (!type) Fail(what + ": output_mapping key '" + channel + "' is not a ChannelType");
            if (mask) Fail(what + ": a mask-stack procedural maps its mask_output, not channels");
            Channel(*type, what + " output_mapping");
            if (output.empty()) Fail(what + ": output_mapping names an empty output");
        }
        if (ref.resolution_override) {
            if (const auto* legacy = std::get_if<Resolution>(&*ref.resolution_override)) {
                if (legacy->extra.contains("mode") || legacy->extra.contains("value") || legacy->extra.contains("log2_offset")) {
                    Fail(what + " resolution_override: mixed legacy and mode-based resolution");
                }
                CheckResolution(*legacy, what + " resolution_override");
            } else {
                const auto& r = std::get<ProceduralResolutionOverride>(*ref.resolution_override);
                if (r.extra.contains("width") || r.extra.contains("height")) {
                    Fail(what + " resolution_override: mixed legacy and mode-based resolution");
                }
                if (static_cast<size_t>(r.mode) >= EnumTable<ProceduralResolutionMode>::names.size()) {
                    Fail(what + " resolution_override: unknown mode");
                }
                for (const int size : r.value) {
                    if (!PowerOfTwoInRange(size) || size > 4096) {
                        Fail(what + " resolution_override.value: expected powers of two between 128 and 4096");
                    }
                }
            }
        }
    }

    void SourceCheck(const Source& source, bool mask, const std::string& what) {
        std::visit(
            [&](const auto& s) {
                using T = std::decay_t<decltype(s)>;
                if constexpr (std::is_same_v<T, UniformColorSource>) {
                    for (const double c : s.rgb) CheckFinite(c, what + " colour component");
                } else if constexpr (std::is_same_v<T, BitmapSource> || std::is_same_v<T, VectorSource> ||
                                     std::is_same_v<T, FontSource>) {
                    Binding(s.resource, what + " resource");
                } else if constexpr (std::is_same_v<T, ProceduralSource>) {
                    Procedural(s.ref, mask, what);
                } else {
                    if (s.anchor == kNoId) Fail(what + ": a reference source names no anchor");
                    if (!s.channel_mapping.empty() && s.referenced_channel) {
                        Fail(what + ": a reference source has a channel mapping or one referenced channel, not both");
                    }
                    if (mask && !s.channel_mapping.empty()) Fail(what + ": a mask-stack reference maps no channels");
                    for (const auto& [channel, referenced] : s.channel_mapping) Channel(channel, what + " channel_mapping");
                    if (s.levels) Levels(*s.levels, mask, what + " reference levels");
                }
            },
            source.value);
    }

    void Fill(const FillContent& fill, bool mask, const std::string& what) {
        if (mask) {
            if (!fill.sources.empty() || fill.material_source || !fill.active_channels.empty()) {
                Fail(what + ": a mask-stack fill is mono-channel (one source, no channels)");
            }
            if (fill.mono_source) SourceCheck(*fill.mono_source, true, what + " source");
        } else {
            if (fill.mono_source) Fail(what + ": a content fill has per-channel sources");
            for (const auto& [channel, source] : fill.sources) {
                Channel(channel, what + " sources");
                SourceCheck(source, false, what + " source " + std::string(ToString(channel)));
            }
            for (const ChannelType channel : fill.active_channels) Channel(channel, what + " active_channels");
            if (fill.material_source) SourceCheck(*fill.material_source, false, what + " material_source");
        }
        const UVTransformation& t = fill.projection.uv.uv_transformation;
        for (const double value : {t.scale[0], t.scale[1], t.rotation, t.offset[0], t.offset[1]}) {
            CheckFinite(value, what + " uv_transformation");
        }
    }

    void Paint(const PaintContent& paint, bool mask, const std::string& what) {
        if (mask && !paint.planes.empty()) Fail(what + ": a mask-stack paint node holds one plane");
        if (!mask && paint.mono_plane) Fail(what + ": a content paint node holds one plane per channel");
        const auto plane = [&](Id id) {
            if (id == kNoId) Fail(what + ": plane_id 0 is not a plane");
            if (!planes_.insert(id).second) Fail(what + ": plane " + std::to_string(id) + " is already bound to another node");
        };
        for (const auto& [channel, id] : paint.planes) {
            Channel(channel, what + " planes");
            plane(id);
        }
        if (paint.mono_plane) plane(*paint.mono_plane);
    }

    void CheckEffect(const Effect& effect, bool mask, const std::string& owner) {
        const std::string what = Label(effect.uid, effect.name) + " in " + owner;
        AddId(effect.uid, what);
        const NodeType type = effect.type();
        if (!mask && MaskOnly(type)) Fail(what + ": " + std::string(ToString(type)) + " is allowed only in mask stacks");
        if (mask) {
            if (!effect.blending.empty()) Fail(what + ": mask-stack blending is mono-channel");
            if (!effect.mono_blending) Fail(what + ": a mask-stack effect needs its mono blending");
            Opacity(*effect.mono_blending, what);
            if (!effect.active_channels.empty()) Fail(what + ": a mask-stack effect has no active channels");
        } else {
            if (effect.mono_blending) Fail(what + ": a content effect blends per channel");
            PerChannel(effect.blending, what);
            if (!effect.active_channels.empty() && effect.kind != EffectKind::generator &&
                effect.kind != EffectKind::filter) {
                Fail(what + ": active_channels belong to generator and filter effects (fills keep theirs in the fill)");
            }
            for (const ChannelType channel : effect.active_channels) Channel(channel, what + " active_channels");
        }
        const bool is_fill = effect.kind == EffectKind::fill;
        const bool is_paint = effect.kind == EffectKind::paint;
        const bool is_procedural = effect.kind == EffectKind::generator || effect.kind == EffectKind::filter;
        if (is_fill != effect.fill.has_value()) Fail(what + ": a fill payload belongs to fill effects only, which need one");
        if (is_paint != effect.paint.has_value()) Fail(what + ": a paint payload belongs to paint effects only, which need one");
        if (!is_procedural && effect.procedural) Fail(what + ": a procedural payload belongs to generator and filter effects");
        // SourceSubstance.resolution raises ValueError for a source used by a FilterEffectNode
        // (python-doc; phase3.2_proc-filter-families 2.4, decision 328).
        if (effect.kind == EffectKind::filter && effect.procedural && effect.procedural->resolution_override) {
            Fail(what + ": the source of a filter effect has no resolution override");
        }
        if (effect.kind != EffectKind::levels && effect.levels) Fail(what + ": levels parameters belong to levels effects");
        if (effect.kind != EffectKind::compare_mask && effect.compare_mask) Fail(what + ": compare_mask parameters belong to compare mask effects");
        if (effect.kind != EffectKind::color_selection && effect.color_selection) {
            Fail(what + ": color_selection parameters belong to colour selection effects");
        }
        if ((effect.kind == EffectKind::anchor) != effect.anchor_name.has_value()) {
            Fail(what + ": an anchor name belongs to anchor point effects only, which need one");
        }
        if (effect.fill) Fill(*effect.fill, mask, what);
        if (effect.paint) Paint(*effect.paint, mask, what);
        if (effect.procedural) Procedural(*effect.procedural, mask, what);
        if (effect.levels) Levels(*effect.levels, mask, what);
        if (effect.preset_ref) {
            if (effect.preset_ref->kind != PresetKind::smart_mask || !mask) {
                Fail(what + ": only mask-stack effects carry smart-mask provenance");
            }
            CheckAsset(effect.preset_ref->asset, what + " preset_ref");
        }
    }

    void CheckLayer(const Layer& layer) {
        const std::string what = Label(layer.uid, layer.name);
        AddId(layer.uid, what);
        PerChannel(layer.blending, what);
        for (const Effect& effect : layer.content_effects) CheckEffect(effect, false, what + " content");
        if (layer.mask) {
            Opacity(layer.mask->blending, what + " mask");
            for (const Effect& effect : layer.mask->effects) CheckEffect(effect, true, what + " mask");
        }
        for (const std::string& item : layer.geometry_mask.items) {
            if (item.empty()) Fail(what + ": a geometry mask item is empty");
        }
        if ((layer.kind == LayerKind::fill) != layer.fill.has_value()) {
            Fail(what + ": a fill payload belongs to fill layers only, which need one");
        }
        if ((layer.kind == LayerKind::paint) != layer.paint.has_value()) {
            Fail(what + ": a paint payload belongs to paint layers only, which need one");
        }
        if (layer.kind != LayerKind::group && (!layer.children.empty() || layer.collapsed)) {
            Fail(what + ": only group layers hold sub-layers and a collapsed state");
        }
        if ((layer.kind == LayerKind::instance) != (layer.instance_source != kNoId)) {
            Fail(what + ": an instance source belongs to instance layers only, which need one");
        }
        if (layer.preset_ref) {
            if (layer.preset_ref->kind != PresetKind::smart_material || layer.kind != LayerKind::group) {
                Fail(what + ": only group layers carry smart-material provenance");
            }
            CheckAsset(layer.preset_ref->asset, what + " preset_ref");
        }
        if (layer.fill) Fill(*layer.fill, false, what);
        if (layer.paint) Paint(*layer.paint, false, what);
        for (const Layer& child : layer.children) CheckLayer(child);
    }

    const Project& project_;
    const Stack* stack_ = nullptr;
    std::set<Id> ids_;
    std::set<Id> planes_;
};

// ── Dependency graph of anchors and instances ────────────────────────────────────────────────

enum class Part { Effect, Base, Out };
using Vertex = std::pair<Id, Part>;

class AnchorGraph {
public:
    void Build(const Project& project) {
        for (const TextureSet& set : project.texture_sets) {
            for (const Stack& stack : set.stacks) {
                for (const Layer& layer : stack.root_layers) Collect(layer, set.id, stack.id);
            }
        }
        for (const TextureSet& set : project.texture_sets) {
            for (const Stack& stack : set.stacks) {
                for (const Layer& layer : stack.root_layers) AddLayer(layer, set.id, stack.id);
            }
        }
    }

    void CheckAcyclic() {
        std::map<Vertex, int> state;  // 0 unvisited, 1 on the path, 2 done
        std::vector<Vertex> path;
        for (const auto& [vertex, edges] : edges_) Visit(vertex, state, path);
    }

private:
    struct Place {
        Id set;
        Id stack;
    };

    void Collect(const Layer& layer, Id set, Id stack) {
        layers_[layer.uid] = {set, stack};
        const auto effects = [&](const std::vector<Effect>& list) {
            for (const Effect& effect : list) {
                if (effect.kind == EffectKind::anchor) anchors_[effect.uid] = {set, stack};
            }
        };
        effects(layer.content_effects);
        if (layer.mask) effects(layer.mask->effects);
        for (const Layer& child : layer.children) Collect(child, set, stack);
    }

    void References(const Vertex& from, const std::optional<FillContent>& fill, Id set, const std::string& what) {
        if (!fill) return;
        const auto add = [&](const Source& source) {
            const auto* reference = std::get_if<ReferenceSource>(&source.value);
            if (reference == nullptr) return;
            const auto anchor = anchors_.find(reference->anchor);
            if (anchor == anchors_.end()) {
                Fail(what + " references " + std::to_string(reference->anchor) + ", which is not an anchor point effect");
            }
            if (anchor->second.set != set) {
                Fail(what + " references anchor " + std::to_string(reference->anchor) + " of another texture set");
            }
            edges_[from].push_back({reference->anchor, Part::Effect});
        };
        for (const auto& [channel, source] : fill->sources) add(source);
        if (fill->mono_source) add(*fill->mono_source);
        if (fill->material_source) add(*fill->material_source);
    }

    /// Chains a list of effects after `previous` (or from nothing when it is empty): each effect
    /// depends on the one before it. Returns the last vertex.
    std::optional<Vertex> Chain(const std::vector<Effect>& effects, std::optional<Vertex> previous, Id set,
                                const std::string& owner) {
        for (const Effect& effect : effects) {
            const Vertex vertex{effect.uid, Part::Effect};
            edges_[vertex];
            if (previous) edges_[vertex].push_back(*previous);
            References(vertex, effect.fill, set, Label(effect.uid, effect.name) + " in " + owner);
            previous = vertex;
        }
        return previous;
    }

    void AddLayer(const Layer& layer, Id set, Id stack) {
        const std::string what = Label(layer.uid, layer.name);
        const Vertex base{layer.uid, Part::Base};
        const Vertex out{layer.uid, Part::Out};
        edges_[base];
        References(base, layer.fill, set, what);
        for (const Layer& child : layer.children) edges_[base].push_back({child.uid, Part::Out});
        if (layer.kind == LayerKind::instance) {
            const auto source = layers_.find(layer.instance_source);
            if (source == layers_.end()) {
                Fail(what + " instances " + std::to_string(layer.instance_source) + ", which is not a layer");
            }
            if (source->second.set != set || source->second.stack != stack) {
                Fail(what + " instances a layer of another stack");
            }
            edges_[base].push_back({layer.instance_source, Part::Out});
        }
        const auto content = Chain(layer.content_effects, base, set, what + " content");
        edges_[out].push_back(*content);
        if (layer.mask) {
            if (const auto mask = Chain(layer.mask->effects, std::nullopt, set, what + " mask")) {
                edges_[out].push_back(*mask);
            }
        }
        for (const Layer& child : layer.children) AddLayer(child, set, stack);
    }

    void Visit(const Vertex& vertex, std::map<Vertex, int>& state, std::vector<Vertex>& path) {
        int& mark = state[vertex];
        if (mark == 2) return;
        if (mark == 1) {
            std::string cycle;
            bool on_cycle = false;
            for (const Vertex& v : path) {
                if (v == vertex) on_cycle = true;
                if (on_cycle) cycle += std::to_string(v.first) + " -> ";
            }
            Fail("anchor reference cycle: " + cycle + std::to_string(vertex.first));
        }
        mark = 1;
        path.push_back(vertex);
        for (const Vertex& next : edges_[vertex]) Visit(next, state, path);
        path.pop_back();
        state[vertex] = 2;
    }

    std::map<Id, Place> layers_;
    std::map<Id, Place> anchors_;
    std::map<Vertex, std::vector<Vertex>> edges_;
};

// ── Insertion ─────────────────────────────────────────────────────────────────────────────────

/// Where a node lives: the list holding it and, for effects, whether that list is a mask stack.
struct Location {
    std::vector<Layer>* layers = nullptr;    // the node is a layer in this list
    std::vector<Effect>* effects = nullptr;  // the node is an effect in this list
    bool in_mask = false;
    std::size_t index = 0;
};

bool Locate(std::vector<Layer>& layers, Id uid, Location& out) {
    for (std::size_t i = 0; i < layers.size(); ++i) {
        Layer& layer = layers[i];
        if (layer.uid == uid) {
            out = {&layers, nullptr, false, i};
            return true;
        }
        const auto in_effects = [&](std::vector<Effect>& effects, bool mask) {
            for (std::size_t j = 0; j < effects.size(); ++j) {
                if (effects[j].uid == uid) {
                    out = {nullptr, &effects, mask, j};
                    return true;
                }
            }
            return false;
        };
        if (in_effects(layer.content_effects, false)) return true;
        if (layer.mask && in_effects(layer.mask->effects, true)) return true;
        if (Locate(layer.children, uid, out)) return true;
    }
    return false;
}

std::optional<Location> Locate(Project& project, Id uid) {
    Location location;
    for (TextureSet& set : project.texture_sets) {
        for (Stack& stack : set.stacks) {
            if (Locate(stack.root_layers, uid, location)) return location;
        }
    }
    return std::nullopt;
}

Layer NewLayer(NodeType type, Id uid, std::string name, Id instance_source) {
    Layer layer;
    layer.uid = uid;
    layer.kind = LayerKindOf(type);
    layer.name = std::move(name);
    if (layer.kind == LayerKind::fill) layer.fill = FillContent{};
    if (layer.kind == LayerKind::paint) layer.paint = PaintContent{};
    if (layer.kind == LayerKind::instance) layer.instance_source = instance_source;
    return layer;
}

Effect NewEffect(NodeType type, Id uid, std::string name, bool mask) {
    Effect effect;
    effect.uid = uid;
    effect.kind = EffectKindOf(type);
    effect.name = std::move(name);
    if (mask) effect.mono_blending = Blending{};
    if (effect.kind == EffectKind::fill) effect.fill = FillContent{};
    if (effect.kind == EffectKind::paint) effect.paint = PaintContent{};
    if (effect.kind == EffectKind::anchor) effect.anchor_name = effect.name;
    return effect;
}

[[noreturn]] void Refuse(NodeType type, const std::string& where) {
    Fail("insertion failed: a " + std::string(ToString(type)) + " cannot be inserted " + where);
}

}  // namespace

void ValidateAnchorGraph(const Project& project) {
    AnchorGraph graph;
    graph.Build(project);
    graph.CheckAcyclic();
}

void Validate(const Project& project) {
    Checker(project).Run();
    ValidateAnchorGraph(project);
}

std::optional<NodeType> FindNodeType(const Project& project, Id uid) {
    const auto location = Locate(const_cast<Project&>(project), uid);
    if (!location) return std::nullopt;
    if (location->layers != nullptr) return (*location->layers)[location->index].type();
    return (*location->effects)[location->index].type();
}

Id InsertNode(Project& project, const InsertPosition& position, NodeType type, std::string name,
              Id instance_source) {
    if (type != NodeType::InstanceLayer && instance_source != kNoId) {
        Fail("insertion failed: only an InstanceLayer has an instance source");
    }
    Project copy = project;
    const Id uid = copy.AllocateId();
    const bool layer = IsLayerType(type);
    switch (position.kind) {
        case InsertPosition::Kind::TopOfStack: {
            Stack* target = nullptr;
            for (TextureSet& set : copy.texture_sets) {
                if (set.id != position.texture_set) continue;
                for (Stack& stack : set.stacks) {
                    if (stack.id == position.stack) target = &stack;
                }
            }
            if (target == nullptr) Fail("insertion failed: no stack " + std::to_string(position.stack) + " in texture set " + std::to_string(position.texture_set));
            if (!layer) Refuse(type, "at the top of a layer stack");
            target->root_layers.insert(target->root_layers.begin(), NewLayer(type, uid, std::move(name), instance_source));
            break;
        }
        case InsertPosition::Kind::AboveNode:
        case InsertPosition::Kind::BelowNode: {
            const auto location = Locate(copy, position.node);
            if (!location) Fail("insertion failed: no node " + std::to_string(position.node));
            const std::size_t index = location->index + (position.kind == InsertPosition::Kind::BelowNode ? 1 : 0);
            if (location->layers != nullptr) {
                if (!layer) Refuse(type, "beside a layer");
                location->layers->insert(location->layers->begin() + static_cast<std::ptrdiff_t>(index),
                                         NewLayer(type, uid, std::move(name), instance_source));
            } else {
                if (layer) Refuse(type, "beside an effect");
                if (!location->in_mask && MaskOnly(type)) Refuse(type, "into a content stack");
                location->effects->insert(location->effects->begin() + static_cast<std::ptrdiff_t>(index),
                                          NewEffect(type, uid, std::move(name), location->in_mask));
            }
            break;
        }
        case InsertPosition::Kind::InsideNode: {
            const auto location = Locate(copy, position.node);
            if (!location) Fail("insertion failed: no node " + std::to_string(position.node));
            if (location->layers == nullptr) Refuse(type, "inside an effect");
            Layer& parent = (*location->layers)[location->index];
            switch (position.node_stack) {
                case NodeStack::Substack:
                    if (parent.kind != LayerKind::group) Refuse(type, "into the sub-stack of a non-group layer");
                    if (!layer) Refuse(type, "into a group's sub-stack");
                    parent.children.insert(parent.children.begin(), NewLayer(type, uid, std::move(name), instance_source));
                    break;
                case NodeStack::Content:
                    if (layer) Refuse(type, "into a content stack");
                    if (MaskOnly(type)) Refuse(type, "into a content stack");
                    parent.content_effects.insert(parent.content_effects.begin(), NewEffect(type, uid, std::move(name), false));
                    break;
                case NodeStack::Mask:
                    if (layer) Refuse(type, "into a mask stack");
                    if (!parent.mask) Refuse(type, "into the mask stack of a layer without a mask");
                    parent.mask->effects.insert(parent.mask->effects.begin(), NewEffect(type, uid, std::move(name), true));
                    break;
            }
            break;
        }
    }
    Validate(copy);
    project = std::move(copy);
    return uid;
}

}  // namespace uzp::core
