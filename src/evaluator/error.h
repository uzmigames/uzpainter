#pragma once

// Evaluator failures travel in the render layer's `Result`/`Error` (one result type from the
// kernels up to the engine thread's futures). They use `ErrorCode::RequestFailed`, no backend,
// and a reason of the form `evaluator:<kind>[ node=<uid>]: <detail>`, so callers and tests can
// read the kind back with `EvalErrorKindOf`.

#include "render/backend.h"

#include <optional>
#include <string>
#include <string_view>

#include "uzp_core/types/ids.h"

namespace uzp::evaluator {

enum class EvalErrorKind : uint8_t {
    NotFound,              ///< No such texture set, stack or channel in the snapshot.
    UnknownTemplate,       ///< The template id is not in the library.
    MissingBaseValue,      ///< No base value for a channel (template and channel defaults).
    UnsupportedNode,       ///< A node kind this profile does not evaluate (paint, effects, ...).
    UnsupportedBlendMode,  ///< A blend mode without a kernel in this build.
    UnsupportedSource,     ///< A source or conversion outside this profile.
    MissingResource,       ///< A bitmap source whose bytes the resource provider lacks.
    TextureSetOverBudget,  ///< A texture set whose live tiles do not fit the admission budget.
    TileBudgetExceeded,    ///< The working set of one tile evaluation exceeds the budget.
    UnknownProfile,        ///< The project's evaluator profile is not registered (profile.h).
    InvalidProfile,        ///< A profile registration with a malformed or taken id.
    Internal,              ///< An invariant failed.
};

/// "not_found", "unknown_template", "missing_base_value", "unsupported_node",
/// "unsupported_blend_mode", "unsupported_source", "missing_resource",
/// "texture_set_over_budget", "tile_budget_exceeded", "unknown_profile", "invalid_profile" or
/// "internal".
[[nodiscard]] std::string_view EvalErrorKindName(EvalErrorKind kind);

/// `request_failed` with the reason `evaluator:<kind>[ node=<node>]: <detail>`.
[[nodiscard]] render::Unexpected EvalFail(EvalErrorKind kind, std::string detail,
                                          core::Id node = core::kNoId);

/// The kind of an evaluator failure, or nullopt for any other error (a GPU error, say).
[[nodiscard]] std::optional<EvalErrorKind> EvalErrorKindOf(const render::Error& error);

}  // namespace uzp::evaluator
