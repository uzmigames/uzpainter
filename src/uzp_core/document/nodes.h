#pragma once

// Walking and finding nodes of a project's layer stacks (`docs/architecture/03-project-model.md`
// §1, `04-layer-stack-and-compositing.md` §1). Used by the transaction diff and by name
// addressing.

#include <cstddef>
#include <functional>

#include "uzp_core/types/enums.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/project.h"

namespace uzp::core {

/// One node met by `ForEachNode`: exactly one of `layer` and `effect` is set. `owner` and
/// `owner_stack` name the list holding it: a stack's root layers are `{stack id, Substack}`, a
/// group's sub-layers `{group uid, Substack}`, a layer's content effects `{layer uid, Content}` and
/// its mask effects `{layer uid, Mask}`. `index` is the position in that list (top first).
struct NodeVisit {
    const Layer* layer = nullptr;
    const Effect* effect = nullptr;
    Id owner = kNoId;
    NodeStack owner_stack = NodeStack::Substack;
    std::size_t index = 0;
    Id texture_set = kNoId;
    Id stack = kNoId;
};

/// Visits every node in tree order: texture sets, stacks, root layers top first, and for each
/// layer its content effects, its mask effects, then its sub-layers.
void ForEachNode(const Project& project, const std::function<void(const NodeVisit&)>& visit);

/// The stack `stack` of texture set `texture_set`, or nullptr.
const Stack* FindStack(const Project& project, Id texture_set, Id stack);

/// The layer or effect with `uid` anywhere in the project, or nullptr.
Layer* FindLayer(Project& project, Id uid);
const Layer* FindLayer(const Project& project, Id uid);
Effect* FindEffect(Project& project, Id uid);

/// The layer with `uid` inside `stack` (at any depth), or nullptr.
const Layer* FindLayer(const Stack& stack, Id uid);

}  // namespace uzp::core
