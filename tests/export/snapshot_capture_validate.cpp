#include "snapshot_capture_validate.h"

#include <fcntl.h>
#include <io.h>
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <initializer_list>
#include <limits>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>

#include "procedural/filter_observation_import_v2.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/sha256.h"

namespace {

namespace fs = std::filesystem;
namespace json = uzp::core::json;
using namespace uzp;

constexpr std::size_t kInputLimit = 65536;
constexpr std::string_view kInputSchema = "uzpainter/parity/snapshot-capture-validation-input/1";
constexpr std::string_view kReportSchema = "uzpainter/parity/snapshot-capture-validation/1";
constexpr std::string_view kValidatorRevision = "uzpainter/snapshot-capture-validator/1";
constexpr std::string_view kSourcesDomain = "uzpainter/snapshot-capture-validator-sources/1";
constexpr std::string_view kProtocol = "paired-scalar-rgb";
constexpr std::string_view kInputInvalid = "INPUT_INVALID";
constexpr std::string_view kValidatorUnavailable = "VALIDATOR_UNAVAILABLE";

// The validator's sources, embedded at build time (decision 147).
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wc23-extensions"
constexpr unsigned char kDiagnosticHeader[] = {
#embed "snapshot_capture_validate.h"
};
constexpr unsigned char kDiagnosticSource[] = {
#embed "snapshot_capture_validate.cpp"
};
constexpr unsigned char kImportHeader[] = {
#embed "../../src/procedural/filter_observation_import_v2.h"
};
constexpr unsigned char kImportSource[] = {
#embed "../../src/procedural/filter_observation_import_v2.cpp"
};
constexpr unsigned char kRecordingHeader[] = {
#embed "../../src/procedural/snapshot_recording.h"
};
constexpr unsigned char kRecordingSource[] = {
#embed "../../src/procedural/snapshot_recording.cpp"
};
constexpr unsigned char kSnapshotsHeader[] = {
#embed "../../src/store/snapshots.h"
};
constexpr unsigned char kSnapshotsSource[] = {
#embed "../../src/store/snapshots.cpp"
};
#pragma clang diagnostic pop

/// A refusal with its value-free reason code.
struct Refused {
    std::string code;
};

void Require(bool condition, std::string_view code = kInputInvalid) {
    if (!condition) throw Refused{std::string(code)};
}

const json::Object& Closed(const json::Value& value, std::initializer_list<std::string_view> members) {
    const auto* object = std::get_if<json::Object>(&value.data);
    Require(object != nullptr && object->size() == members.size());
    for (const std::string_view name : members) Require(object->contains(name));
    return *object;
}

/// The whole file at `path`, read to its size: a short, long or failed read refuses rather than
/// returning part of it.
std::string ReadWhole(const fs::path& path, std::string_view code) {
    std::error_code error;
    const std::uintmax_t size = fs::file_size(path, error);
    Require(!error && size <= static_cast<std::uintmax_t>(std::numeric_limits<std::streamsize>::max()), code);
    std::ifstream file(path, std::ios::binary);
    Require(static_cast<bool>(file), code);
    std::string bytes(static_cast<std::size_t>(size), '\0');
    file.read(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    // The end is checked before the error state: peek() itself can fail and set badbit.
    const bool complete = file.gcount() == static_cast<std::streamsize>(bytes.size()) &&
                          file.peek() == std::ifstream::traits_type::eof();
    Require(complete && !file.bad(), code);
    return bytes;
}

/// The bytes of the regular file (not a link) an input slot names by absolute UTF-8 path, read once.
std::string SlotBytes(const json::Value& slot) {
    const auto* text = std::get_if<std::string>(&Closed(slot, {"path"}).at("path").data);
    Require(text != nullptr && !text->empty() && text->find('\0') == std::string::npos);
    const fs::path path(std::u8string(text->begin(), text->end()));
    Require(path.is_absolute());
    std::error_code error;
    const fs::file_status status = fs::symlink_status(path, error);
    Require(!error && fs::is_regular_file(status));
    return ReadWhole(path, kInputInvalid);
}

/// The SHA-256 of the running executable's file, read whole.
std::string BinarySha256() {
    std::wstring name(32768, L'\0');
    const DWORD length = GetModuleFileNameW(nullptr, name.data(), static_cast<DWORD>(name.size()));
    Require(length != 0 && length != name.size(), kValidatorUnavailable);
    name.resize(length);
    const std::string bytes = ReadWhole(fs::path(name), kValidatorUnavailable);
    Require(!bytes.empty(), kValidatorUnavailable);
    return core::Sha256Hex(bytes);
}

void AppendLength(std::string& out, std::uint64_t length) {
    for (int i = 0; i < 8; ++i) out.push_back(static_cast<char>((length >> (8 * i)) & 0xFF));
}

/// The report of one input, or a `Refused` naming its reason.
json::Object Report(std::string_view input) {
    Require(input.size() <= kInputLimit);
    json::Value value;
    try {
        value = json::Parse(std::string(input));  // UTF-8, no duplicate keys
    } catch (const std::exception&) {
        Require(false);
    }
    const json::Object& request = Closed(value, {"schema", "protocol", "receipt", "request", "scalar_exports", "rgb_exports"});
    Require(request.at("schema") == json::Value(std::string(kInputSchema)) &&
            request.at("protocol") == json::Value(std::string(kProtocol)));

    // Each slot read once into owned bytes; its reference computed from those bytes. Repeated
    // rounds keep their own slots even when their bytes are equal.
    std::map<std::string, std::string, std::less<>> owned;
    const auto slot = [&](const json::Value& item, const std::string& record, const std::string& kind) {
        std::string bytes = SlotBytes(item);
        const std::string sha = core::Sha256Hex(bytes);
        const auto size = static_cast<std::int64_t>(bytes.size());
        owned.insert_or_assign(sha, std::move(bytes));
        return json::Object{{"record_id", record}, {"kind", kind}, {"sha256", sha}, {"size_bytes", size}};
    };
    const auto rounds = [&](const char* field, const std::string& role) {
        const auto* list = std::get_if<json::Array>(&request.at(field).data);
        Require(list != nullptr && list->size() == 2);
        json::Array refs;
        for (std::size_t i = 0; i < 2; ++i) {
            refs.push_back(slot((*list)[i], "r" + std::to_string(i + 1) + "-" + role, "snapshot_" + role + "_export"));
        }
        return refs;
    };
    json::Object slots;
    slots["receipt"] = slot(request.at("receipt"), "receipt", "snapshot_receipt");
    slots["request"] = slot(request.at("request"), "request", "snapshot_request");
    slots["environment"] = json::Value();
    slots["environment_binding"] = json::Value();
    slots["scalar_exports"] = rounds("scalar_exports", "scalar");
    slots["rgb_exports"] = rounds("rgb_exports", "rgb");

    // The capture/2 host section: the same references without their slot ids.
    const auto bare = [](const json::Value& ref) {
        json::Object copy = std::get<json::Object>(ref.data);
        copy.erase("record_id");
        return copy;
    };
    const auto bareRounds = [&](const char* field) {
        json::Array refs;
        for (const json::Value& ref : std::get<json::Array>(slots.at(field).data)) refs.push_back(bare(ref));
        return refs;
    };
    const json::Object host{{"protocol", std::string(kProtocol)},
                            {"receipt", bare(slots.at("receipt"))},
                            {"request", bare(slots.at("request"))},
                            {"environment", json::Value()},
                            {"environment_binding", json::Value()},
                            {"scalar_exports", bareRounds("scalar_exports")},
                            {"rgb_exports", bareRounds("rgb_exports")}};
    const auto validated = procedural::ValidateHostCaptureArtifacts(
        host, [&](std::string_view sha) -> std::optional<std::string> {
            const auto found = owned.find(sha);
            return found == owned.end() ? std::nullopt : std::optional<std::string>(found->second);
        });
    if (!validated) throw Refused{validated.error().reason};

    // The producer pins of the receipt the validation accepted (these same owned bytes).
    const std::string& receiptSha = std::get<std::string>(std::get<json::Object>(slots.at("receipt").data).at("sha256").data);
    const json::Value receipt = json::Parse(owned.at(receiptSha));
    const json::Object& recorder = std::get<json::Object>(std::get<json::Object>(receipt.data).at("recorder").data);
    const json::Object identity = validated->Identity();
    return json::Object{
        {"schema", std::string(kReportSchema)},
        {"protocol", std::string(kProtocol)},
        {"artifacts", std::move(slots)},
        {"producer", json::Object{{"bridge_sha256", recorder.at("bridge_sha256")},
                                  {"painter_side_sha256", recorder.at("painter_side_sha256")}}},
        {"signature_sha256", identity.at("signature_sha256")},
        {"metadata_sha256", identity.at("metadata_sha256")},
        {"capture_context_sha256", validated->CaptureContextSha256()},
        {"scalar_raster_sha256", validated->ScalarSha256()},
        {"validator", json::Object{{"revision", std::string(kValidatorRevision)},
                                   {"code_sha256", SnapshotCaptureValidatorCodeSha256()},
                                   {"binary_sha256", BinarySha256()}}}};
}

}  // namespace

std::string SnapshotCaptureValidatorCodeSha256() {
    const std::pair<std::string_view, std::string_view> files[] = {
        {"tests/export/snapshot_capture_validate.h", {reinterpret_cast<const char*>(kDiagnosticHeader), sizeof(kDiagnosticHeader)}},
        {"tests/export/snapshot_capture_validate.cpp", {reinterpret_cast<const char*>(kDiagnosticSource), sizeof(kDiagnosticSource)}},
        {"src/procedural/filter_observation_import_v2.h", {reinterpret_cast<const char*>(kImportHeader), sizeof(kImportHeader)}},
        {"src/procedural/filter_observation_import_v2.cpp", {reinterpret_cast<const char*>(kImportSource), sizeof(kImportSource)}},
        {"src/procedural/snapshot_recording.h", {reinterpret_cast<const char*>(kRecordingHeader), sizeof(kRecordingHeader)}},
        {"src/procedural/snapshot_recording.cpp", {reinterpret_cast<const char*>(kRecordingSource), sizeof(kRecordingSource)}},
        {"src/store/snapshots.h", {reinterpret_cast<const char*>(kSnapshotsHeader), sizeof(kSnapshotsHeader)}},
        {"src/store/snapshots.cpp", {reinterpret_cast<const char*>(kSnapshotsSource), sizeof(kSnapshotsSource)}}};
    std::string framed(kSourcesDomain);
    framed.push_back('\0');
    for (const auto& [name, bytes] : files) {
        AppendLength(framed, name.size());
        framed.append(name);
        AppendLength(framed, bytes.size());
        framed.append(bytes);
    }
    return core::Sha256Hex(framed);
}

int RunSnapshotCaptureValidate() {
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
    _setmode(_fileno(stderr), _O_BINARY);
    std::string input;
    char buffer[4096];
    std::size_t count = 0;
    while (input.size() <= kInputLimit && (count = std::fread(buffer, 1, sizeof(buffer), stdin)) > 0) input.append(buffer, count);
    std::string code;
    try {
        Require(!std::ferror(stdin));
        const std::string report = json::WriteCanonical(Report(input)) + "\n";
        std::fwrite(report.data(), 1, report.size(), stdout);
        std::fflush(stdout);
        return 0;
    } catch (const Refused& refused) {
        code = refused.code;
    } catch (const std::exception&) {
        code = std::string(kValidatorUnavailable);
    }
    std::fprintf(stderr, "snapshot-capture-validate refused: %s\n", code.c_str());
    return 2;
}
