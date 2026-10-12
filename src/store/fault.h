#pragma once

// Test-only fault hooks of the project store (`docs/architecture/09-project-file-format.md` §4,
// §7): kill the process while SQLite writes the database during `COMMIT`, refuse database growth
// as a full disk does, kill the process between a commit's plane rows and its revision row, kill
// the process after the durable commit before the result is returned, and kill the process or
// fail the I/O while `VACUUM INTO` writes its output and between `VACUUM INTO` and the rename
// (`compact`, `save_as`, `save_as_copy`; `compact.h`). Everything here exists
// only when `UZP_STORE_FAULT_HOOKS` is defined, which the store's test executables and a Debug
// `UzPainter.exe` do (`build.zig`; the worker's `test_fault` arms them inside a save, decision
// 151); `uzp_store.lib` and a release application contain none of it.
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
    /// Terminates the process right after the first page write to the output of `VACUUM INTO`:
    /// the temporary file is partial.
    kill_during_vacuum,
    /// Every page write to the output of `VACUUM INTO` fails with `SQLITE_IOERR_WRITE`.
    fail_during_vacuum,
    /// Terminates the process after `VACUUM INTO` completed, before the rename.
    kill_before_rename,
    /// The rename after `VACUUM INTO` fails as an I/O error would.
    fail_rename,
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

/// Brackets a `VACUUM INTO` statement (the window `kill_during_vacuum` and `fail_during_vacuum`
/// act in).
void EnterVacuum();
void LeaveVacuum();

/// Called between `VACUUM INTO` and the rename: terminates the process when `kill_before_rename`
/// is armed; returns true when `fail_rename` is armed (the caller fails the rename).
bool BeforeRename();

}  // namespace uzp::store::fault

#endif
