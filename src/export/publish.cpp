#include "export/publish.h"

#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

#include <algorithm>
#include <array>
#include <cstdio>
#include <thread>

#if defined(UZP_EXPORT_FAULT_HOOKS)
#include "export/fault.h"
#endif

namespace uzp::exporter {

namespace fs = std::filesystem;
namespace json = core::json;
using publish_detail::Fail;
using publish_detail::ReadBytes;
using publish_detail::RenameDurable;
using publish_detail::Verifies;
using publish_detail::WriteDurable;

namespace {

std::string WindowsError(DWORD code) {
    char* text = nullptr;
    const DWORD size = FormatMessageA(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
                                          FORMAT_MESSAGE_IGNORE_INSERTS,
                                      nullptr, code, 0, reinterpret_cast<char*>(&text), 0, nullptr);
    std::string message = size > 0 && text != nullptr ? std::string(text, size) : "error " + std::to_string(code);
    if (text != nullptr) LocalFree(text);
    while (!message.empty() && (message.back() == '\n' || message.back() == '\r' || message.back() == ' ')) {
        message.pop_back();
    }
    return message;
}

/// The current UTC time as RFC 3339 (`2026-10-12T03:04:05Z`).
std::string MomentNow() {
    SYSTEMTIME t{};
    GetSystemTime(&t);
    std::array<char, 32> text{};
    std::snprintf(text.data(), text.size(), "%04u-%02u-%02uT%02u:%02u:%02uZ", t.wYear, t.wMonth, t.wDay, t.wHour,
                  t.wMinute, t.wSecond);
    return text.data();
}

bool IsGenerationId(std::string_view name) {
    return !name.empty() && name.size() <= 18 &&
           std::all_of(name.begin(), name.end(), [](char c) { return c >= '0' && c <= '9'; });
}

std::uint64_t GenerationNumber(std::string_view id) { return std::stoull(std::string(id)); }

std::string GenerationId(std::uint64_t number) {
    std::string id = std::to_string(number);
    if (id.size() < 6) id.insert(0, 6 - id.size(), '0');
    return id;
}

std::string PointerText(const std::string& generation, const std::string& receiptSha256) {
    return json::WriteCanonical(json::Object{
        {"schema", std::string(kCurrentSchema)},
        {"generation", generation},
        {"receipt", std::string(kGenerationsDir) + "/" + generation + "/receipt.json"},
        {"receipt_sha256", receiptSha256},
    });
}

/// Publishes complete generation `id` (receipt SHA-256 `receiptSha256`) by the pointer's rename.
render::Result<void> WritePointer(const fs::path& exportPath, const std::string& id, const std::string& receiptSha256) {
    const fs::path staging = exportPath / Utf8Path(std::string(kCurrentFile) + std::string(kStagingSuffix));
    render::Result<void> written = WriteDurable(staging, PointerText(id, receiptSha256));
    if (!written) return written;
#if defined(UZP_EXPORT_FAULT_HOOKS)
    fault::Reach(fault::Point::kill_before_pointer_rename);
#endif
    render::Result<void> renamed = RenameDurable(staging, exportPath / Utf8Path(kCurrentFile));
    if (!renamed) {
        std::error_code ignored;
        fs::remove(staging, ignored);
    }
    return renamed;
}

/// Removes a generation this process claimed and could not complete; says what was left behind.
std::string Discard(const fs::path& directory) {
    std::error_code error;
    fs::remove_all(directory, error);
    if (!error) return "";
    return "; the incomplete generation " + Utf8String(directory) + " could not be removed (" + error.message() +
           ") and is left for `export --recover`";
}

/// The plan text a plan hash names: the canonical JSON of plan.json without its `hash` member.
bool PlanMatches(const std::string& text, const std::string& planHash) {
    try {
        json::Value plan = json::Parse(text);
        if (!plan.IsObject()) return false;
        json::Object& o = std::get<json::Object>(plan.data);
        const auto hash = o.find("hash");
        if (hash == o.end() || !hash->second.IsString() || std::get<std::string>(hash->second.data) != planHash) {
            return false;
        }
        o.erase(hash);
        return core::Sha256Hex(json::WriteCanonical(plan)) == planHash;
    } catch (const json::ParseError&) {
        return false;
    }
}

}  // namespace

namespace publish_detail {

render::Unexpected Fail(std::string reason) {
    return render::Fail(render::ErrorCode::RequestFailed, std::nullopt, "export: " + std::move(reason));
}

render::Result<void> WriteDurable(const fs::path& path, std::string_view bytes) {
    HANDLE file = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (file == INVALID_HANDLE_VALUE) {
        return Fail("cannot create " + Utf8String(path) + ": " + WindowsError(GetLastError()));
    }
    size_t done = 0;
    while (done < bytes.size()) {
        const DWORD chunk = static_cast<DWORD>(std::min<size_t>(bytes.size() - done, 1u << 30));
        DWORD written = 0;
        if (!WriteFile(file, bytes.data() + done, chunk, &written, nullptr) || written == 0) {
            const DWORD code = GetLastError();
            CloseHandle(file);
            return Fail("cannot write " + Utf8String(path) + ": " + WindowsError(code));
        }
        done += written;
    }
    if (!FlushFileBuffers(file)) {
        const DWORD code = GetLastError();
        CloseHandle(file);
        return Fail("cannot flush " + Utf8String(path) + ": " + WindowsError(code));
    }
    if (!CloseHandle(file)) return Fail("cannot close " + Utf8String(path) + ": " + WindowsError(GetLastError()));
    return {};
}

render::Result<void> RenameDurable(const fs::path& from, const fs::path& to) {
    if (!MoveFileExW(from.c_str(), to.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        return Fail("cannot rename " + Utf8String(from) + " to " + Utf8String(to) + ": " +
                    WindowsError(GetLastError()));
    }
    return {};
}

std::optional<std::string> ReadBytes(const fs::path& path) {
    std::FILE* file = _wfopen(path.c_str(), L"rb");
    if (file == nullptr) return std::nullopt;
    std::string bytes;
    std::array<char, 1 << 16> buffer{};
    size_t n = 0;
    while ((n = std::fread(buffer.data(), 1, buffer.size(), file)) > 0) bytes.append(buffer.data(), n);
    const bool failed = std::ferror(file) != 0;
    std::fclose(file);
    if (failed) return std::nullopt;
    return bytes;
}

bool Verifies(const fs::path& path, std::uint64_t bytes, std::string_view sha256, std::string& problem) {
    std::FILE* file = _wfopen(path.c_str(), L"rb");
    if (file == nullptr) {
        problem = Utf8String(path) + " is missing";
        return false;
    }
    core::Sha256 hash;
    std::uint64_t size = 0;
    std::vector<char> buffer(1 << 20);
    size_t n = 0;
    while ((n = std::fread(buffer.data(), 1, buffer.size(), file)) > 0) {
        hash.Update(std::string_view(buffer.data(), n));
        size += n;
    }
    const bool failed = std::ferror(file) != 0;
    std::fclose(file);
    if (failed) {
        problem = Utf8String(path) + " cannot be read";
        return false;
    }
    if (size != bytes) {
        problem = Utf8String(path) + " has " + std::to_string(size) + " bytes, not " + std::to_string(bytes);
        return false;
    }
    static constexpr char kHex[] = "0123456789abcdef";
    std::string hex;
    for (const std::uint8_t byte : hash.Finish()) {
        hex.push_back(kHex[byte >> 4]);
        hex.push_back(kHex[byte & 15]);
    }
    if (hex != sha256) {
        problem = Utf8String(path) + " has SHA-256 " + hex + ", not " + std::string(sha256);
        return false;
    }
    return true;
}

}  // namespace publish_detail

fs::path Utf8Path(std::string_view text) { return fs::path(std::u8string(text.begin(), text.end())); }

std::string Utf8String(const fs::path& path) {
    const std::u8string text = path.generic_u8string();
    return std::string(text.begin(), text.end());
}

// ── The publication lock ────────────────────────────────────────────────────

render::Result<PublicationLock> PublicationLock::Acquire(const fs::path& exportPath,
                                                         std::chrono::milliseconds timeout) {
    std::error_code error;
    fs::create_directories(exportPath, error);
    if (error) return Fail("cannot create " + Utf8String(exportPath) + ": " + error.message());
    const fs::path path = exportPath / Utf8Path(kLockFile);
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    for (;;) {
        HANDLE handle = CreateFileW(path.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_ALWAYS,
                                    FILE_ATTRIBUTE_NORMAL, nullptr);
        if (handle != INVALID_HANDLE_VALUE) return PublicationLock(handle);
        const DWORD code = GetLastError();
        if (code != ERROR_SHARING_VIOLATION && code != ERROR_ACCESS_DENIED) {
            return Fail("cannot open the publication lock " + Utf8String(path) + ": " + WindowsError(code));
        }
        if (std::chrono::steady_clock::now() >= deadline) {
            return Fail("the publication lock " + Utf8String(path) + " is held by another process (waited " +
                        std::to_string(timeout.count()) + " ms)");
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
}

PublicationLock::PublicationLock(PublicationLock&& other) noexcept : handle_(other.handle_) { other.handle_ = nullptr; }

PublicationLock& PublicationLock::operator=(PublicationLock&& other) noexcept {
    if (this != &other) {
        Release();
        handle_ = other.handle_;
        other.handle_ = nullptr;
    }
    return *this;
}

PublicationLock::~PublicationLock() { Release(); }

void PublicationLock::Release() noexcept {
    if (handle_ != nullptr) CloseHandle(static_cast<HANDLE>(handle_));
    handle_ = nullptr;
}

// ── Generations and the pointer ─────────────────────────────────────────────

fs::path GenerationPath(const fs::path& exportPath, std::string_view id) {
    return exportPath / Utf8Path(kGenerationsDir) / Utf8Path(id);
}

std::vector<std::string> ListGenerations(const fs::path& exportPath) {
    std::vector<std::string> ids;
    std::error_code error;
    for (const fs::directory_entry& entry : fs::directory_iterator(exportPath / Utf8Path(kGenerationsDir), error)) {
        const std::string name = Utf8String(entry.path().filename());
        std::error_code kind;
        if (entry.is_directory(kind) && IsGenerationId(name)) ids.push_back(name);
    }
    std::sort(ids.begin(), ids.end(), [](const std::string& a, const std::string& b) {
        return GenerationNumber(a) < GenerationNumber(b);
    });
    return ids;
}

render::Result<std::optional<CurrentPointer>> ReadCurrent(const fs::path& exportPath) {
    const fs::path path = exportPath / Utf8Path(kCurrentFile);
    std::error_code error;
    if (!fs::exists(path, error)) return std::optional<CurrentPointer>{};
    const std::optional<std::string> text = ReadBytes(path);
    if (!text) return Fail("cannot read " + Utf8String(path));
    const auto bad = [&](const std::string& why) {
        return Fail(Utf8String(path) + " is not a delivery pointer: " + why);
    };
    json::Value value;
    try {
        value = json::Parse(*text);
    } catch (const json::ParseError& e) {
        return bad(e.what());
    }
    if (!value.IsObject()) return bad("expected an object");
    const json::Object& o = std::get<json::Object>(value.data);
    CurrentPointer pointer;
    for (const auto& [key, out] : {std::pair<const char*, std::string*>{"generation", &pointer.generation},
                                   {"receipt", &pointer.receipt},
                                   {"receipt_sha256", &pointer.receiptSha256}}) {
        const auto it = o.find(key);
        if (it == o.end() || !it->second.IsString()) return bad(std::string(key) + ": expected a string");
        *out = std::get<std::string>(it->second.data);
    }
    const auto schema = o.find("schema");
    if (schema == o.end() || schema->second != json::Value(kCurrentSchema)) {
        return bad("schema: expected " + std::string(kCurrentSchema));
    }
    if (!IsGenerationId(pointer.generation)) {
        return bad("generation: '" + pointer.generation + "' is not a generation id");
    }
    if (pointer.receipt != std::string(kGenerationsDir) + "/" + pointer.generation + "/receipt.json") {
        return bad("receipt: '" + pointer.receipt + "' is not the receipt of its generation");
    }
    if (!core::IsSha256Hex(pointer.receiptSha256)) return bad("receipt_sha256: not a lower-case SHA-256");
    return std::optional<CurrentPointer>(std::move(pointer));
}

GenerationState InspectGeneration(const fs::path& exportPath, std::string_view id) {
    GenerationState state;
    state.id = std::string(id);
    const fs::path directory = GenerationPath(exportPath, id);
    const std::optional<std::string> receiptText = ReadBytes(directory / "receipt.json");
    if (!receiptText) {
        state.problem = "it has no receipt";
        return state;
    }
    ReceiptSummary receipt;
    try {
        receipt = ReadReceipt(*receiptText);
    } catch (const core::ManifestError& e) {
        state.problem = e.what();
        return state;
    }
    if (receipt.generation != id) {
        state.problem = "its receipt names generation " + receipt.generation;
        return state;
    }
    const std::optional<std::string> planText = ReadBytes(directory / "plan.json");
    if (!planText || !PlanMatches(*planText, receipt.planHash)) {
        state.problem = "its plan.json is not the plan " + receipt.planHash;
        return state;
    }
    for (const ReceiptFile& file : receipt.files) {
        if (!Verifies(directory / "files" / Utf8Path(file.path), file.bytes, file.sha256, state.problem)) return state;
    }
    state.complete = true;
    state.receiptSha256 = core::Sha256Hex(*receiptText);
    state.receipt = std::move(receipt);
    return state;
}

// ── Publication ─────────────────────────────────────────────────────────────

render::Result<Publication> PublishExport(const core::Project& project, std::int64_t revision, const ExportPlan& plan,
                                          const SourceInputs& inputs, const evaluator::TemplateLibrary& templates,
                                          evaluator::ITileStore& store, evaluator::TileCache& cache,
                                          const PublishRequest& request) {
    if (request.identity.appVersion.empty() || request.identity.build.empty()) {
        return Fail("a publication needs the application's version and build (ARC-11)");
    }
    const render::Result<evaluator::ExecutionIdentity> execution = store.Execution();
    if (!execution) return render::Unexpected(execution.error());
    // 1. Everything encoded in memory: a refusal or a failure writes nothing.
    render::Result<std::vector<EncodedFile>> encoded =
        EncodeExport(project, revision, plan, inputs, templates, store, cache,
                     request.diagnostic ? &*request.diagnostic : nullptr);
    if (!encoded) return render::Unexpected(encoded.error());
    core::json::Array proceduralSnapshots;
    render::Result<std::set<std::string>> resources = ReadResourceHashes(project, plan, templates, inputs.templateId, inputs.procedurals.get(), &proceduralSnapshots);
    if (!resources) return render::Unexpected(resources.error());

    if (request.beforePublish) {
        const render::Result<void> ready = request.beforePublish();
        if (!ready) return render::Unexpected(ready.error());
    }

    const fs::path exportPath = Utf8Path(plan.exportPath);
    render::Result<PublicationLock> lock = PublicationLock::Acquire(exportPath, request.lockTimeout);
    if (!lock) return render::Unexpected(lock.error());
    if (request.beforePublish) {
        const render::Result<void> ready = request.beforePublish();
        if (!ready) return render::Unexpected(ready.error());
    }

    // 2. A new generation, claimed by creating its directory.
    std::error_code error;
    fs::create_directories(exportPath / Utf8Path(kGenerationsDir), error);
    if (error) {
        return Fail("cannot create " + Utf8String(exportPath / Utf8Path(kGenerationsDir)) + ": " + error.message());
    }
    const std::vector<std::string> existing = ListGenerations(exportPath);
    std::uint64_t number = existing.empty() ? 1 : GenerationNumber(existing.back()) + 1;
    std::string id = GenerationId(number);
    while (!CreateDirectoryW(GenerationPath(exportPath, id).c_str(), nullptr)) {
        const DWORD code = GetLastError();
        if (code != ERROR_ALREADY_EXISTS) {
            return Fail("cannot create " + Utf8String(GenerationPath(exportPath, id)) + ": " + WindowsError(code));
        }
        id = GenerationId(++number);
    }
    const fs::path directory = GenerationPath(exportPath, id);
    const auto failed = [&](const render::Error& cause) -> render::Unexpected {
        return Fail(cause.reason + Discard(directory));
    };

    // 3. The files, the plan and the receipt, each flushed and verified.
    Publication publication;
    publication.generation = id;
    publication.directory = directory;
    for (size_t i = 0; i < plan.files.size(); ++i) {
        const PlannedFile& file = plan.files[i];
        const std::string& bytes = (*encoded)[i].bytes;
        const fs::path path = directory / "files" / Utf8Path(file.relativePath);
        fs::create_directories(path.parent_path(), error);
        if (error) {
            return failed(Fail("cannot create the folder of " + Utf8String(path) + ": " + error.message()).error());
        }
        render::Result<void> written = WriteDurable(path, bytes);
#if defined(UZP_EXPORT_FAULT_HOOKS)
        if (written && fault::Fails(fault::Point::fail_write, i)) {
            written = Fail("injected write failure of " + Utf8String(path));
        }
#endif
        if (!written) return failed(written.error());
#if defined(UZP_EXPORT_FAULT_HOOKS)
        fault::Reach(fault::Point::kill_after_file, i);
#endif
        publication.files.push_back(
            {file.rootPath, file.relativePath, Utf8String(path), bytes.size(), core::Sha256Hex(bytes)});
        // The file's `.uztexture` derivative, right after it (decision 316).
        if (const std::optional<EncodedUzTexture>& derivative = (*encoded)[i].uztexture) {
            const fs::path cooked = directory / "files" / Utf8Path(file.uztexture->relativePath);
            render::Result<void> cookedWritten = WriteDurable(cooked, derivative->bytes);
            if (!cookedWritten) return failed(cookedWritten.error());
#if defined(UZP_EXPORT_FAULT_HOOKS)
            fault::Reach(fault::Point::kill_after_uztexture, i);
#endif
            publication.files.push_back({file.rootPath, file.uztexture->relativePath, Utf8String(cooked),
                                         derivative->bytes.size(), core::Sha256Hex(derivative->bytes)});
        }
        if (const std::optional<EncodedDds>& derivative = (*encoded)[i].dds) {
            const fs::path cooked = directory / "files" / Utf8Path(file.dds->relativePath);
            render::Result<void> cookedWritten = WriteDurable(cooked, derivative->bytes);
            if (!cookedWritten) return failed(cookedWritten.error());
#if defined(UZP_EXPORT_FAULT_HOOKS)
            fault::Reach(fault::Point::kill_after_dds, i);
#endif
            publication.files.push_back({file.rootPath, file.dds->relativePath, Utf8String(cooked),
                                         derivative->bytes.size(), core::Sha256Hex(derivative->bytes)});
        }
        // The `.uzmat` of a UzEngine preset, after its stack's last file (phase3.2_uze-uzmat-preset).
        if (const std::optional<EncodedUzMaterial>& material = (*encoded)[i].material) {
            const UzMaterialOutput& planned = plan.materials[material->index];
            const fs::path written = directory / "files" / Utf8Path(planned.relativePath);
            render::Result<void> materialWritten = WriteDurable(written, material->bytes);
            if (!materialWritten) return failed(materialWritten.error());
#if defined(UZP_EXPORT_FAULT_HOOKS)
            fault::Reach(fault::Point::kill_after_uzmat, material->index);
#endif
            publication.files.push_back({planned.rootPath, planned.relativePath, Utf8String(written),
                                         material->bytes.size(), core::Sha256Hex(material->bytes)});
        }
    }
    for (const WrittenFile& file : publication.files) {
        std::string problem;
        if (!Verifies(Utf8Path(file.path), file.size, file.sha256, problem)) {
            return failed(Fail("verification failed: " + problem).error());
        }
    }
    const std::string planText = json::WriteCanonical(PlanJson(plan));
    render::Result<void> planWritten = WriteDurable(directory / "plan.json", planText);
    if (!planWritten) return failed(planWritten.error());
#if defined(UZP_EXPORT_FAULT_HOOKS)
    fault::Reach(fault::Point::kill_after_plan);
#endif
    const std::string receiptText = json::WriteCanonical(BuildReceipt({project, revision, plan, *encoded, id,
                                                                       MomentNow(), request.projectPath,
                                                                       request.identity, std::move(*resources), *execution, proceduralSnapshots}));
    render::Result<void> receiptWritten = WriteDurable(directory / "receipt.json", receiptText);
    if (!receiptWritten) return failed(receiptWritten.error());
#if defined(UZP_EXPORT_FAULT_HOOKS)
    fault::Reach(fault::Point::kill_after_receipt);
#endif
    const GenerationState state = InspectGeneration(exportPath, id);
    if (!state.complete) return failed(Fail("verification failed: generation " + id + ": " + state.problem).error());

    // 4. The pointer.
    render::Result<void> published = WritePointer(exportPath, id, state.receiptSha256);
    if (!published) return failed(published.error());
#if defined(UZP_EXPORT_FAULT_HOOKS)
    fault::Reach(fault::Point::kill_after_pointer_rename);
#endif
    publication.receipt = directory / "receipt.json";
    publication.receiptSha256 = state.receiptSha256;
    return publication;
}

// ── Recovery ────────────────────────────────────────────────────────────────

render::Result<RecoveryReport> RecoverExport(const fs::path& exportPath, std::chrono::milliseconds lockTimeout) {
    std::error_code missing;
    if (!fs::is_directory(exportPath, missing)) return Fail(Utf8String(exportPath) + " is not an export folder");
    render::Result<PublicationLock> lock = PublicationLock::Acquire(exportPath, lockTimeout);
    if (!lock) return render::Unexpected(lock.error());
    render::Result<std::optional<CurrentPointer>> current = ReadCurrent(exportPath);
    if (!current) return render::Unexpected(current.error());
    RecoveryReport report;
    if (*current) report.currentBefore = (*current)->generation;
    const std::optional<std::uint64_t> selected =
        *current ? std::optional<std::uint64_t>(GenerationNumber((*current)->generation)) : std::nullopt;

    const fs::path staging = exportPath / Utf8Path(std::string(kCurrentFile) + std::string(kStagingSuffix));
    std::error_code error;
    if (fs::exists(staging, error)) {
        fs::remove(staging, error);
        if (error) return Fail("cannot remove the staging pointer " + Utf8String(staging) + ": " + error.message());
        report.removedStagingPointer = true;
    }

    std::vector<GenerationState> states;
    for (const std::string& id : ListGenerations(exportPath)) states.push_back(InspectGeneration(exportPath, id));
    // Roll forward: the newest complete generation newer than the selected one.
    for (auto it = states.rbegin(); it != states.rend(); ++it) {
        if (selected && GenerationNumber(it->id) <= *selected) break;
        if (!it->complete) continue;
        render::Result<void> published = WritePointer(exportPath, it->id, it->receiptSha256);
        if (!published) return render::Unexpected(published.error());
        report.published = it->id;
        break;
    }
    report.currentAfter = report.published ? report.published : report.currentBefore;
    for (const GenerationState& state : states) {
        if (state.complete) {
            if (!report.published && *current && state.id == (*current)->generation &&
                state.receiptSha256 != (*current)->receiptSha256) {
                report.damaged = {state.id, "its receipt is not the one the pointer names"};
            }
            continue;
        }
        if (report.currentAfter && state.id == *report.currentAfter) {
            report.damaged = {state.id, state.problem};
            continue;
        }
        fs::remove_all(GenerationPath(exportPath, state.id), error);
        if (error) {
            return Fail("cannot remove the incomplete generation " + Utf8String(GenerationPath(exportPath, state.id)) +
                        ": " + error.message());
        }
        report.removed.emplace_back(state.id, state.problem);
    }
    if (report.currentAfter && std::none_of(states.begin(), states.end(), [&](const GenerationState& s) {
            return s.id == *report.currentAfter;
        })) {
        report.damaged = {*report.currentAfter, "its directory is missing"};
    }
    return report;
}

}  // namespace uzp::exporter
