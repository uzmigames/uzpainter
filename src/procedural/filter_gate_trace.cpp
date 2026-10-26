#include "procedural/filter_gate_trace.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <functional>
#include <iomanip>
#include <limits>
#include <map>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string_view>
#include <vector>

#include "procedural/filter_gate_settings.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/enums.h"

namespace uzp::procedural {
namespace {

using core::json::Array;
using core::json::Object;
using core::json::Value;
constexpr std::string_view kSchema = "uzpainter/parity/filter-context-readback/1";
constexpr std::string_view kProject = "substance_painter.project.";
constexpr std::string_view kNode = "substance_painter.layerstack.Node.";
constexpr std::string_view kSource = "substance_painter.source.SourceSubstance.";
constexpr std::string_view kResolve = "substance_painter.layerstack.get_node_by_uid";
constexpr std::string_view kSublayers = "substance_painter.layerstack.GroupLayerNode.sub_layers";
constexpr std::array<std::string_view, 5> kBoundaries{
    "after-create", "after-setup6", "pre16-r1", "after-reopen", "pre16-r2"};
constexpr std::string_view kCode = "F_SETTINGS_CONTEXT";

struct Invalid : std::exception {};
void Require(bool okay) { if (!okay) throw Invalid{}; }
const Object& Obj(const Value& value) { Require(value.IsObject()); return std::get<Object>(value.data); }
const Array& Arr(const Value& value) { Require(value.IsArray()); return std::get<Array>(value.data); }
const std::string& Text(const Value& value) { Require(value.IsString()); return std::get<std::string>(value.data); }
std::int64_t Int(const Value& value) { Require(value.IsInt()); return std::get<std::int64_t>(value.data); }
const Value& At(const Object& object, std::string_view key) {
    const auto it = object.find(key); Require(it != object.end()); return it->second;
}
bool Same(const Value& a, const Value& b) { return core::json::WriteCanonical(a) == core::json::WriteCanonical(b); }
bool Bool(const Value& value, bool expected) { return value.IsBool() && std::get<bool>(value.data) == expected; }
double Number(const Value& value) {
    Require(value.IsNumber());
    const double number = value.IsInt() ? static_cast<double>(Int(value)) : std::get<double>(value.data);
    Require(std::isfinite(number));
    return number;
}
bool PositiveId(const Value& value) {
    return value.IsInt() && Int(value) > 0;
}
void Closed(const Object& object, std::initializer_list<std::string_view> keys) {
    Require(object.size() == keys.size());
    for (const auto key : keys) Require(object.contains(key));
}
std::string Call(std::string_view prefix, std::string_view name) { return std::string(prefix) + std::string(name); }
std::vector<std::string> Calls(std::string_view prefix, std::initializer_list<std::string_view> names) {
    std::vector<std::string> result;
    for (const auto name : names) result.push_back(Call(prefix, name));
    return result;
}
const std::map<std::string, std::vector<std::string>, std::less<>>& Spec() {
    static const std::map<std::string, std::vector<std::string>, std::less<>> spec{
        {"project", {Call(kProject, "get_uuid"), Call(kProject, "last_imported_mesh_path"),
                     Call(kProject, "is_open"), Call(kProject, "needs_saving"), "substance_painter.textureset.all_texture_sets"}},
        {"set", Calls("substance_painter.textureset.TextureSet.", {"name", "get_resolution", "all_stacks"})},
        {"stack", {"substance_painter.textureset.Stack.name", "substance_painter.textureset.Stack.all_channels",
                   "substance_painter.layerstack.get_root_layer_nodes"}},
        {"channel", Calls("substance_painter.textureset.Channel.", {"format", "bit_depth", "is_color", "is_floating", "label"})},
        {"node", Calls(kNode, {"uid", "get_type", "get_name", "is_visible", "get_parent", "is_in_mask_stack"})},
        {"layer", Calls("substance_painter.layerstack.LayerNode.", {"has_mask", "content_effects", "mask_effects", "get_geometry_mask"})},
        {"fill", Calls("substance_painter.layerstack.FillLayerNode.", {"source_mode", "active_channels", "get_projection_mode",
                       "get_projection_parameters", "is_symmetry_enabled", "get_symmetry_parameters"})},
        {"filter", {"substance_painter.layerstack.FilterEffectNode.active_channels"}},
        {"source", Calls(kSource, {"get_parameters", "resource_id", "image_inputs", "image_outputs", "active_output", "resolution"})},
        {"blend", Calls(kNode, {"get_blending_mode", "get_opacity"})},
    };
    return spec;
}
std::string Condition(std::string_view boundary) {
    return boundary == "after-reopen" || boundary == "pre16-r2" ? "after_save_reopen" : "same_session";
}
std::string LeafKey(std::string_view call, const Object& selector, const Object& parameters = {}) {
    return core::json::WriteCanonical(Array{Value(call), selector, parameters});
}
void Raised(const Object& output) {
    if (!output.contains("raised")) return;
    const auto& error = Obj(At(output, "raised"));
    Closed(error, {"type", "message"});
    Text(At(error, "type")); Text(At(error, "message"));
    Require(At(output, "value").IsNull());
}
void ApiOutput(const Object& output) {
    if (output.contains("raised")) Closed(output, {"output_id", "kind", "call", "args", "value", "raised"});
    else Closed(output, {"output_id", "kind", "call", "args", "value"});
    Require(Text(At(output, "kind")) == "api_readback");
    Text(At(output, "output_id")); Text(At(output, "call")); Obj(At(output, "args"));
    Raised(output);
}
std::string Scope(const Object& selector) {
    if (selector.empty()) return "project";
    if (selector.contains("role")) {
        if (selector.contains("source")) Closed(selector, {"role", "source"});
        else Closed(selector, {"role"});
        const auto& role = Text(At(selector, "role"));
        Require(role == "host" || role == "filter");
        if (selector.contains("source")) { Require(Bool(At(selector, "source"), true)); return "source"; }
        return "role";
    }
    std::set<std::string> keys;
    for (const auto& [key, value] : selector) keys.insert(key);
    const std::set<std::set<std::string>> allowed{
        {"set"}, {"set", "stack"}, {"set", "stack", "channel"}, {"set", "stack", "path"},
        {"set", "stack", "path", "parent"}};
    Require(allowed.contains(keys));
    for (const auto name : {"set", "stack"}) if (selector.contains(name)) Require(Int(At(selector, name)) >= 0);
    if (selector.contains("channel")) { Require(!Text(At(selector, "channel")).empty()); return "channel"; }
    if (selector.contains("path")) {
        const auto& path = Arr(At(selector, "path")); Require(!path.empty());
        for (std::size_t i = 0; i < path.size(); ++i) {
            const auto& part = Arr(path[i]); Require(part.size() == 2);
            const auto& kind = Text(part[0]);
            Require(i == 0 ? kind == "Root" : kind == "Content" || kind == "Mask" || kind == "Substack");
            Require(Int(part[1]) >= 0);
        }
        if (selector.contains("parent")) { Require(Bool(At(selector, "parent"), true)); return "parent"; }
        return "node";
    }
    return selector.contains("stack") ? "stack" : "set";
}
void Frame(const Object& frame) {
    Closed(frame, {"schema", "boundary", "condition", "outputs"});
    Require(Text(At(frame, "schema")) == kSchema);
    const auto& boundary = Text(At(frame, "boundary"));
    Require(std::ranges::find(kBoundaries, boundary) != kBoundaries.end());
    Require(Text(At(frame, "condition")) == Condition(boundary));
    const auto& outputs = Arr(At(frame, "outputs")); Require(!outputs.empty());
    std::set<std::string> seen;
    for (std::size_t index = 0; index < outputs.size(); ++index) {
        const auto& output = Obj(outputs[index]); ApiOutput(output);
        const auto& call = Text(At(output, "call"));
        std::ostringstream identity;
        identity << "context/" << boundary << '/' << std::setfill('0') << std::setw(4) << index
                 << '-' << call.substr(call.rfind('.') + 1);
        Require(Text(At(output, "output_id")) == identity.str());
        const auto& args = Obj(At(output, "args")); Closed(args, {"selector", "parameters"});
        const auto& selector = Obj(At(args, "selector"));
        const auto& params = Obj(At(args, "parameters"));
        const std::string scope = Scope(selector);
        std::set<std::string> allowed;
        const auto group = [&](std::string_view name) {
            const auto it = Spec().find(name);
            if (it != Spec().end()) allowed.insert(it->second.begin(), it->second.end());
        };
        group(scope);
        if (scope == "node") {
            for (const auto name : {"layer", "fill", "filter", "blend"}) group(name);
            allowed.insert(std::string(kSublayers)); allowed.insert(std::string(kResolve));
        } else if (scope == "role") allowed = {std::string(kResolve), Call(kNode, "uid")};
        else if (scope == "parent") allowed = {Call(kNode, "uid")};
        else if (scope == "source") allowed.insert(Call(kSource, "get_source"));
        Require(allowed.contains(call));
        if (call == kResolve) { Closed(params, {"uid"}); Require(PositiveId(At(params, "uid"))); }
        else if (call == Spec().at("blend")[0] || call == Spec().at("blend")[1]) {
            Closed(params, {"channel"}); Require(At(params, "channel").IsString() || At(params, "channel").IsNull());
        } else if (call == Call(kSource, "get_source")) {
            Closed(params, {"input_identifier"}); Require(!Text(At(params, "input_identifier")).empty());
        } else Closed(params, {});
        Require(seen.insert(LeafKey(call, selector, params)).second);
    }
}

class Leaves {
public:
    explicit Leaves(const Object& frame) {
        for (const auto& value : Arr(At(frame, "outputs"))) {
            const auto& output = Obj(value); const auto& args = Obj(At(output, "args"));
            rows_.emplace(LeafKey(Text(At(output, "call")), Obj(At(args, "selector")), Obj(At(args, "parameters"))), &output);
        }
    }
    const Object& Row(std::string_view call, const Object& selector, const Object& params = {}) {
        const auto key = LeafKey(call, selector, params); const auto it = rows_.find(key);
        Require(it != rows_.end()); used_.insert(key); return *it->second;
    }
    const Value& Take(std::string_view call, const Object& selector, const Object& params = {}, bool raised = false) {
        const auto& output = Row(call, selector, params);
        Require(raised || !output.contains("raised")); return At(output, "value");
    }
    void Group(std::string_view group, const Object& selector) {
        for (const auto& call : Spec().at(std::string(group))) Take(call, selector);
    }
    void Complete() const { Require(used_.size() == rows_.size()); }
private:
    std::map<std::string, const Object*> rows_;
    std::set<std::string> used_;
};
struct CensusNode { std::int64_t uid; std::string type; std::string name; Array path; };
std::vector<CensusNode> Census(const Object& frame) {
    Frame(frame); Leaves leaves(frame);
    leaves.Group("project", {});
    Require(Bool(leaves.Take(Call(kProject, "is_open"), {}), true));
    Require(!Text(leaves.Take(Call(kProject, "get_uuid"), {})).empty());
    Require(Arr(leaves.Take(Spec().at("project").back(), {})).size() == 1);
    const Object set{{"set", 0}}, stack{{"set", 0}, {"stack", 0}};
    leaves.Group("set", set);
    const auto& resolution = Obj(leaves.Take(Spec().at("set")[1], set));
    Closed(resolution, {"class", "width", "height"});
    Require(Int(At(resolution, "width")) == 128 && Int(At(resolution, "height")) == 128);
    Require(Arr(leaves.Take(Spec().at("set")[2], set)).size() == 1);
    leaves.Group("stack", stack);
    const auto& channels = Obj(leaves.Take(Spec().at("stack")[1], stack)); Require(!channels.empty());
    const std::map<std::string, int> depths{{"sRGB8", 8}, {"L8", 8}, {"RGB8", 8}, {"L16", 16}, {"RGB16", 16},
                                           {"L16F", 16}, {"RGB16F", 16}, {"L32F", 32}, {"RGB32F", 32}};
    for (const auto& [channel, ignored] : channels) {
        Require(core::FromString<core::ChannelType>(channel).has_value());
        Object selector = stack; selector["channel"] = channel; leaves.Group("channel", selector);
        const auto& spec = Spec().at("channel");
        const auto& format = Text(leaves.Take(spec[0], selector)); Require(depths.contains(format));
        Require(Int(leaves.Take(spec[1], selector)) == depths.at(format));
        Require(leaves.Take(spec[2], selector).IsBool());
        Require(Bool(leaves.Take(spec[3], selector), format.ends_with('F')));
        Text(leaves.Take(spec[4], selector));
    }
    const auto& roots = Arr(leaves.Take(Spec().at("stack")[2], stack));
    std::vector<CensusNode> census;
    std::set<std::int64_t> uids;
    std::function<void(Array, std::optional<std::int64_t>, const Value&)> visit;
    visit = [&](Array path, std::optional<std::int64_t> parentUid, const Value& descriptor) {
        Object selector = stack; selector["path"] = path;
        const auto& uidValue = leaves.Take(Call(kNode, "uid"), selector); Require(PositiveId(uidValue));
        const auto uid = Int(uidValue); Require(uids.insert(uid).second);
        const auto& resolved = leaves.Take(kResolve, selector, Object{{"uid", uid}});
        leaves.Group("node", selector);
        const auto& type = Text(leaves.Take(Call(kNode, "get_type"), selector));
        const auto& name = Text(leaves.Take(Call(kNode, "get_name"), selector));
        Require(Same(resolved, Object{{"node_type", type}, {"name", name}}) && Same(resolved, descriptor));
        Require(Bool(leaves.Take(Call(kNode, "is_visible"), selector), true));
        Require(Bool(leaves.Take(Call(kNode, "is_in_mask_stack"), selector), false));
        const auto& parent = leaves.Take(Call(kNode, "get_parent"), selector);
        if (!parentUid) Require(parent.IsNull());
        else {
            Require(parent.IsObject()); Object parentSelector = selector; parentSelector["parent"] = true;
            Require(Int(leaves.Take(Call(kNode, "uid"), parentSelector)) == *parentUid);
        }
        census.push_back({uid, type, name, path});
        Require(type == "PaintLayer" || type == "FillLayer" || type == "FilterEffect");
        Array children;
        if (type == "PaintLayer" || type == "FillLayer") {
            leaves.Group("layer", selector); const auto& spec = Spec().at("layer");
            Require(Bool(leaves.Take(spec[0], selector), false) && Same(leaves.Take(spec[2], selector), Array{}));
            const auto& geometry = Obj(leaves.Take(spec[3], selector));
            Closed(geometry, {"class", "inclusion_list", "meshes"});
            Require(Text(At(geometry, "class")) == "GeometryMaskMeshParams" && Bool(At(geometry, "inclusion_list"), false)
                    && Same(At(geometry, "meshes"), Array{}));
            children = Arr(leaves.Take(spec[1], selector));
            if (type == "PaintLayer") Require(children.empty());
        }
        std::vector<std::string> active;
        if (type == "FillLayer") {
            const auto& spec = Spec().at("fill");
            for (std::size_t i = 0; i < spec.size(); ++i) leaves.Take(spec[i], selector, {}, i >= 4);
            for (std::size_t i = 4; i < spec.size(); ++i) {
                const auto& output = leaves.Row(spec[i], selector);
                Require(!output.contains("raised") || Text(At(Obj(At(output, "raised")), "type")) == "ValueError");
            }
            const auto& symmetry = leaves.Row(spec[4], selector);
            Require(symmetry.contains("raised") || Bool(At(symmetry, "value"), false));
            Require(Text(leaves.Take(spec[0], selector)) == "Split" && Same(leaves.Take(spec[1], selector), Array{"User0"}));
            Require(Text(leaves.Take(spec[2], selector)) == "UV");
            const auto& projection = Obj(leaves.Take(spec[3], selector));
            Closed(projection, {"class", "filtering_mode", "uv_wrapping_mode", "uv_transformation"});
            const auto& transform = Obj(At(projection, "uv_transformation")); Closed(transform, {"scale_mode", "scale", "rotation", "offset"});
            Require(Text(At(projection, "class")) == "UVProjectionParams" && Text(At(projection, "filtering_mode")) == "BilinearHQ"
                    && Text(At(projection, "uv_wrapping_mode")) == "Repeat" && Text(At(transform, "scale_mode")) == "Factors");
            for (const auto& [field, wanted] : std::array<std::pair<std::string_view, double>, 2>{{{"scale", 1.0}, {"offset", 0.0}}}) {
                const auto& pair = Arr(At(transform, field)); Require(pair.size() == 2);
                Require(Number(pair[0]) == wanted && Number(pair[1]) == wanted);
            }
            Require(Number(At(transform, "rotation")) == 0.0);
            Object user = stack; user["channel"] = "User0";
            Require(Text(leaves.Take(Spec().at("channel")[0], user)) == "L32F");
            active.push_back("User0");
        }
        if (type == "FilterEffect") {
            const auto& values = Arr(leaves.Take(Spec().at("filter")[0], selector)); Require(!values.empty());
            std::set<std::string> unique;
            for (const auto& value : values) {
                const auto& channel = Text(value); Require(channels.contains(channel) && unique.insert(channel).second); active.push_back(channel);
            }
            Require(std::ranges::is_sorted(active));
        }
        for (const auto& [channel, ignored] : channels) {
            const Object params{{"channel", channel}};
            for (const auto& call : Spec().at("blend")) leaves.Take(call, selector, params, true);
            if (std::ranges::find(active, channel) == active.end()) continue;
            const auto& mode = Text(leaves.Take(Spec().at("blend")[0], selector, params));
            Require(core::FromString<core::BlendingMode>(mode).has_value());
            const double opacity = Number(leaves.Take(Spec().at("blend")[1], selector, params)); Require(opacity >= 0.0 && opacity <= 1.0);
            if (type == "FillLayer") Require(mode == "Normal" && opacity == 1.0);
        }
        for (std::size_t i = 0; i < children.size(); ++i) {
            Array childPath = path; childPath.push_back(Array{"Content", Value(static_cast<std::int64_t>(i))});
            visit(std::move(childPath), uid, children[i]);
        }
    };
    for (std::size_t i = 0; i < roots.size(); ++i) visit(Array{Array{"Root", Value(static_cast<std::int64_t>(i))}}, std::nullopt, roots[i]);
    if (Text(At(frame, "boundary")) != "after-create") {
        for (const auto role : {"host", "filter"}) {
            const Object roleSelector{{"role", role}};
            const auto uid = Int(leaves.Take(Call(kNode, "uid"), roleSelector)); Require(uids.contains(uid));
            const auto node = std::ranges::find_if(census, [uid](const CensusNode& n) { return n.uid == uid; });
            Require(node != census.end());
            Require(Same(leaves.Take(kResolve, roleSelector, Object{{"uid", uid}}), Object{{"node_type", node->type}, {"name", node->name}}));
            const Object selector{{"role", role}, {"source", true}};
            for (const auto& call : Spec().at("source")) {
                const bool optional = std::string_view(role) == "filter" && (call.ends_with(".active_output") || call.ends_with(".resolution"));
                leaves.Take(call, selector, {}, optional);
            }
            const auto& params = Obj(leaves.Take(Call(kSource, "get_parameters"), selector));
            for (const auto& [name, value] : params) Require(value.IsNumber() || value.IsString());
            const auto& identity = Obj(leaves.Take(Call(kSource, "resource_id"), selector)); Closed(identity, {"resource_id", "url"});
            const auto& wrapper = Obj(At(identity, "resource_id")); Closed(wrapper, {"resource"});
            const auto& resource = Obj(At(wrapper, "resource")); Closed(resource, {"context", "name", "version"});
            Require(!Text(At(identity, "url")).empty());
            for (const auto& [key, value] : resource) Require(!Text(value).empty());
            const auto strings = [&](std::string_view getter) -> const Array& {
                const auto& values = Arr(leaves.Take(Call(kSource, getter), selector)); std::set<std::string> unique;
                for (const auto& value : values) { const auto& text = Text(value); Require(!text.empty() && unique.insert(text).second); }
                return values;
            };
            strings("image_outputs");
            const auto& resolutionRow = leaves.Row(Call(kSource, "resolution"), selector);
            if (!resolutionRow.contains("raised")) {
                const auto& sourceResolution = Obj(At(resolutionRow, "value")); Closed(sourceResolution, {"mode", "value", "value_kind", "log2_offset"});
                Text(At(sourceResolution, "mode")); Int(At(sourceResolution, "log2_offset"));
                const auto& kind = Text(At(sourceResolution, "value_kind")); Require(kind == "tuple" || kind == "list" || kind == "other");
            }
            const auto& inputs = strings("image_inputs");
            for (const auto& input : inputs) leaves.Take(Call(kSource, "get_source"), selector, Object{{"input_identifier", input}});
            Require(inputs.empty());
        }
    }
    leaves.Complete(); return census;
}

Value Event(const Object& step, std::string_view condition) {
    return Object{{"kind", "step"}, {"condition", condition}, {"step", At(step, "step")},
                  {"call", At(step, "call")}, {"args", At(step, "args")}};
}
void Readback(const Object& output, std::string_view call, const Object& args) {
    ApiOutput(output); Require(Text(At(output, "call")) == call && Same(At(output, "args"), args) && !output.contains("raised"));
}
std::vector<std::string> PhaseGetters(std::string_view phase) {
    if (phase == "close") return {"is_open", "is_busy"};
    return {"is_open", "is_in_edition_state", "is_busy", "file_path"};
}
struct Rebuilt { Array contexts; std::int64_t initial_paint_uid; Array rounds; };
Rebuilt Rebuild(const Object& record, const Object& recipe) {
    Require(Text(At(record, "golden_id")) == "tier0/api-probes/filter-context-settings-a");
    Require(core::Sha256Hex(core::json::WriteCanonical(recipe)) == "b7758f5b14fd4c5c06780f087dc23dee4269529c37cfc512334ebd389ed6a083");
    std::map<std::int64_t, Object> steps;
    for (const auto& value : Arr(At(recipe, "steps"))) { const auto& step = Obj(value); Require(steps.emplace(Int(At(step, "step")), step).second); }
    Require(Text(At(Obj(At(record, "key")), "instruction_sequence_sha256")) == core::Sha256Hex(core::json::WriteCanonical(recipe)));
    const auto& recordings = Arr(At(record, "recordings")); Require(recordings.size() == 2);
    static const std::regex contextPattern(R"(context/([a-z0-9-]+)/[0-9]{4}-[A-Za-z_][A-Za-z0-9_]*)");
    static const std::regex lifecyclePattern(R"(lifecycle/(create|save|close|open)/([a-z_]+))");
    static const std::regex stepPattern(R"(s([0-9]+)/([A-Za-z_][A-Za-z0-9_]*))");
    Array operations, contexts;
    std::map<std::string, Object> phases;
    const auto stepEvent = [&](const Object& step, std::string_view condition, const Object& outcome) {
        Raised(outcome);
        if (outcome.contains("raised")) Require(Int(At(step, "step")) >= 7);
        operations.push_back(Event(step, condition));
    };
    for (std::size_t round = 0; round < recordings.size(); ++round) {
        const auto& recording = Obj(recordings[round]);
        const std::string condition = round == 0 ? "same_session" : "after_save_reopen";
        Require(Text(At(recording, "condition")) == condition && Text(At(recording, "recording_id")) == (round == 0 ? "r1" : "r2"));
        const auto& outputs = Arr(At(recording, "outputs")); Require(!outputs.empty());
        const auto& first = Obj(outputs[0]); Closed(first, {"output_id", "kind", "subject", "values"});
        Require(Text(At(first, "output_id")) == "template/texture-sets" && Text(At(first, "kind")) == "template_capture");
        Require(!Text(At(first, "subject")).empty()); Obj(At(first, "values"));
        std::optional<std::size_t> frame;
        std::string phase;
        std::vector<std::string> phaseFields, identities;
        bool probed = false;
        std::set<std::string> ids{Text(At(first, "output_id"))};
        const auto close = [&] { if (!phase.empty()) Require(phaseFields == PhaseGetters(phase)); };
        for (std::size_t i = 1; i < outputs.size(); ++i) {
            const auto& output = Obj(outputs[i]); ApiOutput(output);
            const auto& oid = Text(At(output, "output_id")); Require(ids.insert(oid).second);
            std::smatch lifecycle, context, step;
            const bool lifecycleMatch = std::regex_match(oid, lifecycle, lifecyclePattern);
            if (!phase.empty() && !(lifecycleMatch && lifecycle[1].str() == phase)) { close(); phase.clear(); phaseFields.clear(); }
            if (std::regex_match(oid, context, contextPattern)) {
                const std::string boundary = context[1].str();
                if (!frame || Text(At(Obj(contexts[*frame]), "boundary")) != boundary) {
                    contexts.push_back(Object{{"schema", kSchema}, {"boundary", boundary}, {"condition", condition}, {"outputs", Array{}}});
                    frame = contexts.size() - 1; operations.push_back(Object{{"kind", "context"}, {"boundary", boundary}});
                }
                auto& target = std::get<Array>(std::get<Object>(contexts[*frame].data).at("outputs").data); target.push_back(output);
                continue;
            }
            frame.reset();
            if (oid.starts_with("identity/s")) {
                const std::string id = oid.substr(std::string("identity/s").size());
                Require(id == "3" || id == "6");
                Readback(output, kResolve, Object{{"node_step", id == "3" ? 3 : 6}});
                Require(!probed && std::ranges::find(identities, id) == identities.end());
                Require(Same(At(output, "value"), Object{{"present", true}, {"uid_same_as_recorded", true}, {"uid_resolves_to_node", true}}));
                identities.push_back(id); continue;
            }
            if (lifecycleMatch) {
                const std::string name = lifecycle[1].str(), getter = lifecycle[2].str();
                Readback(output, Call(kProject, getter), {});
                if (phase.empty()) {
                    Require(!phases.contains(name)); phase = name; phases[name] = {};
                    if (name == "create") { Require(round == 0); operations.push_back(Event(steps.at(1), condition)); }
                    else operations.push_back(Object{{"kind", name}});
                }
                Require(!phases[name].contains(getter)); phases[name][getter] = At(output, "value"); phaseFields.push_back(getter); continue;
            }
            if (oid == "identity/reopen") {
                Readback(output, kResolve, {});
                Require(Same(At(output, "value"), Object{{"found_by", Object{{"3", "location"}, {"6", "location"}}}}));
                operations.push_back(Object{{"kind", "rebind"}}); continue;
            }
            Require(std::regex_match(oid, step, stepPattern));
            const auto number = std::stoll(step[1].str()); Require(number != 1 && steps.contains(number));
            const auto& authored = steps.at(number); const auto& call = Text(At(authored, "call"));
            Require(step[2].str() == call.substr(call.rfind('.') + 1) && Text(At(output, "call")) == call);
            Object args = Obj(At(authored, "args")); args.erase("probe"); args.erase("wait"); Require(Same(At(output, "args"), args));
            probed = probed || number >= 7; stepEvent(authored, condition, output);
        }
        close(); Require(identities == std::vector<std::string>{"3", "6"});
    }
    Require(phases.size() == 4);
    const auto& saved = At(phases.at("save"), "file_path"); Require(!Text(saved).empty());
    for (const auto name : {"create", "save", "close", "open"}) {
        const auto& phase = phases.at(name);
        if (std::string_view(name) == "close") Require(Bool(At(phase, "is_open"), false));
        else {
            Require(Bool(At(phase, "is_open"), true) && Bool(At(phase, "is_in_edition_state"), true) && Bool(At(phase, "is_busy"), false));
            if (std::string_view(name) == "open") Require(Same(At(phase, "file_path"), saved));
        }
    }
    Array expected;
    for (int step = 1; step <= 6; ++step) {
        expected.push_back(Event(steps.at(step), "same_session"));
        if (step == 1 || step == 6) expected.push_back(Object{{"kind", "context"}, {"boundary", step == 1 ? "after-create" : "after-setup6"}});
    }
    for (int round = 0; round < 2; ++round) {
        if (round == 1) {
            for (const auto name : {"save", "close", "open", "rebind"}) expected.push_back(Object{{"kind", name}});
            expected.push_back(Object{{"kind", "context"}, {"boundary", "after-reopen"}});
        }
        for (int step = 7; step <= 24; ++step) {
            if (step == 16) expected.push_back(Object{{"kind", "context"}, {"boundary", round == 0 ? "pre16-r1" : "pre16-r2"}});
            expected.push_back(Event(steps.at(step), round == 0 ? "same_session" : "after_save_reopen"));
        }
    }
    Require(Same(operations, expected) && contexts.size() == kBoundaries.size());
    std::vector<std::vector<CensusNode>> censuses;
    for (std::size_t i = 0; i < contexts.size(); ++i) {
        const auto& frame = Obj(contexts[i]); Require(Text(At(frame, "boundary")) == kBoundaries[i]); censuses.push_back(Census(frame));
    }
    Require(censuses[0].size() == 1 && censuses[0][0].type == "PaintLayer");
    const auto paintUid = censuses[0][0].uid; const auto paintName = censuses[0][0].name;
    Leaves setup(Obj(contexts[1])), initial(Obj(contexts[0]));
    const auto hostUid = Int(setup.Take(Call(kNode, "uid"), Object{{"role", "host"}}));
    const auto filterUid = Int(setup.Take(Call(kNode, "uid"), Object{{"role", "filter"}}));
    Require(std::set<std::int64_t>{paintUid, hostUid, filterUid}.size() == 3);
    const Value uuid = initial.Take(Call(kProject, "get_uuid"), {});
    for (std::size_t i = 1; i < contexts.size(); ++i) {
        Leaves leaves(Obj(contexts[i]));
        Require(Same(leaves.Take(Call(kProject, "get_uuid"), {}), uuid));
        Require(Int(leaves.Take(Call(kNode, "uid"), Object{{"role", "host"}})) == hostUid);
        Require(Int(leaves.Take(Call(kNode, "uid"), Object{{"role", "filter"}})) == filterUid);
        const auto& nodes = censuses[i]; Require(nodes.size() == 3);
        Require(nodes[0].type == "FillLayer" && nodes[0].uid == hostUid && Same(nodes[0].path, Array{Array{"Root", 0}}));
        Require(nodes[1].type == "FilterEffect" && nodes[1].uid == filterUid && Same(nodes[1].path, Array{Array{"Root", 0}, Array{"Content", 0}}));
        Require(nodes[2].type == "PaintLayer" && nodes[2].uid == paintUid && Same(nodes[2].path, Array{Array{"Root", 1}}) && nodes[2].name == paintName);
    }
    Array hashes;
    for (int round = 0; round < 2; ++round) {
        const std::string condition = round == 0 ? "same_session" : "after_save_reopen";
        Array probes, frames, host, filter;
        for (const auto& value : Arr(At(Obj(recordings[round]), "outputs"))) {
            const auto& output = Obj(value); std::smatch match; const auto& oid = Text(At(output, "output_id"));
            if (std::regex_match(oid, match, stepPattern)) { const auto step = std::stoll(match[1].str()); if (step >= 7 && step <= 24) probes.push_back(value); }
        }
        for (const auto& value : contexts) {
            const auto& frame = Obj(value); if (Text(At(frame, "condition")) != condition) continue; frames.push_back(value);
            if (Text(At(frame, "boundary")) != (round == 0 ? "pre16-r1" : "pre16-r2")) continue;
            for (const auto& outputValue : Arr(At(frame, "outputs"))) {
                const auto& selector = At(Obj(At(Obj(outputValue), "args")), "selector");
                if (Same(selector, Object{{"role", "host"}}) || Same(selector, Object{{"role", "host"}, {"source", true}})) host.push_back(outputValue);
                if (Same(selector, Object{{"role", "filter"}}) || Same(selector, Object{{"role", "filter"}, {"source", true}})) filter.push_back(outputValue);
            }
        }
        const auto hash = [](const Array& value) { return core::Sha256Hex(core::json::WriteCanonical(value)); };
        hashes.push_back(Object{{"condition", condition}, {"probe_sequence_sha256", hash(probes)}, {"context_readback_sha256", hash(frames)},
                                {"host_readback_sha256", hash(host)}, {"filter_readback_sha256", hash(filter)}});
    }
    return {std::move(contexts), paintUid, std::move(hashes)};
}
ImportRefusal Refusal(std::string_view code = kCode) { return {std::string(kFilterCaptureInvalid), std::string(code)}; }

}  // namespace

std::optional<ImportRefusal> ValidateFilterContextFrame(const core::json::Object& frame) {
    try { Frame(frame); return std::nullopt; }
    catch (const std::exception&) { return Refusal(); }
}

std::expected<ValidatedFilterTrace, ImportRefusal> ValidateFilterTrace(
    const AdmittedFilterCapture& capture, const CheckedSettingsPanels& panels) {
    try {
        const Object identity = capture.Identity();
        if (!Same(identity, panels.AdmissionIdentity()) || Text(At(identity, "record_sha256")) != panels.OriginalRecordSha256()) {
            return std::expected<ValidatedFilterTrace, ImportRefusal>(std::unexpect, Refusal("F_SETTINGS_CAPTURE_BINDING"));
        }
        Rebuilt rebuilt = Rebuild(panels.StrippedRecord(), Obj(At(capture.Manifest(), "instruction_sequence")));
        ValidatedFilterTrace result;
        result.admission_identity_ = identity;
        result.original_record_sha256_ = panels.OriginalRecordSha256();
        result.contexts_ = std::move(rebuilt.contexts);
        result.initial_paint_uid_ = static_cast<core::Id>(rebuilt.initial_paint_uid);
        result.rounds_ = std::move(rebuilt.rounds);
        return result;
    } catch (const std::exception&) { return std::expected<ValidatedFilterTrace, ImportRefusal>(std::unexpect, Refusal()); }
}

}  // namespace uzp::procedural
