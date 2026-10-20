#pragma once

// The typed MCP tool families of `docs/architecture/11-mcp-server.md` §2 that the worker serves
// (task phase2.6_mcp-typed-tool-families, decision 164): Project, Texture sets, Resources, Stack,
// Recipes (`sync_stack`, `apply_smart`), Baking and Mesh, and the Stack family's later kinds. Each
// mutating tool is one transaction submitted with its client's key and original precondition
// (`Session::Submit`), running the native edits the `uzpainter` API runs (src/python/edits.h).
// A family whose native implementation is not in this build is registered with its schema and
// declares the release-gap operations it needs, so the supervisor refuses it with `capability_gap`
// before admission; its handler refuses the same way for a direct pipe client. See
// src/supervisor/SUPERVISOR.md (Typed tools).

#include <exception>
#include <filesystem>
#include <functional>
#include <string>
#include <vector>

#include "supervisor/tools.h"
#include "uzp_core/transaction/transaction.h"

namespace uzp::supervisor {

/// What a typed tool needs of the worker.
struct ToolContext {
    /// Runs `call` as the admitted mutation of the call being handled (its client's key and
    /// original precondition) and returns its transaction result; a refused or failed call throws
    /// its `CallError` or the typed error that failed it.
    std::function<json::Object(const std::function<void(core::Edit&)>& call)> submit;
    /// The admitted mutation request of the call being handled.
    std::function<const core::MutationRequest&()> mutation;
    /// The transaction result of an outcome of the admitted request, decided elsewhere (a create or
    /// a revert); throws like `submit`.
    std::function<json::Object(const core::RequestOutcome& outcome, const std::exception_ptr& error)> settle;
    /// A file path inside the worker's output root (a relative path is taken under it);
    /// `invalid_arguments` otherwise.
    std::function<std::filesystem::path(const std::string& path)> output_path;
};

/// Every typed tool of the families above, in listing order.
std::vector<ToolDefinition> TypedTools(const ToolContext& context);

}  // namespace uzp::supervisor
