#pragma once

// Integrity of a `.uzp` file (`docs/architecture/09-project-file-format.md` §1, §4): foreign
// keys, the `manifest_sha256` of every revision, the SHA-256 of every stored blob, the locators
// of a non-portable project and the raster planes (`plane_integrity.h`). A blob or manifest whose
// hash does not match is reported as corrupt with the nodes that bind it; its bytes are never
// used.

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "store/container.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/types/ids.h"

namespace uzp::store {

/// A place in a manifest that names a content hash: the id (`id` or `uid`) of the nearest
/// enclosing object that has one, if any, and the JSON path of the value.
struct AffectedNode {
    std::optional<core::Id> id;
    std::string path;

    bool operator==(const AffectedNode&) const = default;
};

/// Every place of `manifest` whose value is the string `sha256`, in document order.
std::vector<AffectedNode> NodesBinding(const core::json::Value& manifest, std::string_view sha256);

struct CorruptItem {
    std::string kind;  // "blob", "manifest", "operation", "foreign_key", "sqlite" or "plane"
    std::string key;   // the blob's SHA-256, the revision, the idempotency key, the table or the plane_id
    std::string detail;
    std::vector<AffectedNode> nodes;  // blobs: the nodes of the current manifest that bind it
};

struct MissingDependency {
    std::string sha256;
    std::string path;
    std::string reason;  // "absent" or "changed" (the file no longer hashes to `sha256`)
    std::vector<AffectedNode> nodes;
};

/// A `plane` or `plane_version` row no retained manifest reaches: `compact` collects it. Not a
/// failure.
struct CollectableRow {
    std::string table;  // "plane" or "plane_version"
    std::int64_t key = 0;

    bool operator==(const CollectableRow&) const = default;
};

struct IntegrityReport {
    std::vector<CorruptItem> corrupt;
    std::vector<MissingDependency> missing;
    std::vector<CollectableRow> collectable;

    bool ok() const { return corrupt.empty() && missing.empty(); }
    /// `{collectable: [{table, key}], corrupt: [{kind, key, detail, nodes}], missing: [{sha256,
    /// path, reason, nodes}]}`.
    core::json::Value ToJson() const;
};

/// A read that met corrupt content; `item()` names it and the nodes that bind it.
class CorruptionError : public StoreError {
public:
    explicit CorruptionError(CorruptItem item);
    const CorruptItem& item() const { return item_; }

private:
    CorruptItem item_;
};

enum class VerifyLevel {
    /// Foreign keys, every retained manifest against its `manifest_sha256`, every operation row
    /// (its project and outcome), the locators of a non-portable project (existence and
    /// SHA-256), and the plane rules of `plane_integrity.h` with the bytes of the chunks the
    /// current manifest binds.
    standard,
    /// `standard` plus the SHA-256 of every stored blob, the chunks every retained manifest binds
    /// included (`uzpainter inspect --verify`).
    full,
};

/// The manifest text of `revision`, verified against its `manifest_sha256`. Throws
/// `CorruptionError` (kind `manifest`) when the row is missing, does not decompress or does not
/// hash to it.
std::string ReadManifestText(Container& container, std::int64_t revision);

/// Checks `container`; `current_manifest` names the nodes affected by a corrupt blob or a missing
/// dependency. Never throws for corrupt content (it is reported); throws `StoreError` when the
/// file cannot be read at all.
IntegrityReport CheckIntegrity(Container& container, const core::json::Value& current_manifest, VerifyLevel level);

}  // namespace uzp::store
