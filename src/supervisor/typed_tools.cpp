// The typed MCP tool families the worker serves (typed_tools.h; decision 164).

#include "supervisor/typed_tools.h"

#include <algorithm>
#include <fstream>
#include <iterator>
#include <map>
#include <set>

#include "python/edits.h"
#include "python/errors.h"
#include "python/recipe.h"
#include "python/stack_sync.h"
#include "uzp_core/document/layer_tree.h"
#include "uzp_core/naming/naming.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/resource_url.h"

namespace uzp::supervisor {

namespace {

using python::ChannelArg;

[[noreturn]] void Invalid(std::string message) { throw CallError{"invalid_arguments", std::move(message), {}}; }

// ── Schema builders ─────────────────────────────────────────────────────────────────────────────

template <typename E>
json::Array EnumNames() {
    json::Array names;
    for (const std::string_view name : core::EnumTable<E>::names) names.push_back(std::string(name));
    return names;
}

template <typename E>
json::Object EnumProperty(const char* description) {
    return {{"type", "string"}, {"enum", EnumNames<E>()}, {"description", description}};
}

json::Object Strings(json::Array values, const char* description) {
    return {{"type", "string"}, {"enum", std::move(values)}, {"description", description}};
}

json::Object BoolProperty(const char* description) { return {{"type", "boolean"}, {"description", description}}; }

json::Object NumberProperty(const char* description, std::optional<double> minimum = std::nullopt,
                            std::optional<double> maximum = std::nullopt) {
    json::Object property{{"type", "number"}, {"description", description}};
    if (minimum) property["minimum"] = *minimum;
    if (maximum) property["maximum"] = *maximum;
    return property;
}

json::Object IntegerProperty(const char* description, std::optional<std::int64_t> minimum = std::nullopt) {
    json::Object property{{"type", "integer"}, {"description", description}};
    if (minimum) property["minimum"] = *minimum;
    return property;
}

json::Object ArrayProperty(json::Object items, const char* description, std::int64_t min_items = 0) {
    json::Object property{{"type", "array"}, {"items", std::move(items)}, {"description", description}};
    if (min_items > 0) property["minItems"] = min_items;
    return property;
}

json::Object ObjectProperty(json::Object properties, json::Array required, const char* description) {
    json::Object property = Schema(std::move(properties), std::move(required));
    property["description"] = description;
    return property;
}

json::Object TextureSetProperty() {
    return {{"type", "string"},
            {"description", "The texture set's name; the active one when omitted."},
            {"x-uzpainter-ref", "texture_set"}};
}

json::Object StackProperty() {
    return {{"type", "string"},
            {"description", "The stack's name; the texture set's active or first stack when omitted."},
            {"x-uzpainter-ref", "stack"}};
}

json::Object ResourceProperty(const char* description) {
    return {{"type", "string"}, {"minLength", 1}, {"description", description}};
}

/// `{<channel type>: {mode?, opacity?}}`.
json::Object BlendingProperty() {
    json::Object entry = Schema({{"mode", EnumProperty<core::BlendingMode>("The blending mode.")},
                                 {"opacity", NumberProperty("The opacity, 0 to 1.", 0.0, 1.0)}},
                                {});
    return {{"type", "object"},
            {"propertyNames", json::Object{{"enum", EnumNames<core::ChannelType>()}}},
            {"additionalProperties", std::move(entry)},
            {"description", "Per channel of a content-stack node: its blending mode and opacity."}};
}

json::Object MonoBlendingProperty() {
    json::Object property = Schema({{"mode", EnumProperty<core::BlendingMode>("The blending mode.")},
                                    {"opacity", NumberProperty("The opacity, 0 to 1.", 0.0, 1.0)}},
                                   {});
    property["description"] = "The blending of a mask-stack effect (mono-channel).";
    return property;
}

json::Object ChannelsProperty(const char* description) {
    json::Object items = EnumProperty<core::ChannelType>("A channel type.");
    json::Object property = ArrayProperty(std::move(items), description);
    property["uniqueItems"] = true;
    return property;
}

/// The insert position of a layer: at most one of `above`, `below` and `inside`; the top of the
/// (`texture_set`, `stack`) otherwise.
void AddLayerPosition(json::Object& properties) {
    properties["texture_set"] = TextureSetProperty();
    properties["stack"] = StackProperty();
    properties["above"] = UidProperty("Insert directly above this layer (its stack and parent).");
    properties["below"] = UidProperty("Insert directly below this layer (its stack and parent).");
    properties["inside"] = UidProperty("Insert at the top of this group's sub-layers.");
}

/// The fields `layer_set` sets (and `layer_insert`'s `params`).
json::Object LayerFields() {
    json::Object fields{
        {"name", StringProperty("The layer's name.")},
        {"visible", BoolProperty("Whether the layer is visible.")},
        {"blending", BlendingProperty()},
        {"collapsed", BoolProperty("A group's collapsed state (inert UI state, kept as state).")},
        {"geometry_mask",
         CapabilityByValue(
             ObjectProperty({{"type", EnumProperty<core::GeometryMaskType>("Mesh or UVTile.")},
                             {"inclusion_list", BoolProperty("True: only `items` are included; false: `items` are excluded.")},
                             {"items", ArrayProperty(json::Object{{"type", "string"}}, "Mesh or UV-tile names.")}},
                            {"type", "items"}, "The layer's geometry mask."),
             {{"*", "substance_painter.layerstack.LayerNode.set_geometry_mask"}})},
    };
    return fields;
}

/// The fields `fill_set` sets (and a fill's `params`).
json::Object FillFields() {
    std::vector<std::pair<std::string, const char*>> modes;
    static const std::map<std::string, const char*> kModeSymbols{
        {"Fill", "substance_painter.layerstack.ProjectionMode.Fill"},
        {"UV", "substance_painter.layerstack.ProjectionMode.UV"},
        {"Triplanar", "substance_painter.layerstack.ProjectionMode.Triplanar"},
        {"Planar", "substance_painter.layerstack.ProjectionMode.Planar"},
        {"Spherical", "substance_painter.layerstack.ProjectionMode.Spherical"},
        {"Cylindrical", "substance_painter.layerstack.ProjectionMode.Cylindrical"},
        {"Warp", "substance_painter.layerstack.ProjectionMode.Warp"},
        {"UVSetToUVSet", "substance_painter.layerstack.ProjectionMode.UVSetToUVSet"}};
    for (const auto& [mode, symbol] : kModeSymbols) modes.emplace_back(mode, symbol);
    json::Object pair = ArrayProperty(json::Object{{"type", "number"}}, "[u, v].");
    pair["minItems"] = 2;
    pair["maxItems"] = 2;
    return {
        {"active_channels", ChannelsProperty("The channels the fill writes; assigning them changes no source (LAY-01).")},
        {"projection_mode", CapabilityByValue(EnumProperty<core::ProjectionMode>("The projection mode."), modes)},
        {"projection",
         ObjectProperty({{"filtering_mode", EnumProperty<core::FilteringMode>("The filtering mode.")},
                         {"uv_wrapping_mode", EnumProperty<core::UVWrapMode>("The UV wrapping mode.")},
                         {"scale_mode", EnumProperty<core::ScaleMode>("The scale mode.")},
                         {"scale", pair},
                         {"rotation", NumberProperty("Rotation, in degrees.")},
                         {"offset", pair}},
                        {}, "UV projection parameters (the UV and Fill projection modes).")},
        {"symmetry", BoolProperty("Whether the fill's symmetry is enabled.")},
        {"source_mode",
         CapabilityByValue(EnumProperty<core::SourceMode>("Split (one source per channel) or Material."),
                           {{"Split", "uzpainter.source.SourceMode.Split"},
                            {"Material", "substance_painter.layerstack.FillLayerNode.set_material_source"}})},
    };
}

/// The fields `effect_set` sets (and `effect_insert`'s `params`).
json::Object EffectFields() {
    json::Object component = Schema({{"input_min", NumberProperty("")},
                                     {"input_max", NumberProperty("")},
                                     {"gamma", NumberProperty("")},
                                     {"output_min", NumberProperty("")},
                                     {"output_max", NumberProperty("")},
                                     {"clamp", BoolProperty("")}},
                                    {});
    json::Object components = ArrayProperty(std::move(component), "One component (mono channel or mask) or three (RGB).", 1);
    components["maxItems"] = 3;
    return {
        {"name", StringProperty("The effect's name.")},
        {"visible", BoolProperty("Whether the effect is visible.")},
        {"blending", BlendingProperty()},
        {"mono_blending", MonoBlendingProperty()},
        {"levels", ObjectProperty({{"affected_channel", EnumProperty<core::ChannelType>("The channel a levels effect affects.")},
                                   {"components", std::move(components)}},
                                  {}, "A levels effect's parameters.")},
    };
}

json::Object Merge(json::Object a, const json::Object& b) {
    for (const auto& [key, value] : b) a[key] = value;
    return a;
}

// ── Argument readers ────────────────────────────────────────────────────────────────────────────

/// The value of `key` unless absent or null.
const json::Value* Given(const json::Object& object, std::string_view key) {
    const json::Value* value = Field(object, key);
    return value == nullptr || value->IsNull() ? nullptr : value;
}

std::string Text(const json::Value& value, const std::string& what) {
    if (!value.IsString()) Invalid(what + " must be a string");
    return std::get<std::string>(value.data);
}

bool Flag(const json::Value& value, const std::string& what) {
    if (!value.IsBool()) Invalid(what + " must be a boolean");
    return std::get<bool>(value.data);
}

double Number(const json::Value& value, const std::string& what) {
    if (value.IsInt()) return static_cast<double>(std::get<std::int64_t>(value.data));
    if (!value.IsDouble()) Invalid(what + " must be a number");
    return std::get<double>(value.data);
}

std::int64_t Integer(const json::Value& value, const std::string& what) {
    if (!value.IsInt()) Invalid(what + " must be an integer");
    return std::get<std::int64_t>(value.data);
}

const json::Object& ObjectOf(const json::Value& value, const std::string& what) {
    if (!value.IsObject()) Invalid(what + " must be an object");
    return std::get<json::Object>(value.data);
}

const json::Array& ArrayOf(const json::Value& value, const std::string& what) {
    if (!value.IsArray()) Invalid(what + " must be an array");
    return std::get<json::Array>(value.data);
}

template <typename E>
E EnumOf(const json::Value& value, const std::string& what) {
    const std::optional<E> parsed = core::FromString<E>(Text(value, what));
    if (!parsed) Invalid(what + " is not a known member");
    return *parsed;
}

core::Id Uid(const json::Value& value, const std::string& what) {
    const std::int64_t uid = Integer(value, what);
    if (uid < 1) Invalid(what + " must be a node uid (a positive integer)");
    return static_cast<core::Id>(uid);
}

core::Id RequiredUid(const json::Object& arguments, std::string_view key) {
    const json::Value* value = Given(arguments, key);
    if (!value) Invalid(std::string(key) + " is required");
    return Uid(*value, std::string(key));
}

/// A project resource reference: a `resource://project/<name>?version=<sha256>` URL, or a name
/// (unique among the project's resources).
python::ResourceIdHandle ResourceRef(const json::Value& value, const std::string& what) {
    const std::string text = Text(value, what);
    if (text.starts_with("resource://")) {
        try {
            const core::ProjectResourceUrl url = core::ParseResourceUrl(text);
            return {"project", url.name, url.sha256};
        } catch (const core::ValueError& error) {
            Invalid(what + ": " + error.what());
        }
    }
    return {"project", text, ""};
}

std::array<double, 2> Pair(const json::Value& value, const std::string& what) {
    const json::Array& items = ArrayOf(value, what);
    if (items.size() != 2) Invalid(what + " must be [u, v]");
    return {Number(items[0], what), Number(items[1], what)};
}

std::set<core::ChannelType> Channels(const json::Value& value, const std::string& what) {
    std::set<core::ChannelType> channels;
    for (const json::Value& item : ArrayOf(value, what)) channels.insert(EnumOf<core::ChannelType>(item, what));
    return channels;
}

json::Array UidList(const std::vector<core::Id>& ids) {
    json::Array list;
    for (const core::Id id : ids) list.push_back(static_cast<std::int64_t>(id));
    return list;
}

/// The open project (`project_error` when none, from the session).
std::shared_ptr<python::OpenProject> Open() { return python::Session::Get().Current(); }

const core::TextureSet& SetNamed(const core::Project& project, const std::string& name) {
    for (const core::TextureSet& set : project.texture_sets) {
        if (set.name == name) return set;
    }
    Invalid("no texture set " + name);
}

// ── Errors ──────────────────────────────────────────────────────────────────────────────────────

bool GapClass(const std::string& cls) {
    return cls == "NotYetSupported" || cls == "UnsupportedProcedural" || cls == "ReleaseGap" ||
           cls == "PathTracerUnavailable";
}

CallError Gap(const std::string& tool, const std::string& reason, const std::string& type) {
    return CallError{"capability_gap", tool + ": a release gap of this build: " + reason,
                     json::Object{{"tool", tool}, {"type", type}, {"reason", reason}}};
}

/// Runs a typed tool's work and gives its errors their MCP codes: an ambiguous name is
/// `ambiguous_name {candidates}` (LAY-06), a release gap met by the native code (`NotYetSupported`
/// and its kin) `capability_gap` (nothing is committed either way).
json::Object Translated(const std::string& tool, const std::function<json::Object()>& run) {
    try {
        return run();
    } catch (const core::AmbiguousNameError& error) {
        throw CallError{"ambiguous_name", error.what(), json::Object{{"candidates", UidList(error.candidates())}}};
    } catch (const core::NotYetSupported& error) {
        throw Gap(tool, error.what(), "NotYetSupported");
    } catch (const python::ApiError& error) {
        if (GapClass(error.cls())) throw Gap(tool, error.what(), error.cls());
        throw;
    } catch (const CallError& error) {
        // A transaction the support check failed (`evaluator::RequireSupported`, decision 082).
        const json::Value* type = Field(error.details, "type");
        if (error.code == "call_failed" && type && type->IsString() && GapClass(std::get<std::string>(type->data))) {
            throw Gap(tool, error.message, std::get<std::string>(type->data));
        }
        throw;
    }
}

ToolDefinition Define(Tool tool, Handler handler) {
    const std::string name = tool.name;
    return {std::move(tool),
            [name, handler = std::move(handler)](const json::Object& arguments) {
                return Translated(name, [&] { return handler(arguments); });
            },
            nullptr, std::nullopt};
}

ToolDefinition DefineJob(Tool tool, std::optional<std::string> commit_point, JobHandler job) {
    const std::string name = tool.name;
    JobHandler wrapped = [name, job = std::move(job)](const json::Object& arguments) -> python::JobBody {
        python::JobBody body;
        Translated(name, [&] {
            body = job(arguments);
            return json::Object{};
        });
        return [name, body = std::move(body)](python::JobContext& context) {
            return Translated(name, [&] { return body(context); });
        };
    };
    return {std::move(tool), nullptr, std::move(wrapped), std::move(commit_point)};
}

/// A tool of a family whose native implementation is not in this build: its schema and its
/// release-gap operations are listed, and a call is refused before anything runs.
ToolDefinition GapTool(Tool tool, std::string reason) {
    const std::string name = tool.name;
    const json::Array operations = tool.capability;
    return {std::move(tool),
            [name, reason, operations](const json::Object&) -> json::Object {
                CallError gap = Gap(name, reason, "NotYetSupported");
                gap.details["operations"] = operations;
                throw gap;
            },
            nullptr, std::nullopt};
}

json::Array Operations(std::initializer_list<const char*> symbols) {
    json::Array operations;
    for (const char* symbol : symbols) operations.push_back(json::Object{{"symbol", symbol}, {"context", "any"}});
    return operations;
}

// ── Node edits ──────────────────────────────────────────────────────────────────────────────────

void ApplyBlending(core::Edit& edit, core::Id uid, const json::Value& blending) {
    const std::optional<core::NodeType> type = core::FindNodeType(edit.project(), uid);
    if (type && !python::HasBlending(*type)) Invalid("node " + std::to_string(uid) + " has no blending");
    for (const auto& [name, entry] : ObjectOf(blending, "blending")) {
        const std::optional<core::ChannelType> channel = core::FromString<core::ChannelType>(name);
        if (!channel) Invalid("blending: " + name + " is not a channel type");
        const json::Object& fields = ObjectOf(entry, "blending." + name);
        core::Blending& target = python::EditBlending(edit, uid, channel);
        if (const json::Value* mode = Given(fields, "mode")) target.mode = EnumOf<core::BlendingMode>(*mode, "mode");
        if (const json::Value* opacity = Given(fields, "opacity")) target.opacity = python::F32(Number(*opacity, "opacity"));
    }
}

void ApplyMonoBlending(core::Edit& edit, core::Id uid, const json::Value& blending) {
    const json::Object& fields = ObjectOf(blending, "mono_blending");
    core::Blending& target = python::EditBlending(edit, uid, std::nullopt);
    if (const json::Value* mode = Given(fields, "mode")) target.mode = EnumOf<core::BlendingMode>(*mode, "mode");
    if (const json::Value* opacity = Given(fields, "opacity")) target.opacity = python::F32(Number(*opacity, "opacity"));
}

/// `layer_set`'s fields on layer `uid`.
void ApplyLayerFields(core::Edit& edit, core::Id uid, const json::Object& fields) {
    if (core::FindLayer(edit.project(), uid) == nullptr) Invalid("node " + std::to_string(uid) + " is not a layer");
    core::Layer& layer = python::EditLayer(edit, uid);
    if (const json::Value* name = Given(fields, "name")) layer.name = Text(*name, "name");
    if (const json::Value* visible = Given(fields, "visible")) layer.visible = Flag(*visible, "visible");
    if (const json::Value* collapsed = Given(fields, "collapsed")) {
        if (layer.kind != core::LayerKind::group) Invalid("collapsed: layer " + std::to_string(uid) + " is not a group");
        layer.collapsed = Flag(*collapsed, "collapsed");
    }
    if (const json::Value* mask = Given(fields, "geometry_mask")) {
        const json::Object& given = ObjectOf(*mask, "geometry_mask");
        core::GeometryMask geometry;
        const json::Value* type = Given(given, "type");
        if (!type) Invalid("geometry_mask.type is required");
        geometry.type = EnumOf<core::GeometryMaskType>(*type, "geometry_mask.type");
        if (const json::Value* inclusion = Given(given, "inclusion_list")) {
            geometry.inclusion_list = Flag(*inclusion, "geometry_mask.inclusion_list");
        }
        if (const json::Value* items = Given(given, "items")) {
            for (const json::Value& item : ArrayOf(*items, "geometry_mask.items")) {
                geometry.items.push_back(Text(item, "geometry_mask.items"));
            }
        }
        python::EditLayer(edit, uid).geometry_mask = std::move(geometry);
    }
    if (const json::Value* blending = Given(fields, "blending")) ApplyBlending(edit, uid, *blending);
}

/// `fill_set`'s fields on the fill layer or fill effect `uid`.
void ApplyFillFields(core::Edit& edit, core::Id uid, const json::Object& fields) {
    bool mask = false;
    core::FillContent& fill = python::EditFill(edit, uid, &mask);
    if (const json::Value* source_mode = Given(fields, "source_mode")) {
        if (EnumOf<core::SourceMode>(*source_mode, "source_mode") == core::SourceMode::Material) {
            throw python::ApiError("UnsupportedProcedural", "material sources are release gaps (phase3.2_proc-material-families)");
        }
        fill.source_mode = core::SourceMode::Split;
    }
    if (const json::Value* channels = Given(fields, "active_channels")) {
        if (mask) Invalid("a mask-stack fill has no active channels");
        fill.active_channels = Channels(*channels, "active_channels");  // sources are kept as they are (LAY-01)
    }
    if (const json::Value* mode = Given(fields, "projection_mode")) {
        fill.projection.mode = EnumOf<core::ProjectionMode>(*mode, "projection_mode");
    }
    if (const json::Value* projection = Given(fields, "projection")) {
        if (fill.projection.mode != core::ProjectionMode::UV && fill.projection.mode != core::ProjectionMode::Fill) {
            throw core::ValueError("UVProjectionParams need the UV or Fill projection mode");
        }
        const json::Object& given = ObjectOf(*projection, "projection");
        core::UVProjectionParams& uv = fill.projection.uv;
        if (const json::Value* v = Given(given, "filtering_mode")) uv.filtering_mode = EnumOf<core::FilteringMode>(*v, "filtering_mode");
        if (const json::Value* v = Given(given, "uv_wrapping_mode")) uv.uv_wrapping_mode = EnumOf<core::UVWrapMode>(*v, "uv_wrapping_mode");
        if (const json::Value* v = Given(given, "scale_mode")) uv.uv_transformation.scale_mode = EnumOf<core::ScaleMode>(*v, "scale_mode");
        if (const json::Value* v = Given(given, "scale")) uv.uv_transformation.scale = python::F32(Pair(*v, "scale"));
        if (const json::Value* v = Given(given, "rotation")) uv.uv_transformation.rotation = python::F32(Number(*v, "rotation"));
        if (const json::Value* v = Given(given, "offset")) uv.uv_transformation.offset = python::F32(Pair(*v, "offset"));
    }
    if (const json::Value* symmetry = Given(fields, "symmetry")) fill.symmetry.enabled = Flag(*symmetry, "symmetry");
}

/// `effect_set`'s fields on effect `uid`.
void ApplyEffectFields(core::Edit& edit, core::Id uid, const json::Object& fields) {
    if (core::FindEffect(edit.project(), uid) == nullptr) Invalid("node " + std::to_string(uid) + " is not an effect");
    core::Effect& effect = python::EditEffect(edit, uid);
    if (const json::Value* name = Given(fields, "name")) effect.name = Text(*name, "name");
    if (const json::Value* visible = Given(fields, "visible")) effect.visible = Flag(*visible, "visible");
    if (const json::Value* blending = Given(fields, "blending")) ApplyBlending(edit, uid, *blending);
    if (const json::Value* blending = Given(fields, "mono_blending")) {
        if (!python::HasBlending(effect.type())) Invalid("node " + std::to_string(uid) + " has no blending");
        ApplyMonoBlending(edit, uid, *blending);
    }
    if (const json::Value* levels = Given(fields, "levels")) {
        if (python::EditEffect(edit, uid).kind != core::EffectKind::levels) {
            Invalid("levels: effect " + std::to_string(uid) + " is not a levels effect");
        }
        const json::Object& given = ObjectOf(*levels, "levels");
        if (const json::Value* channel = Given(given, "affected_channel")) {
            python::SetAffectedChannel(edit, uid, EnumOf<core::ChannelType>(*channel, "levels.affected_channel"));
        }
        if (const json::Value* components = Given(given, "components")) {
            const json::Array& items = ArrayOf(*components, "levels.components");
            if (items.size() != 1 && items.size() != 3) Invalid("levels.components must hold one or three components");
            std::vector<core::LevelsComponent> parsed;
            for (const json::Value& item : items) {
                const json::Object& c = ObjectOf(item, "levels.components");
                const auto number = [&](const char* key, double fallback) {
                    const json::Value* v = Given(c, key);
                    return v ? Number(*v, std::string("levels.components.") + key) : fallback;
                };
                const json::Value* clamp = Given(c, "clamp");
                parsed.push_back(python::Component(number("input_min", 0.0), number("input_max", 1.0), number("gamma", 1.0),
                                                   number("output_min", 0.0), number("output_max", 1.0),
                                                   clamp ? Flag(*clamp, "levels.components.clamp") : false));
            }
            core::Effect& target = python::EditEffect(edit, uid);
            if (!target.levels) target.levels = core::LevelsParams{};
            target.levels->components = std::move(parsed);
        }
    }
}

/// Whether `params` holds a `fill_set` field.
bool HasFillFields(const json::Object& params) {
    static const std::set<std::string, std::less<>> kFillKeys{"active_channels", "projection_mode", "projection",
                                                               "symmetry", "source_mode"};
    return std::any_of(params.begin(), params.end(), [](const auto& entry) { return kFillKeys.contains(entry.first); });
}

/// A layer's `params`: its `layer_set` fields, and its `fill_set` fields when it is a fill.
void ApplyLayerParams(core::Edit& edit, core::Id uid, const json::Object& params) {
    ApplyLayerFields(edit, uid, params);
    if (HasFillFields(params)) ApplyFillFields(edit, uid, params);
}

void ApplyEffectParams(core::Edit& edit, core::Id uid, const json::Object& params) {
    ApplyEffectFields(edit, uid, params);
    if (HasFillFields(params)) ApplyFillFields(edit, uid, params);
}

/// The insert position of `layer_insert` and `layer_instantiate`.
core::InsertPosition LayerPosition(const json::Object& arguments) {
    const json::Value* above = Given(arguments, "above");
    const json::Value* below = Given(arguments, "below");
    const json::Value* inside = Given(arguments, "inside");
    if ((above != nullptr) + (below != nullptr) + (inside != nullptr) > 1) {
        Invalid("give at most one of above, below and inside");
    }
    if ((above || below || inside) && (Given(arguments, "texture_set") || Given(arguments, "stack"))) {
        Invalid("texture_set and stack address the top of a stack; above, below and inside name the place by a node");
    }
    if (above) return core::InsertPosition::Above(Uid(*above, "above"));
    if (below) return core::InsertPosition::Below(Uid(*below, "below"));
    if (inside) return core::InsertPosition::Inside(Uid(*inside, "inside"), core::NodeStack::Substack);
    const std::shared_ptr<python::OpenProject> open = Open();
    const core::Snapshot snapshot = open->document->snapshot();
    const auto [set, stack] = NamedStack(*snapshot.project, *open, arguments);
    return core::InsertPosition::FromStack(set->id, stack->id);
}

/// `{status, ...}` of an insert: the transaction result, whose `returned` names the node.
json::Object InsertCall(const ToolContext& context, const core::InsertPosition& position, core::NodeType type,
                        const json::Object& arguments, bool defaults,
                        const std::function<void(core::Edit&, core::Id, const json::Object&)>& apply,
                        core::Id instance_source = core::kNoId) {
    const std::optional<std::string> name = StringField(arguments, "name");
    const json::Value* params = Given(arguments, "params");
    if (params) ObjectOf(*params, "params");
    return context.submit([&](core::Edit& edit) {
        const python::Inserted inserted = python::InsertNode(
            edit, position, type, name, instance_source, [&](core::Edit& e, core::Id uid) {
                if (defaults) python::InsertDefaults(e, uid, name.has_value());
            });
        // A named node found in place takes the params too (an upsert): repeating the call with the
        // same params changes nothing (LAY-06).
        if (params) apply(edit, inserted.uid, std::get<json::Object>(params->data));
    });
}

// ── Families ────────────────────────────────────────────────────────────────────────────────────

void ProjectFamily(const ToolContext& context, std::vector<ToolDefinition>& tools) {
    json::Object resolution{{"type", "integer"},
                            {"enum", json::Array{128, 256, 512, 1024, 2048, 4096, 8192}},
                            {"description", "The default texture resolution (a power of two)."}};
    json::Object settings = ObjectProperty(
        {{"normal_map_format", EnumProperty<core::NormalMapFormat>("OpenGL or DirectX.")},
         {"tangent_space_mode", EnumProperty<core::TangentSpace>("PerVertex or PerFragment.")},
         {"project_workflow",
          CapabilityByValue(EnumProperty<core::ProjectWorkflow>("The project workflow."),
                            {{"Default", "substance_painter.project.ProjectWorkflow.Default"},
                             {"TextureSetPerUVTile", "substance_painter.project.ProjectWorkflow.TextureSetPerUVTile"},
                             {"UVTile", "substance_painter.project.ProjectWorkflow.UVTile"}})},
         {"default_texture_resolution", std::move(resolution)},
         {"mesh_unit_scale", json::Object{{"type", "number"}, {"exclusiveMinimum", 0}, {"description", "The mesh unit scale."}}},
         {"import_cameras", BoolProperty("Whether the mesh's cameras are imported.")}},
        {}, "Painter's project.Settings members UzPainter reads.");
    json::Object mesh_map = Schema({{"texture_set", StringProperty("The texture set's name (a material of the mesh).")},
                                    {"usage", EnumProperty<core::MeshMapUsage>("The mesh map usage.")},
                                    {"path", PathProperty("A PNG file, imported as a project resource.", "resource")}},
                                   {"texture_set", "usage", "path"});
    tools.push_back(DefineJob(
        {"project_create",
         "Imports a mesh and creates an untitled project with one texture set per material, its mesh maps bound, in "
         "one transaction whose operation row is the call's (a long job; save_as gives it a path).",
         Schema({{"mesh", PathProperty("The mesh file (OBJ, FBX or glTF).", "mesh")},
                 {"settings", std::move(settings)},
                 {"mesh_maps", ArrayProperty(std::move(mesh_map), "Mesh maps to bind after the texture sets exist.")},
                 {"template", StringProperty("The id of an installed project template; \"default\" when omitted.")},
                 {"ocio_config_hash",
                  json::Object{{"type", "string"},
                               {"pattern", "^[0-9a-f]{64}$"},
                               {"description",
                                "The SHA-256 of the OCIO configuration the project is created under, where Painter "
                                "reads OCIO from its environment at create (the worker reads none). Only Painter's "
                                "substance config is supported; any other hash is refused before anything is "
                                "created. Omitted: a Legacy project (decisions 207 and 212)."}}}},
                {"mesh"}),
         true, false, true, Operation("substance_painter.project.create")},
        "revision", [context](const json::Object& arguments) -> python::JobBody {
            const std::string mesh = Text(*Given(arguments, "mesh"), "mesh");
            python::CreateSettings settings;
            if (const json::Value* given = Given(arguments, "settings")) {
                const json::Object& s = ObjectOf(*given, "settings");
                if (const json::Value* v = Given(s, "normal_map_format")) settings.normal_map_format = EnumOf<core::NormalMapFormat>(*v, "normal_map_format");
                if (const json::Value* v = Given(s, "tangent_space_mode")) settings.tangent_space = EnumOf<core::TangentSpace>(*v, "tangent_space_mode");
                if (const json::Value* v = Given(s, "project_workflow")) settings.workflow = EnumOf<core::ProjectWorkflow>(*v, "project_workflow");
                if (const json::Value* v = Given(s, "default_texture_resolution")) {
                    settings.default_texture_resolution = static_cast<int>(Integer(*v, "default_texture_resolution"));
                }
                if (const json::Value* v = Given(s, "mesh_unit_scale")) settings.mesh_unit_scale = Number(*v, "mesh_unit_scale");
                if (const json::Value* v = Given(s, "import_cameras")) settings.import_cameras = Flag(*v, "import_cameras");
            }
            if (const json::Value* v = Given(arguments, "template")) settings.template_id = Text(*v, "template");
            if (const json::Value* v = Given(arguments, "ocio_config_hash")) settings.ocio_config_hash = Text(*v, "ocio_config_hash");
            python::CheckCreateSettings(settings);  // refused before the job, so nothing is created
            // The mesh maps' files are read before the job, so a missing one fails before anything.
            struct MeshMap {
                std::string texture_set;
                core::MeshMapUsage usage;
                python::ResourceFile file;
            };
            std::vector<MeshMap> maps;
            if (const json::Value* given = Given(arguments, "mesh_maps")) {
                for (const json::Value& item : ArrayOf(*given, "mesh_maps")) {
                    const json::Object& m = ObjectOf(item, "mesh_maps[]");
                    maps.push_back({Text(*Field(m, "texture_set"), "texture_set"), EnumOf<core::MeshMapUsage>(*Field(m, "usage"), "usage"),
                                    python::ReadResourceFile(Text(*Field(m, "path"), "path"), python::ResourceUsage::TEXTURE,
                                                             std::nullopt)});
                }
            }
            const core::MutationRequest request = context.mutation();
            return [mesh, settings, maps, request](python::JobContext& job) {
                job.SetProgress(0.0, "creating a project from " + mesh);
                job.Checkpoint();
                python::CreateCall call;
                call.request = request;
                call.extra = [&maps](core::Edit& edit, store::ProjectStore& store) {
                    for (const MeshMap& map : maps) {
                        const core::Id set = SetNamed(edit.project(), map.texture_set).id;
                        const std::string sha256 = python::ImportResourceFile(edit, store, map.file, std::nullopt);
                        python::SetMeshMapResource(edit, set, map.usage, python::ResourceIdHandle{"project", map.file.entry, sha256});
                    }
                };
                const core::TransactionResult result =
                    python::Session::Get().Create(python::PathFromUtf8(mesh), settings, call);
                job.Commit({{"revision", result.revision}});
                return result.ToJson();
            };
        }));

    tools.push_back(DefineJob(
        {"project_save_as",
         "Saves the project to a new file and makes it the project's file (an untitled project gets its path); `full` "
         "also compacts. A long job with no commit point: repeating it saves the same revision to the same file.",
         Schema({{"path", PathProperty("The .uzp file to write.", "project")},
                 {"mode", Strings({"incremental", "full"}, "incremental (default) or full.")}},
                {"path"}),
         false, false, true, Operation("substance_painter.project.save_as")},
        std::nullopt, [](const json::Object& arguments) -> python::JobBody {
            const std::string path = Text(*Given(arguments, "path"), "path");
            const std::string mode = StringField(arguments, "mode").value_or("incremental");
            Open();  // project_error before the job when none is open
            return [path, mode](python::JobContext& job) {
                job.SetProgress(0.0, "saving as " + path);
                job.Checkpoint();
                python::Session& session = python::Session::Get();
                const core::Checkpoints saved = session.SaveAs(python::PathFromUtf8(path),
                                                               mode == "full" ? store::SaveMode::full : store::SaveMode::incremental);
                json::Object result{{"path", python::Utf8(session.Current()->project_source)}, {"current", saved.current}};
                result["named"] = saved.named ? json::Value(*saved.named) : json::Value(nullptr);
                result["previous"] = saved.previous ? json::Value(*saved.previous) : json::Value(nullptr);
                return result;
            };
        }));

    tools.push_back(Define({"project_recipe",
                            "The recipe dump of the committed revision (decision 122): every output-determining field, "
                            "its digest and what only a rebuild needs.",
                            Schema({}, {}), false, false, true, Operation("uzpainter.project.dump_recipe")},
                           [](const json::Object&) { return python::DumpCurrentRecipe(); }));

    tools.push_back(Define(
        {"project_revert",
         "Appends a revision whose content is that of an earlier revision or of a named checkpoint (one transaction).",
         Schema({{"revision", IntegerProperty("The revision to return to.", 0)},
                 {"checkpoint", Strings({"current", "named", "previous"}, "A checkpoint name.")}},
                {}),
         true, false, true, Operation("uzpainter.project.revert")},
        [context](const json::Object& arguments) {
            const json::Value* revision = Given(arguments, "revision");
            const std::optional<std::string> checkpoint = StringField(arguments, "checkpoint");
            if ((revision == nullptr) == !checkpoint.has_value()) Invalid("give exactly one of revision and checkpoint");
            const core::RequestOutcome outcome = python::Session::Get().RevertRequest(
                context.mutation(), revision ? std::optional(Integer(*revision, "revision")) : std::nullopt,
                checkpoint.value_or(""));
            return context.settle(outcome, nullptr);
        }));
}

json::Object ChannelsJson(const core::Stack& stack) {
    json::Object channels;
    for (const auto& [type, channel] : stack.channels) {
        channels[std::string(core::ToString(type))] =
            json::Object{{"format", std::string(core::ToString(channel.format))}, {"label", channel.label}};
    }
    return channels;
}

void TextureSetFamily(const ToolContext& context, std::vector<ToolDefinition>& tools) {
    tools.push_back(Define(
        {"set_list",
         "The texture sets of the committed revision: name, original (material) name, resolution, UV tiles, stacks with "
         "their channels, and mesh-map bindings.",
         Schema({}, {}), false, false, true, Operation("substance_painter.textureset.all_texture_sets")},
        [](const json::Object&) {
            const std::shared_ptr<python::OpenProject> open = Open();
            const core::Snapshot snapshot = open->document->snapshot();
            const core::Project& project = *snapshot.project;
            json::Array sets;
            for (const core::TextureSet& set : project.texture_sets) {
                json::Array stacks;
                for (const core::Stack& stack : set.stacks) {
                    stacks.push_back(json::Object{{"name", stack.name}, {"channels", ChannelsJson(stack)},
                                                  {"layers", static_cast<std::int64_t>(stack.root_layers.size())}});
                }
                json::Object maps;
                for (const auto& [usage, binding] : set.mesh_maps) {
                    const auto entries = project.resources.find(binding.resource);
                    maps[std::string(core::ToString(usage))] = json::Object{
                        {"sha256", binding.resource},
                        {"name", entries != project.resources.end() && !entries->second.empty()
                                     ? json::Value(entries->second.front().name)
                                     : json::Value(nullptr)},
                        {"invalid", binding.invalid}};
                }
                json::Array tiles;
                for (const core::UVTile& tile : set.uv_tiles) tiles.push_back(static_cast<std::int64_t>(tile.udim));
                sets.push_back(json::Object{{"name", set.name},
                                            {"original_name", set.original_name},
                                            {"resolution", json::Object{{"width", set.resolution.width}, {"height", set.resolution.height}}},
                                            {"uv_tiles", std::move(tiles)},
                                            {"stacks", std::move(stacks)},
                                            {"mesh_maps", std::move(maps)}});
            }
            return json::Object{{"revision", snapshot.revision}, {"texture_sets", std::move(sets)}};
        }));

    json::Object size{{"type", "integer"},
                      {"enum", json::Array{128, 256, 512, 1024, 2048, 4096, 8192}},
                      {"description", "A power of two from 128 to 8192."}};
    tools.push_back(Define(
        {"set_resolution", "Sets the resolution of one texture set, or of every texture set when none is named.",
         Schema({{"texture_set", TextureSetProperty()}, {"width", size}, {"height", size}}, {"width", "height"}), true,
         false, true, Operation("substance_painter.textureset.set_resolutions")},
        [context](const json::Object& arguments) {
            const int width = static_cast<int>(Integer(*Given(arguments, "width"), "width"));
            const int height = static_cast<int>(Integer(*Given(arguments, "height"), "height"));
            const std::optional<std::string> name = StringField(arguments, "texture_set");
            return context.submit([&](core::Edit& edit) {
                bool found = false;
                for (core::TextureSet& set : edit.project().texture_sets) {
                    if (name && set.name != *name) continue;
                    set.resolution.width = width;
                    set.resolution.height = height;
                    found = true;
                }
                if (!found) Invalid("no texture set " + name.value_or("in the project"));
            });
        }));

    tools.push_back(Define(
        {"set_rename",
         "Renames a texture set; its original (material) name is kept. Another set's name is refused; the same name "
         "is a no-op.",
         Schema({{"texture_set", TextureSetProperty()}, {"name", json::Object{{"type", "string"}, {"minLength", 1}}}},
                {"texture_set", "name"}),
         true, false},
        [context](const json::Object& arguments) {
            const std::string from = Text(*Given(arguments, "texture_set"), "texture_set");
            const std::string to = Text(*Given(arguments, "name"), "name");
            return context.submit([&](core::Edit& edit) {
                for (const core::TextureSet& other : edit.project().texture_sets) {
                    if (other.name == to && other.name != from) {
                        throw core::ValueError("another texture set is named '" + to + "' (" + std::to_string(other.id) + ")");
                    }
                }
                python::EditSet(edit, SetNamed(edit.project(), from).id).name = to;
            });
        }));

    json::Object channel_spec = Schema({{"channel", EnumProperty<core::ChannelType>("The channel type.")},
                                        {"format", EnumProperty<core::ChannelFormat>("The channel format.")},
                                        {"label", StringProperty("A user channel's label.")}},
                                       {"channel", "format"});
    tools.push_back(Define(
        {"set_channels",
         "Adds, removes and edits channels of a stack in one transaction (removal strips the channel from every node).",
         Schema({{"texture_set", TextureSetProperty()},
                 {"stack", StackProperty()},
                 {"add", ArrayProperty(channel_spec, "Channels to add.")},
                 {"remove", ChannelsProperty("Channels to remove.")},
                 {"edit", ArrayProperty(channel_spec, "Channels whose format (and label) change.")}},
                {}),
         true, false, true,
         Operations({"substance_painter.textureset.Stack.add_channel", "substance_painter.textureset.Stack.remove_channel",
                     "substance_painter.textureset.Stack.edit_channel"})},
        [context](const json::Object& arguments) {
            const std::shared_ptr<python::OpenProject> open = Open();
            const core::Snapshot snapshot = open->document->snapshot();
            const auto [set, stack] = NamedStack(*snapshot.project, *open, arguments);
            const python::StackHandle handle{set->id, stack->id};
            return context.submit([&](core::Edit& edit) {
                core::Stack& target = python::EditStack(edit, handle);
                if (const json::Value* removed = Given(arguments, "remove")) {
                    for (const core::ChannelType type : Channels(*removed, "remove")) {
                        if (target.channels.erase(type) == 0) {
                            throw core::ValueError("the stack has no " + std::string(core::ToString(type)) + " channel");
                        }
                        python::StripChannel(target.root_layers, type);
                    }
                }
                const auto each = [&](const char* key, const auto& apply) {
                    if (const json::Value* list = Given(arguments, key)) {
                        for (const json::Value& item : ArrayOf(*list, key)) {
                            const json::Object& c = ObjectOf(item, key);
                            const core::ChannelType type = EnumOf<core::ChannelType>(*Field(c, "channel"), "channel");
                            const core::ChannelFormat format = EnumOf<core::ChannelFormat>(*Field(c, "format"), "format");
                            const std::optional<std::string> label = StringField(c, "label");
                            apply(type, format, label);
                        }
                    }
                };
                each("add", [&](core::ChannelType type, core::ChannelFormat format, const std::optional<std::string>& label) {
                    if (target.channels.contains(type)) {
                        throw core::ValueError("the stack already has a " + std::string(core::ToString(type)) + " channel");
                    }
                    target.channels[type] = core::Channel{format, label.value_or(""), {}};
                });
                each("edit", [&](core::ChannelType type, core::ChannelFormat format, const std::optional<std::string>& label) {
                    const auto it = target.channels.find(type);
                    if (it == target.channels.end()) {
                        throw core::ValueError("the stack has no " + std::string(core::ToString(type)) + " channel");
                    }
                    it->second.format = format;
                    if (label) it->second.label = *label;
                });
            });
        }));

    json::Object binding = Schema({{"resource", ResourceProperty("A project resource: its URL or its name.")},
                                   {"path", PathProperty("A PNG file, imported as a project resource first.", "resource")}},
                                  {});
    binding["description"] = "Exactly one of resource and path; null unbinds the usage.";
    binding["type"] = json::Array{"object", "null"};
    tools.push_back(Define(
        {"set_mesh_maps",
         "Binds (or, with null, unbinds) mesh maps of a texture set, by usage, to project resources or to PNG files "
         "imported first, in one transaction.",
         Schema({{"texture_set", TextureSetProperty()},
                 {"maps", json::Object{{"type", "object"},
                                       {"propertyNames", json::Object{{"enum", EnumNames<core::MeshMapUsage>()}}},
                                       {"additionalProperties", binding},
                                       {"description", "{<usage>: {resource} | {path} | null}"}}}},
                {"texture_set", "maps"}),
         true, false, true, Operation("substance_painter.textureset.TextureSet.set_mesh_map_resource")},
        [context](const json::Object& arguments) {
            const std::string set_name = Text(*Given(arguments, "texture_set"), "texture_set");
            struct Binding {
                core::MeshMapUsage usage;
                std::optional<python::ResourceIdHandle> resource;
                std::optional<python::ResourceFile> file;
            };
            std::vector<Binding> bindings;
            for (const auto& [usage, value] : ObjectOf(*Given(arguments, "maps"), "maps")) {
                Binding b{EnumOf<core::MeshMapUsage>(json::Value(usage), "maps"), std::nullopt, std::nullopt};
                if (!value.IsNull()) {
                    const json::Object& given = ObjectOf(value, "maps." + usage);
                    const json::Value* resource = Given(given, "resource");
                    const json::Value* path = Given(given, "path");
                    if ((resource == nullptr) == (path == nullptr)) Invalid("maps." + usage + ": give exactly one of resource and path");
                    if (resource) b.resource = ResourceRef(*resource, "maps." + usage + ".resource");
                    else b.file = python::ReadResourceFile(Text(*path, "path"), python::ResourceUsage::TEXTURE, std::nullopt);
                }
                bindings.push_back(std::move(b));
            }
            const std::shared_ptr<python::OpenProject> open = Open();
            return context.submit([&](core::Edit& edit) {
                const core::Id set = SetNamed(edit.project(), set_name).id;
                for (const Binding& b : bindings) {
                    std::optional<python::ResourceIdHandle> resource = b.resource;
                    if (b.file) {
                        const std::string sha256 = python::ImportResourceFile(edit, *open->store, *b.file, std::nullopt);
                        resource = python::ResourceIdHandle{"project", b.file->entry, sha256};
                    }
                    python::SetMeshMapResource(edit, set, b.usage, resource);
                }
            });
        }));
}

json::Object ResourceEntry(const std::string& sha256, const core::ResourceMeta& meta, bool used) {
    const json::Value* group = Field(meta.extra, "group");
    return {{"name", meta.name},
            {"sha256", sha256},
            {"url", core::FormatResourceUrl({meta.name, sha256})},
            {"usage", meta.usage},
            {"mime", meta.mime},
            {"size", meta.size},
            {"group", group ? *group : json::Value(nullptr)},
            {"origin", meta.origin},
            {"used", used}};
}

/// The resource hashes the layer stacks and mesh maps of `project` bind.
std::set<std::string> BoundResources(const core::Project& project) {
    std::set<std::string> hashes;
    const auto fill = [&](const std::optional<core::FillContent>& content) {
        if (!content) return;
        const auto bound = [&](const core::Source& source) {
            if (source.kind() == core::SourceKind::bitmap) hashes.insert(std::get<core::BitmapSource>(source.value).resource.sha256);
        };
        for (const auto& [channel, source] : content->sources) bound(source);
        if (content->mono_source) bound(*content->mono_source);
    };
    core::ForEachNode(project, [&](const core::NodeVisit& visit) {
        fill(visit.layer ? visit.layer->fill : visit.effect->fill);
    });
    for (const core::TextureSet& set : project.texture_sets) {
        for (const auto& [usage, binding] : set.mesh_maps) hashes.insert(binding.resource);
    }
    return hashes;
}

void ResourceFamily(const ToolContext& context, std::vector<ToolDefinition>& tools) {
    tools.push_back(Define(
        {"resource_import",
         "Imports a file as a project resource (TEXTURE: a PNG; ENVIRONMENT: an equirectangular OpenEXR); identical "
         "bytes under the same name change nothing (skipped). Returns the entry's name, SHA-256 and URL.",
         Schema({{"path", PathProperty("The file to import.", "resource")},
                 {"usage", CapabilityByValue(Strings({"TEXTURE", "ENVIRONMENT", "COLOR_LUT", "GENERATOR", "SMART_MATERIAL"},
                                                     "The resource usage."),
                                             {{"TEXTURE", "substance_painter.resource.Usage.TEXTURE"},
                                              {"ENVIRONMENT", "uzpainter.resource.Usage.ENVIRONMENT"},
                                              {"COLOR_LUT", "uzpainter.resource.Usage.COLOR_LUT"},
                                              {"GENERATOR", "uzpainter.resource.Usage.GENERATOR"},
                                              {"SMART_MATERIAL", "uzpainter.resource.Usage.SMART_MATERIAL"}})},
                 {"name", StringProperty("The entry's name; the file's stem when omitted.")},
                 {"group", StringProperty("The resource group kept with the entry.")}},
                {"path", "usage"}),
         true, false, true, Operation("substance_painter.resource.import_project_resource")},
        [context](const json::Object& arguments) {
            static const std::map<std::string, python::ResourceUsage> kUsages{
                {"TEXTURE", python::ResourceUsage::TEXTURE},           {"ENVIRONMENT", python::ResourceUsage::ENVIRONMENT},
                {"COLOR_LUT", python::ResourceUsage::COLOR_LUT},       {"GENERATOR", python::ResourceUsage::GENERATOR},
                {"SMART_MATERIAL", python::ResourceUsage::SMART_MATERIAL}};
            const auto usage = kUsages.find(Text(*Given(arguments, "usage"), "usage"));
            if (usage == kUsages.end()) Invalid("usage is not a resource usage");
            const python::ResourceFile file = python::ReadResourceFile(Text(*Given(arguments, "path"), "path"),
                                                                       usage->second, StringField(arguments, "name"));
            const std::optional<std::string> group = StringField(arguments, "group");
            const std::shared_ptr<python::OpenProject> open = Open();
            return context.submit([&](core::Edit& edit) {
                const std::string sha256 = python::ImportResourceFile(edit, *open->store, file, group);
                edit.returned()["resource"] = json::Object{{"name", file.entry},
                                                           {"sha256", sha256},
                                                           {"url", core::FormatResourceUrl({file.entry, sha256})},
                                                           {"usage", file.kind}};
            });
        }));

    tools.push_back(Define(
        {"resource_list", "The project's resource entries: name, SHA-256, URL, usage, group, origin and whether a node or "
                          "mesh map binds them.",
         Schema({{"used_only", BoolProperty("List only the entries the layer stacks and mesh maps bind.")}}, {}), false,
         false},
        [](const json::Object& arguments) {
            const std::shared_ptr<python::OpenProject> open = Open();
            const core::Snapshot snapshot = open->document->snapshot();
            const std::set<std::string> bound = BoundResources(*snapshot.project);
            const json::Value* used_only = Given(arguments, "used_only");
            const bool only = used_only && Flag(*used_only, "used_only");
            json::Array entries;
            for (const auto& [sha256, metas] : snapshot.project->resources) {
                const bool used = bound.contains(sha256);
                if (only && !used) continue;
                for (const core::ResourceMeta& meta : metas) entries.push_back(ResourceEntry(sha256, meta, used));
            }
            return json::Object{{"revision", snapshot.revision}, {"resources", std::move(entries)}};
        }));

    tools.push_back(Define(
        {"resource_replace",
         "Rebinds every bitmap source that binds `old` to `new` (resource.update_layer_stack_resource), or, with `uid`, "
         "only that node's source (`channel` for a content-stack fill; LAY-08), in one transaction.",
         Schema({{"old", ResourceProperty("The replaced resource: its URL or its name.")},
                 {"new", ResourceProperty("The replacement: its URL or its name.")},
                 {"uid", UidProperty("Only this node's source.")},
                 {"channel", EnumProperty<core::ChannelType>("The channel of a content-stack fill's source (with uid).")}},
                {"new"}),
         true, false, true, Operation("substance_painter.resource.update_layer_stack_resource")},
        [context](const json::Object& arguments) {
            const python::ResourceIdHandle replacement = ResourceRef(*Given(arguments, "new"), "new");
            const json::Value* uid = Given(arguments, "uid");
            const json::Value* old = Given(arguments, "old");
            if (uid) {
                const core::Id node = Uid(*uid, "uid");
                const ChannelArg channel =
                    Given(arguments, "channel") ? std::optional(EnumOf<core::ChannelType>(*Given(arguments, "channel"), "channel"))
                                                : std::nullopt;
                const std::optional<python::ResourceIdHandle> expected =
                    old ? std::optional(ResourceRef(*old, "old")) : std::nullopt;
                return context.submit([&](core::Edit& edit) {
                    core::BitmapSource& bitmap = python::EditBitmap(edit, node, channel);
                    if (expected && bitmap.resource.sha256 != python::ResolveResource(edit.project(), *expected)) {
                        throw core::ValueError("node " + std::to_string(node) + " does not bind the resource old names");
                    }
                    bitmap.resource.sha256 = python::ResolveResource(edit.project(), replacement);
                    edit.returned()["nodes"] = json::Array{static_cast<std::int64_t>(node)};
                });
            }
            if (!old) Invalid("old is required without uid");
            if (Given(arguments, "channel")) Invalid("channel applies with uid only");
            const python::ResourceIdHandle from = ResourceRef(*old, "old");
            return context.submit([&](core::Edit& edit) {
                edit.returned()["nodes"] = UidList(python::ReplaceLayerStackResource(edit, from, replacement));
            });
        }));

    tools.push_back(GapTool({"resource_search", "Searches the resource libraries (shelves) by query.",
                             Schema({{"query", StringProperty("The search text.")}}, {"query"}), false, false, true,
                             Operation("substance_painter.resource.search")},
                            "searching resource libraries arrives with the asset library (phase3.3_procedural-families)"));
    tools.push_back(GapTool({"assets_search", "Searches the UzPainter asset library, with each asset's parity status.",
                             Schema({{"query", StringProperty("The search text.")}}, {"query"}), false, false, true,
                             Operation("uzpainter.assets.search")},
                            "the asset library with parity status arrives with the procedural families "
                            "(phase3.3_procedural-families)"));
}

json::Object StackNodes(const core::Project& project, std::int64_t revision, const core::TextureSet& set,
                        const core::Stack& stack, const std::optional<std::string>& name) {
    json::Object snapshot = core::SnapshotLayerTree(project, revision);
    json::Array nodes;
    for (json::Value& node : std::get<json::Array>(snapshot.at("nodes").data)) {
        const json::Object& record = std::get<json::Object>(node.data);
        if (record.at("texture_set") != json::Value(static_cast<std::int64_t>(set.id)) ||
            record.at("stack") != json::Value(static_cast<std::int64_t>(stack.id))) {
            continue;
        }
        if (name && record.at("name") != json::Value(*name)) continue;
        nodes.push_back(std::move(node));
    }
    return {{"revision", revision}, {"texture_set", set.name}, {"stack", stack.name}, {"nodes", std::move(nodes)}};
}

void StackFamily(const ToolContext& context, std::vector<ToolDefinition>& tools) {
    tools.push_back(Define(
        {"layer_list",
         "The nodes of one stack of the committed revision (the layer-tree snapshot's records: uid, node, kind, name, "
         "visibility, parent, slot, index and parameters), optionally only those named `name`.",
         Schema({{"texture_set", TextureSetProperty()}, {"stack", StackProperty()}, {"name", StringProperty("Only nodes of this name.")}},
                {}),
         false, false, true, Operation("substance_painter.layerstack.get_root_layer_nodes")},
        [](const json::Object& arguments) {
            const std::shared_ptr<python::OpenProject> open = Open();
            const core::Snapshot snapshot = open->document->snapshot();
            const auto [set, stack] = NamedStack(*snapshot.project, *open, arguments);
            return StackNodes(*snapshot.project, snapshot.revision, *set, *stack, StringField(arguments, "name"));
        }));

    json::Object layer_params = Merge(LayerFields(), FillFields());
    json::Object insert_properties{
        // The native inserts the tool performs (decision 182), as `effect_insert`.
        {"kind", CapabilityByValue(Strings({"fill", "group", "paint"}, "The layer kind."),
                                   {{"fill", "uzpainter.layerstack.insert_fill"},
                                    {"group", "uzpainter.layerstack.insert_group"},
                                    {"paint", "uzpainter.layerstack.insert_paint"}})},
        {"name", StringProperty("With a name, a layer of that name and kind already in the target list is used "
                                "instead of inserting another (LAY-06); several such layers fail ambiguous_name.")},
        {"params", ObjectProperty(layer_params, {}, "The layer_set (and, for a fill, fill_set) fields to set in the same transaction.")}};
    AddLayerPosition(insert_properties);
    tools.push_back(Define(
        {"layer_insert",
         "Inserts a layer with Painter's insert defaults at the top of a stack, above or below a layer, or inside a "
         "group, and sets its params, in one transaction; `returned` names the node and whether it was created.",
         Schema(insert_properties, {"kind"}), true, false},
        [context](const json::Object& arguments) {
            static const std::map<std::string, core::NodeType> kKinds{
                {"fill", core::NodeType::FillLayer}, {"group", core::NodeType::GroupLayer}, {"paint", core::NodeType::PaintLayer}};
            const auto kind = kKinds.find(Text(*Given(arguments, "kind"), "kind"));
            if (kind == kKinds.end()) Invalid("kind must be fill, group or paint");
            return InsertCall(context, LayerPosition(arguments), kind->second, arguments, true, ApplyLayerParams);
        }));

    tools.push_back(Define(
        {"layer_set", "Sets a layer's name, visibility, per-channel blending, collapsed state or geometry mask in one transaction.",
         Schema(Merge({{"uid", UidProperty("The layer.")}}, LayerFields()), {"uid"}), true, false, true,
         Operation("substance_painter.layerstack.Node.set_blending_mode")},
        [context](const json::Object& arguments) {
            const core::Id uid = RequiredUid(arguments, "uid");
            return context.submit([&](core::Edit& edit) { ApplyLayerFields(edit, uid, arguments); });
        }));

    tools.push_back(Define(
        {"layer_delete", "Deletes a layer or an effect, with everything it holds.",
         Schema({{"uid", UidProperty("The node.")}}, {"uid"}), true, false, true,
         Operation("substance_painter.layerstack.delete_node")},
        [context](const json::Object& arguments) {
            const core::Id uid = RequiredUid(arguments, "uid");
            return context.submit([&](core::Edit& edit) { python::RemoveNode(edit.project(), uid); });
        }));

    json::Object instantiate_properties{{"source", UidProperty("The layer to instance.")},
                                        {"name", StringProperty("The instance's name (LAY-06 as layer_insert).")}};
    AddLayerPosition(instantiate_properties);
    tools.push_back(Define(
        {"layer_instantiate", "Inserts an instance of a layer (layerstack.instantiate).",
         Schema(instantiate_properties, {"source"}), true, false, true, Operation("substance_painter.layerstack.instantiate")},
        [context](const json::Object& arguments) {
            const core::Id source = RequiredUid(arguments, "source");
            return InsertCall(context, LayerPosition(arguments), core::NodeType::InstanceLayer, arguments, false,
                              ApplyLayerFields, source);
        }));

    json::Object effect_params = Merge(EffectFields(), FillFields());
    tools.push_back(Define(
        {"effect_insert",
         "Inserts an effect with Painter's insert defaults into a layer's content or mask stack (at its top, or above or "
         "below one of its effects) and sets its params, in one transaction.",
         Schema({{"uid", UidProperty("The layer whose stack receives the effect.")},
                 {"stack", Strings({"content", "mask"}, "The layer's content or mask stack.")},
                 // The operations the tool performs: the native inserts of `uzpainter.layerstack`
                 // (decision 182), not the facade's, whose statuses can differ.
                 {"kind", CapabilityByValue(EnumProperty<core::EffectKind>("The effect kind."),
                                            {{"fill", "uzpainter.layerstack.insert_fill"},
                                             {"paint", "uzpainter.layerstack.insert_paint"},
                                             {"generator", "uzpainter.layerstack.insert_generator_effect"},
                                             {"filter", "uzpainter.layerstack.insert_filter_effect"},
                                             {"levels", "uzpainter.layerstack.insert_levels_effect"},
                                             {"compare_mask", "uzpainter.layerstack.insert_compare_mask_effect"},
                                             {"color_selection", "uzpainter.layerstack.insert_color_selection_effect"},
                                             {"anchor", "uzpainter.layerstack.insert_anchor_point_effect"}})},
                 {"above", UidProperty("Insert directly above this effect of the stack.")},
                 {"below", UidProperty("Insert directly below this effect of the stack.")},
                 {"name", StringProperty("With a name, an effect of that name and kind already in the stack is used instead "
                                         "(LAY-06).")},
                 {"params", ObjectProperty(effect_params, {}, "The effect_set (and, for a fill, fill_set) fields.")}},
                {"uid", "stack", "kind"}),
         true, false},
        [context](const json::Object& arguments) {
            const core::Id layer = RequiredUid(arguments, "uid");
            const core::NodeStack slot =
                Text(*Given(arguments, "stack"), "stack") == "mask" ? core::NodeStack::Mask : core::NodeStack::Content;
            const core::EffectKind kind = EnumOf<core::EffectKind>(*Given(arguments, "kind"), "kind");
            const json::Value* above = Given(arguments, "above");
            const json::Value* below = Given(arguments, "below");
            if (above && below) Invalid("give at most one of above and below");
            core::InsertPosition position = core::InsertPosition::Inside(layer, slot);
            if (above || below) {
                const core::Id sibling = Uid(above ? *above : *below, above ? "above" : "below");
                const std::shared_ptr<const core::Project> project = python::Session::Get().ReadProject();
                const python::NodeInfo info = python::Resolve(*project, sibling);
                if (info.effect == nullptr || info.owner != layer || info.owner_stack != slot) {
                    Invalid(std::string(above ? "above" : "below") + " must name an effect of that stack");
                }
                position = above ? core::InsertPosition::Above(sibling) : core::InsertPosition::Below(sibling);
            }
            return InsertCall(context, position, core::NodeTypeOf(kind), arguments, true, ApplyEffectParams);
        }));

    tools.push_back(Define(
        {"effect_set", "Sets an effect's name, visibility, blending (per channel, or mono in a mask stack) and levels parameters.",
         Schema(Merge({{"uid", UidProperty("The effect.")}}, EffectFields()), {"uid"}), true, false, true,
         Operation("substance_painter.layerstack.Node.set_blending_mode")},
        [context](const json::Object& arguments) {
            const core::Id uid = RequiredUid(arguments, "uid");
            return context.submit([&](core::Edit& edit) { ApplyEffectFields(edit, uid, arguments); });
        }));

    tools.push_back(Define(
        {"mask_set",
         "Adds (present: true, with background) or removes (present: false) a layer's mask, and sets its background and "
         "whether it is enabled; adding an existing mask or removing a missing one is a no-op.",
         Schema({{"uid", UidProperty("The layer.")},
                 {"present", BoolProperty("Whether the layer has a mask.")},
                 {"background", EnumProperty<core::MaskBackground>("The mask's background.")},
                 {"enabled", BoolProperty("Whether the mask is enabled.")}},
                {"uid"}),
         true, false, true, Operation("substance_painter.layerstack.LayerNode.add_mask")},
        [context](const json::Object& arguments) {
            const core::Id uid = RequiredUid(arguments, "uid");
            const json::Value* present = Given(arguments, "present");
            const json::Value* background = Given(arguments, "background");
            const json::Value* enabled = Given(arguments, "enabled");
            return context.submit([&](core::Edit& edit) {
                core::Layer& layer = python::EditLayer(edit, uid);
                if (present && !Flag(*present, "present")) {
                    if (background || enabled) Invalid("background and enabled need present: true or omitted");
                    layer.mask.reset();
                    return;
                }
                if (present && !layer.mask) layer.mask = core::Mask{};
                if (!layer.mask) throw core::ValueError("layer " + std::to_string(uid) + " has no mask");
                if (background) layer.mask->background = EnumOf<core::MaskBackground>(*background, "background");
                if (enabled) layer.mask->enabled = Flag(*enabled, "enabled");
            });
        }));

    json::Object color = ArrayProperty(json::Object{{"type", "number"}}, "r, g, b, stored as given (float32).");
    color["minItems"] = 3;
    color["maxItems"] = 3;
    json::Object source = Schema(
        {{"kind", CapabilityByValue(Strings({"uniform_color", "bitmap", "reference"}, "The source kind."),
                                    {{"uniform_color", "substance_painter.layerstack.FillLayerNode.set_source"},
                                     {"bitmap", "substance_painter.layerstack.FillLayerNode.set_source"},
                                     {"reference", "substance_painter.layerstack.AnchorPointEffectNode"}})},
         {"color", color},
         {"color_space", StringProperty("The colour space of a uniform colour (sRGB, Working, Raw, ...) or of a bitmap "
                                        "(sRGB, Raw, Data, ...); empty or omitted: none.")},
         {"resource", ResourceProperty("A bitmap's project resource: its URL or its name.")},
         {"anchor", UidProperty("A reference source's anchor point effect.")}},
        {"kind"});
    source["type"] = json::Array{"object", "null"};
    source["description"] = "The new source; null resets the channel's source.";
    tools.push_back(Define(
        {"source_set",
         "Sets (or, with null, resets) the source of one channel of a fill layer or fill effect, or the mono source of a "
         "mask-stack fill (no channel).",
         Schema({{"uid", UidProperty("The fill layer or fill effect.")},
                 {"channel", EnumProperty<core::ChannelType>("The channel (content stacks); omitted for a mask-stack fill.")},
                 {"source", source}},
                {"uid", "source"}),
         true, false},
        [context](const json::Object& arguments) {
            const core::Id uid = RequiredUid(arguments, "uid");
            const ChannelArg channel =
                Given(arguments, "channel") ? std::optional(EnumOf<core::ChannelType>(*Given(arguments, "channel"), "channel"))
                                            : std::nullopt;
            const json::Value* given = Field(arguments, "source");
            if (given == nullptr) Invalid("source is required (null resets it)");
            return context.submit([&](core::Edit& edit) {
                bool mask = false;
                core::FillContent& fill = python::EditFill(edit, uid, &mask);
                python::CheckChannel(mask, channel, uid);
                if (given->IsNull()) {
                    if (channel) fill.sources.erase(*channel);
                    else fill.mono_source.reset();
                    return;
                }
                const json::Object& spec = ObjectOf(*given, "source");
                const std::string kind = Text(*Given(spec, "kind"), "source.kind");
                const std::string space = StringField(spec, "color_space").value_or("");
                core::Source value;
                if (kind == "uniform_color") {
                    const json::Value* rgb = Given(spec, "color");
                    if (!rgb) Invalid("source.color is required for a uniform colour");
                    const json::Array& c = ArrayOf(*rgb, "source.color");
                    if (c.size() != 3) Invalid("source.color must be [r, g, b]");
                    value.value = core::UniformColorSource{
                        python::F32(std::array<double, 3>{Number(c[0], "color"), Number(c[1], "color"), Number(c[2], "color")}),
                        space, {}};
                } else if (kind == "bitmap") {
                    const json::Value* resource = Given(spec, "resource");
                    if (!resource) Invalid("source.resource is required for a bitmap");
                    const std::string sha256 = python::ResolveResource(edit.project(), ResourceRef(*resource, "source.resource"));
                    value.value = core::BitmapSource{core::ResourceBinding{sha256, std::nullopt, {}}, space, {}};
                } else {
                    throw core::NotYetSupported("anchor reference sources are release gaps (phase4.1_nodes-instances-anchors)");
                }
                if (fill.source_mode == core::SourceMode::Material) {
                    throw python::ApiError("RuntimeError", "the fill is in SourceMode.Material");
                }
                if (channel) fill.sources[*channel] = std::move(value);
                else fill.mono_source = std::move(value);
            });
        }));

    tools.push_back(Define(
        {"fill_set",
         "Sets a fill's active channels, projection mode and UV parameters, symmetry and source mode in one transaction.",
         Schema(Merge({{"uid", UidProperty("The fill layer or fill effect.")}}, FillFields()), {"uid"}), true, false, true,
         Operation("substance_painter.layerstack.FillLayerNode.set_projection_mode")},
        [context](const json::Object& arguments) {
            const core::Id uid = RequiredUid(arguments, "uid");
            return context.submit([&](core::Edit& edit) { ApplyFillFields(edit, uid, arguments); });
        }));

    tools.push_back(GapTool(
        {"procedural_set",
         "Sets a procedural source or effect's parameters, preset, image inputs, output mapping or resolution.",
         Schema({{"uid", UidProperty("The node.")},
                 {"channel", EnumProperty<core::ChannelType>("The channel of a fill's procedural source.")},
                 {"params", json::Object{{"type", "object"}}},
                 {"preset", StringProperty("A preset of the asset.")},
                 {"image_inputs", json::Object{{"type", "object"}}},
                 {"output_mapping", json::Object{{"type", "object"}}},
                 {"resolution", json::Object{{"type", "object"}}}},
                {"uid"}),
         true, false, true, Operation("uzpainter.layerstack.set_procedural")},
        "procedural content is a release gap (phase3.3_procedural-families)"));
    tools.push_back(GapTool(
        {"anchor_list", "The anchor point effects of a stack, with the nodes that reference them.",
         Schema({{"texture_set", TextureSetProperty()}, {"stack", StackProperty()}}, {}), false, false, true,
         Operation("substance_painter.layerstack.AnchorPointEffectNode")},
        "anchor points are a release gap (phase4.1_nodes-instances-anchors)"));
    json::Object smart_properties{{"asset", StringProperty("The smart material: a pinned uzasset:// URL or a project resource.")},
                                  {"name", StringProperty("The inserted group's name.")}};
    AddLayerPosition(smart_properties);
    tools.push_back(GapTool({"smart_material_insert", "Inserts a smart material (a group) at a layer position.",
                             Schema(smart_properties, {"asset"}), true, false, true,
                             Operation("substance_painter.layerstack.insert_smart_material")},
                            "smart materials are a release gap (phase3.6_smart-presets-projections)"));
    tools.push_back(GapTool({"smart_mask_insert", "Inserts a smart mask into a layer's mask stack.",
                             Schema({{"uid", UidProperty("The layer.")},
                                     {"asset", StringProperty("The smart mask: a pinned uzasset:// URL or a project resource.")},
                                     {"name", StringProperty("The inserted effect's name.")}},
                                    {"uid", "asset"}),
                             true, false, true, Operation("substance_painter.layerstack.insert_smart_mask")},
                            "smart masks are a release gap (phase3.6_smart-presets-projections)"));
    tools.push_back(GapTool(
        {"smart_export", "Exports a group as a smart material, or a mask stack as a smart mask, to a file.",
         Schema({{"uid", UidProperty("The group or layer.")},
                 {"kind", CapabilityByValue(Strings({"material", "mask"}, "material or mask."),
                                            {{"material", "substance_painter.layerstack.export_as_smart_material"},
                                             {"mask", "substance_painter.layerstack.export_as_smart_mask"}})},
                 {"path", PathProperty("The file to write.", "export")}},
                {"uid", "kind", "path"}),
         false, false, true, Operation("substance_painter.layerstack.export_as_smart_material")},
        "smart presets are a release gap (phase3.6_smart-presets-projections)"));
}

void RecipeFamily(const ToolContext& context, std::vector<ToolDefinition>& tools) {
    tools.push_back(Define(
        {"sync_stack",
         "LAY-07: rebuilds the root group the stack JSON names (painter_layer_stack.py sync semantics) from it and the "
         "PNG images of masks_dir, in one transaction; every other visible root layer is hidden, never deleted, unless "
         "its name starts with a keep_visible prefix; images are imported as resources named "
         "<resource_prefix><name> in resource_group. `returned.sync` lists the groups, layers, imports and hidden nodes.",
         Schema({{"stack_json", json::Object{{"type", json::Array{"object", "string"}},
                                             {"description", "The stack JSON, as an object or as the path of its file."},
                                             {"x-uzpainter-root", "resource"}}},
                 {"stack_key", StringProperty("`a.b`: the stack is the object under key a, then b, of the JSON.")},
                 {"masks_dir", PathProperty("The folder of the PNG images the stack names (<name>.png).", "resource")},
                 {"resource_prefix", StringProperty("The prefix of the imported images' resource names.")},
                 {"resource_group", StringProperty("The resource group of the imported images.")},
                 {"keep_visible", ArrayProperty(json::Object{{"type", "string"}}, "Name prefixes of root layers that stay visible.")},
                 {"texture_set", TextureSetProperty()},
                 {"stack", StackProperty()}},
                {"stack_json", "masks_dir"}),
         true, false, true, Operation("uzpainter.layerstack.sync_stack")},
        [context](const json::Object& arguments) {
            const json::Value& given = *Given(arguments, "stack_json");
            json::Value document = given;
            std::string source_name = "<object>";
            if (given.IsString()) {
                source_name = std::get<std::string>(given.data);
                std::ifstream file(python::PathFromUtf8(source_name), std::ios::binary);
                if (!file) Invalid("stack_json: cannot read " + source_name);
                try {
                    document = json::Parse(std::string{std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()});
                } catch (const json::ParseError& error) {
                    Invalid("stack_json: " + source_name + " is not JSON: " + error.what());
                }
            }
            if (const std::optional<std::string> key = StringField(arguments, "stack_key")) {
                std::string rest = *key;
                while (!rest.empty()) {
                    const std::size_t dot = rest.find('.');
                    const std::string part = rest.substr(0, dot);
                    rest = dot == std::string::npos ? "" : rest.substr(dot + 1);
                    if (!document.IsObject() || !std::get<json::Object>(document.data).contains(part)) {
                        Invalid("stack_json: " + source_name + " has no key '" + *key + "'");
                    }
                    json::Value inner = std::get<json::Object>(document.data).at(part);
                    document = std::move(inner);
                }
            }
            const json::Object& stack_json = ObjectOf(document, "stack_json");
            const std::shared_ptr<python::OpenProject> open = Open();
            const core::Snapshot snapshot = open->document->snapshot();
            const auto [set, stack] = NamedStack(*snapshot.project, *open, arguments);
            python::SyncOptions options{set->id, stack->id, {}, StringField(arguments, "resource_prefix").value_or(""),
                                        StringField(arguments, "resource_group")};
            if (const json::Value* keep = Given(arguments, "keep_visible")) {
                for (const json::Value& prefix : ArrayOf(*keep, "keep_visible")) options.keep_visible.push_back(Text(prefix, "keep_visible"));
            }
            const python::ImageReader read = python::MaskImageReader(python::PathFromUtf8(Text(*Given(arguments, "masks_dir"), "masks_dir")));
            return context.submit([&](core::Edit& edit) {
                edit.returned()["sync"] = python::SyncStack(edit, *open->store, stack_json, read, options);
            });
        }));

    tools.push_back(GapTool(
        {"apply_smart",
         "Applies a smart-material configuration (painter_layer_stack.py smart semantics) to a texture set.",
         Schema({{"config_json", json::Object{{"type", json::Array{"object", "string"}},
                                              {"description", "The configuration, as an object or as the path of its file."},
                                              {"x-uzpainter-root", "resource"}}},
                 {"texture_set", TextureSetProperty()}},
                {"config_json"}),
         true, false, true, Operation("substance_painter.layerstack.insert_smart_material")},
        "smart materials are a release gap (phase3.6_smart-presets-projections)"));
}

void BakingFamily(std::vector<ToolDefinition>& tools) {
    const std::string reason = "native baking is a release gap (phase3.5_embree-bakers)";
    tools.push_back(GapTool({"bake_inspect", "A texture set's baking parameters: bakers, UV tiles, common and per-baker values.",
                             Schema({{"texture_set", TextureSetProperty()}}, {}), false, false, true,
                             Operation("substance_painter.baking.BakingParameters.from_texture_set")},
                            reason));
    tools.push_back(GapTool(
        {"bake_configure", "Sets a texture set's baking parameters: enabled, bakers, UV tiles, curvature method, common and "
                           "per-baker values.",
         Schema({{"texture_set", TextureSetProperty()},
                 {"enabled", BoolProperty("Whether the texture set is baked.")},
                 {"bakers", ArrayProperty(json::Object{{"type", "string"}}, "The enabled bakers.")},
                 {"uv_tiles", ArrayProperty(json::Object{{"type", "integer"}}, "The enabled UV tiles (UDIM numbers).")},
                 {"curvature_method", StringProperty("The curvature method.")},
                 {"common", json::Object{{"type", "object"}}},
                 {"per_baker", json::Object{{"type", "object"}}}},
                {"texture_set"}),
         true, false, true, Operation("substance_painter.baking.BakingParameters.set")},
        reason));
    tools.push_back(GapTool({"bake_set_mesh_inputs", "Sets the high-poly meshes (and cage) a texture set bakes from.",
                             Schema({{"texture_set", TextureSetProperty()},
                                     {"high_poly", ArrayProperty(PathProperty("A mesh file.", "bake_mesh"), "The high-poly meshes.")},
                                     {"cage", PathProperty("The cage mesh.", "bake_mesh")}},
                                    {"texture_set"}),
                             true, false, true, Operation("substance_painter.baking.BakingParameters.set")},
                            reason));
    tools.push_back(GapTool({"bake_start", "Bakes the mesh maps of texture sets (a long job).",
                             Schema({{"sets", ArrayProperty(json::Object{{"type", "string"}}, "The texture sets; every enabled one when omitted.")},
                                     {"wait", BoolProperty("Wait for the job's end.")}},
                                    {}),
                             true, false, true, Operation("substance_painter.baking.bake_async")},
                            reason));
    tools.push_back(GapTool({"bake_capture_preset", "Captures a texture set's baking parameters as a baking preset.",
                             Schema({{"texture_set", TextureSetProperty()}, {"path", PathProperty("The preset file.", "export")}},
                                    {"path"}),
                             false, false, true, Operation("uzpainter.baking.BakingParameters")},
                            reason));
    tools.push_back(GapTool({"bake_apply_preset", "Applies a baking preset to texture sets.",
                             Schema({{"preset", json::Object{{"type", json::Array{"object", "string"}},
                                                             {"description", "The preset, as an object or the path of its file."},
                                                             {"x-uzpainter-root", "resource"}}},
                                     {"texture_sets", ArrayProperty(json::Object{{"type", "string"}}, "The texture sets.")}},
                                    {"preset"}),
                             true, false, true, Operation("uzpainter.baking.BakingParameters")},
                            reason));
}

void MeshFamily(const ToolContext& context, std::vector<ToolDefinition>& tools) {
    tools.push_back(DefineJob(
        {"mesh_reload",
         "Replaces the project's mesh, keeping the texture sets matched by material (12-mesh-import.md §7), in one "
         "transaction; `returned.reload` is the report (a long job).",
         Schema({{"path", PathProperty("The new mesh file.", "mesh")},
                 {"settings", ObjectProperty({{"import_cameras", BoolProperty("Whether the mesh's cameras are imported.")},
                                              {"material_mapping",
                                               json::Object{{"type", "object"},
                                                            {"additionalProperties", json::Object{{"type", "string"}}},
                                                            {"description", "Accepted renames: current material name -> new name."}}}},
                                             {}, "Painter's MeshReloadingSettings members UzPainter reads.")}},
                {"path"}),
         true, false, true, Operation("substance_painter.project.reload_mesh")},
        "revision", [context](const json::Object& arguments) -> python::JobBody {
            const std::string path = Text(*Given(arguments, "path"), "path");
            std::optional<bool> import_cameras;
            std::map<std::string, std::string> mapping;
            if (const json::Value* given = Given(arguments, "settings")) {
                const json::Object& s = ObjectOf(*given, "settings");
                if (const json::Value* v = Given(s, "import_cameras")) import_cameras = Flag(*v, "import_cameras");
                if (const json::Value* v = Given(s, "material_mapping")) {
                    for (const auto& [from, to] : ObjectOf(*v, "material_mapping")) mapping[from] = Text(to, "material_mapping");
                }
            }
            auto reload = std::make_shared<const python::MeshReloadCall>(path, import_cameras, std::move(mapping));
            return [context, reload, path](python::JobContext& job) {
                job.SetProgress(0.0, "reloading the mesh from " + path);
                job.Checkpoint();
                json::Object result = context.submit([&](core::Edit& edit) { reload->Apply(edit); });
                reload->Finish();
                if (const json::Value* committed = Field(result, "committed_revision")) {
                    job.Commit({{"revision", *committed}});
                } else {
                    job.NoOp();
                }
                return result;
            };
        }));

    tools.push_back(Define(
        {"mesh_certificate",
         "The current mesh's certificate (12-mesh-import.md §4): counters, per-set UV metrics and status, with its "
         "file's SHA-256 and the texturing-mesh hashes.",
         Schema({}, {}), false, false},
        [](const json::Object&) {
            const std::shared_ptr<python::OpenProject> open = Open();
            const core::Snapshot snapshot = open->document->snapshot();
            const std::optional<core::MeshReference>& mesh = snapshot.project->mesh;
            if (!mesh) throw CallError{"project_error", "the project has no mesh", {}};
            const json::Value* certificate = Field(mesh->import_report, "certificate");
            const json::Value* hashes = Field(mesh->import_report, "hashes");
            return json::Object{{"revision", snapshot.revision},
                                {"mesh", json::Object{{"sha256", mesh->resource}, {"source", mesh->source}}},
                                {"hashes", hashes ? *hashes : json::Value(nullptr)},
                                {"certificate", certificate ? *certificate : json::Value(nullptr)}};
        }));
}

}  // namespace

std::vector<ToolDefinition> TypedTools(const ToolContext& context) {
    std::vector<ToolDefinition> tools;
    ProjectFamily(context, tools);
    TextureSetFamily(context, tools);
    ResourceFamily(context, tools);
    StackFamily(context, tools);
    RecipeFamily(context, tools);
    BakingFamily(tools);
    MeshFamily(context, tools);
    return tools;
}

}  // namespace uzp::supervisor
