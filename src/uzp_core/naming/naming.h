#pragma once

// Name addressing (LAY-06; `docs/architecture/03-project-model.md` §1, `10-python-api.md` §5).
//
// Names are not identity: two nodes may share a name, and a name lookup returns every match.
// Name-addressed mutations resolve within an explicit `{project, set, stack, parent}` scope (the
// project is the document the call runs in): an ambiguous match fails before anything is
// changed and lists the candidate ids, and repeating the same named operation in the same scope
// finds the node it created instead of creating another.

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "uzp_core/types/enums.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/project.h"

namespace uzp::core {

class Edit;

/// One list of nodes: the root layers of `stack` in `texture_set` when `parent` is `kNoId`,
/// otherwise the `node_stack` list (sub-layers, content effects or mask effects) of the layer
/// `parent`, which must be inside that stack.
struct NameScope {
    Id texture_set = kNoId;
    Id stack = kNoId;
    Id parent = kNoId;
    NodeStack node_stack = NodeStack::Substack;
};

/// A name matched more than one node of a scope. The message lists the candidate ids.
class AmbiguousNameError : public ValueError {
public:
    AmbiguousNameError(const std::string& name, std::vector<Id> candidates);
    const std::vector<Id>& candidates() const { return candidates_; }

private:
    std::vector<Id> candidates_;
};

/// Every layer and effect of the project named `name`, in tree order (`ForEachNode`).
std::vector<Id> FindAllByName(const Project& project, std::string_view name);

/// Every node of the scope's list named `name`, top first. Throws `ValueError` when the scope
/// does not exist (unknown set or stack, a parent outside the stack, a sub-stack of a non-group,
/// the mask stack of a layer without a mask).
std::vector<Id> FindByName(const Project& project, const NameScope& scope, std::string_view name);

/// The one node of the scope named `name`, nullopt when there is none; throws
/// `AmbiguousNameError` when there are several.
std::optional<Id> ResolveName(const Project& project, const NameScope& scope, std::string_view name);

struct NamedNode {
    Id node = kNoId;
    bool created = false;
};

/// Inserts a node of `type` named `name` at the top of the scope's list, unless the scope
/// already holds a node of that name: then nothing changes and that node is returned
/// (`created` false). Throws `AmbiguousNameError` (several matches) or `ValueError` (the match
/// is of another type; the scope does not exist; an insertion rule) before changing anything.
NamedNode InsertNamed(Edit& edit, const NameScope& scope, NodeType type, std::string name, Id instance_source = kNoId);

}  // namespace uzp::core
