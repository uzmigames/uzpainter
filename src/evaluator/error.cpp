#include "evaluator/error.h"

#include <array>

namespace uzp::evaluator {

namespace {

constexpr std::array<std::string_view, 13> kKindNames = {
    "not_found",          "unknown_template",      "missing_base_value",   "unsupported_node",
    "unsupported_blend_mode", "unsupported_source", "invalid_argument", "missing_resource",
    "texture_set_over_budget", "tile_budget_exceeded", "unknown_profile", "invalid_profile",
    "internal",
};

constexpr std::string_view kPrefix = "evaluator:";

}  // namespace

std::string_view EvalErrorKindName(EvalErrorKind kind) {
    return kKindNames[static_cast<size_t>(kind)];
}

std::string_view ErrorClassName(EvalErrorKind kind) {
    switch (kind) {
        case EvalErrorKind::UnsupportedNode:
        case EvalErrorKind::UnsupportedBlendMode:
        case EvalErrorKind::UnsupportedSource: return "NotYetSupported";
        case EvalErrorKind::NotFound:
        case EvalErrorKind::UnknownTemplate:
        case EvalErrorKind::InvalidArgument: return "ValueError";
        case EvalErrorKind::MissingResource: return "ResourceNotFoundError";
        case EvalErrorKind::MissingBaseValue:
        case EvalErrorKind::TextureSetOverBudget:
        case EvalErrorKind::TileBudgetExceeded:
        case EvalErrorKind::UnknownProfile:
        case EvalErrorKind::InvalidProfile:
        case EvalErrorKind::Internal: return "RuntimeError";
    }
    return "RuntimeError";
}

render::Unexpected EvalFail(EvalErrorKind kind, std::string detail, core::Id node) {
    std::string reason(kPrefix);
    reason += EvalErrorKindName(kind);
    if (node != core::kNoId) {
        reason += " node=";
        reason += std::to_string(node);
    }
    reason += ": ";
    reason += detail;
    return render::Fail(render::ErrorCode::RequestFailed, std::nullopt, std::move(reason));
}

std::optional<EvalErrorKind> EvalErrorKindOf(const render::Error& error) {
    if (error.code != render::ErrorCode::RequestFailed) return std::nullopt;
    const std::string_view reason(error.reason);
    if (!reason.starts_with(kPrefix)) return std::nullopt;
    const std::string_view rest = reason.substr(kPrefix.size());
    for (size_t i = 0; i < kKindNames.size(); ++i) {
        const std::string_view name = kKindNames[i];
        if (rest.starts_with(name) && rest.size() > name.size() &&
            (rest[name.size()] == ':' || rest[name.size()] == ' ')) {
            return static_cast<EvalErrorKind>(i);
        }
    }
    return std::nullopt;
}

}  // namespace uzp::evaluator
