#pragma once

// Slice C4 of the native F gate (`docs/filter-observations-v2.md` sections 7 and 11): the pure
// expected destination. From the validated F slices (C1 admission, C2 panels and derived settings,
// C3 trace) and the natively validated H artifacts, it checks the J1-J4 source binding and the
// starting shape of `base` (the H store's current projection), then builds the complete prospective
// project the import must commit: the six section 7 mappings, the approved removal of the facade's
// known constructor defaults on the host Fill, deterministic host, Paint and Filter ids, the Filter
// descriptor and observations from the authenticated F steps 16-18 (never old expected values), and
// the capture/2 `filter` section.
//
// It is pure: no store, no Submit, no file, no private read, no caller target, flag or seal. The
// store binding, the seal and the atomic commit are slice C5. A refusal names one fixed reason
// (`filter_observation_import_v2.h`) and one fixed detail code below, never a value or a path.

#include <expected>
#include <optional>
#include <string>
#include <string_view>

#include "procedural/filter_gate_admission.h"
#include "procedural/filter_gate_settings.h"
#include "procedural/filter_gate_trace.h"
#include "procedural/filter_observation_import_v2.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/types/project.h"

namespace uzp::procedural {

/// The detail codes of slice C4. The reason is `F_CAPTURE_INVALID` for the identity join,
/// `HOST_SOURCE_STATE_MISMATCH` for J1-J4 and `TARGET_CONTEXT_UNREPRESENTABLE` for the destination.
namespace filter_gate {
inline constexpr std::string_view kSliceIdentity = "F_GATE_SLICE_IDENTITY";
inline constexpr std::string_view kJ1SourceIdentity = "J1_SOURCE_IDENTITY";
inline constexpr std::string_view kJ2Pre16Parameters = "J2_PRE16_PARAMETERS";
inline constexpr std::string_view kJ3Pre16State = "J3_PRE16_STATE";
inline constexpr std::string_view kJ3IntWrite = "J3_INT_WRITE";
inline constexpr std::string_view kJ3BoolWrite = "J3_BOOL_WRITE";
inline constexpr std::string_view kJ4Outputs = "J4_OUTPUTS";
inline constexpr std::string_view kStartingShape = "DESTINATION_STARTING_SHAPE";
inline constexpr std::string_view kHostSources = "DESTINATION_HOST_SOURCES";
inline constexpr std::string_view kHostSnapshot = "DESTINATION_HOST_SNAPSHOT";
inline constexpr std::string_view kFContext = "DESTINATION_F_CONTEXT";
inline constexpr std::string_view kObservations = "DESTINATION_FILTER_OBSERVATIONS";
inline constexpr std::string_view kDomain = "DESTINATION_DOMAIN";
}  // namespace filter_gate

/// The expected destination. No public constructor.
class ValidatedFilterDestination {
public:
    /// The base as given, and the complete prospective project: the mapped base with the Filter at
    /// the host's Content index 0, its id allocated after any missing host Fill and empty Paint.
    [[nodiscard]] const core::Project& Base() const { return base_; }
    [[nodiscard]] const core::Project& Prospective() const { return prospective_; }
    /// The Filter effect as inserted (its id the role map's `filter`), the descriptor
    /// (`uzpainter/filter-observation-descriptor/1`), the observations
    /// (`parameters, resource_id, image_outputs`) and the capture/2 `filter` section.
    [[nodiscard]] const core::Effect& FilterEffect() const { return filter_; }
    [[nodiscard]] const core::json::Object& Descriptor() const { return descriptor_; }
    [[nodiscard]] const core::json::Object& Observations() const { return observations_; }
    [[nodiscard]] const core::json::Object& FilterCapture() const { return filter_capture_; }
    /// `{texture_set, stack, host, initial_paint, filter}`, each `{native, f_uid}` (texture set and
    /// stack carry no F uid: `f_uid` null), and `allocated`: the roles whose ids were allocated, in
    /// allocation order.
    [[nodiscard]] const core::json::Object& Roles() const { return roles_; }
    /// The known constructor defaults removed from the host Fill: `{channels, sha256}` (the
    /// channel names in order and the typed hash of the removed sources), or empty channels.
    [[nodiscard]] const core::json::Object& RemovedDefaults() const { return removed_defaults_; }
    /// Typed canonical hashes (`store::ObservationKey`): the base and prospective projections
    /// without the observation namespace, the H identity (`ValidatedHostArtifacts::Identity()`),
    /// and the F evidence (the capture/2 `filter` section with the slices' admission identity).
    [[nodiscard]] const std::string& BaseProjectionSha256() const { return base_projection_sha256_; }
    [[nodiscard]] const std::string& ProspectiveProjectionSha256() const { return prospective_projection_sha256_; }
    [[nodiscard]] const std::string& HostIdentitySha256() const { return host_identity_sha256_; }
    [[nodiscard]] const std::string& FilterEvidenceSha256() const { return filter_evidence_sha256_; }
    /// All of the above that is a hash or an id, for the seal and the report (no value).
    [[nodiscard]] core::json::Object Identity() const;

private:
    ValidatedFilterDestination() = default;
    friend std::expected<ValidatedFilterDestination, ImportRefusal> ExpectedDestination(
        const AdmittedFilterCapture&, const CheckedSettingsPanels&, const ValidatedFilterTrace&,
        const ValidatedFilterSettings&, const ValidatedHostArtifacts&, const core::Project&);
    core::Project base_;
    core::Project prospective_;
    core::Effect filter_;
    core::json::Object descriptor_;
    core::json::Object observations_;
    core::json::Object filter_capture_;
    core::json::Object roles_;
    core::json::Object removed_defaults_;
    std::string base_projection_sha256_;
    std::string prospective_projection_sha256_;
    std::string host_identity_sha256_;
    std::string filter_evidence_sha256_;
};

/// The store-free binding of one admitted capture to the validated H: steps 1 and 2 of
/// `ExpectedDestination` below (slice identity, then J1-J4), with no base, store or mapping. The
/// command runs it before any replay lookup; `ExpectedDestination` runs the same code. Nothing when
/// the binding holds, else the refusal.
std::optional<ImportRefusal> ValidateFilterHostBinding(const AdmittedFilterCapture& capture,
                                                       const CheckedSettingsPanels& panels,
                                                       const ValidatedFilterTrace& trace,
                                                       const ValidatedFilterSettings& settings,
                                                       const ValidatedHostArtifacts& host);

/// The expected destination of one admitted capture on `base`, in this order (a refusal stops):
/// 1. `kSliceIdentity`: the four slices name one admission (typed-equal `AdmissionIdentity()`, equal
///    to `capture.Identity()`) and one record (`OriginalRecordSha256()` equal to the admitted record
///    reference's SHA-256).
/// 2. J1-J4 (`tools/parity/filter_source_binding.py`) against `host.Readback()` and
///    `host.Resource()`: the step-5 resource, the H source identity and every F source frame name one
///    identity; the pre16 parameters of both rounds equal H's, typed; the step 12 int write
///    succeeded, step 14 succeeded or refused with TypeError, and steps 13, 15 and pre16 read one
///    typed map; outputs, inputs (empty), active output and resolution equal H's.
/// 3. `kStartingShape`, `kHostSources`, `kHostSnapshot`: `base` is inside the section 11 starting
///    table, holds H's snapshot entry (signature and /3 metadata), and its host Fill (if any) holds
///    the bind of the H signature plus only the approved known constructor defaults.
/// 4. `kFContext`, `kObservations`: the F set, stack, channels, host, initial Paint and Filter
///    states needed by the mapping are present, unraised and typed-equal in both pre16 frames; the
///    Filter's steps 16-18 observations are complete, equal in both rounds and equal to its pre16
///    source leaves.
/// 5. `kDomain`: the prospective project passes `store::FrozenHostDomainProblem`, and the host's
///    request in its own context (`SnapshotUseContext`, `RequestFor`) is H's signature.
std::expected<ValidatedFilterDestination, ImportRefusal> ExpectedDestination(
    const AdmittedFilterCapture& capture, const CheckedSettingsPanels& panels, const ValidatedFilterTrace& trace,
    const ValidatedFilterSettings& settings, const ValidatedHostArtifacts& host, const core::Project& base);

}  // namespace uzp::procedural
