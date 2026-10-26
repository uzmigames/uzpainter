#include "procedural/filter_gate_destination.h"

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <initializer_list>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <utility>
#include <vector>

#include "procedural/seam.h"
#include "procedural/snapshot_source.h"
#include "store/filter_observations.h"
#include "store/snapshots.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/resource_url.h"

namespace uzp::procedural {
namespace {

using core::json::Array;
using core::json::Object;
using core::json::Value;

// Zig's libc++ also declares the pre-C++17 `std::unexpected()`, so the bare name is ambiguous
// (asset_library.cpp, seam.h `Refused`): the error type is named through `std::expected`.
using Unexpected = std::expected<void, ImportRefusal>::unexpected_type;

/// A refusal with one fixed reason and detail code; nothing observed is carried.
struct DestinationRefused {
    std::string_view reason;
    std::string_view code;
};

void Require(bool condition, std::string_view reason, std::string_view code) {
    if (!condition) throw DestinationRefused{reason, code};
}

void Identity(bool condition) { Require(condition, kFilterCaptureInvalid, filter_gate::kSliceIdentity); }
void Context(bool condition) { Require(condition, kTargetContextUnrepresentable, filter_gate::kFContext); }
void Shape(bool condition) { Require(condition, kTargetContextUnrepresentable, filter_gate::kStartingShape); }

/// Typed equality: canonical JSON keeps integers, doubles, signed zero and strings apart.
bool SameTyped(const Value& a, const Value& b) { return core::json::WriteCanonical(a) == core::json::WriteCanonical(b); }

const Object* ObjectAt(const Object& object, std::string_view key) {
    const auto found = object.find(key);
    return found == object.end() || !found->second.IsObject() ? nullptr : &std::get<Object>(found->second.data);
}

const Array* ArrayAt(const Object& object, std::string_view key) {
    const auto found = object.find(key);
    return found == object.end() || !found->second.IsArray() ? nullptr : &std::get<Array>(found->second.data);
}

const std::string* StringAt(const Object& object, std::string_view key) {
    const auto found = object.find(key);
    return found == object.end() || !found->second.IsString() ? nullptr : &std::get<std::string>(found->second.data);
}

constexpr std::string_view kPrefix = "substance_painter.";
constexpr std::string_view kNode = "substance_painter.layerstack.Node.";
constexpr std::string_view kSource = "substance_painter.source.SourceSubstance.";

std::string Call(std::string_view prefix, std::string_view name) { return std::string(prefix) + std::string(name); }

// ── The F context frames ──────────────────────────────────────────────────────────────────────

/// One context frame's leaves by `[call, selector, parameters]`, as the context contract keys them.
class Frame {
public:
    explicit Frame(const Object& frame) {
        const Array* outputs = ArrayAt(frame, "outputs");
        Context(outputs != nullptr);
        for (const Value& item : *outputs) {
            Context(item.IsObject());
            const Object& output = std::get<Object>(item.data);
            const std::string* call = StringAt(output, "call");
            const Object* args = ObjectAt(output, "args");
            Context(call != nullptr && args != nullptr && args->contains("selector") && args->contains("parameters"));
            const std::string key =
                core::json::WriteCanonical(Array{*call, args->at("selector"), args->at("parameters")});
            Context(leaves_.emplace(key, &output).second);
        }
    }

    /// The leaf's whole output object, or nothing when it is absent.
    [[nodiscard]] const Object* Output(std::string_view call, const Object& selector, const Object& parameters = {}) const {
        const auto found =
            leaves_.find(core::json::WriteCanonical(Array{std::string(call), selector, parameters}));
        return found == leaves_.end() ? nullptr : found->second;
    }

    /// The unraised value of a leaf, or nothing when it is absent or raised.
    [[nodiscard]] const Value* Find(std::string_view call, const Object& selector, const Object& parameters = {}) const {
        const auto found =
            leaves_.find(core::json::WriteCanonical(Array{std::string(call), selector, parameters}));
        if (found == leaves_.end() || found->second->contains("raised") || !found->second->contains("value")) return nullptr;
        return &found->second->at("value");
    }

private:
    std::map<std::string, const Object*> leaves_;
};

/// The two pre16 frames; a consumed leaf must be present, unraised and typed-equal in both.
class Pre16 {
public:
    Pre16(const Frame& r1, const Frame& r2) : r1_(r1), r2_(r2) {}

    [[nodiscard]] const Value& Leaf(std::string_view call, const Object& selector, const Object& parameters = {}) const {
        const Value* first = r1_.Find(call, selector, parameters);
        const Value* second = r2_.Find(call, selector, parameters);
        Context(first != nullptr && second != nullptr && SameTyped(*first, *second));
        return *first;
    }

    /// A leaf's outcome in both frames, which must agree: its value when unraised, or nothing when
    /// it raised (then `raised` is the raise type, the same in both frames).
    [[nodiscard]] const Value* Outcome(std::string_view call, const Object& selector, const Object& parameters,
                                       std::string& raised) const {
        const Object* first = r1_.Output(call, selector, parameters);
        const Object* second = r2_.Output(call, selector, parameters);
        Context(first != nullptr && second != nullptr && first->contains("raised") == second->contains("raised"));
        if (first->contains("raised")) {
            const Object* a = ObjectAt(*first, "raised");
            const Object* b = ObjectAt(*second, "raised");
            Context(a != nullptr && b != nullptr && StringAt(*a, "type") != nullptr && StringAt(*b, "type") != nullptr &&
                    *StringAt(*a, "type") == *StringAt(*b, "type"));
            raised = *StringAt(*a, "type");
            return nullptr;
        }
        Context(first->contains("value") && second->contains("value") && SameTyped(first->at("value"), second->at("value")));
        raised.clear();
        return &first->at("value");
    }

    [[nodiscard]] const std::string& Text(std::string_view call, const Object& selector, const Object& parameters = {}) const {
        const Value& value = Leaf(call, selector, parameters);
        Context(value.IsString());
        return std::get<std::string>(value.data);
    }

private:
    const Frame& r1_;
    const Frame& r2_;
};

Object SetSelector() { return Object{{"set", std::int64_t{0}}}; }
Object StackSelector() { return Object{{"set", std::int64_t{0}}, {"stack", std::int64_t{0}}}; }
Object ChannelSelector(const std::string& channel) {
    return Object{{"set", std::int64_t{0}}, {"stack", std::int64_t{0}}, {"channel", channel}};
}
Object PathSelector(std::initializer_list<std::pair<const char*, std::int64_t>> path) {
    Array parts;
    for (const auto& [stack, index] : path) parts.push_back(Array{stack, index});
    return Object{{"set", std::int64_t{0}}, {"stack", std::int64_t{0}}, {"path", parts}};
}
Object RoleSelector(const char* role) { return Object{{"role", role}}; }
Object SourceSelector(const char* role) { return Object{{"role", role}, {"source", true}}; }

/// The F blending of a Filter: required unraised on its `active` channels; on any other stack
/// channel, kept when observed (unraised in both frames), absent when both frames raised.
core::ChannelBlending FilterBlending(const Pre16& frames, const Object& selector, const std::vector<std::string>& channels,
                                     const std::set<std::string>& active) {
    core::ChannelBlending blending;
    for (const std::string& name : channels) {
        const Object parameters{{"channel", name}};
        std::string modeRaised;
        std::string opacityRaised;
        const Value* mode = frames.Outcome(Call(kNode, "get_blending_mode"), selector, parameters, modeRaised);
        const Value* opacity = frames.Outcome(Call(kNode, "get_opacity"), selector, parameters, opacityRaised);
        Context((mode == nullptr) == (opacity == nullptr) && (mode != nullptr || !active.contains(name)));
        if (mode == nullptr) continue;
        const auto parsedMode = mode->IsString() ? core::FromString<core::BlendingMode>(std::get<std::string>(mode->data))
                                                 : std::nullopt;
        const auto parsedChannel = core::FromString<core::ChannelType>(name);
        Context(parsedMode && parsedChannel && opacity->IsNumber());
        const double value = opacity->IsInt() ? static_cast<double>(std::get<std::int64_t>(opacity->data))
                                              : std::get<double>(opacity->data);
        Context(std::isfinite(value) && value >= 0 && value <= 1);
        blending[*parsedChannel] = core::Blending{*parsedMode, value, {}};
    }
    return blending;
}

/// The F per-channel blending of the node at `selector`, for `channels`.
core::ChannelBlending Blending(const Pre16& frames, const Object& selector, const std::vector<std::string>& channels) {
    core::ChannelBlending blending;
    for (const std::string& name : channels) {
        const Object parameters{{"channel", name}};
        const std::string& mode = frames.Text(Call(kNode, "get_blending_mode"), selector, parameters);
        const Value& opacity = frames.Leaf(Call(kNode, "get_opacity"), selector, parameters);
        const auto parsedMode = core::FromString<core::BlendingMode>(mode);
        const auto parsedChannel = core::FromString<core::ChannelType>(name);
        Context(parsedMode && parsedChannel && opacity.IsNumber());
        const double value = opacity.IsInt() ? static_cast<double>(std::get<std::int64_t>(opacity.data))
                                             : std::get<double>(opacity.data);
        Context(std::isfinite(value) && value >= 0 && value <= 1);
        blending[*parsedChannel] = core::Blending{*parsedMode, value, {}};
    }
    return blending;
}

// ── J1-J4 ──────────────────────────────────────────────────────────────────────────────────────

void J(bool condition, std::string_view code) { Require(condition, kHostSourceStateMismatch, code); }

/// The host source leaves of a frame by getter, each present once and unraised.
std::map<std::string, Value> HostLeaves(const Object& frame) {
    std::map<std::string, Value> leaves;
    const Object selector{{"selector", SourceSelector("host")}, {"parameters", Object{}}};
    const Array* outputs = ArrayAt(frame, "outputs");
    Context(outputs != nullptr);
    for (const Value& item : *outputs) {
        Context(item.IsObject() && StringAt(std::get<Object>(item.data), "call") != nullptr);
        const Object& output = std::get<Object>(item.data);
        const std::string& call = *StringAt(output, "call");
        if (!call.starts_with(kSource) || !SameTyped(output.at("args"), selector)) continue;
        const std::string getter = call.substr(kSource.size());
        Context(!leaves.contains(getter) && !output.contains("raised"));
        leaves.emplace(getter, output.at("value"));
    }
    return leaves;
}

/// The step outputs of each recording of the stripped record, by output id.
std::vector<std::map<std::string, const Object*>> StepOutputs(const Object& record) {
    std::vector<std::map<std::string, const Object*>> rounds;
    const Array* recordings = ArrayAt(record, "recordings");
    Context(recordings != nullptr && recordings->size() == 2);
    for (const Value& recording : *recordings) {
        Context(recording.IsObject());
        const Array* items = ArrayAt(std::get<Object>(recording.data), "outputs");
        Context(items != nullptr);
        std::map<std::string, const Object*> outputs;
        for (const Value& item : *items) {
            Context(item.IsObject() && StringAt(std::get<Object>(item.data), "output_id") != nullptr);
            const Object& output = std::get<Object>(item.data);
            Context(outputs.emplace(*StringAt(output, "output_id"), &output).second);
        }
        rounds.push_back(std::move(outputs));
    }
    return rounds;
}

void BindSource(const Object& manifest, const std::map<std::string, const Object*>& contexts,
                const std::vector<std::map<std::string, const Object*>>& steps, const ValidatedHostArtifacts& host) {
    // The H source: two equal readback sources with a complete identity.
    J(host.Readback().IsObject(), filter_gate::kJ1SourceIdentity);
    const Array* sources = ArrayAt(std::get<Object>(host.Readback().data), "sources");
    J(sources != nullptr && sources->size() == 2 && SameTyped((*sources)[0], (*sources)[1]) && (*sources)[0].IsObject(),
      filter_gate::kJ1SourceIdentity);
    const Object& source = std::get<Object>((*sources)[0].data);
    const Object* identity = ObjectAt(source, "resource_id");
    J(identity != nullptr && identity->size() == 4, filter_gate::kJ1SourceIdentity);
    for (const char* key : {"url", "context", "name", "version"}) J(StringAt(*identity, key) != nullptr, filter_gate::kJ1SourceIdentity);

    std::map<std::string, std::map<std::string, Value>> frames;
    for (const char* boundary : {"after-setup6", "pre16-r1", "after-reopen", "pre16-r2"}) {
        Context(contexts.contains(boundary));
        frames[boundary] = HostLeaves(*contexts.at(boundary));
        Context(frames[boundary].contains("get_parameters") && frames[boundary].contains("resource_id"));
    }

    // J1: recipe step 5, the H receipt and every F frame name one complete source identity.
    std::map<std::int64_t, const Object*> recipe;
    for (const Value& step : *ArrayAt(*ObjectAt(manifest, "instruction_sequence"), "steps")) {
        const Object& object = std::get<Object>(step.data);
        recipe[std::get<std::int64_t>(object.at("step").data)] = &object;
    }
    const std::string* url = StringAt(*ObjectAt(*recipe.at(5), "args"), "resource_url");
    J(url != nullptr && *url == host.Resource() && *url == *StringAt(*identity, "url"), filter_gate::kJ1SourceIdentity);
    const Value expected = Object{
        {"resource_id", Object{{"resource", Object{{"context", identity->at("context")},
                                                   {"name", identity->at("name")},
                                                   {"version", identity->at("version")}}}}},
        {"url", identity->at("url")}};
    for (const auto& [boundary, leaves] : frames) J(SameTyped(leaves.at("resource_id"), expected), filter_gate::kJ1SourceIdentity);

    // J2: the pre16 effective parameters of both rounds, typed.
    for (const char* boundary : {"pre16-r1", "pre16-r2"}) {
        J(SameTyped(frames.at(boundary).at("get_parameters"), source.at("parameters")), filter_gate::kJ2Pre16Parameters);
    }

    // J3: step 12 writes int 0, step 14 bool False, steps 13, 15 and pre16 read one typed map.
    const auto step = [&](std::int64_t n) -> const Object& { return *recipe.at(n); };
    const auto arg = [&](std::int64_t n) -> const Value& { return ObjectAt(step(n), "args")->at("toggle"); };
    J(SameTyped(step(12).at("call"), Value(Call(kSource, "set_parameters"))) &&
          SameTyped(step(14).at("call"), Value(Call(kSource, "set_parameters"))) && SameTyped(arg(12), Value(std::int64_t{0})) &&
          SameTyped(arg(14), Value(false)) && SameTyped(step(13).at("call"), Value(Call(kSource, "get_parameters"))) &&
          SameTyped(step(15).at("call"), Value(Call(kSource, "get_parameters"))),
      filter_gate::kJ3Pre16State);
    for (std::size_t round = 0; round < 2; ++round) {
        const auto& outputs = steps[round];
        const auto written = outputs.find("s12/set_parameters");
        J(written != outputs.end() && !written->second->contains("raised"), filter_gate::kJ3IntWrite);
        const auto toggled = outputs.find("s14/set_parameters");
        J(toggled != outputs.end(), filter_gate::kJ3BoolWrite);
        if (toggled->second->contains("raised")) {
            const Value& raised = toggled->second->at("raised");
            J(raised.IsObject() && ObjectAt(*toggled->second, "raised")->contains("type") &&
                  SameTyped(ObjectAt(*toggled->second, "raised")->at("type"), Value("TypeError")),
              filter_gate::kJ3BoolWrite);
        }
        const Value& pre16 = frames.at(round == 0 ? "pre16-r1" : "pre16-r2").at("get_parameters");
        for (const char* id : {"s13/get_parameters", "s15/get_parameters"}) {
            const auto read = outputs.find(id);
            J(read != outputs.end() && !read->second->contains("raised") && read->second->contains("value") &&
                  SameTyped(read->second->at("value"), pre16),
              filter_gate::kJ3Pre16State);
        }
    }

    // J4: outputs, inputs (empty), active output and resolution of both pre16 states.
    for (const char* boundary : {"pre16-r1", "pre16-r2"}) {
        const auto& leaves = frames.at(boundary);
        J(leaves.contains("image_outputs") && leaves.contains("image_inputs") && leaves.contains("active_output") &&
              leaves.contains("resolution"),
          filter_gate::kJ4Outputs);
        J(SameTyped(leaves.at("image_outputs"), source.at("outputs")) && SameTyped(leaves.at("image_inputs"), source.at("inputs")) &&
              SameTyped(leaves.at("image_inputs"), Array{}) && SameTyped(leaves.at("active_output"), source.at("active_output")),
          filter_gate::kJ4Outputs);
        const Value& resolution = leaves.at("resolution");
        J(resolution.IsObject() && std::get<Object>(resolution.data).size() == 4, filter_gate::kJ4Outputs);
        const Object& f = std::get<Object>(resolution.data);
        J(f.contains("mode") && f.contains("value") && f.contains("log2_offset") && f.contains("value_kind") &&
              (SameTyped(f.at("value_kind"), Value("tuple")) || SameTyped(f.at("value_kind"), Value("list"))) &&
              SameTyped(Object{{"mode", f.at("mode")}, {"value", f.at("value")}, {"log2_offset", f.at("log2_offset")}},
                        source.at("resolution")),
          filter_gate::kJ4Outputs);
    }
}

/// What the binding read: the trace's frames by boundary and the stripped record's step outputs.
struct Joined {
    std::map<std::string, const Object*> contexts;
    std::vector<std::map<std::string, const Object*>> steps;
};

/// Steps 1 and 2 of `ExpectedDestination`, shared with `ValidateFilterHostBinding`: the four slices
/// name one admission and one record, then J1-J4. Throws `DestinationRefused`.
Joined Bind(const AdmittedFilterCapture& capture, const CheckedSettingsPanels& panels, const ValidatedFilterTrace& trace,
            const ValidatedFilterSettings& settings, const ValidatedHostArtifacts& host) {
    const Value admission = capture.Identity();
    Identity(SameTyped(panels.AdmissionIdentity(), admission) && SameTyped(trace.AdmissionIdentity(), admission) &&
             SameTyped(settings.AdmissionIdentity(), admission));
    const std::string& record = capture.Refs().at(0).sha256;
    Identity(panels.OriginalRecordSha256() == record && trace.OriginalRecordSha256() == record &&
             settings.OriginalRecordSha256() == record);
    Joined joined;
    for (const Value& item : trace.Contexts()) {
        Context(item.IsObject());
        const Object& frame = std::get<Object>(item.data);
        const std::string* boundary = StringAt(frame, "boundary");
        Context(boundary != nullptr && joined.contexts.emplace(*boundary, &frame).second);
    }
    joined.steps = StepOutputs(panels.StrippedRecord());
    BindSource(capture.Manifest(), joined.contexts, joined.steps, host);
    return joined;
}

// ── The starting shape and the known constructor defaults ───────────────────────────────────────

/// Exactly `ApplyDefaultSources` (stack_sync.cpp): a uniform `value` of `float32` precision on all
/// three components, `Working`, with no extra. Bits are compared, so +0 and -0 differ.
bool KnownDefault(const core::Source& source, float value) {
    const auto* uniform = std::get_if<core::UniformColorSource>(&source.value);
    if (uniform == nullptr || uniform->color_space != "Working" || !uniform->extra.empty()) return false;
    const auto bits = std::bit_cast<std::uint64_t>(static_cast<double>(value));
    return std::all_of(uniform->rgb.begin(), uniform->rgb.end(),
                       [&](double c) { return std::bit_cast<std::uint64_t>(c) == bits; });
}

bool NeutralGeometry(const core::GeometryMask& mask) {
    return mask.type == core::GeometryMaskType::Mesh && !mask.inclusion_list && mask.items.empty() && mask.extra.empty();
}

/// The host's expected User0 reference: the bind of H's snapshot (`assets bind-snapshot`).
core::ProceduralRef BoundReference(const ProceduralRequest& request, const store::SnapshotEntry& entry) {
    core::ProceduralRef ref;
    ref.asset = core::FormatAssetUrl(request.asset);
    ref.params = *entry.source_metadata->typed_effective_parameters;
    ref.output_mapping = {{"User0", request.outputId}};
    return ref;
}

/// `ref` is the bind of H's snapshot; only its resolution override is the binder's choice.
bool IsBound(const core::ProceduralRef& ref, const core::ProceduralRef& expected) {
    return ref.asset == expected.asset && SameTyped(ref.params, expected.params) && !ref.preset && ref.image_inputs.empty() &&
           ref.output_mapping == expected.output_mapping && !ref.mask_output && ref.extra.empty();
}

}  // namespace

Object ValidatedFilterDestination::Identity() const {
    return Object{{"base_projection_sha256", base_projection_sha256_},
                  {"prospective_projection_sha256", prospective_projection_sha256_},
                  {"host_identity_sha256", host_identity_sha256_},
                  {"filter_evidence_sha256", filter_evidence_sha256_},
                  {"descriptor_sha256", store::ObservationKey(descriptor_)},
                  {"roles", roles_},
                  {"removed_defaults", removed_defaults_}};
}

std::optional<ImportRefusal> ValidateFilterHostBinding(const AdmittedFilterCapture& capture, const CheckedSettingsPanels& panels,
                                                       const ValidatedFilterTrace& trace,
                                                       const ValidatedFilterSettings& settings,
                                                       const ValidatedHostArtifacts& host) {
    try {
        Bind(capture, panels, trace, settings, host);
        return std::nullopt;
    } catch (const DestinationRefused& refused) {
        return ImportRefusal{std::string(refused.reason), std::string(refused.code)};
    } catch (const std::exception&) {
        return ImportRefusal{std::string(kTargetContextUnrepresentable), std::string(filter_gate::kFContext)};
    }
}

std::expected<ValidatedFilterDestination, ImportRefusal> ExpectedDestination(
    const AdmittedFilterCapture& capture, const CheckedSettingsPanels& panels, const ValidatedFilterTrace& trace,
    const ValidatedFilterSettings& settings, const ValidatedHostArtifacts& host, const core::Project& base) {
    try {
        ValidatedFilterDestination result;

        // 1-2. The slices' identity and J1-J4: the same code as `ValidateFilterHostBinding`.
        const Joined joined = Bind(capture, panels, trace, settings, host);
        const auto& contexts = joined.contexts;
        const auto& steps = joined.steps;

        // 3. The starting shape of `base` and H's snapshot entry.
        const std::string signature = SignatureHash(host.Request());
        std::optional<store::SnapshotEntry> entry;
        for (store::SnapshotEntry& candidate : store::ProjectSnapshots(base)) {
            if (candidate.key == signature) entry = std::move(candidate);
        }
        Require(entry && entry->error.empty() && entry->source_metadata && entry->source_metadata->typed_effective_parameters &&
                    entry->source_metadata->observed_resource_id && SameTyped(entry->signature, host.Signature()) &&
                    SameTyped(store::SourceMetadataJson(entry->signature, *entry->source_metadata),
                              store::SourceMetadataJson(entry->signature, host.Metadata())),
                kTargetContextUnrepresentable, filter_gate::kHostSnapshot);

        const auto& s = base.settings;
        Shape(s.normal_map_format == core::NormalMapFormat::OpenGL && s.tangent_space == core::TangentSpace::PerVertex &&
              s.workflow == core::ProjectWorkflow::Default && s.mesh_unit_scale == 1.0 && s.extra.empty() &&
              (s.color_management.mode.empty() || s.color_management.mode == "legacy") &&
              s.color_management.config_hash.empty() && s.color_management.working_space.empty() &&
              s.color_management.io_rules.empty() && s.color_management.extra.empty());
        Shape(settings.TangentSpace() == core::ToString(s.tangent_space) && settings.Workflow() == core::ToString(s.workflow) &&
              settings.EffectiveCmPerUnit() == 1);
        Shape(base.mesh && base.mesh->resource == store::kFrozenHostPlaneMesh && base.mesh->extra.empty());
        for (const auto& [key, value] : base.extra) Shape(key == store::kSnapshotsKey);
        Shape(base.texture_sets.size() == 1 && base.texture_sets[0].stacks.size() == 1);
        const core::TextureSet& baseSet = base.texture_sets[0];
        const core::Stack& baseStack = baseSet.stacks[0];
        Shape(baseSet.resolution.width == 128 && baseSet.resolution.height == 128 && baseSet.uv_tiles.size() == 1 &&
              baseSet.uv_tiles[0].udim == 1001 && baseSet.uv_tiles[0].extra.empty() && baseSet.mesh_maps.empty() &&
              baseSet.extra.empty() && baseStack.extra.empty());
        for (const auto& [type, channel] : baseStack.channels) Shape(channel.extra.empty());

        // Root layers: an order-preserving subsequence of [host Fill, empty Paint].
        const core::Layer* baseHost = nullptr;
        const core::Layer* basePaint = nullptr;
        Shape(baseStack.root_layers.size() <= 2);
        for (const core::Layer& layer : baseStack.root_layers) {
            if (layer.kind == core::LayerKind::fill) {
                Shape(baseHost == nullptr && basePaint == nullptr);
                baseHost = &layer;
            } else {
                Shape(layer.kind == core::LayerKind::paint && basePaint == nullptr);
                basePaint = &layer;
            }
        }
        const core::ProceduralRef expectedRef = BoundReference(host.Request(), *entry);
        std::vector<std::string> removed;
        Object removedSources;
        if (baseHost != nullptr) {
            const core::Layer& layer = *baseHost;
            Shape(layer.fill && !layer.paint && layer.content_effects.empty() && !layer.mask && NeutralGeometry(layer.geometry_mask) &&
                  layer.children.empty() && layer.instance_source == core::kNoId && !layer.collapsed && !layer.preset_ref &&
                  layer.extra.empty());
            const core::FillContent& fill = *layer.fill;
            Require(fill.source_mode == core::SourceMode::Split && fill.active_channels == std::set{core::ChannelType::User0} &&
                        !fill.mono_source && !fill.material_source && fill.extra.empty() && !fill.symmetry.enabled &&
                        fill.symmetry.params.empty() && fill.symmetry.extra.empty() && fill.sources.contains(core::ChannelType::User0),
                    kTargetContextUnrepresentable, filter_gate::kHostSources);
            // MAPPED members are replaced from F, so nothing unknown may sit in them.
            const core::Projection& projection = fill.projection;
            Shape(projection.extra.empty() && projection.params.empty() && projection.uv.extra.empty() &&
                  projection.uv.uv_transformation.extra.empty());
            for (const auto& [channel, blend] : layer.blending) Shape(blend.extra.empty());
            for (const auto& [channel, source] : fill.sources) {
                if (channel == core::ChannelType::User0) {
                    const auto* procedural = std::get_if<core::ProceduralSource>(&source.value);
                    Require(procedural != nullptr && IsBound(procedural->ref, expectedRef), kTargetContextUnrepresentable,
                            filter_gate::kHostSources);
                } else if (channel == core::ChannelType::BaseColor && KnownDefault(source, 0.8f)) {
                    removed.emplace_back("BaseColor");
                } else if (channel == core::ChannelType::Height && KnownDefault(source, 0.0f)) {
                    removed.emplace_back("Height");
                } else {
                    Require(false, kTargetContextUnrepresentable, filter_gate::kHostSources);
                }
            }
            for (const std::string& name : removed) {
                const auto& uniform = std::get<core::UniformColorSource>(
                    fill.sources.at(*core::FromString<core::ChannelType>(name)).value);
                removedSources[name] = Object{{"rgb", Array{uniform.rgb[0], uniform.rgb[1], uniform.rgb[2]}},
                                              {"color_space", uniform.color_space}};
            }
        }
        if (basePaint != nullptr) {
            const core::Layer& layer = *basePaint;
            Shape(core::IsEmptyPaintLayer(layer) && !layer.fill && !layer.mask && NeutralGeometry(layer.geometry_mask) &&
                  layer.children.empty() && layer.instance_source == core::kNoId && !layer.collapsed && !layer.preset_ref &&
                  layer.extra.empty() && layer.paint->extra.empty());
            for (const auto& [channel, blend] : layer.blending) Shape(blend.extra.empty());
        }

        // 4. The F states the mapping consumes, equal in both pre16 frames.
        Context(contexts.contains("pre16-r1") && contexts.contains("pre16-r2"));
        const Frame r1(*contexts.at("pre16-r1"));
        const Frame r2(*contexts.at("pre16-r2"));
        const Pre16 f(r1, r2);
        const std::string& setName = f.Text(Call(kPrefix, "textureset.TextureSet.name"), SetSelector());
        const std::string& stackName = f.Text(Call(kPrefix, "textureset.Stack.name"), StackSelector());
        const Value& channelMap = f.Leaf(Call(kPrefix, "textureset.Stack.all_channels"), StackSelector());
        Context(channelMap.IsObject() && !std::get<Object>(channelMap.data).empty());
        std::vector<std::string> channelNames;
        std::map<core::ChannelType, core::Channel> channels;
        for (const auto& [name, unused] : std::get<Object>(channelMap.data)) {
            const auto type = core::FromString<core::ChannelType>(name);
            const auto format = core::FromString<core::ChannelFormat>(
                f.Text(Call(kPrefix, "textureset.Channel.format"), ChannelSelector(name)));
            Context(type && format);
            channels[*type] = core::Channel{*format, f.Text(Call(kPrefix, "textureset.Channel.label"), ChannelSelector(name)), {}};
            channelNames.push_back(name);
        }
        Context(channels.contains(core::ChannelType::User0) && channels.at(core::ChannelType::User0).format == core::ChannelFormat::L32F);
        // A base channel F lacks is dropped only when no base layer references it: the removed
        // known defaults are the only sources allowed on it, and no blending or paint plane names it.
        for (const auto& [type, channel] : baseStack.channels) {
            if (channels.contains(type)) continue;
            const auto references = [type = type](const core::Layer& layer) {
                return layer.blending.contains(type) || (layer.paint && layer.paint->planes.contains(type));
            };
            Shape((baseHost == nullptr || !references(*baseHost)) && (basePaint == nullptr || !references(*basePaint)));
            if (baseHost != nullptr && baseHost->fill && baseHost->fill->sources.contains(type)) {
                const std::string name(core::ToString(type));
                Shape(std::find(removed.begin(), removed.end(), name) != removed.end());
            }
        }

        const Object hostPath = PathSelector({{"Root", 0}});
        const Object filterPath = PathSelector({{"Root", 0}, {"Content", 0}});
        const Object paintPath = PathSelector({{"Root", 1}});
        const Value& roots = f.Leaf(Call(kPrefix, "layerstack.get_root_layer_nodes"), StackSelector());
        Context(roots.IsArray() && std::get<Array>(roots.data).size() == 2);
        const Value& hostUid = f.Leaf(Call(kNode, "uid"), RoleSelector("host"));
        const Value& filterUid = f.Leaf(Call(kNode, "uid"), RoleSelector("filter"));
        Context(SameTyped(f.Leaf(Call(kNode, "uid"), hostPath), hostUid) && SameTyped(f.Leaf(Call(kNode, "uid"), filterPath), filterUid) &&
                SameTyped(f.Leaf(Call(kNode, "uid"), paintPath), Value(static_cast<std::int64_t>(trace.InitialPaintUid()))));
        Context(SameTyped(f.Leaf(Call(kNode, "get_type"), hostPath), Value("FillLayer")) &&
                SameTyped(f.Leaf(Call(kNode, "get_type"), filterPath), Value("FilterEffect")) &&
                SameTyped(f.Leaf(Call(kNode, "get_type"), paintPath), Value("PaintLayer")));
        for (const Object* path : {&hostPath, &filterPath, &paintPath}) {
            Context(SameTyped(f.Leaf(Call(kNode, "is_visible"), *path), Value(true)));
        }
        Context(SameTyped(f.Leaf(Call(kPrefix, "layerstack.FillLayerNode.source_mode"), hostPath), Value("Split")) &&
                SameTyped(f.Leaf(Call(kPrefix, "layerstack.FillLayerNode.active_channels"), hostPath), Array{"User0"}) &&
                SameTyped(f.Leaf(Call(kPrefix, "layerstack.FillLayerNode.get_projection_mode"), hostPath), Value("UV")));
        const Value& projection = f.Leaf(Call(kPrefix, "layerstack.FillLayerNode.get_projection_parameters"), hostPath);
        Context(projection.IsObject());
        const Object& uv = std::get<Object>(projection.data);
        const Object* transform = ObjectAt(uv, "uv_transformation");
        Context(uv.size() == 4 && SameTyped(uv.at("class"), Value("UVProjectionParams")) &&
                SameTyped(uv.at("filtering_mode"), Value("BilinearHQ")) && SameTyped(uv.at("uv_wrapping_mode"), Value("Repeat")) &&
                transform != nullptr && transform->size() == 4 && SameTyped(transform->at("scale_mode"), Value("Factors")));
        const auto number = [](const Value& v) {
            return v.IsInt() ? static_cast<double>(std::get<std::int64_t>(v.data)) : v.IsDouble() ? std::get<double>(v.data) : NAN;
        };
        const Array* scale = ArrayAt(*transform, "scale");
        const Array* offset = ArrayAt(*transform, "offset");
        Context(scale != nullptr && scale->size() == 2 && number((*scale)[0]) == 1 && number((*scale)[1]) == 1 &&
                offset != nullptr && offset->size() == 2 && number((*offset)[0]) == 0 && number((*offset)[1]) == 0 &&
                number(transform->at("rotation")) == 0);
        {
            std::string enabledRaised;
            std::string parametersRaised;
            const Value* enabled =
                f.Outcome(Call(kPrefix, "layerstack.FillLayerNode.is_symmetry_enabled"), hostPath, Object{}, enabledRaised);
            const Value* symmetry =
                f.Outcome(Call(kPrefix, "layerstack.FillLayerNode.get_symmetry_parameters"), hostPath, Object{}, parametersRaised);
            // Disabled (False) or unavailable for this projection (ValueError); unraised symmetry
            // parameters have no representation here and refuse rather than being dropped.
            Context((enabled == nullptr ? enabledRaised == "ValueError" : SameTyped(*enabled, Value(false))) &&
                    symmetry == nullptr && parametersRaised == "ValueError");
        }
        for (const Object* path : {&hostPath, &paintPath}) {
            Context(SameTyped(f.Leaf(Call(kPrefix, "layerstack.LayerNode.has_mask"), *path), Value(false)) &&
                    SameTyped(f.Leaf(Call(kPrefix, "layerstack.LayerNode.mask_effects"), *path), Array{}));
            const Value& geometry = f.Leaf(Call(kPrefix, "layerstack.LayerNode.get_geometry_mask"), *path);
            Context(SameTyped(geometry, Object{{"class", "GeometryMaskMeshParams"}, {"inclusion_list", false}, {"meshes", Array{}}}));
        }
        const Value& filterActive = f.Leaf(Call(kPrefix, "layerstack.FilterEffectNode.active_channels"), filterPath);
        Context(filterActive.IsArray() && !std::get<Array>(filterActive.data).empty());
        std::vector<std::string> activeNames;
        std::set<core::ChannelType> active;
        for (const Value& item : std::get<Array>(filterActive.data)) {
            Context(item.IsString());
            const auto type = core::FromString<core::ChannelType>(std::get<std::string>(item.data));
            Context(type && channels.contains(*type) && active.insert(*type).second);
            activeNames.push_back(std::get<std::string>(item.data));
        }

        // The Filter's steps 16-18 in both rounds, and its pre16 source leaves.
        const auto observe = [&](const char* id) -> const Value& {
            const auto first = steps[0].find(id);
            const auto second = steps[1].find(id);
            Require(first != steps[0].end() && second != steps[1].end() && !first->second->contains("raised") &&
                        !second->second->contains("raised") && first->second->contains("value") &&
                        second->second->contains("value") &&
                        SameTyped(first->second->at("value"), second->second->at("value")),
                    kTargetContextUnrepresentable, filter_gate::kObservations);
            return first->second->at("value");
        };
        const Value& parameters = observe("s16/get_parameters");
        const Value& identity = observe("s17/resource_id");
        const Value& outputs = observe("s18/image_outputs");
        const auto observation = [](bool condition) {
            Require(condition, kTargetContextUnrepresentable, filter_gate::kObservations);
        };
        observation(SameTyped(parameters, f.Leaf(Call(kSource, "get_parameters"), SourceSelector("filter"))) &&
                    SameTyped(identity, f.Leaf(Call(kSource, "resource_id"), SourceSelector("filter"))) &&
                    SameTyped(outputs, f.Leaf(Call(kSource, "image_outputs"), SourceSelector("filter"))) &&
                    SameTyped(f.Leaf(Call(kSource, "image_inputs"), SourceSelector("filter")), Array{}));
        observation(parameters.IsObject() && identity.IsObject() && outputs.IsArray());
        for (const auto& [name, value] : std::get<Object>(parameters.data)) {
            observation(store::ParamByValue(value).has_value());
        }
        const Object& wrapped = std::get<Object>(identity.data);
        const Object* inner = ObjectAt(wrapped, "resource_id");
        const Object* resource = inner == nullptr ? nullptr : ObjectAt(*inner, "resource");
        observation(wrapped.size() == 2 && StringAt(wrapped, "url") != nullptr && inner != nullptr && inner->size() == 1 &&
                    resource != nullptr && resource->size() == 3);
        for (const char* key : {"context", "name", "version"}) observation(StringAt(*resource, key) != nullptr);
        const Object resourceId{{"url", wrapped.at("url")},
                                {"context", resource->at("context")},
                                {"name", resource->at("name")},
                                {"version", resource->at("version")}};
        std::set<std::string> distinct;
        for (const Value& item : std::get<Array>(outputs.data)) {
            observation(item.IsString() && !std::get<std::string>(item.data).empty() &&
                        distinct.insert(std::get<std::string>(item.data)).second);
        }
        result.descriptor_ = Object{{"schema", std::string(store::kObservationDescriptorSchema)},
                                    {"role", "filter"},
                                    {"resource_id", resourceId},
                                    {"parameters", parameters}};
        result.observations_ = Object{{"parameters", parameters}, {"resource_id", resourceId}, {"image_outputs", outputs}};

        // The capture/2 `filter` section from the admitted evidence.
        const Object& manifest = capture.Manifest();
        const Object* create6 = nullptr;
        for (const Value& item : *ArrayAt(*ObjectAt(manifest, "instruction_sequence"), "steps")) {
            const Object& step = std::get<Object>(item.data);
            if (SameTyped(step.at("step"), Value(std::int64_t{6}))) create6 = ObjectAt(step, "args");
        }
        Context(create6 != nullptr && StringAt(*create6, "search") != nullptr);
        Array receipts;
        const Array* recordings = ArrayAt(capture.Record(), "recordings");
        Context(recordings != nullptr && recordings->size() == 2);
        for (const Value& recording : *recordings) {
            receipts.push_back(Object{{"condition", std::get<Object>(recording.data).at("condition")},
                                      {"sha256", store::ObservationKey(recording)}});
        }
        const auto ref = [&](const char* kind, const AdmittedRef& admitted) {
            return Object{{"kind", kind}, {"sha256", admitted.sha256}, {"size_bytes", admitted.size_bytes}};
        };
        const Object& painter = *ObjectAt(*ObjectAt(manifest, "software"), "painter");
        const Object admissionIdentity = capture.Identity();
        result.filter_capture_ = Object{
            {"provenance",
             Object{{"recorder", capture.Environment().at("recorder_version")},
                    {"envelope_id", admissionIdentity.at("envelope_id")},
                    {"painter_build_id", painter.at("build_id")},
                    {"recipe_sha256", core::Sha256Hex(core::json::WriteCanonical(manifest.at("instruction_sequence")))},
                    {"resource_query", create6->at("search")},
                    {"authored_inputs", Array{Object{{"input_id", "plane"}, {"sha256", std::string(store::kFrozenHostPlaneMesh)}}}},
                    {"receipts", receipts}}},
            {"manifest", Object{{"kind", "filter_manifest"},
                                {"sha256", capture.ManifestRef().at("sha256")},
                                {"size_bytes", capture.ManifestRef().at("size_bytes")}}},
            {"record", ref("filter_record", capture.Refs().at(0))},
            {"environment", ref("filter_environment", capture.Refs().at(1))},
            {"rounds", trace.Rounds()}};

        // 5. The prospective project: the six mappings, the known defaults removed, then the ids.
        core::Project prospective = base;
        core::TextureSet& set = prospective.texture_sets[0];
        core::Stack& stack = set.stacks[0];
        set.name = setName;
        stack.name = stackName;
        stack.channels = channels;

        Object roles;
        Array allocated;
        core::Layer hostLayer;
        if (baseHost != nullptr) {
            hostLayer = *baseHost;
        } else {
            hostLayer.uid = prospective.AllocateId();
            hostLayer.kind = core::LayerKind::fill;
            allocated.push_back("host");
        }
        core::Layer paintLayer;
        if (basePaint != nullptr) {
            paintLayer = *basePaint;
        } else {
            paintLayer.uid = prospective.AllocateId();
            paintLayer.kind = core::LayerKind::paint;
            paintLayer.paint = core::PaintContent{};
            allocated.push_back("initial_paint");
        }
        hostLayer.name = f.Text(Call(kNode, "get_name"), hostPath);
        hostLayer.visible = true;
        hostLayer.blending = Blending(f, hostPath, channelNames);
        hostLayer.geometry_mask = core::GeometryMask{};
        core::ProceduralRef hostRef = expectedRef;
        if (baseHost != nullptr) {
            hostRef = std::get<core::ProceduralSource>(baseHost->fill->sources.at(core::ChannelType::User0).value).ref;
        }
        core::FillContent fill;
        fill.source_mode = core::SourceMode::Split;
        fill.sources[core::ChannelType::User0] = core::Source{core::ProceduralSource{hostRef}};
        fill.active_channels = {core::ChannelType::User0};
        fill.projection = core::Projection{};
        fill.projection.mode = core::ProjectionMode::UV;
        fill.projection.uv.filtering_mode = core::FilteringMode::BilinearHQ;
        fill.projection.uv.uv_wrapping_mode = core::UVWrapMode::Repeat;
        fill.projection.uv.uv_transformation = core::UVTransformation{};
        fill.symmetry = core::Symmetry{};
        hostLayer.fill = std::move(fill);
        paintLayer.name = f.Text(Call(kNode, "get_name"), paintPath);
        paintLayer.visible = true;
        paintLayer.blending = Blending(f, paintPath, channelNames);

        core::Effect filter;
        filter.uid = prospective.AllocateId();
        filter.kind = core::EffectKind::filter;
        filter.name = f.Text(Call(kNode, "get_name"), filterPath);
        filter.visible = true;
        filter.active_channels = active;
        filter.blending = FilterBlending(f, filterPath, channelNames, std::set<std::string>(activeNames.begin(), activeNames.end()));
        filter.procedural.emplace();
        filter.procedural->asset = store::ObservationPin(store::ObservationKey(result.descriptor_));
        filter.procedural->params = std::get<Object>(parameters.data);
        hostLayer.content_effects = {filter};
        allocated.push_back("filter");
        stack.root_layers = {hostLayer, paintLayer};

        const auto role = [](core::Id native, const Value& fUid) {
            return Object{{"native", static_cast<std::int64_t>(native)}, {"f_uid", fUid}};
        };
        roles = Object{{"texture_set", role(set.id, Value())},
                       {"stack", role(stack.id, Value())},
                       {"host", role(hostLayer.uid, hostUid)},
                       {"initial_paint", role(paintLayer.uid, Value(static_cast<std::int64_t>(trace.InitialPaintUid())))},
                       {"filter", role(filter.uid, filterUid)},
                       {"allocated", allocated}};

        // The domain and the host's own request.
        store::FrozenHostNodes nodes;
        const std::string domain = store::FrozenHostDomainProblem(prospective, nodes);
        Require(domain.empty(), kTargetContextUnrepresentable, filter_gate::kDomain);
        const auto request = SnapshotFillRequest(prospective, *nodes.set, core::ChannelType::User0, core::ChannelFormat::L32F,
                                                 *nodes.host->fill, *nodes.host_ref, nodes.host->uid, false);
        Require(request.has_value() && SignatureHash(*request) == signature, kTargetContextUnrepresentable, filter_gate::kDomain);

        const auto projectionHash = [](const core::Project& project) {
            Value projection = core::ProjectToJson(project);
            std::get<Object>(projection.data).erase(std::string(store::kFilterObservationsKey));
            return store::ObservationKey(projection);
        };
        result.base_ = base;
        result.prospective_ = std::move(prospective);
        result.filter_ = filter;
        result.roles_ = std::move(roles);
        result.removed_defaults_ = Object{{"channels", Array(removed.begin(), removed.end())},
                                          {"sha256", store::ObservationKey(removedSources)}};
        result.base_projection_sha256_ = projectionHash(result.base_);
        result.prospective_projection_sha256_ = projectionHash(result.prospective_);
        result.host_identity_sha256_ = store::ObservationKey(host.Identity());
        result.filter_evidence_sha256_ =
            store::ObservationKey(Object{{"filter_capture", result.filter_capture_}, {"admission_identity", admissionIdentity}});
        return result;
    } catch (const DestinationRefused& refused) {
        return Unexpected(ImportRefusal{std::string(refused.reason), std::string(refused.code)});
    } catch (const std::exception&) {
        return Unexpected(ImportRefusal{std::string(kTargetContextUnrepresentable), std::string(filter_gate::kFContext)});
    }
}

}  // namespace uzp::procedural
