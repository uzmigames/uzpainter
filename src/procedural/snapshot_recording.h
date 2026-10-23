#pragma once

// Local recording boundary for project-private procedural snapshots (decision 327).

#include "procedural/seam.h"
#include "store/project_store.h"

namespace uzp::procedural {

/// Reads the complete signature, refusing missing, extra or unrepresentable fields.
/// The result's SignatureJson is the canonical form of the supplied signature.
std::expected<ProceduralRequest, std::string> RequestFromSignature(const core::json::Value& signature);

/// Decode the actual Painter export at its native precision. No colour conversion,
/// channel extraction, resampling or extrapolation is permitted.
std::expected<std::string, std::string> SnapshotExportTexels(std::string_view file, const RasterSpec& spec);

/// Ingest a captured export into its original project/revision in one store transaction.
/// The Document must belong to and remain attached to this store at its current journal
/// revision. Saving a named checkpoint is not required; no commit sink is replaced here.
/// The signature must carry EvaluationSettings(project), including the actual mesh hash.
/// A mismatch or a malformed export fails before submission; no request-provided fingerprint
/// substitutes for the document's identity. This boundary does not certify source isolation.
std::expected<core::RequestOutcome, std::string> RecordSnapshotExport(
    store::ProjectStore& store, core::Document& document, const ProceduralRequest& request,
    std::string_view exportFile, std::string_view projectUuid, int64_t revision);

}  // namespace uzp::procedural
