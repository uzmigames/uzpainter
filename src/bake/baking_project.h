#pragma once

#include <functional>

#include "bake/baking_parameters.h"
#include "uzp_core/transaction/transaction.h"

namespace uzp::bake {

// Called once after creating texture sets. Persist observed initial values so later texture
// resolution edits cannot silently change the bake resolution. Unobserved sizes remain unset.
void InitializeBakingSettings(core::Project& project);

// A fresh, independent session. Persisted groups use texture-set IDs; API names are
// resolved from this project. Legacy manifests without groups retain the common link.
// Malformed groups, conflicting linked values and unsupported parameters are refused.
[[nodiscard]] BakingSession LoadBakingSession(const core::Project& project);

// Replaces supported settings and group membership together; preserves unrelated extras.
// Failure leaves project unchanged. Session names must match the project's sets exactly.
void StoreBakingSession(const BakingSession& session, core::Project& project);

// Use inside ProjectStore::Submit, or ExecuteBakingSession below. No live session is
// mutated: callback edits an independent session of the transaction's working project.
// A callback with no effective settings/group change leaves even legacy manifests intact.
void EditBakingSession(core::Edit& edit, const std::function<void(BakingSession&)>& call);

// Admission, idempotency, revision and commit-sink rollback are Document transactions'.
[[nodiscard]] core::RequestOutcome ExecuteBakingSession(
    core::Document& document, core::MutationRequest request,
    const std::function<void(BakingSession&)>& call);

}  // namespace uzp::bake
