#pragma once

// Persistent caches of derived results (decision 253): content-addressed files under the user's
// local cache folder, `%LOCALAPPDATA%\UzPainter\cache\<area>` (`UZP_CACHE_DIR\<area>` when that
// variable is set), shared by every UzPainter process of the user. The evaluator keeps the
// channel read-outs and virtual normals export and capture consume (evaluator/result_cache.h),
// the preview its environment lighting (preview/environment.h).
//
// An entry is a 56-byte header followed by the payload: magic "UZPC", format version (u32), the
// 32-byte key, payload size (u64) and XXH64 of the payload (u64), little-endian. It is written to
// a temporary file of its own, then moved over the entry's name in one atomic replace, so a
// reader sees a whole entry or none. A read that finds anything inconsistent (magic, version,
// key, a size other than the caller's, a short file, the checksum) deletes the file it read and
// reports a miss: the caller computes the result again and stores it. A hit marks the entry as
// used (its last-write time); after every write the least recently used entries are removed
// until the area fits its cap. Two processes that store one key store the same bytes; a replace
// that finds the entry held by a reader is dropped.
//
// The caches are off unless the process enables them: `UzPainter.exe` does, unless `--no-cache`
// is given or `UZP_NO_CACHE` is set (src/main.cpp); a library or test binary does nothing until
// it calls `EnableCaches`. A key is the caller's: it must cover every input of the cached
// result, `BuildFingerprint()` and `FloatControlBits()` included.

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <mutex>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace uzp::render {

/// The key of an entry: a SHA-256 the caller computes over everything the result depends on.
using CacheKey = std::array<uint8_t, 32>;

class DiskCache {
public:
    struct Stats {
        uint64_t hits = 0;
        uint64_t misses = 0;
        /// Entries found inconsistent (removed and reported as misses).
        uint64_t corrupt = 0;
        uint64_t writes = 0;
        /// Entries that could not be written (the result was still returned).
        uint64_t writeFailures = 0;
        uint64_t evictions = 0;
    };

    DiskCache(std::filesystem::path directory, uint64_t maxBytes);

    /// The payload stored under `key`, which must be `size` bytes; nullopt when there is none or
    /// it is inconsistent (then removed).
    [[nodiscard]] std::optional<std::vector<std::byte>> Get(const CacheKey& key, uint64_t size);

    /// Stores `payload` under `key`, then evicts down to the cap. False when it could not be
    /// written, or is larger than the cap; never throws.
    bool Put(const CacheKey& key, std::span<const std::byte> payload);

    [[nodiscard]] std::filesystem::path EntryPath(const CacheKey& key) const;
    [[nodiscard]] const std::filesystem::path& Directory() const { return m_directory; }
    [[nodiscard]] uint64_t MaxBytes() const { return m_maxBytes; }
    [[nodiscard]] Stats GetStats() const;

private:
    void Evict();
    void Count(uint64_t Stats::*field);

    std::filesystem::path m_directory;
    uint64_t m_maxBytes;
    mutable std::mutex m_mutex;
    Stats m_stats;
};

/// The caches' root: `UZP_CACHE_DIR` when it is set and not empty, else
/// `%LOCALAPPDATA%\UzPainter\cache`; empty when neither can be resolved.
[[nodiscard]] std::filesystem::path DefaultCacheRoot();

/// True when `UZP_NO_CACHE` is set to anything but empty or "0".
[[nodiscard]] bool CachesDisabledByEnvironment();

/// Turns the caches on under `root` for this process (off when `root` is empty).
void EnableCaches(std::filesystem::path root);
/// Turns the caches off for this process.
void DisableCaches();
/// The root of the enabled caches; empty when they are off.
[[nodiscard]] std::filesystem::path EnabledCacheRoot();

/// The area `name` of the enabled caches (`<root>\<name>`), capped at `maxBytes`; null when the
/// caches are off. The object lives as long as the process.
[[nodiscard]] DiskCache* CacheArea(std::string_view name, uint64_t maxBytes);

/// The identity of the code computing cached results, the same for one build on one machine:
/// XXH64 of the bytes of the module holding this code (UzPainter.exe, or a test binary), XXH64
/// of the bytes of the loaded `ucrtbase.dll` (whose `pow`, `acos` and `atan2` the evaluator and
/// the lighting call), the CPU's vendor, signature and feature words and the extended state the
/// OS enables (the CRT picks code paths by them), and the format version of the entries.
/// Computed once per process, on first use.
[[nodiscard]] const std::string& BuildFingerprint();

/// The control bits of the calling thread's MXCSR (rounding, flush-to-zero, denormals-are-zero,
/// exception masks): the float environment the CPU computes in.
[[nodiscard]] uint32_t FloatControlBits();

/// The areas `UzPainter.exe cache` reports and clears.
inline constexpr std::array<std::string_view, 2> kCacheAreas{"eval", "lighting"};

/// `UzPainter.exe cache info|clear` (decision 253): `info` prints the root and each area's entries
/// and bytes as one JSON object; `clear` removes every entry and temporary file of the areas
/// (files in use are skipped and counted). Only files named as entries are touched, and reparse
/// points are never followed. Exit status 0, or 2 for a usage error.
[[nodiscard]] bool IsCacheCommand(std::string_view verb);
int RunCacheCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err);

}  // namespace uzp::render
