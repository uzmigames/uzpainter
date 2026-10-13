#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "render/disk_cache.h"

#include "render/xxhash64.h"

#include <windows.h>
#include <shlobj.h>

#include <cpuid.h>
#include <xmmintrin.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <map>
#include <memory>
#include <system_error>
#include <utility>

namespace uzp::render {

namespace fs = std::filesystem;

namespace {

// ── Entry files ──────────────────────────────────────────────────────────────

constexpr std::array<char, 4> kMagic = {'U', 'Z', 'P', 'C'};
constexpr uint32_t kFormatVersion = 1;
constexpr size_t kVersionOffset = 4;
constexpr size_t kKeyOffset = 8;
constexpr size_t kSizeOffset = 40;
constexpr size_t kChecksumOffset = 48;
constexpr size_t kHeaderSize = 56;
/// A temporary file older than this belongs to a writer that died (or stalled: its replace then
/// fails, and it drops the entry).
constexpr auto kStaleTemporary = std::chrono::hours(1);
constexpr std::wstring_view kTemporaryMarker = L".tmp-";

class Handle {
public:
    explicit Handle(HANDLE handle) : m_handle(handle) {}
    ~Handle() {
        if (ok()) CloseHandle(m_handle);
    }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    [[nodiscard]] bool ok() const { return m_handle != INVALID_HANDLE_VALUE; }
    [[nodiscard]] HANDLE get() const { return m_handle; }

private:
    HANDLE m_handle;
};

bool ReadExactly(HANDLE file, void* data, uint64_t size) {
    auto* out = static_cast<std::byte*>(data);
    while (size > 0) {
        const DWORD chunk = static_cast<DWORD>(std::min<uint64_t>(size, 1u << 30));
        DWORD read = 0;
        if (!ReadFile(file, out, chunk, &read, nullptr) || read == 0) return false;
        out += read;
        size -= read;
    }
    return true;
}

bool WriteExactly(HANDLE file, const void* data, uint64_t size) {
    const auto* in = static_cast<const std::byte*>(data);
    while (size > 0) {
        const DWORD chunk = static_cast<DWORD>(std::min<uint64_t>(size, 1u << 30));
        DWORD written = 0;
        if (!WriteFile(file, in, chunk, &written, nullptr) || written == 0) return false;
        in += written;
        size -= written;
    }
    return true;
}

uint64_t LoadU64(const std::byte* p) {
    uint64_t value = 0;
    for (int i = 0; i < 8; ++i) value |= static_cast<uint64_t>(p[i]) << (8 * i);
    return value;
}

void StoreU64(std::byte* p, uint64_t value) {
    for (int i = 0; i < 8; ++i) p[i] = static_cast<std::byte>((value >> (8 * i)) & 0xFF);
}

std::string HexOf(std::span<const uint8_t> bytes) {
    static constexpr char kDigits[] = "0123456789abcdef";
    std::string text;
    text.reserve(bytes.size() * 2);
    for (const uint8_t byte : bytes) {
        text.push_back(kDigits[byte >> 4]);
        text.push_back(kDigits[byte & 0xF]);
    }
    return text;
}

bool IsHexName(std::wstring_view name) {
    return name.size() == 64 && std::all_of(name.begin(), name.end(), [](wchar_t c) {
               return (c >= L'0' && c <= L'9') || (c >= L'a' && c <= L'f');
           });
}

bool IsEntryName(std::wstring_view name) { return IsHexName(name); }

bool IsTemporaryName(std::wstring_view name) {
    return name.size() > 64 && IsHexName(name.substr(0, 64)) && name.substr(64).starts_with(kTemporaryMarker);
}

/// `<root>\<name>`.
fs::path AreaPath(const fs::path& root, std::string_view name) {
    return root / fs::path(std::u8string(name.begin(), name.end()));
}

bool IsReparsePoint(const fs::path& path) {
    const DWORD attributes = GetFileAttributesW(path.c_str());
    return attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0;
}

// ── Process settings ─────────────────────────────────────────────────────────

std::mutex g_settingsMutex;
fs::path g_root;  // empty: the caches are off
std::map<fs::path, std::unique_ptr<DiskCache>> g_areas;

// ── Fingerprint ──────────────────────────────────────────────────────────────

fs::path ModulePath(HMODULE module) {
    std::wstring path(MAX_PATH, L'\0');
    for (;;) {
        const DWORD length = GetModuleFileNameW(module, path.data(), static_cast<DWORD>(path.size()));
        if (length == 0) return {};
        if (length < path.size()) {
            path.resize(length);
            return fs::path(path);
        }
        path.resize(path.size() * 2);
    }
}

/// XXH64 of the file's bytes; nullopt when it cannot be read.
std::optional<uint64_t> HashFile(const fs::path& path) {
    if (path.empty()) return std::nullopt;
    Handle file(CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING,
                            FILE_FLAG_SEQUENTIAL_SCAN, nullptr));
    LARGE_INTEGER length{};
    if (!file.ok() || !GetFileSizeEx(file.get(), &length)) return std::nullopt;
    std::vector<std::byte> bytes(static_cast<size_t>(length.QuadPart));
    if (!ReadExactly(file.get(), bytes.data(), bytes.size())) return std::nullopt;
    return Xxh64(bytes);
}

std::string Hex32(uint32_t value) {
    char buffer[12];
    std::snprintf(buffer, sizeof(buffer), "%08x", value);
    return buffer;
}

std::string Hex64(uint64_t value) {
    char buffer[20];
    std::snprintf(buffer, sizeof(buffer), "%016llx", static_cast<unsigned long long>(value));
    return buffer;
}

/// The CPU's vendor, signature (leaf 1 EAX) and feature words (leaf 1 ECX, EDX; leaf 7 EBX, ECX,
/// EDX) and, when the OS uses XSAVE, the extended state it enables (XCR0).
std::string CpuIdentity() {
    unsigned int a = 0;
    unsigned int b = 0;
    unsigned int c = 0;
    unsigned int d = 0;
    if (!__get_cpuid(0, &a, &b, &c, &d)) return "cpu unknown";
    const unsigned int maxLeaf = a;
    char vendor[13] = {};
    std::memcpy(vendor, &b, 4);
    std::memcpy(vendor + 4, &d, 4);
    std::memcpy(vendor + 8, &c, 4);
    std::string identity = std::string("cpu ") + vendor;
    __get_cpuid(1, &a, &b, &c, &d);
    const unsigned int features = c;
    identity += " " + Hex32(a) + " " + Hex32(c) + " " + Hex32(d);
    if (maxLeaf >= 7) {
        __get_cpuid_count(7, 0, &a, &b, &c, &d);
        identity += " " + Hex32(b) + " " + Hex32(c) + " " + Hex32(d);
    }
    if ((features & (1u << 27)) != 0) {  // OSXSAVE
        uint32_t low = 0;
        uint32_t high = 0;
        __asm__ volatile("xgetbv" : "=a"(low), "=d"(high) : "c"(0));
        identity += " xcr0 " + Hex64((uint64_t{high} << 32) | low);
    }
    return identity;
}

std::string ComputeFingerprint() {
    HMODULE self = nullptr;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                            reinterpret_cast<LPCWSTR>(&ComputeFingerprint), &self)) {
        return {};
    }
    const std::optional<uint64_t> module = HashFile(ModulePath(self));
    if (!module) return {};
    std::string fingerprint = "entries " + std::to_string(kFormatVersion) + "; module " + Hex64(*module);
    if (HMODULE crt = GetModuleHandleW(L"ucrtbase.dll")) {
        const std::optional<uint64_t> hash = HashFile(ModulePath(crt));
        if (!hash) return {};
        fingerprint += "; ucrtbase " + Hex64(*hash);
    } else {
        fingerprint += "; ucrtbase none";
    }
    return fingerprint + "; " + CpuIdentity();
}

// ── Command line ─────────────────────────────────────────────────────────────

std::string Utf8(const fs::path& path) {
    const std::u8string text = path.u8string();
    return std::string(text.begin(), text.end());
}

std::string JsonString(std::string_view text) {
    std::string out = "\"";
    for (const char c : text) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    char escaped[8];
                    std::snprintf(escaped, sizeof(escaped), "\\u%04x", static_cast<unsigned int>(c));
                    out += escaped;
                } else {
                    out.push_back(c);
                }
        }
    }
    return out + "\"";
}

struct AreaFiles {
    uint64_t entries = 0;
    uint64_t bytes = 0;
    uint64_t removed = 0;
    uint64_t removedBytes = 0;
    uint64_t skipped = 0;
};

/// The entries and temporary files of one area; with `remove`, each is deleted.
AreaFiles ScanArea(const fs::path& directory, bool remove) {
    AreaFiles files;
    std::error_code ec;
    if (!fs::is_directory(directory, ec) || IsReparsePoint(directory)) return files;
    for (fs::directory_iterator it(directory, ec), end; !ec && it != end; it.increment(ec)) {
        const fs::path path = it->path();
        const std::wstring name = path.filename().wstring();
        std::error_code entryError;
        if (!(IsEntryName(name) || IsTemporaryName(name)) || !it->is_regular_file(entryError) || IsReparsePoint(path)) {
            continue;
        }
        const uint64_t bytes = it->file_size(entryError);
        if (entryError) continue;
        ++files.entries;
        files.bytes += bytes;
        if (!remove) continue;
        if (DeleteFileW(path.c_str())) {
            ++files.removed;
            files.removedBytes += bytes;
        } else {
            ++files.skipped;
        }
    }
    return files;
}

}  // namespace

// ── DiskCache ────────────────────────────────────────────────────────────────

DiskCache::DiskCache(fs::path directory, uint64_t maxBytes)
    : m_directory(std::move(directory)), m_maxBytes(maxBytes) {}

fs::path DiskCache::EntryPath(const CacheKey& key) const { return m_directory / HexOf(key); }

DiskCache::Stats DiskCache::GetStats() const {
    std::lock_guard lock(m_mutex);
    return m_stats;
}

void DiskCache::Count(uint64_t Stats::*field) {
    std::lock_guard lock(m_mutex);
    ++(m_stats.*field);
}

std::optional<std::vector<std::byte>> DiskCache::Get(const CacheKey& key, uint64_t size) {
    const fs::path path = EntryPath(key);
    // Shared for deletion, so a writer can replace the name and an eviction remove it while this
    // reads; this handle keeps reading the file it opened.
    Handle file(CreateFileW(path.c_str(), GENERIC_READ | FILE_WRITE_ATTRIBUTES | DELETE,
                            FILE_SHARE_READ | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN,
                            nullptr));
    if (!file.ok()) {
        Count(&Stats::misses);
        return std::nullopt;
    }
    auto inconsistent = [&]() -> std::optional<std::vector<std::byte>> {
        // Deletes the file this handle read, never one that has replaced its name since.
        FILE_DISPOSITION_INFO disposition{TRUE};
        SetFileInformationByHandle(file.get(), FileDispositionInfo, &disposition, sizeof(disposition));
        Count(&Stats::corrupt);
        Count(&Stats::misses);
        return std::nullopt;
    };
    LARGE_INTEGER length{};
    std::array<std::byte, kHeaderSize> header{};
    if (!GetFileSizeEx(file.get(), &length) || static_cast<uint64_t>(length.QuadPart) != kHeaderSize + size ||
        !ReadExactly(file.get(), header.data(), kHeaderSize)) {
        return inconsistent();
    }
    uint32_t version = 0;
    std::memcpy(&version, header.data() + kVersionOffset, sizeof(version));
    if (std::memcmp(header.data(), kMagic.data(), kMagic.size()) != 0 || version != kFormatVersion ||
        std::memcmp(header.data() + kKeyOffset, key.data(), key.size()) != 0 ||
        LoadU64(header.data() + kSizeOffset) != size) {
        return inconsistent();
    }
    std::vector<std::byte> payload(static_cast<size_t>(size));
    if (!ReadExactly(file.get(), payload.data(), payload.size()) ||
        Xxh64(payload) != LoadU64(header.data() + kChecksumOffset)) {
        return inconsistent();
    }
    // Recently used: the eviction keeps it longer. A failed touch still serves the entry.
    FILETIME now{};
    GetSystemTimeAsFileTime(&now);
    SetFileTime(file.get(), nullptr, nullptr, &now);
    Count(&Stats::hits);
    return payload;
}

bool DiskCache::Put(const CacheKey& key, std::span<const std::byte> payload) {
    if (kHeaderSize + payload.size() > m_maxBytes) {
        Count(&Stats::writeFailures);
        return false;
    }
    std::error_code ec;
    fs::create_directories(m_directory, ec);
    const fs::path path = EntryPath(key);
    static std::atomic<uint64_t> counter{0};
    const fs::path temporary =
        m_directory / (path.filename().wstring() + std::wstring(kTemporaryMarker) +
                       std::to_wstring(GetCurrentProcessId()) + L"-" + std::to_wstring(GetCurrentThreadId()) + L"-" +
                       std::to_wstring(counter.fetch_add(1)));
    std::array<std::byte, kHeaderSize> header{};
    std::memcpy(header.data(), kMagic.data(), kMagic.size());
    std::memcpy(header.data() + kVersionOffset, &kFormatVersion, sizeof(kFormatVersion));
    std::memcpy(header.data() + kKeyOffset, key.data(), key.size());
    StoreU64(header.data() + kSizeOffset, payload.size());
    StoreU64(header.data() + kChecksumOffset, Xxh64(payload));
    bool written = false;
    {
        Handle file(CreateFileW(temporary.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr));
        written = file.ok() && WriteExactly(file.get(), header.data(), header.size()) &&
                  WriteExactly(file.get(), payload.data(), payload.size());
    }
    if (!written || !MoveFileExW(temporary.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING)) {
        DeleteFileW(temporary.c_str());
        Count(&Stats::writeFailures);
        return false;
    }
    Count(&Stats::writes);
    Evict();
    return true;
}

void DiskCache::Evict() {
    struct Entry {
        fs::path path;
        uint64_t bytes = 0;
        fs::file_time_type time;
    };
    std::vector<Entry> entries;
    uint64_t total = 0;
    const fs::file_time_type now = fs::file_time_type::clock::now();
    std::error_code ec;
    for (fs::directory_iterator it(m_directory, ec), end; !ec && it != end; it.increment(ec)) {
        const std::wstring name = it->path().filename().wstring();
        std::error_code entryError;
        if (!it->is_regular_file(entryError)) continue;
        const fs::file_time_type time = it->last_write_time(entryError);
        if (entryError) continue;
        if (IsTemporaryName(name)) {
            if (now - time > kStaleTemporary) fs::remove(it->path(), entryError);
            continue;
        }
        if (!IsEntryName(name)) continue;
        const uint64_t bytes = it->file_size(entryError);
        if (entryError) continue;
        entries.push_back({it->path(), bytes, time});
        total += bytes;
    }
    if (total <= m_maxBytes) return;
    std::sort(entries.begin(), entries.end(), [](const Entry& a, const Entry& b) { return a.time < b.time; });
    for (const Entry& entry : entries) {
        if (total <= m_maxBytes) break;
        // An entry a reader holds is still removed (readers share deletion); one that cannot be
        // removed stays and the next write tries again.
        if (DeleteFileW(entry.path.c_str())) {
            total -= entry.bytes;
            Count(&Stats::evictions);
        }
    }
}

// ── Process settings ─────────────────────────────────────────────────────────

fs::path DefaultCacheRoot() {
    if (const wchar_t* overridden = _wgetenv(L"UZP_CACHE_DIR"); overridden != nullptr && *overridden != L'\0') {
        return fs::path(overridden);
    }
    // FOLDERID_LocalAppData {F1B32785-6FBA-4FCF-9D55-7B8E7F157091}.
    static const GUID kLocalAppData = {0xF1B32785, 0x6FBA, 0x4FCF, {0x9D, 0x55, 0x7B, 0x8E, 0x7F, 0x15, 0x70, 0x91}};
    PWSTR folder = nullptr;
    fs::path root;
    if (SUCCEEDED(SHGetKnownFolderPath(kLocalAppData, KF_FLAG_DEFAULT, nullptr, &folder))) {
        root = fs::path(folder) / L"UzPainter" / L"cache";
    }
    CoTaskMemFree(folder);
    return root;
}

bool CachesDisabledByEnvironment() {
    const wchar_t* value = _wgetenv(L"UZP_NO_CACHE");
    return value != nullptr && *value != L'\0' && std::wstring_view(value) != L"0";
}

void EnableCaches(fs::path root) {
    std::lock_guard lock(g_settingsMutex);
    g_root = std::move(root);
}

void DisableCaches() {
    std::lock_guard lock(g_settingsMutex);
    g_root.clear();
}

fs::path EnabledCacheRoot() {
    std::lock_guard lock(g_settingsMutex);
    return g_root;
}

DiskCache* CacheArea(std::string_view name, uint64_t maxBytes) {
    const fs::path root = EnabledCacheRoot();
    // Without the code's identity no key can be trusted across processes.
    if (root.empty() || BuildFingerprint().empty()) return nullptr;
    const fs::path directory = AreaPath(root, name);
    std::lock_guard lock(g_settingsMutex);
    std::unique_ptr<DiskCache>& area = g_areas[directory];
    if (!area) area = std::make_unique<DiskCache>(directory, maxBytes);
    return area.get();
}

const std::string& BuildFingerprint() {
    static const std::string fingerprint = ComputeFingerprint();
    return fingerprint;
}

uint32_t FloatControlBits() { return _mm_getcsr() & ~0x3Fu; }

// ── Command line ─────────────────────────────────────────────────────────────

bool IsCacheCommand(std::string_view verb) { return verb == "cache"; }

int RunCacheCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err) {
    constexpr const char* kUsage = "usage: UzPainter.exe cache info | clear\n";
    if (args.size() != 2 || (args[1] != "info" && args[1] != "clear")) {
        std::fputs(kUsage, err);
        return 2;
    }
    const bool clear = args[1] == "clear";
    const fs::path root = DefaultCacheRoot();
    std::string json = "{\"root\":" + JsonString(Utf8(root));
    if (!clear) json += std::string(",\"enabled\":") + (EnabledCacheRoot().empty() ? "false" : "true");
    json += ",\"areas\":{";
    for (size_t i = 0; i < kCacheAreas.size(); ++i) {
        const AreaFiles files = root.empty() ? AreaFiles{} : ScanArea(AreaPath(root, kCacheAreas[i]), clear);
        json += (i == 0 ? "" : ",") + JsonString(kCacheAreas[i]) + ":";
        json += clear ? "{\"removed\":" + std::to_string(files.removed) + ",\"bytes\":" + std::to_string(files.removedBytes) +
                            ",\"skipped\":" + std::to_string(files.skipped) + "}"
                      : "{\"entries\":" + std::to_string(files.entries) + ",\"bytes\":" + std::to_string(files.bytes) + "}";
    }
    json += "}}\n";
    std::fputs(json.c_str(), out);
    return 0;
}

}  // namespace uzp::render
