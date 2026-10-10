#pragma once

// The result-record header carried by every export, capture, bake and recipe-dump receipt
// (ARC-11; `docs/architecture/03-project-model.md` §5): the revision the result was computed
// from, the profiles and app version that computed it, and the SHA-256 of every resource it
// read. Receipts embed the header's JSON object under their own keys.

#include <cstdint>
#include <set>
#include <string>

#include "uzp_core/manifest/json.h"

namespace uzp::core {

struct ResultRecordHeader {
    std::int64_t revision = 0;
    std::string evaluator_profile;
    std::string compat_profile;
    std::string app_version;
    std::set<std::string> resource_hashes;  // sorted, unique

    bool operator==(const ResultRecordHeader&) const = default;
};

/// `{revision, evaluator_profile, compat_profile, app_version, resource_hashes}`.
json::Object HeaderToJson(const ResultRecordHeader& header);

/// Reads the header keys of a receipt object (other keys belong to the receipt). Throws
/// `ManifestError` on a missing or mistyped key, a negative revision, an empty profile or
/// version, or a hash that is not lower-case SHA-256.
ResultRecordHeader HeaderFromJson(const json::Object& receipt);

}  // namespace uzp::core
