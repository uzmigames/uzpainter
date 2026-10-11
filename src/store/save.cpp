#include "store/save.h"

#include <algorithm>
#include <utility>

#include "store/commit.h"
#include "store/compact.h"
#include "store/integrity.h"
#include "store/project_store.h"
#include "store/versioning.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/manifest.h"

namespace uzp::store {

using core::json::Object;
using core::json::Value;

namespace {

std::string Utf8(const std::filesystem::path& path) {
    const std::u8string text = path.u8string();
    return std::string(text.begin(), text.end());
}

CheckpointRow Row(Statement& q) {
    return CheckpointRow{q.Text(0), q.Int(1), q.Text(2), q.Text(3), !q.IsNull(4) && q.Int(4) == 1};
}

bool Reserved(std::string_view name) { return name == kCurrentCheckpoint || name == kPreviousCheckpoint; }

/// The `versions.format_version` a stored manifest carries.
FormatVersion StampedVersion(const Value& manifest, std::int64_t revision) {
    if (const auto* root = std::get_if<Object>(&manifest.data)) {
        if (const auto versions = root->find("versions"); versions != root->end() && versions->second.IsObject()) {
            const Object& v = std::get<Object>(versions->second.data);
            if (const auto it = v.find("format_version"); it != v.end() && it->second.IsString()) {
                return FormatVersion::Parse(std::get<std::string>(it->second.data));
            }
        }
    }
    throw StoreError(StoreError::Code::corrupt,
                     "the manifest of revision " + std::to_string(revision) + " has no versions.format_version");
}

void RemoveQuietly(const std::filesystem::path& path) {
    std::error_code ec;
    std::filesystem::remove(path, ec);
    std::filesystem::path journal = path;
    journal += "-journal";
    std::filesystem::remove(journal, ec);
}

}  // namespace

std::vector<CheckpointRow> ReadCheckpoints(Container& container) {
    Statement q(container, "SELECT name, revision, created_at, note, protected FROM checkpoint ORDER BY revision, name");
    std::vector<CheckpointRow> rows;
    while (q.Step()) rows.push_back(Row(q));
    return rows;
}

std::optional<CheckpointRow> ReadCheckpoint(Container& container, std::string_view name) {
    Statement q(container, "SELECT name, revision, created_at, note, protected FROM checkpoint WHERE name = ?");
    q.Bind(1, name);
    if (!q.Step()) return std::nullopt;
    return Row(q);
}

std::optional<std::int64_t> ReadNamedRevision(Container& container) {
    Statement q(container, "SELECT MAX(revision) FROM checkpoint WHERE name NOT IN ('current', 'previous')");
    if (!q.Step() || q.IsNull(0)) return std::nullopt;
    return q.Int(0);
}

std::optional<std::int64_t> ReadPreviousRevision(Container& container) {
    const std::optional<CheckpointRow> row = ReadCheckpoint(container, kPreviousCheckpoint);
    if (!row) return std::nullopt;
    return row->revision;
}

core::Checkpoints ReadCheckpointState(Container& container) {
    return core::Checkpoints{ReadCurrentRevision(container), ReadNamedRevision(container), ReadPreviousRevision(container)};
}

std::string DefaultCheckpointName(std::int64_t revision) { return "save-" + std::to_string(revision); }

core::Checkpoints WriteSaveCheckpoint(Container& container, const SaveOptions& options) {
    const core::Checkpoints before = ReadCheckpointState(container);
    const std::string name = options.name.empty() ? DefaultCheckpointName(before.current) : options.name;
    if (Reserved(name)) {
        throw StoreError(StoreError::Code::conflict, "'" + name + "' is a reserved checkpoint name");
    }
    if (const std::optional<CheckpointRow> existing = ReadCheckpoint(container, name); existing && existing->is_protected) {
        throw StoreError(StoreError::Code::protected_checkpoint,
                         "checkpoint '" + name + "' is protected (revision " + std::to_string(existing->revision) +
                             ") and cannot be overwritten");
    }
    Statement upsert(container,
                     "INSERT INTO checkpoint (name, revision, created_at, note, protected) VALUES (?, ?, ?, ?, ?) "
                     "ON CONFLICT (name) DO UPDATE SET revision = excluded.revision, created_at = excluded.created_at, "
                     "note = excluded.note, protected = excluded.protected");
    upsert.Bind(1, name).Bind(2, before.current).Bind(3, UtcNow());
    if (options.note.empty()) {
        upsert.BindNull(4);
    } else {
        upsert.Bind(4, options.note);
    }
    upsert.Bind(5, std::int64_t{options.protect ? 1 : 0}).Run();

    core::Checkpoints after{before.current, before.current, before.previous};
    if (before.named != before.current && before.named) {
        // The current revision becomes the last named checkpoint: `previous` moves to the one before.
        after.previous = before.named;
        Statement previous(container,
                           "INSERT INTO checkpoint (name, revision, created_at, note, protected) "
                           "VALUES ('previous', ?, ?, NULL, 0) "
                           "ON CONFLICT (name) DO UPDATE SET revision = excluded.revision, created_at = excluded.created_at");
        previous.Bind(1, *before.named).Bind(2, UtcNow()).Run();
    }
    return after;
}

std::int64_t ResolveCheckpoint(Container& container, std::string_view name) {
    const std::optional<CheckpointRow> row = ReadCheckpoint(container, name);
    if (!row) throw StoreError(StoreError::Code::not_retained, "there is no checkpoint '" + std::string(name) + "'");
    return row->revision;
}

core::Project RevertedProject(Container& container, std::int64_t revision, const core::Project& current) {
    const Retention retention = ComputeRetention(container);
    if (retention.revisions.count(revision) == 0) {
        throw StoreError(StoreError::Code::not_retained,
                         "revision " + std::to_string(revision) +
                             " is not retained (current, previous, the last named checkpoint, the last " +
                             std::to_string(kRetainedMutations) + " mutations and protected checkpoints)");
    }
    Value manifest;
    try {
        manifest = core::json::Parse(ReadManifestText(container, revision));
    } catch (const core::json::ParseError& error) {
        throw CorruptionError(CorruptItem{"manifest", std::to_string(revision), error.what(), {}});
    }
    bool migrated = false;
    const FormatVersion stamped = StampedVersion(manifest, revision);
    manifest = MigrateManifest(std::move(manifest), stamped, VersionPolicy::Current(), migrated);
    core::Project project = core::LoadManifest(core::json::WriteCanonical(manifest));
    project.next_id = std::max(project.next_id, current.next_id);
    return project;
}

// ── ProjectStore: close, save, save_as, save_as_copy, revert ──────────────────────────────────

void ProjectStore::Close() {
    std::lock_guard lock(mutex_);
    if (container_.handle() != nullptr) {
        try {
            container_.EnsureDeleteJournal();  // a WAL file is checkpointed back into the database
        } catch (const StoreError&) {
            // The connection closes regardless; DELETE was set when the file was opened.
        }
        Container closing = std::move(container_);
    }
    lock_.Release();
}

void ProjectStore::CheckDocument(const core::Document& document) {
    if (document.project_uuid() != project_uuid_) {
        throw StoreError(StoreError::Code::conflict, "the document belongs to project " + document.project_uuid());
    }
    const std::int64_t stored = ReadCurrentRevision(container_);
    if (document.revision() != stored) {
        throw StoreError(StoreError::Code::conflict, "the document is at revision " + std::to_string(document.revision()) +
                                                         ", the file at " + std::to_string(stored));
    }
}

core::Checkpoints ProjectStore::Save(core::Document& document, const SaveOptions& options, SaveMode mode) {
    std::lock_guard lock(mutex_);
    CheckDocument(document);
    core::Checkpoints checkpoints;
    {
        Container::WriteTransaction transaction(container_);
        checkpoints = WriteSaveCheckpoint(container_, options);
        transaction.Commit();
    }
    document.MarkCheckpoint();
    if (mode == SaveMode::full) CompactLocked(document);
    return checkpoints;
}

bool ProjectStore::NeedsSaving() {
    std::lock_guard lock(mutex_);
    const core::Checkpoints state = ReadCheckpointState(container_);
    return state.named != state.current;
}

core::Checkpoints ProjectStore::CheckpointState() {
    std::lock_guard lock(mutex_);
    return ReadCheckpointState(container_);
}

core::Checkpoints ProjectStore::SaveAs(core::Document& document, const std::filesystem::path& target,
                                       const SaveOptions& options) {
    std::lock_guard lock(mutex_);
    CheckDocument(document);
    std::error_code ec;
    if (std::filesystem::exists(target, ec)) throw StoreError(StoreError::Code::exists, Utf8(target) + " already exists");
    ProjectLock target_lock = ProjectLock::Acquire(target);
    const std::filesystem::path output = SiblingPath(target, "vacuum");
    core::Checkpoints checkpoints;
    Container relocated = [&] {
        try {
            VacuumInto(container_, output);
            {
                Container copy = Container::Open(output);
                Container::WriteTransaction transaction(copy);
                checkpoints = WriteSaveCheckpoint(copy, options);
                transaction.Commit();
            }
            RenameFile(output, target, false);
        } catch (const StoreError& error) {
            RemoveQuietly(output);
            throw StoreError(error.code(), "save_as " + Utf8(target) + ": " + ErrorDetail(error));
        }
        Container opened = Container::Open(target);
        opened.EnsureDeleteJournal();
        return opened;
    }();
    container_ = std::move(relocated);  // the original file closes unchanged
    path_ = target;
    lock_ = std::move(target_lock);  // releases the original's lock
    document.MarkCheckpoint();
    return checkpoints;
}

void ProjectStore::SaveAsCopy(const std::filesystem::path& target) {
    std::lock_guard lock(mutex_);
    std::error_code ec;
    if (std::filesystem::exists(target, ec)) throw StoreError(StoreError::Code::exists, Utf8(target) + " already exists");
    const std::filesystem::path output = SiblingPath(target, "vacuum");
    try {
        VacuumInto(container_, output);
        RenameFile(output, target, false);
    } catch (const StoreError& error) {
        RemoveQuietly(output);
        throw StoreError(error.code(), "save_as_copy " + Utf8(target) + ": " + ErrorDetail(error));
    }
}

core::RequestOutcome ProjectStore::Revert(core::Document& document, core::MutationRequest request,
                                          std::int64_t revision) {
    return SubmitRevert(document, std::move(request), [revision] { return revision; });
}

core::RequestOutcome ProjectStore::Revert(core::Document& document, core::MutationRequest request,
                                          const std::string& checkpoint) {
    return SubmitRevert(document, std::move(request), [this, checkpoint] { return ResolveCheckpoint(container_, checkpoint); });
}

core::RequestOutcome ProjectStore::SubmitRevert(core::Document& document, core::MutationRequest request,
                                                const std::function<std::int64_t()>& target) {
    return Submit(document, std::move(request), [&](core::Edit& edit) {
        std::lock_guard lock(mutex_);
        edit.project() = RevertedProject(container_, target(), edit.project());
    });
}

}  // namespace uzp::store
