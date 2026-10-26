#pragma once

// The internal verified-context transaction component of the V2 Filter observation import
// (decision 363, `docs/filter-observations-v2.md`, rule `paired-scalar-rgb-to-user0-frozen-host-v1`).
// It is NOT a complete importer: it has no runtime entry point that accepts a payload.
//
// - `VerifyHostCapture` verifies the H capture of the host snapshot completely: the paired
//   scalar/RGB receipt, its request, its readback (the bridge's capture predicates), its observed
//   metadata against the stored `/3` metadata, and its exports at native precision against the
//   census raster. Its `capture_context_sha256` is computed from the validated readback, never taken
//   from a caller.
// - `VerifiedFilterContext` (the observed Filter's effect, descriptor, observations and F capture
//   section) has no public constructor: the F gate that would verify a closed F capture protocol
//   does not exist yet, so no real F context can be built. Authored tests reach it through the
//   test-only `FilterImportTestAccess`, declared here and defined only in a test source.
// - `CommitFilterObservation` inserts the Filter and the immutable V2 entry in one store `Submit`
//   (whose callback holds no store mutex): it checks the target revision and projection, the
//   frozen-host domain and the host request, builds the context from one census, runs the native
//   proof (every count zero), rechecks the owning revision, the projection and the census after the
//   proof, checks the namespace structurally and requires `ObservedFilter` before the commit. A
//   refusal leaves no revision, operation record or stored change.

#include <cstdint>
#include <expected>
#include <functional>
#include <optional>
#include <string>
#include <string_view>

#include "evaluator/templates.h"
#include "store/project_store.h"
#include "uzp_core/document/document.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/operation/operation.h"
#include "uzp_core/types/project.h"

namespace uzp::procedural {

/// The refusal reasons of the migration rule.
inline constexpr std::string_view kHostCaptureInvalid = "HOST_CAPTURE_INVALID";
inline constexpr std::string_view kHostSourceStateMismatch = "HOST_SOURCE_STATE_MISMATCH";
inline constexpr std::string_view kTargetContextUnrepresentable = "TARGET_CONTEXT_UNREPRESENTABLE";
inline constexpr std::string_view kUnreviewedContextDifference = "UNREVIEWED_CONTEXT_DIFFERENCE";
inline constexpr std::string_view kFrozenRasterNotFixedPoint = "FROZEN_RASTER_NOT_FIXED_POINT";
inline constexpr std::string_view kNativeTransportMismatch = "NATIVE_TRANSPORT_MISMATCH";
inline constexpr std::string_view kStaleProspectiveView = "STALE_PROSPECTIVE_VIEW";

/// Why an import step refused: one reason above and its detail.
struct ImportRefusal {
    std::string reason;
    std::string detail;
};

/// The bytes of an admitted private artifact by SHA-256, or nothing when the transport lacks it.
using ArtifactBytes = std::function<std::optional<std::string>(std::string_view sha256)>;

/// The verified H capture of the host snapshot.
class VerifiedHostMigration {
public:
    /// The capture/2 `host` section (artifact references only).
    [[nodiscard]] const core::json::Object& HostCapture() const { return host_capture_; }
    /// The typed canonical hash of the validated H readback.
    [[nodiscard]] const std::string& CaptureContextSha256() const { return capture_context_sha256_; }
    /// The host snapshot's signature key.
    [[nodiscard]] const std::string& SignatureSha256() const { return signature_sha256_; }
    /// What the verification bound the capture to, and the commit rechecks: the store uuid, the
    /// snapshot's plane, version, chunk root, raster SHA-256 and byte count, and the typed hash of
    /// its `/3` metadata.
    [[nodiscard]] core::json::Object Identity() const;
    [[nodiscard]] const std::string& ProjectUuid() const { return project_uuid_; }

private:
    VerifiedHostMigration() = default;
    friend std::expected<VerifiedHostMigration, ImportRefusal> VerifyHostCapture(store::ProjectStore&, const core::Project&,
                                                                                const core::json::Object&,
                                                                                const ArtifactBytes&);
    core::json::Object host_capture_;
    std::string capture_context_sha256_;
    std::string signature_sha256_;
    std::string project_uuid_;
    std::int64_t plane_id_ = 0;
    std::int64_t version_id_ = 0;
    std::string chunk_root_;
    std::string raster_sha256_;
    std::int64_t byte_count_ = 0;
    std::string metadata_sha256_;
};

/// Verifies the capture/2 `host` section `host_capture` against `project`, the PROSPECTIVE
/// destination (the base with the Filter to insert, since the frozen-host domain holds that Filter;
/// its host snapshot recorded in `store`), resolving every artifact through `artifacts` by hash and
/// size: the closed receipt `uzpainter/procedural-capture/1` exactly as the snapshot bridge writes
/// it (`python/uzpainter_snapshot/bridge.py` `record` and `main`: recorder pins, the Legacy
/// host identity with no project open, two `Success` exports of the bridge's raw export
/// configuration into `export1` and `export2`, and `files`, the SHA-256 of each round's
/// `user0.exr` and `user1.exr`, which must name the scalar and RGB artifacts in round order; this
/// store's uuid; the stored signature, which is the host's current request; the observed resource
/// naming the signature's pin), the request (the exact versioned resource and scalar overrides the
/// readback's effective parameters hold, compared as the bridge compares Python values), the
/// readback (the bridge's isolated paired User0 L32F / User1 RGB32F capture predicates), the
/// observed metadata equal to the stored `/3` metadata, and the two scalar and two RGB exports
/// decoded at native precision (scalar rounds, every RGB component and the census raster
/// bit-equal). The H environment and its binding must both be null: no supported representation
/// of historical H environment evidence exists, so a present one is refused, never accepted as an
/// arbitrary blob.
std::expected<VerifiedHostMigration, ImportRefusal> VerifyHostCapture(store::ProjectStore& store, const core::Project& project,
                                                                     const core::json::Object& host_capture,
                                                                     const ArtifactBytes& artifacts);

struct FilterImportTestAccess;

namespace detail {
/// The bridge's comparison of a requested override with an effective parameter, as Python compares
/// its values: integers exactly (a boolean is its integer), an integer and a float only when the
/// float is that exact integer, floats and strings by value.
[[nodiscard]] bool BridgeScalarEquals(const core::json::Value& requested, const core::json::Value& effective);
}  // namespace detail

/// A verified F context: the observed Filter effect to insert (its reference already the
/// descriptor's pin), the Filter descriptor, the three observations and the capture/2 `filter`
/// section. No public constructor (see above).
class VerifiedFilterContext {
public:
    [[nodiscard]] const core::Effect& Effect() const { return effect_; }
    [[nodiscard]] const core::json::Object& Descriptor() const { return descriptor_; }
    [[nodiscard]] const core::json::Object& Observations() const { return observations_; }
    [[nodiscard]] const core::json::Object& FilterCapture() const { return filter_capture_; }

private:
    VerifiedFilterContext() = default;
    friend struct FilterImportTestAccess;
    core::Effect effect_;
    core::json::Object descriptor_;
    core::json::Object observations_;
    core::json::Object filter_capture_;
};

/// The destination the transaction must find unchanged: the store uuid, the owning Document's
/// revision, the typed hash of its projection without the observation namespace, and the id the
/// Filter receives (the base's next id).
struct ImportTarget {
    std::string project_uuid;
    std::int64_t revision = 0;
    std::string base_projection_sha256;
    core::Id filter_uid = core::kNoId;
};

/// After the native proof: the store's current revision and `document`'s still `revision`, the
/// projection (without the namespace) still `context.project`, and a fresh census still
/// `context.inventory`; otherwise `STALE_PROSPECTIVE_VIEW`.
std::optional<ImportRefusal> RecheckProspectiveView(store::ProjectStore& store, const core::Document& document,
                                                    const core::Project& project, const core::json::Object& context,
                                                    std::int64_t revision);

/// The store request of a commit: its arguments are every validated input (the target with its
/// expected revision, the verified H capture and identity, the Filter effect, descriptor,
/// observations and F capture section), and its idempotency key is their typed canonical hash, so
/// only the exact same import at the same revision replays a stored outcome.
core::MutationRequest FilterObservationCommitRequest(const VerifiedHostMigration& host, const VerifiedFilterContext& filter,
                                                     const ImportTarget& target);

/// Inserts the verified Filter and its immutable V2 entry in one `Submit` (above); returns the
/// entry key. The verified H capture must still describe this store and the prospective census
/// and proof (its uuid, snapshot plane, version, root, raster and metadata), else
/// `HOST_SOURCE_STATE_MISMATCH`.
std::expected<std::string, ImportRefusal> CommitFilterObservation(store::ProjectStore& store, core::Document& document,
                                                                  const VerifiedHostMigration& host,
                                                                  const VerifiedFilterContext& filter,
                                                                  const ImportTarget& target,
                                                                  const evaluator::TemplateLibrary& templates);

}  // namespace uzp::procedural
