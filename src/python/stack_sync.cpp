// The native composite `layerstack.sync_stack` and shared node edits (stack_sync.h).

#include "python/stack_sync.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <set>

#include "evaluator/sources.h"
#include "python/session.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

namespace uzp::python {

namespace {

using core::json::Array;
using core::json::Object;
using core::json::Value;

[[noreturn]] void Invalid(const std::string& message) { throw core::ValueError("sync_stack: " + message); }

const Value* Member(const Object& object, std::string_view key) {
    const auto it = object.find(key);
    return it == object.end() || it->second.IsNull() ? nullptr : &it->second;
}

std::string String(const Object& object, std::string_view key, const std::string& where) {
    const Value* value = Member(object, key);
    if (value == nullptr || !value->IsString()) Invalid(where + ": '" + std::string(key) + "' must be a string");
    return std::get<std::string>(value->data);
}

std::optional<std::string> OptionalString(const Object& object, std::string_view key, const std::string& where) {
    if (Member(object, key) == nullptr) return std::nullopt;
    return String(object, key, where);
}

double Number(const Value& value, const std::string& where) {
    if (value.IsInt()) return static_cast<double>(std::get<std::int64_t>(value.data));
    if (value.IsDouble()) return std::get<double>(value.data);
    Invalid(where + " must be a number");
}

std::optional<double> OptionalNumber(const Object& object, std::string_view key, const std::string& where) {
    const Value* value = Member(object, key);
    if (value == nullptr) return std::nullopt;
    return Number(*value, where + ": '" + std::string(key) + "'");
}

const Array& Items(const Object& object, std::string_view key) {
    const Value* value = Member(object, key);
    if (value == nullptr || !value->IsArray()) Invalid("'" + std::string(key) + "' must be a list");
    return std::get<Array>(value->data);
}

const Object& AsObject(const Value& value, const std::string& where) {
    if (!value.IsObject()) Invalid(where + " must be an object");
    return std::get<Object>(value.data);
}

/// Values are stored as float32, as every setter of the API stores them (bindings.h, `F32`).
double F32(double value) { return static_cast<double>(static_cast<float>(value)); }

core::Source Uniform(std::array<double, 3> rgb, const std::string& colour_space) {
    return core::Source{core::UniformColorSource{{F32(rgb[0]), F32(rgb[1]), F32(rgb[2])}, colour_space, {}}};
}

/// The facade's float32 sRGB decode of one component (`python/uzpainter_facade/colour.py`
/// `srgb_to_linear`): x = f32(v), ((x + 0.055f) / 1.055f) ^ 2.4f, the power of the float32
/// operands rounded once to float32.
double SrgbToLinear(double value) {
    const float x = static_cast<float>(value);
    if (x <= 0.04045f) return x / 12.92f;
    const float base = (x + 0.055f) / 1.055f;
    return static_cast<float>(std::pow(static_cast<double>(base), static_cast<double>(2.4f)));
}

core::Source Bitmap(const std::string& sha256, const std::string& colour_space) {
    return core::Source{core::BitmapSource{core::ResourceBinding{sha256, std::nullopt, {}}, colour_space, {}}};
}

/// A black mask holding one fill effect whose source is the image `sha256` in UV projection, in
/// the Data colour space Painter gives a bitmap bound in a mask.
core::Mask ImageMask(core::Edit& edit, const std::string& name, const std::string& sha256) {
    core::Effect effect;
    effect.uid = edit.AllocateId();
    effect.kind = core::EffectKind::fill;
    effect.name = name;
    effect.mono_blending = core::Blending{};
    core::FillContent fill;
    fill.mono_source = Bitmap(sha256, "Data");
    fill.projection.mode = core::ProjectionMode::UV;
    effect.fill = std::move(fill);
    core::Mask mask;
    mask.background = core::MaskBackground::Black;
    mask.effects.push_back(std::move(effect));
    return mask;
}

/// Erases `uid` from `layers` (any depth, effects included); true when found.
bool Erase(std::vector<core::Layer>& layers, core::Id uid) {
    for (auto it = layers.begin(); it != layers.end(); ++it) {
        if (it->uid == uid) {
            layers.erase(it);
            return true;
        }
    }
    for (core::Layer& layer : layers) {
        const auto erase_effect = [uid](std::vector<core::Effect>& effects) {
            const auto found = std::find_if(effects.begin(), effects.end(), [uid](const core::Effect& e) { return e.uid == uid; });
            if (found == effects.end()) return false;
            effects.erase(found);
            return true;
        };
        if (erase_effect(layer.content_effects)) return true;
        if (layer.mask && erase_effect(layer.mask->effects)) return true;
        if (Erase(layer.children, uid)) return true;
    }
    return false;
}

}  // namespace

void ApplyDefaultBlending(core::ChannelBlending& blending, const std::map<core::ChannelType, core::Channel>& channels) {
    if (channels.contains(core::ChannelType::Height)) {
        blending[core::ChannelType::Height] = core::Blending{core::BlendingMode::LinearDodge, 1.0, {}};
    }
    if (channels.contains(core::ChannelType::Normal)) {
        blending[core::ChannelType::Normal] = core::Blending{core::BlendingMode::NormalMapDetail, 1.0, {}};
    }
}

void ApplyDefaultSources(core::FillContent& fill, const std::map<core::ChannelType, core::Channel>& channels) {
    const auto set = [&](core::ChannelType channel, double value) {
        if (channels.contains(channel)) fill.sources[channel] = Uniform({value, value, value}, "Working");
    };
    set(core::ChannelType::BaseColor, 0.8);
    set(core::ChannelType::Height, 0.0);
}

void RemoveNode(core::Project& project, core::Id uid) {
    for (core::TextureSet& set : project.texture_sets) {
        for (core::Stack& stack : set.stacks) {
            if (Erase(stack.root_layers, uid)) return;
        }
    }
    throw core::ValueError("no node " + std::to_string(uid));
}

std::string ImportResource(core::Edit& edit, store::ProjectStore& store, std::string bytes, const std::string& name,
                           const std::string& mime, const std::string& usage, const std::string& origin) {
    const std::int64_t size = static_cast<std::int64_t>(bytes.size());
    const std::string sha256 = store.StageResource(std::move(bytes), mime);
    core::Project& project = edit.project();
    std::vector<core::ResourceMeta>& entries = project.resources[sha256];
    const bool known = std::any_of(entries.begin(), entries.end(), [&](const core::ResourceMeta& m) { return m.name == name; });
    if (known) {
        edit.NoteSkippedResource(sha256);
        return sha256;
    }
    if (!entries.empty() || edit.base().resources.contains(sha256)) edit.NoteSkippedResource(sha256);
    core::ResourceMeta meta;
    meta.id = edit.AllocateId();
    meta.name = name;
    meta.mime = mime;
    meta.size = size;
    meta.usage = usage;
    meta.origin = origin;
    meta.imported_at = NowUtc();
    entries.push_back(std::move(meta));
    return sha256;
}

Object SyncStack(core::Edit& edit, store::ProjectStore& store, const Object& stack_json, const ImageReader& read,
                 const SyncOptions& options) {
    // Read the whole stack before changing anything.
    const std::string title = String(stack_json, "title", "stack");
    struct Group {
        std::string key, name;
        std::optional<std::string> mask;
        bool replace_height = false;
    };
    struct LayerSpec {
        std::string group, name;
        std::optional<std::string> mask, base_tex;
        std::optional<std::array<double, 3>> base;
        std::optional<double> rough, metal, spec, height;
        double op = 1.0;
    };
    std::vector<Group> groups;
    std::set<std::string> keys;
    for (std::size_t i = 0; i < Items(stack_json, "groups").size(); ++i) {
        const std::string where = "groups[" + std::to_string(i) + "]";
        const Object& g = AsObject(Items(stack_json, "groups")[i], where);
        Group group{String(g, "key", where), String(g, "name", where), OptionalString(g, "mask", where), false};
        if (const Value* replace = Member(g, "replace_height")) {
            if (!replace->IsBool()) Invalid(where + ": 'replace_height' must be a boolean");
            group.replace_height = std::get<bool>(replace->data);
        }
        if (!keys.insert(group.key).second) Invalid(where + ": the key '" + group.key + "' repeats");
        groups.push_back(std::move(group));
    }
    std::vector<LayerSpec> layers;
    for (std::size_t i = 0; i < Items(stack_json, "layers").size(); ++i) {
        const std::string where = "layers[" + std::to_string(i) + "]";
        const Object& l = AsObject(Items(stack_json, "layers")[i], where);
        LayerSpec layer;
        layer.group = String(l, "group", where);
        layer.name = String(l, "name", where);
        if (!keys.contains(layer.group)) Invalid(where + ": no group has the key '" + layer.group + "'");
        layer.mask = OptionalString(l, "mask", where);
        layer.base_tex = OptionalString(l, "base_tex", where);
        if (!layer.base_tex) {
            const Value* base = Member(l, "base");
            if (base == nullptr || !base->IsArray() || std::get<Array>(base->data).size() != 3) {
                Invalid(where + ": 'base' must be [r, g, b] when there is no 'base_tex'");
            }
            std::array<double, 3> rgb{};
            const Array& values = std::get<Array>(base->data);
            for (std::size_t c = 0; c < 3; ++c) rgb[c] = Number(values[c], where + ": 'base'");
            // "base" may be 0-1 or 0-255: any component above 1 is read as 0-255.
            if (*std::max_element(rgb.begin(), rgb.end()) > 1.0) {
                for (double& c : rgb) c /= 255.0;
            }
            layer.base = rgb;
        }
        layer.rough = OptionalNumber(l, "rough", where);
        layer.metal = OptionalNumber(l, "metal", where);
        layer.spec = OptionalNumber(l, "spec", where);
        layer.height = OptionalNumber(l, "height", where);
        layer.op = OptionalNumber(l, "op", where).value_or(1.0);
        layers.push_back(std::move(layer));
    }
    const core::Project& base_project = edit.base();
    const core::Stack* target = core::FindStack(base_project, options.texture_set, options.stack);
    if (target == nullptr) Invalid("no stack " + std::to_string(options.stack) + " in texture set " + std::to_string(options.texture_set));

    // Import every image the stack names, in name order.
    std::set<std::string> images;
    for (const Group& g : groups) {
        if (g.mask) images.insert(*g.mask);
    }
    for (const LayerSpec& l : layers) {
        if (l.mask) images.insert(*l.mask);
        if (l.base_tex) images.insert(*l.base_tex);
    }
    std::map<std::string, std::string> sha_of;
    Array imported, skipped;
    for (const std::string& name : images) {
        std::optional<std::string> bytes = read(name);
        if (!bytes) Invalid("cannot read the image '" + name + "' (" + name + ".png)");
        const std::string sha = core::Sha256Hex(*bytes);
        const std::string entry = options.resource_prefix + name;
        const auto existing = base_project.resources.find(sha);
        const bool stored = existing != base_project.resources.end() &&
                            std::any_of(existing->second.begin(), existing->second.end(),
                                        [&](const core::ResourceMeta& m) { return m.name == entry; });
        sha_of[name] = ImportResource(edit, store, std::move(*bytes), entry, "image/png", "TEXTURE", name + ".png");
        if (options.resource_group) {
            for (core::ResourceMeta& meta : edit.project().resources.at(sha_of[name])) {
                if (meta.name == entry) meta.extra["group"] = *options.resource_group;
            }
        }
        (stored ? skipped : imported).push_back(name);
    }

    // Build the root group detached: children are stored top first, the JSON lists bottom first.
    core::Layer root;
    root.uid = edit.AllocateId();
    root.kind = core::LayerKind::group;
    root.name = title;
    // The script inserts every node, so each one starts with Painter's insert defaults.
    const std::map<core::ChannelType, core::Channel> channels = target->channels;
    ApplyDefaultBlending(root.blending, channels);
    Array group_report, layer_report;
    for (const Group& g : groups) {
        core::Layer group;
        group.uid = edit.AllocateId();
        group.kind = core::LayerKind::group;
        group.name = g.name;
        if (g.mask) group.mask = ImageMask(edit, *g.mask, sha_of.at(*g.mask));
        ApplyDefaultBlending(group.blending, channels);
        if (g.replace_height) group.blending[core::ChannelType::Height] = core::Blending{};
        for (const LayerSpec& l : layers) {
            if (l.group != g.key) continue;
            core::Layer fill;
            fill.uid = edit.AllocateId();
            fill.kind = core::LayerKind::fill;
            fill.name = l.name;
            ApplyDefaultBlending(fill.blending, channels);
            core::FillContent content;
            ApplyDefaultSources(content, channels);
            if (l.base_tex) {
                content.sources[core::ChannelType::BaseColor] = Bitmap(sha_of.at(*l.base_tex), "sRGB");
                content.projection.mode = core::ProjectionMode::UV;
                content.projection.uv.filtering_mode = core::FilteringMode::BilinearHQ;
                content.projection.uv.uv_wrapping_mode = core::UVWrapMode::RepeatNone;
                content.projection.uv.uv_transformation = core::UVTransformation{};
            } else {
                // The script sets `base` as an sRGB colour; the facade stores the working value
                // it decodes to on a colour-managed (sRGB8) BaseColor, the value as given on any
                // other format (decision 115).
                std::array<double, 3> working = *l.base;
                const auto base_channel = channels.find(core::ChannelType::BaseColor);
                if (base_channel != channels.end() && base_channel->second.format == core::ChannelFormat::sRGB8) {
                    // Under OCIO the facade reads Painter's measured decode (`ocio_srgb.py`,
                    // decision 202), which the native module does not hold.
                    if (evaluator::PainterOcio(edit.project())) {
                        throw core::NotYetSupported(
                            "sync_stack: under OCIO, the working value of the sRGB base colour of '" + l.name +
                            "' is Painter's measured decode, which only the facade holds (decisions 202 and 207)");
                    }
                    for (double& c : working) c = SrgbToLinear(c);
                }
                content.sources[core::ChannelType::BaseColor] = Uniform(working, "Working");
            }
            // The active channels are exactly the ones the layer names; the default sources of
            // the others stay, inactive, as the script's inserted fill keeps them.
            content.active_channels.insert(core::ChannelType::BaseColor);
            const auto raw = [&content](core::ChannelType channel, const std::optional<double>& value) {
                if (!value) return;
                content.sources[channel] = Uniform({*value, *value, *value}, "Working");
                content.active_channels.insert(channel);
            };
            raw(core::ChannelType::SpecularRoughness, l.rough);
            raw(core::ChannelType::BaseMetalness, l.metal);
            raw(core::ChannelType::SpecularWeight, l.spec);
            raw(core::ChannelType::Height, l.height);
            fill.fill = std::move(content);
            if (l.mask) fill.mask = ImageMask(edit, *l.mask, sha_of.at(*l.mask));
            fill.blending[core::ChannelType::BaseColor] = core::Blending{core::BlendingMode::Normal, F32(l.op), {}};
            layer_report.push_back(Object{{"group", g.key}, {"name", l.name}, {"uid", static_cast<std::int64_t>(fill.uid)}});
            group.children.insert(group.children.begin(), std::move(fill));
        }
        group_report.push_back(Object{{"key", g.key}, {"name", g.name}, {"uid", static_cast<std::int64_t>(group.uid)}});
        root.children.insert(root.children.begin(), std::move(group));
    }
    const core::Id root_uid = root.uid;

    // The earlier groups with the title are the group being rebuilt.
    Array deleted;
    std::vector<core::Id> old;
    for (const core::Layer& layer : target->root_layers) {
        if (layer.name == title) old.push_back(layer.uid);
    }
    for (const core::Id uid : old) {
        RemoveNode(edit.project(), uid);
        deleted.push_back(static_cast<std::int64_t>(uid));
    }
    edit.Attach(core::InsertPosition::FromStack(options.texture_set, options.stack), std::move(root));

    // Hide, never delete, every other visible root layer unless a keep-visible prefix matches.
    Array hidden;
    for (core::TextureSet& set : edit.project().texture_sets) {
        if (set.id != options.texture_set) continue;
        for (core::Stack& stack : set.stacks) {
            if (stack.id != options.stack) continue;
            for (core::Layer& layer : stack.root_layers) {
                if (layer.uid == root_uid || !layer.visible) continue;
                const bool keep = std::any_of(options.keep_visible.begin(), options.keep_visible.end(),
                                              [&](const std::string& prefix) { return layer.name.starts_with(prefix); });
                if (keep) continue;
                layer.visible = false;
                hidden.push_back(Object{{"name", layer.name}, {"uid", static_cast<std::int64_t>(layer.uid)}});
            }
        }
    }
    return Object{{"deleted", std::move(deleted)}, {"groups", std::move(group_report)},
                  {"hidden", std::move(hidden)},   {"imported", std::move(imported)},
                  {"layers", std::move(layer_report)}, {"root_uid", static_cast<std::int64_t>(root_uid)},
                  {"skipped", std::move(skipped)}};
}

}  // namespace uzp::python
