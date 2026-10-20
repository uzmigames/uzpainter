#include "bake/baking_project.h"

#include <algorithm>
#include <map>
#include <set>
#include <utility>

#include "uzp_core/types/errors.h"

namespace uzp::bake {
namespace {

using core::json::Array;
using core::json::Object;
using core::json::Value;
using core::ValueError;
constexpr const char* kGroups = "linked_groups";

const Object& ObjectOf(const Value& value) {
    if (!value.IsObject()) throw ValueError("bake linked_groups: expected an object");
    return std::get<Object>(value.data);
}

const Value& Need(const Object& object, const char* key) {
    const auto it = object.find(key);
    if (it == object.end()) throw ValueError(std::string("bake linked_groups: missing ") + key);
    return it->second;
}

struct Sets {
    std::vector<std::string> names;
    std::map<core::Id, std::string> by_id;
    std::map<std::string, core::Id> by_name;

    explicit Sets(const core::Project& project) {
        for (const auto& set : project.texture_sets) {
            if (set.id == 0 || set.id > core::kMaxId || !by_id.emplace(set.id, set.name).second ||
                !by_name.emplace(set.name, set.id).second)
                throw ValueError("bake linked_groups: texture sets require distinct IDs and names");
            names.push_back(set.name);
        }
    }
};

Array GroupIds(const std::vector<std::string>& group, const Sets& sets) {
    std::set<core::Id> ids;
    for (const auto& name : group) {
        const auto it = sets.by_name.find(name);
        if (it == sets.by_name.end() || !ids.insert(it->second).second)
            throw ValueError("bake linked_groups: unknown or repeated texture set");
    }
    if (ids.size() == 1) throw ValueError("bake linked_groups: a group needs at least two members");
    Array result;
    for (core::Id id : ids) result.emplace_back(static_cast<std::int64_t>(id));
    return result;
}

std::vector<std::string> GroupNames(const Value& value, const Sets& sets) {
    if (!value.IsArray()) throw ValueError("bake linked_groups: expected member IDs");
    std::set<core::Id> members;
    for (const Value& item : std::get<Array>(value.data)) {
        if (!item.IsInt() || std::get<std::int64_t>(item.data) <= 0)
            throw ValueError("bake linked_groups: member ID must be a positive integer");
        const auto id = static_cast<core::Id>(std::get<std::int64_t>(item.data));
        if (!sets.by_id.contains(id) || !members.insert(id).second)
            throw ValueError("bake linked_groups: unknown or repeated member ID");
    }
    if (members.size() == 1) throw ValueError("bake linked_groups: a group needs at least two members");
    std::vector<std::string> names;
    for (const auto& name : sets.names)
        if (members.contains(sets.by_name.at(name))) names.push_back(name);
    return names;
}

struct Groups {
    std::vector<std::string> common, ao;
    bool operator==(const Groups&) const = default;
};

Groups ReadGroups(const Value& value, const Sets& sets) {
    const auto& object = ObjectOf(value);
    for (const auto& [key, unused] : object)
        if (key != "common" && key != "per_baker")
            throw ValueError("bake linked_groups: unknown field '" + key + "'");
    Groups groups{GroupNames(Need(object, "common"), sets), {}};
    const auto& bakers = ObjectOf(Need(object, "per_baker"));
    for (const auto& [name, group] : bakers) {
        if (name != "AO") throw ValueError("bake linked_groups: unsupported baker '" + name + "'");
        groups.ao = GroupNames(group, sets);
    }
    return groups;
}

/// The AO values of `settings` (the only baker values a link group shares).
Object AoValues(const core::BakeSettings& settings) {
    const auto it = settings.per_baker.find("AO");
    return it == settings.per_baker.end() ? Object{} : it->second;
}

void LinkChecked(BakingSession& session, const std::vector<std::string>& group, bool ao) {
    if (group.empty()) return;
    const core::BakeSettings reference = ToBakeSettings(session.parameters(group.front()));
    for (const auto& name : group) {
        const core::BakeSettings settings = ToBakeSettings(session.parameters(name));
        if (ao ? AoValues(settings) != AoValues(reference)
               : settings.common != reference.common || settings.detail != reference.detail)
            throw ValueError("bake linked_groups: linked members have conflicting values");
    }
    if (ao) session.set_linked_group(group, group.front(), MeshMapUsage::AO);
    else session.set_linked_group_common_parameters(group, group.front());
}

}  // namespace

BakingSession LoadBakingSession(const core::Project& project) {
    const Sets sets(project);
    BakingSession session(sets.names);
    session.unlink_all_common_parameters();
    std::optional<Groups> groups;
    std::size_t records = 0;
    for (const auto& set : project.texture_sets) {
        LoadBakeSettings(session.parameters(set.name), set.bake_settings);
        const auto it = set.bake_settings.extra.find(kGroups);
        if (it == set.bake_settings.extra.end()) continue;
        ++records;
        Groups current = ReadGroups(it->second, sets);
        if (groups && *groups != current) throw ValueError("bake linked_groups: inconsistent group records");
        groups = std::move(current);
    }
    if (records != 0 && records != project.texture_sets.size())
        throw ValueError("bake linked_groups: partially persisted groups");
    if (!groups) groups = Groups{sets.names.size() >= 2 ? sets.names : std::vector<std::string>{}, {}};
    LinkChecked(session, groups->common, false);
    LinkChecked(session, groups->ao, true);
    return session;
}

void StoreBakingSession(const BakingSession& session, core::Project& project) {
    (void)LoadBakingSession(project);
    const Sets sets(project);
    if (std::set<std::string>(session.texture_sets().begin(), session.texture_sets().end()) !=
        std::set<std::string>(sets.names.begin(), sets.names.end()))
        throw ValueError("bake linked_groups: session texture sets do not match project");
    const Object groups{{"common", GroupIds(session.get_link_group_common_parameters(), sets)},
                        {"per_baker", Object{{"AO", GroupIds(session.get_link_group(MeshMapUsage::AO), sets)}}}};
    core::Project staged = project;
    for (auto& set : staged.texture_sets) {
        const auto values = ToBakeSettings(session.parameters(set.name));
        set.bake_settings.common = values.common;
        set.bake_settings.detail = values.detail;
        for (int u = 0; u <= static_cast<int>(MeshMapUsage::Opacity); ++u) {
            const auto usage = static_cast<MeshMapUsage>(u);
            if (!StoresBakerValues(usage)) continue;
            const auto stored = values.per_baker.find(UsageName(usage));
            if (stored != values.per_baker.end()) set.bake_settings.per_baker[UsageName(usage)] = stored->second;
            else set.bake_settings.per_baker.erase(UsageName(usage));
        }
        set.bake_settings.extra[kGroups] = groups;
    }
    // Also rejects unsupported persisted settings; never overwrite a file we cannot load.
    (void)LoadBakingSession(staged);
    project = std::move(staged);
}

void EditBakingSession(core::Edit& edit, const std::function<void(BakingSession&)>& call) {
    BakingSession session = LoadBakingSession(edit.project());
    core::Project before = edit.project();
    StoreBakingSession(session, before);
    call(session);
    core::Project after = edit.project();
    StoreBakingSession(session, after);
    if (after != before) edit.project() = std::move(after);
}

core::RequestOutcome ExecuteBakingSession(core::Document& document, core::MutationRequest request,
                                        const std::function<void(BakingSession&)>& call) {
    return core::Execute(document, std::move(request), [&](core::Edit& edit) { EditBakingSession(edit, call); });
}

}  // namespace uzp::bake
