#include <algorithm>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <expected>
#include <filesystem>
#include <fstream>
#include <initializer_list>
#include <iostream>
#include <iterator>
#include <memory>
#include <optional>
#include <set>
#include <stdexcept>
#include <string_view>

#include "evaluator/evaluator.h"
#include "evaluator/profile.h"
#include "evaluator/result_cache.h"
#include "evaluator/support.h"
#include "procedural/admission.h"
#include "procedural/filter_observation_source.h"
#include "procedural/snapshot_backend.h"
#include "procedural/snapshot_source.h"
#include "store/bundle.h"
#include "store/filter_observations.h"
#include "render/disk_cache.h"
#include "store/snapshots.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

namespace {
void Check(bool okay, const char* message) {
    if (!okay) throw std::runtime_error(message);
}

/// The alternate snapshot's recorded observations (schema /2): authored test values in the
/// bridge's serialization, not Painter data. Its image inputs are an empty observation.
uzp::store::SourceMetadata AuthoredObservations() {
    namespace json = uzp::core::json;
    const auto property = [](const std::string& name, json::Value value, const std::string& widget) {
        return json::Object{{"value", std::move(value)}, {"name", name}, {"short_name", name},
                            {"label", "Authored " + name}, {"widget_type", widget},
                            {"enum_values", json::Object{}}, {"properties", json::Object{{"visible", true}}}};
    };
    json::Object mode = property("mode", std::int64_t{1}, "Combobox");
    // A label beyond 32 bits: enum_value must return the full integer.
    mode["enum_values"] = json::Object{{"Small", std::int64_t{1}}, {"Big", std::int64_t{2147483648LL}}};
    return uzp::store::SourceMetadata{
        {"scalar", "aux"}, std::vector<std::string>{}, std::vector<std::string>{"authored preset"},
        json::Object{{"$randomseed", property("$randomseed", std::int64_t{7}, "RandomSeed")},
                     {"amount", property("amount", 0.625, "Slider")},
                     {"mode", std::move(mode)}},
        std::nullopt, std::nullopt};
}
}

int RunSnapshotSource(const std::filesystem::path& path, std::optional<int64_t> seed) {
    using namespace uzp;
    auto opened = store::ProjectStore::Open(path);
    Check(opened.report.ok(), "initial project integrity");
    core::Document document(std::move(opened.state));
    opened.store->Attach(document);
    auto& store = *opened.store;
    procedural::ProceduralRequest request;
    request.asset = core::ParseAssetUrl("uzasset://snapshot/authored-test@1");
    request.params = {{"amount", 0.5}};
    if (seed) {
        request.params["$randomseed"] = *seed;
        request.seed = static_cast<uint64_t>(*seed);
    }
    request.meshClass = "quad";
    request.outputId = "scalar";
    request.output = {128, procedural::ChannelFormat::F32, "raw", 1};
    request.settings = procedural::EvaluationSettings(*document.snapshot().project);
    std::string bytes(128 * 128 * 4, '\0');
    for (size_t i = 0; i < 128 * 128; ++i) {
        const uint32_t bits = 0x3F000000u + static_cast<uint32_t>((i * 104729) & 0x7FFFFF);
        std::memcpy(bytes.data() + i * 4, &bits, 4);
    }
    int key = 0;
    const auto submit = [&](const std::function<void(core::Edit&)>& call) {
        const auto id = "snapshot-source-" + std::to_string(++key);
        return store.Submit(document, {"snapshot-source-test", core::json::Object{}, id, document.revision()}, call);
    };
    auto recorded = submit([&](core::Edit& edit) {
        procedural::RecordSnapshot(store, edit, request, bytes);
    });
    Check(recorded.result && recorded.result->status == core::ResultStatus::committed, "record synthetic plane");
    core::Id layer = 0;
    auto bound = submit([&](core::Edit& edit) {
        auto& set = edit.project().texture_sets.front();
        auto& stack = set.stacks.front();
        stack.channels[core::ChannelType::User0].format = core::ChannelFormat::L32F;
        core::Layer fill;
        fill.uid = layer = edit.AllocateId();
        fill.name = "explicit snapshot";
        fill.kind = core::LayerKind::fill;
        fill.fill.emplace();
        fill.fill->active_channels.insert(core::ChannelType::User0);
        core::ProceduralRef ref;
        ref.asset = core::FormatAssetUrl(request.asset);
        ref.params = {{"amount", 0.5}};
        if (seed) ref.params["$randomseed"] = *seed;
        ref.output_mapping = {{"User0", "scalar"}};
        fill.fill->sources[core::ChannelType::User0].value = core::ProceduralSource{ref};
        stack.root_layers.insert(stack.root_layers.begin(), std::move(fill));
        procedural::SnapshotSourceProvider provider(store, edit.project());
        evaluator::RequireSupported(edit.base(), edit.project(), {}, &provider);
    });
    if (!bound.result || bound.result->status != core::ResultStatus::committed)
        throw std::runtime_error("explicit bind failed: " + (bound.result ? core::json::WriteCanonical(bound.result->ToJson()) : "no result"));
    const auto project = *document.snapshot().project;
    auto templates = std::make_shared<const evaluator::TemplateLibrary>(
        evaluator::TemplateLibrary::Load(evaluator::TemplateLibrary::DefaultDirectory()));
    render::EnableCaches(path.parent_path() / "snapshot-cache");
    evaluator::CpuEvaluator cpu(templates, {1ull << 30, 1ull << 20});
    evaluator::EvaluateRequest evaluation;
    evaluation.textureSet = project.texture_sets.front().id;
    evaluation.stack = project.texture_sets.front().stacks.front().id;
    evaluation.channel = core::ChannelType::User0;
    evaluation.templateId = project.settings.template_id;
    evaluation.procedurals = std::make_shared<procedural::SnapshotSourceProvider>(store, project);
    for (int repeat = 0; repeat < 2; ++repeat) {
        auto output = cpu.Evaluate(project, evaluation);
        if (!output) throw std::runtime_error(output.error().reason);
        Check(output->tiles.size() == 1 && output->tiles[0].texels.size() == bytes.size(), "one scalar tile");
        Check(std::memcmp(output->tiles[0].texels.data(), bytes.data(), bytes.size()) == 0, "L32F bit exact readout");
    }
    evaluator::CpuEvaluator reopenedCpu(templates, {1ull << 30, 1ull << 20});
    auto persisted = reopenedCpu.Evaluate(project, evaluation);
    Check(persisted && persisted->stats.persistentHits == 1 && persisted->stats.uploads == 0,
          "new evaluator reuses persistent snapshot result without upload");
    auto retainedDag = evaluator::BuildDag(project, evaluation.textureSet, evaluation.stack,
        evaluation.channel, *templates, evaluation.templateId, evaluation.procedurals.get());
    Check(bool(retainedDag), "retained snapshot DAG");
    {
        store::Container::WriteTransaction corruption(store.container());
        store.container().Exec("UPDATE blob SET data = X'00' WHERE mime = 'application/vnd.uzpainter.plane-chunk'");
        Check(!evaluator::ProceduralInputsAvailable(*retainedDag, evaluation.procedurals.get()),
              "retained DAG refuses corrupted authoritative plane");
        Check(!evaluator::LoadReadout(*evaluator::PersistentResults(), *retainedDag, nullptr, nullptr,
                                      evaluation.procedurals.get()),
              "persistent readout rechecks corrupted retained snapshot inputs");
        Check(!cpu.Evaluate(project, evaluation), "hot cache refuses corrupted plane");
        Check(!reopenedCpu.Evaluate(project, evaluation), "persistent cache refuses corrupted plane");
    }
    auto other = store::ProjectStore::Open(path.parent_path() / "foreign.uzp");
    Check(other.store->project_uuid() != store.project_uuid(), "foreign project has distinct UUID");
    auto foreignRequest = evaluation;
    foreignRequest.procedurals = std::make_shared<procedural::SnapshotSourceProvider>(*other.store, project);
    Check(!cpu.Evaluate(project, foreignRequest), "warm cache refuses copied metadata in foreign store");
    other.store->Close();
    auto missing = project;
    missing.extra.erase(std::string(store::kSnapshotsKey));
    Check(!cpu.Evaluate(missing, evaluation), "warm cache refuses absent snapshot");
    auto absentProvider = evaluation;
    absentProvider.procedurals.reset();
    Check(!cpu.Evaluate(project, absentProvider), "warm cache requires provider");
    auto unrelated = missing;
    unrelated.display.environment.rotation = 45;
    procedural::SnapshotSourceProvider missingProvider(store, unrelated);
    Check(!evaluator::FirstNewGap(missing, unrelated, {}, &missingProvider),
          "unrelated edit preserves preexisting missing snapshot gap");
    auto wrong = project;
    wrong.settings.mesh_unit_scale = 2.0;
    Check(!cpu.Evaluate(wrong, evaluation), "warm cache refuses changed mesh settings");
    auto foreign = project;
    auto& entries = std::get<core::json::Object>(foreign.extra.at(std::string(store::kSnapshotsKey)).data);
    auto& entry = std::get<core::json::Object>(entries.begin()->second.data);
    entry["project_uuid"] = "00000000-0000-4000-8000-000000000000";
    Check(!cpu.Evaluate(foreign, evaluation), "warm cache refuses foreign snapshot provenance");
    {
        // Decision 361 getters: only a legitimate absence falls back; anything else is an error.
        const auto observe = [&](const core::Project& state, const core::Project& owner) {
            const auto& fill = *core::FindLayer(state, layer)->fill;
            const auto& ref = std::get<core::ProceduralSource>(fill.sources.at(core::ChannelType::User0).value).ref;
            return procedural::SnapshotSourceProvider(store, owner)
                .Observations(state, state.texture_sets.front(), core::ChannelType::User0, core::ChannelFormat::L32F,
                              fill, ref, layer, false);
        };
        const auto none = observe(missing, missing);
        Check(none && !*none, "observations: a project holding no snapshots is a legitimate absence");
        Check(!observe(missing, project), "observations: snapshots missing on one side are an error");
        Check(!observe(foreign, foreign), "observations: a foreign entry is an error, never an absence");
        const auto present = observe(project, project);
        Check(present && !*present, "observations: a snapshot recorded without metadata is a legitimate absence");
    }
    for (int scenario = 0; scenario < 8; ++scenario) {
        const auto before = document.revision();
        auto refused = submit([&](core::Edit& edit) {
            auto& set = edit.project().texture_sets.front();
            auto& fill = *core::FindLayer(edit.project(), layer)->fill;
            auto& ref = std::get<core::ProceduralSource>(fill.sources.at(core::ChannelType::User0).value).ref;
            if (scenario == 0) set.resolution = {256, 256, {}};
            if (scenario == 1) ref.params["amount"] = 0.75;
            if (scenario == 2) ref.output_mapping["User0"] = "other";
            if (scenario == 3) fill.projection.uv.filtering_mode = core::FilteringMode::Nearest;
            if (scenario == 4) edit.project().mesh->resource = std::string(64, 'a');
            if (scenario == 5) ref.params["$randomseed"] = seed == 7 ? int64_t{8} : int64_t{7};
            if (scenario == 6) ref.params["$randomseed"] = 7.0;
            if (scenario == 7) ref.params["$randomseed"] = true;
            procedural::SnapshotSourceProvider provider(store, edit.project());
            evaluator::RequireSupported(edit.base(), edit.project(), {}, &provider);
        });
        Check(refused.result && refused.result->status != core::ResultStatus::committed &&
                  document.revision() == before, "unsupported edit is atomic");
    }
    auto alternateRequest = request;
    alternateRequest.params["amount"] = 0.625;
    std::string alternateBytes = bytes;
    for (size_t i = 0; i < 128 * 128; ++i) {
        const uint32_t bits = 0x3E000000u + static_cast<uint32_t>((i * 65537) & 0x7FFFFF);
        std::memcpy(alternateBytes.data() + i * 4, &bits, 4);
    }
    auto alternate = submit([&](core::Edit& edit) {
        procedural::RecordSnapshot(store, edit, alternateRequest, alternateBytes,
                                   AuthoredObservations());
    });
    Check(alternate.result && alternate.result->status == core::ResultStatus::committed,
          "record editable synthetic plane after refusal checks");
    const auto alternateBackend = procedural::SnapshotBackend::Load(store, *document.snapshot().project);
    Check(bool(alternateBackend), "reload editable snapshot backend");
    const auto alternateStored = alternateBackend->Stored(alternateRequest);
    Check(alternateStored && (*alternateStored)->bytes == alternateBytes,
          "alternate snapshot serves authored bytes exactly before compositing");
    std::ofstream alternateExpected(path.parent_path() / "snapshot-alternate.raw", std::ios::binary);
    alternateExpected.write(alternateBytes.data(), static_cast<std::streamsize>(alternateBytes.size()));
    store.Save(document);
    store.Close();
    std::ofstream expected(path.parent_path() / "snapshot-expected.raw", std::ios::binary);
    expected.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    const auto bundle = path.parent_path() / "snapshot-bundle";
    store::ExportBundle(path, bundle);
    store::ImportBundle(bundle, path.parent_path() / "snapshot-imported.uzp");
    std::cout << "snapshot source: exact CPU readout, warm cache refusals, atomic edits, save and bundle passed\n";
    return 0;
}

// Stores one fill layer whose content effects are a generator and a filter with authored
// procedural references, and a generator without one: the Python get_source() fixture
// (synthetic pins, not Painter evidence; neither effect can be inserted through the API yet).
int RunProceduralEffects(const std::filesystem::path& path, bool observation) {
    using namespace uzp;
    // `observation`: the same layout with every procedural reference pinned in the reserved
    // observation family (decision 362) and no observation namespace, so nothing binds them.
    const auto pin = [&](const char* asset, char digit) {
        return observation ? "uzasset://observation/" + std::string(64, digit) + "@1" : std::string(asset);
    };
    auto opened = store::ProjectStore::Open(path);
    Check(opened.report.ok(), "initial project integrity");
    core::Document document(std::move(opened.state));
    opened.store->Attach(document);
    auto& store = *opened.store;
    const core::Blending normal{core::BlendingMode::Normal, 1.0, {}};
    const auto effect = [&](core::Edit& edit, core::EffectKind kind, std::string name) {
        core::Effect e;
        e.uid = edit.AllocateId();
        e.kind = kind;
        e.name = std::move(name);
        e.blending[core::ChannelType::BaseColor] = normal;
        e.active_channels = {core::ChannelType::BaseColor};
        return e;
    };
    auto stored = store.Submit(document, {"procedural-effects-test", core::json::Object{}, "procedural-effects-1",
                                          document.revision()}, [&](core::Edit& edit) {
        auto& stack = edit.project().texture_sets.front().stacks.front();
        core::Layer host;
        host.uid = edit.AllocateId();
        host.name = "procedural host";
        host.kind = core::LayerKind::fill;
        host.blending[core::ChannelType::BaseColor] = normal;
        host.fill.emplace();
        host.fill->active_channels = {core::ChannelType::BaseColor};
        if (observation) {
            core::ProceduralSource source;
            source.ref.asset = pin("", 'c');
            source.ref.params = {{"amount", 0.5}};
            source.ref.output_mapping = {{"BaseColor", "output"}};
            host.fill->sources[core::ChannelType::BaseColor] = core::Source{source};
        } else {
            host.fill->sources[core::ChannelType::BaseColor] =
                core::Source{core::UniformColorSource{{0.5, 0.5, 0.5}, "sRGB", {}}};
        }
        core::Effect generator = effect(edit, core::EffectKind::generator, "authored generator");
        generator.procedural.emplace();
        generator.procedural->asset = pin("uzasset://test-generator/ridge@2", 'a');
        generator.procedural->params = {{"amount", 0.25}, {"$randomseed", std::int64_t{3}}, {"label", std::string("a")}};
        generator.procedural->output_mapping = {{"BaseColor", "mask"}};
        generator.procedural->resolution_override =
            core::ProceduralResolutionOverride{core::ProceduralResolutionMode::Manual, {256, 256}, 0, {}};
        core::Effect filter = effect(edit, core::EffectKind::filter, "authored filter");
        filter.procedural.emplace();
        filter.procedural->asset = pin("uzasset://test-filter/blur@1", 'b');
        filter.procedural->params = {{"radius", 2.0}};
        filter.procedural->output_mapping = {{"BaseColor", "output"}};
        host.content_effects = {generator, filter, effect(edit, core::EffectKind::generator, "empty generator")};
        stack.root_layers.insert(stack.root_layers.begin(), std::move(host));
    });
    Check(stored.result && stored.result->status == core::ResultStatus::committed, "store procedural effects");
    store.Save(document);
    store.Close();
    std::cout << "procedural effects stored\n";
    return 0;
}

/// The import payload and base schemas (decision 362, phase3.1 item 2.6h; wire schema agreed with
/// the Python preflight, tools/parity/filter_observation_import.py).
constexpr std::string_view kImportSchema = "uzpainter/filter-observation-import/2";
constexpr std::string_view kBaseSchema = "uzpainter/filter-observation-base/1";
constexpr std::string_view kRecipeSchema = "uzpainter/filter-observation-recipe/1";

namespace observation_import {

namespace json = uzp::core::json;

[[noreturn]] void Refuse(const std::string& what) { throw uzp::core::ValueError("observation import: " + what); }

const json::Object& Closed(const json::Value& value, const std::string& path, std::initializer_list<std::string_view> members) {
    const auto* object = std::get_if<json::Object>(&value.data);
    if (object == nullptr) Refuse(path + " is not an object");
    for (const auto& [name, _] : *object) {
        if (std::find(members.begin(), members.end(), name) == members.end()) Refuse(path + " has an unknown member " + name);
    }
    for (const std::string_view name : members) {
        if (!object->contains(name)) Refuse(path + " lacks " + std::string(name));
    }
    return *object;
}

const json::Value& At(const json::Object& object, std::string_view name) { return object.find(name)->second; }

const std::string& Text(const json::Object& object, std::string_view name, const std::string& path) {
    const auto* text = std::get_if<std::string>(&At(object, name).data);
    if (text == nullptr || text->empty()) Refuse(path + "." + std::string(name) + " is not a nonempty string");
    return *text;
}

bool Typed(const json::Value& a, const json::Value& b) { return json::WriteCanonical(a) == json::WriteCanonical(b); }

std::string Hash(const json::Value& value) { return uzp::core::Sha256Hex(json::WriteCanonical(value)); }

/// ProjectToJson of `project` without the observation namespace.
json::Value Projection(const uzp::core::Project& project) {
    json::Value manifest = uzp::core::ProjectToJson(project);
    std::get<json::Object>(manifest.data).erase(std::string(uzp::store::kFilterObservationsKey));
    return manifest;
}

void Parameters(const json::Value& value, const std::string& path) {
    const auto* map = std::get_if<json::Object>(&value.data);
    if (map == nullptr) Refuse(path + " is not an object");
    for (const auto& [name, parameter] : *map) {
        const auto* number = std::get_if<double>(&parameter.data);
        if (!(parameter.IsInt() || parameter.IsString() || (number != nullptr && std::isfinite(*number)))) {
            Refuse(path + "." + name + " is not an int64, finite double or string");
        }
    }
}

void ResourceId(const json::Value& value, const std::string& path) {
    const json::Object& id = Closed(value, path, {"url", "context", "name", "version"});
    for (const char* part : {"url", "context", "name", "version"}) Text(id, part, path);
}

void Observation(const json::Value& value, const std::string& path) {
    const auto* block = std::get_if<json::Object>(&value.data);
    if (block == nullptr) Refuse(path + " is not an object");
    for (const auto& [name, observed] : *block) {
        if (name == "parameters") {
            Parameters(observed, path + ".parameters");
        } else if (name == "resource_id") {
            ResourceId(observed, path + ".resource_id");
        } else if (name == "image_outputs") {
            const auto* outputs = std::get_if<json::Array>(&observed.data);
            if (outputs == nullptr) Refuse(path + ".image_outputs is not an array");
            std::set<std::string> seen;
            for (const json::Value& output : *outputs) {
                const auto* text = std::get_if<std::string>(&output.data);
                if (text == nullptr || text->empty() || !seen.insert(*text).second) {
                    Refuse(path + ".image_outputs is not distinct nonempty strings");
                }
            }
        } else {
            Refuse(path + " has an unknown member " + name);
        }
    }
}

/// Everything the payload must satisfy before any mutation (closed members, codecs, recomputed
/// recipe hash, capture and readback pairing, descriptor agreement, canonical host and Filter).
struct Checked {
    json::Object hostDescriptor, filterDescriptor;
    std::string hostKey, filterKey;
    uzp::core::Layer host;
    json::Value observations;
};

Checked Preflight(const json::Value& payload) {
    const json::Object& top = Closed(payload, "payload", {"schema", "target", "recipe", "host_state", "filter_state",
                                                          "descriptors", "expected_projection", "capture", "readbacks"});
    if (Text(top, "schema", "payload") != kImportSchema) Refuse("payload.schema is not " + std::string(kImportSchema));
    const json::Object& target = Closed(At(top, "target"), "target",
                                        {"project_uuid", "texture_set", "stack", "preimport_projection_sha256", "mesh"});
    Text(target, "project_uuid", "target");
    Text(target, "preimport_projection_sha256", "target");
    if (!At(target, "texture_set").IsInt() || !At(target, "stack").IsInt()) Refuse("target texture_set/stack are not ids");
    const json::Object& mesh = Closed(At(target, "mesh"), "target.mesh", {"sha256", "size_bytes", "mime"});
    Text(mesh, "sha256", "target.mesh");
    Text(mesh, "mime", "target.mesh");
    if (!At(mesh, "size_bytes").IsInt()) Refuse("target.mesh.size_bytes is not an integer");

    const json::Object& recipe = Closed(At(top, "recipe"), "recipe", {"sha256", "body"});
    const json::Object& body =
        Closed(At(recipe, "body"), "recipe.body", {"schema", "instruction_sequence", "applied_settings", "inputs"});
    if (Text(body, "schema", "recipe.body") != kRecipeSchema) Refuse("recipe.body.schema is not " + std::string(kRecipeSchema));
    if (!At(body, "instruction_sequence").IsObject()) Refuse("recipe.body.instruction_sequence is not an object");
    if (!At(body, "inputs").IsArray()) Refuse("recipe.body.inputs is not an array");
    // The recipe hash is recomputed from its canonical body, never taken as declared.
    if (Hash(At(recipe, "body")) != Text(recipe, "sha256", "recipe")) Refuse("recipe.sha256 is not the hash of recipe.body");

    const json::Object& capture = Closed(At(top, "capture"), "capture",
                                         {"recorder", "envelope_id", "painter_build_id", "recipe_sha256", "resource_query",
                                          "authored_inputs", "receipts"});
    if (Text(capture, "recipe_sha256", "capture") != Text(recipe, "sha256", "recipe")) {
        Refuse("capture.recipe_sha256 is not the recipe's hash");
    }
    if (!Typed(At(capture, "authored_inputs"), At(body, "inputs"))) Refuse("capture.authored_inputs differ from recipe.body.inputs");

    const json::Object& descriptors = Closed(At(top, "descriptors"), "descriptors", {"host", "filter"});
    Checked out;
    const auto descriptor = [&](const char* role, json::Object& into, std::string& key) {
        const std::string path = std::string("descriptors.") + role;
        const json::Object& given = Closed(At(descriptors, role), path, {"resource_id", "parameters"});
        ResourceId(At(given, "resource_id"), path + ".resource_id");
        Parameters(At(given, "parameters"), path + ".parameters");
        into = json::Object{{"schema", std::string(uzp::store::kObservationDescriptorSchema)}, {"role", std::string(role)},
                            {"resource_id", At(given, "resource_id")}, {"parameters", At(given, "parameters")}};
        key = uzp::store::ObservationKey(into);
    };
    descriptor("host", out.hostDescriptor, out.hostKey);
    descriptor("filter", out.filterDescriptor, out.filterKey);

    const json::Object& readbacks = Closed(At(top, "readbacks"), "readbacks", {"same_session", "after_save_reopen"});
    Observation(At(readbacks, "same_session"), "readbacks.same_session");
    Observation(At(readbacks, "after_save_reopen"), "readbacks.after_save_reopen");
    if (!Typed(At(readbacks, "same_session"), At(readbacks, "after_save_reopen"))) {
        Refuse("the paired readbacks differ (typed)");
    }
    out.observations = At(readbacks, "same_session");
    const auto& observed = std::get<json::Object>(out.observations.data);
    if (const auto it = observed.find("parameters"); it != observed.end() && !Typed(it->second, out.filterDescriptor.at("parameters"))) {
        Refuse("readbacks.parameters differ from descriptors.filter.parameters");
    }
    if (const auto it = observed.find("resource_id"); it != observed.end() && !Typed(it->second, out.filterDescriptor.at("resource_id"))) {
        Refuse("readbacks.resource_id differs from descriptors.filter.resource_id");
    }

    // The host Fill and its Filter exactly as the core codec reads and writes them.
    try {
        out.host = uzp::core::LayerFromJson(At(top, "host_state"), "host_state");
    } catch (const uzp::core::ManifestError& error) {
        Refuse(error.what());
    }
    if (!Typed(uzp::core::LayerToJson(out.host), At(top, "host_state"))) Refuse("host_state is not its canonical layer");
    if (out.host.content_effects.size() != 1) Refuse("host_state does not hold exactly one content effect");
    if (!Typed(uzp::core::EffectToJson(out.host.content_effects.front(), false), At(top, "filter_state"))) {
        Refuse("filter_state is not host_state.content_effects[0]");
    }
    const uzp::core::Effect& filter = out.host.content_effects.front();
    if (filter.kind != uzp::core::EffectKind::filter || !filter.procedural) Refuse("filter_state is not a procedural Filter");
    if (filter.procedural->asset != uzp::store::ObservationPin(out.filterKey)) Refuse("the Filter's asset is not its descriptor's pin");
    if (!out.host.fill || out.host.fill->sources.size() != 1) Refuse("host_state is not a Fill with one source");
    const auto* hostSource = std::get_if<uzp::core::ProceduralSource>(&out.host.fill->sources.begin()->second.value);
    if (hostSource == nullptr || hostSource->ref.asset != uzp::store::ObservationPin(out.hostKey)) {
        Refuse("the host source's asset is not its descriptor's pin");
    }
    if (!At(top, "expected_projection").IsObject()) Refuse("expected_projection is not an object");
    return out;
}

}  // namespace observation_import

/// `filter-observation-base <uzp> <out.json>` (test tooling, read-only): the project's UUID, its
/// single authoritative ProjectToJson without the observation namespace, that projection's typed
/// canonical hash and the mesh's identity, size and MIME (bytes read and hashed), written to a
/// private file; stdout gives hashes and counts only. No Submit, no new revision.
int RunFilterObservationBase(const std::filesystem::path& path, const std::filesystem::path& out) {
    using namespace uzp;
    namespace json = core::json;
    auto opened = store::ProjectStore::Open(path);
    Check(opened.report.ok(), "project integrity");
    const core::Project project = opened.state.project;
    if (!project.mesh) throw core::ValueError("observation base: the project has no mesh");
    const std::string sha = project.mesh->resource;
    const std::string bytes = opened.store->ReadResource(sha);
    const auto metadata = project.resources.find(sha);
    if (core::Sha256Hex(bytes) != sha || metadata == project.resources.end() || metadata->second.empty()) {
        throw core::ValueError("observation base: the mesh resource bytes or metadata do not verify");
    }
    // Every metadata record of the mesh names a nonempty MIME and the actual byte size, all alike.
    const core::ResourceMeta& first = metadata->second.front();
    for (const core::ResourceMeta& record : metadata->second) {
        if (record.mime.empty() || record.mime != first.mime || record.size != static_cast<std::int64_t>(bytes.size())) {
            throw core::ValueError("observation base: the mesh metadata does not agree with its bytes");
        }
    }
    const json::Value projection = observation_import::Projection(project);
    const json::Value base = json::Object{
        {"schema", std::string(kBaseSchema)},
        {"project_uuid", opened.store->project_uuid()},
        {"projection", projection},
        {"projection_sha256", observation_import::Hash(projection)},
        {"mesh", json::Object{{"sha256", sha}, {"size_bytes", static_cast<std::int64_t>(bytes.size())},
                              {"mime", metadata->second.front().mime}}}};
    opened.store->Close();
    // Success only once the whole file is written, flushed and closed.
    std::ofstream file(out, std::ios::binary);
    file << json::WriteCanonical(base);
    file.flush();
    file.close();
    if (!file) {
        std::cout << "observation base refused: cannot write " << out.filename().string() << '\n';
        return 1;
    }
    std::cout << "observation base: projection " << observation_import::Hash(projection).substr(0, 16) << ", mesh "
              << bytes.size() << " bytes\n";
    return 0;
}

/// `filter-observation-import <uzp> <payload.json>` (test tooling; a product importer stays a
/// separate reviewed design): the closed payload is checked first (`Preflight`); then ONE store
/// Submit revalidates the base (authoritative UUID, the pre-import projection hash, the mesh bytes
/// and metadata, the target set and stack, an absent namespace), allocates the host and Filter ids
/// in the contract's order, inserts the host Fill (with its Filter) at the top of the target stack,
/// requires the prospective projection to equal `expected_projection` (typed), takes the context
/// from the provider on that working copy, and writes the entry and namespace after the structural
/// check. No Admit/CanEvaluate; nothing is defaulted or chosen.
int RunFilterObservationImport(const std::filesystem::path& path, const std::filesystem::path& payloadPath) {
    using namespace uzp;
    namespace json = core::json;
    namespace oi = observation_import;
    std::ifstream file(payloadPath, std::ios::binary);
    const std::string text((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    const json::Value payload = json::Parse(text);
    const oi::Checked checked = oi::Preflight(payload);
    const json::Object& top = std::get<json::Object>(payload.data);
    const json::Object& target = std::get<json::Object>(oi::At(top, "target").data);
    const json::Object& mesh = std::get<json::Object>(oi::At(target, "mesh").data);

    auto opened = store::ProjectStore::Open(path);
    Check(opened.report.ok(), "project integrity");
    core::Document document(std::move(opened.state));
    opened.store->Attach(document);
    auto& store = *opened.store;
    auto stored = store.Submit(document, {"filter-observation-import", json::Object{}, "filter-observation-import-1",
                                          document.revision()}, [&](core::Edit& edit) {
        core::Project& project = edit.project();
        if (store.project_uuid() != oi::Text(target, "project_uuid", "target")) oi::Refuse("target.project_uuid is another project");
        if (project.extra.contains(store::kFilterObservationsKey)) oi::Refuse("the target already holds observations");
        if (oi::Hash(oi::Projection(project)) != oi::Text(target, "preimport_projection_sha256", "target")) {
            oi::Refuse("the project is not the pre-import base");
        }
        const std::string sha = oi::Text(mesh, "sha256", "target.mesh");
        if (!project.mesh || project.mesh->resource != sha) oi::Refuse("the project's mesh is not target.mesh");
        const std::string bytes = store.ReadResource(sha);
        const auto metadata = project.resources.find(sha);
        if (core::Sha256Hex(bytes) != sha || static_cast<std::int64_t>(bytes.size()) != std::get<std::int64_t>(oi::At(mesh, "size_bytes").data) ||
            metadata == project.resources.end() || metadata->second.empty() ||
            metadata->second.front().mime != oi::Text(mesh, "mime", "target.mesh")) {
            oi::Refuse("the mesh bytes or metadata are not target.mesh");
        }
        const auto setId = static_cast<core::Id>(std::get<std::int64_t>(oi::At(target, "texture_set").data));
        const auto stackId = static_cast<core::Id>(std::get<std::int64_t>(oi::At(target, "stack").data));
        core::Stack* stack = nullptr;
        for (core::TextureSet& set : project.texture_sets) {
            if (set.id != setId) continue;
            for (core::Stack& candidate : set.stacks) {
                if (candidate.id == stackId) stack = &candidate;
            }
        }
        if (stack == nullptr) oi::Refuse("target texture_set/stack is not in the project");
        // The contract's id order: the host, then its Filter.
        core::Layer host = checked.host;
        if (edit.AllocateId() != host.uid || edit.AllocateId() != host.content_effects.front().uid) {
            oi::Refuse("the host and Filter ids are not the next ids of the base");
        }
        const core::Id hostUid = host.uid;
        const core::Id filterUid = host.content_effects.front().uid;
        const core::ProceduralRef hostRef =
            std::get<core::ProceduralSource>(host.fill->sources.begin()->second.value).ref;
        const core::ProceduralRef filterRef = *host.content_effects.front().procedural;
        const std::string channel(core::ToString(host.fill->sources.begin()->first));
        stack->root_layers.insert(stack->root_layers.begin(), std::move(host));
        if (!oi::Typed(oi::Projection(project), oi::At(top, "expected_projection"))) {
            oi::Refuse("the prospective project is not expected_projection");
        }
        const std::expected<json::Object, std::string> context = procedural::CurrentFilterObservationContext(store, project);
        if (!context) oi::Refuse(context.error());
        json::Object entry{
            {"schema", std::string(store::kObservationEntrySchema)},
            {"project_uuid", store.project_uuid()},
            {"role", std::string("filter")},
            {"host_descriptor", checked.hostKey},
            {"filter_descriptor", checked.filterKey},
            {"binding", json::Object{{"texture_set", static_cast<std::int64_t>(setId)}, {"stack", static_cast<std::int64_t>(stackId)},
                                     {"host_uid", static_cast<std::int64_t>(hostUid)},
                                     {"filter_uid", static_cast<std::int64_t>(filterUid)},
                                     {"node_stack", std::string("Content")}, {"effect_index", 0},
                                     {"host_channel", channel},
                                     {"host_reference", core::ProceduralRefToJson(hostRef)},
                                     {"filter_reference", core::ProceduralRefToJson(filterRef)}}},
            {"context", *context},
            {"context_sha256", store::ObservationKey(*context)},
            {"capture", oi::At(top, "capture")},
            {"observations", checked.observations}};
        const std::string entryKey = store::ObservationKey(entry);
        const json::Value space = json::Object{
            {"schema", std::string(store::kFilterObservationsSchema)},
            {"descriptors", json::Object{{checked.hostKey, checked.hostDescriptor}, {checked.filterKey, checked.filterDescriptor}}},
            {"entries", json::Object{{entryKey, entry}}},
            {"host_bindings", json::Object{{std::to_string(hostUid),
                                            json::Object{{"channel", channel}, {"descriptor", checked.hostKey}}}}},
            {"bindings", json::Object{{std::to_string(filterUid), entryKey}}}};
        if (const std::string problem = store::FilterObservationsProblem(space, store.project_uuid()); !problem.empty()) {
            oi::Refuse(problem);
        }
        project.extra[std::string(store::kFilterObservationsKey)] = space;
        // The shared authoritative lookup on the prospective project before the commit: it also
        // compares the references' parameters by value with the descriptors', which the structural
        // check and the context do not, so no immediately unusable observation commits.
        const std::expected<procedural::FilterObservation, std::string> usable =
            procedural::ObservedFilter(store, project, filterUid);
        if (!usable) oi::Refuse("the imported observation does not resolve: " + usable.error());
        if (usable->entry_key != entryKey) oi::Refuse("the imported observation resolves to another entry");
    });
    if (!(stored.result && stored.result->status == core::ResultStatus::committed)) {
        std::cout << "observation import refused: " << (stored.result ? stored.result->error : std::string("no result")) << "\n";
        store.Close();
        return 1;
    }
    store.Save(document);
    store.Close();
    std::cout << "observation import committed: entry 1, descriptors 2\n";
    return 0;
}

/// The `assets bind-snapshot` fixture: two authored synthetic snapshots of one asset (toggle
/// `flag` 0 and 1; the first with recorded `/3` metadata: outputs, typed parameters and an
/// authored observed ResourceID; the second without, as a legacy entry),
/// nothing bound, and a bottom fill layer `effect host` holding a content fill effect and a mask
/// fill effect (the refused targets). The positive target and the channels are created by the
/// test through the public API. Prints one `BIND_FIXTURE:` JSON line with the hashes and uids.
/// Test values only; no Painter data.
int RunSnapshotBindFixture(const std::filesystem::path& path) {
    using namespace uzp;
    auto opened = store::ProjectStore::Open(path);
    Check(opened.report.ok(), "initial project integrity");
    core::Document document(std::move(opened.state));
    opened.store->Attach(document);
    auto& store = *opened.store;
    int key = 0;
    const auto submit = [&](const std::function<void(core::Edit&)>& call) {
        const auto id = "snapshot-bind-fixture-" + std::to_string(++key);
        auto outcome = store.Submit(document, {"snapshot-bind-fixture", core::json::Object{}, id, document.revision()}, call);
        if (!outcome.result || outcome.result->status != core::ResultStatus::committed) {
            throw std::runtime_error("fixture transaction " + id + ": " +
                                     (outcome.result ? core::json::WriteCanonical(outcome.result->ToJson()) : "no result"));
        }
    };
    core::json::Object hashes;
    // An authored resource URL (not a Painter resource): the snapshot pin names its SHA-256.
    const std::string url = "resource://authored_shelf/authored_noise?version=authored-1";
    for (const int64_t flag : {0, 1}) {
        procedural::ProceduralRequest request;
        request.asset = core::ParseAssetUrl("uzasset://snapshot/" + core::Sha256Hex(url) + "@1");
        // `scale` is an integral float: the signature encodes it as 2, the typed map keeps 2.0.
        request.params = {{"amount", 0.5}, {"flag", flag}, {"scale", 2.0}};
        request.meshClass = "quad";
        request.outputId = "scalar";
        request.output = {128, procedural::ChannelFormat::F32, "raw", 1};
        request.settings = procedural::EvaluationSettings(*document.snapshot().project);
        std::string bytes(128 * 128 * 4, '\0');
        for (size_t i = 0; i < 128 * 128; ++i) {
            const float value = static_cast<float>(flag) * 0.5f + static_cast<float>(i % 128) / 256.0f;
            std::memcpy(bytes.data() + i * 4, &value, 4);
        }
        std::optional<store::SourceMetadata> metadata;
        // flag 0: schema /3 with typed parameters and an authored observed ResourceID; flag 1: none.
        if (flag == 0) {
            metadata = store::SourceMetadata{
                {"scalar", "aux"}, std::nullopt, std::nullopt, std::nullopt,
                core::json::Object{{"amount", 0.5}, {"flag", flag}, {"scale", 2.0}},
                store::ObservedResourceId{url, "authored_shelf", "authored_noise", "authored-1"}};
        }
        submit([&](core::Edit& edit) { procedural::RecordSnapshot(store, edit, request, bytes, metadata); });
        hashes["flag" + std::to_string(flag)] = procedural::SignatureHash(request);
    }
    core::Id host = 0, content = 0, mask = 0;
    submit([&](core::Edit& edit) {
        auto& stack = edit.project().texture_sets.front().stacks.front();
        core::Layer hostLayer;
        hostLayer.uid = host = edit.AllocateId();
        hostLayer.name = "effect host";
        hostLayer.kind = core::LayerKind::fill;
        hostLayer.fill.emplace();
        core::Effect contentEffect;
        contentEffect.uid = content = edit.AllocateId();
        contentEffect.name = "content fill";
        contentEffect.fill.emplace();
        contentEffect.fill->active_channels = {core::ChannelType::User0};
        hostLayer.content_effects.push_back(std::move(contentEffect));
        core::Effect maskEffect;
        maskEffect.uid = mask = edit.AllocateId();
        maskEffect.name = "mask fill";
        maskEffect.fill.emplace();
        maskEffect.mono_blending.emplace();
        hostLayer.mask.emplace();
        hostLayer.mask->effects.push_back(std::move(maskEffect));
        stack.root_layers.push_back(std::move(hostLayer));
    });
    store.Save(document);
    store.Close();
    const core::json::Object report{{"signatures", std::move(hashes)}, {"host", static_cast<int64_t>(host)},
                                    {"content_effect", static_cast<int64_t>(content)},
                                    {"mask_effect", static_cast<int64_t>(mask)}};
    std::cout << "BIND_FIXTURE:" << core::json::WriteCanonical(report) << "\n";
    return 0;
}
