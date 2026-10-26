// Slice C4 of the native F gate (`docs/filter-observations-v2.md` sections 7 and 11): the pure
// expected destination on authored evidence. The F record and PNG are the authored Python fixture
// the wrapper writes into the work folder (`destination-record.json`, `destination-panel.png`); this
// test makes the authored world's source leaves bind an authored H (the recipe's step-5 resource and
// the world's parameters) and fills the probe answers the authored Painter leaves empty, rebinding
// the panels' context brackets. Every token comes through the real C1-C3 slices and the real native
// H validation; nothing reads a real store, capture or private value.

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <tuple>
#include <iostream>
#include <iterator>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

#include "export/exr_writer.h"
#include "filter_gate_test_support.h"
#include "procedural/filter_gate_destination.h"
#include "procedural/filter_gate_request.h"
#include "procedural/filter_observation_source.h"
#include "procedural/filter_gate_settings.h"
#include "procedural/filter_gate_trace.h"
#include "procedural/filter_observation_import_v2.h"
#include "procedural/seam.h"
#include "procedural/snapshot_backend.h"
#include "procedural/snapshot_recording.h"
#include "procedural/snapshot_source.h"
#include "store/commit.h"
#include "store/container.h"
#include "store/filter_observations.h"
#include "store/project_store.h"
#include "store/snapshots.h"
#include "uzp_core/document/document.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/types/resource_url.h"

static_assert(!std::is_default_constructible_v<uzp::procedural::ValidatedFilterDestination>);

namespace {

using namespace uzp;
using namespace uzp::filter_gate_test;
namespace gate = uzp::procedural::filter_gate;

void Expect(bool okay, const std::string& message) { Require(okay, message); }

std::string Read(const fs::path& path) {
    std::ifstream file(path, std::ios::binary);
    Expect(static_cast<bool>(file), "authored destination fixture present");
    return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}

constexpr const char* kSource = "substance_painter.source.SourceSubstance.";

/// The recipe's step-5 resource of the fixed request, and the identity H observes for it.
std::string StepFiveUrl(const json::Object& manifest) {
    for (const json::Value& item :
         std::get<json::Array>(std::get<json::Object>(manifest.at("instruction_sequence").data).at("steps").data)) {
        const auto& step = std::get<json::Object>(item.data);
        if (json::WriteCanonical(step.at("step")) == "5") {
            return std::get<std::string>(std::get<json::Object>(step.at("args").data).at("resource_url").data);
        }
    }
    throw std::runtime_error("the fixed request has no step 5");
}

json::Object HostIdentity(const std::string& url) {
    return json::Object{{"url", url}, {"context", "starter_assets"}, {"name", "grunge_brushed"}, {"version", "authored"}};
}

/// The F serializer's form of an identity (`describe(ResourceID)`).
json::Object Wrapped(const json::Object& identity) {
    return json::Object{{"resource_id", json::Object{{"resource", json::Object{{"context", identity.at("context")},
                                                                               {"name", identity.at("name")},
                                                                               {"version", identity.at("version")}}}}},
                        {"url", identity.at("url")}};
}

bool Selector(const json::Object& output, const char* role, bool source) {
    const auto args = output.find("args");
    if (args == output.end() || !args->second.IsObject()) return false;
    const auto& object = std::get<json::Object>(args->second.data);
    json::Object expected{{"role", role}};
    if (source) expected["source"] = true;
    return object.contains("selector") && json::WriteCanonical(object.at("selector")) == json::WriteCanonical(expected);
}

bool Calls(const json::Object& output, const std::string& getter) {
    const auto call = output.find("call");
    return call != output.end() && call->second.IsString() && std::get<std::string>(call->second.data) == kSource + getter;
}

json::Array& Outputs(json::Object& record, std::size_t round) {
    return std::get<json::Array>(Obj(Arr(record, "recordings")[round]).at("outputs").data);
}

/// The first pre16 leaf of `getter` for `role`'s source in recording `round`.
json::Value PreLeaf(json::Object& record, std::size_t round, const char* role, const std::string& getter) {
    for (json::Value& item : Outputs(record, round)) {
        const auto& output = std::get<json::Object>(item.data);
        const auto& id = std::get<std::string>(output.at("output_id").data);
        if (id.starts_with("context/pre16-") && Selector(output, role, true) && Calls(output, getter)) return output.at("value");
    }
    throw std::runtime_error("the authored record has no pre16 leaf " + getter);
}

/// Recomputes every panel's context bracket from its frame, as the authored Python fixture does.
void Rebind(json::Object& record) {
    for (json::Value& recording : Arr(record, "recordings")) {
        json::Array& outputs = std::get<json::Array>(Obj(recording).at("outputs").data);
        for (json::Value& item : outputs) {
            json::Object& output = Obj(item);
            if (json::WriteCanonical(output.at("kind")) != "\"settings_panel_readback\"") continue;
            json::Object& values = Obj(output, "values");
            const std::string prefix = "context/" + std::get<std::string>(values.at("boundary").data) + "/";
            json::Array frame;
            for (const json::Value& other : outputs) {
                const auto& id = std::get<std::string>(std::get<json::Object>(other.data).at("output_id").data);
                if (id.starts_with(prefix)) frame.push_back(other);
            }
            json::Object& binding = Obj(values, "binding");
            const std::string digest = core::Sha256Hex(json::WriteCanonical(frame));
            binding["context_before_sha256"] = digest;
            binding["context_after_sha256"] = digest;
            binding["context_after_outputs"] = frame;
        }
    }
}

/// The host source parameters of the bound record and of the authored H: an integer and a
/// non-integral double, which every codec keeps type for type (`ReceiptSourceMetadata`).
json::Value HostParameters() { return json::Object{{"amount", 0.5}, {"integer", std::int64_t{1}}}; }

/// The authored record made to bind the authored H: the host source identity is the step-5
/// resource, the host source parameters (every frame, and steps 13/15) are `HostParameters()`,
/// steps 16-18 answer the Filter's pre16 leaves.
json::Object Bound(json::Object record, const std::string& url) {
    const json::Value wrapped = Wrapped(HostIdentity(url));
    const json::Value parameters = HostParameters();
    for (std::size_t round = 0; round < 2; ++round) {
        const json::Value filterParameters = PreLeaf(record, round, "filter", "get_parameters");
        const json::Value filterIdentity = PreLeaf(record, round, "filter", "resource_id");
        const json::Value filterOutputs = PreLeaf(record, round, "filter", "image_outputs");
        for (json::Value& item : Outputs(record, round)) {
            json::Object& output = Obj(item);
            const auto& id = std::get<std::string>(output.at("output_id").data);
            if (id.starts_with("context/") && Selector(output, "host", true) && Calls(output, "resource_id")) {
                output["value"] = wrapped;
            }
            if (id.starts_with("context/") && Selector(output, "host", true) && Calls(output, "get_parameters")) {
                output["value"] = parameters;
            }
            const auto answer = [&](const json::Value& value) {
                output.erase("raised");
                output["value"] = value;
            };
            if (id == "s13/get_parameters" || id == "s15/get_parameters") answer(parameters);
            if (id == "s16/get_parameters") answer(filterParameters);
            if (id == "s17/resource_id") answer(filterIdentity);
            if (id == "s18/image_outputs") answer(filterOutputs);
        }
    }
    Rebind(record);
    return record;
}

/// Changes the value of the first output of `round` whose id starts with `prefix` and whose call
/// ends with `suffix` (and, when given, whose selector is `role`'s source).
void ChangeLeaf(json::Object& record, std::size_t round, const std::string& prefix, const std::string& suffix,
                const json::Value& value, const char* role = nullptr) {
    for (json::Value& item : Outputs(record, round)) {
        json::Object& output = Obj(item);
        const auto& id = std::get<std::string>(output.at("output_id").data);
        const auto call = output.find("call");
        if (!id.starts_with(prefix) || call == output.end() || !std::get<std::string>(call->second.data).ends_with(suffix)) continue;
        if (role != nullptr && !Selector(output, role, true)) continue;
        output.erase("raised");
        output["value"] = value;
        return;
    }
    throw std::runtime_error("no leaf " + prefix + "*" + suffix);
}

/// Makes the Filter's blending leaves of `channel` in the frames starting with `prefix` unraised
/// (Normal, opacity 1.0), as an observed inactive channel reads.
void ChangeFilterBlend(json::Object& record, std::size_t round, const std::string& prefix, const std::string& channel) {
    const json::Value path = json::Array{json::Array{"Root", std::int64_t{0}}, json::Array{"Content", std::int64_t{0}}};
    const json::Value parameters = json::Object{{"channel", channel}};
    int changed = 0;
    for (json::Value& item : Outputs(record, round)) {
        json::Object& output = Obj(item);
        const auto& id = std::get<std::string>(output.at("output_id").data);
        const auto call = output.find("call");
        if (!id.starts_with(prefix) || call == output.end()) continue;
        const auto& name = std::get<std::string>(call->second.data);
        const bool mode = name.ends_with("Node.get_blending_mode");
        if (!mode && !name.ends_with("Node.get_opacity")) continue;
        const auto& args = std::get<json::Object>(output.at("args").data);
        const auto& selector = std::get<json::Object>(args.at("selector").data);
        const auto found = selector.find("path");
        if (found == selector.end() || json::WriteCanonical(found->second) != json::WriteCanonical(path) ||
            json::WriteCanonical(args.at("parameters")) != json::WriteCanonical(parameters)) {
            continue;
        }
        output.erase("raised");
        output["value"] = mode ? json::Value("Normal") : json::Value(1.0);
        ++changed;
    }
    Expect(changed == 2, "the Filter's two blending leaves of the channel were changed");
}

void Raise(json::Object& record, std::size_t round, const std::string& id, const std::string& type) {
    for (json::Value& item : Outputs(record, round)) {
        json::Object& output = Obj(item);
        if (std::get<std::string>(output.at("output_id").data) != id) continue;
        output["value"] = nullptr;
        output["raised"] = json::Object{{"type", type}, {"message", "authored refusal"}};
        return;
    }
    throw std::runtime_error("no output " + id);
}

// ── The authored H ─────────────────────────────────────────────────────────────────────────────

std::string Exr(std::uint32_t channels, float value = 0.5f) {
    exporter::ExrImage image{128, 128, channels, {}, false};
    image.values.assign(std::size_t{128} * 128 * channels, value);
    return exporter::EncodeExr(image);
}

json::Object ExportRound(int index) {
    const std::string directory = "C:/authored/h-capture/export" + std::to_string(index);
    json::Array maps;
    for (const auto& [name, channels] : {std::pair<const char*, const char*>{"user0", "L"}, {"user1", "RGB"}}) {
        json::Array list;
        for (const char* c = channels; *c != '\0'; ++c) {
            list.push_back(json::Object{{"destChannel", std::string(1, *c)}, {"srcChannel", std::string(1, *c)},
                                        {"srcMapType", "documentMap"}, {"srcMapName", name}});
        }
        maps.push_back(json::Object{{"fileName", name}, {"channels", std::move(list)}});
    }
    const json::Object config{
        {"exportPath", directory}, {"exportShaderParams", false}, {"defaultExportPreset", "uzp_snapshot"},
        {"exportPresets", json::Array{json::Object{{"name", "uzp_snapshot"}, {"maps", std::move(maps)}}}},
        {"exportList", json::Array{json::Object{{"rootPath", "uzp_plane"}}}},
        {"exportParameters", json::Array{json::Object{{"parameters", json::Object{{"fileFormat", "exr"}, {"bitDepth", "32f"},
                                                                                  {"dithering", false},
                                                                                  {"paddingAlgorithm", "passthrough"}}}}}}};
    return json::Object{{"config", config},
                        {"result", json::Object{{"status", "Success"}, {"message", ""},
                                                {"files", json::Array{directory + "/user0.exr", directory + "/user1.exr"}}}}};
}

/// The bridge's readback of the authored H source: the world's parameters, outputs, active output
/// and resolution, observed for the step-5 resource.
json::Object Readback(const std::string& url, const json::Value& parameters, const json::Value& outputs,
                      const json::Value& active, const json::Value& resolution) {
    const auto& f = std::get<json::Object>(resolution.data);
    const json::Object source{{"resource", url},
                              {"inputs", json::Array{}},
                              {"outputs", outputs},
                              {"active_output", active},
                              {"opacity", std::int64_t{1}},
                              {"blending", "Normal"},
                              {"resolution", json::Object{{"mode", f.at("mode")}, {"value", f.at("value")},
                                                          {"log2_offset", f.at("log2_offset")}}},
                              {"resource_id", HostIdentity(url)},
                              {"parameters", parameters}};
    return json::Object{
        {"channel_formats", json::Object{{"User0", "L32F"}, {"User1", "RGB32F"}}},
        {"source_mode", "Split"},
        {"projection_mode", "UV"},
        {"active_channels", json::Array{"User0", "User1"}},
        {"projection", json::Object{{"filtering", "Nearest"}, {"wrapping", "RepeatNone"}, {"scale_mode", "Factors"},
                                    {"scale", json::Array{std::int64_t{1}, std::int64_t{1}}}, {"rotation", std::int64_t{0}},
                                    {"offset", json::Array{std::int64_t{0}, std::int64_t{0}}}}},
        {"isolated_tree", json::Object{{"roots", json::Array{std::int64_t{7}}}, {"fill", std::int64_t{7}}, {"visible", true},
                                       {"mask", false}, {"content_effects", json::Array{}}, {"mask_effects", json::Array{}}}},
        {"sets", json::Array{json::Object{{"name", "uzp_plane"}, {"resolution", json::Array{std::int64_t{128}, std::int64_t{128}}},
                                          {"has_uv_tiles", false}}}},
        {"sources", json::Array{source, source}}};
}

/// The H store's projection: one set, one stack (User0 L32F), the host Fill bound to the snapshot of
/// `url` with `parameters`, and the initial empty Paint; the plane is the only resource.
core::Project HScene(const std::string& url, const json::Object& parameters) {
    core::Project p;
    p.versions.app_version = "0.0.0";
    p.versions.evaluator_profile = "painter-12.1-isolated-linear";
    core::TextureSet set;
    set.id = p.AllocateId();
    set.name = "uzp_plane";
    set.original_name = "uzp_plane";
    set.material_id = "material-0";
    set.resolution.width = 128;
    set.resolution.height = 128;
    set.uv_tiles = {core::UVTile{p.AllocateId(), 1001, {}}};
    core::Stack stack;
    stack.id = p.AllocateId();
    stack.channels[core::ChannelType::User0] = core::Channel{core::ChannelFormat::L32F, "", {}};
    core::Layer host;
    host.uid = p.AllocateId();
    host.kind = core::LayerKind::fill;
    host.name = "host";
    host.blending[core::ChannelType::User0] = core::Blending{core::BlendingMode::Normal, 1.0, {}};
    core::ProceduralSource source;
    source.ref.asset = "uzasset://snapshot/" + core::Sha256Hex(url) + "@1";
    source.ref.params = parameters;
    source.ref.output_mapping = {{"User0", "scalar"}};
    core::FillContent fill;
    fill.source_mode = core::SourceMode::Split;
    fill.sources[core::ChannelType::User0] = core::Source{source};
    fill.active_channels = {core::ChannelType::User0};
    host.fill = std::move(fill);
    core::Layer paint;
    paint.uid = p.AllocateId();
    paint.kind = core::LayerKind::paint;
    paint.name = "Layer 1";
    paint.paint = core::PaintContent{};
    stack.root_layers = {std::move(host), std::move(paint)};
    set.stacks = {std::move(stack)};
    p.texture_sets = {std::move(set)};
    core::ResourceMeta meta;
    meta.id = p.AllocateId();
    meta.name = "plane.obj";
    meta.mime = "model/obj";
    meta.size = static_cast<std::int64_t>(fx::PlaneObj().size());
    meta.usage = "MESH";
    meta.origin = "import";
    meta.imported_at = "2026-10-26T00:00:00Z";
    p.resources[std::string(store::kFrozenHostPlaneMesh)] = {meta};
    p.mesh.emplace();
    p.mesh->resource = std::string(store::kFrozenHostPlaneMesh);
    return p;
}

/// The authored H: its store's projection with the recorded snapshot, its validated artifacts, the
/// capture/2 host section with its artifact bytes, and the store's uuid and revision.
struct AuthoredH {
    core::Project base;
    std::optional<procedural::ValidatedHostArtifacts> artifacts;
    json::Object hostCapture;
    std::map<std::string, std::string, std::less<>> artifactBytes;
    std::string uuid;
    std::int64_t revision = 0;
};

/// How an authored H is recorded: the receipt's recorder pins, the raster value, whether the store
/// is saved and closed (for the command), and an optional edit committed after the snapshot.
struct HOptions {
    json::Object recorder{{"bridge_sha256", core::Sha256Hex("authored bridge")},
                          {"painter_side_sha256", core::Sha256Hex("authored painter side")}};
    float raster = 0.5f;
    bool persist = false;
    std::function<void(core::Project&)> amend;
};

AuthoredH RecordH(const fs::path& file, const std::string& url, const json::Value& parameters, const json::Value& outputs,
                  const json::Value& active, const json::Value& resolution, const HOptions& options = {}) {
    const std::string plane = fx::PlaneObj();
    core::DocumentState initial;
    initial.project_uuid = "6f1c2a3e-0000-4000-8000-0000000c4c4c";
    initial.project = HScene(url, std::get<json::Object>(parameters.data));
    store::CreateOptions create;
    create.resources = {store::PendingContent::Bytes{plane, "model/obj"}};
    auto store = store::ProjectStore::Create(file, initial, create);
    core::Document document(initial);
    store->Attach(document);
    const std::string scalar = Exr(1, options.raster);
    const std::string rgb = Exr(3, options.raster);
    std::string texels(std::size_t{128} * 128 * 4, '\0');
    for (std::size_t i = 0; i < 128 * 128; ++i) std::memcpy(texels.data() + i * 4, &options.raster, 4);
    json::Object receipt;
    std::optional<std::string> failure;
    const auto outcome = store->Submit(document, {"filter-gate-destination-test", json::Object{}, "record", document.revision()},
                                       [&](core::Edit& edit) {
                                           core::Project& project = edit.project();
                                           core::Layer& host = project.texture_sets[0].stacks[0].root_layers[0];
                                           const core::ProceduralRef& ref =
                                               std::get<core::ProceduralSource>(host.fill->sources.at(core::ChannelType::User0).value).ref;
                                           auto request = procedural::SnapshotFillRequest(
                                               project, project.texture_sets[0], core::ChannelType::User0,
                                               core::ChannelFormat::L32F, *host.fill, ref, host.uid, false);
                                           if (!request) throw std::runtime_error(request.error());
                                           receipt = json::Object{
                                               {"schema", "uzpainter/procedural-capture/1"},
                                               {"recorder", options.recorder},
                                               {"identity", json::Object{{"pid", std::int64_t{4242}}, {"version", "12.2.0"},
                                                                         {"version_info", json::Array{std::int64_t{12}, std::int64_t{2}, std::int64_t{0}}},
                                                                         {"OCIO", nullptr}, {"PAINTER_ACE_CONFIG", nullptr},
                                                                         {"project_open", false}, {"mesh", nullptr}}},
                                               {"resource", url},
                                               {"readback", Readback(url, parameters, outputs, active, resolution)},
                                               {"exports", json::Array{ExportRound(1), ExportRound(2)}},
                                               {"project_uuid", store->project_uuid()},
                                               {"revision", document.revision()},
                                               {"signature", procedural::SignatureJson(*request)},
                                               {"files", json::Object{{"export1/user0.exr", core::Sha256Hex(scalar)},
                                                                      {"export1/user1.exr", core::Sha256Hex(rgb)},
                                                                      {"export2/user0.exr", core::Sha256Hex(scalar)},
                                                                      {"export2/user1.exr", core::Sha256Hex(rgb)}}}};
                                           auto metadata = procedural::ReceiptSourceMetadata(receipt, url, *request);
                                           if (!metadata) {
                                               failure = metadata.error();
                                               throw std::runtime_error(metadata.error());
                                           }
                                           procedural::RecordSnapshot(*store, edit, *request, texels, *metadata);
                                       });
    Expect(outcome.result && outcome.result->status == core::ResultStatus::committed,
           "record the authored H snapshot: " + failure.value_or(outcome.result ? outcome.result->error : ""));
    std::map<std::string, std::string, std::less<>> artifacts;
    const auto ref = [&](const char* kind, const std::string& bytes) {
        artifacts[core::Sha256Hex(bytes)] = bytes;
        return json::Object{{"kind", kind}, {"sha256", core::Sha256Hex(bytes)}, {"size_bytes", static_cast<std::int64_t>(bytes.size())}};
    };
    const json::Object hostCapture{
        {"protocol", "paired-scalar-rgb"},
        {"receipt", ref("snapshot_receipt", json::WriteCanonical(receipt))},
        {"request", ref("snapshot_request", json::WriteCanonical(json::Object{{"resource", url},
                                                                              {"parameters", json::Object{{"integer", std::int64_t{1}}}}}))},
        {"environment", nullptr},
        {"environment_binding", nullptr},
        {"scalar_exports", json::Array{ref("snapshot_scalar_export", scalar), ref("snapshot_scalar_export", scalar)}},
        {"rgb_exports", json::Array{ref("snapshot_rgb_export", rgb), ref("snapshot_rgb_export", rgb)}}};
    const procedural::ArtifactBytes transport = [&artifacts](std::string_view sha) -> std::optional<std::string> {
        const auto found = artifacts.find(sha);
        return found == artifacts.end() ? std::nullopt : std::optional<std::string>(found->second);
    };
    AuthoredH h;
    auto validated = procedural::ValidateHostCaptureArtifacts(hostCapture, transport);
    Expect(validated.has_value(), "the authored H validates: " + (validated ? std::string() : validated.error().detail));
    h.artifacts.emplace(std::move(*validated));
    if (options.amend) {
        const auto amended = store->Submit(document, {"filter-gate-destination-amend", json::Object{}, "amend", document.revision()},
                                           [&](core::Edit& edit) { options.amend(edit.project()); });
        Expect(amended.result && amended.result->status == core::ResultStatus::committed, "amend the authored H project");
    }
    h.base = *document.snapshot().project;
    h.hostCapture = hostCapture;
    h.artifactBytes = artifacts;
    h.uuid = store->project_uuid();
    h.revision = document.revision();
    if (options.persist) {
        store->Save(document);
        store->Close();
    }
    return h;
}

}  // namespace

int RunFilterGateDestinationCases(const fs::path& work) {
    int checks = 0;
    const auto check = [&](bool okay, const std::string& message) {
        Expect(okay, message);
        ++checks;
    };
    const json::Object authored = std::get<json::Object>(json::Parse(Read(work / "destination-record.json")).data);
    const std::string png = Read(work / "destination-panel.png");
    int cases = 0;

    // The F slices of one record, through the real C1-C3.
    struct Slices {
        std::optional<procedural::AdmittedFilterCapture> capture;
        std::optional<procedural::CheckedSettingsPanels> panels;
        std::optional<procedural::ValidatedFilterTrace> trace;
        std::optional<procedural::ValidatedFilterSettings> settings;
    };
    const auto slices = [&](const json::Object& record, const std::string& manifestText = {}) {
        Capture capture;
        capture.record = record;
        capture.record["environment"] = capture.environment;
        for (auto& [id, bytes] : capture.images) bytes = png;
        capture.Reference();
        if (!manifestText.empty()) capture.manifest_text = manifestText + json::WriteCanonical(capture.manifest);
        const std::string name = "case-" + std::to_string(++cases);
        auto admitted = AdmitAuthored(capture, work / (name + "-store"), work / (name + "-registry.json"));
        Expect(admitted.has_value(), "the authored F admits (" + (admitted ? std::string() : admitted.error().detail) + ")");
        Slices s;
        s.capture.emplace(std::move(*admitted));
        auto panels = procedural::CheckFilterSettingsPanels(*s.capture);
        Expect(panels.has_value(), "the authored panels check (" + (panels ? std::string() : panels.error().detail) + ")");
        s.panels.emplace(std::move(*panels));
        auto trace = procedural::ValidateFilterTrace(*s.capture, *s.panels);
        Expect(trace.has_value(), "the authored trace validates (" + (trace ? std::string() : trace.error().detail) + ")");
        s.trace.emplace(std::move(*trace));
        auto settings = procedural::DeriveFilterSettings(*s.capture, *s.panels, *s.trace);
        Expect(settings.has_value(), "the authored settings derive (" + (settings ? std::string() : settings.error().detail) + ")");
        s.settings.emplace(std::move(*settings));
        return s;
    };

    // The bound record and the authored H it binds.
    const std::string url = StepFiveUrl(Capture().manifest);
    json::Object recordCopy = authored;
    const json::Object bound = Bound(recordCopy, url);
    json::Object probe = bound;
    const json::Value parameters = PreLeaf(probe, 0, "host", "get_parameters");
    const json::Value outputs = PreLeaf(probe, 0, "host", "image_outputs");
    const json::Value active = PreLeaf(probe, 0, "host", "active_output");
    const json::Value resolution = PreLeaf(probe, 0, "host", "resolution");
    const AuthoredH h = RecordH(work / "h-store.uzp", url, parameters, outputs, active, resolution);
    const procedural::ValidatedHostArtifacts& host = *h.artifacts;
    const Slices f = slices(bound);
    const auto expected = [&](const Slices& s, const core::Project& base) {
        return procedural::ExpectedDestination(*s.capture, *s.panels, *s.trace, *s.settings, host, base);
    };
    const auto detail = [](const auto& result) { return result ? std::string("accepted") : result.error().detail; };
    const auto refuses = [&](const std::string& label, std::string_view reason, std::string_view code,
                             const std::expected<procedural::ValidatedFilterDestination, procedural::ImportRefusal>& result) {
        check(!result && result.error().reason == reason && result.error().detail == code,
              label + " refuses " + std::string(code) + " (" + (result ? std::string("accepted") : result.error().reason + "/" + result.error().detail) + ")");
    };

    // Acceptance on the H store's own projection: reused host and Paint, the Filter's id allocated.
    {
        const auto result = expected(f, h.base);
        check(result.has_value(), "the authored F and H give the expected destination (" + detail(result) + ")");
        if (result) {
            const core::Project& prospective = result->Prospective();
            const core::Stack& stack = prospective.texture_sets.at(0).stacks.at(0);
            const core::Stack& baseStack = h.base.texture_sets.at(0).stacks.at(0);
            check(stack.root_layers.size() == 2 && stack.root_layers[0].uid == baseStack.root_layers[0].uid &&
                      stack.root_layers[1].uid == baseStack.root_layers[1].uid &&
                      stack.root_layers[0].content_effects.size() == 1 &&
                      stack.root_layers[0].content_effects[0].uid == h.base.next_id && prospective.next_id == h.base.next_id + 1,
                  "the host and Paint keep their ids and the Filter takes the base's next id");
            check(stack.root_layers[0].name == "same name" && stack.root_layers[1].name == "same name" &&
                      result->FilterEffect().name == "same name" && prospective.texture_sets[0].name == "set" && stack.name == "stack" &&
                      stack.channels.at(core::ChannelType::User0).label == "User 0",
                  "the F names and channel label are mapped");
            store::FrozenHostNodes nodes;
            check(store::FrozenHostDomainProblem(prospective, nodes).empty(), "the prospective project is inside the domain");
            const auto& roles = result->Roles();
            check(json::WriteCanonical(roles.at("allocated")) == R"(["filter"])" &&
                      json::WriteCanonical(std::get<json::Object>(roles.at("host").data).at("f_uid")) == "20" &&
                      json::WriteCanonical(std::get<json::Object>(roles.at("initial_paint").data).at("f_uid")) == "10" &&
                      json::WriteCanonical(std::get<json::Object>(roles.at("filter").data).at("f_uid")) == "30",
                  "the role map names the F uids and only the Filter as allocated");
            const auto& descriptor = result->Descriptor();
            check(descriptor.size() == 4 && json::WriteCanonical(descriptor.at("role")) == "\"filter\"" &&
                      json::WriteCanonical(descriptor.at("parameters")) ==
                          json::WriteCanonical(result->Observations().at("parameters")) &&
                      result->FilterEffect().procedural->asset == store::ObservationPin(store::ObservationKey(descriptor)),
                  "the descriptor and observations come from steps 16-18 and pin the Filter");
            const auto& capture = result->FilterCapture();
            const auto& provenance = std::get<json::Object>(capture.at("provenance").data);
            check(capture.size() == 5 && provenance.size() == 7 &&
                      std::get<json::Array>(provenance.at("receipts").data).size() == 2 &&
                      json::WriteCanonical(capture.at("rounds")) == json::WriteCanonical(f.trace->Rounds()),
                  "the capture/2 filter section carries the V1 provenance and the trace rounds");
            check(json::WriteCanonical(result->RemovedDefaults().at("channels")) == "[]", "no defaults to remove on this base");
            const auto again = expected(f, h.base);
            check(again && json::WriteCanonical(again->Identity()) == json::WriteCanonical(result->Identity()),
                  "the expected destination is deterministic");
        }
    }

    // A base without host and Paint, and with only the Paint: ids allocated host, Paint, Filter.
    {
        core::Project base = h.base;
        base.texture_sets[0].stacks[0].root_layers.clear();
        const auto result = expected(f, base);
        check(result && json::WriteCanonical(result->Roles().at("allocated")) == R"(["host","initial_paint","filter"])" &&
                  result->Prospective().texture_sets[0].stacks[0].root_layers[0].uid == base.next_id &&
                  result->Prospective().texture_sets[0].stacks[0].root_layers[1].uid == base.next_id + 1 &&
                  result->FilterEffect().uid == base.next_id + 2,
              "an empty base allocates the host, the Paint and the Filter in order (" + detail(result) + ")");
        core::Project paintOnly = h.base;
        auto& layers = paintOnly.texture_sets[0].stacks[0].root_layers;
        layers.erase(layers.begin());
        const auto partial = expected(f, paintOnly);
        check(partial && json::WriteCanonical(partial->Roles().at("allocated")) == R"(["host","filter"])" &&
                  partial->FilterEffect().uid == paintOnly.next_id + 1,
              "a Paint-only base allocates the host, then the Filter (" + detail(partial) + ")");
    }

    // A host-only base allocates the Paint, then the Filter; the input base is never changed.
    {
        core::Project hostOnly = h.base;
        hostOnly.texture_sets[0].stacks[0].root_layers.pop_back();
        const std::string before = json::WriteCanonical(core::ProjectToJson(hostOnly));
        const auto result = expected(f, hostOnly);
        check(result && json::WriteCanonical(result->Roles().at("allocated")) == R"(["initial_paint","filter"])" &&
                  result->Prospective().texture_sets[0].stacks[0].root_layers[1].uid == hostOnly.next_id &&
                  result->FilterEffect().uid == hostOnly.next_id + 1,
              "a host-only base allocates the Paint, then the Filter (" + detail(result) + ")");
        check(json::WriteCanonical(core::ProjectToJson(hostOnly)) == before && result &&
                  json::WriteCanonical(core::ProjectToJson(result->Base())) == before,
              "the input base is unchanged and kept as given");
    }

    // Retained snapshots stay exactly as they were.
    {
        core::Project base = h.base;
        json::Object& snapshots = std::get<json::Object>(base.extra.at(std::string(store::kSnapshotsKey)).data);
        snapshots[std::string(64, 'f')] = snapshots.begin()->second;
        const auto result = expected(f, base);
        check(result && json::WriteCanonical(result->Prospective().extra.at(std::string(store::kSnapshotsKey))) ==
                            json::WriteCanonical(base.extra.at(std::string(store::kSnapshotsKey))),
              "other retained snapshot entries are kept unchanged (" + detail(result) + ")");
    }

    // The store-free binding the command runs before any replay lookup.
    check(!procedural::ValidateFilterHostBinding(*f.capture, *f.panels, *f.trace, *f.settings, host).has_value(),
          "the authored F binds the authored H without a base");

    // The approved known constructor defaults: every subset is removed, every mutation refuses.
    const auto withDefaults = [&](const std::function<void(core::FillContent&)>& change) {
        core::Project base = h.base;
        auto& stack = base.texture_sets[0].stacks[0];
        stack.channels[core::ChannelType::BaseColor] = core::Channel{core::ChannelFormat::sRGB8, "", {}};
        stack.channels[core::ChannelType::Height] = core::Channel{core::ChannelFormat::L16F, "", {}};
        change(*stack.root_layers[0].fill);
        return base;
    };
    const auto uniform = [](double value, const char* space = "Working") {
        return core::Source{core::UniformColorSource{{value, value, value}, space, {}}};
    };
    const double point8 = static_cast<double>(0.8f);
    for (const auto& [label, channels] : std::vector<std::pair<std::string, std::string>>{
             {"BaseColor", R"(["BaseColor"])"}, {"Height", R"(["Height"])"}, {"both", R"(["BaseColor","Height"])"}}) {
        const auto base = withDefaults([&, label = label](core::FillContent& fill) {
            if (label != "Height") fill.sources[core::ChannelType::BaseColor] = uniform(point8);
            if (label != "BaseColor") fill.sources[core::ChannelType::Height] = uniform(0.0);
        });
        const auto result = expected(f, base);
        check(result && json::WriteCanonical(result->RemovedDefaults().at("channels")) == channels &&
                  result->Prospective().texture_sets[0].stacks[0].root_layers[0].fill->sources.size() == 1,
              "the known default subset " + label + " is removed (" + detail(result) + ")");
    }
    for (const auto& [label, change] : std::vector<std::pair<std::string, std::function<void(core::FillContent&)>>>{
             {"a double 0.8 BaseColor", [&](core::FillContent& fill) { fill.sources[core::ChannelType::BaseColor] = uniform(0.8); }},
             {"a -0 Height", [&](core::FillContent& fill) { fill.sources[core::ChannelType::Height] = uniform(-0.0); }},
             {"another colour space", [&](core::FillContent& fill) {
                  fill.sources[core::ChannelType::BaseColor] = uniform(point8, "sRGB");
              }},
             {"an extra field", [&](core::FillContent& fill) {
                  core::Source source = uniform(point8);
                  std::get<core::UniformColorSource>(source.value).extra["authored"] = true;
                  fill.sources[core::ChannelType::BaseColor] = source;
              }},
             {"another source kind", [&](core::FillContent& fill) {
                  fill.sources[core::ChannelType::BaseColor] = core::Source{core::BitmapSource{}};
              }},
             {"an active default channel", [&](core::FillContent& fill) {
                  fill.sources[core::ChannelType::BaseColor] = uniform(point8);
                  fill.active_channels.insert(core::ChannelType::BaseColor);
              }},
             {"another channel", [&](core::FillContent& fill) { fill.sources[core::ChannelType::Roughness] = uniform(point8); }}}) {
        refuses("a host default with " + label, procedural::kTargetContextUnrepresentable, gate::kHostSources,
                expected(f, withDefaults(change)));
    }

    // Base channels F lacks: dropped when unreferenced, refused when a layer still names them.
    {
        core::Project base = h.base;
        base.texture_sets[0].stacks[0].channels[core::ChannelType::Roughness] = core::Channel{core::ChannelFormat::L8, "", {}};
        const auto result = expected(f, base);
        check(result && !result->Prospective().texture_sets[0].stacks[0].channels.contains(core::ChannelType::Roughness),
              "an unreferenced base channel F lacks is dropped (" + detail(result) + ")");
        core::Project hostBlend = base;
        hostBlend.texture_sets[0].stacks[0].root_layers[0].blending[core::ChannelType::Roughness] = core::Blending{};
        refuses("a dropped channel the host blends", procedural::kTargetContextUnrepresentable, gate::kStartingShape,
                expected(f, hostBlend));
        core::Project paintBlend = base;
        paintBlend.texture_sets[0].stacks[0].root_layers[1].blending[core::ChannelType::Roughness] = core::Blending{};
        refuses("a dropped channel the Paint blends", procedural::kTargetContextUnrepresentable, gate::kStartingShape,
                expected(f, paintBlend));
    }

    // The starting shape and H's snapshot entry.
    {
        core::Project base = h.base;
        base.texture_sets[0].stacks[0].root_layers.push_back(base.texture_sets[0].stacks[0].root_layers[1]);
        refuses("a third root layer", procedural::kTargetContextUnrepresentable, gate::kStartingShape, expected(f, base));
        core::Project swapped = h.base;
        auto& layers = swapped.texture_sets[0].stacks[0].root_layers;
        std::swap(layers[0], layers[1]);
        refuses("the Paint above the host", procedural::kTargetContextUnrepresentable, gate::kStartingShape, expected(f, swapped));
        core::Project tangent = h.base;
        tangent.settings.tangent_space = core::TangentSpace::PerFragment;
        refuses("a per-fragment tangent space", procedural::kTargetContextUnrepresentable, gate::kStartingShape, expected(f, tangent));
        core::Project extra = h.base;
        extra.extra["authored"] = true;
        refuses("an unknown project member", procedural::kTargetContextUnrepresentable, gate::kStartingShape, expected(f, extra));
        core::Project noSnapshot = h.base;
        noSnapshot.extra.erase(std::string(store::kSnapshotsKey));
        refuses("a base without H's snapshot", procedural::kTargetContextUnrepresentable, gate::kHostSnapshot, expected(f, noSnapshot));
        core::Project rebound = h.base;
        std::get<core::ProceduralSource>(rebound.texture_sets[0].stacks[0].root_layers[0].fill->sources.at(core::ChannelType::User0).value)
            .ref.params["integer"] = std::int64_t{2};
        refuses("a host bound to other parameters", procedural::kTargetContextUnrepresentable, gate::kHostSources,
                expected(f, rebound));
    }

    // The host reference and the layers' remaining members: anything but the plain bind refuses.
    const auto hostRef = [](core::Project& p) -> core::ProceduralRef& {
        return std::get<core::ProceduralSource>(
                   p.texture_sets[0].stacks[0].root_layers[0].fill->sources.at(core::ChannelType::User0).value)
            .ref;
    };
    for (const auto& [label, code, change] :
         std::vector<std::tuple<std::string, std::string_view, std::function<void(core::Project&)>>>{
             {"a host reference extra", gate::kHostSources, [&](core::Project& p) { hostRef(p).extra["authored"] = true; }},
             {"a host reference preset", gate::kHostSources, [&](core::Project& p) { hostRef(p).preset = "authored"; }},
             {"a host reference image input", gate::kHostSources,
              [&](core::Project& p) { hostRef(p).image_inputs["input"] = core::ResourceBinding{}; }},
             {"a host reference mask output", gate::kHostSources, [&](core::Project& p) { hostRef(p).mask_output = "mask"; }},
             {"a host layer extra", gate::kStartingShape,
              [](core::Project& p) { p.texture_sets[0].stacks[0].root_layers[0].extra["authored"] = true; }},
             {"a collapsed host", gate::kStartingShape,
              [](core::Project& p) { p.texture_sets[0].stacks[0].root_layers[0].collapsed = true; }},
             {"a Paint layer extra", gate::kStartingShape,
              [](core::Project& p) { p.texture_sets[0].stacks[0].root_layers[1].extra["authored"] = true; }},
             {"a collapsed Paint", gate::kStartingShape,
              [](core::Project& p) { p.texture_sets[0].stacks[0].root_layers[1].collapsed = true; }}}) {
        core::Project base = h.base;
        change(base);
        refuses(label, procedural::kTargetContextUnrepresentable, code, expected(f, base));
    }

    // MAPPED members are replaced from F: any unknown data in them refuses instead of being dropped.
    for (const auto& [label, change] : std::vector<std::pair<std::string, std::function<void(core::Project&)>>>{
             {"a host projection extra", [](core::Project& p) {
                  p.texture_sets[0].stacks[0].root_layers[0].fill->projection.extra["authored"] = true;
              }},
             {"host projection parameters", [](core::Project& p) {
                  p.texture_sets[0].stacks[0].root_layers[0].fill->projection.params["authored"] = true;
              }},
             {"a host UV projection extra", [](core::Project& p) {
                  p.texture_sets[0].stacks[0].root_layers[0].fill->projection.uv.extra["authored"] = true;
              }},
             {"a host UV transformation extra", [](core::Project& p) {
                  p.texture_sets[0].stacks[0].root_layers[0].fill->projection.uv.uv_transformation.extra["authored"] = true;
              }},
             {"a host blending extra", [](core::Project& p) {
                  p.texture_sets[0].stacks[0].root_layers[0].blending[core::ChannelType::User0].extra["authored"] = true;
              }},
             {"a Paint blending extra", [](core::Project& p) {
                  p.texture_sets[0].stacks[0].root_layers[1].blending[core::ChannelType::User0].extra["authored"] = true;
              }}}) {
        core::Project base = h.base;
        change(base);
        refuses(label, procedural::kTargetContextUnrepresentable, gate::kStartingShape, expected(f, base));
    }

    // J1-J4 on records changed after binding (panels rebound so C1-C3 still accept them).
    const auto joined = [&](const std::string& label, std::string_view code, const std::function<void(json::Object&)>& change) {
        json::Object record = bound;
        change(record);
        Rebind(record);
        refuses(label, procedural::kHostSourceStateMismatch, code, expected(slices(record), h.base));
    };
    {
        json::Object record = bound;
        ChangeLeaf(record, 1, "context/after-reopen/", "SourceSubstance.resource_id",
                   Wrapped(HostIdentity("resource://starter_assets/other?version=1")), "host");
        Rebind(record);
        const Slices other = slices(record);
        const auto binding = procedural::ValidateFilterHostBinding(*other.capture, *other.panels, *other.trace, *other.settings, host);
        check(binding && binding->reason == procedural::kHostSourceStateMismatch && binding->detail == gate::kJ1SourceIdentity,
              "the store-free binding refuses the same J1 as the destination");
    }
    joined("another reopened source identity", gate::kJ1SourceIdentity, [&](json::Object& record) {
        ChangeLeaf(record, 1, "context/after-reopen/", "SourceSubstance.resource_id",
                   Wrapped(HostIdentity("resource://starter_assets/other?version=1")), "host");
    });
    joined("other pre16 parameters", gate::kJ2Pre16Parameters, [&](json::Object& record) {
        ChangeLeaf(record, 1, "context/pre16-r2/", "SourceSubstance.get_parameters", json::Object{{"integer", std::int64_t{2}}}, "host");
    });
    joined("a failed int write", gate::kJ3IntWrite, [&](json::Object& record) { Raise(record, 0, "s12/set_parameters", "RuntimeError"); });
    joined("a bool write refused other than TypeError", gate::kJ3BoolWrite,
           [&](json::Object& record) { Raise(record, 1, "s14/set_parameters", "ValueError"); });
    joined("a changed step-15 read", gate::kJ3Pre16State,
           [&](json::Object& record) { ChangeLeaf(record, 0, "s15/", "get_parameters", json::Object{{"integer", std::int64_t{2}}}); });
    joined("other pre16 outputs", gate::kJ4Outputs, [&](json::Object& record) {
        for (std::size_t round = 0; round < 2; ++round) {
            ChangeLeaf(record, round, round == 0 ? "context/pre16-r1/" : "context/pre16-r2/", "SourceSubstance.image_outputs",
                       json::Array{"scalar", "other"}, "host");
        }
    });
    {
        json::Object record = bound;
        Raise(record, 1, "s14/set_parameters", "TypeError");
        Rebind(record);
        const auto result = expected(slices(record), h.base);
        check(result.has_value(), "a bool write refused with TypeError still binds (" + detail(result) + ")");
    }

    // The Filter observations and the F context consumed by the mapping.
    {
        json::Object record = bound;
        ChangeLeaf(record, 1, "s17/", "resource_id", Wrapped(HostIdentity("resource://authored/other?version=1")));
        Rebind(record);
        refuses("steps 17 that differ between rounds", procedural::kTargetContextUnrepresentable, gate::kObservations,
                expected(slices(record), h.base));
    }
    {
        json::Object record = bound;
        ChangeLeaf(record, 1, "context/pre16-r2/", "Channel.label", "another label");
        Rebind(record);
        refuses("a channel label that differs between the pre16 frames", procedural::kTargetContextUnrepresentable, gate::kFContext,
                expected(slices(record), h.base));
    }

    // Symmetry: unraised parameters, or outcomes that differ between the pre16 frames, refuse.
    {
        json::Object record = bound;
        for (std::size_t round = 0; round < 2; ++round) {
            ChangeLeaf(record, round, round == 0 ? "context/pre16-r1/" : "context/pre16-r2/",
                       "FillLayerNode.get_symmetry_parameters", json::Object{{"class", "SymmetryParams"}});
        }
        Rebind(record);
        refuses("unraised symmetry parameters", procedural::kTargetContextUnrepresentable, gate::kFContext,
                expected(slices(record), h.base));
    }
    {
        json::Object record = bound;
        ChangeLeaf(record, 1, "context/pre16-r2/", "FillLayerNode.is_symmetry_enabled", false);
        Rebind(record);
        refuses("a symmetry outcome that differs between the pre16 frames", procedural::kTargetContextUnrepresentable,
                gate::kFContext, expected(slices(record), h.base));
    }

    // Inactive Filter channels: an observed state is kept, a raised one is absent, a mixed or
    // differing one refuses; a raised host leaf refuses even on an inactive channel.
    const auto variant = [&](const char* name) {
        return Bound(std::get<json::Object>(json::Parse(Read(work / (std::string("destination-record-") + name + ".json"))).data),
                     url);
    };
    {
        const auto result = expected(slices(variant("inactive-observed")), h.base);
        const bool ok = result.has_value();
        const auto& filter = ok ? result->FilterEffect() : core::Effect{};
        check(ok && filter.active_channels == std::set{core::ChannelType::User0} && filter.blending.size() == 2 &&
                  filter.blending.contains(core::ChannelType::User1) &&
                  filter.blending.at(core::ChannelType::User1).mode == core::BlendingMode::Normal &&
                  filter.blending.at(core::ChannelType::User1).opacity == 1.0 &&
                  result->Prospective().texture_sets[0].stacks[0].channels.size() == 2,
              "an observed inactive Filter channel keeps its blending (" + detail(result) + ")");
    }
    {
        const auto result = expected(slices(variant("inactive-raised")), h.base);
        check(result && result->FilterEffect().blending.size() == 1 &&
                  result->FilterEffect().blending.contains(core::ChannelType::User0),
              "a raised inactive Filter channel stays absent (" + detail(result) + ")");
    }
    refuses("a mixed inactive Filter channel", procedural::kTargetContextUnrepresentable, gate::kFContext,
            expected(slices(variant("inactive-mixed")), h.base));
    {
        json::Object record = variant("inactive-raised");
        ChangeFilterBlend(record, 1, "context/pre16-r2/", "User1");
        Rebind(record);
        refuses("an inactive Filter channel that differs between the pre16 frames", procedural::kTargetContextUnrepresentable,
                gate::kFContext, expected(slices(record), h.base));
    }
    refuses("a raised host blending leaf on an inactive channel", procedural::kTargetContextUnrepresentable, gate::kFContext,
            expected(slices(variant("host-inactive-raised")), h.base));

    // The four slices must name one admission.
    {
        const Slices other = slices(bound, " \n");
        refuses("panels of another admission", procedural::kFilterCaptureInvalid, gate::kSliceIdentity,
                procedural::ExpectedDestination(*f.capture, *other.panels, *f.trace, *f.settings, host, h.base));
    }

    std::cout << "FILTER_GATE_DESTINATION: " << json::WriteCanonical(json::Object{{"checks", checks}}) << "\n";
    return 0;
}

// ── The import command, end to end ──────────────────────────────────────────────────────────────
//
// Fixture limitation, stated plainly: the F capture is admitted under AUTHORED pins (an authored
// registry and envelope), through the test-only `FilterGateTestAccess::RunCommand`, because the
// compiled envelope's hash has no authored preimage. Everything else is the real command: the
// compiled H producer policy, the payload parser, the store-free binding, the read-only preflight,
// the C4 destination, the C5 transaction with its native proof, save, reopen and getters.

namespace {

std::string Utf8(const fs::path& path) {
    const auto text = path.u8string();
    return std::string(text.begin(), text.end());
}

std::string FileSha256(const fs::path& path) { return core::Sha256Hex(Read(path)); }

/// The public H producer policy (`parity/snapshot-producer-policy-v1.json`), as the command's
/// compiled policy embeds it.
std::string PolicyBytes() {
    return Read(fs::path(__FILE__).lexically_normal().parent_path().parent_path().parent_path() / "parity" /
                "snapshot-producer-policy-v1.json");
}

/// Writes `h`'s artifacts and its admission record into the oracle store under the compiled policy.
void AdmitH(const fs::path& oracle, const AuthoredH& h, const std::string& policy) {
    for (const auto& [sha, bytes] : h.artifactBytes) WriteFile(oracle / "blobs" / sha.substr(0, 2) / sha, bytes);
    const auto slot = [](const json::Value& ref, const char* id) {
        json::Object object = std::get<json::Object>(ref.data);
        object["record_id"] = id;
        return object;
    };
    const auto& host = h.hostCapture;
    const auto& scalar = std::get<json::Array>(host.at("scalar_exports").data);
    const auto& rgb = std::get<json::Array>(host.at("rgb_exports").data);
    const json::Object slots{{"environment", nullptr},
                             {"environment_binding", nullptr},
                             {"receipt", slot(host.at("receipt"), "receipt")},
                             {"request", slot(host.at("request"), "request")},
                             {"scalar_exports", json::Array{slot(scalar[0], "r1-scalar"), slot(scalar[1], "r2-scalar")}},
                             {"rgb_exports", json::Array{slot(rgb[0], "r1-rgb"), slot(rgb[1], "r2-rgb")}}};
    const std::string capture =
        core::Sha256Hex(json::WriteCanonical(json::Object{{"protocol", "paired-scalar-rgb"}, {"artifacts", slots}}));
    const std::string policySha = core::Sha256Hex(policy);
    const json::Object identity = h.artifacts->Identity();
    const json::Object admission{
        {"schema", "uzpainter/parity/snapshot-capture-admission/1"},
        {"protocol", "paired-scalar-rgb"},
        {"capture_id", capture},
        {"producer_policy", json::Object{{"sha256", policySha}, {"revision", std::int64_t{1}}}},
        {"artifacts", slots},
        {"provenance", json::Object{{"basis", "owner_local_submission"}, {"execution_attestation", "none"}}},
        {"validation", json::Object{{"validator_revision", "uzpainter/snapshot-capture-validator/1"},
                                    {"validator_code_sha256", core::Sha256Hex("authored validator code")},
                                    {"validator_binary_sha256", core::Sha256Hex("authored validator binary")},
                                    {"signature_sha256", identity.at("signature_sha256")},
                                    {"capture_context_sha256", identity.at("capture_context_sha256")},
                                    {"scalar_raster_sha256", identity.at("raster_sha256")}}},
        {"admitted_at", "2026-10-26T00:00:00Z"}};
    WriteFile(oracle / "snapshot-captures" / capture / (policySha + ".json"), json::WriteCanonical(admission));
    WriteFile(oracle / "snapshot-producer-policies" / (policySha + ".json"), policy);
}

/// The command's one report line and exit code.
struct CommandRun {
    int code = -1;
    json::Object report;
};

/// The command driver: with `fixtureOnly`, it stops after the first import of A and its three
/// checks, printing that fixture's identity and leaving the V2 project unchanged in `work`.
int CommandCases(const fs::path& work, bool fixtureOnly) {
    int checks = 0;
    const auto check = [&](bool okay, const std::string& message) {
        Expect(okay, message);
        ++checks;
    };
    const json::Object authored = std::get<json::Object>(json::Parse(Read(work / "destination-record.json")).data);
    const std::string png = Read(work / "destination-panel.png");
    const std::string policy = PolicyBytes();
    const json::Value policyDocument = json::Parse(policy);
    const json::Object& producer = std::get<json::Object>(
        std::get<json::Array>(std::get<json::Object>(policyDocument.data).at("producers").data)[0].data);
    HOptions approved;
    approved.recorder = json::Object{{"bridge_sha256", producer.at("bridge_sha256")},
                                     {"painter_side_sha256", producer.at("painter_side_sha256")}};
    approved.persist = true;

    // The authored F (bound to the authored H) in the oracle store, its manifest and registry.
    const std::string url = StepFiveUrl(Capture().manifest);
    const json::Object bound = Bound(authored, url);
    Capture capture;
    capture.record = bound;
    capture.record["environment"] = capture.environment;
    for (auto& [id, bytes] : capture.images) bytes = png;
    capture.Reference();
    const fs::path oracle = work / "cli-oracle";
    const fs::path registry = work / "cli-registry.json";
    const fs::path manifest = work / "cli-manifest.json";
    const std::string manifestBytes = capture.Store(oracle, registry);
    WriteFile(manifest, manifestBytes);
    json::Object probe = bound;
    const json::Value parameters = PreLeaf(probe, 0, "host", "get_parameters");
    const json::Value outputs = PreLeaf(probe, 0, "host", "image_outputs");
    const json::Value active = PreLeaf(probe, 0, "host", "active_output");
    const json::Value resolution = PreLeaf(probe, 0, "host", "resolution");

    // The original H stores: A (the import target), B (a starting shape C4 refuses), C (a frozen
    // raster that is not a fixed point, refused by the native proof inside the transaction).
    const AuthoredH a = RecordH(work / "cli-h-a.uzp", url, parameters, outputs, active, resolution, approved);
    HOptions amended = approved;
    amended.amend = [](core::Project& project) { project.extra["authored"] = true; };
    const AuthoredH b = RecordH(work / "cli-h-b.uzp", url, parameters, outputs, active, resolution, amended);
    HOptions negative = approved;
    negative.raster = -0.0f;
    const AuthoredH c = RecordH(work / "cli-h-c.uzp", url, parameters, outputs, active, resolution, negative);
    for (const AuthoredH* h : {&a, &b, &c}) AdmitH(oracle, *h, policy);

    int runs = 0;
    const auto payload = [&](const AuthoredH& h, std::int64_t revision) {
        const fs::path path = work / ("cli-request-" + std::to_string(++runs) + ".json");
        WriteFile(path, json::WriteCanonical(json::Object{{"schema", "uzpainter/filter-observation-v2-import/1"},
                                                          {"manifest", ManifestRef(manifestBytes)},
                                                          {"host", h.hostCapture},
                                                          {"expected_base_revision", revision}}));
        return path;
    };
    const auto run = [&](const fs::path& project, const fs::path& request) {
        const std::string name = "cli-run-" + std::to_string(++runs);
        const fs::path outPath = work / (name + "-out.txt");
        const fs::path errPath = work / (name + "-err.txt");
        std::FILE* out = _wfopen(outPath.c_str(), L"wb");
        std::FILE* err = _wfopen(errPath.c_str(), L"wb");
        Expect(out != nullptr && err != nullptr, "open the command's output files");
        const std::vector<std::string> args{"assets", "import-filter-observation", Utf8(project), "--oracle-store", Utf8(oracle),
                                            "--manifest", Utf8(manifest), "--request", Utf8(request)};
        CommandRun result;
        result.code = procedural::FilterGateTestAccess::RunCommand(args, out, err, registry, capture.pins);
        std::fclose(out);
        std::fclose(err);
        const std::string text = Read(outPath);
        const auto start = text.find("UZP_JSON:");
        Expect(start != std::string::npos, "the command printed its report");
        const auto end = text.find('\n', start);
        result.report = std::get<json::Object>(
            json::Parse(text.substr(start + 9, end == std::string::npos ? std::string::npos : end - start - 9)).data);
        return result;
    };
    const auto text = [](const json::Object& report, const char* key) {
        const auto found = report.find(key);
        return found == report.end() ? std::string() : json::WriteCanonical(found->second);
    };
    const auto refused = [&](const CommandRun& result, std::string_view reason, std::string_view detail) {
        return result.code == 3 && text(result.report, "status") == "\"refused\"" &&
               text(result.report, "reason") == "\"" + std::string(reason) + "\"" &&
               text(result.report, "detail") == "\"" + std::string(detail) + "\"";
    };
    const auto census = [](const fs::path& project) {
        auto reader = store::Container::OpenReadOnly(project);
        store::Statement count(reader, "SELECT COUNT(*) FROM operation");
        Expect(count.Step(), "count the operation rows");
        return std::tuple{reader.Meta("project_uuid").value_or(""), store::ReadCurrentRevision(reader), count.Int(0)};
    };

    // 1. The import commits once on the original H store.
    const fs::path project = work / "cli-h-a.uzp";
    const auto [uuidBefore, revisionBefore, operationsBefore] = census(project);
    const fs::path first = payload(a, a.revision);
    const CommandRun committed = run(project, first);
    check(committed.code == 0 && text(committed.report, "status") == "\"ok\"" && text(committed.report, "replayed") == "false" &&
              text(committed.report, "verified_after_reopen") == "true",
          "the command imports the authored capture (" + json::WriteCanonical(committed.report) + ")");
    const std::string entry = text(committed.report, "entry_key");
    const auto [uuidAfter, revisionAfter, operationsAfter] = census(project);
    check(uuidAfter == a.uuid && uuidAfter == uuidBefore && revisionAfter == revisionBefore + 1 &&
              operationsAfter == operationsBefore + 1,
          "the original store keeps its uuid and gains one revision and one operation");
    core::Id filterUid = core::kNoId;
    {
        auto opened = store::ProjectStore::Open(project);
        const core::Project& state = opened.state.project;
        const core::Id filter = state.texture_sets.at(0).stacks.at(0).root_layers.at(0).content_effects.at(0).uid;
        filterUid = filter;
        const auto observed = procedural::ObservedFilter(*opened.store, state, filter);
        check(observed && "\"" + observed->entry_key + "\"" == entry && observed->parameters && observed->resource_id &&
                  observed->image_outputs,
              "the reopened store serves the imported observations");
    }
    if (fixtureOnly) {
        std::cout << "FILTER_OBSERVATION_V2_FIXTURE: "
                  << json::WriteCanonical(json::Object{{"checks", checks},
                                                       {"project", "cli-h-a.uzp"},
                                                       {"project_sha256", FileSha256(project)},
                                                       {"project_uuid", uuidAfter},
                                                       {"revision", revisionAfter},
                                                       {"entry_key", json::Parse(entry)},
                                                       {"filter_uid", static_cast<std::int64_t>(filterUid)}})
                  << "\n";
        return 0;
    }

    // 2. The same payload replays the recorded outcome without executing or writing.
    {
        const std::string before = FileSha256(project);
        const CommandRun replay = run(project, first);
        check(replay.code == 0 && text(replay.report, "replayed") == "true" && text(replay.report, "entry_key") == entry &&
                  text(replay.report, "revision") == std::to_string(revisionAfter),
              "an exact replay returns the recorded entry");
        check(FileSha256(project) == before, "a replay leaves the file byte-identical");
    }

    // 3. After a later unrelated revision, the same payload still replays the historical row.
    {
        auto opened = store::ProjectStore::Open(project);
        core::Document document(std::move(opened.state));
        opened.store->Attach(document);
        const auto later = opened.store->Submit(document, {"filter-import-later", json::Object{}, "later", document.revision()},
                                                [](core::Edit& edit) { edit.project().texture_sets[0].description = "later"; });
        Expect(later.result && later.result->status == core::ResultStatus::committed, "commit a later revision");
        opened.store->Save(document);
        opened.store->Close();
        const std::string before = FileSha256(project);
        const CommandRun replay = run(project, first);
        check(replay.code == 0 && text(replay.report, "replayed") == "true" && text(replay.report, "entry_key") == entry &&
                  text(replay.report, "revision") == std::to_string(revisionAfter) && FileSha256(project) == before,
              "a replay after a later revision returns the historical row and writes nothing");
    }

    // 4-6. Without a row: a stale revision, a revision below the horizon, and a corrupt row refuse.
    {
        const std::string before = FileSha256(project);
        const CommandRun stale = run(project, payload(a, revisionAfter));
        check(refused(stale, procedural::kStaleProspectiveView, "stale_revision") && FileSha256(project) == before,
              "a stale revision without a row refuses and writes nothing (" + json::WriteCanonical(stale.report) + ")");
    }
    {
        {
            auto container = store::Container::Open(project);
            container.SetMeta("operation_horizon_revision", std::to_string(revisionAfter));
        }
        const std::string before = FileSha256(project);
        const CommandRun horizon = run(project, payload(a, 0));
        check(refused(horizon, procedural::kStaleProspectiveView, "outcome_unknown") && FileSha256(project) == before,
              "a revision below the horizon refuses and writes nothing (" + json::WriteCanonical(horizon.report) + ")");
    }
    {
        const auto parsed = procedural::ParseFilterImportRequest(Read(first));
        Expect(parsed.has_value(), "parse the first payload");
        {
            auto container = store::Container::Open(project);
            store::Statement corrupt(container, "UPDATE operation SET outcome = X'00' WHERE idempotency_key = ?");
            corrupt.Bind(1, parsed->MutationRequestFor(a.uuid).idempotency_key);
            corrupt.Step();
        }
        const std::string before = FileSha256(project);
        const CommandRun broken = run(project, first);
        check(refused(broken, procedural::kStaleProspectiveView, "outcome_unknown") && FileSha256(project) == before,
              "a corrupt recorded row refuses and writes nothing (" + json::WriteCanonical(broken.report) + ")");
    }

    // 7. A refusal in the read-only preflight (C4 refuses the starting shape) writes nothing.
    {
        const fs::path other = work / "cli-h-b.uzp";
        const std::string before = FileSha256(other);
        const CommandRun preflight = run(other, payload(b, b.revision));
        check(refused(preflight, procedural::kTargetContextUnrepresentable, gate::kStartingShape) && FileSha256(other) == before,
              "a preflight refusal leaves the file byte-identical (" + json::WriteCanonical(preflight.report) + ")");
    }

    // 8. A refusal inside the transaction (the native proof) writes nothing.
    {
        const fs::path other = work / "cli-h-c.uzp";
        const std::string before = FileSha256(other);
        const CommandRun proof = run(other, payload(c, c.revision));
        check(refused(proof, procedural::kFrozenRasterNotFixedPoint, "NATIVE_COMMIT_REFUSED") && FileSha256(other) == before,
              "a transaction refusal leaves the file byte-identical (" + json::WriteCanonical(proof.report) + ")");
    }

    std::cout << "FILTER_IMPORT_COMMAND: " << json::WriteCanonical(json::Object{{"checks", checks}}) << "\n";
    return 0;
}

}  // namespace

int RunFilterImportCommandCases(const fs::path& work) { return CommandCases(work, false); }

/// The authored V2 fixture for facade tests: the command driver's first import only (no replay,
/// later revision, horizon, corruption or refusal case), leaving a valid V2 `work/cli-h-a.uzp`.
int RunFilterObservationV2Fixture(const fs::path& work) { return CommandCases(work, true); }
