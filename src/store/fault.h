#pragma once

// Test-only fault hooks of the project store (`docs/architecture/09-project-file-format.md` §4,
// §7): kill the process while SQLite writes the database during `COMMIT`, refuse database growth
// as a full disk does, kill the process between a commit's plane rows and its revision row, and
// kill the process after the durable commit before the result is returned. Everything here exists
// only when `UZP_STORE_FAULT_HOOKS` is defined, which only the store's test executable does
// (`build.zig`); `uzp_store.lib` and the application contain none of it.
//
// The hooks work through a SQLite VFS (`VfsName()`) that wraps the platform VFS and forwards
// every call; the store opens its connections through it in the test build.

#if defined(UZP_STORE_FAULT_HOOKS)

namespace uzp::store::fault {

enum class Fault {
    none,
    /// Terminates the process right after the first page write to the main database file made
    /// by the `COMMIT` statement: the rollback journal is hot and the file is torn.
    kill_during_commit,
    /// Every write that would grow the main database file fails with `SQLITE_FULL`.
    disk_full,
    /// Terminates the process after `COMMIT` returned, before the commit sink returns.
    kill_after_commit,
    /// Terminates the process inside the commit transaction, after the plane rows (plane
    /// versions, chunk blobs and chunk rows) were inserted and before the revision row.
    kill_before_revision_row,
};

/// Exit code of a process terminated by a hook.
inline constexpr unsigned kKillExitCode = 77;

void Arm(Fault fault);
Fault Armed();

/// The wrapping VFS, registered on first use.
const char* VfsName();

/// Brackets the `COMMIT` statement of a mutation (the window `kill_during_commit` acts in).
void EnterCommit();
void LeaveCommit();

/// Called after the durable commit; terminates the process when `kill_after_commit` is armed.
void AfterDurableCommit();

/// Called after the plane rows of a commit; terminates the process when
/// `kill_before_revision_row` is armed.
void AfterPlaneRows();

}  // namespace uzp::store::fault

#endif
