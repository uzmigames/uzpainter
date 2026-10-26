#pragma once

// Filter source observations (decision 362): a project-private namespace of immutable
// observations a recording made of one Filter effect, for a test-only diagnostic fixture. The
// manifest's top-level `filter_source_observations` object is closed:
//
//     "filter_source_observations": {
//         "schema": "uzpainter/filter-source-observations/1",
//         "descriptors": {"<descriptor sha256>": {schema, role, resource_id, parameters}},
//         "entries": {"<entry sha256>": {schema, project_uuid, role, host_descriptor,
//                     filter_descriptor, binding, context, context_sha256, capture, observations}},
//         "host_bindings": {"<host uid>": {"channel": "<channel>", "descriptor": "<sha256>"}},
//         "bindings": {"<filter uid>": "<entry sha256>"}}
//
// Every key is the typed canonical hash of its body (SHA-256 of its canonical JSON, which keeps
// int versus double and the sign of zero). A descriptor's pin is
// `uzasset://observation/<descriptor sha256>@1` (core/resource_url.h), a reserved family no
// procedural backend executes.
//
// This header checks the namespace's STRUCTURE only: closed members and types, recomputed keys,
// the project UUID and the internal links (bindings to entries, entries to descriptors, the
// references' pins to their descriptors). It never compares an entry with the project's current
// nodes, channels, positions or context: a permitted edit can make an entry stale, and a stale
// entry stays committable and savable (its getters refuse until the context matches again).

#include <string>
#include <string_view>

#include "uzp_core/manifest/json.h"
#include "uzp_core/types/project.h"
#include "uzp_core/types/resource_url.h"

namespace uzp::store {

/// The manifest's top-level key of the namespace (core/resource_url.h), and the schemas of its parts.
using core::kFilterObservationsKey;
inline constexpr std::string_view kFilterObservationsSchema = "uzpainter/filter-source-observations/1";
inline constexpr std::string_view kObservationDescriptorSchema = "uzpainter/filter-observation-descriptor/1";
inline constexpr std::string_view kObservationEntrySchema = "uzpainter/filter-source-observation/1";
inline constexpr std::string_view kObservationContextSchema = "uzpainter/filter-observation-context/1";

// Version 2 (decision 363, `docs/filter-observations-v2.md`): one Filter observed over a real
// snapshot-backed host (`paired-scalar-rgb-to-user0-frozen-host-v1`). The namespace's exact
// `schema` selects the version; a project holds one, and a body of one version is never read as
// the other. V2 has `schema, descriptors, entries, bindings` (no host bindings: the host is the
// real snapshot reference), Filter descriptors only, and entries with exactly `schema,
// project_uuid, role, host_snapshot, filter_descriptor, binding, context, context_sha256, capture,
// observations`, whose context holds the historical projection and its census
// (observation_inventory.h) and whose capture holds the H and F provenance, the migration and its
// native proof record. The V2 check is structural and historical: it validates the entry against
// the projection and census it records, never against the current project.
inline constexpr std::string_view kFilterObservationsSchemaV2 = "uzpainter/filter-source-observations/2";
inline constexpr std::string_view kObservationEntrySchemaV2 = "uzpainter/filter-source-observation/2";
inline constexpr std::string_view kObservationContextSchemaV2 = "uzpainter/filter-observation-context/2";
inline constexpr std::string_view kObservationCaptureSchemaV2 = "uzpainter/filter-observation-capture/2";
inline constexpr std::string_view kFrozenHostProofSchema = "uzpainter/filter-frozen-host-native-proof/1";
inline constexpr std::string_view kFrozenHostDomainSchema = "uzpainter/filter-frozen-host-domain/1";
inline constexpr std::string_view kFrozenHostRule = "paired-scalar-rgb-to-user0-frozen-host-v1";
/// The recorder's authored full-UV plane (`parity/fixtures/meshes/plane.obj`), the same literal as
/// the snapshot source provider's admission (procedural/snapshot_source.cpp).
inline constexpr std::string_view kFrozenHostPlaneMesh = "7d3c5f616c2abf4b06050434fa943d19dcb15ec998245a211d1d4ca7e95197fe";

/// The public domain record of the frozen-host rule, whose typed canonical hash a native proof
/// names as `domain_sha256`.
core::json::Value FrozenHostDomain();

/// The nodes of a project inside the V2 frozen-host domain: one texture set and stack, the root
/// layers `[host Fill, initial empty Paint]` and the host's one content Filter.
struct FrozenHostNodes {
    const core::TextureSet* set = nullptr;
    const core::Stack* stack = nullptr;
    const core::Layer* host = nullptr;
    const core::Layer* paint = nullptr;
    const core::Effect* filter = nullptr;
    const core::ProceduralRef* host_ref = nullptr;
};

/// Why `project` is outside the V2 frozen-host domain, or empty with `nodes` filled: one full-UV
/// 128 x 128 set on the authored plane mesh (its only resource, no external graph or display
/// resource), one stack, Legacy colour management, OpenGL, PerVertex, Default workflow, unit scale
/// 1; root layers exactly `[host Fill, empty Paint]` (`core::IsEmptyPaintLayer`, no mask, child or
/// instance); a visible host Fill without mask, preset, child, instance or active geometry mask,
/// Normal at opacity 1 on User0, one Split procedural source on User0 (L32F, the only active
/// channel) whose reference is a snapshot pin with one User0 output, no preset, image input or
/// mask output and decision 361 parameters, an identity UV or Fill projection with BilinearHQ and
/// Repeat and no symmetry; and the host's only content effect a Filter whose reference is an
/// observation pin, with a nonempty set of active stack channels and each channel blending of a
/// stack channel at a finite opacity in [0, 1]. Pure: the project only.
std::string FrozenHostDomainProblem(const core::Project& project, FrozenHostNodes& nodes);

/// The typed canonical hash of a closed body: the SHA-256 of its canonical JSON.
std::string ObservationKey(const core::json::Value& body);
/// The reserved pin of the descriptor stored under `descriptor_key`.
std::string ObservationPin(std::string_view descriptor_key);

/// Why the namespace value `member` may not stand in the manifest of project `project_uuid`, or
/// empty: a member is missing, unknown or of the wrong type; a key is not its body's hash; an
/// entry was recorded for another project; or a link (binding, host binding, descriptor, pin)
/// does not resolve inside the namespace. Structural only (see above). The exact `schema`
/// selects the V1 or the V2 check; any other schema is refused.
std::string FilterObservationsProblem(const core::json::Value& member, std::string_view project_uuid);
/// That problem for the namespace `project` holds; empty when it holds none.
std::string ProjectFilterObservationsProblem(const core::Project& project, std::string_view project_uuid);
/// The commit check: throws `StoreError(conflict)` with the problem, so a corrupt or foreign
/// namespace is never committed. A stale entry commits.
void CheckFilterObservations(const core::Project& project, std::string_view project_uuid);

}  // namespace uzp::store
