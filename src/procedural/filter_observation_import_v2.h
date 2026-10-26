#pragma once

// The internal verified-context transaction component of the V2 Filter observation import
// (decision 363, `docs/filter-observations-v2.md`, rule `paired-scalar-rgb-to-user0-frozen-host-v1`).
// It is NOT a complete importer: it has no runtime entry point that accepts a payload.
//
// - `ValidateHostCaptureArtifacts` validates the H artifacts on their own (no store, target or F):
//   the paired scalar/RGB receipt, the request its signature names, its request artifact, its
//   readback (the bridge's capture predicates), its `/3` metadata and its exports at native
//   precision. Its `capture_context_sha256` is computed from the validated readback, never taken
//   from a caller.
// - `VerifyHostCapture` reuses that result and binds it to the destination: the owning store's
//   uuid, the stored host snapshot's signature and `/3` metadata, and the census raster.
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
#include "procedural/seam.h"
#include "store/project_store.h"
#include "store/snapshots.h"
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

/// The H artifacts of a capture/2 `host` section, validated on their own (no store, target or F):
/// owning copies of what the original receipt recorded and the decoded scalar raster.
class ValidatedHostArtifacts {
public:
    /// The capture/2 `host` section (artifact references only).
    [[nodiscard]] const core::json::Object& HostCapture() const { return host_capture_; }
    /// The receipt's typed signature, readback and resource, as recorded.
    [[nodiscard]] const core::json::Value& Signature() const { return signature_; }
    [[nodiscard]] const core::json::Value& Readback() const { return readback_; }
    [[nodiscard]] const std::string& Resource() const { return resource_; }
    /// The request the receipt's signature names (`RequestFromSignature`).
    [[nodiscard]] const ProceduralRequest& Request() const { return request_; }
    /// The `/3` source metadata the receipt observed (`ReceiptSourceMetadata`).
    [[nodiscard]] const store::SourceMetadata& Metadata() const { return metadata_; }
    /// The scalar raster: 128x128 finite float32 texels, every export round and RGB component
    /// bit-equal to it.
    [[nodiscard]] const std::string& ScalarTexels() const { return scalar_texels_; }
    [[nodiscard]] const std::string& ScalarSha256() const { return scalar_sha256_; }
    /// The project and revision the receipt was recorded for (not checked against any store).
    [[nodiscard]] const std::string& CapturedProjectUuid() const { return captured_project_uuid_; }
    [[nodiscard]] std::int64_t CapturedRevision() const { return captured_revision_; }
    /// The typed canonical hash of the validated readback.
    [[nodiscard]] const std::string& CaptureContextSha256() const { return capture_context_sha256_; }
    /// What the validation computed: the captured project and revision, the signature key, the
    /// scalar raster hash, the typed metadata hash and the readback hash.
    [[nodiscard]] core::json::Object Identity() const;

private:
    ValidatedHostArtifacts() = default;
    friend std::expected<ValidatedHostArtifacts, ImportRefusal> ValidateHostCaptureArtifacts(const core::json::Object&,
                                                                                            const ArtifactBytes&);
    core::json::Object host_capture_;
    core::json::Value signature_;
    core::json::Value readback_;
    std::string resource_;
    ProceduralRequest request_;
    store::SourceMetadata metadata_;
    std::string scalar_texels_;
    std::string scalar_sha256_;
    std::string captured_project_uuid_;
    std::int64_t captured_revision_ = 0;
    std::string capture_context_sha256_;
};

/// Validates the capture/2 `host` section `host_capture` and the artifacts it names on their own,
/// with no store, target or F context: the closed section and references (resolved through
/// `artifacts` by hash and size), the closed receipt `uzpainter/procedural-capture/1` exactly as the
/// snapshot bridge writes it (schema, a nonempty project uuid, a nonnegative revision, recorder
/// pins, the Legacy identity with no project open, the two raw export rounds and `files` naming
/// the scalar and RGB artifacts in round order), the request derived from the receipt's signature
/// (`RequestFromSignature`) inside the original H domain (the snapshot pin of the observed
/// resource, one 128-square raw float32 channel, no preset or inputs, one quad UV tile, and the
/// seed the bridge derives: the observed integer `$randomseed`, or 0 when it is absent), the
/// request artifact (the exact versioned resource and scalar overrides), the readback (the
/// bridge's capture predicates), its `/3` metadata (`ReceiptSourceMetadata`), and the four exports
/// decoded at native precision: both rounds equal, every RGB component equal to the scalar, every
/// texel finite. The H environment and its binding must both be null: no supported representation
/// of historical H environment evidence exists, so a present one is refused, never accepted as an
/// arbitrary blob. Nothing a caller computed is accepted in place of these checks.
std::expected<ValidatedHostArtifacts, ImportRefusal> ValidateHostCaptureArtifacts(const core::json::Object& host_capture,
                                                                                const ArtifactBytes& artifacts);

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
/// its host snapshot recorded in `store`): the target's frozen-host domain and host request, its
/// recorded snapshot with `/3` metadata and one census plane, then `ValidateHostCaptureArtifacts`,
/// then the receipt recorded for this store's uuid, its signature equal to the stored snapshot's and
/// to the host's current request (the observed resource naming that signature's pin), its metadata
/// equal to the stored `/3` metadata and its scalar raster equal to the census raster.
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
