#include <bit>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <optional>
#include <stdexcept>

#include "evaluator/evaluator.h"
#include "evaluator/profile.h"
#include "evaluator/result_cache.h"
#include "evaluator/support.h"
#include "procedural/admission.h"
#include "procedural/snapshot_backend.h"
#include "procedural/snapshot_source.h"
#include "store/bundle.h"
#include "render/disk_cache.h"
#include "store/snapshots.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/sha256.h"

namespace {
void Check(bool okay, const char* message) {
    if (!okay) throw std::runtime_error(message);
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
