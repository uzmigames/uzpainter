#pragma once

// The project store: a `.uzp` file bound to a `Document` (`docs/architecture/09-project-file-format.md`,
// `src/store/STORE.md`).
//
// `Create` writes a new file holding the initial revision; `Open` checks `format_version`
// (versioning.h), reads the current revision's manifest (refusing one that does not hash to its
// `manifest_sha256`), migrates an older minor in memory, loads the operation records and runs the
// open-time integrity checks (integrity.h). `Attach` makes the store the document's commit sink,
// so every committed transaction lands in one SQLite transaction with its operation record
// (commit.h). `Submit` decides a mutation request against the stored rows before executing it.
// The raster planes of paint nodes are created and written from a transaction's call
// (`CreatePlane`, `WritePlane`), committed with the revision, and read through the manifest
// binding of a revision (planes.h). `Save`, `Compact`, `SaveAs`, `SaveAsCopy` and `Revert` are the
// saving vocabulary of 09 §4 (save.h, compact.h). An open store holds the project's lock sidecar
// (lock.h); `Close` (or destroying the store) closes the file, leaving no `-wal`/`-shm`/`-journal`
// companion, and removes the lock.
//
// The store must outlive every document attached to it. A store is used by one worker; its
// methods are serialised by an internal mutex, which is not held while a transaction's call runs.

#include <filesystem>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <string_view>
#include <vector>

#include "store/commit.h"
#include "store/compact.h"
#include "store/container.h"
#include "store/integrity.h"
#include "store/lock.h"
#include "store/planes.h"
#include "store/save.h"
#include "store/versioning.h"
#include "uzp_core/document/document.h"
#include "uzp_core/transaction/transaction.h"

namespace uzp::store {

struct CreateOptions {
    /// Portable (default): every dependency is embedded. Non-portable: resources may be kept as
    /// `{path, sha256}` locators (`StageLocator`).
    bool portable = true;
    /// Bytes (and MIME type) of resources the initial project references.
    std::vector<PendingContent::Bytes> resources;
    /// Locator targets of resources the initial project references (non-portable only).
    std::vector<std::filesystem::path> locators;
};

struct OpenOptions {
    VerifyLevel verify = VerifyLevel::standard;
    VersionPolicy policy = VersionPolicy::Current();
};

class ProjectStore {
public:
    struct Opened;

    /// Creates `path` holding `initial` as its first revision (`kind = checkpoint`, named by
    /// `checkpoint('current')`) and takes its lock. Throws `StoreError` (`exists`, `locked`,
    /// `missing_resource`, ...) and `core::ValueError` (invalid project, operation records in a new
    /// project).
    static std::unique_ptr<ProjectStore> Create(const std::filesystem::path& path, const core::DocumentState& initial,
                                                const CreateOptions& options = {});

    /// Opens `path`: takes its lock (`StoreError(locked)` while a live worker holds it; a stale
    /// lock is replaced) and removes the temporary files a killed `compact` left. Throws
    /// `StoreError(version)` for a `format_version` of another major (the file is not changed),
    /// `StoreError(not_a_project)`, and `CorruptionError` when the current manifest does not
    /// verify. Corrupt history, blobs (with `VerifyLevel::full`) and missing dependencies are
    /// reported in `Opened::report`, not thrown. A bundle directory (`IsBundleDirectory`) is first
    /// imported into `BundleImportTarget(path)`, `<dir>.uzp` beside it (`ImportBundle`;
    /// `StoreError(exists)` when that file exists), which is then opened; `ImportBundle` takes
    /// another target.
    static Opened Open(const std::filesystem::path& path, const OpenOptions& options = {});

    ProjectStore(const ProjectStore&) = delete;
    ProjectStore& operator=(const ProjectStore&) = delete;
    ~ProjectStore();

    const std::string& project_uuid() const { return project_uuid_; }
    bool portable() const { return portable_; }
    Container& container() { return container_; }
    /// The project file (the target after `SaveAs`).
    const std::filesystem::path& path() const { return path_; }
    /// The lock sidecar this store holds (empty after `Close`).
    const std::filesystem::path& lock_path() const { return lock_.path(); }

    /// Closes the file (`journal_mode = DELETE`, no companion file left) and removes the lock.
    /// Every later call that reads or writes the file throws `StoreError(io)`. Idempotent.
    void Close();

    /// `save()`: writes the named checkpoint of the current revision and moves `previous`
    /// (save.h), then marks the document; `SaveMode::full` compacts afterwards. Returns the
    /// checkpoints. Throws `StoreError(protected_checkpoint)` for a protected name and
    /// `StoreError(conflict)` when the document is not at the stored current revision.
    core::Checkpoints Save(core::Document& document, const SaveOptions& options = {},
                           SaveMode mode = SaveMode::incremental);
    /// `needs_saving()` as the file holds it: the current revision is not the last named
    /// checkpoint (equal to `Document::NeedsSaving` of the attached document).
    bool NeedsSaving();
    /// `{current, named, previous}` as the file holds them.
    core::Checkpoints CheckpointState();

    /// `compact` (compact.h): collapses what retention does not keep, collects unreachable rows,
    /// `VACUUM INTO` a temporary file and renames it over the project; raises the document's
    /// operation horizon. On failure the project file is unchanged and the error names the step.
    CompactResult Compact(core::Document& document);

    /// `save_as(path)`: `VACUUM INTO` a temporary file beside `target`, writes `save()`'s
    /// checkpoint into it, renames it to `target` and relocates the open project and its lock
    /// there; the original file is not changed. Throws `StoreError(exists)` when `target` exists
    /// and `StoreError(locked)` when another worker holds its lock; on failure nothing is left at
    /// `target` and the project stays where it was.
    core::Checkpoints SaveAs(core::Document& document, const std::filesystem::path& target,
                             const SaveOptions& options = {});
    /// `save_as_copy(path)`: `VACUUM INTO` a temporary file beside `target` and renames it to
    /// `target`; the project keeps its path, lock and dirty state. Throws `StoreError(exists)`
    /// when `target` exists; on failure nothing is left at `target`.
    void SaveAsCopy(const std::filesystem::path& target);

    /// Revert: submits `request` as a mutation whose project copies the manifest of `revision`
    /// (`RevertedProject`), plane bindings included. A revision outside the retained set fails
    /// the call with `not_retained`; history is append-only.
    core::RequestOutcome Revert(core::Document& document, core::MutationRequest request, std::int64_t revision);
    /// Revert to the revision checkpoint `name` names (resolved inside the call).
    core::RequestOutcome Revert(core::Document& document, core::MutationRequest request, const std::string& checkpoint);

    /// Stages resource bytes for the commit of the running `Submit` (call it from the
    /// transaction's call); returns their SHA-256. The commit stores them once if the committed
    /// project references the hash and they are not stored yet. `Submit` discards what an earlier
    /// call staged without committing.
    std::string StageResource(std::string bytes, std::string mime);
    /// Non-portable projects only: stages a `{path, sha256}` locator for the next commit; returns
    /// the file's SHA-256. Throws `StoreError(conflict)` for a portable project and
    /// `StoreError(missing_dependency)` when the file cannot be read.
    std::string StageLocator(const std::filesystem::path& path);

    /// The verified bytes of a resource: from `blob`, or through the locator of a non-portable
    /// project. Throws `CorruptionError` (with the nodes of the current manifest that bind the
    /// hash) when stored bytes do not verify, `StoreError(missing_dependency)` for an absent or
    /// changed locator target and `StoreError(missing_resource)` when the hash is unknown.
    std::string ReadResource(std::string_view sha256);

    /// Creates a raster plane owned by a paint node of the transaction's working copy, bound to
    /// an empty version (`StageNewPlane`); call it from the transaction's call. Returns its
    /// `plane_id`. The plane row and version are written by the transaction's commit.
    core::Id CreatePlane(core::Edit& edit, const PlaneSpec& spec);
    /// Stages `image` as the new content of `plane_id` and rebinds its node in the working copy
    /// (`StagePlaneContent`): a new immutable version written by the transaction's commit, with
    /// blobs only for the chunks the file does not hold. Call it from the transaction's call.
    VersionRef WritePlane(core::Edit& edit, core::Id plane_id, const PlaneImage& image);
    /// The pixels `project` binds to `plane_id` (a working copy's staged content included).
    PlaneImage ReadPlane(const core::Project& project, core::Id plane_id);
    /// The pixels the manifest of `revision` binds to `plane_id`. Throws
    /// `StoreError(missing_resource)` when that manifest binds no such plane and `CorruptionError`
    /// (naming the plane and its owning node) when its rows or chunk bytes do not verify.
    PlaneImage ReadPlane(std::int64_t revision, core::Id plane_id);
    /// The texels of chunk (x, y) of that plane at `revision`; zeros when the version has no row
    /// for it (`ReadPlaneChunkAt`).
    std::string ReadPlaneChunk(std::int64_t revision, core::Id plane_id, int x, int y);

    /// Rows written inside every mutation's SQLite transaction, after the plane rows.
    void AddCommitExtension(CommitExtension extension);

    /// Sets the document's commit sink to this store.
    void Attach(core::Document& document);

    /// Decides `request` against the stored operation rows, `checkpoint('current')` and
    /// `meta.operation_horizon_revision`; executes `call` through `core::Execute` only when that
    /// decision is `execute`. The document must be attached. Throws `core::ValueError` for a
    /// request without a tool or idempotency key and `StoreError(conflict)` when the document's
    /// revision is not the stored one.
    core::RequestOutcome Submit(core::Document& document, core::MutationRequest request,
                                const std::function<void(core::Edit&)>& call);

    /// `DecideStored` for `request` without executing anything: the worker's admission of a
    /// mutating call before its handler runs (src/supervisor/worker.cpp). `fallback_revision` as
    /// in `DecideStored`.
    core::AdmissionDecision Decide(const core::MutationRequest& request, std::int64_t fallback_revision);

    /// The operation rows a supervisor reconciles its ledger from after a worker restart.
    struct OperationLog {
        std::int64_t current_revision = 0;
        std::int64_t horizon_revision = 0;
        /// The readable rows committed after the revision asked for, by committed revision.
        std::vector<core::OperationRecord> records;
        /// The keys of every row that does not decode (`ReadOperations`).
        std::vector<std::string> unreadable;
    };
    /// `checkpoint('current')`, the horizon and the operation rows committed after `after`.
    /// Throws `StoreError` when the file cannot be read.
    OperationLog OperationsAfter(std::int64_t after);

private:
    ProjectStore(ProjectLock lock, Container container, std::string project_uuid, bool portable,
                 core::json::Value manifest);
    void Commit(const core::Snapshot& snapshot, const core::OperationRecord& record);
    /// `StoreError(conflict)` unless `document` is this project at the stored current revision.
    void CheckDocument(const core::Document& document);
    CompactResult CompactLocked(core::Document& document);
    core::RequestOutcome SubmitRevert(core::Document& document, core::MutationRequest request,
                                      const std::function<std::int64_t()>& target);

    ProjectLock lock_;  // released after the connection closes
    std::filesystem::path path_;
    Container container_;
    const std::string project_uuid_;
    const bool portable_;
    std::mutex mutex_;  // never held while a transaction runs
    PendingContent pending_;
    PendingPlanes planes_;
    std::vector<CommitExtension> extensions_;
    core::json::Value current_manifest_;  // the manifest of the last committed (or opened) revision
};

struct ProjectStore::Opened {
    std::unique_ptr<ProjectStore> store;
    /// What a `Document` is opened from, with the last named checkpoint and `previous`.
    core::DocumentState state;
    IntegrityReport report;
    /// `meta.format_version` as found in the file, and whether the manifest was migrated in memory.
    FormatVersion file_version;
    bool migrated = false;
};

}  // namespace uzp::store
