#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "render/kernel_cache.h"

#include "render/xxhash64.h"
#include "shader_compiler.h"

#include <windows.h>
#include <shlobj.h>

#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <optional>
#include <system_error>
#include <thread>
#include <utility>

namespace uzp::render {

namespace fs = std::filesystem;

namespace {

// ── Canonical encoding ───────────────────────────────────────────────────────

void PutU64(std::string& out, uint64_t value) {
    for (int i = 0; i < 8; ++i) out.push_back(static_cast<char>((value >> (8 * i)) & 0xFF));
}

/// A length-prefixed field, so no two different field lists encode alike.
void PutField(std::string& out, std::string_view field) {
    PutU64(out, field.size());
    out.append(field);
}

uint64_t HashText(std::string_view text) {
    return Xxh64(std::as_bytes(std::span<const char>(text.data(), text.size())));
}

std::string Hex64(uint64_t value) {
    char buf[20];
    std::snprintf(buf, sizeof(buf), "%016llx", static_cast<unsigned long long>(value));
    return buf;
}

std::vector<const KernelInclude*> SortedIncludes(const KernelSource& source) {
    std::vector<const KernelInclude*> sorted;
    for (const KernelInclude& include : source.includes) sorted.push_back(&include);
    std::sort(sorted.begin(), sorted.end(),
              [](const KernelInclude* a, const KernelInclude* b) { return a->name < b->name; });
    return sorted;
}

/// A declared include name is a relative path below the include folder.
bool ValidIncludeName(const std::string& name) {
    if (name.empty() || name.find(':') != std::string::npos || name.front() == '/' ||
        name.front() == '\\') {
        return false;
    }
    for (const fs::path& part : fs::path(name)) {
        if (part == ".." || part == ".") return false;
    }
    return true;
}

// ── Entry files ──────────────────────────────────────────────────────────────
//
// An entry is a 32-byte header followed by the bytecode: magic "UZPK", format version (u32),
// key (u64), bytecode size (u64), XXH64 of the bytecode (u64), all little-endian.

constexpr std::array<char, 4> kEntryMagic = {'U', 'Z', 'P', 'K'};
constexpr uint32_t kEntryVersion = 1;
constexpr size_t kHeaderSize = 32;

enum class EntryState : uint8_t { Absent, Valid, Corrupt };

// The atomic-write suffix can exceed MAX_PATH even when the final include path fits.
// Extended Win32 paths require absolute paths and backslashes, including for the CRT.
fs::path IoPath(const fs::path& path) {
    std::wstring value = fs::absolute(path).lexically_normal().make_preferred().wstring();
    if (value.starts_with(L"\\\\?\\")) return value;
    if (value.starts_with(L"\\\\")) return L"\\\\?\\UNC\\" + value.substr(2);
    return L"\\\\?\\" + value;
}

uint64_t LoadU64(const uint8_t* p) {
    uint64_t v;
    std::memcpy(&v, p, sizeof(v));
    return v;
}

EntryState ReadEntry(const fs::path& path, uint64_t key, std::vector<uint8_t>& bytecode) {
    std::error_code ec;
    if (!fs::is_regular_file(IoPath(path), ec)) return EntryState::Absent;
    std::ifstream file(IoPath(path), std::ios::binary);
    if (!file) return EntryState::Corrupt;
    std::vector<uint8_t> data((std::istreambuf_iterator<char>(file)),
                              std::istreambuf_iterator<char>());
    if (data.size() < kHeaderSize) return EntryState::Corrupt;
    uint32_t version;
    std::memcpy(&version, data.data() + 4, sizeof(version));
    const uint64_t size = LoadU64(data.data() + 16);
    if (std::memcmp(data.data(), kEntryMagic.data(), kEntryMagic.size()) != 0 ||
        version != kEntryVersion || LoadU64(data.data() + 8) != key ||
        size != data.size() - kHeaderSize || size == 0) {
        return EntryState::Corrupt;
    }
    bytecode.assign(data.begin() + kHeaderSize, data.end());
    if (Xxh64(std::as_bytes(std::span<const uint8_t>(bytecode))) != LoadU64(data.data() + 24)) {
        bytecode.clear();
        return EntryState::Corrupt;
    }
    return EntryState::Valid;
}

/// Writes `data` to `path` through a temporary file in the same folder and an atomic replace,
/// so readers in other processes see the old file or the new one, never a partial one.
bool WriteAtomically(const fs::path& path, std::string_view data) {
    std::error_code ec;
    fs::create_directories(IoPath(path.parent_path()), ec);
    if (ec) return false;
    const fs::path temp =
        path.parent_path() /
        (path.filename().string() + ".tmp-" + std::to_string(GetCurrentProcessId()) + "-" +
         std::to_string(std::hash<std::thread::id>{}(std::this_thread::get_id())));
    {
        std::ofstream file(IoPath(temp), std::ios::binary | std::ios::trunc);
        file.write(data.data(), static_cast<std::streamsize>(data.size()));
        if (!file) {
            file.close();
            fs::remove(IoPath(temp), ec);
            return false;
        }
    }
    if (!MoveFileExW(IoPath(temp).c_str(), IoPath(path).c_str(), MOVEFILE_REPLACE_EXISTING)) {
        fs::remove(IoPath(temp), ec);
        return false;
    }
    return true;
}

bool WriteEntry(const fs::path& path, uint64_t key, const std::vector<uint8_t>& bytecode) {
    std::string data(kEntryMagic.data(), kEntryMagic.size());
    for (int i = 0; i < 4; ++i) data.push_back(static_cast<char>((kEntryVersion >> (8 * i)) & 0xFF));
    PutU64(data, key);
    PutU64(data, bytecode.size());
    PutU64(data, Xxh64(std::as_bytes(std::span<const uint8_t>(bytecode))));
    data.append(reinterpret_cast<const char*>(bytecode.data()), bytecode.size());
    return WriteAtomically(path, data);
}

std::string FileVersion(const fs::path& file) {
    DWORD handle = 0;
    const DWORD size = GetFileVersionInfoSizeW(file.c_str(), &handle);
    if (size == 0) return "unknown";
    std::vector<unsigned char> data(size);
    VS_FIXEDFILEINFO* info = nullptr;
    UINT len = 0;
    if (!GetFileVersionInfoW(file.c_str(), 0, size, data.data()) ||
        !VerQueryValueW(data.data(), L"\\", reinterpret_cast<void**>(&info), &len) || !info) {
        return "unknown";
    }
    return std::to_string(HIWORD(info->dwFileVersionMS)) + "." +
           std::to_string(LOWORD(info->dwFileVersionMS)) + "." +
           std::to_string(HIWORD(info->dwFileVersionLS)) + "." +
           std::to_string(LOWORD(info->dwFileVersionLS));
}

}  // namespace

// ── Key ──────────────────────────────────────────────────────────────────────

uint64_t KernelKey(const KernelSource& source, KernelTarget target,
                   std::string_view compilerVersion) {
    std::string encoded;
    PutField(encoded, "uzp-kernel-key/1");
    PutField(encoded, KernelTargetName(target));
    PutField(encoded, kKernelCompileFlags);
    PutField(encoded, compilerVersion);
    PutField(encoded, source.entryPoint);
    PutField(encoded, source.hlsl);
    PutU64(encoded, source.defines.size());
    for (const std::string& define : source.defines) PutField(encoded, define);
    const std::vector<const KernelInclude*> includes = SortedIncludes(source);
    PutU64(encoded, includes.size());
    for (const KernelInclude* include : includes) {
        PutField(encoded, include->name);
        PutField(encoded, include->text);
    }
    return HashText(encoded);
}

// ── Locations ────────────────────────────────────────────────────────────────

fs::path DefaultKernelCacheRoot() {
    // FOLDERID_LocalAppData {F1B32785-6FBA-4FCF-9D55-7B8E7F157091}.
    static const GUID kLocalAppData = {
        0xF1B32785, 0x6FBA, 0x4FCF, {0x9D, 0x55, 0x7B, 0x8E, 0x7F, 0x15, 0x70, 0x91}};
    PWSTR folder = nullptr;
    fs::path root;
    if (SUCCEEDED(SHGetKnownFolderPath(kLocalAppData, KF_FLAG_DEFAULT, nullptr, &folder))) {
        root = fs::path(folder) / L"UzPainter" / L"kernel-cache";
    }
    CoTaskMemFree(folder);
    return root;
}

fs::path DefaultDxcompilerPath() {
    std::wstring exe(MAX_PATH, L'\0');
    for (;;) {
        const DWORD length = GetModuleFileNameW(nullptr, exe.data(), static_cast<DWORD>(exe.size()));
        if (length < exe.size()) {
            exe.resize(length);
            break;
        }
        exe.resize(exe.size() * 2);
    }
    return fs::path(exe).parent_path() / L"dxcompiler.dll";
}

// ── DxcKernelCompiler ────────────────────────────────────────────────────────

Result<std::unique_ptr<DxcKernelCompiler>> DxcKernelCompiler::Load(const fs::path& dxcompiler) {
    std::unique_ptr<DxcKernelCompiler> self(new DxcKernelCompiler());
    self->m_compiler = std::make_unique<uz::ShaderCompiler>();
    if (!self->m_compiler->Init(dxcompiler.string())) {
        return Fail(ErrorCode::KernelCompileFailed, std::nullopt,
                    "DXC could not be loaded from " + dxcompiler.string());
    }
    self->m_version =
        "dxc " + self->m_compiler->GetVersion() + ", dxcompiler.dll " + FileVersion(dxcompiler);
    return self;
}

DxcKernelCompiler::~DxcKernelCompiler() = default;

Result<std::vector<uint8_t>> DxcKernelCompiler::Compile(const KernelSource& source,
                                                        KernelTarget target,
                                                        const fs::path& includeDir) {
    uz::ShaderCompileDesc desc;
    desc.source = source.hlsl;
    desc.entryPoint = source.entryPoint;
    // With includes, the source is named inside their folder: quoted includes are then looked
    // up there (the including file's folder) and never in the working directory. Without
    // includes no include handler exists and every `#include` fails.
    desc.sourceName = includeDir.empty() ? source.name + ".hlsl"
                                         : (includeDir / (source.name + ".hlsl")).string();
    desc.stage = uz::ShaderStageCompile::Compute;
    desc.model = uz::ShaderModelCompile::SM6_6;
    desc.output = target == KernelTarget::Dxil ? uz::ShaderOutputFormat::DXIL
                                               : uz::ShaderOutputFormat::SPIRV;
    desc.defines = source.defines;
    if (!includeDir.empty()) desc.includeDirs = {includeDir.string()};
    desc.ieeeStrict = true;

    uz::ShaderCompileResult result = m_compiler->Compile(desc);
    const std::string what =
        "kernel '" + source.name + "' to " + std::string(KernelTargetName(target));
    if (!result.success || result.bytecode.size() < 4) {
        return Fail(ErrorCode::KernelCompileFailed, std::nullopt,
                    what + ": " + (result.errors.empty() ? "no bytecode" : result.errors));
    }
    uint32_t magic = 0;
    std::memcpy(&magic, result.bytecode.data(), sizeof(magic));
    const bool valid = target == KernelTarget::Dxil
                           ? std::memcmp(result.bytecode.data(), "DXBC", 4) == 0
                           : magic == 0x07230203u;
    if (!valid) {
        return Fail(ErrorCode::KernelCompileFailed, std::nullopt,
                    what + ": DXC returned no " + std::string(KernelTargetName(target)) +
                        " container");
    }
    return std::move(result.bytecode);
}

// ── KernelCache ──────────────────────────────────────────────────────────────

KernelCache::KernelCache(IKernelCompiler& compiler, fs::path root)
    : m_compiler(compiler), m_root(std::move(root)) {}

fs::path KernelCache::EntryPath(uint64_t key, KernelTarget target) const {
    return m_root / (Hex64(key) + (target == KernelTarget::Dxil ? ".dxil" : ".spv"));
}

Result<fs::path> KernelCache::MaterialiseIncludes(const KernelSource& source) {
    if (source.includes.empty()) return fs::path();
    const std::vector<const KernelInclude*> includes = SortedIncludes(source);
    std::string encoded;
    for (size_t i = 0; i < includes.size(); ++i) {
        const KernelInclude& include = *includes[i];
        if (!ValidIncludeName(include.name) ||
            (i > 0 && includes[i - 1]->name == include.name)) {
            return Fail(ErrorCode::KernelCompileFailed, std::nullopt,
                        "kernel '" + source.name + "' declares an invalid or duplicate include '" +
                            include.name + "'");
        }
        PutField(encoded, include.name);
        PutField(encoded, include.text);
    }
    // One folder per include set, named by its content.
    const fs::path folder = m_root / "includes" / Hex64(HashText(encoded));
    for (const KernelInclude* include : includes) {
        const fs::path file = folder / fs::path(include->name);
        std::ifstream existing(IoPath(file), std::ios::binary);
        const std::string current((std::istreambuf_iterator<char>(existing)),
                                  std::istreambuf_iterator<char>());
        if (existing.is_open() && current == include->text) continue;
        existing.close();
        if (!WriteAtomically(file, include->text)) {
            return Fail(ErrorCode::KernelCompileFailed, std::nullopt,
                        "include '" + include->name + "' of kernel '" + source.name +
                            "' could not be written to " + file.string());
        }
    }
    return IoPath(folder);
}

Result<CompiledKernel> KernelCache::Get(const KernelSource& source, KernelTarget target) {
    CompiledKernel kernel;
    kernel.key = KernelKey(source, target, m_compiler.Version());
    kernel.target = target;
    const fs::path entry = EntryPath(kernel.key, target);
    switch (ReadEntry(entry, kernel.key, kernel.bytecode)) {
        case EntryState::Valid:
            ++m_stats.hits;
            kernel.cacheHit = true;
            return kernel;
        case EntryState::Corrupt: ++m_stats.corruptEntries; break;
        case EntryState::Absent: break;
    }
    ++m_stats.misses;
    Result<fs::path> includeDir = MaterialiseIncludes(source);
    if (!includeDir) return Unexpected(std::move(includeDir.error()));
    Result<std::vector<uint8_t>> bytecode = m_compiler.Compile(source, target, *includeDir);
    if (!bytecode) return Unexpected(std::move(bytecode.error()));
    kernel.bytecode = std::move(*bytecode);
    if (!WriteEntry(entry, kernel.key, kernel.bytecode)) ++m_stats.writeFailures;
    return kernel;
}

}  // namespace uzp::render
