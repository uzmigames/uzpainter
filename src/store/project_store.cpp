#include "store/project_store.h"

#include <fstream>
#include <sstream>
#include <utility>

#include "store/blobs.h"
#include "store/bundle.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/validation.h"

namespace uzp::store {

using core::json::Value;

namespace {

std::string Utf8(const std::filesystem::path& path) {
    const std::u8string text = path.u8string();
    return std::string(text.begin(), text.end());
}

std::optional<std::string> ReadFile(const std::filesystem::path& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) return std::nullopt;
    std::ostringstream bytes;
    bytes << file.rdbuf();
    if (file.bad()) return std::nullopt;
    return bytes.str();
}

}  // namespace

ProjectStore::ProjectStore(ProjectLock lock, Container container, std::string project_uuid, bool portable,
                           Value manifest)
    : lock_(std::move(lock)),
      path_(container.path()),
      container_(std::move(container)),
      project_uuid_(std::move(project_uuid)),
      portable_(portable),
      current_manifest_(std::move(manifest)) {}

ProjectStore::~ProjectStore() { Close(); }

std::unique_ptr<ProjectStore> ProjectStore::Create(const std::filesystem::path& path,
                                                   const core::DocumentState& initial, const CreateOptions& options) {
    if (initial.project_uuid.empty()) throw core::ValueError("store: the project uuid is empty");
    if (initial.revision < 0) throw core::ValueError("store: negative revision");
    if (!initial.operations.empty()) throw core::ValueError("store: a new project has no operation records");
    if (options.portable && !options.locators.empty()) {
        throw StoreError(StoreError::Code::conflict, "a portable project keeps no locators");
    }
    core::Validate(initial.project);
    {
        const Value manifest = core::ProjectToJson(initial.project);
        if (!ManifestPlaneReferences(manifest).empty() || !ManifestPlaneBindings(manifest).empty()) {
            throw core::ValueError("store: a new project holds no raster planes; create them with CreatePlane in a mutation");
        }
    }

    PendingContent pending;
    for (const PendingContent::Bytes& resource : options.resources) {
        pending.blobs[core::Sha256Hex(resource.bytes)] = resource;
    }
    for (const std::filesystem::path& locator : options.locators) {
        const auto hash = HashFile(locator);
        if (!hash) throw StoreError(StoreError::Code::missing_dependency, "cannot read " + Utf8(locator));
        pending.locators[*hash] = locator;
    }

    ProjectLock lock = ProjectLock::Acquire(path);
    Container container = Container::Create(path);
    try {
        Container::WriteTransaction transaction(container);
        container.CreateSchema();
        container.SetMeta("project_uuid", initial.project_uuid);
        container.SetMeta("created", UtcNow());
        container.SetMeta("operation_horizon_revision", std::to_string(initial.operation_horizon));
        container.SetMeta("portable", options.portable ? "1" : "0");
        WriteResources(container, initial.project, pending, options.portable);
        WriteRevision(container, initial.revision, std::nullopt, "checkpoint", initial.project);
        Statement checkpoint(container,
                             "INSERT INTO checkpoint (name, revision, created_at, note, protected) "
                             "VALUES ('current', ?, ?, NULL, 0)");
        checkpoint.Bind(1, initial.revision).Bind(2, UtcNow()).Run();
        transaction.Commit();
    } catch (...) {
        { Container closing = std::move(container); }  // the connection closes before the file goes
        std::error_code ec;
        std::filesystem::remove(path, ec);
        throw;
    }
    return std::unique_ptr<ProjectStore>(new ProjectStore(std::move(lock), std::move(container), initial.project_uuid,
                                                          options.portable, core::ProjectToJson(initial.project)));
}

ProjectStore::Opened ProjectStore::Open(const std::filesystem::path& path, const OpenOptions& options) {
    if (IsBundleDirectory(path)) {
        const std::filesystem::path target = BundleImportTarget(path);
        ImportBundle(path, target);
        return Open(target, options);
    }
    ProjectLock lock = ProjectLock::Acquire(path);
    RemoveTemporaryFiles(path);  // left by a worker killed during compact
    Container container = Container::Open(path);
    if (!container.HasTable("meta")) {
        throw StoreError(StoreError::Code::not_a_project, Utf8(path) + " has no meta table: not a .uzp project");
    }
    const std::optional<std::string> version_text = container.Meta("format_version");
    const std::optional<std::string> uuid = container.Meta("project_uuid");
    if (!version_text || !uuid) {
        throw StoreError(StoreError::Code::not_a_project, Utf8(path) + " has no format_version or project_uuid");
    }
    Opened opened;
    opened.file_version = FormatVersion::Parse(*version_text);
    CheckReadable(opened.file_version, options.policy);  // before anything can write to the file
    container.EnsureDeleteJournal();

    const bool portable = container.Meta("portable").value_or("1") != "0";
    const std::int64_t revision = ReadCurrentRevision(container);
    const std::string text = ReadManifestText(container, revision);
    Value manifest;
    try {
        manifest = MigrateManifest(core::json::Parse(text), opened.file_version, options.policy, opened.migrated);
    } catch (const core::json::ParseError& error) {
        throw CorruptionError(CorruptItem{"manifest", std::to_string(revision), error.what(), {}});
    }
    try {
        opened.state.project = core::LoadManifest(core::json::WriteCanonical(manifest));
    } catch (const std::exception& error) {
        throw StoreError(StoreError::Code::corrupt,
                         "the manifest of revision " + std::to_string(revision) + " cannot be read: " + error.what());
    }
    opened.state.project_uuid = *uuid;
    opened.state.revision = revision;
    opened.state.operation_horizon = ReadHorizon(container);
    opened.state.named_checkpoint = ReadNamedRevision(container);
    opened.state.previous_checkpoint = ReadPreviousRevision(container);
    std::vector<std::string> unreadable;  // reported by CheckIntegrity
    for (core::OperationRecord& record : ReadOperations(container, *uuid, unreadable)) {
        // Rows of collapsed revisions are expired (compaction removes them); the document keeps
        // the records above the horizon.
        if (record.committed_revision > opened.state.operation_horizon) opened.state.operations.push_back(std::move(record));
    }
    opened.report = CheckIntegrity(container, manifest, options.verify);
    opened.store.reset(new ProjectStore(std::move(lock), std::move(container), *uuid, portable, std::move(manifest)));
    return opened;
}

std::string ProjectStore::StageResource(std::string bytes, std::string mime) {
    std::lock_guard lock(mutex_);
    std::string sha256 = core::Sha256Hex(bytes);
    pending_.blobs[sha256] = PendingContent::Bytes{std::move(bytes), std::move(mime)};
    return sha256;
}

std::string ProjectStore::StageLocator(const std::filesystem::path& path) {
    std::lock_guard lock(mutex_);
    if (portable_) {
        throw StoreError(StoreError::Code::conflict,
                         "a portable project embeds every dependency; stage the bytes of " + Utf8(path) + " instead");
    }
    const auto hash = HashFile(path);
    if (!hash) throw StoreError(StoreError::Code::missing_dependency, "cannot read " + Utf8(path));
    pending_.locators[*hash] = path;
    return *hash;
}

std::string ProjectStore::ReadResource(std::string_view sha256) {
    std::lock_guard lock(mutex_);
    if (HasBlob(container_, sha256)) {
        try {
            return ReadBlob(container_, sha256);
        } catch (const StoreError& error) {
            if (error.code() != StoreError::Code::corrupt) throw;
            throw CorruptionError(
                CorruptItem{"blob", std::string(sha256), error.what(), NodesBinding(current_manifest_, sha256)});
        }
    }
    if (const auto locator = FindLocator(container_, sha256)) {
        const std::optional<std::string> bytes = ReadFile(*locator);
        if (!bytes) {
            throw StoreError(StoreError::Code::missing_dependency,
                             "resource " + std::string(sha256) + ": " + Utf8(*locator) + " is absent");
        }
        if (core::Sha256Hex(*bytes) != sha256) {
            throw StoreError(StoreError::Code::missing_dependency,
                             "resource " + std::string(sha256) + ": " + Utf8(*locator) + " changed");
        }
        return *bytes;
    }
    throw StoreError(StoreError::Code::missing_resource, "no stored resource " + std::string(sha256));
}

core::Id ProjectStore::CreatePlane(core::Edit& edit, const PlaneSpec& spec) {
    std::lock_guard lock(mutex_);
    return StageNewPlane(container_, planes_, edit, spec);
}

VersionRef ProjectStore::WritePlane(core::Edit& edit, core::Id plane_id, const PlaneImage& image) {
    std::lock_guard lock(mutex_);
    return StagePlaneContent(container_, planes_, edit, plane_id, image);
}

PlaneImage ProjectStore::ReadPlane(const core::Project& project, core::Id plane_id) {
    std::lock_guard lock(mutex_);
    return ReadPlaneIn(container_, planes_, project, plane_id);
}

PlaneImage ProjectStore::ReadPlane(std::int64_t revision, core::Id plane_id) {
    std::lock_guard lock(mutex_);
    return ReadPlaneAt(container_, revision, plane_id);
}

std::string ProjectStore::ReadPlaneChunk(std::int64_t revision, core::Id plane_id, int x, int y) {
    std::lock_guard lock(mutex_);
    return ReadPlaneChunkAt(container_, revision, plane_id, x, y);
}

void ProjectStore::AddCommitExtension(CommitExtension extension) {
    std::lock_guard lock(mutex_);
    extensions_.push_back(std::move(extension));
}

void ProjectStore::Attach(core::Document& document) {
    if (document.project_uuid() != project_uuid_) {
        throw StoreError(StoreError::Code::conflict, "the document belongs to project " + document.project_uuid());
    }
    document.SetCommitSink([this](const core::Snapshot& snapshot, const core::OperationRecord& record) {
        Commit(snapshot, record);
    });
}

void ProjectStore::Commit(const core::Snapshot& snapshot, const core::OperationRecord& record) {
    std::lock_guard lock(mutex_);
    PendingContent pending = std::move(pending_);
    pending_.clear();
    PendingPlanes planes = std::move(planes_);
    planes_.clear();
    std::vector<CommitExtension> extensions{
        [&planes](Container& container, const core::Snapshot& committed) { WritePlaneRows(container, planes, committed); }};
    extensions.insert(extensions.end(), extensions_.begin(), extensions_.end());
    CommitMutation(container_, snapshot, record, pending, portable_, extensions);
    current_manifest_ = core::ProjectToJson(*snapshot.project);
}

core::RequestOutcome ProjectStore::Submit(core::Document& document, core::MutationRequest request,
                                          const std::function<void(core::Edit&)>& call) {
    if (request.tool.empty()) throw core::ValueError("transaction: the request names no tool");
    if (request.idempotency_key.empty()) throw core::ValueError("transaction: the request has no idempotency key");
    {
        std::lock_guard lock(mutex_);
        core::RequestOutcome outcome;
        outcome.decision = DecideStored(container_, project_uuid_, request, document.revision());
        if (outcome.decision.admission != core::Admission::execute) return outcome;
        if (document.revision() != outcome.decision.current_revision) {
            throw StoreError(StoreError::Code::conflict, "the document is at revision " +
                                                             std::to_string(document.revision()) + ", the file at " +
                                                             std::to_string(outcome.decision.current_revision));
        }
        pending_.clear();
        planes_.clear();
    }
    // The document decides again under its own lock (a commit in between gives stale_revision);
    // the commit sink takes the store's mutex.
    return core::Execute(document, std::move(request), call);
}

core::AdmissionDecision ProjectStore::Decide(const core::MutationRequest& request, std::int64_t fallback_revision) {
    std::lock_guard lock(mutex_);
    return DecideStored(container_, project_uuid_, request, fallback_revision);
}

ProjectStore::OperationLog ProjectStore::OperationsAfter(std::int64_t after) {
    std::lock_guard lock(mutex_);
    OperationLog log;
    log.current_revision = ReadCurrentRevision(container_);
    log.horizon_revision = ReadHorizon(container_);
    for (core::OperationRecord& record : ReadOperations(container_, project_uuid_, log.unreadable)) {
        if (record.committed_revision > after) log.records.push_back(std::move(record));
    }
    return log;
}

}  // namespace uzp::store
