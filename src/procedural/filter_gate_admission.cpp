#include "procedural/filter_gate_admission.h"

#include <algorithm>
#include <array>
#include <initializer_list>
#include <stdexcept>
#include <utility>

#include "uzp_core/manifest/sha256.h"

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

namespace uzp::procedural {
namespace {

namespace fs = std::filesystem;
using core::json::Array;
using core::json::Object;
using core::json::Value;

// Zig's libc++ also declares the pre-C++17 `std::unexpected()`, so the bare name is ambiguous
// (asset_library.cpp, seam.h `Refused`): the error type is named through `std::expected`.
using Unexpected = std::expected<void, ImportRefusal>::unexpected_type;

/// A refusal with one fixed detail code; nothing observed is carried.
struct FilterAdmissionRefused {
    std::string_view code;
};

void Require(bool condition, std::string_view code) {
    if (!condition) throw FilterAdmissionRefused{code};
}

ImportRefusal Refusal(std::string detail) { return ImportRefusal{std::string(kFilterCaptureInvalid), std::move(detail)}; }

const Object& AsObject(const Value& value, std::string_view code) {
    Require(value.IsObject(), code);
    return std::get<Object>(value.data);
}

const Array& AsArray(const Value& value, std::string_view code) {
    Require(value.IsArray(), code);
    return std::get<Array>(value.data);
}

const Value& At(const Object& object, std::string_view key, std::string_view code) {
    const auto found = object.find(key);
    Require(found != object.end(), code);
    return found->second;
}

const std::string& StringAt(const Object& object, std::string_view key, std::string_view code) {
    const Value& value = At(object, key, code);
    Require(value.IsString(), code);
    return std::get<std::string>(value.data);
}

/// `object` has every `required` key and no key outside `required` and `allowed`.
void Closed(const Object& object, std::initializer_list<std::string_view> required,
            std::initializer_list<std::string_view> allowed, std::string_view code) {
    for (const std::string_view key : required) Require(object.contains(key), code);
    for (const auto& [key, value] : object) {
        bool known = false;
        for (const std::string_view name : required) known = known || key == name;
        for (const std::string_view name : allowed) known = known || key == name;
        Require(known, code);
    }
}

/// Typed equality: canonical JSON keeps integers, doubles, signed zero and strings apart.
bool SameTyped(const Value& a, const Value& b) { return core::json::WriteCanonical(a) == core::json::WriteCanonical(b); }

Value Decode(std::string_view bytes, std::string_view code) {
    try {
        return core::json::Parse(bytes);
    } catch (const std::exception&) {
        throw FilterAdmissionRefused{code};
    }
}

bool NonnegativeInt(const Value& value) { return value.IsInt() && std::get<std::int64_t>(value.data) >= 0; }

bool Lower(char c) { return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9'); }

/// `^[a-z0-9][a-z0-9._-]*$` (store.py `_RECORD_ID`, golden-public `record_id`).
bool RecordId(std::string_view text) {
    if (text.empty() || !Lower(text.front())) return false;
    for (const char c : text) {
        if (!Lower(c) && c != '.' && c != '_' && c != '-') return false;
    }
    return true;
}

/// `^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)*$` (store.py `_GOLDEN_ID`).
bool GoldenId(std::string_view text) {
    std::size_t start = 0;
    while (true) {
        const std::size_t slash = text.find('/', start);
        if (!RecordId(text.substr(start, slash == std::string_view::npos ? std::string_view::npos : slash - start))) {
            return false;
        }
        if (slash == std::string_view::npos) return true;
        start = slash + 1;
    }
}

/// `^[A-Za-z0-9][A-Za-z0-9._+-]*$` (store.py `_BUILD_DIR`).
bool BuildDir(std::string_view text) {
    const auto alnum = [](char c) { return Lower(c) || (c >= 'A' && c <= 'Z'); };
    if (text.empty() || !alnum(text.front())) return false;
    for (const char c : text) {
        if (!alnum(c) && c != '.' && c != '_' && c != '+' && c != '-') return false;
    }
    return true;
}

/// `^[0-9]+\.[0-9]+\.[0-9]+$`.
bool Version(std::string_view text) {
    int parts = 0;
    std::size_t digits = 0;
    for (const char c : text) {
        if (c >= '0' && c <= '9') {
            ++digits;
        } else if (c == '.' && digits != 0 && parts < 2) {
            ++parts;
            digits = 0;
        } else {
            return false;
        }
    }
    return parts == 2 && digits != 0;
}

/// A JSON Schema string length (code points) in [1, 512] (golden-private `known_or_unknown`).
bool KnownOrUnknown(const Value& value) {
    if (!value.IsString()) return false;
    std::size_t points = 0;
    for (const char c : std::get<std::string>(value.data)) {
        if ((static_cast<unsigned char>(c) & 0xC0u) != 0x80u) ++points;
    }
    return points >= 1 && points <= 512;
}

// ── Fenced reads ─────────────────────────────────────────────────────────────────────────────────

struct Handle {
    HANDLE value = INVALID_HANDLE_VALUE;
    explicit Handle(HANDLE h) : value(h) {}
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    ~Handle() {
        if (value != INVALID_HANDLE_VALUE) CloseHandle(value);
    }
};

/// True when `path` is missing, unreadable or a reparse point (symbolic link, junction, mount).
bool ReparseOrMissing(const fs::path& path) {
    const DWORD attributes = GetFileAttributesW(path.c_str());
    return attributes == INVALID_FILE_ATTRIBUTES || (attributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0;
}

/// The handle's final, normalized path, or nothing.
std::optional<std::wstring> FinalPath(HANDLE handle) {
    const DWORD needed = GetFinalPathNameByHandleW(handle, nullptr, 0, FILE_NAME_NORMALIZED);
    if (needed == 0) return std::nullopt;
    std::wstring text(needed, L'\0');
    const DWORD written = GetFinalPathNameByHandleW(handle, text.data(), needed, FILE_NAME_NORMALIZED);
    if (written == 0 || written >= needed) return std::nullopt;
    text.resize(written);
    return text;
}

/// `path` lies strictly inside the folder whose final path is `root` (ordinal, case-insensitive).
bool Inside(const std::wstring& path, const std::wstring& root) {
    return path.size() > root.size() + 1 && path[root.size()] == L'\\' &&
           CompareStringOrdinal(path.c_str(), static_cast<int>(root.size()), root.c_str(), static_cast<int>(root.size()),
                                TRUE) == CSTR_EQUAL;
}

/// The whole regular file opened at `path` without following a reparse point, when its handle's
/// final path lies inside `fence` (empty: no fence); nothing otherwise.
std::optional<std::string> ReadHandle(const fs::path& path, const std::wstring& fence) {
    Handle file(CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                            FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
    if (file.value == INVALID_HANDLE_VALUE) return std::nullopt;
    BY_HANDLE_FILE_INFORMATION info{};
    if (!GetFileInformationByHandle(file.value, &info)) return std::nullopt;
    if ((info.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) != 0) return std::nullopt;
    if (!fence.empty()) {
        const auto resolved = FinalPath(file.value);
        if (!resolved || !Inside(*resolved, fence)) return std::nullopt;
    }
    LARGE_INTEGER size{};
    if (!GetFileSizeEx(file.value, &size) || size.QuadPart < 0) return std::nullopt;
    std::string bytes(static_cast<std::size_t>(size.QuadPart), '\0');
    std::size_t done = 0;
    while (done < bytes.size()) {
        const DWORD chunk = static_cast<DWORD>(std::min<std::size_t>(bytes.size() - done, 1u << 30));
        DWORD read = 0;
        if (!ReadFile(file.value, bytes.data() + done, chunk, &read, nullptr) || read == 0) return std::nullopt;
        done += read;
    }
    char extra = 0;
    DWORD more = 0;
    if (!ReadFile(file.value, &extra, 1, &more, nullptr) || more != 0) return std::nullopt;
    return bytes;
}

fs::path Component(std::string_view text) { return fs::path(std::u8string(text.begin(), text.end())); }

/// The file at `parts` under `root`, every folder between them not a reparse point, read through
/// a handle fenced inside `final_root`.
std::optional<std::string> ReadFenced(const fs::path& root, const std::wstring& final_root,
                                      const std::vector<std::string>& parts) {
    fs::path path = root;
    for (std::size_t i = 0; i + 1 < parts.size(); ++i) {
        path /= Component(parts[i]);
        if (ReparseOrMissing(path)) return std::nullopt;
    }
    path /= Component(parts.back());
    return ReadHandle(path, final_root);
}

// ── Fixed references, Legacy and the record shapes ─────────────────────────────────────────────

/// Python's `slug` for the fixed record id fragments used here (lowercase ASCII, `/` -> `-`).
std::string ImageRecordId(std::string_view round, std::string_view boundary, std::string_view image) {
    return std::string(round) + "-settings-" + std::string(boundary) + "-" + std::string(image);
}

/// The twelve fixed references `(record id, kind)` in their fixed order.
std::vector<std::pair<std::string, std::string>> ExpectedRefs() {
    std::vector<std::pair<std::string, std::string>> refs{{"golden-record", "private_oracle_record"},
                                                          {"oracle-environment", "oracle_environment_record"}};
    constexpr std::array<std::pair<std::string_view, std::string_view>, 5> boundaries{{{"r1", "after-create"},
                                                                                        {"r1", "after-setup6"},
                                                                                        {"r1", "pre16-r1"},
                                                                                        {"r2", "after-reopen"},
                                                                                        {"r2", "pre16-r2"}}};
    for (const auto& [round, boundary] : boundaries) {
        for (const std::string_view image : {"configuration-image", "physical-size-image"}) {
            refs.emplace_back(ImageRecordId(round, boundary, image), "settings_panel_evidence");
        }
    }
    return refs;
}

/// The Legacy colour selection (`filter_context_validation.LEGACY`).
Value Legacy() { return Object{{"mode", "legacy"}, {"OCIO", nullptr}, {"PAINTER_ACE_CONFIG", nullptr}}; }

/// `environment.colour_configuration_sha256(LEGACY)`: no configuration file is named.
std::string LegacyColourSha256() {
    return core::Sha256Hex(core::json::WriteCanonical(Object{{"colour_management", Legacy()}, {"files", Object{}}}));
}

/// The manifest without `private_records` and without `software.painter`.
Object Invariant(const Object& document, std::string_view code) {
    Object result = document;
    result.erase("private_records");
    Object software = AsObject(At(document, "software", code), code);
    software.erase("painter");
    result["software"] = std::move(software);
    return result;
}

void CheckRecordShape(const Object& record) {
    const std::string_view code = filter_gate::kReceipt;
    Closed(record, {"schema", "record_class", "golden_id", "tier", "key", "recordings"}, {"environment", "note"}, code);
    Require(StringAt(record, "schema", code) == "uzpainter/parity/golden-private/1" &&
                StringAt(record, "record_class", code) == "private_oracle_record" &&
                GoldenId(StringAt(record, "golden_id", code)),
            code);
    const std::string& tier = StringAt(record, "tier", code);
    Require(tier == "0" || tier == "1" || tier == "2a" || tier == "2b" || tier == "3", code);
    if (record.contains("note")) StringAt(record, "note", code);

    const Object& key = AsObject(At(record, "key", code), code);
    Closed(key,
           {"inputs", "instruction_sequence_sha256", "effective_defaults", "painter_build", "project_settings",
            "resource_hashes", "bake_backend", "render_state"},
           {}, code);
    for (const Value& item : AsArray(At(key, "inputs", code), code)) {
        const Object& input = AsObject(item, code);
        Closed(input, {"input_id", "sha256"}, {}, code);
        Require(!StringAt(input, "input_id", code).empty() && core::IsSha256Hex(StringAt(input, "sha256", code)), code);
    }
    Require(core::IsSha256Hex(StringAt(key, "instruction_sequence_sha256", code)), code);
    AsObject(At(key, "effective_defaults", code), code);
    const Object& build = AsObject(At(key, "painter_build", code), code);
    Closed(build, {"product", "version", "build_id"}, {}, code);
    Require(StringAt(build, "product", code) == "Adobe Substance 3D Painter" && Version(StringAt(build, "version", code)) &&
                !StringAt(build, "build_id", code).empty(),
            code);
    AsObject(At(key, "project_settings", code), code);
    for (const Value& item : AsArray(At(key, "resource_hashes", code), code)) {
        const Object& resource = AsObject(item, code);
        Closed(resource, {"resource", "sha256"}, {}, code);
        Require(!StringAt(resource, "resource", code).empty() && core::IsSha256Hex(StringAt(resource, "sha256", code)), code);
    }
    const Value& backend = At(key, "bake_backend", code);
    Require(backend.IsNull() || SameTyped(backend, Value("cpu")) || SameTyped(backend, Value("gpu")), code);
    const Value& render = At(key, "render_state", code);
    Require(render.IsNull() || render.IsObject(), code);

    for (const Value& item : AsArray(At(record, "recordings", code), code)) {
        const Object& recording = AsObject(item, code);
        Closed(recording, {"recording_id", "condition", "session_id", "recorded_at", "outputs"}, {}, code);
        Require(RecordId(StringAt(recording, "recording_id", code)), code);
        const std::string& condition = StringAt(recording, "condition", code);
        Require(condition == "same_session" || condition == "after_save_reopen" || condition == "separate_session" ||
                    condition == "k_times_samples",
                code);
        Require(!StringAt(recording, "session_id", code).empty(), code);
        StringAt(recording, "recorded_at", code);
        const Array& outputs = AsArray(At(recording, "outputs", code), code);
        Require(!outputs.empty(), code);
        // Each output's own closed shape is checked by the slices that read it (C2, C3).
        for (const Value& output : outputs) AsObject(output, code);
    }
}

void CheckEnvironmentShape(const Object& environment) {
    const std::string_view code = filter_gate::kReceipt;
    Closed(environment,
           {"schema", "basis", "painter_build", "gpu_model", "driver_version", "os_build", "colour_configuration_sha256",
            "recorder_version"},
           {"operator_id"}, code);
    Require(StringAt(environment, "schema", code) == "uzpainter/parity/oracle-environment/1", code);
    const std::string& basis = StringAt(environment, "basis", code);
    Require(basis == "recorded" || basis == "backfilled", code);
    for (const std::string_view field : {"painter_build", "gpu_model", "driver_version", "os_build", "recorder_version"}) {
        Require(KnownOrUnknown(At(environment, field, code)), code);
    }
    if (environment.contains("operator_id")) Require(KnownOrUnknown(At(environment, "operator_id", code)), code);
    const std::string& colour = StringAt(environment, "colour_configuration_sha256", code);
    Require(colour == "unknown" || core::IsSha256Hex(colour), code);
}

/// `recorded_request_environment_matches` for a manifest that names no OCIO configuration, against
/// the registry's current `entry`.
bool JoinsApprovedEnvelope(const Object& environment, const Object& entry) {
    const std::string_view code = filter_gate::kReceipt;
    if (StringAt(environment, "basis", code) != "recorded") return false;
    Object fields;
    for (const std::string_view field :
         {"painter_build", "gpu_model", "driver_version", "os_build", "colour_configuration_sha256"}) {
        const Value& value = At(environment, field, code);
        if (!value.IsString()) return false;
        const std::string& text = std::get<std::string>(value.data);
        if (text.empty() || text == "unknown") return false;
        fields[std::string(field)] = text;
    }
    if (!SameTyped(fields.at("painter_build"), At(entry, "painter_build", code))) return false;
    const Value hash(core::Sha256Hex(core::json::WriteCanonical(fields)));
    if (SameTyped(hash, At(entry, "envelope_sha256", code))) return true;
    for (const Value& equivalent : AsArray(At(entry, "equivalent_envelopes", code), code)) {
        if (SameTyped(hash, equivalent)) return true;
    }
    return false;
}

/// The registry's `current` entry (exactly one envelope with that id), or nothing.
std::optional<Object> CurrentEntry(std::string_view bytes) {
    try {
        const Value document = core::json::Parse(bytes);
        if (!document.IsObject()) return std::nullopt;
        const Object& registry = std::get<Object>(document.data);
        const auto current = registry.find("current");
        const auto envelopes = registry.find("envelopes");
        if (current == registry.end() || !current->second.IsString() || envelopes == registry.end() ||
            !envelopes->second.IsArray()) {
            return std::nullopt;
        }
        std::optional<Object> entry;
        for (const Value& candidate : std::get<Array>(envelopes->second.data)) {
            if (!candidate.IsObject()) return std::nullopt;
            const Object& object = std::get<Object>(candidate.data);
            const auto id = object.find("envelope_id");
            if (id == object.end() || !SameTyped(id->second, current->second)) continue;
            if (entry) return std::nullopt;
            entry = object;
        }
        return entry;
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

}  // namespace

std::expected<OracleStoreReader, ImportRefusal> OracleStoreReader::Open(const fs::path& root, const fs::path& registry) {
    const auto refused = [] {
        return std::expected<OracleStoreReader, ImportRefusal>(std::unexpect,
                                                               Refusal(std::string(filter_gate::kStoreUnavailable)));
    };
    try {
        const fs::path absolute = fs::absolute(root).lexically_normal();
        // A store is private: the root and every ancestor are plain folders, and none of them is
        // a UzPainter checkout (parity/CONTRACT.md 6.4).
        std::error_code error;
        for (fs::path ancestor = absolute;; ancestor = ancestor.parent_path()) {
            if (ReparseOrMissing(ancestor)) return refused();
            if (fs::exists(ancestor / ".git", error) && fs::exists(ancestor / "build.zig", error)) return refused();
            if (ancestor == ancestor.parent_path()) break;
        }
        Handle folder(CreateFileW(absolute.c_str(), FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                                  nullptr, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
        if (folder.value == INVALID_HANDLE_VALUE) return refused();
        BY_HANDLE_FILE_INFORMATION info{};
        if (!GetFileInformationByHandle(folder.value, &info) || (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) == 0 ||
            (info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
            return refused();
        }
        const auto final_root = FinalPath(folder.value);
        if (!final_root) return refused();
        const auto marker = ReadFenced(absolute, *final_root, {"store.json"});
        if (!marker) return refused();
        const Value document = core::json::Parse(*marker);
        if (!document.IsObject()) return refused();
        const Object& object = std::get<Object>(document.data);
        if (object.size() != 2 || !object.contains("schema") || !object.contains("hash") ||
            !SameTyped(object.at("schema"), Value("uzpainter/parity/store/1")) || !SameTyped(object.at("hash"), Value("sha256"))) {
            return refused();
        }
        return OracleStoreReader(absolute, *final_root, fs::absolute(registry).lexically_normal());
    } catch (const std::exception&) {
        return refused();
    }
}

std::optional<ImportRefusal> OracleStoreReader::RequireAdmitted(std::string_view build_id, std::string_view golden_id,
                                                                const AdmittedRef& ref) const {
    const ImportRefusal refused = Refusal(std::string(filter_gate::kReceipt));
    try {
        if (observe_) observe_("entry");
        // The ids are validated before any path is built from them.
        if (!BuildDir(build_id) || !GoldenId(golden_id) || !RecordId(ref.record_id)) return refused;
        std::vector<std::string> parts{"corpora", std::string(build_id)};
        for (std::size_t start = 0;;) {
            const std::size_t slash = golden_id.find('/', start);
            parts.emplace_back(golden_id.substr(start, slash == std::string_view::npos ? slash : slash - start));
            if (slash == std::string_view::npos) break;
            start = slash + 1;
        }
        parts.push_back(ref.record_id + ".json");
        const auto bytes = ReadFenced(root_, final_root_, parts);
        if (!bytes) return refused;
        const Value document = core::json::Parse(*bytes);
        if (!document.IsObject()) return refused;
        const Object& entry = std::get<Object>(document.data);
        Closed(entry, {"schema", "painter_build_id", "golden_id", "record_id", "kind", "sha256", "size_bytes", "file_name"},
               {}, filter_gate::kReceipt);
        const bool joins = SameTyped(entry.at("schema"), Value("uzpainter/parity/store-entry/1")) &&
                           SameTyped(entry.at("painter_build_id"), Value(build_id)) &&
                           SameTyped(entry.at("golden_id"), Value(golden_id)) &&
                           SameTyped(entry.at("record_id"), Value(ref.record_id)) &&
                           SameTyped(entry.at("kind"), Value(ref.kind)) && SameTyped(entry.at("sha256"), Value(ref.sha256)) &&
                           SameTyped(entry.at("size_bytes"), Value(ref.size_bytes)) && entry.at("file_name").IsString();
        if (!joins) return refused;
        return std::nullopt;
    } catch (const FilterAdmissionRefused&) {
        return refused;
    } catch (const std::exception&) {
        return refused;
    }
}

std::optional<std::string> OracleStoreReader::SnapshotAdmissionBytes(std::string_view capture_id,
                                                                  std::string_view policy_sha256) const {
    if (observe_) observe_("snapshot-admission");
    if (!core::IsSha256Hex(capture_id) || !core::IsSha256Hex(policy_sha256)) return std::nullopt;
    return ReadFenced(root_, final_root_,
                      {"snapshot-captures", std::string(capture_id), std::string(policy_sha256) + ".json"});
}

std::optional<std::string> OracleStoreReader::SnapshotPolicyBytes(std::string_view policy_sha256) const {
    if (observe_) observe_("snapshot-policy");
    if (!core::IsSha256Hex(policy_sha256)) return std::nullopt;
    return ReadFenced(root_, final_root_, {"snapshot-producer-policies", std::string(policy_sha256) + ".json"});
}

std::optional<std::string> OracleStoreReader::Blob(std::string_view sha256, std::optional<std::int64_t> size_bytes) const {
    try {
        if (observe_) observe_("blob");
        if (!core::IsSha256Hex(sha256)) return std::nullopt;
        const std::string name(sha256);
        auto bytes = ReadFenced(root_, final_root_, {"blobs", name.substr(0, 2), name});
        if (!bytes || core::Sha256Hex(*bytes) != sha256) return std::nullopt;
        if (size_bytes && static_cast<std::int64_t>(bytes->size()) != *size_bytes) return std::nullopt;
        return bytes;
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

std::optional<std::string> OracleStoreReader::RegistryBytes() const {
    try {
        if (observe_) observe_("registry");
        return ReadHandle(registry_, std::wstring());
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

const std::string* AdmittedFilterCapture::Image(std::string_view record_id) const {
    const auto found = images_.find(record_id);
    return found == images_.end() ? nullptr : &found->second;
}

Object AdmittedFilterCapture::Identity() const {
    return Object{{"manifest_sha256", manifest_ref_.at("sha256")},
                  {"record_sha256", refs_.at(0).sha256},
                  {"environment_sha256", refs_.at(1).sha256},
                  {"registry_sha256", registry_sha256_},
                  {"envelope_id", envelope_id_},
                  {"producer", producer_},
                  {"gate_code_sha256", FilterGateCodeSha256()}};
}

std::expected<AdmittedFilterCapture, ImportRefusal> AdmittedFilterCapture::Admit(std::string_view manifest_bytes,
                                                                                 const Object& manifest_ref,
                                                                                 const OracleStoreReader& store,
                                                                                 const FilterGatePins& pins) {
    // 0. The registry before admission: the reviewed bytes, and the approved envelope current.
    const auto initial = store.RegistryBytes();
    if (!initial) return Unexpected(Refusal(std::string(filter_gate::kRegistryUnavailable)));
    const auto entry = CurrentEntry(*initial);
    if (*initial != pins.registry_bytes || !entry || !entry->contains("envelope_id") ||
        !SameTyped(entry->at("envelope_id"), Value(pins.envelope_id))) {
        return Unexpected(Refusal(std::string(filter_gate::kRegistryDrift)));
    }

    auto result = AdmitUnder(manifest_bytes, manifest_ref, store, pins, *entry);

    // 9. The registry after admission, on success and on refusal: a drift supersedes the outcome.
    if (store.before_final_registry_) store.before_final_registry_();
    const auto after = store.RegistryBytes();
    bool drift = !after || *after != *initial;
    if (!drift) {
        const auto again = CurrentEntry(*after);
        drift = !again || !SameTyped(*again, *entry);
    }
    if (drift) {
        std::string detail(filter_gate::kRegistryDrift);
        if (!result) detail += ":" + result.error().detail;
        return Unexpected(Refusal(std::move(detail)));
    }
    if (result) result->registry_sha256_ = core::Sha256Hex(*initial);
    return result;
}

std::expected<AdmittedFilterCapture, ImportRefusal> AdmittedFilterCapture::AdmitUnder(std::string_view manifest_bytes,
                                                                                      const Object& manifest_ref,
                                                                                      const OracleStoreReader& store,
                                                                                      const FilterGatePins& pins,
                                                                                      const Object& entry) {
    try {
        AdmittedFilterCapture admitted;
        {
            const std::string_view code = filter_gate::kRegistryDrift;
            Require(SameTyped(At(entry, "status", code), Value("current")) &&
                        SameTyped(At(entry, "environment_known", code), Value(true)) &&
                        At(entry, "painter_build", code).IsString() && core::IsSha256Hex(StringAt(entry, "envelope_sha256", code)),
                    code);
            for (const Value& equivalent : AsArray(At(entry, "equivalent_envelopes", code), code)) {
                Require(equivalent.IsString() && core::IsSha256Hex(std::get<std::string>(equivalent.data)), code);
            }
        }
        const std::string& painter_build = std::get<std::string>(entry.at("painter_build").data);

        // 1. The caller's manifest bytes, its reference and the fixed request's invariants.
        std::string_view code = filter_gate::kManifest;
        Closed(manifest_ref, {"kind", "sha256", "size_bytes"}, {}, code);
        Require(StringAt(manifest_ref, "kind", code) == "filter_manifest" &&
                    core::IsSha256Hex(StringAt(manifest_ref, "sha256", code)) &&
                    NonnegativeInt(At(manifest_ref, "size_bytes", code)),
                code);
        Require(core::Sha256Hex(manifest_bytes) == StringAt(manifest_ref, "sha256", code) &&
                    std::get<std::int64_t>(manifest_ref.at("size_bytes").data) ==
                        static_cast<std::int64_t>(manifest_bytes.size()),
                code);
        const Object manifest = AsObject(Decode(manifest_bytes, code), code);
        const Object request = AsObject(Decode(pins.request_bytes, filter_gate::kRegistryDrift), filter_gate::kRegistryDrift);
        // Each reference closed as `golden-public.json` `private_record_ref` says.
        for (const Value& item : AsArray(At(manifest, "private_records", code), code)) {
            const Object& ref = AsObject(item, code);
            Closed(ref, {"record_id", "kind", "sha256", "size_bytes"}, {}, code);
            const std::string& kind = StringAt(ref, "kind", code);
            bool knownKind = false;
            for (const std::string_view name :
                 {"private_oracle_record", "exported_map", "exported_sidecar", "api_readback", "effective_default_capture",
                  "template_capture", "iray_reference", "operator_recorded_settings", "settings_panel_evidence",
                  "oracle_environment_record"}) {
                knownKind = knownKind || kind == name;
            }
            Require(knownKind && RecordId(StringAt(ref, "record_id", code)) && core::IsSha256Hex(StringAt(ref, "sha256", code)) &&
                        NonnegativeInt(ref.at("size_bytes")),
                    code);
        }
        const Object& painter = AsObject(At(AsObject(At(manifest, "software", code), code), "painter", code), code);
        Closed(painter, {"product", "version", "build_id"}, {}, code);
        const std::string& build_id = StringAt(painter, "build_id", code);
        Require(Version(StringAt(painter, "version", code)) && !build_id.empty() && build_id.size() <= 128, code);
        StringAt(painter, "product", code);
        Require(SameTyped(Invariant(manifest, code), Invariant(request, filter_gate::kRegistryDrift)), code);

        // 2. Recipe A.
        Require(core::Sha256Hex(core::json::WriteCanonical(At(manifest, "instruction_sequence", filter_gate::kRecipe))) ==
                    pins.recipe_sha256,
                filter_gate::kRecipe);

        // 3. Exactly the twelve fixed references.
        code = filter_gate::kReferences;
        const Array& records = AsArray(At(manifest, "private_records", code), code);
        Require(records.size() == 12, code);
        std::map<std::string, AdmittedRef, std::less<>> byId;
        std::vector<AdmittedRef> manifestOrder;
        for (const Value& item : records) {
            const Object& ref = std::get<Object>(item.data);
            AdmittedRef parsed{StringAt(ref, "record_id", code), StringAt(ref, "kind", code), StringAt(ref, "sha256", code), 0};
            parsed.size_bytes = std::get<std::int64_t>(ref.at("size_bytes").data);
            Require(byId.emplace(parsed.record_id, parsed).second, code);
            manifestOrder.push_back(std::move(parsed));
        }
        for (const auto& [id, kind] : ExpectedRefs()) {
            const auto found = byId.find(id);
            Require(found != byId.end() && found->second.kind == kind, code);
            admitted.refs_.push_back(found->second);
        }

        // 4. All twelve store entries before the first blob, then the record and environment blobs.
        code = filter_gate::kReceipt;
        const std::string& golden = StringAt(manifest, "golden_id", code);
        for (const AdmittedRef& ref : manifestOrder) {
            if (const auto refusal = store.RequireAdmitted(build_id, golden, ref)) return Unexpected(*refusal);
        }
        const auto recordBytes = store.Blob(admitted.refs_[0].sha256, admitted.refs_[0].size_bytes);
        const auto environmentBytes = store.Blob(admitted.refs_[1].sha256, admitted.refs_[1].size_bytes);
        Require(recordBytes && environmentBytes, code);
        const Object record = AsObject(Decode(*recordBytes, code), code);
        const Object environment = AsObject(Decode(*environmentBytes, code), code);
        CheckRecordShape(record);
        CheckEnvironmentShape(environment);
        Require(record.contains("environment") && SameTyped(record.at("environment"), environment), code);

        // 5. The reviewed settings producer.
        Require(StringAt(environment, "recorder_version", code) == pins.settings_producer, filter_gate::kProducer);

        // 6. The receipt's identity, envelope, key and recordings.
        Require(SameTyped(record.at("golden_id"), At(request, "golden_id", code)) && SameTyped(record.at("tier"), Value("0")),
                code);
        const Object& requestPainter = AsObject(At(AsObject(At(request, "software", code), code), "painter", code), code);
        const std::size_t marker = build_id.find("+js-api.");
        Require(build_id == painter_build && StringAt(painter, "version", code) == build_id.substr(0, marker) &&
                    SameTyped(painter.at("product"), At(requestPainter, "product", code)),
                code);
        Require(JoinsApprovedEnvelope(environment, entry), code);
        Require(StringAt(environment, "colour_configuration_sha256", code) == LegacyColourSha256(), code);
        const Object& key = std::get<Object>(record.at("key").data);
        Require(SameTyped(key.at("painter_build"), painter), code);
        Array inputs;
        for (const Value& item : AsArray(At(request, "inputs", code), code)) {
            const Object& input = AsObject(item, code);
            inputs.push_back(Object{{"input_id", At(input, "input_id", code)}, {"sha256", At(input, "sha256", code)}});
        }
        Require(SameTyped(key.at("inputs"), inputs) &&
                    SameTyped(key.at("instruction_sequence_sha256"), Value(pins.recipe_sha256)),
                code);
        Object create;
        for (const Value& step : AsArray(At(AsObject(At(request, "instruction_sequence", code), code), "steps", code), code)) {
            const Object& object = AsObject(step, code);
            if (!SameTyped(At(object, "call", code), Value("substance_painter.project.create"))) continue;
            create = AsObject(At(object, "args", code), code);
            create.erase("mesh");
            break;
        }
        Require(SameTyped(key.at("project_settings"), Object{{"create", create}, {"colour_management", Legacy()}}), code);
        const Object& defaults = std::get<Object>(key.at("effective_defaults").data);
        Require(defaults.contains("colour_management") && SameTyped(defaults.at("colour_management"), Legacy()), code);
        Require(SameTyped(key.at("resource_hashes"), Array{}) && key.at("bake_backend").IsNull() &&
                    key.at("render_state").IsNull(),
                code);
        const Array& recordings = std::get<Array>(record.at("recordings").data);
        Require(recordings.size() == 2, code);
        const Object& first = std::get<Object>(recordings[0].data);
        const Object& second = std::get<Object>(recordings[1].data);
        Require(SameTyped(first.at("recording_id"), Value("r1")) && SameTyped(first.at("condition"), Value("same_session")) &&
                    SameTyped(second.at("recording_id"), Value("r2")) &&
                    SameTyped(second.at("condition"), Value("after_save_reopen")) &&
                    SameTyped(first.at("session_id"), second.at("session_id")),
                code);
        // The authored input must be available in the store (Python `store.resolve`).
        const auto plane = store.Blob(pins.plane_sha256, std::nullopt);
        Require(plane.has_value(), code);

        // 7. The ten settings images, rehashed with their sizes.
        for (std::size_t i = 2; i < admitted.refs_.size(); ++i) {
            const AdmittedRef& ref = admitted.refs_[i];
            auto bytes = store.Blob(ref.sha256, ref.size_bytes);
            Require(bytes.has_value(), filter_gate::kImageBytes);
            admitted.images_.emplace(ref.record_id, std::move(*bytes));
        }

        // 8. The request's one plane input, as its pinned blob.
        Require(inputs.size() == 1 && SameTyped(std::get<Object>(inputs[0].data).at("input_id"), Value("plane")) &&
                    SameTyped(std::get<Object>(inputs[0].data).at("sha256"), Value(pins.plane_sha256)),
                filter_gate::kInputs);
        Require(core::Sha256Hex(*plane) == pins.plane_sha256, filter_gate::kInputBytes);

        admitted.manifest_ = manifest;
        admitted.manifest_ref_ = manifest_ref;
        admitted.record_ = record;
        admitted.environment_ = environment;
        admitted.plane_ = *plane;
        admitted.envelope_id_ = pins.envelope_id;
        admitted.producer_ = pins.settings_producer;
        return admitted;
    } catch (const FilterAdmissionRefused& refused) {
        return Unexpected(Refusal(std::string(refused.code)));
    } catch (const std::exception&) {
        return Unexpected(Refusal(std::string(filter_gate::kReceipt)));
    }
}

std::expected<AdmittedFilterCapture, ImportRefusal> AdmitFilterCapture(std::string_view manifest_bytes,
                                                                     const Object& manifest_ref,
                                                                     const OracleStoreReader& store) {
    const auto pins = CompiledFilterGatePins();
    if (!pins) return Unexpected(pins.error());
    return AdmittedFilterCapture::Admit(manifest_bytes, manifest_ref, store, *pins);
}

}  // namespace uzp::procedural
