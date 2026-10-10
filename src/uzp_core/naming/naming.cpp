#include "uzp_core/naming/naming.h"

#include <utility>

#include "uzp_core/document/nodes.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/validation.h"

namespace uzp::core {

namespace {

std::string IdList(const std::vector<Id>& ids) {
    std::string out;
    for (const Id id : ids) out += (out.empty() ? "" : ", ") + std::to_string(id);
    return out;
}

std::string Describe(const NameScope& scope) {
    std::string out = "texture set " + std::to_string(scope.texture_set) + ", stack " + std::to_string(scope.stack);
    if (scope.parent != kNoId) {
        out += ", parent " + std::to_string(scope.parent) + " (" + std::string(ToString(scope.node_stack)) + ")";
    }
    return out;
}

template <typename Node>
void Match(const std::vector<Node>& nodes, std::string_view name, std::vector<Id>& out) {
    for (const Node& node : nodes) {
        if (node.name == name) out.push_back(node.uid);
    }
}

NodeType TypeOf(const Project& project, Id uid) { return *FindNodeType(project, uid); }

}  // namespace

AmbiguousNameError::AmbiguousNameError(const std::string& name, std::vector<Id> candidates)
    : ValueError("name '" + name + "' is ambiguous: candidates " + IdList(candidates)),
      candidates_(std::move(candidates)) {}

std::vector<Id> FindAllByName(const Project& project, std::string_view name) {
    std::vector<Id> out;
    ForEachNode(project, [&](const NodeVisit& visit) {
        if (visit.layer != nullptr && visit.layer->name == name) out.push_back(visit.layer->uid);
        if (visit.effect != nullptr && visit.effect->name == name) out.push_back(visit.effect->uid);
    });
    return out;
}

std::vector<Id> FindByName(const Project& project, const NameScope& scope, std::string_view name) {
    const Stack* stack = FindStack(project, scope.texture_set, scope.stack);
    if (stack == nullptr) throw ValueError("no scope " + Describe(scope) + ": the stack does not exist");
    std::vector<Id> out;
    if (scope.parent == kNoId) {
        Match(stack->root_layers, name, out);
        return out;
    }
    const Layer* parent = FindLayer(*stack, scope.parent);
    if (parent == nullptr) throw ValueError("no scope " + Describe(scope) + ": the parent is not a layer of the stack");
    switch (scope.node_stack) {
        case NodeStack::Substack:
            if (parent->kind != LayerKind::group) throw ValueError("no scope " + Describe(scope) + ": the parent is not a group");
            Match(parent->children, name, out);
            break;
        case NodeStack::Content:
            Match(parent->content_effects, name, out);
            break;
        case NodeStack::Mask:
            if (!parent->mask) throw ValueError("no scope " + Describe(scope) + ": the parent has no mask");
            Match(parent->mask->effects, name, out);
            break;
    }
    return out;
}

std::optional<Id> ResolveName(const Project& project, const NameScope& scope, std::string_view name) {
    std::vector<Id> matches = FindByName(project, scope, name);
    if (matches.empty()) return std::nullopt;
    if (matches.size() > 1) throw AmbiguousNameError(std::string(name), std::move(matches));
    return matches.front();
}

NamedNode InsertNamed(Edit& edit, const NameScope& scope, NodeType type, std::string name, Id instance_source) {
    if (const std::optional<Id> existing = ResolveName(edit.project(), scope, name)) {
        const NodeType found = TypeOf(edit.project(), *existing);
        if (found != type) {
            throw ValueError("name '" + name + "' in " + Describe(scope) + " already names " +
                             std::string(ToString(found)) + " " + std::to_string(*existing) + ", not a " +
                             std::string(ToString(type)));
        }
        return NamedNode{*existing, false};
    }
    const InsertPosition position = scope.parent == kNoId ? InsertPosition::FromStack(scope.texture_set, scope.stack)
                                                          : InsertPosition::Inside(scope.parent, scope.node_stack);
    return NamedNode{edit.Insert(position, type, std::move(name), instance_source), true};
}

}  // namespace uzp::core
