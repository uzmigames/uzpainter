#include "python/assets3d_guard.h"

#include <fstream>
#include <iterator>
#include <mutex>
#include <optional>

#include "python/errors.h"
#include "uzp_core/manifest/sha256.h"

namespace uzp::python::assets3d {

namespace {

namespace json = core::json;

constexpr std::string_view kPolicySchema = "uzpainter/assets3d-native-policy/1";
constexpr std::string_view kStatusSchema = "uzpainter/assets3d-production-status/1";

struct Pin {
    std::filesystem::path path;
    std::string sha256;
    std::int64_t size = 0;
};

struct Policy {
    std::string source_sha256;
    std::int64_t source_size = 0;
    std::string import_report;  ///< Canonical JSON of the admitted report.
    std::string request_sha256;
    std::vector<Pin> pins;
};

std::mutex g_mutex;
Mode g_mode = Mode::absent;
std::optional<Policy> g_policy;

[[noreturn]] void Refuse(const std::string& message) {
    throw ApiError("Assets3DProductionError", "Assets3D production guard: " + message);
}

std::filesystem::path PathFromUtf8(const std::string& text) {
    return std::filesystem::path(std::u8string(text.begin(), text.end()));
}

const json::Value& Member(const json::Object& object, const char* name) {
    const auto it = object.find(name);
    if (it == object.end()) Refuse(std::string("the policy has no ") + name);
    return it->second;
}

std::string Sha(const json::Object& object, const char* name) {
    const json::Value& value = Member(object, name);
    if (!value.IsString() || !core::IsSha256Hex(std::get<std::string>(value.data))) {
        Refuse(std::string("policy ") + name + " must be a lowercase SHA-256");
    }
    return std::get<std::string>(value.data);
}

std::int64_t Size(const json::Value& value, const std::string& what) {
    if (!value.IsInt() || std::get<std::int64_t>(value.data) < 0) Refuse(what + " must be a non-negative integer");
    return std::get<std::int64_t>(value.data);
}

Policy Parse(const std::string& text) {
    json::Value parsed;
    try {
        parsed = json::Parse(text);
    } catch (const std::exception& error) {
        Refuse(std::string("the policy is not JSON: ") + error.what());
    }
    const auto* object = std::get_if<json::Object>(&parsed.data);
    if (object == nullptr) Refuse("the policy is not an object");
    for (const auto& [key, ignored] : *object) {
        if (key != "schema" && key != "source_sha256" && key != "source_size" && key != "import_report" &&
            key != "request_sha256" && key != "pins") {
            Refuse("the policy has the unknown member " + key);
        }
    }
    const json::Value& schema = Member(*object, "schema");
    if (!schema.IsString() || std::get<std::string>(schema.data) != kPolicySchema) {
        Refuse("the policy schema must be " + std::string(kPolicySchema));
    }
    Policy policy;
    policy.source_sha256 = Sha(*object, "source_sha256");
    policy.source_size = Size(Member(*object, "source_size"), "policy source_size");
    const json::Value& report = Member(*object, "import_report");
    if (!report.IsObject()) Refuse("policy import_report must be the complete import report object");
    policy.import_report = json::WriteCanonical(report);
    policy.request_sha256 = Sha(*object, "request_sha256");
    const auto* pins = std::get_if<json::Array>(&Member(*object, "pins").data);
    if (pins == nullptr || pins->empty()) Refuse("policy pins must be a nonempty array");
    bool request = false;
    for (const json::Value& item : *pins) {
        const auto* pin = std::get_if<json::Object>(&item.data);
        if (pin == nullptr || pin->size() != 3) Refuse("a pin is an object of exactly path, sha256 and size");
        const json::Value& path = Member(*pin, "path");
        if (!path.IsString() || !PathFromUtf8(std::get<std::string>(path.data)).is_absolute()) {
            Refuse("a pin path must be an absolute path");
        }
        Pin parsedPin{PathFromUtf8(std::get<std::string>(path.data)), Sha(*pin, "sha256"),
                      Size(Member(*pin, "size"), "a pin size")};
        request = request || parsedPin.sha256 == policy.request_sha256;
        policy.pins.push_back(std::move(parsedPin));
    }
    if (!request) Refuse("no pin covers the request (request_sha256)");
    return policy;
}

/// Every pin re-hashed from disk, before anything is persisted.
void VerifyPins(const Policy& policy) {
    for (const Pin& pin : policy.pins) {
        std::ifstream stream(pin.path, std::ios::binary);
        if (!stream) Refuse("a pinned file is unreadable: " + pin.path.generic_string());
        const std::string bytes{std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};
        if (static_cast<std::int64_t>(bytes.size()) != pin.size || core::Sha256Hex(bytes) != pin.sha256) {
            Refuse("a pinned file changed since the preflight: " + pin.path.generic_string());
        }
    }
}

/// The armed policy, its pins verified; nullopt when absent.
std::optional<Policy> Armed(const std::string& boundary) {
    std::lock_guard lock(g_mutex);
    if (g_mode == Mode::absent) return std::nullopt;
    if (g_mode == Mode::required || !g_policy) Refuse(boundary + " refused: no production policy is installed");
    VerifyPins(*g_policy);
    return g_policy;
}

void CheckReport(const Policy& policy, const json::Object& report, const std::string& boundary) {
    const auto certificate = report.find("certificate");
    if (certificate != report.end() && certificate->second.IsObject()) {
        const auto& object = std::get<json::Object>(certificate->second.data);
        const auto status = object.find("status");
        if (status != object.end() && status->second.IsString() && std::get<std::string>(status->second.data) == "fail") {
            Refuse(boundary + " refused: the mesh certificate is fail");
        }
    }
    if (json::WriteCanonical(json::Value(report)) != policy.import_report) {
        Refuse(boundary + " refused: the import report differs from the admitted report");
    }
}

}  // namespace

void Require() {
    std::lock_guard lock(g_mutex);
    if (g_mode == Mode::absent) g_mode = Mode::required;
}

Mode CurrentMode() {
    std::lock_guard lock(g_mutex);
    return g_mode;
}

void InstallPolicy(const std::string& policy_json) {
    Policy policy = Parse(policy_json);
    std::lock_guard lock(g_mutex);
    if (g_mode == Mode::absent) Refuse("no production round was required for this process");
    if (g_mode == Mode::armed) Refuse("a production policy is already installed and cannot be replaced");
    VerifyPins(policy);
    g_policy = std::move(policy);
    g_mode = Mode::armed;
}

json::Object Status() {
    std::lock_guard lock(g_mutex);
    const char* mode = g_mode == Mode::absent ? "absent" : g_mode == Mode::required ? "required" : "armed";
    return json::Object{
        {"schema", std::string(kStatusSchema)},
        {"mode", std::string(mode)},
        {"policy_installed", g_policy.has_value()},
        {"request_sha256", g_policy ? json::Value(g_policy->request_sha256) : json::Value(nullptr)},
        {"source_sha256", g_policy ? json::Value(g_policy->source_sha256) : json::Value(nullptr)},
    };
}

void CheckImport(const mesh::ImportResult& result) {
    const std::optional<Policy> policy = Armed("the mesh import");
    if (!policy) return;
    if (result.sha256 != policy->source_sha256 || result.size != policy->source_size) {
        Refuse("the mesh import refused: the mesh bytes are not the admitted source");
    }
    CheckReport(*policy, result.report, "the mesh import");
}

void RequireAdmittedProject(const core::Project& project) {
    const std::optional<Policy> policy = Armed("the project change");
    if (!policy) return;
    if (!project.mesh || project.mesh->resource != policy->source_sha256) {
        Refuse("the project change refused: the project's mesh is not the admitted source");
    }
    CheckReport(*policy, project.mesh->import_report, "the project change");
}

std::optional<double> RequestedMeshUnitScale(const core::Project& project) {
    if (!project.mesh) return std::nullopt;
    const auto units = project.mesh->import_report.find("units");
    if (units == project.mesh->import_report.end() || !units->second.IsObject()) return std::nullopt;
    const auto& object = std::get<json::Object>(units->second.data);
    const auto requested = object.find("requested_mesh_unit_scale");
    if (requested == object.end()) return std::nullopt;
    if (requested->second.IsInt()) return static_cast<double>(std::get<std::int64_t>(requested->second.data));
    if (requested->second.IsDouble()) return std::get<double>(requested->second.data);
    return std::nullopt;
}

void RefuseRestore(const std::string& operation) {
    if (CurrentMode() == Mode::absent) return;
    Refuse(operation + " is refused in production: it restores a stored revision past the admission checks");
}

void CheckOpenPath(const std::filesystem::path& path) {
    const std::optional<Policy> policy = Armed("opening a project");
    if (!policy) return;
    std::error_code error;
    if (std::filesystem::is_directory(path, error)) {
        Refuse("opening a bundle directory is refused in production (its import writes before any check)");
    }
}

}  // namespace uzp::python::assets3d
