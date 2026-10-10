#pragma once

// Integrity rules of the raster planes (`docs/architecture/09-project-file-format.md` §1), run by
// `CheckIntegrity` on open and by `uzpainter inspect --verify` (`VerifyLevel::full`):
//
// - every plane binding of a retained manifest is well-formed and names an existing
//   `plane_version` of that `plane_id` with the bound `chunk_root`, and every plane a paint node
//   references is bound;
// - the chunk rows of every bound version hash to its `chunk_root` and lie inside the plane;
// - every chunk hash exists in `blob`, holding the chunk's byte count; its bytes are hashed for
//   the versions the current manifest binds (`standard`) or for every bound version (`full`);
// - `plane` and `plane_version` rows no retained manifest reaches are listed as collectable.
//
// Every failure is a `CorruptItem` of kind `plane` keyed by the `plane_id`, with the owning node
// and the path of its binding. Foreign keys are checked by `CheckIntegrity`
// (`PRAGMA foreign_key_check`; every connection runs with `foreign_keys = ON`).

#include <set>
#include <string>
#include <vector>

#include "store/container.h"
#include "store/integrity.h"
#include "uzp_core/manifest/json.h"

namespace uzp::store {

struct PlaneIntegrity {
    std::vector<CorruptItem> corrupt;
    std::vector<CollectableRow> collectable;
    /// Chunk hashes whose blob bytes were verified here (so the blob pass does not report them
    /// a second time).
    std::set<std::string, std::less<>> verified_chunks;
};

/// Checks the plane rules against every revision row (the retained manifests) and
/// `current_manifest` (the current revision as opened). Manifests that do not verify are skipped
/// (`CheckIntegrity` reports them). Never throws for corrupt content.
PlaneIntegrity CheckPlaneIntegrity(Container& container, const core::json::Value& current_manifest, VerifyLevel level);

}  // namespace uzp::store
