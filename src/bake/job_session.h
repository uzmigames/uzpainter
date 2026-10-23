#pragma once

// A bake job of the open project (phase3.3_baker-evidence-publication items 2.6 and 2.7; decision
// 355), shared by `uzpainter.baking.start` (`src/python/bind_baking.cpp`, behind the facade's
// `bake_async` and `bake_selected_textures_async`) and the MCP tool `bake_start`
// (`src/supervisor/typed_tools.cpp`).
//
// `StartSessionBake` runs on the calling thread: it reads the committed revision, prepares every
// set (`job_inputs.h`) and starts the native `BakeJob` on the CPU baker (Embree), so every refusal
// is raised before any work and before any job exists. It returns the body that follows the bake on
// the native job pool (`src/python/jobs.h`): its progress is the bake's, a cancel of the pool job
// cancels the bake at once (checked at tile boundaries), and its commit point is the publication.
//
// The publication follows decision 001: every set's receipt is built (`BuildReceipt`) and a usage
// whose receipt `parity_status` is not `supported` is refused (`NotYetSupported`, naming its owner
// task) before any change; the job then fails with each baker `refused`. Today every usage is
// `pending-evidence`, so a session bake bakes, reports its receipts and binds nothing. A publication
// of supported usages would be one transaction through `submit` (the call's own mutation request),
// every set bound or none.
//
// The body's result is the job report (`ReportJson`) plus the receipts' content; a failed bake
// raises its error (`NotYetSupported` for refusals, `ValueError`, or `RuntimeError` with the report
// in its message); a cancelled one raises the pool's cancellation, after recording the commit when
// the publication had committed.

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

#include "bake/job.h"
#include "python/jobs.h"
#include "uzp_core/transaction/transaction.h"

namespace uzp::bake {

/// Runs `call` as the bake's one publication transaction; returns the committed revision, or throws
/// the error that refused or failed it.
using SessionSubmit = std::function<std::int64_t(const std::function<void(core::Edit&)>& call)>;

/// Starts a bake of `texture_sets` (every texture set when empty) with `usages` (each set's enabled
/// bakers when empty) on the open project; see above.
python::JobBody StartSessionBake(const std::vector<std::string>& texture_sets, const std::vector<MeshMapUsage>& usages,
                                 SessionSubmit submit, BakeJobOptions options = {});

}  // namespace uzp::bake
