#pragma once

// Transactions (`docs/architecture/03-project-model.md` §6, `10-python-api.md` §5, §7;
// `09-project-file-format.md` §4).
//
// One API call is one transaction: `Execute`. A transaction is admitted by `DecideAdmission`
// under the document lock; its calls edit a private copy of the current revision (`Edit`); its
// commit validates the copy and publishes it as the next revision together with its operation
// record. A call that throws, a copy that fails validation or a commit sink that throws commits
// nothing: the document, its revision and its operation records are unchanged, and the result
// lists what would have changed. A call that changes nothing is a no-op: no revision, no record,
// and a result that says so (QG-03).
//
// Composite operations build their subtree detached (ids from `Edit::AllocateId`) and attach it
// in one step with `Edit::Attach`. The native `Transaction` (`uzpainter.Transaction`) is the same
// object driven call by call: `Apply` per call, then `Commit`; `Rollback`, or destruction while
// open, discards every call.

#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <set>
#include <string>
#include <vector>

#include "uzp_core/document/document.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/operation/operation.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/layers.h"
#include "uzp_core/types/project.h"
#include "uzp_core/types/validation.h"

namespace uzp::core {

/// Ids (ascending) and resource hashes (sorted) a transaction changed (QG-03). Nodes are layers
/// and effects; texture sets and stacks appear in `modified` when their own fields change.
/// `modified`: a node whose own fields (not its sub-lists) changed, which moved to another list,
/// or whose list was reordered (the list's owner). `hidden`: visible before, hidden after.
/// `imported`: resource hashes new in the project; `skipped`: hashes an import found already
/// stored (`Edit::NoteSkippedResource`).
struct ChangeSet {
    std::vector<Id> created;
    std::vector<Id> modified;
    std::vector<Id> removed;
    std::vector<Id> hidden;
    std::vector<std::string> imported;
    std::vector<std::string> skipped;

    bool empty() const;
    /// `{created, hidden, imported, modified, removed, skipped}`.
    json::Object ToJson() const;
    bool operator==(const ChangeSet&) const = default;
};

/// What changed from `before` to `after` (`skipped` is left empty).
ChangeSet Diff(const Project& before, const Project& after);

enum class ResultStatus { committed, no_op, failed };

template <>
struct EnumTable<ResultStatus> {
    static constexpr auto names = std::to_array<std::string_view>({"committed", "no_op", "failed"});
};

struct TransactionResult {
    ResultStatus status = ResultStatus::no_op;
    /// The document revision after the call: the revision it committed, or the unchanged one.
    std::int64_t revision = 0;
    /// Committed: what was applied. Failed: what would have changed. No-op: only `skipped`.
    ChangeSet changes;
    /// Values the calls returned (`Edit::returned`), e.g. the node a named insert resolved.
    json::Object returned;
    /// Failed: the error class (`ValueError`, `NotYetSupported`, `RuntimeError`) and its message.
    std::string error_type;
    std::string error;

    /// `{status, revision, returned, <changes>}`, with `committed_revision` when committed; a
    /// failed result has `error {type, message}` and its changes under `would_change`.
    json::Object ToJson() const;
};

/// The outcome of one mutation request.
struct RequestOutcome {
    AdmissionDecision decision;
    /// Set when the request was executed (`decision.admission == execute`).
    std::optional<TransactionResult> result;
    /// The record this request committed (committed results only).
    std::optional<OperationRecord> committed;
};

/// The edit context of one transaction: a private copy of the revision it started from.
class Edit {
public:
    /// The working copy. Calls change it freely; the commit validates it.
    Project& project() { return working_; }
    /// The revision the transaction started from.
    const Project& base() const { return *base_; }

    /// Hands out the next persistent id of the working copy (for detached subtrees).
    Id AllocateId() { return working_.AllocateId(); }

    /// `InsertNode` on the working copy (documented insertion rules; throws `ValueError`).
    Id Insert(const InsertPosition& position, NodeType type, std::string name, Id instance_source = kNoId);

    /// Attaches a detached layer subtree, or an effect, at `position` in one step, under the
    /// insertion rules of its root's type; its ids must come from `AllocateId`. On failure
    /// nothing is attached, the working copy is unchanged, the subtree's ids are what the result
    /// lists as would-be created, and `ValueError` propagates.
    void Attach(const InsertPosition& position, Layer subtree);
    void Attach(const InsertPosition& position, Effect effect);

    /// Records that an import found `sha256` already stored.
    void NoteSkippedResource(std::string sha256) { skipped_.insert(std::move(sha256)); }

    json::Object& returned() { return returned_; }

private:
    friend class Transaction;
    explicit Edit(std::shared_ptr<const Project> base);
    template <typename Node>
    void AttachNode(const InsertPosition& position, Node node, const std::vector<Id>& ids);

    std::shared_ptr<const Project> base_;
    Project working_;
    std::set<std::string> skipped_;
    json::Object returned_;
    std::vector<Id> unattached_;  // ids of a subtree whose attachment failed
};

class Transaction {
public:
    /// Takes the document lock (waiting for an open transaction of another thread) and decides
    /// the request with `DecideAdmission`; only `execute` keeps the lock and opens the
    /// transaction. Throws `ValueError` for an empty tool or key, `std::logic_error` when this
    /// thread already holds an open transaction of the document.
    Transaction(Document& document, MutationRequest request);
    ~Transaction();

    Transaction(const Transaction&) = delete;
    Transaction& operator=(const Transaction&) = delete;

    const AdmissionDecision& decision() const { return decision_; }
    /// Admitted and neither committed nor rolled back.
    bool open() const { return lock_.owns_lock(); }
    /// A call failed: no further call applies and `Commit` commits nothing.
    bool failed() const { return failure_.has_value(); }

    /// Runs one call on the working copy. If it throws, the transaction is failed: the exception
    /// propagates and a later `Commit` commits nothing. Throws `std::logic_error` when the
    /// transaction is not open or has already failed.
    void Apply(const std::function<void(Edit&)>& call);

    /// Ends the transaction. Not admitted: the decision only. Failed, invalid or refused by the
    /// commit sink: a failed result, nothing changed. Unchanged project: a no-op result. Otherwise
    /// the next revision and its operation record are published. Releases the document lock.
    RequestOutcome Commit();

    /// Discards every call and releases the document lock.
    void Rollback();

private:
    void Release();
    TransactionResult Failed(std::string type, std::string message, ChangeSet would_change) const;

    Document& document_;
    MutationRequest request_;
    std::string request_hash_;
    AdmissionDecision decision_;
    std::unique_lock<std::mutex> lock_;
    std::unique_ptr<Edit> edit_;
    std::int64_t base_revision_ = 0;
    std::optional<TransactionResult> failure_;
};

/// One call = one transaction: admits `request`, applies `call`, commits. Never throws for a
/// failing call (the result says `failed`).
RequestOutcome Execute(Document& document, MutationRequest request, const std::function<void(Edit&)>& call);

}  // namespace uzp::core
