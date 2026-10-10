#include "uzp_core/types/receipt.h"

#include "uzp_core/manifest/object_reader.h"
#include "uzp_core/manifest/sha256.h"

namespace uzp::core {

using namespace manifest_detail;

json::Object HeaderToJson(const ResultRecordHeader& header) {
    json::Array hashes;
    for (const std::string& hash : header.resource_hashes) hashes.emplace_back(hash);
    return json::Object{
        {"revision", json::Value(header.revision)},
        {"evaluator_profile", json::Value(header.evaluator_profile)},
        {"compat_profile", json::Value(header.compat_profile)},
        {"app_version", json::Value(header.app_version)},
        {"resource_hashes", json::Value(std::move(hashes))},
    };
}

ResultRecordHeader HeaderFromJson(const json::Object& receipt) {
    const json::Value value(receipt);
    ObjectReader reader(value, "receipt");
    ResultRecordHeader header;
    header.revision = reader.Int("revision");
    if (header.revision < 0) Fail(reader.Path("revision"), "a revision is not negative");
    for (const auto* key : {"evaluator_profile", "compat_profile", "app_version"}) {
        if (reader.String(key).empty()) Fail(reader.Path(key), "must not be empty");
    }
    header.evaluator_profile = reader.String("evaluator_profile");
    header.compat_profile = reader.String("compat_profile");
    header.app_version = reader.String("app_version");
    const json::Array& hashes = reader.Array("resource_hashes");
    for (const json::Value& item : hashes) {
        const std::string& hash = AsString(item, reader.Path("resource_hashes"));
        if (!IsSha256Hex(hash)) Fail(reader.Path("resource_hashes"), "'" + hash + "' is not a lower-case SHA-256");
        if (!header.resource_hashes.insert(hash).second) Fail(reader.Path("resource_hashes"), "'" + hash + "' is listed twice");
    }
    return header;
}

}  // namespace uzp::core
