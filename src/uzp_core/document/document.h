#pragma once

// The document: the current revision of a project, its checkpoint pointers and its operation
// records (`docs/architecture/03-project-model.md` §5-§6, `09-project-file-format.md` §4).
//
// Copy-on-write at revision granularity: a revision is an immutable `Project` behind a
// `shared_ptr<const Project>`, so a snapshot costs one pointer copy and stays valid and unchanged
// for as long as a reader holds it, whatever is committed after it. A `Transaction`
// (`uzp_core/transaction/transaction.h`) edits a private copy of the current revision under the
// document lock and publishes it as the next revision in one step; nothing else changes the
// document. The evaluator, exporter and renderers read snapshots only.

#include <atomic>
#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

#include "uzp_core/operation/operation.h"
#include "uzp_core/types/project.h"

namespace uzp::core {

/// An immutable revision.
struct Snapshot {
    std::int64_t revision = 0;
    std::shared_ptr<const Project> project;
};

/// `current` is the current revision (the store's `checkpoint('current')`, moved by every
/// commit); `named` is the last revision `save()` marked; `previous` the named checkpoint before
/// it. Persisted by the project store.
struct Checkpoints {
    std::int64_t current = 0;
    std::optional<std::int64_t> named;
    std::optional<std::int64_t> previous;

    bool operator==(const Checkpoints&) const = default;
};

/// Everything a document is opened from (a new project, or what the store read back).
struct DocumentState {
    std::string project_uuid;
    Project project;
    std::int64_t revision = 0;
    std::optional<std::int64_t> named_checkpoint;
    std::optional<std::int64_t> previous_checkpoint;
    std::vector<OperationRecord> operations;
    std::int64_t operation_horizon = 0;
};

/// Called by a committing transaction under the document lock with the new revision and its
/// operation record, before either becomes visible: the project store writes both in one SQLite
/// transaction. If it throws, the commit fails and the document is unchanged.
using CommitSink = std::function<void(const Snapshot& snapshot, const OperationRecord& record)>;

class Document {
public:
    /// Throws `ValueError` when the project is invalid (`Validate`), the uuid is empty, a
    /// checkpoint is above the revision or the previous one is not below the named one, or an
    /// operation record belongs to another project, repeats a key or names a revision outside
    /// (horizon, revision].
    explicit Document(DocumentState state);

    Document(const Document&) = delete;
    Document& operator=(const Document&) = delete;

    const std::string& project_uuid() const { return project_uuid_; }

    Snapshot snapshot() const;
    std::int64_t revision() const;
    Checkpoints checkpoints() const;

    /// `needs_saving()`: the current revision is not the last named checkpoint (SAV-01).
    bool NeedsSaving() const;
    /// `save()`: marks the current revision as the named checkpoint and moves `previous` to the
    /// one before it (no change when the current revision is already marked).
    void MarkCheckpoint();

    /// The record stored under `key`, if any.
    std::optional<OperationRecord> FindOperation(std::string_view key) const;
    /// Every retained record, by committed revision.
    std::vector<OperationRecord> operations() const;
    std::int64_t operation_horizon() const;
    /// Records that compaction collapsed every revision up to `horizon`: drops the records of
    /// those revisions. Throws `ValueError` when `horizon` is below the current horizon or above
    /// the current revision.
    void SetOperationHorizon(std::int64_t horizon);

    void SetCommitSink(CommitSink sink);

private:
    friend class Transaction;

    const std::string project_uuid_;
    mutable std::mutex state_mutex_;  // guards the members below; held briefly
    Snapshot current_;
    std::optional<std::int64_t> named_;
    std::optional<std::int64_t> previous_;
    std::map<std::string, OperationRecord, std::less<>> operations_;
    std::int64_t horizon_ = 0;
    CommitSink sink_;

    std::mutex document_lock_;  // held by a transaction from admission to commit or rollback
    std::atomic<std::thread::id> lock_owner_{};
};

}  // namespace uzp::core
