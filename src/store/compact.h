#pragma once

// Retention, reachability and compaction (`docs/architecture/09-project-file-format.md` §1, §4;
// owner answer Q11, decision 024; SAV-02, QG-05, ARC-02).
//
// The retained revisions are `checkpoint('current')`, the last named checkpoint (what `save()`
// marked last), `checkpoint('previous')`, the last `kRetainedMutations` revisions of kind
// `mutation` and the revision of every checkpoint flagged `protected`. `compact` collapses every
// other revision and every unprotected named checkpoint that names neither the last named
// checkpoint nor `previous`; it deletes the `operation` rows of the collapsed revisions and raises
// `meta.operation_horizon_revision` to the highest collapsed revision; it deletes the `plane`,
// `plane_version`, `plane_chunk`, `blob`, `blob_meta` and `locator` rows no retained manifest
// reaches and empties `cache`. Reachability is resolved through each retained manifest, so a chunk
// first written by a collapsed revision stays as long as a retained manifest binds a version that
// lists it.
//
// The file is rewritten, never edited in place: the project is copied to `<file>.compact`, the
// copy is collapsed and collected in one SQLite transaction, `VACUUM INTO` writes
// `<file>.vacuum`, and an atomic rename replaces the project file. An interruption at any point
// leaves the project file in its previous state; the temporary files are removed on failure and,
// after a killed worker, by the next `Open` (`RemoveTemporaryFiles`).

#include <cstdint>
#include <filesystem>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <vector>

#include "store/container.h"
#include "uzp_core/types/ids.h"

namespace uzp::store {

/// The mutation revisions retention keeps besides the checkpoints (owner Q11).
inline constexpr int kRetainedMutations = 50;

/// What retention keeps and why.
struct Retention {
    std::int64_t current = 0;
    std::optional<std::int64_t> named;     // the last named checkpoint
    std::optional<std::int64_t> previous;  // checkpoint('previous')
    std::vector<std::int64_t> mutations;   // the last kRetainedMutations mutation revisions, ascending
    std::set<std::int64_t> protected_revisions;
    std::set<std::int64_t> revisions;      // the union of the above
};

/// The retention set of the file as it is now. Throws `StoreError(corrupt)` without
/// `checkpoint('current')`.
Retention ComputeRetention(Container& container);

/// What one compaction did.
struct CompactResult {
    std::vector<std::int64_t> retained;   // ascending
    std::vector<std::int64_t> collapsed;  // ascending
    std::vector<std::string> removed_checkpoints;
    std::int64_t horizon = 0;  // meta.operation_horizon_revision afterwards
    std::int64_t removed_operations = 0;
    std::int64_t removed_planes = 0;
    std::int64_t removed_versions = 0;
    std::int64_t removed_chunks = 0;
    std::int64_t removed_blobs = 0;
    std::uintmax_t bytes_before = 0;
    std::uintmax_t bytes_after = 0;
};

/// The rows every retained manifest (each `revision` row) reaches: bound plane versions and their
/// planes, the chunk hashes of those versions, and every content hash a manifest names (resource
/// keys and any other SHA-256 value). Throws `CorruptionError` when a manifest or a binding does
/// not verify: nothing can be collected safely then.
struct Reachable {
    std::set<std::int64_t> versions;
    std::set<core::Id> planes;
    std::set<std::string, std::less<>> hashes;
};
Reachable ComputeReachable(Container& container);

/// Collapses and collects `container` in one write transaction (see above); fills everything of
/// the result but the byte counts.
CompactResult CollapseAndCollect(Container& container);

/// The message of `error` without its code prefix (for an error rethrown with the step it
/// failed in).
std::string ErrorDetail(const StoreError& error);

/// `<target>.<suffix>`.
std::filesystem::path SiblingPath(const std::filesystem::path& target, std::string_view suffix);

/// Removes the temporary files a killed `compact` or `save_as` may have left beside `project`
/// (`.compact`, `.vacuum` and their `-journal`).
void RemoveTemporaryFiles(const std::filesystem::path& project);

/// `VACUUM INTO output`: a consistent, closed copy of `source` with `journal_mode = DELETE` and no
/// `-wal`/`-shm`. Removes a partial output and throws `StoreError` naming the step on failure.
void VacuumInto(Container& source, const std::filesystem::path& output);

/// Atomically renames `from` to `to` (replacing an existing `to` only when `replace`), written
/// through to disk. Throws `StoreError(io)` naming the step; `from` is left for the caller.
void RenameFile(const std::filesystem::path& from, const std::filesystem::path& to, bool replace);

}  // namespace uzp::store
