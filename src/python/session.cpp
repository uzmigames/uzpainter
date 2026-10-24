// The open project and the mutation contract of the `uzpainter` module (session.h).

#include "python/session.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <chrono>
#include <ctime>
#include <fstream>
#include <iterator>
#include <map>
#include <mutex>
#include <random>
#include <system_error>
#include <utility>

#include "bake/baking_project.h"
#include "evaluator/dag.h"
#include "evaluator/profile.h"
#include "evaluator/sources.h"
#include "evaluator/support.h"
#include "evaluator/templates.h"
#include "mesh/mesh_import.h"
#include "procedural/snapshot_source.h"
#include "mesh/reload.h"
#include "python/display.h"
#include "python/errors.h"
#include "python/evaluation.h"
#include "python/recipe.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/validation.h"

namespace uzp::python {

namespace {

/// The native `Transaction` of a thread: the core transaction, the edit context of its working
/// copy (alive until the transaction ends) and the project it belongs to.
struct ThreadState {
    std::unique_ptr<core::Transaction> transaction;
    core::Edit* edit = nullptr;
    std::shared_ptr<OpenProject> project;
    std::int64_t base_revision = 0;
    std::optional<CallResult> last;
    std::optional<ScriptLog> log;
    core::Snapshot committed_base;
    std::vector<TextureInvalidation> texture_invalidations;
};

ThreadState& Thread() {
    thread_local ThreadState state;
    return state;
}

std::vector<TextureInvalidation> SourceInvalidation(const std::string& tool, const core::json::Object& args) {
    if (tool != "layerstack.FillLayerNode.set_source" && tool != "source.SourceUniformColor.set_color" &&
        tool != "source.SourceSubstance.set_parameters" && tool != "source.SourceSubstance.active_output" &&
        tool != "source.SourceSubstance.resolution" && tool != "source_set") return {};
    const auto node = args.find(tool == "source_set" ? "uid" : "node");
    if (node == args.end() || !node->second.IsInt()) return {};
    TextureInvalidation target;
    target.node = static_cast<core::Id>(std::get<std::int64_t>(node->second.data));
    if (const auto channel = args.find("channel"); channel != args.end() && !channel->second.IsNull()) {
        if (!channel->second.IsString()) return {};
        target.channel = core::FromString<core::ChannelType>(std::get<std::string>(channel->second.data));
        if (!target.channel) return {};
    }
    return {target};
}

void TextureDependencies(const evaluator::DagList& list, std::vector<core::Id>& out) {
    for (const evaluator::DagLayer& layer : list.layers) {
        out.push_back(layer.uid);
        for (const evaluator::DagEffect& effect : layer.effects) out.push_back(effect.uid);
        if (layer.maskStack) {
            for (const evaluator::DagEffect& effect : layer.maskStack->effects) out.push_back(effect.uid);
        }
        if (layer.group) TextureDependencies(*layer.group, out);
    }
}

// Channel metadata need not have an evaluator base until visible content uses it.
// Unknown or malformed content stays eligible so BuildDag reports its real error.
bool MayHaveTextureContent(const core::Stack& stack, const core::Layer& layer,
                           core::ChannelType channel, std::vector<core::Id> path = {}) {
    if (!layer.visible || evaluator::EffectiveBlending(layer, channel).mode == core::BlendingMode::Disable) {
        return false;
    }
    if (std::find(path.begin(), path.end(), layer.uid) != path.end()) return true;
    path.push_back(layer.uid);
    switch (layer.kind) {
        case core::LayerKind::fill:
            return !layer.fill || layer.fill->source_mode == core::SourceMode::Material ||
                   (layer.fill->active_channels.contains(channel) && layer.fill->sources.contains(channel));
        case core::LayerKind::group:
            return !layer.content_effects.empty() ||
                   std::any_of(layer.children.begin(), layer.children.end(), [&](const core::Layer& child) {
                       return MayHaveTextureContent(stack, child, channel, path);
                   });
        case core::LayerKind::instance: {
            const core::Layer* source = core::FindLayer(stack, layer.instance_source);
            return source == nullptr || MayHaveTextureContent(stack, *source, channel, path);
        }
        case core::LayerKind::paint:  // an empty paint layer is transparent (decision 348)
            return !core::IsEmptyPaintLayer(layer);
    }
    return true;
}

/// The support check's reader of PNG headers (evaluator/support.h `BitmapShapes`, decision 240):
/// the bytes `store` holds or has staged for the running transaction. A resource's shape is read
/// once per process: its bytes are content-addressed, so a shape read is never stale. Bytes the
/// store cannot give are left to the evaluation.
evaluator::BitmapShapes ShapesOf(store::ProjectStore& store) {
    return [&store](std::string_view sha256) -> std::optional<evaluator::BitmapShape> {
        static std::mutex mutex;
        static std::map<std::string, evaluator::BitmapShape, std::less<>> shapes;
        {
            std::lock_guard lock(mutex);
            if (const auto it = shapes.find(sha256); it != shapes.end()) return it->second;
        }
        std::optional<evaluator::BitmapShape> shape;
        try {
            shape = evaluator::BitmapShapeOf(store.ReadResource(sha256));
        } catch (const store::StoreError&) {
            return std::nullopt;
        }
        if (shape) {
            std::lock_guard lock(mutex);
            shapes.emplace(std::string(sha256), *shape);
        }
        return shape;
    };
}

std::string RandomHex(std::size_t bytes) {
    thread_local std::mt19937_64 engine{[] {
        std::random_device device;
        std::seed_seq seed{device(), device(), device(), device(),
                           static_cast<unsigned>(std::chrono::steady_clock::now().time_since_epoch().count())};
        return std::mt19937_64(seed);
    }()};
    static constexpr char kDigits[] = "0123456789abcdef";
    std::string out;
    while (out.size() < bytes * 2) {
        std::uint64_t value = engine();
        for (int i = 0; i < 16 && out.size() < bytes * 2; ++i, value >>= 4) out.push_back(kDigits[value & 15]);
    }
    return out;
}

/// A random version-4 UUID.
std::string NewUuid() {
    std::string hex = RandomHex(16);
    hex[12] = '4';
    hex[16] = "89ab"[std::stoi(hex.substr(16, 1), nullptr, 16) & 3];
    return hex.substr(0, 8) + "-" + hex.substr(8, 4) + "-" + hex.substr(12, 4) + "-" + hex.substr(16, 4) + "-" +
           hex.substr(20, 12);
}

std::string ReadFile(const std::filesystem::path& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) ThrowProjectError("cannot read " + Utf8(path));
    return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}

CallResult FromResult(const core::TransactionResult& result) {
    return {std::string(core::ToString(result.status)), result.revision, result.changes, result.returned};
}

/// The result of a submitted request: the committed or no-op result, or the error it raises.
core::TransactionResult Settle(const core::RequestOutcome& outcome, const std::exception_ptr& error) {
    switch (outcome.decision.admission) {
        case core::Admission::execute:
            break;
        case core::Admission::stale_revision:
            ThrowStale(outcome.decision.expected_revision.value_or(0), outcome.decision.current_revision);
        default:
            throw ApiError("RuntimeError", "the call was not executed (" +
                                               std::string(core::ToString(outcome.decision.admission)) + ")");
    }
    const core::TransactionResult& result = *outcome.result;
    if (result.status == core::ResultStatus::failed) RaiseFailed(result, error);
    return result;
}

void SetActiveDefault(OpenProject& project) {
    const core::Snapshot snapshot = project.document->snapshot();
    for (const core::TextureSet& set : snapshot.project->texture_sets) {
        if (set.stacks.empty()) continue;
        project.active_set = set.id;
        project.active_stack = set.stacks.front().id;
        return;
    }
}

}  // namespace

OpenProject::~OpenProject() {
    document.reset();
    store.reset();
    if (!untitled_dir.empty()) {
        std::error_code ignored;
        std::filesystem::remove_all(untitled_dir, ignored);
    }
}

std::filesystem::path PathFromUtf8(std::string_view text) { return std::u8string(text.begin(), text.end()); }

std::string Utf8(const std::filesystem::path& path) {
    const std::u8string text = path.generic_u8string();
    return {text.begin(), text.end()};
}

std::string NewKey() { return "py-" + RandomHex(16); }

std::string NowUtc() {
    const std::time_t now = std::time(nullptr);
    std::tm utc{};
    gmtime_s(&utc, &now);
    std::array<char, 32> text{};
    std::strftime(text.data(), text.size(), "%Y-%m-%dT%H:%M:%SZ", &utc);
    return text.data();
}

Session& Session::Get() {
    static Session* session = new Session();  // never destroyed: lives as long as the process
    return *session;
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────────────────────

void Session::SetCurrent(std::shared_ptr<OpenProject> project) {
    std::lock_guard lock(mutex_);
    current_ = std::move(project);
    ++generation_;
}

bool Session::IsOpen() const {
    std::lock_guard lock(mutex_);
    return current_ != nullptr;
}

std::shared_ptr<OpenProject> Session::Current() const {
    std::lock_guard lock(mutex_);
    if (!current_) ThrowProjectError("no project is open");
    return current_;
}

void Session::RequireNotBusy(const std::string& what) const {
    if (!running_job) return;
    if (const std::optional<std::string> job = running_job()) {
        ThrowBusy(*job, what + " is refused while job " + *job + " is running");
    }
}

void CheckCreateSettings(const CreateSettings& settings) {
    if (settings.workflow && *settings.workflow != core::ProjectWorkflow::Default) {
        ThrowNotYetSupported("project workflow " + std::string(core::ToString(*settings.workflow)) +
                             " is a release gap: the UV-tile workflow (phase4.5_uv-tiles)");
    }
    if (settings.ocio_config_hash && *settings.ocio_config_hash != evaluator::kPainterOcioConfigSha256) {
        ThrowNotYetSupported("an OCIO project with the configuration " + *settings.ocio_config_hash +
                             ": only Painter's substance config (" + std::string(evaluator::kPainterOcioConfigSha256) +
                             ") is a pinned colour profile (decisions 190, 202 and 207)");
    }
}

void Session::SetAdmissionLimits(std::optional<evaluator::AdmissionLimits> limits) {
    std::lock_guard lock(admission_mutex_);
    admission_limits_ = limits;
}

void Session::RequireAdmission(const core::Project& project) const {
    std::optional<evaluator::AdmissionLimits> limits;
    {
        std::lock_guard lock(admission_mutex_);
        limits = admission_limits_;
    }
    if (!limits) return;
    for (const auto& set : project.texture_sets) {
        const auto admitted = evaluator::CheckTextureSet(*limits, set);
        if (!admitted) throw ApiError("RuntimeError", admitted.error().Describe());
    }
}

core::TransactionResult Session::Create(const std::filesystem::path& mesh_path, const CreateSettings& settings,
                                        const CreateCall& call) {
    if (IsOpen()) ThrowProjectError("a project is already open");
    CheckCreateSettings(settings);
    const std::string bytes = ReadFile(mesh_path);
    mesh::ImportSettings import;
    import.mesh_unit_scale = settings.mesh_unit_scale;
    const mesh::ImportResult imported =
        mesh::ImportMesh(bytes, Utf8(mesh_path.filename()), import, mesh_path.parent_path());

    const evaluator::TemplateLibrary templates =
        evaluator::TemplateLibrary::Load(evaluator::TemplateLibrary::DefaultDirectory());
    const std::string template_id = settings.template_id.value_or(std::string(evaluator::kDefaultTemplateId));
    const evaluator::ProjectTemplate* fresh = templates.Find(template_id);
    if (fresh == nullptr || fresh->channelDefaults) {
        std::string known;
        for (const std::string& id : templates.Ids()) {
            if (id != evaluator::kChannelDefaultsId) known += (known.empty() ? "" : ", ") + id;
        }
        throw ApiError("ValueError", "no project template '" + template_id + "' is installed (" + known + ")");
    }

    core::DocumentState state;
    state.project_uuid = NewUuid();
    core::Project& p = state.project;
    p.versions.app_version = kAppVersion;
    p.versions.evaluator_profile = std::string(evaluator::kCurrentProfile);
    if (settings.normal_map_format) p.settings.normal_map_format = *settings.normal_map_format;
    if (settings.tangent_space) p.settings.tangent_space = *settings.tangent_space;
    // The settings' resolution overrides the template's, as Painter's settings override the
    // template parameters.
    if (const std::optional<int> size =
            settings.default_texture_resolution ? settings.default_texture_resolution : fresh->defaultResolution) {
        p.settings.default_resolution.width = *size;
        p.settings.default_resolution.height = *size;
    }
    if (settings.mesh_unit_scale) p.settings.mesh_unit_scale = *settings.mesh_unit_scale;
    if (settings.import_cameras) p.settings.import_cameras = *settings.import_cameras;
    if (settings.ocio_config_hash) {
        p.settings.color_management.mode = "ocio";
        p.settings.color_management.config_hash = *settings.ocio_config_hash;
    }
    p.settings.template_id = template_id;
    display::InitialiseNewProject(p);
    core::Validate(p);

    // All imported sets start with this resolution and these channels. Refuse the ordinary
    // creation before making an untitled store; the optional extra edit is checked again below.
    core::Project admission = p;
    core::TextureSet admission_set;
    admission_set.resolution = p.settings.default_resolution;
    core::Stack admission_stack;
    admission_stack.channels = fresh->StackChannels();
    admission_set.stacks.push_back(std::move(admission_stack));
    admission.texture_sets.push_back(std::move(admission_set));
    if (!call.extra) RequireAdmission(admission);

    auto project = std::make_shared<OpenProject>();
    project->untitled_dir = std::filesystem::temp_directory_path() / "UzPainter" / ("untitled-" + RandomHex(8));
    std::filesystem::create_directories(project->untitled_dir);
    project->mesh_path = Utf8(mesh_path);
    const std::string mesh_source = Utf8(std::filesystem::absolute(mesh_path));
    project->store = store::ProjectStore::Create(project->untitled_dir / "Untitled.uzp", state);
    project->document = std::make_unique<core::Document>(std::move(state));
    project->store->Attach(*project->document);

    store::ProjectStore& store = *project->store;
    const std::map<core::ChannelType, core::Channel> channels = fresh->StackChannels();
    core::MutationRequest request =
        call.request ? *call.request
                     : core::MutationRequest{"project.create",
                                             core::json::Object{{"mesh", Utf8(mesh_path.filename())},
                                                                {"mesh_sha256", imported.sha256}},
                                             NewKey(), project->document->revision()};
    std::exception_ptr error;
    const core::RequestOutcome outcome = store.Submit(*project->document, request, [&](core::Edit& edit) {
        try {
            store.StageResource(bytes, std::string(mesh::MimeOf(imported.format)));
            for (const mesh::ExternalFile& file : imported.external_files) {
                store.StageResource(file.bytes, std::string(mesh::kExternalFileMime));
            }
            mesh::CreateTextureSets(edit, imported, mesh::MeshSource{mesh_source, NowUtc()}, channels);
            bake::InitializeBakingSettings(edit.project());
            // Painter's new stack holds one empty paint layer, "Layer 1", at its bottom (every
            // structure readback of the Tier 0 api-probes, both recordings; decisions 105, 348).
            std::vector<core::InsertPosition> stacks;
            for (const core::TextureSet& set : edit.project().texture_sets) {
                for (const core::Stack& stack : set.stacks) stacks.push_back(core::InsertPosition::FromStack(set.id, stack.id));
            }
            for (const core::InsertPosition& position : stacks) edit.Insert(position, core::NodeType::PaintLayer, "Layer 1");
            if (call.extra) call.extra(edit, store);
            RequireAdmission(edit.project());
        } catch (...) {
            error = std::current_exception();
            throw;
        }
    });
    core::TransactionResult result = Settle(outcome, error);
    Record(FromResult(result), {}, project);
    SetActiveDefault(*project);
    {
        std::lock_guard lock(mutex_);
        if (current_) ThrowProjectError("a project is already open");
        current_ = std::move(project);
        ++generation_;
    }
    NotifyDurableChange();
    return result;
}

void Session::Open(const std::filesystem::path& path, bool untitled) {
    if (IsOpen()) ThrowProjectError("a project is already open");
    if (!std::filesystem::exists(path)) ThrowProjectError("cannot open " + Utf8(path) + ": no such file");
    // The session never reads the integrity report: building it hashed every retained manifest on
    // every open (decision 253). `inspect --verify`, `export` and the census still build it.
    store::OpenOptions options;
    options.report = false;
    store::ProjectStore::Opened opened = store::ProjectStore::Open(path, options);
    auto project = std::make_shared<OpenProject>();
    project->store = std::move(opened.store);
    project->document = std::make_unique<core::Document>(std::move(opened.state));
    project->store->Attach(*project->document);
    const core::Snapshot snapshot = project->document->snapshot();
    if (snapshot.project->mesh) {
        const auto it = snapshot.project->resources.find(snapshot.project->mesh->resource);
        if (it != snapshot.project->resources.end() && !it->second.empty()) project->mesh_path = it->second.front().origin;
        // The current mesh's recorded source (absolute); a project written before it was recorded
        // has none, and its mesh source stays unknown rather than resolved against this directory.
        if (!snapshot.project->mesh->source.empty()) project->mesh_path = snapshot.project->mesh->source;
    }
    if (untitled) {
        project->untitled_dir = std::filesystem::absolute(path).parent_path();
    } else {
        project->project_source = std::filesystem::absolute(project->store->path());  // a bundle: its `.uzp`
    }
    SetActiveDefault(*project);
    {
        std::lock_guard lock(mutex_);
        if (current_) ThrowProjectError("a project is already open");
        current_ = std::move(project);
        ++generation_;
    }
    NotifyDurableChange();
}

void Session::Rebuild(const core::json::Value& dump, const std::filesystem::path& resources_dir) {
    if (IsOpen()) ThrowProjectError("a project is already open");
    core::Project rebuilt = core::ProjectFromRecipe(dump, HostRecipe());
    core::ForEachNode(rebuilt, [](const core::NodeVisit& visit) {
        const auto& fill = visit.layer ? visit.layer->fill : visit.effect->fill;
        if (!fill) return;
        for (const auto& [channel, source] : fill->sources) {
            (void)channel;
            if (source.kind() == core::SourceKind::procedural)
                throw core::NotYetSupported("recipe rebuild cannot transport project-private procedural snapshot planes; reopen the original project or import its bundle");
        }
    });
    RequireAdmission(rebuilt);

    std::error_code ec;
    if (!std::filesystem::is_directory(resources_dir, ec)) {
        ThrowProjectError("rebuild: " + Utf8(resources_dir) + " is not a folder of resource files");
    }
    std::map<std::string, std::filesystem::path> files;  // sha256 -> file
    for (const std::filesystem::directory_entry& entry : std::filesystem::directory_iterator(resources_dir)) {
        if (!entry.is_regular_file()) continue;
        const std::string name = Utf8(entry.path().filename());
        const std::string stem = name.substr(0, name.find('.'));
        if (core::IsSha256Hex(stem)) files[stem] = entry.path();
    }
    std::map<std::string, std::string> bytes;  // sha256 -> stored bytes
    for (auto& [hash, entries] : rebuilt.resources) {
        const auto file = files.find(hash);
        if (file == files.end()) ThrowProjectError("rebuild: the resource " + hash + " is not in " + Utf8(resources_dir));
        std::string data = ReadFile(file->second);
        if (core::Sha256Hex(data) != hash) {
            ThrowProjectError("rebuild: " + Utf8(file->second) + " does not hold the bytes of " + hash);
        }
        for (core::ResourceMeta& meta : entries) {
            if (meta.origin.empty()) meta.origin = Utf8(std::filesystem::absolute(file->second));
            if (meta.imported_at.empty()) meta.imported_at = NowUtc();
        }
        bytes[hash] = std::move(data);
    }
    // The mesh, its external files included, re-derives from what the recipe stores alone, never
    // from files beside an origin.
    if (rebuilt.mesh) {
        mesh::RederiveMesh(
            rebuilt,
            [&bytes](const std::string& sha256) -> std::string {
                const auto it = bytes.find(sha256);
                if (it == bytes.end()) {
                    throw core::ValueError("rebuild: the mesh reads " + sha256 + ", which the recipe does not store");
                }
                return it->second;
            },
            false);
    }
    evaluator::RequireSupported(core::Project{}, rebuilt, [&bytes](std::string_view sha256) {
        const auto it = bytes.find(std::string(sha256));
        return it == bytes.end() ? std::nullopt : evaluator::BitmapShapeOf(it->second);
    });

    core::DocumentState state;
    state.project_uuid = NewUuid();
    state.project.versions = rebuilt.versions;
    state.project.settings = rebuilt.settings;
    core::Validate(state.project);

    auto project = std::make_shared<OpenProject>();
    project->untitled_dir = std::filesystem::temp_directory_path() / "UzPainter" / ("untitled-" + RandomHex(8));
    std::filesystem::create_directories(project->untitled_dir);
    if (rebuilt.mesh) project->mesh_path = rebuilt.mesh->source;
    project->store = store::ProjectStore::Create(project->untitled_dir / "Untitled.uzp", state);
    project->document = std::make_unique<core::Document>(std::move(state));
    project->store->Attach(*project->document);

    store::ProjectStore& store = *project->store;
    const core::json::Object& dump_object = std::get<core::json::Object>(dump.data);
    core::MutationRequest request{"project.rebuild_from_recipe",
                                  core::json::Object{{"digest", dump_object.at("digest")}, {"resources", Utf8(resources_dir)}},
                                  NewKey(), project->document->revision()};
    std::exception_ptr error;
    const core::RequestOutcome outcome = store.Submit(*project->document, request, [&](core::Edit& edit) {
        try {
            for (const auto& [hash, data] : bytes) store.StageResource(data, rebuilt.resources.at(hash).front().mime);
            edit.project() = rebuilt;
        } catch (...) {
            error = std::current_exception();
            throw;
        }
    });
    Record(FromResult(Settle(outcome, error)), {}, project);
    SetActiveDefault(*project);
    {
        std::lock_guard lock(mutex_);
        if (current_) ThrowProjectError("a project is already open");
        current_ = std::move(project);
        ++generation_;
    }
    NotifyDurableChange();  // the rebuilt project is now the open one, as after Create
}

void Session::Close() {
    Current();  // ProjectError when none is open
    if (Thread().transaction) throw ApiError("RuntimeError", "close() inside an open Transaction");
    RequireNotBusy("close()");
    SetCurrent(nullptr);
    NotifyDurableChange();
}

void Session::DiscardUnsaved() {
    const std::shared_ptr<OpenProject> project = Current();
    RequireNotBusy("close()");
    if (!project->untitled_dir.empty()) return;
    const core::Checkpoints checkpoints = project->document->checkpoints();
    if (!checkpoints.named || checkpoints.current == *checkpoints.named) return;
    Revert(*checkpoints.named, "");
    Save(store::SaveMode::incremental);
}

core::Checkpoints Session::Save(store::SaveMode mode) {
    const std::shared_ptr<OpenProject> project = Current();
    if (!project->untitled_dir.empty()) {
        ThrowProjectError("the project has never been saved: save_as(path) gives it a file path");
    }
    RequireNotBusy("save()");
    return project->store->Save(*project->document, {}, mode);
}

core::Checkpoints Session::SaveAs(const std::filesystem::path& path, store::SaveMode mode,
                                store::SaveTargetPolicy policy) {
    const std::shared_ptr<OpenProject> project = Current();
    RequireNotBusy("save_as()");
    if (path.has_parent_path()) std::filesystem::create_directories(path.parent_path());
    core::Checkpoints checkpoints = project->store->SaveAs(*project->document, path, {}, policy);
    project->project_source = std::filesystem::absolute(project->store->path());
    if (mode == store::SaveMode::full) project->store->Compact(*project->document);
    if (!project->untitled_dir.empty()) {
        std::error_code ignored;
        std::filesystem::remove_all(project->untitled_dir, ignored);
        project->untitled_dir.clear();
    }
    NotifyDurableChange();
    return checkpoints;
}

void Session::SaveAsCopy(const std::filesystem::path& path) {
    const std::shared_ptr<OpenProject> project = Current();
    RequireNotBusy("save_as_copy()");
    if (path.has_parent_path()) std::filesystem::create_directories(path.parent_path());
    project->store->SaveAsCopy(path);
}

CallResult Session::Revert(std::optional<std::int64_t> revision, const std::string& checkpoint) {
    const std::shared_ptr<OpenProject> project = Current();
    if (Thread().transaction) throw ApiError("RuntimeError", "revert() inside an open Transaction");
    core::json::Object arguments;
    if (revision) arguments["revision"] = *revision;
    else arguments["checkpoint"] = checkpoint;
    core::MutationRequest request{"project.revert", arguments, NewKey(), project->document->revision()};
    const core::RequestOutcome outcome = revision ? project->store->Revert(*project->document, request, *revision)
                                                  : project->store->Revert(*project->document, request, checkpoint);
    CallResult result = FromResult(Settle(outcome, nullptr));
    Record(result, {}, project);
    return result;
}

core::RequestOutcome Session::RevertRequest(core::MutationRequest request, std::optional<std::int64_t> revision,
                                            const std::string& checkpoint) {
    const std::shared_ptr<OpenProject> project = Current();
    if (Thread().transaction) throw ApiError("RuntimeError", "a typed tool call inside an open Transaction");
    core::RequestOutcome outcome = revision ? project->store->Revert(*project->document, request, *revision)
                                            : project->store->Revert(*project->document, request, checkpoint);
    if (outcome.result) Record(FromResult(*outcome.result), {}, project);
    return outcome;
}

std::optional<std::filesystem::path> Session::FilePath() const {
    const std::shared_ptr<OpenProject> project = Current();
    if (!project->untitled_dir.empty()) return std::nullopt;
    return project->store->path();
}

// ── Reads and mutations ───────────────────────────────────────────────────────────────────────

std::shared_ptr<const core::Project> Session::ReadProject() const {
    ThreadState& thread = Thread();
    if (thread.transaction) return {thread.project, &thread.edit->project()};
    return Current()->document->snapshot().project;
}

std::int64_t Session::Revision() const {
    const ThreadState& thread = Thread();
    if (thread.transaction) return thread.base_revision;
    return Current()->document->revision();
}

void Session::Record(const CallResult& result, const std::vector<TextureInvalidation>& invalidated,
                      const std::shared_ptr<OpenProject>& origin) {
    ThreadState& thread = Thread();
    thread.last = result;
    if (thread.log && result.status == "committed") {
        thread.log->last_committed_revision = result.revision;
        thread.log->committed.push_back(result);
    }
    if (result.status == "committed") {
        // Keep the supervisor notification separate from the texture producer's identity.
        if (origin) DropSupersededEvaluation(*origin);
        if (on_durable_change) on_durable_change();
        PublishTextures(invalidated, origin);
    } else if (result.status == "no_op" && !invalidated.empty()) PublishTextures(invalidated, origin);
}

void Session::NotifyDurableChange(const std::vector<TextureInvalidation>& invalidated) const {
    std::shared_ptr<OpenProject> project;
    {
        std::lock_guard lock(mutex_);
        project = current_;
    }
    // A commit supersedes the evaluation kept for the revision before it (evaluation.h).
    if (project) DropSupersededEvaluation(*project);
    if (on_durable_change) on_durable_change();
    PublishTextures(invalidated, project);
}

std::shared_ptr<const TextureStateSnapshot> Session::TextureSnapshot() const {
    auto result = std::make_shared<TextureStateSnapshot>();
    std::shared_ptr<OpenProject> open;
    {
        std::lock_guard lock(mutex_);
        open = current_;
        result->generation = generation_;
    }
    if (!open) return result;
    const ThreadState& thread = Thread();
    const core::Snapshot snapshot = thread.transaction && thread.project == open
                                        ? thread.committed_base : open->document->snapshot();
    result->revision = snapshot.revision;
    try {
        const core::Project& project = *snapshot.project;
        if (project.settings.workflow != core::ProjectWorkflow::Default) {
            result->errors.push_back("texture state is qualified for the Default workflow only");
            return result;
        }
        const evaluator::TemplateLibrary templates =
            evaluator::TemplateLibrary::Load(evaluator::TemplateLibrary::DefaultDirectory());
        procedural::SnapshotSourceProvider procedurals(*open->store, project);
        for (const core::TextureSet& set : project.texture_sets) {
            for (const core::Stack& stack : set.stacks) {
                for (const auto& [channel, unused] : stack.channels) {
                    (void)unused;
                    if (std::none_of(stack.root_layers.begin(), stack.root_layers.end(),
                                     [&](const core::Layer& layer) {
                                         return MayHaveTextureContent(stack, layer, channel);
                                     })) continue;
                    const auto dag = evaluator::BuildDag(project, set.id, stack.id, channel, templates,
                                                         project.settings.template_id, &procedurals);
                    if (!dag) {
                        result->errors.push_back("unsupported texture DAG: " + std::to_string(stack.id) + "/" +
                                                 std::string(core::ToString(channel)));
                        continue;
                    }
                    if (dag->root.layers.empty()) continue;
                    TextureState texture;
                    texture.address = {set.id, stack.id, 0, 0, channel};
                    const evaluator::Digest digest = dag->root.isolated ? dag->readoutHash
                                                                        : dag->root.layers.back().prefixHash;
                    texture.digest = evaluator::Hex(digest);
                    evaluator::HashWriter key;
                    key.Str("document-texture-state-v1").Str(open->document->project_uuid())
                        .U64(set.id).U64(stack.id).U32(0).U32(0).U32(static_cast<std::uint32_t>(channel)).Sub(digest);
                    const evaluator::Digest bytes = key.Finish();
                    for (std::size_t i = 0; i < 8; ++i) texture.cache_key |= std::uint64_t{bytes[i]} << (i * 8);
                    TextureDependencies(dag->root, texture.dependencies);
                    result->textures.push_back(std::move(texture));
                }
            }
        }
    } catch (const std::exception& error) {
        // Observation cannot turn an already committed edit into an apparent failed edit.
        result->errors.push_back(error.what());
    }
    return result;
}

void Session::PublishTextures(const std::vector<TextureInvalidation>& invalidated,
                               const std::shared_ptr<OpenProject>& origin) const {
    {
        std::lock_guard lock(mutex_);
        if (current_ != origin) return;
    }
    {
        std::lock_guard lock(texture_mutex_);
        if (texture_subscribers_.empty()) return;
    }
    TextureStateNotice notice{TextureSnapshot(), {}};
    for (const TextureState& texture : notice.snapshot->textures) {
        const bool forced = std::any_of(invalidated.begin(), invalidated.end(), [&](const TextureInvalidation& target) {
            return (!target.channel || *target.channel == texture.address.channel) &&
                   std::find(texture.dependencies.begin(), texture.dependencies.end(), target.node) != texture.dependencies.end();
        });
        if (forced) notice.invalidated.push_back(texture.address);
    }
    {
        std::lock_guard session_lock(mutex_);
        if (current_ != origin || notice.snapshot->generation != generation_) return;
        std::lock_guard lock(texture_mutex_);
        for (auto& [token, subscriber] : texture_subscribers_) {
            (void)token;
            if (subscriber.overflow) continue;
            TextureStateNotice next = notice;
            if (subscriber.generation > next.snapshot->generation ||
                (subscriber.generation == next.snapshot->generation && subscriber.revision > next.snapshot->revision)) continue;
            if (subscriber.generation != next.snapshot->generation) subscriber.pending.clear();
            subscriber.generation = next.snapshot->generation;
            subscriber.revision = next.snapshot->revision;
            bool coalesce = false;
            if (!subscriber.pending.empty()) {
                const TextureStateNotice& old = subscriber.pending.back();
                coalesce = old.snapshot->generation == next.snapshot->generation &&
                    old.snapshot->errors.empty() && next.snapshot->errors.empty() &&
                    old.snapshot->textures.size() == next.snapshot->textures.size() &&
                    std::equal(old.snapshot->textures.begin(), old.snapshot->textures.end(), next.snapshot->textures.begin(),
                        [](const TextureState& a, const TextureState& b) { return a.address == b.address; });
                if (coalesce) {
                    for (const TextureState& texture : next.snapshot->textures) {
                        const auto previous = std::find_if(old.snapshot->textures.begin(), old.snapshot->textures.end(),
                            [&](const TextureState& value) { return value.address == texture.address; });
                        const bool changed = previous != old.snapshot->textures.end() && previous->digest != texture.digest;
                        if ((changed || std::find(old.invalidated.begin(), old.invalidated.end(), texture.address) !=
                                        old.invalidated.end()) &&
                            std::find(next.invalidated.begin(), next.invalidated.end(), texture.address) == next.invalidated.end()) {
                            next.invalidated.push_back(texture.address);
                        }
                    }
                }
            }
            if (coalesce) subscriber.pending.back() = std::move(next);
            else if (subscriber.pending.size() < 64) subscriber.pending.push_back(std::move(next));
            else {
                auto failed = std::make_shared<TextureStateSnapshot>(*notice.snapshot);
                failed->errors.push_back("texture state observer overflow: resubscribe and take a fresh snapshot");
                subscriber.pending.clear();
                subscriber.pending.push_back({std::move(failed), {}});
                subscriber.overflow = true;
            }
        }
    }
    texture_changed_.notify_all();
}

std::uint64_t Session::SubscribeTextures() {
    std::lock_guard lock(texture_mutex_);
    const std::uint64_t token = ++next_texture_subscriber_;
    texture_subscribers_.emplace(token, TextureSubscriber{});
    return token;
}

void Session::UnsubscribeTextures(std::uint64_t token) {
    {
        std::lock_guard lock(texture_mutex_);
        texture_subscribers_.erase(token);
    }
    texture_changed_.notify_all();
}

void Session::WakeTextures(std::uint64_t token) {
    {
        std::lock_guard lock(texture_mutex_);
        if (auto it = texture_subscribers_.find(token); it != texture_subscribers_.end()) it->second.wake = true;
    }
    texture_changed_.notify_all();
}

std::vector<TextureStateNotice> Session::DrainTextures(std::uint64_t token, double timeout) {
    if (!std::isfinite(timeout) || timeout < 0.0) throw core::ValueError("texture drain timeout must be finite and nonnegative");
    std::unique_lock lock(texture_mutex_);
    texture_changed_.wait_for(lock, std::chrono::duration<double>(timeout), [&] {
        const auto it = texture_subscribers_.find(token);
        return it == texture_subscribers_.end() || !it->second.pending.empty() || it->second.wake;
    });
    const auto it = texture_subscribers_.find(token);
    if (it == texture_subscribers_.end()) return {};
    it->second.wake = false;
    std::vector<TextureStateNotice> result;
    while (!it->second.pending.empty()) {
        result.push_back(std::move(it->second.pending.front()));
        it->second.pending.pop_front();
    }
    return result;
}

CallResult Session::Mutate(const std::string& tool, core::json::Object arguments,
                           const std::function<void(core::Edit&)>& call) {
    ThreadState& thread = Thread();
    const std::vector<TextureInvalidation> invalidated = SourceInvalidation(tool, arguments);
    // Inside a native Transaction the bitmaps' images and the set changes are checked once, by the
    // commit (`CommitTransaction`): its calls may resize a set and rebind its bitmaps in either order.
    const evaluator::BitmapShapes shapes = thread.transaction ? evaluator::BitmapShapes{} : ShapesOf(*Current()->store);
    const auto checked = [this, &call, &shapes, deferred = bool(thread.transaction)](core::Edit& edit) {
        call(edit);
        procedural::SnapshotSourceProvider procedurals(*Current()->store, edit.project());
        evaluator::RequireSupported(edit.base(), edit.project(), shapes, &procedurals, deferred);
        if (!deferred) RequireAdmission(edit.project());
    };
    if (thread.transaction) {
        const core::Project before = thread.edit->project();
        thread.transaction->Apply(checked);  // a throwing call fails the transaction and propagates
        for (const TextureInvalidation& target : invalidated) {
            if (std::find(thread.texture_invalidations.begin(), thread.texture_invalidations.end(), target) ==
                thread.texture_invalidations.end()) thread.texture_invalidations.push_back(target);
        }
        CallResult result{"pending", thread.base_revision, core::Diff(before, thread.edit->project()), {}};
        Record(result);
        return result;
    }
    const std::shared_ptr<OpenProject> project = Current();
    core::MutationRequest request{tool, std::move(arguments), NewKey(), project->document->revision()};
    std::exception_ptr error;
    const core::RequestOutcome outcome =
        project->store->Submit(*project->document, std::move(request), [&](core::Edit& edit) {
            try {
                checked(edit);
            } catch (...) {
                error = std::current_exception();
                throw;
            }
        });
    CallResult result = FromResult(Settle(outcome, error));
    Record(result, invalidated, project);
    return result;
}

core::RequestOutcome Session::Submit(core::MutationRequest request, const std::function<void(core::Edit&)>& call) {
    if (Thread().transaction) throw ApiError("RuntimeError", "a typed tool call inside an open Transaction");
    const std::shared_ptr<OpenProject> project = Current();
    const std::vector<TextureInvalidation> invalidated = SourceInvalidation(request.tool, request.arguments);
    const evaluator::BitmapShapes shapes = ShapesOf(*project->store);
    core::RequestOutcome outcome =
        project->store->Submit(*project->document, std::move(request), [this, &call, &shapes](core::Edit& edit) {
            call(edit);
            procedural::SnapshotSourceProvider procedurals(*Current()->store, edit.project());
            evaluator::RequireSupported(edit.base(), edit.project(), shapes, &procedurals);
            RequireAdmission(edit.project());
        });
    if (outcome.result) Record(FromResult(*outcome.result), invalidated, project);
    return outcome;
}

void Session::OpenTransaction(const std::string& name) {
    ThreadState& thread = Thread();
    if (thread.transaction) throw ApiError("RuntimeError", "a Transaction is already open on this thread");
    std::shared_ptr<OpenProject> project = Current();
    const core::Snapshot committed_base = project->document->snapshot();
    const std::int64_t base = committed_base.revision;
    core::MutationRequest request{"transaction", core::json::Object{{"name", name}}, NewKey(), base};
    auto transaction = std::make_unique<core::Transaction>(*project->document, std::move(request));
    if (!transaction->open()) {
        const core::AdmissionDecision& decision = transaction->decision();
        if (decision.admission == core::Admission::stale_revision) {
            ThrowStale(decision.expected_revision.value_or(base), decision.current_revision);
        }
        throw ApiError("RuntimeError", "the Transaction was not admitted (" +
                                           std::string(core::ToString(decision.admission)) + ")");
    }
    core::Edit* edit = nullptr;
    transaction->Apply([&edit](core::Edit& e) { edit = &e; });
    thread.transaction = std::move(transaction);
    thread.edit = edit;
    thread.project = std::move(project);
    thread.base_revision = base;
    thread.committed_base = committed_base;
    thread.texture_invalidations.clear();
}

CallResult Session::CommitTransaction() {
    ThreadState& thread = Thread();
    if (!thread.transaction) throw ApiError("RuntimeError", "no Transaction is open on this thread");
    std::unique_ptr<core::Transaction> transaction = std::move(thread.transaction);
    const std::shared_ptr<OpenProject> project = std::move(thread.project);
    const std::vector<TextureInvalidation> invalidated = std::move(thread.texture_invalidations);
    thread.texture_invalidations.clear();
    thread.committed_base = {};
    thread.edit = nullptr;
    // The support check of the state that commits, with the bitmaps' images (support.h): a refusal
    // fails the transaction, which then commits nothing and raises it.
    std::exception_ptr error;
    if (!transaction->failed()) {
        const evaluator::BitmapShapes shapes = ShapesOf(*project->store);
        try {
            transaction->Apply([this, &shapes](core::Edit& edit) {
                procedural::SnapshotSourceProvider procedurals(*Current()->store, edit.project());
                evaluator::RequireSupported(edit.base(), edit.project(), shapes, &procedurals);
                RequireAdmission(edit.project());
            });
        } catch (...) {
            error = std::current_exception();
        }
    }
    const core::RequestOutcome outcome = transaction->Commit();
    CallResult result = FromResult(Settle(outcome, error));
    Record(result, invalidated, project);
    return result;
}

void Session::RollbackTransaction() {
    ThreadState& thread = Thread();
    if (!thread.transaction) return;
    thread.transaction->Rollback();
    thread.transaction.reset();
    thread.edit = nullptr;
    thread.project.reset();
    thread.committed_base = {};
    thread.texture_invalidations.clear();
}

bool Session::TransactionOpen() const { return Thread().transaction != nullptr; }

std::optional<CallResult> Session::LastResult() const { return Thread().last; }

void Session::BeginScriptLog() { Thread().log = ScriptLog{}; }

ScriptLog Session::EndScriptLog() {
    ThreadState& thread = Thread();
    ScriptLog log = thread.log.value_or(ScriptLog{});
    thread.log.reset();
    return log;
}

}  // namespace uzp::python
