#pragma once

// The recipe dump and rebuild of the open project (task phase2.1_recipe-dump-manifest-blocks,
// decision 122; `src/uzp_core/manifest/recipe.h`), and the host the `inspect` verb uses.
//
// - `HostRecipe()`: UzPainter's version and the base values of the templates installed beside the
//   executable (`assets/templates/`), loaded on first use. A template the library does not hold,
//   or a library that does not load, makes the dump fail with `core::ValueError`.
// - `DumpCurrentRecipe()`: the dump of the open project's current revision. It is the native
//   operation behind `uzpainter.project.dump_recipe`, the MCP `project_recipe` tool and the
//   `uzpainter://project/recipe` resource (their registration: phase2.6_mcp-typed-tool-families).
//   A native `Transaction`'s working copy is never dumped: the dump describes a committed
//   revision.

#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/recipe.h"

namespace uzp::python {

core::RecipeHost HostRecipe();

/// `ProjectError` when no project is open.
core::json::Object DumpCurrentRecipe();

}  // namespace uzp::python
