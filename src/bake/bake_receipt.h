#pragma once

// `BakeReceipt` (phase3.3_baker-evidence-publication, `docs/architecture/06-baking.md` §4, BAK-07,
// ARC-11; decision 347): every field of §4 plus the result-record header `{revision,
// evaluator_profile, compat_profile, app_version, resource_hashes}` of `03-project-model.md` §5.
// Its accounting is `bake_accounting.h`'s, and its map hashes are those of the files
// `EvidenceFiles` writes and publication binds. Parity with Painter is not claimed: the receipt
// carries the baker's `parity_status` (`pending-evidence`).

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "bake/bake_accounting.h"
#include "bake/bake_request.h"
#include "bake/baker.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/types/project.h"
#include "uzp_core/types/receipt.h"

namespace uzp::bake {

/// The version of the CPU baker's output contract, recorded in receipts and bindings.
inline constexpr const char* kBakerVersion = "uzpainter-cpu-baker/1";

/// SHA-256 of a mesh's content (not its name): the counts, then positions, normals and UVs
/// (float bits), indices and corner tangents, little-endian.
std::string MeshContentHash(const BakeMesh& mesh);

/// The texturing mesh hashes of a binding (`03-project-model.md` §4) over the request's low
/// parts in order, each part prefixed by its vertex or corner count: positions, UVs, corner normals
/// (the vertex normal of each corner) and triangulation (the indices).
core::MeshHashes LowMeshHashes(const BakeRequest& request);

/// Every setting of `request` that determines the output (not its meshes, mask or thread count).
core::json::Object SettingsJson(const BakeRequest& request);

/// SHA-256 of the canonical `SettingsJson`.
std::string SettingsHash(const BakeRequest& request);

struct ReceiptTools {
    std::string baker_version = kBakerVersion;
    core::BakerBackend backend = core::BakerBackend::embree;
    std::string backend_version;
    std::string isa_or_gpu;
    std::string build_hash;
};

/// A part's cage: a custom cage's hash, or the distance-based cage's request distances.
struct ReceiptCage {
    std::optional<std::string> sha256;
    float frontal = 0.0f;
    float rear = 0.0f;
    bool relative = false;
};

struct ReceiptPart {
    std::string name;
    std::vector<std::string> high_meshes;  // content hashes of the meshes its rays may hit
    ReceiptCage cage;
};

struct ReceiptInputs {
    std::vector<std::string> low_mesh_hashes;
    std::vector<ReceiptPart> parts;
    std::optional<std::string> hidden_mask;
};

struct ReceiptUsage {
    UsageAccount account;
    /// SHA-256 of the compatible map's and RAW map's files (`EncodeMapFile`); none for Thickness.
    std::optional<std::string> map_sha256;
    std::optional<std::string> raw_sha256;
    core::json::Object effective_normalization;
};

/// What the caller knows that the bake does not: the job, the record header and the build.
struct ReceiptContext {
    std::uint64_t job_id = 0;
    core::ResultRecordHeader header;
    std::string build_hash;
};

struct BakeReceipt {
    std::uint64_t job_id = 0;
    std::string texture_set;
    std::string input_revision;
    JobStatus status = JobStatus::Success;
    std::string settings_hash;
    std::string parity_status;
    ReceiptTools tools;
    ReceiptInputs inputs;
    std::vector<ReceiptUsage> usages;
    core::ResultRecordHeader header;
};

/// The receipt of a `Success` bake of `request`. Raises `uzp::core::ValueError` for an empty build
/// hash and the errors of `AccountUsage`.
BakeReceipt BuildReceipt(const BakeRequest& request, const BakeResult& result, const Capabilities& caps,
                         const ReceiptContext& context);

/// The receipt as JSON: the §4 fields, `parity_status` and the header keys at the top level.
core::json::Object ReceiptJson(const BakeReceipt& receipt);

/// The canonical JSON bytes of `ReceiptJson`.
std::string ReceiptBytes(const BakeReceipt& receipt);

}  // namespace uzp::bake
