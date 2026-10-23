#include "uzp_core/document/document.h"

#include <algorithm>
#include <utility>

#include "uzp_core/types/errors.h"
#include "uzp_core/types/validation.h"

namespace uzp::core {

namespace {

std::string Revision(std::int64_t revision) { return std::to_string(revision); }

}  // namespace

Document::Document(DocumentState state) : project_uuid_(std::move(state.project_uuid)) {
    if (project_uuid_.empty()) throw ValueError("document: the project uuid is empty");
    if (state.revision < 0) throw ValueError("document: negative revision " + Revision(state.revision));
    Validate(state.project);
    const auto check_checkpoint = [&](const std::optional<std::int64_t>& checkpoint, const char* what) {
        if (checkpoint && (*checkpoint < 0 || *checkpoint > state.revision)) {
            throw ValueError(std::string("document: ") + what + " checkpoint " + Revision(*checkpoint) +
                             " is outside 0.." + Revision(state.revision));
        }
    };
    check_checkpoint(state.named_checkpoint, "named");
    check_checkpoint(state.previous_checkpoint, "previous");
    if (state.previous_checkpoint && (!state.named_checkpoint || *state.previous_checkpoint >= *state.named_checkpoint)) {
        throw ValueError("document: the previous checkpoint must precede the named checkpoint");
    }
    if (state.operation_horizon < 0 || state.operation_horizon > state.revision) {
        throw ValueError("document: operation horizon " + Revision(state.operation_horizon) + " is outside 0.." +
                         Revision(state.revision));
    }
    for (OperationRecord& record : state.operations) {
        if (record.project_uuid != project_uuid_) {
            throw ValueError("document: operation record '" + record.idempotency_key + "' belongs to project " +
                             record.project_uuid);
        }
        if (record.committed_revision <= state.operation_horizon || record.committed_revision > state.revision) {
            throw ValueError("document: operation record '" + record.idempotency_key + "' names revision " +
                             Revision(record.committed_revision) + ", outside the retained range");
        }
        const std::string key = record.idempotency_key;
        if (!operations_.emplace(key, std::move(record)).second) {
            throw ValueError("document: two operation records with key '" + key + "'");
        }
    }
    current_ = Snapshot{state.revision, std::make_shared<const Project>(std::move(state.project))};
    named_ = state.named_checkpoint;
    previous_ = state.previous_checkpoint;
    horizon_ = state.operation_horizon;
}

Snapshot Document::snapshot() const {
    std::lock_guard lock(state_mutex_);
    return current_;
}

std::int64_t Document::revision() const {
    std::lock_guard lock(state_mutex_);
    return current_.revision;
}

Checkpoints Document::checkpoints() const {
    std::lock_guard lock(state_mutex_);
    return Checkpoints{current_.revision, named_, previous_};
}

bool Document::NeedsSaving() const {
    std::lock_guard lock(state_mutex_);
    return named_ != current_.revision;
}

void Document::MarkCheckpoint() {
    std::lock_guard lock(state_mutex_);
    if (named_ == current_.revision) return;
    previous_ = named_;
    named_ = current_.revision;
}

std::optional<OperationRecord> Document::FindOperation(std::string_view key) const {
    std::lock_guard lock(state_mutex_);
    const auto found = operations_.find(key);
    if (found == operations_.end()) return std::nullopt;
    return found->second;
}

std::vector<OperationRecord> Document::operations() const {
    std::vector<OperationRecord> records;
    {
        std::lock_guard lock(state_mutex_);
        for (const auto& [key, record] : operations_) records.push_back(record);
    }
    std::sort(records.begin(), records.end(), [](const OperationRecord& a, const OperationRecord& b) {
        return a.committed_revision < b.committed_revision;
    });
    return records;
}

std::int64_t Document::operation_horizon() const {
    std::lock_guard lock(state_mutex_);
    return horizon_;
}

void Document::SetOperationHorizon(std::int64_t horizon) {
    std::lock_guard lock(state_mutex_);
    if (horizon < horizon_ || horizon > current_.revision) {
        throw ValueError("document: operation horizon " + Revision(horizon) + " is outside " + Revision(horizon_) +
                         ".." + Revision(current_.revision));
    }
    horizon_ = horizon;
    std::erase_if(operations_, [&](const auto& entry) { return entry.second.committed_revision <= horizon; });
}

void Document::SetCommitSink(CommitSink sink, const void* owner) {
    std::lock_guard lock(state_mutex_);
    sink_ = std::move(sink);
    sink_owner_ = sink_ ? owner : nullptr;
}

bool Document::HasCommitSink(const void* owner) const {
    std::lock_guard lock(state_mutex_);
    return bool(sink_) && sink_owner_ == owner;
}

}  // namespace uzp::core
