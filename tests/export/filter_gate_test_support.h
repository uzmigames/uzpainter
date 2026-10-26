#pragma once

// The shared authored fixture of the native F gate's tests (slices C1-C3,
// `docs/filter-observations-v2.md` section 11). It is the ONE definition of the test-only
// `procedural::FilterGateTestAccess` (declared in `procedural/filter_gate_admission.h`, defined
// nowhere in production): every test translation unit includes this header, so the friend has a
// single definition (no ODR divergence). Everything here is authored: an oracle store laid out as
// `tools/parity/store/store.py` writes it, an envelope registry and pins whose envelope hash is the
// authored environment's, under the test's own work folder. Nothing reads a real store, capture or
// private value.
//
// A later slice's test sets `Capture::record`, `environment` and `images` (for example from a record
// the authored Python fixtures produced and wrote into the work folder), calls `Reference()`, then
// `AdmitAuthored` to obtain an `AdmittedFilterCapture` through the real C1 admission.

#include <algorithm>
#include <cstdint>
#include <expected>
#include <filesystem>
#include <fstream>
#include <functional>
#include <map>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#include "procedural/filter_gate_admission.h"
#include "procedural/filter_gate_pins.h"
#include "procedural/filter_import_cli.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/sha256.h"
#include "../filter_observation_v2_fixture.h"

namespace uzp::procedural {

/// The authored-tests-only route to admission under authored pins.
struct FilterGateTestAccess {
    static int RunCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err,
                          const std::filesystem::path& registry, const FilterGatePins& pins) {
        return FilterImportCommandDriver::Run(args, out, err, registry,
            [&pins](std::string_view bytes, const core::json::Object& ref, const OracleStoreReader& store) {
                return AdmittedFilterCapture::Admit(bytes, ref, store, pins);
            });
    }
    static std::expected<AdmittedFilterCapture, ImportRefusal> Admit(std::string_view manifest_bytes,
                                                                     const core::json::Object& manifest_ref,
                                                                     const OracleStoreReader& store,
                                                                     const FilterGatePins& pins) {
        return AdmittedFilterCapture::Admit(manifest_bytes, manifest_ref, store, pins);
    }
    /// Sets the store's private read observer (`entry`, `blob`, `registry`, before each read).
    static void Observe(OracleStoreReader& store, std::function<void(std::string_view)> observer) {
        store.observe_ = std::move(observer);
    }
    /// Sets the action run once right before admission's final registry read.
    static void BeforeFinalRegistryRead(OracleStoreReader& store, std::function<void()> action) {
        store.before_final_registry_ = std::move(action);
    }
};

}  // namespace uzp::procedural

namespace uzp::filter_gate_test {

namespace fs = std::filesystem;
namespace json = core::json;
namespace fx = v2fixture;

inline void Require(bool okay, const std::string& message) {
    if (!okay) throw std::runtime_error(message);
}

inline void WriteFile(const fs::path& path, const std::string& bytes) {
    fs::create_directories(path.parent_path());
    std::ofstream file(path, std::ios::binary);
    file.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    Require(static_cast<bool>(file), "write an authored fixture file");
}

inline json::Object& Obj(json::Value& value) { return std::get<json::Object>(value.data); }
inline json::Object& Obj(json::Object& object, const std::string& key) { return std::get<json::Object>(object.at(key).data); }
inline json::Array& Arr(json::Object& object, const std::string& key) { return std::get<json::Array>(object.at(key).data); }

inline json::Value Legacy() {
    return json::Object{{"mode", "legacy"}, {"OCIO", nullptr}, {"PAINTER_ACE_CONFIG", nullptr}};
}

/// The fixed image record ids in their fixed order.
inline std::vector<std::string> ImageIds() {
    std::vector<std::string> ids;
    for (const auto& [round, boundary] : std::vector<std::pair<std::string, std::string>>{
             {"r1", "after-create"}, {"r1", "after-setup6"}, {"r1", "pre16-r1"}, {"r2", "after-reopen"}, {"r2", "pre16-r2"}}) {
        for (const std::string image : {"configuration-image", "physical-size-image"}) {
            ids.push_back(round + "-settings-" + boundary + "-" + image);
        }
    }
    return ids;
}

/// One authored capture: what the manifest, record, environment, images and plane hold, and the
/// authored pins whose envelope hash is the authored environment's.
struct Capture {
    procedural::FilterGatePins pins;
    json::Object manifest;
    json::Object record;
    json::Object environment;
    std::map<std::string, std::string> images;
    std::string plane = fx::PlaneObj();
    /// Overrides applied after the references are computed (corrupt stored bytes, drop entries).
    std::map<std::string, std::string> stored_bytes;
    std::vector<std::string> missing_entries;
    std::map<std::string, json::Object> entry_overrides;
    bool store_plane = true;
    std::string manifest_text;  ///< When set, the manifest bytes as given (not canonical).
    std::string registry_text;  ///< When set, the registry bytes at the locator (not the pinned ones).
    bool write_registry = true;

    static json::Object EnvelopeFields(const json::Object& environment) {
        json::Object fields;
        for (const char* field : {"painter_build", "gpu_model", "driver_version", "os_build", "colour_configuration_sha256"}) {
            fields[field] = environment.at(field);
        }
        return fields;
    }

    Capture() {
        const auto compiled = procedural::CompiledFilterGatePins();
        Require(compiled.has_value(), "the compiled pins decode");
        pins = *compiled;
        const json::Value request = json::Parse(pins.request_bytes);
        manifest = std::get<json::Object>(request.data);
        environment = json::Object{
            {"schema", "uzpainter/parity/oracle-environment/1"},
            {"basis", "recorded"},
            {"painter_build", pins.painter_build},
            {"gpu_model", "authored gpu"},
            {"driver_version", "authored driver"},
            {"os_build", "10.0.1.0"},
            {"colour_configuration_sha256",
             core::Sha256Hex(json::WriteCanonical(json::Object{{"colour_management", Legacy()}, {"files", json::Object{}}}))},
            {"recorder_version", pins.settings_producer}};
        pins.envelope_sha256 = core::Sha256Hex(json::WriteCanonical(EnvelopeFields(environment)));
        pins.equivalent_envelopes.clear();
        Register();
        json::Object create;
        for (const json::Value& step : std::get<json::Array>(std::get<json::Object>(manifest.at("instruction_sequence").data).at("steps").data)) {
            const auto& object = std::get<json::Object>(step.data);
            if (json::WriteCanonical(object.at("call")) == json::WriteCanonical(json::Value("substance_painter.project.create"))) {
                create = std::get<json::Object>(object.at("args").data);
                create.erase("mesh");
                break;
            }
        }
        const json::Object painter = std::get<json::Object>(std::get<json::Object>(manifest.at("software").data).at("painter").data);
        const auto recording = [](const char* id, const char* condition) {
            return json::Object{{"recording_id", id},
                                {"condition", condition},
                                {"session_id", "authored-session"},
                                {"recorded_at", "2026-10-26T00:00:00Z"},
                                {"outputs", json::Array{json::Object{{"output_id", "authored"}, {"kind", "api_readback"}}}}};
        };
        record = json::Object{
            {"schema", "uzpainter/parity/golden-private/1"},
            {"record_class", "private_oracle_record"},
            {"golden_id", manifest.at("golden_id")},
            {"tier", "0"},
            {"key", json::Object{{"inputs", json::Array{json::Object{{"input_id", "plane"}, {"sha256", pins.plane_sha256}}}},
                                 {"instruction_sequence_sha256", pins.recipe_sha256},
                                 {"effective_defaults", json::Object{{"colour_management", Legacy()}}},
                                 {"painter_build", painter},
                                 {"project_settings", json::Object{{"create", create}, {"colour_management", Legacy()}}},
                                 {"resource_hashes", json::Array{}},
                                 {"bake_backend", nullptr},
                                 {"render_state", nullptr}}},
            {"recordings", json::Array{recording("r1", "same_session"), recording("r2", "after_save_reopen")}},
            {"environment", environment}};
        for (const std::string& id : ImageIds()) images[id] = "authored png " + id;
    }

    /// The authored registry whose current entry (by default) is the pinned envelope; its bytes
    /// become the pinned registry bytes.
    void Register(const std::string& current = {}) {
        json::Array equivalents;
        for (const std::string& hash : pins.equivalent_envelopes) equivalents.push_back(hash);
        const json::Object entry{{"envelope_id", pins.envelope_id},
                                 {"status", "current"},
                                 {"painter_build", pins.painter_build},
                                 {"envelope_sha256", pins.envelope_sha256},
                                 {"environment_known", true},
                                 {"equivalent_envelopes", equivalents}};
        const json::Object other{{"envelope_id", "authored-other-envelope"},
                                 {"status", "previous"},
                                 {"painter_build", pins.painter_build},
                                 {"envelope_sha256", core::Sha256Hex("other envelope")},
                                 {"environment_known", true},
                                 {"equivalent_envelopes", json::Array{}}};
        pins.registry_bytes = json::WriteCanonical(json::Object{{"schema", "uzpainter/parity/envelope-registry/1"},
                                                                {"current", current.empty() ? pins.envelope_id : current},
                                                                {"candidate", nullptr},
                                                                {"envelopes", json::Array{entry, other}},
                                                                {"quarantine", json::Array{}}});
    }

    static json::Object Ref(const std::string& id, const std::string& kind, const std::string& bytes) {
        return json::Object{{"record_id", id},
                            {"kind", kind},
                            {"sha256", core::Sha256Hex(bytes)},
                            {"size_bytes", static_cast<std::int64_t>(bytes.size())}};
    }

    /// The manifest's references over the current record, environment and images.
    void Reference() {
        json::Array refs{Ref("golden-record", "private_oracle_record", json::WriteCanonical(record)),
                         Ref("oracle-environment", "oracle_environment_record", json::WriteCanonical(environment))};
        for (const std::string& id : ImageIds()) refs.push_back(Ref(id, "settings_panel_evidence", images.at(id)));
        manifest["private_records"] = refs;
    }

    /// Lays out the store under `root` as store.py does; returns the manifest bytes.
    std::string Store(const fs::path& root, const fs::path& registry) const {
        if (write_registry) WriteFile(registry, registry_text.empty() ? pins.registry_bytes : registry_text);
        WriteFile(root / "store.json", json::WriteCanonical(json::Object{{"schema", "uzpainter/parity/store/1"}, {"hash", "sha256"}}));
        const auto blob = [&](const std::string& bytes) {
            const std::string sha = core::Sha256Hex(bytes);
            const auto replaced = stored_bytes.find(sha);
            WriteFile(root / "blobs" / sha.substr(0, 2) / sha, replaced == stored_bytes.end() ? bytes : replaced->second);
        };
        const auto& painter = std::get<json::Object>(std::get<json::Object>(manifest.at("software").data).at("painter").data);
        const std::string build = std::get<std::string>(painter.at("build_id").data);
        const std::string golden = std::get<std::string>(manifest.at("golden_id").data);
        std::map<std::string, std::string> payloads{{"golden-record", json::WriteCanonical(record)},
                                                    {"oracle-environment", json::WriteCanonical(environment)}};
        for (const auto& [id, bytes] : images) payloads[id] = bytes;
        for (const json::Value& item : std::get<json::Array>(manifest.at("private_records").data)) {
            const auto& ref = std::get<json::Object>(item.data);
            const std::string id = std::get<std::string>(ref.at("record_id").data);
            if (payloads.contains(id)) blob(payloads.at(id));
            if (std::find(missing_entries.begin(), missing_entries.end(), id) != missing_entries.end()) continue;
            json::Object entry{{"schema", "uzpainter/parity/store-entry/1"},
                               {"painter_build_id", build},
                               {"golden_id", golden},
                               {"record_id", id},
                               {"kind", ref.at("kind")},
                               {"sha256", ref.at("sha256")},
                               {"size_bytes", ref.at("size_bytes")},
                               {"file_name", id + ".json"}};
            if (entry_overrides.contains(id)) {
                for (const auto& [field, value] : entry_overrides.at(id)) {
                    if (value.IsNull() && field == "file_name") {
                        entry.erase(field);
                    } else {
                        entry[field] = value;
                    }
                }
            }
            fs::path path = root / "corpora" / build;
            for (std::size_t start = 0;;) {
                const std::size_t slash = golden.find('/', start);
                path /= golden.substr(start, slash == std::string::npos ? std::string::npos : slash - start);
                if (slash == std::string::npos) break;
                start = slash + 1;
            }
            WriteFile(path / (id + ".json"), json::WriteCanonical(entry));
        }
        if (store_plane) blob(plane);
        return manifest_text.empty() ? json::WriteCanonical(manifest) : manifest_text;
    }
};

inline json::Object ManifestRef(const std::string& bytes) {
    return json::Object{{"kind", "filter_manifest"},
                        {"sha256", core::Sha256Hex(bytes)},
                        {"size_bytes", static_cast<std::int64_t>(bytes.size())}};
}

/// Lays `capture` out under `root` (store) and `registry` (registry locator), then admits it
/// through the real C1 admission under the capture's authored pins. `edit_ref` may change the
/// manifest reference before admission.
inline std::expected<procedural::AdmittedFilterCapture, procedural::ImportRefusal> AdmitAuthored(
    const Capture& capture, const fs::path& root, const fs::path& registry,
    const std::function<void(json::Object&)>& edit_ref = {}) {
    const std::string bytes = capture.Store(root, registry);
    json::Object ref = ManifestRef(bytes);
    if (edit_ref) edit_ref(ref);
    const auto store = procedural::OracleStoreReader::Open(root, registry);
    Require(store.has_value(), "open the authored store");
    return procedural::FilterGateTestAccess::Admit(bytes, ref, *store, capture.pins);
}

}  // namespace uzp::filter_gate_test
