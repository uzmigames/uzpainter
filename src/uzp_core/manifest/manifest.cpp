#include "uzp_core/manifest/manifest.h"

#include <algorithm>
#include <charconv>
#include <cstdint>
#include <set>
#include <tuple>
#include <type_traits>
#include <utility>
#include <variant>

#include "uzp_core/manifest/object_reader.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/validation.h"

namespace uzp::core {

using namespace manifest_detail;

namespace {

// ── Writing ──────────────────────────────────────────────────────────────────────────────────

json::Value IdValue(Id id) { return json::Value(static_cast<std::int64_t>(id)); }

template <typename E>
json::Value EnumValue(E value) {
    return json::Value(std::string(ToString(value)));
}

json::Value OptionalString(const std::optional<std::string>& value) {
    return value ? json::Value(*value) : json::Value(nullptr);
}

json::Value ChannelList(const std::set<ChannelType>& channels) {
    std::set<std::string> names;
    for (const ChannelType channel : channels) names.emplace(ToString(channel));
    json::Array out;
    for (const std::string& name : names) out.emplace_back(name);
    return json::Value(std::move(out));
}

json::Value Pair(const std::array<double, 2>& values) { return json::Value(json::Array{values[0], values[1]}); }

json::Value Write(const Resolution& r) {
    json::Object o = r.extra;
    o["width"] = r.width;
    o["height"] = r.height;
    return o;
}

json::Value Write(const Blending& b) {
    json::Object o = b.extra;
    o["mode"] = EnumValue(b.mode);
    o["opacity"] = b.opacity;
    return o;
}

json::Value Write(const ChannelBlending& blending) {
    json::Object o;
    for (const auto& [channel, value] : blending) o[std::string(ToString(channel))] = Write(value);
    return o;
}

json::Value Write(const ResourceBinding& b) {
    json::Object o = b.extra;
    o["sha256"] = b.sha256;
    o["alias"] = OptionalString(b.alias);
    return o;
}

json::Value Write(const LevelsParams& levels) {
    json::Object o = levels.extra;
    o["affected_channel"] =
        levels.affected_channel ? EnumValue(*levels.affected_channel) : json::Value(nullptr);
    json::Array components;
    for (const LevelsComponent& c : levels.components) {
        json::Object component = c.extra;
        component["input_min"] = c.input_min;
        component["input_max"] = c.input_max;
        component["gamma"] = c.gamma;
        component["output_min"] = c.output_min;
        component["output_max"] = c.output_max;
        component["clamp"] = c.clamp;
        components.emplace_back(std::move(component));
    }
    o["components"] = std::move(components);
    return o;
}

void WriteProcedural(json::Object& o, const ProceduralRef& ref) {
    o["asset"] = ref.asset;
    o["params"] = ref.params;
    o["preset"] = OptionalString(ref.preset);
    json::Object inputs;
    for (const auto& [name, binding] : ref.image_inputs) inputs[name] = Write(binding);
    o["image_inputs"] = std::move(inputs);
    json::Object mapping;
    for (const auto& [channel, output] : ref.output_mapping) mapping[channel] = output;
    o["output_mapping"] = std::move(mapping);
    o["mask_output"] = OptionalString(ref.mask_output);
    o["resolution_override"] = ref.resolution_override ? Write(*ref.resolution_override) : json::Value(nullptr);
}

json::Value Write(const ProceduralRef& ref) {
    json::Object o = ref.extra;
    WriteProcedural(o, ref);
    return o;
}

json::Value Write(const Source& source) {
    json::Object o;
    std::visit(
        [&](const auto& s) {
            using T = std::decay_t<decltype(s)>;
            if constexpr (std::is_same_v<T, UniformColorSource>) {
                o = s.extra;
                o["rgb"] = json::Array{s.rgb[0], s.rgb[1], s.rgb[2]};
                o["color_space"] = s.color_space;
            } else if constexpr (std::is_same_v<T, BitmapSource>) {
                o = s.extra;
                o["resource"] = Write(s.resource);
                o["color_space"] = s.color_space;
            } else if constexpr (std::is_same_v<T, VectorSource> || std::is_same_v<T, FontSource>) {
                o = s.extra;
                o["resource"] = Write(s.resource);
                o["params"] = s.params;
            } else if constexpr (std::is_same_v<T, ProceduralSource>) {
                o = s.ref.extra;
                WriteProcedural(o, s.ref);
            } else {
                o = s.extra;
                o["anchor"] = IdValue(s.anchor);
                json::Object mapping;
                for (const auto& [channel, referenced] : s.channel_mapping) {
                    mapping[std::string(ToString(channel))] = EnumValue(referenced);
                }
                o["channel_mapping"] = std::move(mapping);
                o["referenced_channel"] = s.referenced_channel ? EnumValue(*s.referenced_channel) : json::Value(nullptr);
                o["alpha_matte"] = s.alpha_matte;
                o["levels"] = s.levels ? Write(*s.levels) : json::Value(nullptr);
            }
        },
        source.value);
    o["type"] = EnumValue(source.kind());
    return o;
}

json::Value Write(const Projection& p) {
    json::Object transform = p.uv.uv_transformation.extra;
    transform["scale_mode"] = EnumValue(p.uv.uv_transformation.scale_mode);
    transform["scale"] = Pair(p.uv.uv_transformation.scale);
    transform["rotation"] = p.uv.uv_transformation.rotation;
    transform["offset"] = Pair(p.uv.uv_transformation.offset);
    json::Object uv = p.uv.extra;
    uv["filtering_mode"] = EnumValue(p.uv.filtering_mode);
    uv["uv_wrapping_mode"] = EnumValue(p.uv.uv_wrapping_mode);
    uv["uv_transformation"] = std::move(transform);
    json::Object o = p.extra;
    o["mode"] = EnumValue(p.mode);
    o["uv"] = std::move(uv);
    o["params"] = p.params;
    return o;
}

json::Value Write(const FillContent& fill, bool mask) {
    json::Object o = fill.extra;
    if (mask) {
        o["source"] = fill.mono_source ? Write(*fill.mono_source) : json::Value(nullptr);
    } else {
        o["source_mode"] = EnumValue(fill.source_mode);
        json::Object sources;
        for (const auto& [channel, source] : fill.sources) sources[std::string(ToString(channel))] = Write(source);
        o["sources"] = std::move(sources);
        o["material_source"] = fill.material_source ? Write(*fill.material_source) : json::Value(nullptr);
        o["active_channels"] = ChannelList(fill.active_channels);
    }
    o["projection"] = Write(fill.projection);
    json::Object symmetry = fill.symmetry.extra;
    symmetry["enabled"] = fill.symmetry.enabled;
    symmetry["params"] = fill.symmetry.params;
    o["symmetry"] = std::move(symmetry);
    return o;
}

json::Value Write(const PaintContent& paint, bool mask) {
    json::Object o = paint.extra;
    if (mask) {
        o["plane"] = paint.mono_plane ? IdValue(*paint.mono_plane) : json::Value(nullptr);
    } else {
        json::Object planes;
        for (const auto& [channel, id] : paint.planes) planes[std::string(ToString(channel))] = IdValue(id);
        o["planes"] = std::move(planes);
    }
    return o;
}

json::Value Write(const PresetRef& preset) {
    json::Object o = preset.extra;
    o["kind"] = EnumValue(preset.kind);
    o["asset"] = preset.asset;
    return o;
}

json::Value Write(const Effect& e, bool mask) {
    json::Object o = e.extra;
    o["uid"] = IdValue(e.uid);
    o["kind"] = EnumValue(e.kind);
    o["name"] = e.name;
    o["visible"] = e.visible;
    if (mask) {
        o["blending"] = e.mono_blending ? Write(*e.mono_blending) : json::Value(nullptr);
    } else {
        o["blending"] = Write(e.blending);
        o["active_channels"] = ChannelList(e.active_channels);
    }
    o["preset_ref"] = e.preset_ref ? Write(*e.preset_ref) : json::Value(nullptr);
    switch (e.kind) {
        case EffectKind::fill: o["fill"] = e.fill ? Write(*e.fill, mask) : json::Value(nullptr); break;
        case EffectKind::paint: o["paint"] = e.paint ? Write(*e.paint, mask) : json::Value(nullptr); break;
        case EffectKind::generator:
        case EffectKind::filter: o["procedural"] = e.procedural ? Write(*e.procedural) : json::Value(nullptr); break;
        case EffectKind::levels: o["levels"] = e.levels ? Write(*e.levels) : json::Value(nullptr); break;
        case EffectKind::compare_mask: o["compare_mask"] = e.compare_mask ? json::Value(*e.compare_mask) : json::Value(nullptr); break;
        case EffectKind::color_selection:
            o["color_selection"] = e.color_selection ? json::Value(*e.color_selection) : json::Value(nullptr);
            break;
        case EffectKind::anchor: o["anchor_name"] = OptionalString(e.anchor_name); break;
    }
    return o;
}

json::Value Write(const Layer& layer) {
    json::Object o = layer.extra;
    o["uid"] = IdValue(layer.uid);
    o["kind"] = EnumValue(layer.kind);
    o["name"] = layer.name;
    o["visible"] = layer.visible;
    o["blending"] = Write(layer.blending);
    json::Array content;
    for (const Effect& effect : layer.content_effects) content.push_back(Write(effect, false));
    o["content_effects"] = std::move(content);
    if (layer.mask) {
        json::Object mask = layer.mask->extra;
        mask["background"] = EnumValue(layer.mask->background);
        mask["enabled"] = layer.mask->enabled;
        mask["blending"] = Write(layer.mask->blending);
        json::Array effects;
        for (const Effect& effect : layer.mask->effects) effects.push_back(Write(effect, true));
        mask["effects"] = std::move(effects);
        o["mask"] = std::move(mask);
    } else {
        o["mask"] = nullptr;
    }
    json::Object geometry = layer.geometry_mask.extra;
    geometry["type"] = EnumValue(layer.geometry_mask.type);
    geometry["inclusion_list"] = layer.geometry_mask.inclusion_list;
    json::Array items;
    for (const std::string& item : layer.geometry_mask.items) items.emplace_back(item);
    geometry["items"] = std::move(items);
    o["geometry_mask"] = std::move(geometry);
    o["preset_ref"] = layer.preset_ref ? Write(*layer.preset_ref) : json::Value(nullptr);
    switch (layer.kind) {
        case LayerKind::fill: o["fill"] = layer.fill ? Write(*layer.fill, false) : json::Value(nullptr); break;
        case LayerKind::paint: o["paint"] = layer.paint ? Write(*layer.paint, false) : json::Value(nullptr); break;
        case LayerKind::group: {
            json::Array children;
            for (const Layer& child : layer.children) children.push_back(Write(child));
            o["children"] = std::move(children);
            o["collapsed"] = layer.collapsed;
            break;
        }
        case LayerKind::instance: o["instance_source"] = IdValue(layer.instance_source); break;
    }
    return o;
}

json::Value Write(const MeshMapBinding& binding) {
    json::Object provenance;
    if (const auto* imported = std::get_if<ImportedProvenance>(&binding.provenance)) {
        provenance = imported->extra;
        provenance["source_path"] = imported->source_path;
        provenance["source_sha256"] = imported->source_sha256;
        provenance["declared_role"] = EnumValue(imported->declared_role);
        provenance["declared_convention"] = EnumValue(imported->declared_convention);
        provenance["units"] = imported->units;
    } else {
        const auto& baked = std::get<BakedProvenance>(binding.provenance);
        provenance = baked.extra;
        provenance["baker_version"] = baked.baker_version;
        provenance["backend"] = EnumValue(baked.backend);
        provenance["settings_hash"] = baked.settings_hash;
        json::Array high;
        for (const std::string& hash : baked.high_meshes) high.emplace_back(hash);
        provenance["high_meshes"] = std::move(high);
        provenance["cage"] = OptionalString(baked.cage);
        json::Object hashes = baked.mesh_hashes.extra;
        hashes["positions"] = baked.mesh_hashes.positions;
        hashes["uvs"] = baked.mesh_hashes.uvs;
        hashes["corner_normals"] = baked.mesh_hashes.corner_normals;
        hashes["triangulation"] = baked.mesh_hashes.triangulation;
        provenance["mesh_hashes"] = std::move(hashes);
        provenance["effective_normalization"] = baked.effective_normalization;
    }
    provenance["kind"] = EnumValue(binding.provenance_kind());
    json::Object o = binding.extra;
    o["resource"] = binding.resource;
    o["format"] = EnumValue(binding.format);
    o["color_space"] = binding.color_space;
    o["provenance"] = std::move(provenance);
    o["invalid"] = binding.invalid;
    o["invalid_report"] = binding.invalid_report ? json::Value(*binding.invalid_report) : json::Value(nullptr);
    return o;
}

json::Value Write(const TextureSet& set) {
    json::Object o = set.extra;
    o["id"] = IdValue(set.id);
    o["name"] = set.name;
    o["original_name"] = set.original_name;
    o["description"] = set.description;
    o["material_id"] = set.material_id;
    o["resolution"] = Write(set.resolution);
    std::vector<const UVTile*> tiles;
    for (const UVTile& tile : set.uv_tiles) tiles.push_back(&tile);
    std::sort(tiles.begin(), tiles.end(), [](const UVTile* a, const UVTile* b) { return a->udim < b->udim; });
    json::Array uv_tiles;
    for (const UVTile* tile : tiles) {
        json::Object t = tile->extra;
        t["id"] = IdValue(tile->id);
        t["udim"] = tile->udim;
        uv_tiles.emplace_back(std::move(t));
    }
    o["uv_tiles"] = std::move(uv_tiles);
    json::Object maps;
    for (const auto& [usage, binding] : set.mesh_maps) maps[std::string(ToString(usage))] = Write(binding);
    o["mesh_maps"] = std::move(maps);
    json::Object bake = set.bake_settings.extra;
    bake["common"] = set.bake_settings.common;
    bake["detail"] = set.bake_settings.detail;
    json::Object per_baker;
    for (const auto& [name, settings] : set.bake_settings.per_baker) per_baker[name] = settings;
    bake["per_baker"] = std::move(per_baker);
    o["bake_settings"] = std::move(bake);
    o["height_to_normal_method"] = EnumValue(set.height_to_normal_method);
    json::Array stacks;
    for (const Stack& stack : set.stacks) {
        json::Object s = stack.extra;
        s["id"] = IdValue(stack.id);
        s["name"] = stack.name;
        json::Object channels;
        for (const auto& [type, channel] : stack.channels) {
            json::Object c = channel.extra;
            c["format"] = EnumValue(channel.format);
            c["label"] = channel.label;
            channels[std::string(ToString(type))] = std::move(c);
        }
        s["channels"] = std::move(channels);
        json::Array roots;
        for (const Layer& layer : stack.root_layers) roots.push_back(Write(layer));
        s["root_layers"] = std::move(roots);
        stacks.emplace_back(std::move(s));
    }
    o["stacks"] = std::move(stacks);
    return o;
}

// ── Reading ──────────────────────────────────────────────────────────────────────────────────

std::array<double, 2> ReadPair(const json::Value& value, const std::string& path) {
    const json::Array& a = AsArray(value, path);
    if (a.size() != 2) Fail(path, "expected two numbers");
    return {AsNumber(a[0], path + "[0]"), AsNumber(a[1], path + "[1]")};
}

int ReadInt32(ObjectReader& r, std::string_view key) {
    const std::int64_t value = r.Int(key);
    if (value < INT32_MIN || value > INT32_MAX) Fail(r.Path(key), "outside the 32-bit range");
    return static_cast<int>(value);
}

Resolution ReadResolution(const json::Value& value, const std::string& path) {
    ObjectReader r(value, path);
    Resolution out;
    out.width = ReadInt32(r, "width");
    out.height = ReadInt32(r, "height");
    out.extra = r.Rest();
    return out;
}

Blending ReadBlending(const json::Value& value, const std::string& path) {
    ObjectReader r(value, path);
    Blending out;
    out.mode = r.Enum<BlendingMode>("mode");
    out.opacity = r.Number("opacity");
    out.extra = r.Rest();
    return out;
}

ChannelBlending ReadChannelBlending(const json::Value& value, const std::string& path) {
    ChannelBlending out;
    for (const auto& [key, member] : AsObject(value, path)) {
        out[KeyEnum<ChannelType>(key, path)] = ReadBlending(member, path + "." + key);
    }
    return out;
}

std::set<ChannelType> ReadChannelList(const json::Value& value, const std::string& path) {
    std::set<ChannelType> out;
    for (const json::Value& item : AsArray(value, path)) {
        if (!out.insert(AsEnum<ChannelType>(item, path)).second) Fail(path, "a channel is listed twice");
    }
    return out;
}

ResourceBinding ReadBinding(const json::Value& value, const std::string& path) {
    ObjectReader r(value, path);
    ResourceBinding out;
    out.sha256 = r.String("sha256");
    out.alias = r.OptionalString("alias");
    out.extra = r.Rest();
    return out;
}

LevelsParams ReadLevels(const json::Value& value, const std::string& path) {
    ObjectReader r(value, path);
    LevelsParams out;
    if (const json::Value* channel = r.GetOptional("affected_channel")) {
        out.affected_channel = AsEnum<ChannelType>(*channel, r.Path("affected_channel"));
    }
    const json::Array& components = r.Array("components");
    for (std::size_t i = 0; i < components.size(); ++i) {
        ObjectReader c(components[i], r.Path("components") + "[" + std::to_string(i) + "]");
        LevelsComponent component;
        component.input_min = c.Number("input_min");
        component.input_max = c.Number("input_max");
        component.gamma = c.Number("gamma");
        component.output_min = c.Number("output_min");
        component.output_max = c.Number("output_max");
        component.clamp = c.Bool("clamp");
        component.extra = c.Rest();
        out.components.push_back(std::move(component));
    }
    out.extra = r.Rest();
    return out;
}

ProceduralRef ReadProcedural(ObjectReader& r) {
    ProceduralRef out;
    out.asset = r.String("asset");
    out.params = r.Object("params");
    out.preset = r.OptionalString("preset");
    for (const auto& [name, binding] : r.Object("image_inputs")) {
        out.image_inputs[name] = ReadBinding(binding, r.Path("image_inputs") + "." + name);
    }
    for (const auto& [channel, output] : r.Object("output_mapping")) {
        out.output_mapping[channel] = AsString(output, r.Path("output_mapping") + "." + channel);
    }
    out.mask_output = r.OptionalString("mask_output");
    if (const json::Value* resolution = r.GetOptional("resolution_override")) {
        out.resolution_override = ReadResolution(*resolution, r.Path("resolution_override"));
    }
    out.extra = r.Rest();
    return out;
}

Source ReadSource(const json::Value& value, const std::string& path) {
    ObjectReader r(value, path);
    switch (r.Enum<SourceKind>("type")) {
        case SourceKind::uniform_color: {
            UniformColorSource s;
            const json::Array& rgb = r.Array("rgb");
            if (rgb.size() != 3) Fail(r.Path("rgb"), "expected three numbers");
            for (std::size_t i = 0; i < 3; ++i) s.rgb[i] = AsNumber(rgb[i], r.Path("rgb"));
            s.color_space = r.String("color_space");
            s.extra = r.Rest();
            return Source{s};
        }
        case SourceKind::bitmap: {
            BitmapSource s;
            s.resource = ReadBinding(r.Need("resource"), r.Path("resource"));
            s.color_space = r.String("color_space");
            s.extra = r.Rest();
            return Source{s};
        }
        case SourceKind::vector: {
            VectorSource s;
            s.resource = ReadBinding(r.Need("resource"), r.Path("resource"));
            s.params = r.Object("params");
            s.extra = r.Rest();
            return Source{s};
        }
        case SourceKind::font: {
            FontSource s;
            s.resource = ReadBinding(r.Need("resource"), r.Path("resource"));
            s.params = r.Object("params");
            s.extra = r.Rest();
            return Source{s};
        }
        case SourceKind::procedural: return Source{ProceduralSource{ReadProcedural(r)}};
        case SourceKind::reference: {
            ReferenceSource s;
            s.anchor = r.IdValue("anchor");
            for (const auto& [key, mapped] : r.Object("channel_mapping")) {
                s.channel_mapping[KeyEnum<ChannelType>(key, r.Path("channel_mapping"))] =
                    AsEnum<ChannelType>(mapped, r.Path("channel_mapping") + "." + key);
            }
            if (const json::Value* channel = r.GetOptional("referenced_channel")) {
                s.referenced_channel = AsEnum<ChannelType>(*channel, r.Path("referenced_channel"));
            }
            s.alpha_matte = r.Bool("alpha_matte");
            if (const json::Value* levels = r.GetOptional("levels")) s.levels = ReadLevels(*levels, r.Path("levels"));
            s.extra = r.Rest();
            return Source{s};
        }
    }
    Fail(path, "unknown source type");
}

Projection ReadProjection(const json::Value& value, const std::string& path) {
    ObjectReader r(value, path);
    Projection out;
    out.mode = r.Enum<ProjectionMode>("mode");
    ObjectReader uv(r.Need("uv"), r.Path("uv"));
    out.uv.filtering_mode = uv.Enum<FilteringMode>("filtering_mode");
    out.uv.uv_wrapping_mode = uv.Enum<UVWrapMode>("uv_wrapping_mode");
    ObjectReader t(uv.Need("uv_transformation"), uv.Path("uv_transformation"));
    out.uv.uv_transformation.scale_mode = t.Enum<ScaleMode>("scale_mode");
    out.uv.uv_transformation.scale = ReadPair(t.Need("scale"), t.Path("scale"));
    out.uv.uv_transformation.rotation = t.Number("rotation");
    out.uv.uv_transformation.offset = ReadPair(t.Need("offset"), t.Path("offset"));
    out.uv.uv_transformation.extra = t.Rest();
    out.uv.extra = uv.Rest();
    out.params = r.Object("params");
    out.extra = r.Rest();
    return out;
}

FillContent ReadFill(const json::Value& value, const std::string& path) {
    ObjectReader r(value, path);
    FillContent out;
    if (const json::Value* mode = r.Get("source_mode")) out.source_mode = AsEnum<SourceMode>(*mode, r.Path("source_mode"));
    if (const json::Value* sources = r.Get("sources")) {
        for (const auto& [key, source] : AsObject(*sources, r.Path("sources"))) {
            out.sources[KeyEnum<ChannelType>(key, r.Path("sources"))] = ReadSource(source, r.Path("sources") + "." + key);
        }
    }
    if (const json::Value* source = r.GetOptional("source")) out.mono_source = ReadSource(*source, r.Path("source"));
    if (const json::Value* source = r.GetOptional("material_source")) {
        out.material_source = ReadSource(*source, r.Path("material_source"));
    }
    if (const json::Value* channels = r.Get("active_channels")) {
        out.active_channels = ReadChannelList(*channels, r.Path("active_channels"));
    }
    out.projection = ReadProjection(r.Need("projection"), r.Path("projection"));
    ObjectReader symmetry(r.Need("symmetry"), r.Path("symmetry"));
    out.symmetry.enabled = symmetry.Bool("enabled");
    out.symmetry.params = symmetry.Object("params");
    out.symmetry.extra = symmetry.Rest();
    out.extra = r.Rest();
    return out;
}

PaintContent ReadPaint(const json::Value& value, const std::string& path) {
    ObjectReader r(value, path);
    PaintContent out;
    if (const json::Value* planes = r.Get("planes")) {
        for (const auto& [key, id] : AsObject(*planes, r.Path("planes"))) {
            out.planes[KeyEnum<ChannelType>(key, r.Path("planes"))] = AsId(id, r.Path("planes") + "." + key);
        }
    }
    if (const json::Value* plane = r.GetOptional("plane")) out.mono_plane = AsId(*plane, r.Path("plane"));
    out.extra = r.Rest();
    return out;
}

std::optional<PresetRef> ReadPreset(ObjectReader& r) {
    const json::Value* value = r.GetOptional("preset_ref");
    if (value == nullptr) return std::nullopt;
    ObjectReader p(*value, r.Path("preset_ref"));
    PresetRef out;
    out.kind = p.Enum<PresetKind>("kind");
    out.asset = p.String("asset");
    out.extra = p.Rest();
    return out;
}

Effect ReadEffect(const json::Value& value, const std::string& path, bool mask) {
    ObjectReader r(value, path);
    Effect e;
    e.uid = r.IdValue("uid");
    e.kind = r.Enum<EffectKind>("kind");
    e.name = r.String("name");
    e.visible = r.Bool("visible");
    if (mask) {
        if (const json::Value* blending = r.GetOptional("blending")) e.mono_blending = ReadBlending(*blending, r.Path("blending"));
    } else {
        e.blending = ReadChannelBlending(r.Need("blending"), r.Path("blending"));
    }
    if (const json::Value* channels = r.Get("active_channels")) {
        e.active_channels = ReadChannelList(*channels, r.Path("active_channels"));
    }
    e.preset_ref = ReadPreset(r);
    if (const json::Value* fill = r.GetOptional("fill")) e.fill = ReadFill(*fill, r.Path("fill"));
    if (const json::Value* paint = r.GetOptional("paint")) e.paint = ReadPaint(*paint, r.Path("paint"));
    if (const json::Value* procedural = r.GetOptional("procedural")) {
        ObjectReader p(*procedural, r.Path("procedural"));
        e.procedural = ReadProcedural(p);
    }
    if (const json::Value* levels = r.GetOptional("levels")) e.levels = ReadLevels(*levels, r.Path("levels"));
    if (const json::Value* params = r.GetOptional("compare_mask")) e.compare_mask = AsObject(*params, r.Path("compare_mask"));
    if (const json::Value* params = r.GetOptional("color_selection")) {
        e.color_selection = AsObject(*params, r.Path("color_selection"));
    }
    e.anchor_name = r.OptionalString("anchor_name");
    e.extra = r.Rest();
    return e;
}

std::vector<Effect> ReadEffects(const json::Value& value, const std::string& path, bool mask) {
    std::vector<Effect> out;
    const json::Array& items = AsArray(value, path);
    for (std::size_t i = 0; i < items.size(); ++i) out.push_back(ReadEffect(items[i], path + "[" + std::to_string(i) + "]", mask));
    return out;
}

Layer ReadLayer(const json::Value& value, const std::string& path) {
    ObjectReader r(value, path);
    Layer layer;
    layer.uid = r.IdValue("uid");
    layer.kind = r.Enum<LayerKind>("kind");
    layer.name = r.String("name");
    layer.visible = r.Bool("visible");
    layer.blending = ReadChannelBlending(r.Need("blending"), r.Path("blending"));
    layer.content_effects = ReadEffects(r.Need("content_effects"), r.Path("content_effects"), false);
    if (const json::Value* mask = r.GetOptional("mask")) {
        ObjectReader m(*mask, r.Path("mask"));
        Mask out;
        out.background = m.Enum<MaskBackground>("background");
        out.enabled = m.Bool("enabled");
        out.blending = ReadBlending(m.Need("blending"), m.Path("blending"));
        out.effects = ReadEffects(m.Need("effects"), m.Path("effects"), true);
        out.extra = m.Rest();
        layer.mask = std::move(out);
    }
    ObjectReader g(r.Need("geometry_mask"), r.Path("geometry_mask"));
    layer.geometry_mask.type = g.Enum<GeometryMaskType>("type");
    layer.geometry_mask.inclusion_list = g.Bool("inclusion_list");
    for (const json::Value& item : g.Array("items")) layer.geometry_mask.items.push_back(AsString(item, g.Path("items")));
    layer.geometry_mask.extra = g.Rest();
    layer.preset_ref = ReadPreset(r);
    if (const json::Value* fill = r.GetOptional("fill")) layer.fill = ReadFill(*fill, r.Path("fill"));
    if (const json::Value* paint = r.GetOptional("paint")) layer.paint = ReadPaint(*paint, r.Path("paint"));
    if (const json::Value* children = r.Get("children")) {
        const json::Array& items = AsArray(*children, r.Path("children"));
        for (std::size_t i = 0; i < items.size(); ++i) {
            layer.children.push_back(ReadLayer(items[i], r.Path("children") + "[" + std::to_string(i) + "]"));
        }
    }
    if (const json::Value* collapsed = r.Get("collapsed")) layer.collapsed = AsBool(*collapsed, r.Path("collapsed"));
    if (const json::Value* source = r.Get("instance_source")) layer.instance_source = AsId(*source, r.Path("instance_source"));
    layer.extra = r.Rest();
    return layer;
}

MeshMapBinding ReadMeshMap(const json::Value& value, const std::string& path) {
    ObjectReader r(value, path);
    MeshMapBinding out;
    out.resource = r.String("resource");
    out.format = r.Enum<ChannelFormat>("format");
    out.color_space = r.String("color_space");
    ObjectReader p(r.Need("provenance"), r.Path("provenance"));
    if (p.Enum<MeshMapProvenanceKind>("kind") == MeshMapProvenanceKind::imported) {
        ImportedProvenance imported;
        imported.source_path = p.String("source_path");
        imported.source_sha256 = p.String("source_sha256");
        imported.declared_role = p.Enum<MeshMapRole>("declared_role");
        imported.declared_convention = p.Enum<NormalMapFormat>("declared_convention");
        imported.units = p.String("units");
        imported.extra = p.Rest();
        out.provenance = std::move(imported);
    } else {
        BakedProvenance baked;
        baked.baker_version = p.String("baker_version");
        baked.backend = p.Enum<BakerBackend>("backend");
        baked.settings_hash = p.String("settings_hash");
        for (const json::Value& hash : p.Array("high_meshes")) baked.high_meshes.push_back(AsString(hash, p.Path("high_meshes")));
        baked.cage = p.OptionalString("cage");
        ObjectReader h(p.Need("mesh_hashes"), p.Path("mesh_hashes"));
        baked.mesh_hashes.positions = h.String("positions");
        baked.mesh_hashes.uvs = h.String("uvs");
        baked.mesh_hashes.corner_normals = h.String("corner_normals");
        baked.mesh_hashes.triangulation = h.String("triangulation");
        baked.mesh_hashes.extra = h.Rest();
        baked.effective_normalization = p.Object("effective_normalization");
        baked.extra = p.Rest();
        out.provenance = std::move(baked);
    }
    out.invalid = r.Bool("invalid");
    if (const json::Value* report = r.GetOptional("invalid_report")) out.invalid_report = AsObject(*report, r.Path("invalid_report"));
    out.extra = r.Rest();
    return out;
}

TextureSet ReadTextureSet(const json::Value& value, const std::string& path) {
    ObjectReader r(value, path);
    TextureSet set;
    set.id = r.IdValue("id");
    set.name = r.String("name");
    set.original_name = r.String("original_name");
    set.description = r.String("description");
    set.material_id = r.String("material_id");
    set.resolution = ReadResolution(r.Need("resolution"), r.Path("resolution"));
    const json::Array& tiles = r.Array("uv_tiles");
    for (std::size_t i = 0; i < tiles.size(); ++i) {
        ObjectReader t(tiles[i], r.Path("uv_tiles") + "[" + std::to_string(i) + "]");
        UVTile tile;
        tile.id = t.IdValue("id");
        tile.udim = ReadInt32(t, "udim");
        tile.extra = t.Rest();
        set.uv_tiles.push_back(std::move(tile));
    }
    for (const auto& [key, binding] : r.Object("mesh_maps")) {
        set.mesh_maps[KeyEnum<MeshMapUsage>(key, r.Path("mesh_maps"))] = ReadMeshMap(binding, r.Path("mesh_maps") + "." + key);
    }
    ObjectReader b(r.Need("bake_settings"), r.Path("bake_settings"));
    set.bake_settings.common = b.Object("common");
    set.bake_settings.detail = b.Object("detail");
    for (const auto& [name, settings] : b.Object("per_baker")) {
        set.bake_settings.per_baker[name] = AsObject(settings, b.Path("per_baker") + "." + name);
    }
    set.bake_settings.extra = b.Rest();
    if (const json::Value* method = r.GetOptional("height_to_normal_method")) {
        set.height_to_normal_method = AsEnum<HeightToNormalMethod>(*method, r.Path("height_to_normal_method"));
    }
    const json::Array& stacks = r.Array("stacks");
    for (std::size_t i = 0; i < stacks.size(); ++i) {
        ObjectReader s(stacks[i], r.Path("stacks") + "[" + std::to_string(i) + "]");
        Stack stack;
        stack.id = s.IdValue("id");
        stack.name = s.String("name");
        for (const auto& [key, channel] : s.Object("channels")) {
            ObjectReader c(channel, s.Path("channels") + "." + key);
            Channel out;
            out.format = c.Enum<ChannelFormat>("format");
            out.label = c.String("label");
            out.extra = c.Rest();
            stack.channels[KeyEnum<ChannelType>(key, s.Path("channels"))] = std::move(out);
        }
        const json::Array& roots = s.Array("root_layers");
        for (std::size_t j = 0; j < roots.size(); ++j) {
            stack.root_layers.push_back(ReadLayer(roots[j], s.Path("root_layers") + "[" + std::to_string(j) + "]"));
        }
        stack.extra = s.Rest();
        set.stacks.push_back(std::move(stack));
    }
    set.extra = r.Rest();
    return set;
}

void CheckFormatVersion(const std::string& version, const std::string& path) {
    int parts[3] = {0, 0, 0};
    const char* p = version.data();
    const char* end = version.data() + version.size();
    for (int i = 0; i < 3; ++i) {
        const auto [next, ec] = std::from_chars(p, end, parts[i]);
        if (ec != std::errc() || next == p) Fail(path, "'" + version + "' is not a semantic version");
        p = next;
        if (i < 2) {
            if (p == end || *p != '.') Fail(path, "'" + version + "' is not a semantic version");
            ++p;
        }
    }
    if (p != end) Fail(path, "'" + version + "' is not a semantic version");
    const int supported_major = kFormatVersion.front() - '0';
    if (parts[0] > supported_major) {
        Fail(path, "format " + version + " is newer than this version reads (" + std::string(kFormatVersion) + ")");
    }
}

}  // namespace

json::Value ProjectToJson(const Project& project) {
    json::Object o = project.extra;
    o["schema"] = std::string(kManifestSchema);
    const Versions& v = project.versions;
    json::Object reference = v.painter_reference.extra;
    reference["build"] = v.painter_reference.build;
    reference["recorded_from"] = v.painter_reference.recorded_from;
    json::Object versions = v.extra;
    versions["format_version"] = v.format_version;
    versions["app_version"] = v.app_version;
    versions["evaluator_profile"] = v.evaluator_profile;
    versions["compat_profile"] = v.compat_profile;
    versions["painter_reference"] = std::move(reference);
    o["versions"] = std::move(versions);
    o["next_id"] = IdValue(project.next_id);

    const ProjectSettings& s = project.settings;
    json::Object color = s.color_management.extra;
    color["mode"] = s.color_management.mode;
    color["config_hash"] = s.color_management.config_hash;
    color["working_space"] = s.color_management.working_space;
    color["io_rules"] = s.color_management.io_rules;
    json::Object settings = s.extra;
    settings["normal_map_format"] = EnumValue(s.normal_map_format);
    settings["tangent_space"] = EnumValue(s.tangent_space);
    settings["workflow"] = EnumValue(s.workflow);
    settings["default_resolution"] = Write(s.default_resolution);
    settings["mesh_unit_scale"] = s.mesh_unit_scale;
    settings["color_management"] = std::move(color);
    settings["import_cameras"] = s.import_cameras;
    settings["auto_unwrap"] = s.auto_unwrap;
    if (s.template_id != "default") settings["template"] = s.template_id;
    o["settings"] = std::move(settings);

    if (project.mesh) {
        json::Object mesh = project.mesh->extra;
        mesh["resource"] = project.mesh->resource;
        mesh["import_report"] = project.mesh->import_report;
        if (!project.mesh->source.empty()) mesh["source"] = project.mesh->source;
        o["mesh"] = std::move(mesh);
    } else {
        o["mesh"] = nullptr;
    }

    json::Array sets;
    for (const TextureSet& set : project.texture_sets) sets.push_back(Write(set));
    o["texture_sets"] = std::move(sets);

    json::Object resources;
    for (const auto& [hash, entries] : project.resources) {
        std::vector<const ResourceMeta*> sorted;
        for (const ResourceMeta& meta : entries) sorted.push_back(&meta);
        std::sort(sorted.begin(), sorted.end(), [](const ResourceMeta* a, const ResourceMeta* b) {
            return std::tie(a->name, a->id) < std::tie(b->name, b->id);
        });
        json::Array list;
        for (const ResourceMeta* meta : sorted) {
            json::Object m = meta->extra;
            m["id"] = IdValue(meta->id);
            m["name"] = meta->name;
            m["mime"] = meta->mime;
            m["size"] = meta->size;
            m["usage"] = meta->usage;
            m["origin"] = meta->origin;
            m["imported_at"] = meta->imported_at;
            m["color_space"] = meta->color_space;
            m["session"] = meta->session;
            list.emplace_back(std::move(m));
        }
        resources[hash] = std::move(list);
    }
    o["resources"] = std::move(resources);

    const DisplayState& d = project.display;
    json::Object environment = d.environment.extra;
    environment["resource"] = OptionalString(d.environment.resource);
    environment["rotation"] = d.environment.rotation;
    environment["exposure"] = d.environment.exposure;
    environment["opacity"] = d.environment.opacity;
    environment["blur"] = d.environment.blur;
    json::Object shader = d.shader.extra;
    shader["id"] = d.shader.id;
    shader["hash"] = d.shader.hash;
    shader["parameters"] = d.shader.parameters;
    json::Object display = d.extra;
    display["environment"] = std::move(environment);
    display["color_lut"] = OptionalString(d.color_lut);
    display["tone_mapping"] = EnumValue(d.tone_mapping);
    display["shader"] = std::move(shader);
    display["cameras"] = d.cameras;
    display["background"] = d.background;
    display["shadows"] = d.shadows;
    display["post_effects"] = d.post_effects;
    o["display"] = std::move(display);

    o["export_defaults"] = project.export_defaults;
    json::Object metadata;
    for (const auto& [context, values] : project.metadata) metadata[context] = values;
    o["metadata"] = std::move(metadata);
    return o;
}

Project ProjectFromJson(const json::Value& manifest) {
    ObjectReader r(manifest, "$");
    Project project;
    if (r.String("schema") != kManifestSchema) {
        Fail(r.Path("schema"), "expected '" + std::string(kManifestSchema) + "'");
    }

    ObjectReader v(r.Need("versions"), r.Path("versions"));
    project.versions.format_version = v.String("format_version");
    CheckFormatVersion(project.versions.format_version, v.Path("format_version"));
    project.versions.app_version = v.String("app_version");
    project.versions.evaluator_profile = v.String("evaluator_profile");
    project.versions.compat_profile = v.String("compat_profile");
    ObjectReader pr(v.Need("painter_reference"), v.Path("painter_reference"));
    project.versions.painter_reference.build = pr.String("build");
    project.versions.painter_reference.recorded_from = pr.String("recorded_from");
    project.versions.painter_reference.extra = pr.Rest();
    project.versions.extra = v.Rest();
    project.next_id = r.IdValue("next_id");

    ObjectReader s(r.Need("settings"), r.Path("settings"));
    ProjectSettings& settings = project.settings;
    settings.normal_map_format = s.Enum<NormalMapFormat>("normal_map_format");
    settings.tangent_space = s.Enum<TangentSpace>("tangent_space");
    settings.workflow = s.Enum<ProjectWorkflow>("workflow");
    settings.default_resolution = ReadResolution(s.Need("default_resolution"), s.Path("default_resolution"));
    settings.mesh_unit_scale = s.Number("mesh_unit_scale");
    ObjectReader c(s.Need("color_management"), s.Path("color_management"));
    settings.color_management.mode = c.String("mode");
    settings.color_management.config_hash = c.String("config_hash");
    settings.color_management.working_space = c.String("working_space");
    settings.color_management.io_rules = c.Array("io_rules");
    settings.color_management.extra = c.Rest();
    settings.import_cameras = s.Bool("import_cameras");
    settings.auto_unwrap = s.Bool("auto_unwrap");
    if (const json::Value* id = s.GetOptional("template")) settings.template_id = AsString(*id, s.Path("template"));
    settings.extra = s.Rest();

    if (const json::Value* mesh = r.GetOptional("mesh")) {
        ObjectReader m(*mesh, r.Path("mesh"));
        MeshReference out;
        out.resource = m.String("resource");
        out.import_report = m.Object("import_report");
        if (const json::Value* source = m.GetOptional("source")) out.source = AsString(*source, m.Path("source"));
        out.extra = m.Rest();
        project.mesh = std::move(out);
    }

    const json::Array& sets = r.Array("texture_sets");
    for (std::size_t i = 0; i < sets.size(); ++i) {
        project.texture_sets.push_back(ReadTextureSet(sets[i], r.Path("texture_sets") + "[" + std::to_string(i) + "]"));
    }

    for (const auto& [hash, entries] : r.Object("resources")) {
        const std::string path = r.Path("resources") + "." + hash;
        std::vector<ResourceMeta>& list = project.resources[hash];
        const json::Array& items = AsArray(entries, path);
        for (std::size_t i = 0; i < items.size(); ++i) {
            ObjectReader m(items[i], path + "[" + std::to_string(i) + "]");
            ResourceMeta meta;
            meta.id = m.IdValue("id");
            meta.name = m.String("name");
            meta.mime = m.String("mime");
            meta.size = m.Int("size");
            meta.usage = m.String("usage");
            meta.origin = m.String("origin");
            meta.imported_at = m.String("imported_at");
            meta.color_space = m.String("color_space");
            meta.session = m.Bool("session");
            meta.extra = m.Rest();
            list.push_back(std::move(meta));
        }
    }

    ObjectReader d(r.Need("display"), r.Path("display"));
    DisplayState& display = project.display;
    ObjectReader e(d.Need("environment"), d.Path("environment"));
    display.environment.resource = e.OptionalString("resource");
    display.environment.rotation = e.Number("rotation");
    display.environment.exposure = e.Number("exposure");
    display.environment.opacity = e.Number("opacity");
    display.environment.blur = e.Number("blur");
    display.environment.extra = e.Rest();
    display.color_lut = d.OptionalString("color_lut");
    display.tone_mapping = d.Enum<ToneMapping>("tone_mapping");
    ObjectReader sh(d.Need("shader"), d.Path("shader"));
    display.shader.id = sh.String("id");
    display.shader.hash = sh.String("hash");
    display.shader.parameters = sh.Object("parameters");
    display.shader.extra = sh.Rest();
    display.cameras = d.Array("cameras");
    display.background = d.Object("background");
    display.shadows = d.Bool("shadows");
    display.post_effects = d.Object("post_effects");
    display.extra = d.Rest();

    project.export_defaults = r.Object("export_defaults");
    for (const auto& [context, values] : r.Object("metadata")) {
        project.metadata[context] = AsObject(values, r.Path("metadata") + "." + context);
    }
    project.extra = r.Rest();
    return project;
}

std::string SaveManifest(const Project& project) {
    Validate(project);
    return json::WriteCanonical(ProjectToJson(project));
}

Project LoadManifest(std::string_view text) {
    Project project = ProjectFromJson(json::Parse(text));
    Validate(project);
    return project;
}

std::string ManifestDigest(const Project& project) { return Sha256Hex(SaveManifest(project)); }

}  // namespace uzp::core
