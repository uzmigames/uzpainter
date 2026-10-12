#include "uzp_core/document/layer_tree.h"

#include <map>
#include <string>
#include <utility>

#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/types/errors.h"

namespace uzp::core {

namespace {

json::Value IdValue(Id id) { return json::Value(static_cast<std::int64_t>(id)); }

json::Array Uids(const json::Value& nodes) {
    json::Array uids;
    for (const json::Value& node : std::get<json::Array>(nodes.data)) {
        uids.push_back(std::get<json::Object>(node.data).at("uid"));
    }
    return uids;
}

json::Object Params(json::Value manifest) {
    json::Object params = std::move(std::get<json::Object>(manifest.data));
    for (const char* key : {"uid", "kind", "name", "visible"}) params.erase(key);
    if (const auto it = params.find("content_effects"); it != params.end()) it->second = Uids(it->second);
    if (const auto it = params.find("children"); it != params.end()) it->second = Uids(it->second);
    if (const auto it = params.find("mask"); it != params.end() && it->second.IsObject()) {
        json::Object& mask = std::get<json::Object>(it->second.data);
        if (const auto effects = mask.find("effects"); effects != mask.end()) effects->second = Uids(effects->second);
    }
    return params;
}

[[noreturn]] void Malformed(std::string_view which, const std::string& what) {
    throw ValueError("diff_snapshots: the " + std::string(which) + " snapshot is not a " +
                     std::string(kLayerTreeSchema) + " snapshot: " + what);
}

/// The records of `member` of a snapshot by their integer `key`.
std::map<std::int64_t, const json::Object*> Records(const json::Object& snapshot, std::string_view which,
                                                    const char* member, const char* key) {
    const auto it = snapshot.find(member);
    if (it == snapshot.end() || !it->second.IsArray()) Malformed(which, std::string(member) + " is not a list");
    std::map<std::int64_t, const json::Object*> records;
    for (const json::Value& value : std::get<json::Array>(it->second.data)) {
        if (!value.IsObject()) Malformed(which, std::string(member) + " holds a value that is not an object");
        const json::Object& record = std::get<json::Object>(value.data);
        const auto id = record.find(key);
        if (id == record.end() || !id->second.IsInt()) {
            Malformed(which, std::string(member) + " holds a record without an integer " + key);
        }
        if (!records.emplace(std::get<std::int64_t>(id->second.data), &record).second) {
            Malformed(which, std::string(member) + " repeats " + key + " " +
                                 std::to_string(std::get<std::int64_t>(id->second.data)));
        }
    }
    return records;
}

const json::Object& Snapshot(const json::Value& value, std::string_view which) {
    if (!value.IsObject()) Malformed(which, "not an object");
    const json::Object& snapshot = std::get<json::Object>(value.data);
    const auto schema = snapshot.find("schema");
    if (schema == snapshot.end() || schema->second != json::Value(kLayerTreeSchema)) Malformed(which, "wrong schema");
    const auto revision = snapshot.find("revision");
    if (revision == snapshot.end() || !revision->second.IsInt()) Malformed(which, "no integer revision");
    return snapshot;
}

/// `key` escaped as a JSON pointer token (RFC 6901).
std::string Token(std::string_view key) {
    std::string out;
    for (const char c : key) {
        if (c == '~') {
            out += "~0";
        } else if (c == '/') {
            out += "~1";
        } else {
            out += c;
        }
    }
    return out;
}

void Compare(const json::Value& before, const json::Value& after, const std::string& path, json::Array& changes) {
    if (before.IsObject() && after.IsObject()) {
        const json::Object& a = std::get<json::Object>(before.data);
        const json::Object& b = std::get<json::Object>(after.data);
        // Both maps are sorted by key: one merge pass visits every key once, in path order.
        auto i = a.begin();
        auto j = b.begin();
        while (i != a.end() || j != b.end()) {
            if (j == b.end() || (i != a.end() && i->first < j->first)) {
                changes.push_back(json::Object{{"path", path + "/" + Token(i->first)}, {"before", i->second}});
                ++i;
            } else if (i == a.end() || j->first < i->first) {
                changes.push_back(json::Object{{"path", path + "/" + Token(j->first)}, {"after", j->second}});
                ++j;
            } else {
                Compare(i->second, j->second, path + "/" + Token(i->first), changes);
                ++i;
                ++j;
            }
        }
        return;
    }
    if (before != after) changes.push_back(json::Object{{"path", path}, {"before", before}, {"after", after}});
}

/// `{added, removed, modified}` of two keyed record sets.
json::Object Changes(const std::map<std::int64_t, const json::Object*>& before,
                     const std::map<std::int64_t, const json::Object*>& after, const char* key) {
    json::Array added;
    json::Array removed;
    json::Array modified;
    for (const auto& [id, record] : before) {
        const auto other = after.find(id);
        if (other == after.end()) {
            removed.push_back(*record);
            continue;
        }
        json::Array changes;
        Compare(json::Value(*record), json::Value(*other->second), "", changes);
        if (!changes.empty()) modified.push_back(json::Object{{key, id}, {"changes", std::move(changes)}});
    }
    for (const auto& [id, record] : after) {
        if (!before.contains(id)) added.push_back(*record);
    }
    return {{"added", std::move(added)}, {"removed", std::move(removed)}, {"modified", std::move(modified)}};
}

}  // namespace

json::Object SnapshotLayerTree(const Project& project, std::int64_t revision) {
    json::Array stacks;
    for (const TextureSet& set : project.texture_sets) {
        for (const Stack& stack : set.stacks) {
            stacks.push_back(json::Object{{"texture_set", IdValue(set.id)},
                                          {"texture_set_name", set.name},
                                          {"stack", IdValue(stack.id)},
                                          {"stack_name", stack.name}});
        }
    }
    json::Array nodes;
    ForEachNode(project, [&](const NodeVisit& visit) {
        const bool layer = visit.layer != nullptr;
        const bool root = layer && visit.owner == visit.stack;
        json::Object record{
            {"uid", IdValue(layer ? visit.layer->uid : visit.effect->uid)},
            {"node", layer ? "layer" : "effect"},
            {"kind", layer ? std::string(ToString(visit.layer->kind)) : std::string(ToString(visit.effect->kind))},
            {"name", layer ? visit.layer->name : visit.effect->name},
            {"visible", layer ? visit.layer->visible : visit.effect->visible},
            {"texture_set", IdValue(visit.texture_set)},
            {"stack", IdValue(visit.stack)},
            {"parent", root ? json::Value(nullptr) : IdValue(visit.owner)},
            {"slot", std::string(ToString(visit.owner_stack))},
            {"index", static_cast<std::int64_t>(visit.index)},
            {"params", Params(layer ? LayerToJson(*visit.layer)
                                    : EffectToJson(*visit.effect, visit.owner_stack == NodeStack::Mask))}};
        nodes.push_back(std::move(record));
    });
    return {{"schema", std::string(kLayerTreeSchema)},
            {"revision", revision},
            {"stacks", std::move(stacks)},
            {"nodes", std::move(nodes)}};
}

json::Object DiffSnapshots(const json::Value& before, const json::Value& after) {
    const json::Object& a = Snapshot(before, "first");
    const json::Object& b = Snapshot(after, "second");
    json::Object nodes = Changes(Records(a, "first", "nodes", "uid"), Records(b, "second", "nodes", "uid"), "uid");
    json::Object diff{{"schema", std::string(kLayerTreeDiffSchema)},
                      {"before_revision", a.at("revision")},
                      {"after_revision", b.at("revision")},
                      {"stacks", Changes(Records(a, "first", "stacks", "stack"), Records(b, "second", "stacks", "stack"),
                                         "stack")}};
    for (auto& [key, value] : nodes) diff[key] = std::move(value);
    return diff;
}

}  // namespace uzp::core
