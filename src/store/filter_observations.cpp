#include "store/filter_observations.h"

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <initializer_list>
#include <map>
#include <set>
#include <string>

#include "store/container.h"
#include "store/observation_inventory.h"
#include "store/snapshots.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/recipe.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/resource_url.h"
#include "uzp_core/types/validation.h"

namespace uzp::store {

using core::json::Array;
using core::json::Object;
using core::json::Value;

namespace {

/// The first structural problem found, with its JSON path.
struct Problem {
    std::string text;
};

[[noreturn]] void Fail(const std::string& path, const std::string& what) { throw Problem{path + ": " + what}; }

/// `value` as an object of exactly `members`.
const Object& Closed(const Value& value, const std::string& path, std::initializer_list<std::string_view> members) {
    const Object* object = std::get_if<Object>(&value.data);
    if (object == nullptr) Fail(path, "expected an object");
    for (const auto& [name, _] : *object) {
        if (std::find(members.begin(), members.end(), name) == members.end()) {
            Fail(path, "unknown member '" + name + "'");
        }
    }
    for (const std::string_view name : members) {
        if (!object->contains(name)) Fail(path, "missing member '" + std::string(name) + "'");
    }
    return *object;
}

const Value& Member(const Object& object, std::string_view name) { return object.find(name)->second; }

const std::string& Text(const Object& object, std::string_view name, const std::string& path) {
    const std::string* text = std::get_if<std::string>(&Member(object, name).data);
    if (text == nullptr || text->empty()) Fail(path + "." + std::string(name), "expected a nonempty string");
    return *text;
}

std::int64_t Integer(const Object& object, std::string_view name, const std::string& path, std::int64_t minimum) {
    const std::int64_t* value = std::get_if<std::int64_t>(&Member(object, name).data);
    if (value == nullptr || *value < minimum) {
        Fail(path + "." + std::string(name), "expected an integer of at least " + std::to_string(minimum));
    }
    return *value;
}

const Object& Map(const Object& object, std::string_view name, const std::string& path) {
    const Object* map = std::get_if<Object>(&Member(object, name).data);
    if (map == nullptr) Fail(path + "." + std::string(name), "expected an object");
    return *map;
}

bool Sha256Text(std::string_view text) {
    return text.size() == 64 &&
           std::all_of(text.begin(), text.end(), [](char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); });
}

const std::string& Sha256(const Object& object, std::string_view name, const std::string& path) {
    const std::string& text = Text(object, name, path);
    if (!Sha256Text(text)) Fail(path + "." + std::string(name), "expected a lowercase SHA-256");
    return text;
}

/// A node UID key: a positive decimal integer without leading zeros.
std::int64_t UidKey(const std::string& key, const std::string& path) {
    std::int64_t uid = 0;
    const auto [end, error] = std::from_chars(key.data(), key.data() + key.size(), uid);
    if (key.empty() || key.front() == '0' || error != std::errc{} || end != key.data() + key.size() || uid < 1) {
        Fail(path, "the key '" + key + "' is not a node UID");
    }
    return uid;
}

void ChannelName(const std::string& name, const std::string& path) {
    if (!core::FromString<core::ChannelType>(name)) Fail(path, "'" + name + "' is not a channel type");
}

/// Decision 361's codec: an object of int64, finite double or string values.
void Parameters(const Value& value, const std::string& path) {
    const Object* map = std::get_if<Object>(&value.data);
    if (map == nullptr) Fail(path, "expected an object");
    for (const auto& [name, parameter] : *map) {
        const double* number = std::get_if<double>(&parameter.data);
        if (!(parameter.IsInt() || parameter.IsString() || (number != nullptr && std::isfinite(*number)))) {
            Fail(path + "." + name, "expected an int64, finite double or string");
        }
    }
}

/// Exactly the four nonempty strings of an observed ResourceID, none reconstructed.
void ResourceId(const Value& value, const std::string& path) {
    const Object& id = Closed(value, path, {"url", "context", "name", "version"});
    for (const char* part : {"url", "context", "name", "version"}) Text(id, part, path);
}

/// An array of distinct nonempty strings, in its own order; empty is allowed.
void DistinctStrings(const Value& value, const std::string& path) {
    const Array* array = std::get_if<Array>(&value.data);
    if (array == nullptr) Fail(path, "expected an array");
    std::set<std::string> seen;
    for (const Value& item : *array) {
        const std::string* text = std::get_if<std::string>(&item.data);
        if (text == nullptr || text->empty() || !seen.insert(*text).second) {
            Fail(path, "expected distinct nonempty strings");
        }
    }
}

/// Typed equality: the same canonical JSON, so int versus double and the sign of zero count
/// (json::Value's own `==` compares doubles by value).
bool SameTyped(const Value& a, const Value& b) { return core::json::WriteCanonical(a) == core::json::WriteCanonical(b); }

/// A complete reference serialization: exactly what the core manifest writes for the reference it
/// reads (every member, absent optionals as null, unknown keys kept), whose `asset` is the
/// descriptor's pin.
void Reference(const Object& binding, std::string_view name, const std::string& descriptor, const std::string& path) {
    const std::string member = path + "." + std::string(name);
    const Value& stored = Member(binding, name);
    core::ProceduralRef reference;
    try {
        reference = core::ProceduralRefFromJson(stored, member);
    } catch (const core::ManifestError& error) {
        Fail(member, error.what());
    }
    if (reference.asset != ObservationPin(descriptor)) {
        Fail(member + ".asset", "expected the descriptor's pin " + ObservationPin(descriptor));
    }
    if (!SameTyped(core::ProceduralRefToJson(reference), stored)) {
        Fail(member, "is not the complete canonical serialization of its procedural reference");
    }
}

void Context(const Value& value, std::string_view project_uuid, const std::string& path) {
    const Object& context = Closed(value, path, {"schema", "project", "store_uuid", "resources"});
    if (Text(context, "schema", path) != kObservationContextSchema) {
        Fail(path + ".schema", "expected " + std::string(kObservationContextSchema));
    }
    // The stored projection of the project as observed: a complete historical manifest
    // (ProjectToJson minus the namespace), exactly what the core codec writes back for the project
    // it reads, unknown keys kept. Never compared here with the current project.
    const Value& stored = Member(context, "project");
    const Object* project = std::get_if<Object>(&stored.data);
    if (project == nullptr) Fail(path + ".project", "expected an object");
    if (project->contains(kFilterObservationsKey)) {
        Fail(path + ".project", "the projection holds the observation namespace it must exclude");
    }
    try {
        if (!SameTyped(core::ProjectToJson(core::ProjectFromJson(stored)), stored)) {
            Fail(path + ".project", "is not the canonical manifest of the project it describes");
        }
    } catch (const core::ManifestError& error) {
        Fail(path + ".project", error.what());
    }
    if (Text(context, "store_uuid", path) != project_uuid) {
        Fail(path + ".store_uuid", "names another project than " + std::string(project_uuid));
    }
    const Array* resources = std::get_if<Array>(&Member(context, "resources").data);
    if (resources == nullptr || resources->size() != 1) {
        Fail(path + ".resources", "expected exactly one record, the mesh (V1)");
    }
    const std::string record = path + ".resources[0]";
    const Object& mesh =
        Closed(resources->front(), record, {"binding_path", "kind", "identity", "mime", "sha256", "size_bytes"});
    if (Text(mesh, "binding_path", record) != "/mesh/resource") Fail(record + ".binding_path", "expected /mesh/resource");
    if (Text(mesh, "kind", record) != "mesh") Fail(record + ".kind", "expected mesh");
    const std::string& identity = Sha256(mesh, "identity", record);
    if (Sha256(mesh, "sha256", record) != identity) Fail(record + ".sha256", "expected the identity's SHA-256");
    // Self-consistency of the stored context: the census names the stored projection's own mesh
    // resource (never the current project's).
    const auto projectMesh = project->find("mesh");
    const Object* meshObject = projectMesh == project->end() ? nullptr : std::get_if<Object>(&projectMesh->second.data);
    const auto resource = meshObject == nullptr ? Object::const_iterator{} : meshObject->find("resource");
    if (meshObject == nullptr || resource == meshObject->end() || resource->second != Value(identity)) {
        Fail(record + ".identity", "is not the stored projection's mesh.resource");
    }
    Text(mesh, "mime", record);
    Integer(mesh, "size_bytes", record, 0);
}

void Capture(const Value& value, const std::string& path) {
    const Object& capture = Closed(value, path,
                                   {"recorder", "envelope_id", "painter_build_id", "recipe_sha256", "resource_query",
                                    "authored_inputs", "receipts"});
    for (const char* name : {"recorder", "envelope_id", "painter_build_id", "resource_query"}) Text(capture, name, path);
    Sha256(capture, "recipe_sha256", path);
    const Array* inputs = std::get_if<Array>(&Member(capture, "authored_inputs").data);
    if (inputs == nullptr) Fail(path + ".authored_inputs", "expected an array");
    std::set<std::string> ids;
    for (size_t i = 0; i < inputs->size(); ++i) {
        const std::string item = path + ".authored_inputs[" + std::to_string(i) + "]";
        const Object& input = Closed((*inputs)[i], item, {"input_id", "sha256"});
        if (!ids.insert(Text(input, "input_id", item)).second) Fail(item, "the input_id repeats");
        Sha256(input, "sha256", item);
    }
    const Array* receipts = std::get_if<Array>(&Member(capture, "receipts").data);
    if (receipts == nullptr || receipts->size() != 2) Fail(path + ".receipts", "expected exactly two receipts");
    std::set<std::string> conditions;
    for (size_t i = 0; i < receipts->size(); ++i) {
        const std::string item = path + ".receipts[" + std::to_string(i) + "]";
        const Object& receipt = Closed((*receipts)[i], item, {"condition", "sha256"});
        conditions.insert(Text(receipt, "condition", item));
        Sha256(receipt, "sha256", item);
    }
    if (conditions != std::set<std::string>{"after_save_reopen", "same_session"}) {
        Fail(path + ".receipts", "expected the paired conditions same_session and after_save_reopen");
    }
}

void Observations(const Value& value, const Object& filter, const std::string& path) {
    const Object* observations = std::get_if<Object>(&value.data);
    if (observations == nullptr) Fail(path, "expected an object");
    for (const auto& [name, observed] : *observations) {
        const std::string member = path + "." + name;
        if (name == "parameters") {
            Parameters(observed, member);
            if (!SameTyped(observed, Member(filter, "parameters"))) {
                Fail(member, "differs from the Filter descriptor's parameters");
            }
        } else if (name == "resource_id") {
            ResourceId(observed, member);
            if (!SameTyped(observed, Member(filter, "resource_id"))) {
                Fail(member, "differs from the Filter descriptor's resource_id");
            }
        } else if (name == "image_outputs") {
            DistinctStrings(observed, member);
        } else {
            Fail(path, "unknown member '" + name + "'");
        }
    }
}

void CheckV1(const Value& value, std::string_view project_uuid) {
    const std::string root(kFilterObservationsKey);
    const Object& space = Closed(value, root, {"schema", "descriptors", "entries", "host_bindings", "bindings"});
    if (Text(space, "schema", root) != kFilterObservationsSchema) {
        Fail(root + ".schema", "expected " + std::string(kFilterObservationsSchema));
    }

    std::map<std::string, const Object*, std::less<>> descriptors;
    for (const auto& [key, body] : Map(space, "descriptors", root)) {
        const std::string path = root + ".descriptors." + key;
        const Object& descriptor = Closed(body, path, {"schema", "role", "resource_id", "parameters"});
        if (Text(descriptor, "schema", path) != kObservationDescriptorSchema) {
            Fail(path + ".schema", "expected " + std::string(kObservationDescriptorSchema));
        }
        const std::string& role = Text(descriptor, "role", path);
        if (role != "host" && role != "filter") Fail(path + ".role", "expected host or filter");
        ResourceId(Member(descriptor, "resource_id"), path + ".resource_id");
        Parameters(Member(descriptor, "parameters"), path + ".parameters");
        if (const std::string hash = ObservationKey(body); hash != key) Fail(path, "the descriptor hashes to " + hash);
        descriptors.emplace(key, &descriptor);
    }
    const auto descriptorOf = [&](const std::string& key, std::string_view role, const std::string& path) {
        const auto it = descriptors.find(key);
        if (it == descriptors.end()) Fail(path, "names no descriptor of the namespace");
        if (Text(*it->second, "role", path) != role) Fail(path, "names a descriptor whose role is not " + std::string(role));
        return it->second;
    };

    std::map<std::string, const Object*, std::less<>> entries;
    std::set<std::string> contexts;
    for (const auto& [key, body] : Map(space, "entries", root)) {
        const std::string path = root + ".entries." + key;
        const Object& entry = Closed(body, path,
                                     {"schema", "project_uuid", "role", "host_descriptor", "filter_descriptor",
                                      "binding", "context", "context_sha256", "capture", "observations"});
        if (Text(entry, "schema", path) != kObservationEntrySchema) {
            Fail(path + ".schema", "expected " + std::string(kObservationEntrySchema));
        }
        if (const std::string& recorded = Text(entry, "project_uuid", path); recorded != project_uuid) {
            Fail(path + ".project_uuid", "the observation was recorded for project " + recorded + ", not for project " +
                                             std::string(project_uuid) + ": observations are project-private");
        }
        if (Text(entry, "role", path) != "filter") Fail(path + ".role", "expected filter");
        const std::string& host = Text(entry, "host_descriptor", path);
        const std::string& filter = Text(entry, "filter_descriptor", path);
        descriptorOf(host, "host", path + ".host_descriptor");
        const Object* filterDescriptor = descriptorOf(filter, "filter", path + ".filter_descriptor");

        const std::string bindingPath = path + ".binding";
        const Object& binding = Closed(Member(entry, "binding"), bindingPath,
                                       {"texture_set", "stack", "host_uid", "filter_uid", "node_stack", "effect_index",
                                        "host_channel", "host_reference", "filter_reference"});
        for (const char* name : {"texture_set", "stack", "host_uid", "filter_uid"}) Integer(binding, name, bindingPath, 1);
        if (Text(binding, "node_stack", bindingPath) != "Content") Fail(bindingPath + ".node_stack", "expected Content");
        Integer(binding, "effect_index", bindingPath, 0);
        ChannelName(Text(binding, "host_channel", bindingPath), bindingPath + ".host_channel");
        Reference(binding, "host_reference", host, bindingPath);
        Reference(binding, "filter_reference", filter, bindingPath);

        Context(Member(entry, "context"), project_uuid, path + ".context");
        const std::string& contextHash = Sha256(entry, "context_sha256", path);
        if (contextHash != ObservationKey(Member(entry, "context"))) {
            Fail(path + ".context_sha256", "is not the context's hash");
        }
        if (!contexts.insert(contextHash).second) {
            Fail(path, "another entry holds the same context: conflicting observations are refused");
        }
        Capture(Member(entry, "capture"), path + ".capture");
        Observations(Member(entry, "observations"), *filterDescriptor, path + ".observations");
        if (const std::string hash = ObservationKey(body); hash != key) Fail(path, "the entry hashes to " + hash);
        entries.emplace(key, &entry);
    }

    std::map<std::int64_t, const Object*> hosts;
    for (const auto& [key, body] : Map(space, "host_bindings", root)) {
        const std::string path = root + ".host_bindings." + key;
        const std::int64_t uid = UidKey(key, path);
        const Object& host = Closed(body, path, {"channel", "descriptor"});
        ChannelName(Text(host, "channel", path), path + ".channel");
        descriptorOf(Text(host, "descriptor", path), "host", path + ".descriptor");
        hosts.emplace(uid, &host);
    }

    // Every entry, bound or historical, names a host binding that agrees with it. An entry need not
    // be bound and its nodes need not be alive.
    for (const auto& [key, entry] : entries) {
        const std::string path = root + ".entries." + key;
        const Object& binding = std::get<Object>(Member(*entry, "binding").data);
        const auto host = hosts.find(std::get<std::int64_t>(Member(binding, "host_uid").data));
        if (host == hosts.end()) Fail(path + ".binding.host_uid", "the entry's host UID has no host binding");
        if (Member(*host->second, "channel") != Member(binding, "host_channel") ||
            Member(*host->second, "descriptor") != Member(*entry, "host_descriptor")) {
            Fail(path, "the host binding disagrees with the entry's host channel or descriptor");
        }
    }

    for (const auto& [key, body] : Map(space, "bindings", root)) {
        const std::string path = root + ".bindings." + key;
        const std::int64_t uid = UidKey(key, path);
        const std::string* entryKey = std::get_if<std::string>(&body.data);
        const auto entry = entryKey == nullptr ? entries.end() : entries.find(*entryKey);
        if (entry == entries.end()) Fail(path, "names no entry of the namespace");
        const Object& binding = std::get<Object>(Member(*entry->second, "binding").data);
        if (std::get<std::int64_t>(Member(binding, "filter_uid").data) != uid) {
            Fail(path, "the entry is bound to another Filter UID");
        }
    }
}

// ── Version 2 (decision 363) ─────────────────────────────────────────────────────────────────

void Literal(const Object& object, std::string_view name, std::string_view expected, const std::string& path) {
    if (Text(object, name, path) != expected) Fail(path + "." + std::string(name), "expected " + std::string(expected));
}

/// An artifact reference `{kind, sha256, size_bytes}` of kind `kind`.
void Artifact(const Value& value, std::string_view kind, const std::string& path) {
    const Object& artifact = Closed(value, path, {"kind", "sha256", "size_bytes"});
    Literal(artifact, "kind", kind, path);
    Sha256(artifact, "sha256", path);
    Integer(artifact, "size_bytes", path, 0);
}

/// An array of exactly `count` artifact references of kind `kind`, in their own order (the same
/// blob may occur twice: repeated identical exports).
void Artifacts(const Value& value, std::string_view kind, size_t count, const std::string& path) {
    const Array* array = std::get_if<Array>(&value.data);
    if (array == nullptr || array->size() != count) Fail(path, "expected exactly " + std::to_string(count) + " references");
    for (size_t i = 0; i < array->size(); ++i) Artifact((*array)[i], kind, path + "[" + std::to_string(i) + "]");
}

bool SnapshotPin(const std::string& asset) {
    try {
        return core::ParseAssetUrl(asset).family == "snapshot";
    } catch (const core::ValueError&) {
        return false;
    }
}

/// The historical project of a V2 context projection: a complete manifest without the namespace,
/// valid, that round-trips to the same canonical text.
core::Project HistoricalProject(const Value& stored, const std::string& path) {
    const Object* project = std::get_if<Object>(&stored.data);
    if (project == nullptr) Fail(path, "expected an object");
    if (project->contains(kFilterObservationsKey)) Fail(path, "the projection holds the observation namespace it must exclude");
    core::Project historical;
    try {
        historical = core::ProjectFromJson(stored);
        core::Validate(historical);
    } catch (const core::ManifestError& error) {
        Fail(path, error.what());
    } catch (const core::ValueError& error) {
        Fail(path, error.what());
    }
    if (!SameTyped(core::ProjectToJson(historical), stored)) Fail(path, "is not the canonical manifest of the project it describes");
    return historical;
}

/// The census plane `plane_id` of a (validated) inventory serialization.
const Object& CensusPlane(const Value& inventory, std::int64_t plane_id, const std::string& path) {
    for (const Value& plane : std::get<Array>(std::get<Object>(inventory.data).at("planes").data)) {
        const Object& object = std::get<Object>(plane.data);
        if (std::get<std::int64_t>(object.at("plane_id").data) == plane_id) return object;
    }
    Fail(path, "the census holds no plane " + std::to_string(plane_id));
}

void Rounds(const Value& value, const std::string& path) {
    const Array* rounds = std::get_if<Array>(&value.data);
    if (rounds == nullptr || rounds->size() != 2) Fail(path, "expected exactly two rounds");
    const char* conditions[] = {"same_session", "after_save_reopen"};
    for (size_t i = 0; i < 2; ++i) {
        const std::string item = path + "[" + std::to_string(i) + "]";
        const Object& round = Closed((*rounds)[i], item,
                                     {"condition", "probe_sequence_sha256", "context_readback_sha256",
                                      "host_readback_sha256", "filter_readback_sha256"});
        Literal(round, "condition", conditions[i], item);
        for (const char* name : {"probe_sequence_sha256", "context_readback_sha256", "host_readback_sha256",
                                 "filter_readback_sha256"}) {
            Sha256(round, name, item);
        }
    }
}

/// The entry's capture /2: the F provenance, the H provenance and the migration with its native
/// proof record, checked against the historical context it belongs to (`host` the selected host
/// snapshot, `plane` its census plane, `context_hash` the entry's context hash).
void CaptureV2(const Value& value, const Object& context, const SnapshotEntry& host, const Object& plane,
               const std::string& context_hash, std::string_view project_uuid, const std::string& path) {
    const Object& capture = Closed(value, path, {"schema", "filter", "host", "migration"});
    Literal(capture, "schema", kObservationCaptureSchemaV2, path);

    const std::string filterPath = path + ".filter";
    const Object& filter = Closed(Member(capture, "filter"), filterPath,
                                  {"provenance", "manifest", "record", "environment", "rounds"});
    Capture(Member(filter, "provenance"), filterPath + ".provenance");
    Artifact(Member(filter, "manifest"), "filter_manifest", filterPath + ".manifest");
    Artifact(Member(filter, "record"), "filter_record", filterPath + ".record");
    Artifact(Member(filter, "environment"), "filter_environment", filterPath + ".environment");
    Rounds(Member(filter, "rounds"), filterPath + ".rounds");

    const std::string hostPath = path + ".host";
    const Object& hostCapture = Closed(Member(capture, "host"), hostPath,
                                       {"protocol", "receipt", "request", "environment", "environment_binding",
                                        "scalar_exports", "rgb_exports"});
    Literal(hostCapture, "protocol", "paired-scalar-rgb", hostPath);
    Artifact(Member(hostCapture, "receipt"), "snapshot_receipt", hostPath + ".receipt");
    Artifact(Member(hostCapture, "request"), "snapshot_request", hostPath + ".request");
    const Value& environment = Member(hostCapture, "environment");
    const Value& environmentBinding = Member(hostCapture, "environment_binding");
    if (environment.IsNull() != environmentBinding.IsNull()) {
        Fail(hostPath, "the environment and its binding must both be present or both be null");
    }
    if (!environment.IsNull()) {
        Artifact(environment, "snapshot_environment", hostPath + ".environment");
        Artifact(environmentBinding, "snapshot_environment_binding", hostPath + ".environment_binding");
    }
    Artifacts(Member(hostCapture, "scalar_exports"), "snapshot_scalar_export", 2, hostPath + ".scalar_exports");
    Artifacts(Member(hostCapture, "rgb_exports"), "snapshot_rgb_export", 2, hostPath + ".rgb_exports");

    const std::string migrationPath = path + ".migration";
    const Object& migration = Closed(Member(capture, "migration"), migrationPath,
                                     {"rule", "raster_stage", "raster_sha256", "capture_context_sha256",
                                      "destination_host_context_sha256", "native_evidence"});
    Literal(migration, "rule", kFrozenHostRule, migrationPath);
    Literal(migration, "raster_stage", "frozen_output", migrationPath);
    const std::string& raster = std::get<std::string>(plane.at("sha256").data);
    if (Sha256(migration, "raster_sha256", migrationPath) != raster) {
        Fail(migrationPath + ".raster_sha256", "is not the host snapshot plane's texel SHA-256");
    }
    Sha256(migration, "capture_context_sha256", migrationPath);
    if (Sha256(migration, "destination_host_context_sha256", migrationPath) != context_hash) {
        Fail(migrationPath + ".destination_host_context_sha256", "is not the entry's context hash");
    }

    // The native proof record: structurally bound to this context, never execution evidence by itself.
    const std::string proofPath = migrationPath + ".native_evidence";
    const Object& proof = Closed(Member(migration, "native_evidence"), proofPath,
                                 {"schema", "rule", "validator_code_sha256", "binary_sha256", "domain_sha256",
                                  "project_uuid", "prospective_projection_sha256", "inventory_sha256",
                                  "signature_sha256", "plane_id", "version_id", "chunk_root", "raster_sha256",
                                  "uploaded_sha256", "final_output_sha256", "sample_count", "nonfinite_count",
                                  "fixed_point_mismatches", "upload_mismatches", "final_output_mismatches"});
    Literal(proof, "schema", kFrozenHostProofSchema, proofPath);
    Literal(proof, "rule", kFrozenHostRule, proofPath);
    Sha256(proof, "validator_code_sha256", proofPath);
    Sha256(proof, "binary_sha256", proofPath);
    if (Sha256(proof, "domain_sha256", proofPath) != ObservationKey(FrozenHostDomain())) {
        Fail(proofPath + ".domain_sha256", "is not the hash of the frozen-host domain record");
    }
    if (Text(proof, "project_uuid", proofPath) != project_uuid) Fail(proofPath + ".project_uuid", "names another project");
    if (Sha256(proof, "prospective_projection_sha256", proofPath) != ObservationKey(Member(context, "project"))) {
        Fail(proofPath + ".prospective_projection_sha256", "is not the hash of the context's projection");
    }
    if (Sha256(proof, "inventory_sha256", proofPath) != ObservationKey(Member(context, "inventory"))) {
        Fail(proofPath + ".inventory_sha256", "is not the hash of the context's inventory");
    }
    if (Sha256(proof, "signature_sha256", proofPath) != host.key) Fail(proofPath + ".signature_sha256", "is not the host snapshot");
    if (Integer(proof, "plane_id", proofPath, 1) != static_cast<std::int64_t>(host.plane_id)) {
        Fail(proofPath + ".plane_id", "is not the host snapshot's plane");
    }
    if (Integer(proof, "version_id", proofPath, 0) != std::get<std::int64_t>(plane.at("version_id").data) ||
        Sha256(proof, "chunk_root", proofPath) != std::get<std::string>(plane.at("chunk_root").data)) {
        Fail(proofPath, "names another version than the host snapshot plane's");
    }
    for (const char* name : {"raster_sha256", "uploaded_sha256", "final_output_sha256"}) {
        if (Sha256(proof, name, proofPath) != raster) Fail(proofPath + "." + name, "is not the host raster's SHA-256");
    }
    const std::int64_t samples = std::get<std::int64_t>(plane.at("width").data) * std::get<std::int64_t>(plane.at("height").data);
    if (Integer(proof, "sample_count", proofPath, 0) != samples) Fail(proofPath + ".sample_count", "is not width x height");
    for (const char* name : {"nonfinite_count", "fixed_point_mismatches", "upload_mismatches", "final_output_mismatches"}) {
        if (Integer(proof, name, proofPath, 0) != 0) Fail(proofPath + "." + name, "expected zero");
    }
}

void CheckV2(const Value& value, std::string_view project_uuid) {
    const std::string root(kFilterObservationsKey);
    const Object& space = Closed(value, root, {"schema", "descriptors", "entries", "bindings"});
    Literal(space, "schema", kFilterObservationsSchemaV2, root);

    std::map<std::string, const Object*, std::less<>> descriptors;
    for (const auto& [key, body] : Map(space, "descriptors", root)) {
        const std::string path = root + ".descriptors." + key;
        const Object& descriptor = Closed(body, path, {"schema", "role", "resource_id", "parameters"});
        Literal(descriptor, "schema", kObservationDescriptorSchema, path);
        Literal(descriptor, "role", "filter", path);
        ResourceId(Member(descriptor, "resource_id"), path + ".resource_id");
        Parameters(Member(descriptor, "parameters"), path + ".parameters");
        if (const std::string hash = ObservationKey(body); hash != key) Fail(path, "the descriptor hashes to " + hash);
        descriptors.emplace(key, &descriptor);
    }

    std::map<std::string, const Object*, std::less<>> entries;
    std::set<std::string> contexts;
    for (const auto& [key, body] : Map(space, "entries", root)) {
        const std::string path = root + ".entries." + key;
        const Object& entry = Closed(body, path,
                                     {"schema", "project_uuid", "role", "host_snapshot", "filter_descriptor", "binding",
                                      "context", "context_sha256", "capture", "observations"});
        Literal(entry, "schema", kObservationEntrySchemaV2, path);
        if (const std::string& recorded = Text(entry, "project_uuid", path); recorded != project_uuid) {
            Fail(path + ".project_uuid", "the observation was recorded for project " + recorded + ", not for project " +
                                             std::string(project_uuid) + ": observations are project-private");
        }
        Literal(entry, "role", "filter", path);
        const std::string& filterKey = Text(entry, "filter_descriptor", path);
        const auto filterDescriptor = descriptors.find(filterKey);
        if (filterDescriptor == descriptors.end()) Fail(path + ".filter_descriptor", "names no descriptor of the namespace");

        // The historical context: projection, store uuid and census of that projection.
        const std::string contextPath = path + ".context";
        const Object& context = Closed(Member(entry, "context"), contextPath, {"schema", "project", "store_uuid", "inventory"});
        Literal(context, "schema", kObservationContextSchemaV2, contextPath);
        const core::Project historical = HistoricalProject(Member(context, "project"), contextPath + ".project");
        if (Text(context, "store_uuid", contextPath) != project_uuid) {
            Fail(contextPath + ".store_uuid", "names another project than " + std::string(project_uuid));
        }
        if (const std::string problem = InventoryHistoryProblem(historical, Member(context, "inventory"), project_uuid);
            !problem.empty()) {
            Fail(contextPath + ".inventory", problem);
        }
        const std::string& contextHash = Sha256(entry, "context_sha256", path);
        if (contextHash != ObservationKey(Member(entry, "context"))) Fail(path + ".context_sha256", "is not the context's hash");
        if (!contexts.insert(contextHash).second) {
            Fail(path, "another entry holds the same context: conflicting observations are refused");
        }
        FrozenHostNodes nodes;
        if (const std::string problem = FrozenHostDomainProblem(historical, nodes); !problem.empty()) {
            Fail(contextPath + ".project", "outside the frozen-host domain: " + problem);
        }

        // The binding names the historical nodes and their complete references.
        const std::string bindingPath = path + ".binding";
        const Object& binding = Closed(Member(entry, "binding"), bindingPath,
                                       {"texture_set", "stack", "host_uid", "filter_uid", "initial_paint_uid", "node_stack",
                                        "effect_index", "host_channel", "host_reference", "filter_reference"});
        const auto names = [&](const char* name, core::Id id) {
            if (Integer(binding, name, bindingPath, 1) != static_cast<std::int64_t>(id)) {
                Fail(bindingPath + "." + name, "is not the historical node of that role");
            }
        };
        names("texture_set", nodes.set->id);
        names("stack", nodes.stack->id);
        names("host_uid", nodes.host->uid);
        names("filter_uid", nodes.filter->uid);
        names("initial_paint_uid", nodes.paint->uid);
        Literal(binding, "node_stack", "Content", bindingPath);
        if (Integer(binding, "effect_index", bindingPath, 0) != 0) Fail(bindingPath + ".effect_index", "expected 0");
        Literal(binding, "host_channel", "User0", bindingPath);
        const auto reference = [&](const char* name, const core::ProceduralRef& actual) {
            const std::string member = bindingPath + "." + name;
            const Value& stored = Member(binding, name);
            core::ProceduralRef parsed;
            try {
                parsed = core::ProceduralRefFromJson(stored, member);
            } catch (const core::ManifestError& error) {
                Fail(member, error.what());
            }
            if (!SameTyped(core::ProceduralRefToJson(parsed), stored) || !SameTyped(core::ProceduralRefToJson(actual), stored)) {
                Fail(member, "is not the complete canonical serialization of the historical reference");
            }
            return parsed;
        };
        const core::ProceduralRef hostRef = reference("host_reference", *nodes.host_ref);
        const core::ProceduralRef filterRef = reference("filter_reference", *nodes.filter->procedural);
        if (filterRef.asset != ObservationPin(filterKey)) {
            Fail(bindingPath + ".filter_reference.asset", "expected the descriptor's pin " + ObservationPin(filterKey));
        }
        if (!SnapshotPin(hostRef.asset) || core::IsObservationAsset(hostRef.asset)) {
            Fail(bindingPath + ".host_reference.asset", "expected a snapshot pin, never an observation pin");
        }

        // The selected host snapshot of the historical projection, with its /3 observations, its
        // signature's output and the census plane.
        const std::string hostPath = path + ".host_snapshot";
        const Object& hostSnapshot = Closed(Member(entry, "host_snapshot"), hostPath, {"signature_sha256", "plane_id"});
        const std::string& signature = Sha256(hostSnapshot, "signature_sha256", hostPath);
        const std::int64_t planeId = Integer(hostSnapshot, "plane_id", hostPath, 1);
        std::optional<SnapshotEntry> host;
        for (SnapshotEntry& snapshot : ProjectSnapshots(historical)) {
            if (snapshot.key == signature) host = std::move(snapshot);
        }
        if (!host) Fail(hostPath + ".signature_sha256", "names no snapshot of the historical projection");
        if (static_cast<std::int64_t>(host->plane_id) != planeId) Fail(hostPath + ".plane_id", "is not the snapshot's plane");
        if (!host->source_metadata || !host->source_metadata->typed_effective_parameters ||
            !host->source_metadata->observed_resource_id) {
            Fail(hostPath, "the snapshot's metadata does not hold both typed effective parameters and the observed ResourceID (/3)");
        }
        const Object* signatureObject = std::get_if<Object>(&host->signature.data);
        const auto signatureText = [&](const char* name) -> std::string {
            const auto it = signatureObject == nullptr ? Object::const_iterator{} : signatureObject->find(name);
            if (signatureObject == nullptr || it == signatureObject->end() || !it->second.IsString()) {
                Fail(hostPath, std::string("the snapshot signature has no ") + name);
            }
            return std::get<std::string>(it->second.data);
        };
        if (hostRef.asset != signatureText("asset") + "@" + signatureText("version")) {
            Fail(bindingPath + ".host_reference.asset", "is not the selected snapshot signature's pin");
        }
        const auto output = signatureObject->find("output");
        const Object* outputObject = output == signatureObject->end() ? nullptr : std::get_if<Object>(&output->second.data);
        const Object& plane = CensusPlane(Member(context, "inventory"), planeId, hostPath + ".plane_id");
        const auto outputInt = [&](const char* name) {
            const auto it = outputObject == nullptr ? Object::const_iterator{} : outputObject->find(name);
            return outputObject != nullptr && it != outputObject->end() && it->second.IsInt()
                       ? std::get<std::int64_t>(it->second.data)
                       : std::int64_t{-1};
        };
        const auto outputText = [&](const char* name) {
            const auto it = outputObject == nullptr ? Object::const_iterator{} : outputObject->find(name);
            return outputObject != nullptr && it != outputObject->end() && it->second.IsString()
                       ? std::get<std::string>(it->second.data)
                       : std::string();
        };
        // The host's output and parameters are the signature's: its one User0 output is the
        // signature's output id, and its parameters are the signature's by decision 361's codec.
        if (outputText("id").empty() || outputText("id") != hostRef.output_mapping.at("User0")) {
            Fail(hostPath, "the snapshot's output id is not the host's User0 output");
        }
        const auto params = signatureObject->find("params");
        const Object* signatureParams = params == signatureObject->end() ? nullptr : std::get_if<Object>(&params->second.data);
        if (signatureParams == nullptr || signatureParams->size() != hostRef.params.size()) {
            Fail(hostPath, "the snapshot's parameters are not the host's");
        }
        for (const auto& [name, parameter] : hostRef.params) {
            const auto signed_ = signatureParams->find(name);
            const auto a = ParamByValue(parameter);
            const auto b = signed_ == signatureParams->end() ? std::nullopt : ParamByValue(signed_->second);
            if (!a || !b || !SameTyped(*a, *b)) Fail(hostPath, "the snapshot's parameter '" + name + "' is not the host's");
        }
        if (outputObject == nullptr || outputInt("resolution") != 128 || outputInt("channels") != 1 ||
            outputText("format") != "f32" || outputText("colour_space") != "raw" ||
            std::get<std::int64_t>(plane.at("width").data) != 128 || std::get<std::int64_t>(plane.at("height").data) != 128 ||
            plane.at("format") != Value(std::string("L32F"))) {
            Fail(hostPath, "the snapshot's output and census plane are not one 128 x 128 f32 channel (L32F)");
        }

        CaptureV2(Member(entry, "capture"), context, *host, plane, contextHash, project_uuid, path + ".capture");
        Observations(Member(entry, "observations"), *filterDescriptor->second, path + ".observations");
        if (const std::string hash = ObservationKey(body); hash != key) Fail(path, "the entry hashes to " + hash);
        entries.emplace(key, &entry);
    }

    for (const auto& [key, body] : Map(space, "bindings", root)) {
        const std::string path = root + ".bindings." + key;
        const std::int64_t uid = UidKey(key, path);
        const std::string* entryKey = std::get_if<std::string>(&body.data);
        const auto entry = entryKey == nullptr ? entries.end() : entries.find(*entryKey);
        if (entry == entries.end()) Fail(path, "names no entry of the namespace");
        const Object& binding = std::get<Object>(Member(*entry->second, "binding").data);
        if (std::get<std::int64_t>(Member(binding, "filter_uid").data) != uid) Fail(path, "the entry is bound to another Filter UID");
    }
}

/// The namespace check of its exact schema: V2, or else V1 (whose own check refuses every other
/// schema).
void Check(const Value& value, std::string_view project_uuid) {
    const Object* space = std::get_if<Object>(&value.data);
    const auto schema = space == nullptr ? Object::const_iterator{} : space->find("schema");
    if (space != nullptr && schema != space->end() && schema->second == Value(std::string(kFilterObservationsSchemaV2))) {
        CheckV2(value, project_uuid);
    } else {
        CheckV1(value, project_uuid);
    }
}

}  // namespace

Value FrozenHostDomain() {
    return Object{{"schema", std::string(kFrozenHostDomainSchema)},
                  {"rule", std::string(kFrozenHostRule)},
                  {"mesh_sha256", std::string(kFrozenHostPlaneMesh)},
                  {"width", 128},
                  {"height", 128},
                  {"channel", std::string("User0")},
                  {"format", std::string("L32F")},
                  {"source_stage", std::string("frozen_output")},
                  {"source_transport", std::string("snapshot-direct-upload")},
                  {"proof_topology", std::string("host-fill-over-empty-paint-with-observed-filter-removed")},
                  {"readout", std::string("float32(1+float32(v-1))")},
                  {"finite_required", true},
                  {"fixed_point_required", true},
                  {"bitwise_upload_required", true},
                  {"bitwise_final_output_required", true}};
}

std::string FrozenHostDomainProblem(const core::Project& project, FrozenHostNodes& nodes) {
    using core::ChannelType;
    nodes = {};
    const auto& settings = project.settings;
    const auto& colour = settings.color_management;
    if (project.texture_sets.size() != 1 || project.texture_sets.front().stacks.size() != 1) {
        return "one texture set with one stack is required";
    }
    const core::TextureSet& set = project.texture_sets.front();
    const core::Stack& stack = set.stacks.front();
    if (set.uv_tiles.size() != 1 || set.uv_tiles.front().udim != 1001 || set.resolution.width != 128 ||
        set.resolution.height != 128 || !set.mesh_maps.empty()) {
        return "one full-UV 128 x 128 set on UV tile 1001 without mesh maps is required";
    }
    if (!project.mesh || project.mesh->resource != kFrozenHostPlaneMesh) return "the mesh must be the authored full-UV plane";
    const std::set<std::string> onlyMesh{project.mesh->resource};
    const auto external = project.mesh->import_report.find(core::kMeshExternalFiles);
    if (project.resources.size() != 1 || !project.resources.contains(project.mesh->resource) ||
        core::MeshResourceHashes(project) != onlyMesh || core::RecipeResourceHashes(project) != onlyMesh ||
        (external != project.mesh->import_report.end() &&
         !(external->second.IsArray() && std::get<Array>(external->second.data).empty())) ||
        project.display.environment.resource || project.display.color_lut) {
        return "the mesh must be the only resource and dependency";
    }
    if (settings.workflow != core::ProjectWorkflow::Default || settings.normal_map_format != core::NormalMapFormat::OpenGL ||
        settings.tangent_space != core::TangentSpace::PerVertex || settings.mesh_unit_scale != 1.0 ||
        (!colour.mode.empty() && colour.mode != "legacy") || !colour.config_hash.empty() ||
        !colour.working_space.empty() || !colour.io_rules.empty()) {
        return "Legacy, OpenGL, PerVertex, the Default workflow and unit scale 1 are required";
    }
    if (stack.root_layers.size() != 2) return "the root layers must be exactly [host Fill, empty Paint]";
    const core::Layer& host = stack.root_layers[0];
    const core::Layer& paint = stack.root_layers[1];
    if (!core::IsEmptyPaintLayer(paint) || paint.mask || !paint.children.empty() || paint.instance_source != core::kNoId) {
        return "the bottom root layer must be the initial empty Paint layer";
    }
    if (host.kind != core::LayerKind::fill || !host.fill || host.paint || host.mask || !host.children.empty() ||
        host.instance_source != core::kNoId || host.preset_ref || !host.visible || host.geometry_mask.inclusion_list ||
        !host.geometry_mask.items.empty()) {
        return "the top root layer must be a visible host Fill without mask, preset, child, instance or geometry mask";
    }
    const auto blending = host.blending.find(ChannelType::User0);
    if (blending == host.blending.end() || blending->second.mode != core::BlendingMode::Normal ||
        blending->second.opacity != 1.0) {
        return "the host must blend User0 Normal at opacity 1";
    }
    const core::FillContent& fill = *host.fill;
    const auto channel = stack.channels.find(ChannelType::User0);
    if (fill.source_mode != core::SourceMode::Split || fill.sources.size() != 1 || !fill.sources.contains(ChannelType::User0) ||
        fill.active_channels != std::set<ChannelType>{ChannelType::User0} || fill.mono_source || fill.material_source ||
        channel == stack.channels.end() || channel->second.format != core::ChannelFormat::L32F) {
        return "the host must hold one active Split source on User0 (L32F)";
    }
    const auto* source = std::get_if<core::ProceduralSource>(&fill.sources.at(ChannelType::User0).value);
    if (source == nullptr || !SnapshotPin(source->ref.asset) || source->ref.preset || !source->ref.image_inputs.empty() ||
        source->ref.mask_output || source->ref.output_mapping.size() != 1 ||
        !source->ref.output_mapping.contains("User0") || source->ref.output_mapping.at("User0").empty()) {
        return "the host source must be a snapshot reference with one User0 output and no preset, input or mask output";
    }
    for (const auto& [name, parameter] : source->ref.params) {
        if (!ParamByValue(parameter)) return "the host parameter '" + name + "' is outside decision 361's codec";
    }
    const auto& uv = fill.projection.uv;
    const auto& transform = uv.uv_transformation;
    if ((fill.projection.mode != core::ProjectionMode::UV && fill.projection.mode != core::ProjectionMode::Fill) ||
        transform.scale_mode != core::ScaleMode::Factors || transform.scale != std::array<double, 2>{1, 1} ||
        transform.rotation != 0 || transform.offset != std::array<double, 2>{0, 0} || fill.symmetry.enabled ||
        uv.filtering_mode != core::FilteringMode::BilinearHQ || uv.uv_wrapping_mode != core::UVWrapMode::Repeat) {
        return "the host projection must be the identity UV or Fill projection with BilinearHQ and Repeat";
    }
    if (host.content_effects.size() != 1) return "the host must hold exactly one content effect, the Filter";
    const core::Effect& filter = host.content_effects.front();
    if (filter.kind != core::EffectKind::filter || !filter.procedural || filter.fill || filter.paint || filter.levels ||
        filter.compare_mask || filter.color_selection || filter.anchor_name || filter.preset_ref || filter.mono_blending ||
        !core::IsObservationPin(filter.procedural->asset)) {
        return "the content effect must be a Filter whose reference is an observation pin";
    }
    // The observed Filter keeps V1's reference boundary: three getter observations authenticate no
    // preset and no image input, whatever resource it would name.
    if (filter.procedural->preset || !filter.procedural->image_inputs.empty()) {
        return "the Filter reference may hold no preset and no image input";
    }
    for (const auto& [name, parameter] : filter.procedural->params) {
        if (!ParamByValue(parameter)) return "the Filter parameter '" + name + "' is outside decision 361's codec";
    }
    if (filter.active_channels.empty() ||
        std::any_of(filter.active_channels.begin(), filter.active_channels.end(),
                    [&](ChannelType c) { return !stack.channels.contains(c); })) {
        return "the Filter must be active on a nonempty set of stack channels";
    }
    for (const auto& [blended, blend] : filter.blending) {
        if (!stack.channels.contains(blended) || !std::isfinite(blend.opacity) || blend.opacity < 0 || blend.opacity > 1) {
            return "the Filter blends a channel outside the stack or at an opacity outside [0, 1]";
        }
    }
    nodes = FrozenHostNodes{&set, &stack, &host, &paint, &filter, &source->ref};
    return {};
}

std::string ObservationKey(const Value& body) { return core::Sha256Hex(core::json::WriteCanonical(body)); }

std::string ObservationPin(std::string_view descriptor_key) {
    return "uzasset://" + std::string(core::kObservationFamily) + "/" + std::string(descriptor_key) + "@1";
}

std::string FilterObservationsProblem(const Value& member, std::string_view project_uuid) {
    try {
        Check(member, project_uuid);
    } catch (const Problem& problem) {
        return problem.text;
    }
    return {};
}

std::string ProjectFilterObservationsProblem(const core::Project& project, std::string_view project_uuid) {
    const auto member = project.extra.find(kFilterObservationsKey);
    return member == project.extra.end() ? std::string{} : FilterObservationsProblem(member->second, project_uuid);
}

void CheckFilterObservations(const core::Project& project, std::string_view project_uuid) {
    const std::string problem = ProjectFilterObservationsProblem(project, project_uuid);
    if (!problem.empty()) throw StoreError(StoreError::Code::conflict, problem);
}

}  // namespace uzp::store
