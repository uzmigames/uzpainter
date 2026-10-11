#pragma once

// The saving vocabulary over the mutation history (`docs/architecture/09-project-file-format.md`
// §4; `03-project-model.md` §5; SAV-01, SAV-02, QG-05).
//
// Every committed mutation is already durable (the commit is the autosave). On top of it:
//
// - `checkpoint` rows: `current` (moved by every commit), `previous` (moved by `save()`) and the
//   named checkpoints `save()` writes. The last named checkpoint is the highest revision a named
//   row names: `save()` always names the current revision, which no earlier name exceeds.
// - `save()` (`SaveMode::incremental`, facade `ProjectSaveMode.Incremental`) writes a named row
//   for the current revision (`save-<revision>` unless a name is given) and, when the current
//   revision was not the last named checkpoint yet, moves `previous` to that checkpoint. A name
//   flagged `protected` is never overwritten: saving under it fails with
//   `StoreError(protected_checkpoint)` and changes nothing. `current` and `previous` are not names
//   a caller may give.
// - `needs_saving()` is `checkpoint('current') ≠` the last named checkpoint, exactly.
// - Revert appends a mutation whose project is the manifest of a retained revision (`compact.h`),
//   plane bindings included, with the project counter `next_id` kept at its current value (a
//   plane id or node id is never handed out twice); history stays append-only.

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "store/container.h"
#include "uzp_core/document/document.h"
#include "uzp_core/types/project.h"

namespace uzp::store {

inline constexpr std::string_view kCurrentCheckpoint = "current";
inline constexpr std::string_view kPreviousCheckpoint = "previous";

/// One `checkpoint` row.
struct CheckpointRow {
    std::string name;
    std::int64_t revision = 0;
    std::string created_at;
    std::string note;
    bool is_protected = false;

    bool operator==(const CheckpointRow&) const = default;
};

enum class SaveMode {
    incremental,  // `save()`: a named checkpoint
    full,         // `save(Full)`: a named checkpoint, then `compact`
};

struct SaveOptions {
    /// The checkpoint's name; empty: `save-<revision>`.
    std::string name;
    std::string note;
    /// An approved baseline (QG-05): never overwritten, never collapsed.
    bool protect = false;
};

/// Every `checkpoint` row, ordered by revision then name.
std::vector<CheckpointRow> ReadCheckpoints(Container& container);
/// The row `name`, if any.
std::optional<CheckpointRow> ReadCheckpoint(Container& container, std::string_view name);
/// The last named checkpoint: the highest revision a row other than `current` and `previous`
/// names; nothing before the first `save()`.
std::optional<std::int64_t> ReadNamedRevision(Container& container);
/// `checkpoint('previous')`, if any.
std::optional<std::int64_t> ReadPreviousRevision(Container& container);
/// `{current, named, previous}` as the file holds them.
core::Checkpoints ReadCheckpointState(Container& container);

/// `save-<revision>`.
std::string DefaultCheckpointName(std::int64_t revision);

/// The rows of `save()`, written in the caller's write transaction; returns the checkpoints
/// afterwards. Throws `StoreError(protected_checkpoint)` when `options.name` is a protected
/// checkpoint and `StoreError(conflict)` for the names `current` and `previous`.
core::Checkpoints WriteSaveCheckpoint(Container& container, const SaveOptions& options);

/// The revision checkpoint `name` names. Throws `StoreError(not_retained)` when there is no such
/// checkpoint.
std::int64_t ResolveCheckpoint(Container& container, std::string_view name);

/// The project a revert to `revision` commits: the verified manifest of `revision` (an older
/// minor migrated as `Open` does) with `next_id` = the larger of its own and `current.next_id`.
/// Throws `StoreError(not_retained)` when `revision` is outside the retained set
/// (`ComputeRetention`) and `CorruptionError` when its manifest does not verify.
core::Project RevertedProject(Container& container, std::int64_t revision, const core::Project& current);

}  // namespace uzp::store
