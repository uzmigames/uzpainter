#pragma once

#include <expected>
#include <optional>
#include <string>
#include <vector>

#include "store/project_store.h"
#include "uzp_core/types/project.h"

namespace uzp::procedural {

/// Copies of raw observations, never an executable procedural source. Absence is not empty;
/// callers must refuse a getter whose corresponding optional is absent.
struct FilterObservation {
    std::string entry_key;
    std::optional<core::json::Object> parameters;
    std::optional<core::json::Object> resource_id;
    std::optional<std::vector<std::string>> image_outputs;
};

/// Decision 362's no-plane, mesh-only context. The caller supplies one immutable snapshot,
/// or a transaction's prospective project, and the owning store. No session reads occur here.
/// ReadResource is safe inside Submit's callback (not its commit sink): Submit releases the
/// store mutex before invoking the callback. All metadata comes from this project, not the store's
/// latest manifest. The returned context retains every project field except the observation namespace.
std::expected<core::json::Object, std::string> CurrentFilterObservationContext(
    store::ProjectStore& store, const core::Project& project);

/// Strict lookup: missing, corrupt, foreign, stale or mismatched observations always refuse.
/// The caller owns legacy dispatch and must validate its retained OpenProject/session lease;
/// this function neither manufactures a lease nor treats an unbound pin as a legacy source.
std::expected<FilterObservation, std::string> ObservedFilter(
    store::ProjectStore& store, const core::Project& project, core::Id filter_uid);

}  // namespace uzp::procedural
