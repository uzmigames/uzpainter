#pragma once

// The lock sidecar of an open project (`docs/architecture/09-project-file-format.md` §4, SAV-05).
//
// `<file>.uzp.lock` (the project path with `.lock` appended) holds the owning worker's pid and
// the start time of that process (`pid=<n>` and `started=<FILETIME ticks>` lines). Opening a
// project takes the lock; a second owner is refused while the recorded process lives. A lock
// whose process has exited, whose pid now names a later process (another start time) or whose
// content cannot be read is stale and is replaced. Releasing the lock (`close`, the destructor)
// removes the sidecar.

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
/// True while the process `owner` names runs (same pid, same start time).
bool OwnerAlive(const LockOwner& owner);

/// A held project lock; move-only; releasing removes the sidecar.
class ProjectLock {
public:
    /// Takes the lock of `project` for this process. Throws `StoreError(locked)` naming the
    /// owner's pid while a live process holds it, and `StoreError(io)` when the sidecar cannot be
    /// written. A stale lock is replaced.
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
    /// Removes the sidecar; nothing when not held.
    void Release() noexcept;

private:
    explicit ProjectLock(std::filesystem::path path) : path_(std::move(path)) {}
    std::filesystem::path path_;
};

}  // namespace uzp::store
