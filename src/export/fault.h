#pragma once

// Test-only fault hooks of the export publication (`docs/architecture/08-export.md` §5, task
// phase1.17_export-publication-receipts): terminate the process, or fail as an encoder or a disk
// would, between every publication step (publish.h) and around every fixed-name copy
// (fixed_names.h). Everything here exists only when `UZP_EXPORT_FAULT_HOOKS` is defined, which only
// the export test executable does (`build.zig`); `UzPainter.exe` contains none of it.

#if defined(UZP_EXPORT_FAULT_HOOKS)

#include <cstddef>
#include <string_view>

namespace uzp::exporter::fault {

enum class Point {
    none,
    /// Encoding file n throws, as a failing encoder would (the host must stay alive).
    fail_encode,
    /// Writing file n of the generation fails, as a full disk would.
    fail_write,
    /// Terminates the process after file n of the generation was written and flushed.
    kill_after_file,
    /// Terminates the process after the generation's plan.json was written.
    kill_after_plan,
    /// Terminates the process after the generation's receipt was written.
    kill_after_receipt,
    /// Terminates the process after the pointer's temporary file was written, before the rename.
    kill_before_pointer_rename,
    /// Terminates the process after the pointer was renamed into place, before the result returns.
    kill_after_pointer_rename,
    /// Terminates the process after fixed-name file n was staged, before its rename.
    kill_before_fixed_rename,
    /// Terminates the process after fixed-name file n was renamed, before the journal records it.
    kill_after_fixed_rename,
};

/// Exit code of a process terminated by a hook.
inline constexpr unsigned kKillExitCode = 77;

/// Arms `point` for the step with index `index` (file n; ignored by the single steps).
void Arm(Point point, std::size_t index);
/// Parses `<point>[:<index>]`; throws std::invalid_argument for an unknown point.
void Arm(std::string_view spec);

/// True when `point` is armed for `index` (the failing points: the caller fails).
bool Fails(Point point, std::size_t index = 0);
/// Terminates the process when `point` is armed for `index`.
void Reach(Point point, std::size_t index = 0);

}  // namespace uzp::exporter::fault

#endif
