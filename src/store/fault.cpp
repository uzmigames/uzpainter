// Test-only fault hooks (see fault.h). Compiles to nothing unless `UZP_STORE_FAULT_HOOKS` is
// defined.

#include "store/fault.h"

#if defined(UZP_STORE_FAULT_HOOKS)

#include <windows.h>

#include <atomic>
#include <mutex>
#include <stdexcept>

#include "sqlite3.h"

namespace uzp::store::fault {
namespace {

std::atomic<Fault> g_armed{Fault::none};
std::atomic<bool> g_in_commit{false};
std::atomic<bool> g_in_vacuum{false};

struct FaultFile {
    sqlite3_file base;
    sqlite3_file* real;
    bool main_db;
};

sqlite3_vfs* Real(sqlite3_vfs* vfs) { return static_cast<sqlite3_vfs*>(vfs->pAppData); }
sqlite3_file* Inner(sqlite3_file* file) { return reinterpret_cast<FaultFile*>(file)->real; }

[[noreturn]] void Kill() {
    TerminateProcess(GetCurrentProcess(), kKillExitCode);
    ExitProcess(kKillExitCode);
}

int Close(sqlite3_file* file) {
    sqlite3_file* real = Inner(file);
    const int rc = real->pMethods ? real->pMethods->xClose(real) : SQLITE_OK;
    file->pMethods = nullptr;
    return rc;
}
int Read(sqlite3_file* file, void* buffer, int amount, sqlite3_int64 offset) {
    return Inner(file)->pMethods->xRead(Inner(file), buffer, amount, offset);
}
int Write(sqlite3_file* file, const void* buffer, int amount, sqlite3_int64 offset) {
    auto* f = reinterpret_cast<FaultFile*>(file);
    const Fault armed = g_armed.load();
    if (f->main_db && armed == Fault::disk_full) {
        sqlite3_int64 size = 0;
        const int rc = f->real->pMethods->xFileSize(f->real, &size);
        if (rc != SQLITE_OK) return rc;
        if (offset + amount > size) return SQLITE_FULL;
    }
    // While `VACUUM INTO` runs, the only database file written is its output.
    const bool vacuum_output = f->main_db && g_in_vacuum.load();
    if (vacuum_output && armed == Fault::fail_during_vacuum) return SQLITE_IOERR_WRITE;
    const int rc = f->real->pMethods->xWrite(f->real, buffer, amount, offset);
    if (f->main_db && armed == Fault::kill_during_commit && g_in_commit.load()) Kill();
    if (vacuum_output && armed == Fault::kill_during_vacuum) Kill();
    return rc;
}
int Truncate(sqlite3_file* file, sqlite3_int64 size) { return Inner(file)->pMethods->xTruncate(Inner(file), size); }
int Sync(sqlite3_file* file, int flags) { return Inner(file)->pMethods->xSync(Inner(file), flags); }
int FileSize(sqlite3_file* file, sqlite3_int64* size) { return Inner(file)->pMethods->xFileSize(Inner(file), size); }
int Lock(sqlite3_file* file, int level) { return Inner(file)->pMethods->xLock(Inner(file), level); }
int Unlock(sqlite3_file* file, int level) { return Inner(file)->pMethods->xUnlock(Inner(file), level); }
int CheckReservedLock(sqlite3_file* file, int* out) {
    return Inner(file)->pMethods->xCheckReservedLock(Inner(file), out);
}
int FileControl(sqlite3_file* file, int op, void* arg) {
    return Inner(file)->pMethods->xFileControl(Inner(file), op, arg);
}
int SectorSize(sqlite3_file* file) { return Inner(file)->pMethods->xSectorSize(Inner(file)); }
int DeviceCharacteristics(sqlite3_file* file) {
    return Inner(file)->pMethods->xDeviceCharacteristics(Inner(file));
}

// Version 1: no shared memory and no memory mapping, so the store's DELETE journal is the only
// journal mode these connections can use.
const sqlite3_io_methods kMethods = {
    1, Close, Read, Write, Truncate, Sync, FileSize, Lock, Unlock, CheckReservedLock, FileControl,
    SectorSize, DeviceCharacteristics, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr,
};

int Open(sqlite3_vfs* vfs, sqlite3_filename name, sqlite3_file* file, int flags, int* out_flags) {
    auto* f = reinterpret_cast<FaultFile*>(file);
    f->base.pMethods = nullptr;
    f->real = reinterpret_cast<sqlite3_file*>(f + 1);
    f->main_db = (flags & SQLITE_OPEN_MAIN_DB) != 0;
    const int rc = Real(vfs)->xOpen(Real(vfs), name, f->real, flags, out_flags);
    if (rc == SQLITE_OK) f->base.pMethods = &kMethods;
    return rc;
}
int Delete(sqlite3_vfs* vfs, const char* name, int sync) { return Real(vfs)->xDelete(Real(vfs), name, sync); }
int Access(sqlite3_vfs* vfs, const char* name, int flags, int* out) {
    return Real(vfs)->xAccess(Real(vfs), name, flags, out);
}
int FullPathname(sqlite3_vfs* vfs, const char* name, int size, char* out) {
    return Real(vfs)->xFullPathname(Real(vfs), name, size, out);
}
void* DlOpen(sqlite3_vfs* vfs, const char* name) { return Real(vfs)->xDlOpen(Real(vfs), name); }
void DlError(sqlite3_vfs* vfs, int size, char* out) { Real(vfs)->xDlError(Real(vfs), size, out); }
void (*DlSym(sqlite3_vfs* vfs, void* handle, const char* symbol))(void) {
    return Real(vfs)->xDlSym(Real(vfs), handle, symbol);
}
void DlClose(sqlite3_vfs* vfs, void* handle) { Real(vfs)->xDlClose(Real(vfs), handle); }
int Randomness(sqlite3_vfs* vfs, int size, char* out) { return Real(vfs)->xRandomness(Real(vfs), size, out); }
int Sleep(sqlite3_vfs* vfs, int microseconds) { return Real(vfs)->xSleep(Real(vfs), microseconds); }
int CurrentTime(sqlite3_vfs* vfs, double* out) { return Real(vfs)->xCurrentTime(Real(vfs), out); }
int GetLastError(sqlite3_vfs* vfs, int size, char* out) { return Real(vfs)->xGetLastError(Real(vfs), size, out); }
int CurrentTimeInt64(sqlite3_vfs* vfs, sqlite3_int64* out) {
    return Real(vfs)->xCurrentTimeInt64(Real(vfs), out);
}

constexpr const char* kVfsName = "uzp-fault";

}  // namespace

void Arm(Fault fault) { g_armed = fault; }
Fault Armed() { return g_armed.load(); }

const char* VfsName() {
    static std::once_flag once;
    std::call_once(once, [] {
        sqlite3_initialize();
        sqlite3_vfs* real = sqlite3_vfs_find(nullptr);
        if (real == nullptr || real->iVersion < 2) throw std::runtime_error("fault hooks: no default SQLite VFS");
        static sqlite3_vfs vfs{};
        vfs.iVersion = 2;
        vfs.szOsFile = static_cast<int>(sizeof(FaultFile)) + real->szOsFile;
        vfs.mxPathname = real->mxPathname;
        vfs.zName = kVfsName;
        vfs.pAppData = real;
        vfs.xOpen = Open;
        vfs.xDelete = Delete;
        vfs.xAccess = Access;
        vfs.xFullPathname = FullPathname;
        vfs.xDlOpen = DlOpen;
        vfs.xDlError = DlError;
        vfs.xDlSym = DlSym;
        vfs.xDlClose = DlClose;
        vfs.xRandomness = Randomness;
        vfs.xSleep = Sleep;
        vfs.xCurrentTime = CurrentTime;
        vfs.xGetLastError = GetLastError;
        vfs.xCurrentTimeInt64 = CurrentTimeInt64;
        if (sqlite3_vfs_register(&vfs, 0) != SQLITE_OK) throw std::runtime_error("fault hooks: VFS not registered");
    });
    return kVfsName;
}

void EnterCommit() { g_in_commit = true; }
void LeaveCommit() { g_in_commit = false; }

void AfterDurableCommit() {
    if (g_armed.load() == Fault::kill_after_commit) Kill();
}

void AfterPlaneRows() {
    if (g_armed.load() == Fault::kill_before_revision_row) Kill();
}

void EnterVacuum() { g_in_vacuum = true; }
void LeaveVacuum() { g_in_vacuum = false; }

bool BeforeRename() {
    const Fault armed = g_armed.load();
    if (armed == Fault::kill_before_rename) Kill();
    return armed == Fault::fail_rename;
}

}  // namespace uzp::store::fault

#endif
