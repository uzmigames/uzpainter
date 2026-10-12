#pragma once

// The project a `uzpainter` script works on, and the mutation contract of
// docs/architecture/10-python-api.md §5 (task phase1.19_pyapi-native-module).
//
// - One project at a time: a project store (`src/store/`) bound to a `core::Document`. A project
//   created from a mesh lives in a private folder of the temporary directory until `save_as` gives
//   it a path (`file_path()` is None meanwhile); closing it removes that folder.
// - One API call = one transaction: `Mutate` submits the call through the project store
//   (`ProjectStore::Submit`, `core::Execute`) with a fresh idempotency key and the current revision
//   as its precondition, runs the Phase 1 support check (`evaluator::RequireSupported`, decision
//   082) on the working copy, and returns the committed result or raises. A call that fails
//   commits nothing; another thread's commit in between raises `StaleRevisionError`.
// - The native `Transaction` (`OpenTransaction`) makes several calls of one thread atomic: each
//   call is applied to the transaction's working copy, reads on that thread see the working copy,
//   and the block commits once or not at all.
// - Thread rules of 02-runtime-topology.md §4: the document lock is held only while a call edits
//   the working copy (or for the duration of a native `Transaction`); the GIL is released around
//   every wait for the document lock, a job or the store, so other Python threads run meanwhile.
//
// Every function here may be called with or without the GIL; the bindings release it around
// `Mutate`, the lifecycle calls and job waits.

#include <cstdint>
#include <filesystem>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "store/project_store.h"
#include "uzp_core/document/document.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/project.h"

namespace uzp::python {

/// UzPainter's version (`build.zig.zon`), reported by `application.version()`.
inline constexpr const char* kAppVersion = "0.0.0";

/// The result of one API call (QG-03). `status` is `committed` or `no_op`, or `pending` for a call
/// applied inside an open native `Transaction` (its `changes` are what the call changed in the
/// working copy; `revision` is the revision the transaction started from).
struct CallResult {
    std::string status;
    std::int64_t revision = 0;
    core::ChangeSet changes;
    core::json::Object returned;
};

/// What `project.create` takes (Painter's `project.Settings`, the members UzPainter reads).
struct CreateSettings {
    std::optional<core::NormalMapFormat> normal_map_format;
    std::optional<core::TangentSpace> tangent_space;
    std::optional<core::ProjectWorkflow> workflow;
    std::optional<int> default_texture_resolution;
    std::optional<double> mesh_unit_scale;
    std::optional<bool> import_cameras;
    /// The id of an installed project template (`assets/templates/<id>.json`); none = "default".
    std::optional<std::string> template_id;
};

/// The open project.
struct OpenProject {
    std::unique_ptr<store::ProjectStore> store;
    std::unique_ptr<core::Document> document;
    /// The private folder of a project that was never saved (empty once it has a path).
    std::filesystem::path untitled_dir;
    /// The mesh file the project was created from (`last_imported_mesh_path`).
    std::string mesh_path;
    /// The project file as an absolute path, resolved against the working directory when the
    /// call that named it ran (an export job names its project with it, and
    /// `project.absolute_file_path()` returns it, so a later change of directory or of project does
    /// not move it). Empty while untitled. The mesh's source is the document's own
    /// `MeshReference::source`.
    std::filesystem::path project_source;
    /// The default `(texture set, stack)` address (`textureset.get/set_active_stack`).
    core::Id active_set = core::kNoId;
    core::Id active_stack = core::kNoId;

    ~OpenProject();
};

/// The revision a script last committed and every committed call result, recorded while a
/// script runs (`script.h`).
struct ScriptLog {
    std::optional<std::int64_t> last_committed_revision;
    std::vector<CallResult> committed;
};

class Session {
public:
    static Session& Get();

    // ── Lifecycle (`uzpainter.project`) ───────────────────────────────────────────────────────
    /// Imports the mesh and creates an untitled project with one texture set per material.
    /// `ProjectError` when a project is open; mesh refusals as `mesh::ImportError`.
    void Create(const std::filesystem::path& mesh_path, const CreateSettings& settings);
    /// `ProjectError` when a project is open or the file cannot be opened.
    void Open(const std::filesystem::path& path);
    /// `ProjectError` when none is open, `BusyError` while a job runs.
    void Close();
    bool IsOpen() const;
    /// `ProjectError` for an untitled project (it has no path yet).
    core::Checkpoints Save(store::SaveMode mode);
    core::Checkpoints SaveAs(const std::filesystem::path& path, store::SaveMode mode);
    void SaveAsCopy(const std::filesystem::path& path);
    /// Appends a revision whose project is the one of `revision` (or the checkpoint `name`).
    CallResult Revert(std::optional<std::int64_t> revision, const std::string& checkpoint);

    /// The open project (`ProjectError` when none). Holding it keeps the store and the document
    /// alive across a concurrent `Close`.
    std::shared_ptr<OpenProject> Current() const;
    /// The file path, or nullopt for an untitled project.
    std::optional<std::filesystem::path> FilePath() const;

    // ── Reads and mutations ───────────────────────────────────────────────────────────────────
    /// The project this thread reads: the working copy of its open native `Transaction`, or
    /// the current revision.
    std::shared_ptr<const core::Project> ReadProject() const;
    std::int64_t Revision() const;

    /// One API call (see above). `tool` and `arguments` form the operation record's request.
    CallResult Mutate(const std::string& tool, core::json::Object arguments,
                      const std::function<void(core::Edit&)>& call);

    /// The native `Transaction` of this thread: opened (waiting for the document lock), then
    /// committed or rolled back. `Commit` raises the transaction's error when it fails.
    void OpenTransaction(const std::string& name);
    CallResult CommitTransaction();
    void RollbackTransaction();
    bool TransactionOpen() const;

    /// The result of this thread's last API call.
    std::optional<CallResult> LastResult() const;

    /// Starts and stops recording `ScriptLog` for this thread.
    void BeginScriptLog();
    ScriptLog EndScriptLog();

    /// The id of a running job, if any (`BusyError` checks).
    std::function<std::optional<std::string>()> running_job;

private:
    Session() = default;
    void RequireNotBusy(const std::string& what) const;
    void Record(const CallResult& result);
    void SetCurrent(std::shared_ptr<OpenProject> project);

    mutable std::mutex mutex_;  // guards current_
    std::shared_ptr<OpenProject> current_;
};

/// A UTF-8 path as a filesystem path, and a filesystem path as UTF-8 with `/` separators.
std::filesystem::path PathFromUtf8(std::string_view text);
std::string Utf8(const std::filesystem::path& path);

/// A fresh idempotency key (`py-<random 128-bit hex>`).
std::string NewKey();
/// The current UTC time in RFC 3339 (`2026-10-12T09:30:00Z`).
std::string NowUtc();

}  // namespace uzp::python
