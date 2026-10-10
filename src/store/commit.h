#pragma once

// The mutation commit and the stored admission decision (`docs/architecture/09-project-file-format.md`
// §4, `02-runtime-topology.md` §3, §5; ARC-02).
//
// Every committed mutation is one SQLite transaction: the new blobs (and their `blob_meta`
// names, or the locators of a non-portable project), the rows of the commit extensions (the plane
// rows, versions and chunk rows of planes.h first), the `revision` row (`kind = mutation`, the
// zstd canonical manifest and its `manifest_sha256`), the request's `operation` row
// `{project_uuid, idempotency_key, request_hash, outcome, committed_revision}`, the update of
// `checkpoint('current')` and the versions in `meta`. Anything that fails rolls the whole
// transaction back: a failed mutation writes no row. The file at rest therefore always holds the
// last committed revision, and a lost acknowledgement is resolved from the file alone.

#include <cstdint>
#include <filesystem>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include "store/container.h"
#include "uzp_core/document/document.h"
#include "uzp_core/operation/operation.h"

namespace uzp::store {

/// Writes further rows of a revision inside its SQLite transaction (after the blobs, before the
/// revision row); throwing rolls the commit back.
using CommitExtension = std::function<void(Container& container, const core::Snapshot& snapshot)>;

/// Resource content staged for the next commit, by SHA-256.
struct PendingContent {
    struct Bytes {
        std::string bytes;
        std::string mime;
    };
    std::map<std::string, Bytes, std::less<>> blobs;
    std::map<std::string, std::filesystem::path, std::less<>> locators;  // non-portable projects only

    void clear() {
        blobs.clear();
        locators.clear();
    }
};

/// Makes every resource of `project` stored: inserts the staged bytes (or, for a non-portable
/// project, the staged locators) of resources the file does not hold yet and a `blob_meta` row per
/// resource name. Throws `StoreError(missing_resource)` for a resource with neither stored nor
/// staged content (a portable project embeds every dependency).
void WriteResources(Container& container, const core::Project& project, const PendingContent& pending, bool portable);

/// Inserts a `revision` row with the zstd canonical manifest of `project` and its SHA-256, and
/// mirrors the project's versions into `meta`.
void WriteRevision(Container& container, std::int64_t revision, std::optional<std::int64_t> parent,
                   std::string_view kind, const core::Project& project);

/// The mutation commit described above. `snapshot.revision` must follow the stored
/// `checkpoint('current')` and `record` must name it (`StoreError(conflict)` otherwise).
void CommitMutation(Container& container, const core::Snapshot& snapshot, const core::OperationRecord& record,
                    const PendingContent& pending, bool portable, const std::vector<CommitExtension>& extensions);

/// `checkpoint('current')`; `StoreError(corrupt)` when absent.
std::int64_t ReadCurrentRevision(Container& container);
/// `meta.operation_horizon_revision` (0 when absent).
std::int64_t ReadHorizon(Container& container);
/// The `operation` row of `key`, if any. Throws `StoreError(corrupt)` when it does not decode or
/// belongs to another project.
std::optional<core::OperationRecord> ReadOperation(Container& container, std::string_view project_uuid,
                                                   std::string_view key);
/// Every readable `operation` row, by committed revision. A row that fails the checks of
/// `ReadOperation` is left out and its key appended to `unreadable` (`CheckIntegrity` reports it,
/// and `DecideStored` answers its key with `outcome_unknown`).
std::vector<core::OperationRecord> ReadOperations(Container& container, std::string_view project_uuid,
                                                  std::vector<std::string>& unreadable);

/// `DecideAdmission` against the stored rows: the request's key in `operation`, the current
/// revision from `checkpoint('current')` and the horizon from `meta.operation_horizon_revision`.
/// Rows that cannot be read give `records_readable = false` (`outcome_unknown`), with
/// `fallback_revision` as the current revision.
core::AdmissionDecision DecideStored(Container& container, std::string_view project_uuid,
                                     const core::MutationRequest& request, std::int64_t fallback_revision);

}  // namespace uzp::store
