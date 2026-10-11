#pragma once

// The lock sidecar of an open project (`docs/architecture/09-project-file-format.md` §4, SAV-05).
//
// `<file>.uzp.lock` (the project path with `.lock` appended) holds the owning worker's pid and
// the start time of that process (`pid=<n>` and `started=<FILETIME ticks>` lines). Opening a
// project takes the lock: the owner keeps the sidecar open for writing, sharing reads only, for as
// long as it holds the lock, so the OS refuses a second owner and the delete of a held sidecar. The
// OS closes that handle when the owner dies; a sidecar no process holds open is stale whatever it
// records and is overwritten. The recorded owner is diagnostics (the `locked` error names its pid).
// Releasing the lock (`close`, the destructor) closes the handle and removes the sidecar.

#include <cstdint>
#include <filesystem>
#include <optional>

namespace uzp::store {

/// `<project>.lock`.
std::filesystem::path LockPath(const std::filesystem::path& project);

/// The owner a lock sidecar records.
struct LockOwner {
    std::uint32_t pid = 0;
    std::uint64_t started = 0;  // process creation time (FILETIME ticks)

    bool operator==(const LockOwner&) const = default;
};

/// This process as a lock owner.
LockOwner CurrentOwner();
/// The owner recorded in `lock`, or nothing when the file is absent or unreadable.
std::optional<LockOwner> ReadLockOwner(const std::filesystem::path& lock);
/// True while the process `owner` names runs (same pid, same start time); diagnostics only.
bool OwnerAlive(const LockOwner& owner);

/// A held project lock; move-only; releasing removes the sidecar.
class ProjectLock {
public:
    /// Takes the lock of `project` for this process. Throws `StoreError(locked)` naming the
    /// owner's pid while a live process holds it, and `StoreError(io)` when the sidecar cannot be
    /// written. A sidecar no process holds is stale and is replaced.
    static ProjectLock Acquire(const std::filesystem::path& project);

    ProjectLock() = default;
    ProjectLock(ProjectLock&& other) noexcept;
    ProjectLock& operator=(ProjectLock&& other) noexcept;
    ProjectLock(const ProjectLock&) = delete;
    ProjectLock& operator=(const ProjectLock&) = delete;
    ~ProjectLock();

    /// The sidecar's path (empty when not held).
    const std::filesystem::path& path() const { return path_; }
    bool held() const { return !path_.empty(); }
    /// Closes the sidecar and removes it; nothing when not held.
    void Release() noexcept;

private:
    ProjectLock(std::filesystem::path path, void* handle) : path_(std::move(path)), handle_(handle) {}
    std::filesystem::path path_;
    void* handle_ = nullptr;  // the sidecar's Windows HANDLE, open while held
};

}  // namespace uzp::store
