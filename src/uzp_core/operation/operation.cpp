#include "uzp_core/operation/operation.h"

#include "uzp_core/manifest/sha256.h"

namespace uzp::core {

std::string RequestHash(std::string_view tool, const json::Object& arguments) {
    const json::Object request{{"arguments", arguments}, {"tool", json::Value(tool)}};
    return Sha256Hex(json::WriteCanonical(request));
}

AdmissionDecision DecideAdmission(const AdmissionInput& input) {
    AdmissionDecision decision;
    decision.current_revision = input.current_revision;
    decision.expected_revision = input.expected_revision;
    if (!input.records_readable) {
        decision.admission = Admission::outcome_unknown;
        return decision;
    }
    if (input.known) {
        decision.record = input.known;
        decision.admission = input.known->request_hash == input.request_hash ? Admission::stored_outcome
                                                                             : Admission::idempotency_conflict;
        return decision;
    }
    if (!input.expected_revision || *input.expected_revision < input.horizon_revision) {
        decision.admission = Admission::outcome_unknown;
    } else if (*input.expected_revision != input.current_revision) {
        decision.admission = Admission::stale_revision;
    } else {
        decision.admission = Admission::execute;
    }
    return decision;
}

}  // namespace uzp::core
