#include "store/filter_observations.h"

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <initializer_list>
#include <map>
#include <set>
#include <string>

#include "store/container.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/resource_url.h"

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

void Check(const Value& value, std::string_view project_uuid) {
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
        const auto host = hosts.find(std::get<std::int64_t>(Member(binding, "host_uid").data));
        if (host == hosts.end()) Fail(path, "the entry's host UID has no host binding");
        if (Member(*host->second, "channel") != Member(binding, "host_channel") ||
            Member(*host->second, "descriptor") != Member(*entry->second, "host_descriptor")) {
            Fail(path, "the host binding disagrees with the entry's host channel or descriptor");
        }
    }
}

}  // namespace

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
