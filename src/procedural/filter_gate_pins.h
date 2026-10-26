#pragma once

// The compiled pins of the native F gate (`docs/filter-observations-v2.md` section 11, F1-F4): the
// fixed `filter-context-settings-a` request, the approved envelope entry of the registry and the
// single reviewed settings producer. Every pin is built into the binary (`#embed`, decision 147);
// none is read from a caller. The registry file at its run-time locator can still change; admission
// therefore compares its bytes with the pinned ones before and after admission
// (`filter_gate_admission.h`). A changed request, registry or gate source changes
// `FilterGateCodeSha256()`.

#include <expected>
#include <string>
#include <vector>

#include "procedural/filter_observation_import_v2.h"

namespace uzp::procedural {

/// What the gate admits against.
struct FilterGatePins {
    /// The fixed request's bytes as embedded, and its golden id.
    std::string request_bytes;
    std::string golden_id;
    /// The typed canonical hash of the request's `instruction_sequence` (recipe A).
    std::string recipe_sha256;
    /// The request's one input, `plane`, and its pinned SHA-256.
    std::string plane_sha256;
    /// The reviewed envelope registry's bytes as embedded; at run time the registry at its locator
    /// must have exactly these bytes.
    std::string registry_bytes;
    /// The approved envelope: the registry's current entry.
    std::string envelope_id;
    std::string painter_build;
    std::string envelope_sha256;
    std::vector<std::string> equivalent_envelopes;
    /// The reviewed settings producer (`environment.recorder_version`) and the source revision it
    /// was reviewed at (compiled provenance only; never read from a record).
    std::string settings_producer;
    std::string producer_source_revision;
};

/// The pins decoded from the embedded files. Refused (`F_CAPTURE_INVALID`,
/// `F_SETTINGS_REGISTRY_DRIFT`) when the embedded registry does not name the approved envelope
/// as its current entry, or the embedded request is not recipe A with its one plane input.
std::expected<FilterGatePins, ImportRefusal> CompiledFilterGatePins();

/// SHA-256 of the gate's own sources (the pins, admission, settings and trace slices, headers and
/// sources) and the embedded pin files, in that fixed order, each hashed with CRLF read as LF so the
/// value does not depend on the checkout's line endings. It is typed source provenance of what this
/// binary was built from, not a runtime attestation; later gate slices (destination, factory, command)
/// extend the list when they exist.
std::string FilterGateCodeSha256();

}  // namespace uzp::procedural
