#pragma once

// Model validation and node insertion (`docs/architecture/03-project-model.md` §1-§4,
// `04-layer-stack-and-compositing.md` §1-§2).
//
// `Validate` checks a whole project: unique persistent ids below `next_id`; power-of-two
// resolutions 128-8192; the single UV tile 1001 of the Default workflow; per-node channels drawn
// from the stack's channels; the payload each node kind needs; the documented placement rules
// (compare mask and colour selection only in mask stacks, mono-channel blending and sources in
// mask stacks, smart-mask provenance only on mask effects, smart-material provenance only on
// groups); bindings to stored resources; unaliased paint planes; and an acyclic dependency graph
// of anchor references and instances. Every violation throws `ValueError`.
//
// `InsertNode` applies the documented insertion rules of the twelve `NodeType`s and leaves the
// project unchanged when it throws.

#include <string>

#include "uzp_core/types/enums.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/project.h"

namespace uzp::core {

void Validate(const Project& project);

/// Throws `ValueError` when the anchor references and instance links of `project` form a cycle
/// (part of `Validate`, exposed for the transaction layer).
void ValidateAnchorGraph(const Project& project);

/// The documented insertion positions (`layerstack.InsertPosition`).
struct InsertPosition {
    enum class Kind { TopOfStack, AboveNode, BelowNode, InsideNode };

    Kind kind = Kind::TopOfStack;
    Id texture_set = kNoId;  // TopOfStack
    Id stack = kNoId;        // TopOfStack
    Id node = kNoId;         // AboveNode, BelowNode, InsideNode
    NodeStack node_stack = NodeStack::Substack;  // InsideNode

    static InsertPosition FromStack(Id texture_set, Id stack) {
        return {Kind::TopOfStack, texture_set, stack, kNoId, NodeStack::Substack};
    }
    static InsertPosition Above(Id node) { return {Kind::AboveNode, kNoId, kNoId, node, NodeStack::Substack}; }
    static InsertPosition Below(Id node) { return {Kind::BelowNode, kNoId, kNoId, node, NodeStack::Substack}; }
    static InsertPosition Inside(Id node, NodeStack stack) {
        return {Kind::InsideNode, kNoId, kNoId, node, stack};
    }
};

/// Inserts a new node of `type` named `name` and returns its new persistent id. An instance
/// layer needs `instance_source`, the uid of the layer it instances. Throws `ValueError` (the
/// project unchanged) when the position does not exist or the type is not allowed there:
/// layers go at the top of a stack, beside a layer or inside a group's sub-stack; effects go
/// beside an effect or inside a layer's content or mask stack (the mask must exist); compare
/// mask and colour selection effects go only into mask stacks.
Id InsertNode(Project& project, const InsertPosition& position, NodeType type, std::string name,
              Id instance_source = kNoId);

/// The node type of the node with `uid`, or nullopt when no such node exists.
std::optional<NodeType> FindNodeType(const Project& project, Id uid);

}  // namespace uzp::core
