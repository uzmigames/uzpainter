// The worker's tool definitions (tools.h).

#include "supervisor/tools.h"

namespace uzp::supervisor {

json::Object Schema(json::Object properties, json::Array required) {
    return {{"type", "object"},
            {"properties", std::move(properties)},
            {"required", std::move(required)},
            {"additionalProperties", false}};
}

json::Object StringProperty(const char* description) { return {{"type", "string"}, {"description", description}}; }

json::Object PathProperty(const char* description, const char* root) {
    return {{"type", "string"}, {"minLength", 1}, {"description", description}, {"x-uzpainter-root", root}};
}

json::Object UidProperty(const char* description) {
    return {{"type", "integer"}, {"minimum", 1}, {"description", description}, {"x-uzpainter-ref", "node"}};
}

json::Array Operation(const char* symbol) { return {json::Object{{"symbol", symbol}, {"context", "any"}}}; }

json::Object CapabilityByValue(json::Object property, std::vector<std::pair<std::string, const char*>> operations) {
    json::Object map;
    for (const auto& [value, symbol] : operations) map[value] = Operation(symbol);
    property["x-uzpainter-capability"] = std::move(map);
    return property;
}

const json::Value* Field(const json::Object& object, std::string_view key) {
    const auto it = object.find(key);
    return it == object.end() ? nullptr : &it->second;
}

std::optional<std::string> StringField(const json::Object& object, std::string_view key) {
    const json::Value* value = Field(object, key);
    if (!value || !value->IsString()) return std::nullopt;
    return std::get<std::string>(value->data);
}

std::pair<const core::TextureSet*, const core::Stack*> NamedStack(const core::Project& project,
                                                                  const python::OpenProject& open,
                                                                  const json::Object& arguments) {
    const core::TextureSet* set = nullptr;
    const std::optional<std::string> set_name = StringField(arguments, "texture_set");
    for (const core::TextureSet& candidate : project.texture_sets) {
        if (set_name ? candidate.name == *set_name : candidate.id == open.active_set) set = &candidate;
    }
    if (!set) throw CallError{"invalid_arguments", "no texture set " + set_name.value_or("(active)"), {}};
    const core::Stack* stack = nullptr;
    const std::optional<std::string> stack_name = StringField(arguments, "stack");
    for (const core::Stack& candidate : set->stacks) {
        if (stack_name ? candidate.name == *stack_name : candidate.id == open.active_stack) stack = &candidate;
    }
    if (!stack && !stack_name && !set->stacks.empty()) stack = &set->stacks.front();
    if (!stack) throw CallError{"invalid_arguments", "no stack " + stack_name.value_or("(active)"), {}};
    return {set, stack};
}

std::optional<CallError> AdmissionRefusal(const core::AdmissionDecision& decision, const std::string& key) {
    switch (decision.admission) {
        case core::Admission::idempotency_conflict:
            return CallError{"idempotency_conflict", "the idempotency key was committed with other arguments",
                             json::Object{{"key", key}, {"committed_revision", decision.record->committed_revision}}};
        case core::Admission::outcome_unknown:
            return CallError{"outcome_unknown",
                             "the key is unknown and its precondition is missing, expired or unreadable: the call "
                             "is not run",
                             json::Object{{"key", key}, {"committed_revision", decision.current_revision}}};
        case core::Admission::stale_revision: {
            json::Object details{{"expected", decision.expected_revision ? json::Value(*decision.expected_revision)
                                                                         : json::Value(nullptr)},
                                 {"current", decision.current_revision}};
            return CallError{"stale_revision", "the project is at another revision than the call expected",
                             std::move(details)};
        }
        case core::Admission::stored_outcome:
        case core::Admission::execute:
            break;
    }
    return std::nullopt;
}

}  // namespace uzp::supervisor
