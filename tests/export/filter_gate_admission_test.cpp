// Slice C1 of the native F gate (`docs/filter-observations-v2.md` section 11, F1-F4): admission
// and envelope on authored evidence. The oracle store, manifest, record, environment, images and
// envelope pins are authored here under the fixture's work folder, never a real store or capture;
// authored pins reach admission through the test-only access of `filter_gate_test_support.h`,
// which no production source defines.

#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <algorithm>
#include <functional>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

#include "procedural/filter_gate_admission.h"
#include "procedural/filter_gate_pins.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/sha256.h"
#include "filter_gate_test_support.h"

namespace {

// `fs`, `json` and `fx` come from the shared fixture's namespace.
namespace gate = uzp::procedural::filter_gate;
using namespace uzp;
using namespace uzp::filter_gate_test;
using procedural::FilterGateTestAccess;

void Expect(bool okay, const std::string& message) { Require(okay, message); }

/// Makes `link` a directory junction to `target` with `mklink /J`, which needs no privilege; both
/// lie inside the test's work folder.
void Junction(const fs::path& link, const fs::path& target) {
    const std::wstring command = L"cmd /c mklink /J \"" + link.wstring() + L"\" \"" + target.wstring() + L"\" >nul";
    Expect(_wsystem(command.c_str()) == 0 && fs::is_directory(link), "create an authored junction");
}

}  // namespace

int RunFilterGateAdmissionCases(const fs::path& work) {
    int checks = 0;
    const auto check = [&](bool okay, const std::string& message) {
        Expect(okay, message);
        ++checks;
    };
    int cases = 0;
    const auto run = [&](Capture capture, const std::function<void(json::Object&)>& editRef = {})
        -> std::expected<procedural::AdmittedFilterCapture, procedural::ImportRefusal> {
        const fs::path root = work / ("store-" + std::to_string(++cases));
        const fs::path registry = work / ("registry-" + std::to_string(cases) + ".json");
        const std::string bytes = capture.Store(root, registry);
        json::Object ref = ManifestRef(bytes);
        if (editRef) editRef(ref);
        const auto store = procedural::OracleStoreReader::Open(root, registry);
        Expect(store.has_value(), "open the authored store");
        return FilterGateTestAccess::Admit(bytes, ref, *store, capture.pins);
    };
    const auto refuses = [&](const std::string& label, std::string_view code, Capture capture,
                             const std::function<void(json::Object&)>& editRef = {}) {
        const auto result = run(std::move(capture), editRef);
        check(!result && result.error().reason == procedural::kFilterCaptureInvalid && result.error().detail == code,
              label + " refuses " + std::string(code) +
                  (result ? std::string(" (admitted)") : " (got " + result.error().reason + "/" + result.error().detail + ")"));
    };
    const auto base = [] {
        Capture capture;
        capture.Reference();
        return capture;
    };

    // The compiled pins: the approved envelope, the producer, recipe A and the plane.
    const auto compiled = procedural::CompiledFilterGatePins();
    check(compiled && compiled->envelope_id == "painter-12.2.0+js-api.1.1.20-env-a981b586eae7" &&
              compiled->painter_build == "12.2.0+js-api.1.1.20" &&
              compiled->settings_producer == "uzp-recorder/1+src.89f3bbffae21361e" &&
              compiled->plane_sha256 == core::Sha256Hex(fx::PlaneObj()) && core::IsSha256Hex(compiled->envelope_sha256),
          "the compiled pins name the approved envelope, the settings producer and the plane");
    check(core::IsSha256Hex(procedural::FilterGateCodeSha256()), "the gate code hash is a SHA-256");

    // The store: missing, without a marker, another schema, or inside a checkout refuses.
    const auto unavailable = [&](const fs::path& root, const std::string& label) {
        const auto store = procedural::OracleStoreReader::Open(root, work / "registry-unused.json");
        check(!store && store.error().detail == gate::kStoreUnavailable, label);
    };
    unavailable(work / "absent-store", "a missing store refuses");
    fs::create_directories(work / "no-marker");
    unavailable(work / "no-marker", "a folder without store.json refuses");
    WriteFile(work / "other-schema" / "store.json", R"({"hash":"sha256","schema":"uzpainter/parity/store/2"})");
    unavailable(work / "other-schema", "another store schema refuses");
    WriteFile(work / "marker-extra" / "store.json", R"({"hash":"sha256","schema":"uzpainter/parity/store/1","x":1})");
    unavailable(work / "marker-extra", "a store marker with another field refuses");
    WriteFile(work / "marker-hash" / "store.json", R"({"hash":"md5","schema":"uzpainter/parity/store/1"})");
    unavailable(work / "marker-hash", "a store marker with another hash refuses");
    WriteFile(work / "store-file", "authored");
    unavailable(work / "store-file", "a store that is a file refuses");
    WriteFile(work / "checkout" / "build.zig", "authored");
    fs::create_directories(work / "checkout" / ".git");
    WriteFile(work / "checkout" / "store" / "store.json", R"({"hash":"sha256","schema":"uzpainter/parity/store/1"})");
    unavailable(work / "checkout" / "store", "a store inside a checkout refuses");

    // Reparse points: the root, an ancestor or a folder inside the store refuses, wherever it points.
    {
        const Capture capture = base();
        capture.Store(work / "junction-real", work / "junction-registry.json");
        Junction(work / "junction-root", work / "junction-real");
        const auto store = procedural::OracleStoreReader::Open(work / "junction-root", work / "junction-registry.json");
        check(!store && store.error().detail == gate::kStoreUnavailable, "a store root that is a junction refuses");
    }
    {
        const Capture capture = base();
        capture.Store(work / "ancestor-real" / "store", work / "ancestor-registry.json");
        Junction(work / "ancestor-link", work / "ancestor-real");
        const auto store =
            procedural::OracleStoreReader::Open(work / "ancestor-link" / "store", work / "ancestor-registry.json");
        check(!store && store.error().detail == gate::kStoreUnavailable, "a store under a junction refuses");
    }
    const auto junctioned = [&](const std::string& label, std::string_view code,
                                const std::function<void(const fs::path& root)>& relink) {
        const Capture capture = base();
        const fs::path root = work / ("store-" + std::to_string(++cases));
        const fs::path registry = work / ("registry-" + std::to_string(cases) + ".json");
        const std::string bytes = capture.Store(root, registry);
        relink(root);
        const auto store = procedural::OracleStoreReader::Open(root, registry);
        Expect(store.has_value(), "open the authored store before its inner junction is read");
        const auto result = FilterGateTestAccess::Admit(bytes, ManifestRef(bytes), *store, capture.pins);
        check(!result && result.error().detail == code, label);
    };
    junctioned("store entries behind a junction to outside the store refuse", gate::kReceipt, [&](const fs::path& root) {
        const fs::path outside = work / ("outside-corpora-" + std::to_string(cases));
        fs::rename(root / "corpora", outside);
        Junction(root / "corpora", outside);
    });
    junctioned("store entries behind a junction to inside the store refuse", gate::kReceipt, [&](const fs::path& root) {
        fs::rename(root / "corpora", root / "corpora-real");
        Junction(root / "corpora", root / "corpora-real");
    });
    junctioned("a blob folder behind a junction refuses", gate::kReceipt, [&](const fs::path& root) {
        const std::string sha = core::Sha256Hex(json::WriteCanonical(base().record));
        const fs::path outside = work / ("outside-blobs-" + std::to_string(cases));
        fs::rename(root / "blobs" / sha.substr(0, 2), outside);
        Junction(root / "blobs" / sha.substr(0, 2), outside);
    });

    // The authored capture is admitted, with its references in the fixed order.
    {
        const auto admitted = run(base());
        check(admitted.has_value(), "the authored capture is admitted" +
                                        (admitted ? std::string() : " (" + admitted.error().detail + ")"));
        if (admitted) {
            const auto& refs = admitted->Refs();
            check(refs.size() == 12 && refs[0].record_id == "golden-record" && refs[1].record_id == "oracle-environment" &&
                      refs[2].record_id == "r1-settings-after-create-configuration-image" &&
                      refs[11].record_id == "r2-settings-pre16-r2-physical-size-image",
                  "the references are in the fixed order");
            const std::string* image = admitted->Image("r2-settings-after-reopen-configuration-image");
            check(image && *image == "authored png r2-settings-after-reopen-configuration-image" &&
                      admitted->Image("golden-record") == nullptr,
                  "the images are kept by record id, and only the images");
            check(admitted->PlaneBytes() == fx::PlaneObj(), "the plane bytes are the pinned blob");
            const json::Object identity = admitted->Identity();
            check(identity.size() == 7 && identity.at("envelope_id") == json::Value(compiled->envelope_id) &&
                      identity.at("producer") == json::Value(compiled->settings_producer),
                  "the identity carries hashes, the envelope and the producer only");
        }
    }
    {
        Capture capture = base();
        const std::string hash = capture.pins.envelope_sha256;
        capture.pins.envelope_sha256 = core::Sha256Hex("another envelope");
        capture.pins.equivalent_envelopes = {hash};
        capture.Register();
        check(run(std::move(capture)).has_value(), "an equivalent envelope of the approved entry is admitted");
    }

    // The registry: unreadable, other bytes than the reviewed ones, or another current entry.
    {
        Capture capture = base();
        capture.write_registry = false;
        refuses("a registry missing at its locator", gate::kRegistryUnavailable, std::move(capture));
    }
    {
        Capture capture = base();
        capture.registry_text = capture.pins.registry_bytes + "\n";
        refuses("registry bytes other than the reviewed ones", gate::kRegistryDrift, std::move(capture));
    }
    {
        Capture capture = base();
        capture.Register("authored-other-envelope");
        refuses("another current envelope", gate::kRegistryDrift, std::move(capture));
    }

    // F1: the manifest reference, bytes and invariants.
    refuses("a wrong manifest hash", gate::kManifest, base(), [](json::Object& ref) { ref["sha256"] = core::Sha256Hex("x"); });
    refuses("a wrong manifest size", gate::kManifest, base(), [](json::Object& ref) { ref["size_bytes"] = std::int64_t{1}; });
    refuses("another manifest kind", gate::kManifest, base(), [](json::Object& ref) { ref["kind"] = "filter_record"; });
    refuses("an extra manifest reference field", gate::kManifest, base(), [](json::Object& ref) { ref["path"] = "x"; });
    {
        Capture capture = base();
        capture.manifest_text = "{not json";
        refuses("manifest bytes that are not JSON", gate::kManifest, std::move(capture));
    }
    {
        Capture capture = base();
        capture.manifest_text = json::WriteCanonical(capture.manifest);
        capture.manifest_text.insert(1, R"("tier":"0",)");
        refuses("a duplicate manifest key", gate::kManifest, std::move(capture));
    }
    {
        Capture capture = base();
        capture.manifest["description"] = "another description";
        refuses("a changed manifest invariant", gate::kManifest, std::move(capture));
    }
    {
        Capture capture = base();
        Obj(Obj(capture.manifest, "software"), "painter")["channel"] = "authored";
        refuses("an extra software.painter field", gate::kManifest, std::move(capture));
    }
    {
        Capture capture = base();
        Obj(Arr(capture.manifest, "private_records")[3])["note"] = "authored";
        refuses("an extra reference field", gate::kManifest, std::move(capture));
    }
    {
        Capture capture = base();
        capture.pins.recipe_sha256 = core::Sha256Hex("another recipe");
        refuses("a recipe other than the pinned one", gate::kRecipe, std::move(capture));
    }

    // F1: exactly the twelve fixed references.
    {
        Capture capture = base();
        Arr(capture.manifest, "private_records").pop_back();
        refuses("eleven references", gate::kReferences, std::move(capture));
    }
    {
        Capture capture = base();
        Obj(Arr(capture.manifest, "private_records")[4])["kind"] = "api_readback";
        refuses("an image reference of another kind", gate::kReferences, std::move(capture));
    }
    {
        Capture capture = base();
        auto& refs = Arr(capture.manifest, "private_records");
        refs[5] = refs[4];
        refuses("a duplicate reference", gate::kReferences, std::move(capture));
    }
    {
        Capture capture = base();
        Obj(Arr(capture.manifest, "private_records")[6])["record_id"] = "r1-settings-unknown-image";
        refuses("an unknown reference id", gate::kReferences, std::move(capture));
    }

    // F2-F4: admission joins and admitted bytes.
    {
        Capture capture = base();
        capture.missing_entries = {"r2-settings-pre16-r2-physical-size-image"};
        refuses("a reference without a store entry", gate::kReceipt, std::move(capture));
    }
    for (const auto& [field, value] : std::vector<std::pair<std::string, json::Value>>{
             {"kind", json::Value("api_readback")},
             {"sha256", json::Value(core::Sha256Hex("other"))},
             {"size_bytes", json::Value(std::int64_t{2})},
             {"golden_id", json::Value("tier0/api-probes/other")},
             {"painter_build_id", json::Value("12.2.1+js-api.1.1.20")},
             {"extra", json::Value("authored")},
             {"file_name", json::Value()}}) {
        Capture capture = base();
        capture.entry_overrides["oracle-environment"] = json::Object{{field, value}};
        refuses("a store entry with a different " + field, gate::kReceipt, std::move(capture));
    }
    {
        Capture capture = base();
        capture.stored_bytes[core::Sha256Hex(json::WriteCanonical(capture.record))] = "authored corruption";
        refuses("a record blob that fails its hash", gate::kReceipt, std::move(capture));
    }
    const auto receipt = [&](const std::string& label, const std::function<void(Capture&)>& change) {
        Capture capture;
        change(capture);
        capture.Reference();
        refuses(label, gate::kReceipt, std::move(capture));
    };
    receipt("an extra record field", [](Capture& c) { c.record["extra"] = "authored"; });
    receipt("a record without its environment", [](Capture& c) { c.record.erase("environment"); });
    receipt("a record environment that differs from the blob", [](Capture& c) { Obj(c.record, "environment")["os_build"] = "1.0.0.0"; });
    receipt("an extra environment field", [](Capture& c) {
        c.environment["extra"] = "authored";
        c.record["environment"] = c.environment;
    });
    receipt("a backfilled environment", [](Capture& c) {
        c.environment["basis"] = "backfilled";
        c.record["environment"] = c.environment;
    });
    receipt("an unknown envelope field", [](Capture& c) {
        c.environment["gpu_model"] = "unknown";
        c.record["environment"] = c.environment;
        c.pins.envelope_sha256 = core::Sha256Hex(json::WriteCanonical(Capture::EnvelopeFields(c.environment)));
        c.Register();
    });
    receipt("an environment outside the approved envelope", [](Capture& c) {
        c.environment["driver_version"] = "another driver";
        c.record["environment"] = c.environment;
    });
    receipt("a colour configuration other than Legacy", [](Capture& c) {
        c.environment["colour_configuration_sha256"] = core::Sha256Hex("ocio");
        c.record["environment"] = c.environment;
        c.pins.envelope_sha256 = core::Sha256Hex(json::WriteCanonical(Capture::EnvelopeFields(c.environment)));
        c.Register();
    });
    {
        Capture capture;
        capture.environment["recorder_version"] = "uzp-recorder/1+src.0000000000000000";
        capture.record["environment"] = capture.environment;
        capture.Reference();
        refuses("another producer", gate::kProducer, std::move(capture));
    }
    receipt("another record golden", [](Capture& c) { c.record["golden_id"] = "tier0/api-probes/other"; });
    receipt("another tier", [](Capture& c) { c.record["tier"] = "1"; });
    receipt("a Painter build other than the envelope's", [](Capture& c) {
        auto& painter = Obj(Obj(c.manifest, "software"), "painter");
        painter["build_id"] = "12.2.1+js-api.1.1.20";
        painter["version"] = "12.2.1";
        Obj(c.record, "key")["painter_build"] = painter;
    });
    receipt("a version that is not the build's prefix", [](Capture& c) {
        Obj(Obj(c.manifest, "software"), "painter")["version"] = "12.2.1";
        Obj(Obj(c.record, "key"), "painter_build")["version"] = "12.2.1";
    });
    receipt("other input pins", [](Capture& c) { Arr(Obj(c.record, "key"), "inputs").clear(); });
    receipt("other create settings", [](Capture& c) { Obj(Obj(Obj(c.record, "key"), "project_settings"), "create").erase("normal_map_format"); });
    receipt("defaults without the Legacy selection", [](Capture& c) { Obj(Obj(c.record, "key"), "effective_defaults").clear(); });
    receipt("a resource hash", [](Capture& c) {
        Arr(Obj(c.record, "key"), "resource_hashes").push_back(json::Object{{"resource", "authored"}, {"sha256", core::Sha256Hex("r")}});
    });
    receipt("a bake backend", [](Capture& c) { Obj(c.record, "key")["bake_backend"] = "cpu"; });
    receipt("a render state", [](Capture& c) { Obj(c.record, "key")["render_state"] = json::Object{}; });
    receipt("swapped recording conditions", [](Capture& c) {
        auto& recordings = Arr(c.record, "recordings");
        std::swap(Obj(recordings[0])["condition"], Obj(recordings[1])["condition"]);
    });
    receipt("two sessions", [](Capture& c) { Obj(Arr(c.record, "recordings")[1])["session_id"] = "another-session"; });
    receipt("a third recording", [](Capture& c) {
        auto& recordings = Arr(c.record, "recordings");
        recordings.push_back(recordings[1]);
    });
    {
        Capture capture = base();
        capture.store_plane = false;
        refuses("a plane missing from the store", gate::kReceipt, std::move(capture));
    }
    {
        Capture capture = base();
        const std::string id = "r1-settings-pre16-r1-physical-size-image";
        capture.stored_bytes[core::Sha256Hex(capture.images.at(id))] = "authored corruption";
        refuses("an image blob that fails its hash", gate::kImageBytes, std::move(capture));
    }

    // Private seams (test-only access, empty otherwise): the read order and the final registry read.
    const auto admitWith = [&](const Capture& capture, const std::function<void(json::Object&)>& editRef,
                               const std::function<void(procedural::OracleStoreReader&, const fs::path&)>& seam) {
        const fs::path root = work / ("store-" + std::to_string(++cases));
        const fs::path registry = work / ("registry-" + std::to_string(cases) + ".json");
        const std::string bytes = capture.Store(root, registry);
        json::Object ref = ManifestRef(bytes);
        if (editRef) editRef(ref);
        auto store = procedural::OracleStoreReader::Open(root, registry);
        Expect(store.has_value(), "open the authored store");
        seam(*store, registry);
        return FilterGateTestAccess::Admit(bytes, ref, *store, capture.pins);
    };
    const auto detail = [](const auto& result) { return result ? std::string("admitted") : result.error().detail; };
    {
        std::vector<std::string> reads;
        const auto result = admitWith(base(), {}, [&](procedural::OracleStoreReader& store, const fs::path&) {
            FilterGateTestAccess::Observe(store, [&](std::string_view what) { reads.emplace_back(what); });
        });
        const auto firstBlob = std::find(reads.begin(), reads.end(), "blob");
        const auto entries = std::count(reads.begin(), reads.end(), "entry");
        const auto lastEntry = std::find(reads.rbegin(), reads.rend(), "entry").base();
        check(result && entries == 12 && firstBlob != reads.end() && lastEntry <= firstBlob && reads.front() == "registry" &&
                  reads.back() == "registry" && std::count(reads.begin(), reads.end(), "registry") == 2,
              "all twelve entries are admitted before the first blob, between two registry reads (" + detail(result) + ")");
    }
    {
        Capture capture = base();
        capture.missing_entries = {"r2-settings-pre16-r2-physical-size-image"};
        std::vector<std::string> reads;
        const auto result = admitWith(capture, {}, [&](procedural::OracleStoreReader& store, const fs::path&) {
            FilterGateTestAccess::Observe(store, [&](std::string_view what) { reads.emplace_back(what); });
        });
        check(!result && result.error().detail == gate::kReceipt && std::count(reads.begin(), reads.end(), "blob") == 0 &&
                  std::count(reads.begin(), reads.end(), "entry") == 12,
              "a missing last entry refuses before any blob is read (" + detail(result) + ")");
    }
    const auto drift = [&](const std::string& label, const Capture& capture, const std::function<void(json::Object&)>& editRef,
                           const std::function<void(const fs::path&)>& change, const std::string& expected) {
        const auto result = admitWith(capture, editRef, [&](procedural::OracleStoreReader& store, const fs::path& registry) {
            FilterGateTestAccess::BeforeFinalRegistryRead(store, [&change, registry] { change(registry); });
        });
        check(!result && result.error().reason == procedural::kFilterCaptureInvalid && result.error().detail == expected,
              label + " gives " + expected + " (" + detail(result) + ")");
    };
    const auto appendByte = [](const fs::path& registry) {
        std::ofstream file(registry, std::ios::binary | std::ios::app);
        file << "\n";
    };
    drift("a registry changed after a successful admission", base(), {}, appendByte, std::string(gate::kRegistryDrift));
    drift("a registry deleted after a refusal", base(), [](json::Object& ref) { ref["kind"] = "filter_record"; },
          [](const fs::path& registry) { fs::remove(registry); },
          std::string(gate::kRegistryDrift) + ":" + std::string(gate::kManifest));
    {
        Capture capture = base();
        capture.store_plane = false;
        Capture other = base();
        other.Register("authored-other-envelope");
        const std::string moved = other.pins.registry_bytes;
        drift("another current envelope after a refusal", capture, {},
              [moved](const fs::path& registry) { WriteFile(registry, moved); },
              std::string(gate::kRegistryDrift) + ":" + std::string(gate::kReceipt));
    }
    {
        const Capture capture = base();
        const std::string same = capture.pins.registry_bytes;
        const auto result = admitWith(capture, {}, [&](procedural::OracleStoreReader& store, const fs::path& registry) {
            FilterGateTestAccess::BeforeFinalRegistryRead(store, [same, registry] { WriteFile(registry, same); });
        });
        check(result.has_value(), "the same registry bytes rewritten are not a drift (" + detail(result) + ")");
    }

    // Typed values: booleans and doubles are never sizes, an integer never equals a double.
    refuses("a manifest size that is a double", gate::kManifest, base(), [](json::Object& ref) {
        ref["size_bytes"] = static_cast<double>(std::get<std::int64_t>(ref.at("size_bytes").data));
    });
    refuses("a manifest size that is a boolean", gate::kManifest, base(), [](json::Object& ref) { ref["size_bytes"] = true; });
    for (const json::Value& size : {json::Value(static_cast<double>(1)), json::Value(true)}) {
        Capture capture = base();
        auto& ref = Obj(Arr(capture.manifest, "private_records")[2]);
        ref["size_bytes"] = size.IsBool() ? size : json::Value(static_cast<double>(std::get<std::int64_t>(ref.at("size_bytes").data)));
        refuses(std::string("a reference size that is a ") + (size.IsBool() ? "boolean" : "double"), gate::kManifest,
                std::move(capture));
    }
    for (const bool boolean : {false, true}) {
        Capture capture = base();
        const auto& ref = std::get<json::Object>(Arr(capture.manifest, "private_records")[1].data);
        const auto size = std::get<std::int64_t>(ref.at("size_bytes").data);
        capture.entry_overrides["oracle-environment"] =
            json::Object{{"size_bytes", boolean ? json::Value(true) : json::Value(static_cast<double>(size))}};
        refuses(std::string("a store entry size that is a ") + (boolean ? "boolean" : "double"), gate::kReceipt,
                std::move(capture));
    }
    receipt("an environment field that is not a string", [](Capture& c) {
        c.environment["gpu_model"] = std::int64_t{1};
        c.record["environment"] = c.environment;
    });
    {
        Capture capture = base();
        auto& steps = Arr(Obj(capture.manifest, "instruction_sequence"), "steps");
        Obj(Obj(steps[11]), "args")["toggle"] = 0.0;
        refuses("a recipe integer written as a double", gate::kManifest, std::move(capture));
    }
    {
        Capture capture = base();
        auto& steps = Arr(Obj(capture.manifest, "instruction_sequence"), "steps");
        Obj(Obj(steps[0]), "args")["default_texture_resolution"] = 128.0;
        refuses("a create resolution written as a double", gate::kManifest, std::move(capture));
    }
    receipt("a recorded create resolution that is a double", [](Capture& c) {
        Obj(Obj(Obj(c.record, "key"), "project_settings"), "create")["default_texture_resolution"] = 128.0;
    });
    const auto doubleZero = [](double manifestToggle) {
        Capture capture;
        json::Value request = json::Parse(capture.pins.request_bytes);
        Obj(Obj(Arr(Obj(Obj(request), "instruction_sequence"), "steps")[11]), "args")["toggle"] = 0.0;
        capture.pins.request_bytes = json::WriteCanonical(request);
        capture.pins.recipe_sha256 = core::Sha256Hex(json::WriteCanonical(Obj(request).at("instruction_sequence")));
        capture.manifest = Obj(request);
        Obj(Obj(Arr(Obj(capture.manifest, "instruction_sequence"), "steps")[11]), "args")["toggle"] = manifestToggle;
        Obj(capture.record, "key")["instruction_sequence_sha256"] = capture.pins.recipe_sha256;
        capture.Reference();
        return capture;
    };
    {
        const auto result = run(doubleZero(0.0));
        check(result.has_value(), "a double zero pinned and recorded alike is admitted (" + detail(result) + ")");
    }
    refuses("a negative zero against a pinned positive zero", gate::kManifest, doubleZero(-0.0));

    std::cout << "FILTER_GATE_ADMISSION: " << json::WriteCanonical(json::Object{{"checks", checks}}) << "\n";
    return 0;
}
