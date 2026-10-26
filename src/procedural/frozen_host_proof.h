#pragma once

// The native proof of the frozen-host migration (decision 363, `docs/filter-observations-v2.md`
// section 8, rule `paired-scalar-rgb-to-user0-frozen-host-v1`): a computation on the actual prospective
// project, never a supplied claim. It derives the host raster B through the real snapshot source
// provider and DAG, evaluates the proof scene (the project with only the observed Filter removed,
// the initial empty Paint kept) on a real CPU tile store, and compares bit for bit:
//
// - every B sample is finite and a fixed point of the User0 read-out R(v) = float32(1 +
//   float32(v - 1)) (`R(B) == B`, for every sample, whatever its range);
// - the bits the actual procedural upload left in the tile equal B;
// - the actual final `ChannelResult` of the full chain equals B.
//
// The evaluation is cold (a fresh tile cache): exactly one procedural upload and no bitmap
// projection must be observed, through a delegating store around a real `CpuTileStore`. The
// project's registered evaluator profile must be the isolated one whose read-out base is 1; no
// other profile is substituted. The run reports its counts and hashes truthfully; acceptance (all
// four counts zero) is the caller's, and the store's structural check refuses a record with a
// nonzero count. Nothing is written, imported or normalized. The project and census rechecks here
// do not assert the owning Document's revision: a caller that inserts an observation (the gated
// importer) checks that revision itself before its atomic insertion.

#include <cstdint>
#include <expected>
#include <string>
#include <string_view>
#include <vector>

#include "evaluator/templates.h"
#include "store/project_store.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/types/project.h"

namespace uzp::procedural {

/// One proof run: the bits it observed and the closed native proof record
/// (`store::kFrozenHostProofSchema`) computed from them.
struct FrozenHostRun {
    std::vector<std::uint32_t> source;    ///< B, as the real provider resolved it for the DAG.
    std::vector<std::uint32_t> uploaded;  ///< The tile's bits read back after the actual upload.
    std::vector<std::uint32_t> final;     ///< The actual final `ChannelResult` bits.
    std::uint64_t uploads = 0;            ///< Procedural uploads observed.
    std::uint64_t projects = 0;           ///< Bitmap projections observed.
    std::int64_t nonfinite = 0;
    std::int64_t fixed_point_mismatches = 0;
    std::int64_t upload_mismatches = 0;
    std::int64_t final_output_mismatches = 0;
    core::json::Object evidence;
};

/// The SHA-256 of this validator's own source (frozen_host_proof.h and .cpp, embedded at build time
/// with `#embed`, decision 147): the record's `validator_code_sha256`.
std::string FrozenHostValidatorCodeSha256();

/// The proof of `prospective` (inside the V2 frozen-host domain, its host snapshot recorded in
/// `store`): the census is read before and after the evaluation and must not change. The record's
/// `validator_code_sha256` is `FrozenHostValidatorCodeSha256()` and its `binary_sha256` the SHA-256
/// of the running executable's file, never a caller's claim. Refused, with the reason, when the
/// project is outside the domain, the host request names no recorded snapshot, the census plane is
/// not one 128 x 128 L32F raster, the profile or read-out base is not the rule's, the DAG is not the
/// one procedural host layer, the upload or the final tile is not observed as one 128 x 128 L32F
/// tile, or the census changed during the run.
std::expected<FrozenHostRun, std::string> RunFrozenHostProof(store::ProjectStore& store, const core::Project& prospective,
                                                             const evaluator::TemplateLibrary& templates);

/// The User0 read-out of the rule, R(v) = float32(1 + float32(v - 1)), on bits.
std::uint32_t FrozenHostReadout(std::uint32_t bits);

}  // namespace uzp::procedural
