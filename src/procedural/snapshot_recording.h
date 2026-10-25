#pragma once

// Local recording boundary for project-private procedural snapshots (decision 327).

#include "procedural/seam.h"
#include "store/project_store.h"

#include <optional>
#include <string>
#include <vector>

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
/// The signature must carry EvaluationSettings(project), including the mesh and import hashes.
/// A mismatch or a malformed export fails before submission; no request-provided fingerprint
/// substitutes for the document's identity. This boundary does not certify source isolation.
/// `metadata`, when given, is stored as the entry's `source_metadata` (store/snapshots.h) and is
/// checked before submission. Its canonical SHA-256 then joins the operation's arguments and
/// idempotency key, so a recording with other metadata never replays an earlier one; without it,
/// the key and arguments are those of a recording without metadata.
std::expected<core::RequestOutcome, std::string> RecordSnapshotExport(
    store::ProjectStore& store, core::Document& document, const ProceduralRequest& request,
    std::string_view exportFile, std::string_view projectUuid, int64_t revision,
    const std::optional<store::SourceMetadata>& metadata = std::nullopt);

/// The `image_outputs` a capture receipt (`uzpainter/procedural-capture/1`) observed: its
/// `readback.sources` must be exactly the two paired sources, each naming `resource`, with
/// `active_output` equal to `request.outputId` and `outputs` exactly `[request.outputId]` (the
/// capture domain is a singleton output source; stored metadata in general may list more).
/// Nothing else of the receipt or of the request is used, and nothing is inferred.
std::expected<std::vector<std::string>, std::string> ReceiptImageOutputs(
    const core::json::Value& receipt, std::string_view resource, const ProceduralRequest& request);

/// Everything a capture receipt observed about its source (store/snapshots.h `source_metadata`):
/// `ReceiptImageOutputs`'s checks, plus the two paired sources being identical and their
/// `parameters` equal to the request's effective parameters, key for key and type for type. The
/// sources' `inputs` give `image_inputs`, and `presets` and `properties`, when the bridge observed
/// them, give the `/2` members, validated by `store::ParseSourceMetadata` (an absent member stays
/// absent). No value is inferred, and the property names need not equal the parameter names.
std::expected<store::SourceMetadata, std::string> ReceiptSourceMetadata(
    const core::json::Value& receipt, std::string_view resource, const ProceduralRequest& request);

}  // namespace uzp::procedural
