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

namespace uzp::store {

/// The manifest's top-level key of the namespace, and the schemas of its parts.
inline constexpr std::string_view kFilterObservationsKey = "filter_source_observations";
inline constexpr std::string_view kFilterObservationsSchema = "uzpainter/filter-source-observations/1";
inline constexpr std::string_view kObservationDescriptorSchema = "uzpainter/filter-observation-descriptor/1";
inline constexpr std::string_view kObservationEntrySchema = "uzpainter/filter-source-observation/1";
inline constexpr std::string_view kObservationContextSchema = "uzpainter/filter-observation-context/1";

/// The typed canonical hash of a closed body: the SHA-256 of its canonical JSON.
std::string ObservationKey(const core::json::Value& body);
/// The reserved pin of the descriptor stored under `descriptor_key`.
std::string ObservationPin(std::string_view descriptor_key);

/// Why the namespace value `member` may not stand in the manifest of project `project_uuid`, or
/// empty: a member is missing, unknown or of the wrong type; a key is not its body's hash; an
/// entry was recorded for another project; or a link (binding, host binding, descriptor, pin)
/// does not resolve inside the namespace. Structural only (see above).
std::string FilterObservationsProblem(const core::json::Value& member, std::string_view project_uuid);
/// That problem for the namespace `project` holds; empty when it holds none.
std::string ProjectFilterObservationsProblem(const core::Project& project, std::string_view project_uuid);
/// The commit check: throws `StoreError(conflict)` with the problem, so a corrupt or foreign
/// namespace is never committed. A stale entry commits.
void CheckFilterObservations(const core::Project& project, std::string_view project_uuid);

}  // namespace uzp::store
