#include "store/lock.h"

#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include <fstream>
#include <string>
#include <utility>

#include "store/container.h"

namespace uzp::store {

namespace {

std::string Utf8(const std::filesystem::path& path) {
    const std::u8string text = path.u8string();
    return std::string(text.begin(), text.end());
}

std::uint64_t Ticks(const FILETIME& time) {
    return (static_cast<std::uint64_t>(time.dwHighDateTime) << 32) | time.dwLowDateTime;
}

std::optional<std::uint64_t> StartTime(HANDLE process) {
    FILETIME created{}, exited{}, kernel{}, user{};
    if (!GetProcessTimes(process, &created, &exited, &kernel, &user)) return std::nullopt;
    return Ticks(created);
}

/// Opens the sidecar for writing, sharing reads only, and records `owner` in it; nothing while
/// another handle holds it. The handle is kept for the lock's lifetime: no other process can then
/// open it for writing or delete it, and the OS closes it when the owner dies, so a sidecar nobody
/// holds is stale whatever it contains and is overwritten.
HANDLE CreateLockFile(const std::filesystem::path& lock, const LockOwner& owner) {
    const HANDLE file = CreateFileW(lock.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_ALWAYS,
                                    FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) {
        const DWORD error = GetLastError();
        if (error == ERROR_SHARING_VIOLATION) return nullptr;
        throw StoreError(StoreError::Code::io, "cannot create the lock " + Utf8(lock) + " (error " +
                                                   std::to_string(error) + ")");
    }
    const std::string text = "pid=" + std::to_string(owner.pid) + "\nstarted=" + std::to_string(owner.started) + "\n";
    DWORD written = 0;
    const bool ok = WriteFile(file, text.data(), static_cast<DWORD>(text.size()), &written, nullptr) &&
                    written == text.size() && FlushFileBuffers(file);
    if (!ok) {
        CloseHandle(file);
        DeleteFileW(lock.c_str());
        throw StoreError(StoreError::Code::io, "cannot write the lock " + Utf8(lock));
    }
    return file;
}

}  // namespace

std::filesystem::path LockPath(const std::filesystem::path& project) {
    std::filesystem::path lock = project;
    lock += ".lock";
    return lock;
}

LockOwner CurrentOwner() {
    return LockOwner{static_cast<std::uint32_t>(GetCurrentProcessId()), StartTime(GetCurrentProcess()).value_or(0)};
}

std::optional<LockOwner> ReadLockOwner(const std::filesystem::path& lock) {
    std::ifstream file(lock, std::ios::binary);
    if (!file) return std::nullopt;
    std::optional<std::uint64_t> pid, started;
    std::string line;
    while (std::getline(file, line)) {
        const std::size_t eq = line.find('=');
        if (eq == std::string::npos) return std::nullopt;
        const std::string key = line.substr(0, eq), value = line.substr(eq + 1);
        if (value.empty() || value.find_first_not_of("0123456789") != std::string::npos || value.size() > 20) {
            return std::nullopt;
        }
        try {
            const std::uint64_t number = std::stoull(value);
            if (key == "pid") pid = number;
            if (key == "started") started = number;
        } catch (const std::exception&) {
            return std::nullopt;
        }
    }
    if (!pid || !started || *pid == 0 || *pid > 0xffffffffu) return std::nullopt;
    return LockOwner{static_cast<std::uint32_t>(*pid), *started};
}

bool OwnerAlive(const LockOwner& owner) {
    const HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, owner.pid);
    if (process == nullptr) {
        // A process this user may not inspect exists; one that is gone cannot be opened at all.
        return GetLastError() == ERROR_ACCESS_DENIED;
    }
    const bool running = WaitForSingleObject(process, 0) == WAIT_TIMEOUT;
    const std::optional<std::uint64_t> started = StartTime(process);
    CloseHandle(process);
    return running && started == owner.started;
}

ProjectLock ProjectLock::Acquire(const std::filesystem::path& project) {
    const std::filesystem::path lock = LockPath(project);
    if (const HANDLE file = CreateLockFile(lock, CurrentOwner())) return ProjectLock(lock, file);
    // Held: the recorded pid is diagnostics only (the holder may not have written it yet).
    const std::optional<LockOwner> owner = ReadLockOwner(lock);
    throw StoreError(StoreError::Code::locked, Utf8(project) + " is open in " +
                                                   (owner ? "process " + std::to_string(owner->pid) : "another process") +
                                                   " (" + Utf8(lock) + ")");
}

ProjectLock::ProjectLock(ProjectLock&& other) noexcept
    : path_(std::exchange(other.path_, {})), handle_(std::exchange(other.handle_, nullptr)) {}

ProjectLock& ProjectLock::operator=(ProjectLock&& other) noexcept {
    if (this != &other) {
        Release();
        path_ = std::exchange(other.path_, {});
        handle_ = std::exchange(other.handle_, nullptr);
    }
    return *this;
}

ProjectLock::~ProjectLock() { Release(); }

void ProjectLock::Release() noexcept {
    if (path_.empty()) return;
    // Once the handle closes another worker may take the lock first; its handle then refuses the
    // delete, so only an unheld sidecar is removed.
    CloseHandle(handle_);
    handle_ = nullptr;
    DeleteFileW(path_.c_str());
    path_.clear();
}

}  // namespace uzp::store
