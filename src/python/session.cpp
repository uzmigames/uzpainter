// The open project and the mutation contract of the `uzpainter` module (session.h).

#include "python/session.h"

#include <array>
#include <chrono>
#include <ctime>
#include <fstream>
#include <iterator>
#include <random>
#include <system_error>
#include <utility>

#include "evaluator/profile.h"
#include "evaluator/support.h"
#include "evaluator/templates.h"
#include "mesh/mesh_import.h"
#include "python/errors.h"
#include "uzp_core/types/errors.h"

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
};

ThreadState& Thread() {
    thread_local ThreadState state;
    return state;
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

void Session::Create(const std::filesystem::path& mesh_path, const CreateSettings& settings) {
    if (IsOpen()) ThrowProjectError("a project is already open");
    if (settings.workflow && *settings.workflow != core::ProjectWorkflow::Default) {
        ThrowNotYetSupported("project workflow " + std::string(core::ToString(*settings.workflow)) +
                             " is a release gap: the UV-tile workflow (phase4.5_uv-tiles)");
    }
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
    p.settings.template_id = template_id;
    core::Validate(p);

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
    core::MutationRequest request{"project.create",
                                  core::json::Object{{"mesh", Utf8(mesh_path.filename())}, {"mesh_sha256", imported.sha256}},
                                  NewKey(), project->document->revision()};
    std::exception_ptr error;
    const core::RequestOutcome outcome = store.Submit(*project->document, request, [&](core::Edit& edit) {
        try {
            store.StageResource(bytes, std::string(mesh::MimeOf(imported.format)));
            mesh::CreateTextureSets(edit, imported, mesh::MeshSource{mesh_source, NowUtc()}, channels);
        } catch (...) {
            error = std::current_exception();
            throw;
        }
    });
    Record(FromResult(Settle(outcome, error)));
    SetActiveDefault(*project);
    {
        std::lock_guard lock(mutex_);
        if (current_) ThrowProjectError("a project is already open");
        current_ = std::move(project);
    }
}

void Session::Open(const std::filesystem::path& path) {
    if (IsOpen()) ThrowProjectError("a project is already open");
    if (!std::filesystem::exists(path)) ThrowProjectError("cannot open " + Utf8(path) + ": no such file");
    store::ProjectStore::Opened opened = store::ProjectStore::Open(path);
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
    project->project_source = std::filesystem::absolute(path);
    SetActiveDefault(*project);
    std::lock_guard lock(mutex_);
    if (current_) ThrowProjectError("a project is already open");
    current_ = std::move(project);
}

void Session::Close() {
    Current();  // ProjectError when none is open
    if (Thread().transaction) throw ApiError("RuntimeError", "close() inside an open Transaction");
    RequireNotBusy("close()");
    SetCurrent(nullptr);
}

core::Checkpoints Session::Save(store::SaveMode mode) {
    const std::shared_ptr<OpenProject> project = Current();
    if (!project->untitled_dir.empty()) {
        ThrowProjectError("the project has never been saved: save_as(path) gives it a file path");
    }
    RequireNotBusy("save()");
    return project->store->Save(*project->document, {}, mode);
}

core::Checkpoints Session::SaveAs(const std::filesystem::path& path, store::SaveMode mode) {
    const std::shared_ptr<OpenProject> project = Current();
    RequireNotBusy("save_as()");
    if (path.has_parent_path()) std::filesystem::create_directories(path.parent_path());
    core::Checkpoints checkpoints = project->store->SaveAs(*project->document, path);
    project->project_source = std::filesystem::absolute(path);
    if (mode == store::SaveMode::full) project->store->Compact(*project->document);
    if (!project->untitled_dir.empty()) {
        std::error_code ignored;
        std::filesystem::remove_all(project->untitled_dir, ignored);
        project->untitled_dir.clear();
    }
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
    Record(result);
    return result;
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

void Session::Record(const CallResult& result) {
    ThreadState& thread = Thread();
    thread.last = result;
    if (thread.log && result.status == "committed") {
        thread.log->last_committed_revision = result.revision;
        thread.log->committed.push_back(result);
    }
}

CallResult Session::Mutate(const std::string& tool, core::json::Object arguments,
                           const std::function<void(core::Edit&)>& call) {
    ThreadState& thread = Thread();
    const auto checked = [&call](core::Edit& edit) {
        call(edit);
        evaluator::RequireSupported(edit.base(), edit.project());
    };
    if (thread.transaction) {
        const core::Project before = thread.edit->project();
        thread.transaction->Apply(checked);  // a throwing call fails the transaction and propagates
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
    Record(result);
    return result;
}

void Session::OpenTransaction(const std::string& name) {
    ThreadState& thread = Thread();
    if (thread.transaction) throw ApiError("RuntimeError", "a Transaction is already open on this thread");
    std::shared_ptr<OpenProject> project = Current();
    const std::int64_t base = project->document->revision();
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
}

CallResult Session::CommitTransaction() {
    ThreadState& thread = Thread();
    if (!thread.transaction) throw ApiError("RuntimeError", "no Transaction is open on this thread");
    std::unique_ptr<core::Transaction> transaction = std::move(thread.transaction);
    thread.edit = nullptr;
    thread.project.reset();
    const core::RequestOutcome outcome = transaction->Commit();
    CallResult result = FromResult(Settle(outcome, nullptr));
    Record(result);
    return result;
}

void Session::RollbackTransaction() {
    ThreadState& thread = Thread();
    if (!thread.transaction) return;
    thread.transaction->Rollback();
    thread.transaction.reset();
    thread.edit = nullptr;
    thread.project.reset();
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
