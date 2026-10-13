#pragma once

// SCRATCH profiling of wt/loadcache (load-cache track); reverted before the branch is used.
// With UZP_PROFILE=<dir>, every process appends `pid name dur_ms abs_start_ms` lines to
// <dir>/<pid>.tsv (abs: milliseconds since the Unix epoch, system clock).

#include <process.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <string>

namespace uzp_prof {

inline const char* Dir() {
    static const char* dir = std::getenv("UZP_PROFILE");
    return dir;
}

inline double NowAbsMs() {
    return std::chrono::duration<double, std::milli>(std::chrono::system_clock::now().time_since_epoch()).count();
}

inline void Line(const std::string& name, double startAbs, double durMs) {
    const char* dir = Dir();
    if (!dir) return;
    static std::mutex mutex;
    std::lock_guard lock(mutex);
    const int pid = _getpid();
    const std::string path = std::string(dir) + "\\" + std::to_string(pid) + ".tsv";
    if (FILE* f = std::fopen(path.c_str(), "ab")) {
        std::fprintf(f, "%d\t%s\t%.2f\t%.2f\n", pid, name.c_str(), durMs, startAbs);
        std::fclose(f);
    }
}

inline void Mark(const std::string& name) {
    if (Dir()) Line(name, NowAbsMs(), 0.0);
}

struct Scope {
    explicit Scope(std::string n) : name(std::move(n)), start(Dir() ? NowAbsMs() : 0.0) {}
    ~Scope() {
        if (Dir()) Line(name, start, NowAbsMs() - start);
    }
    std::string name;
    double start;
};

}  // namespace uzp_prof

#define UZP_PROF_CAT2(a, b) a##b
#define UZP_PROF_CAT(a, b) UZP_PROF_CAT2(a, b)
#define UZP_PROF(name) ::uzp_prof::Scope UZP_PROF_CAT(uzp_prof_scope_, __LINE__)(name)
