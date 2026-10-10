#pragma once

// Operation records and the idempotency/precondition decision (ARC-02;
// `docs/architecture/09-project-file-format.md` §4, `02-runtime-topology.md` §3,
// `11-mcp-server.md` §4).
//
// Each committed transaction produces one `OperationRecord`, persisted by the project store in the
// same SQLite transaction as its revision; a failed or no-op call produces none. `DecideAdmission`
// is the single decision every mutation request goes through, in the document (`Transaction`),
// the project store and the worker: a known key and its `request_hash` are checked before the
// current revision.

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

#include "uzp_core/manifest/json.h"
#include "uzp_core/types/enums.h"

namespace uzp::core {

/// `{project_uuid, idempotency_key, request_hash, outcome, committed_revision}`. `outcome` is the
/// committed call's result object (`TransactionResult::ToJson`), returned unchanged to a retry.
struct OperationRecord {
    std::string project_uuid;
    std::string idempotency_key;
    std::string request_hash;
    json::Value outcome;
    std::int64_t committed_revision = 0;

    bool operator==(const OperationRecord&) const = default;
};

/// Lower-case hexadecimal SHA-256 of the canonical JSON (`json::WriteCanonical`) of
/// `{"arguments": <arguments>, "tool": <tool>}`. Independent of the order in which the arguments
/// were written; Python computes the same bytes with
/// `canonical_json({"tool": tool, "arguments": arguments})` (`tools/parity/recorder/job.py`).
std::string RequestHash(std::string_view tool, const json::Object& arguments);

/// One mutation request. `expected_revision` is the original base revision captured before the
/// first admission and preserved, with `idempotency_key`, on every retry.
struct MutationRequest {
    std::string tool;
    json::Object arguments;
    std::string idempotency_key;
    std::optional<std::int64_t> expected_revision;

    std::string request_hash() const { return RequestHash(tool, arguments); }
};

/// The five decisions of `09-…` §4, in the order they are checked.
enum class Admission { stored_outcome, idempotency_conflict, outcome_unknown, stale_revision, execute };

template <>
struct EnumTable<Admission> {
    static constexpr auto names = std::to_array<std::string_view>(
        {"stored_outcome", "idempotency_conflict", "outcome_unknown", "stale_revision", "execute"});
};

struct AdmissionInput {
    std::string request_hash;
    std::optional<std::int64_t> expected_revision;
    /// The record stored under the request's key in this project, if any.
    std::optional<OperationRecord> known;
    /// False when the operation records could not be read: the call cannot be resolved.
    bool records_readable = true;
    std::int64_t current_revision = 0;
    /// `meta.operation_horizon_revision`: the highest revision compaction has collapsed (0 before
    /// any compaction). A precondition below it is expired.
    std::int64_t horizon_revision = 0;
};

struct AdmissionDecision {
    Admission admission = Admission::execute;
    /// The known record (`stored_outcome`, `idempotency_conflict`).
    std::optional<OperationRecord> record;
    std::int64_t current_revision = 0;
    std::optional<std::int64_t> expected_revision;

    bool operator==(const AdmissionDecision&) const = default;
};

/// Records unreadable → `outcome_unknown`. Known key: same `request_hash` → `stored_outcome`
/// (even when the current revision is newer), different → `idempotency_conflict`. Unknown key:
/// missing precondition or one below the horizon → `outcome_unknown` (never executed); a
/// precondition other than the current revision → `stale_revision`; otherwise `execute`.
AdmissionDecision DecideAdmission(const AdmissionInput& input);

}  // namespace uzp::core
