#pragma once

// Atomic publication of a bake per `(texture set, input revision)` (phase3.3_baker-evidence-
// publication, `docs/architecture/06-baking.md` §4, `03-project-model.md` §4; decision 347).
//
// `PublishBake` runs one document transaction. Inside it, every check comes first: the document is
// still at the revision the bake read (`BakeRequest::input_revision` is its decimal revision), the
// texture set exists, its resolution is the bake's output size, Normal's format and tangent space
// are the project's, the result is not diagnostic and every enabled usage has a map a binding can
// hold. Then it stages each map's file and the receipt through `StageResource` (the project store's
// `StageResource`, which stores staged bytes only when the commit references them), adds their
// resource entries and binds every enabled usage with `baked {...}` provenance whose `extra` names
// the receipt. A refusal, a failure or a commit sink that throws commits nothing: no usage is bound
// and the revision is unchanged.
//
// Bound today: AO (L16) and Normal (RGB16), the usages whose 16-bit codes the baker writes. The float
// maps (WorldSpaceNormal, Position, Opacity, Height) have no established channel format (decisions
// 337 and 341), ID has no colour map and Thickness no per-texel value: a bake with any of them is
// refused before mutation, naming its owner task. This is native only: Python and MCP do not
// reach it, and a binding's `extra.parity_status` is the baker's (`pending-evidence`).

#include <cstdint>
#include <functional>
#include <optional>
#include <set>
#include <string>

#include "bake/bake_receipt.h"
#include "uzp_core/transaction/transaction.h"

namespace uzp::bake {

/// Stages `bytes` (of type `mime`) for the running transaction; returns their SHA-256.
using StageResource = std::function<std::string(std::string bytes, std::string mime)>;

struct PublicationContext {
    std::uint64_t job_id = 0;
    std::string build_hash;
    /// SHA-256 of every resource the bake read (the receipt header's `resource_hashes`).
    std::set<std::string> input_resources;
    /// RFC 3339 UTC time recorded on the new resource entries.
    std::string published_at;
};

struct PublicationOutcome {
    core::RequestOutcome outcome;
    /// Set when the transaction committed.
    std::optional<BakeReceipt> receipt;
    std::string receipt_sha256;
};

/// The ChannelFormat a binding of `usage` declares; raises `uzp::core::NotYetSupported` (naming the
/// owner task) for a usage whose map no binding can hold yet.
core::ChannelFormat PublishedFormat(MeshMapUsage usage);

/// Publishes `result` (a `Success` bake of `request` on a baker with `caps`) into `document`.
PublicationOutcome PublishBake(core::Document& document, core::MutationRequest mutation, const BakeRequest& request,
                               const BakeResult& result, const Capabilities& caps, const PublicationContext& context,
                               const StageResource& stage);

}  // namespace uzp::bake
