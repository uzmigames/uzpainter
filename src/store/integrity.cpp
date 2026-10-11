#include "store/integrity.h"

#include <set>
#include <utility>

#include "store/blobs.h"
#include "store/plane_integrity.h"
#include "uzp_core/manifest/sha256.h"

namespace uzp::store {

using core::json::Array;
using core::json::Object;
using core::json::Value;

namespace {

std::optional<core::Id> OwnId(const Object& object) {
    for (const char* key : {"id", "uid"}) {
        const auto it = object.find(key);
        if (it != object.end() && it->second.IsInt() && std::get<std::int64_t>(it->second.data) > 0) {
            return static_cast<core::Id>(std::get<std::int64_t>(it->second.data));
        }
    }
    return std::nullopt;
}

void Walk(const Value& value, std::string_view sha256, const std::string& path, std::optional<core::Id> owner,
          std::vector<AffectedNode>& out) {
    if (const auto* text = std::get_if<std::string>(&value.data)) {
        if (*text == sha256) out.push_back(AffectedNode{owner, path});
    } else if (const auto* array = std::get_if<Array>(&value.data)) {
        for (std::size_t i = 0; i < array->size(); ++i) {
            Walk((*array)[i], sha256, path + "[" + std::to_string(i) + "]", owner, out);
        }
    } else if (const auto* object = std::get_if<Object>(&value.data)) {
        const std::optional<core::Id> id = OwnId(*object);
        for (const auto& [key, member] : *object) {
            Walk(member, sha256, path.empty() ? key : path + "." + key, id ? id : owner, out);
        }
    }
}

Value NodesJson(const std::vector<AffectedNode>& nodes) {
    Array out;
    for (const AffectedNode& node : nodes) {
        out.push_back(Object{{"id", node.id ? Value(static_cast<std::int64_t>(*node.id)) : Value()}, {"path", node.path}});
    }
    return out;
}

std::string Describe(const CorruptItem& item) {
    std::string text = item.kind + " " + item.key + ": " + item.detail;
    if (!item.nodes.empty()) {
        text += "; bound by";
        for (const AffectedNode& node : item.nodes) {
            text += " " + (node.id ? "node " + std::to_string(*node.id) + " at " : std::string()) + node.path + ",";
        }
        text.pop_back();
    }
    return text;
}

}  // namespace

std::vector<AffectedNode> NodesBinding(const Value& manifest, std::string_view sha256) {
    std::vector<AffectedNode> out;
    Walk(manifest, sha256, "", std::nullopt, out);
    return out;
}

Value IntegrityReport::ToJson() const {
    Array c;
    for (const CorruptItem& item : corrupt) {
        c.push_back(Object{{"kind", item.kind}, {"key", item.key}, {"detail", item.detail}, {"nodes", NodesJson(item.nodes)}});
    }
    Array m;
    for (const MissingDependency& d : missing) {
        m.push_back(Object{{"sha256", d.sha256}, {"path", d.path}, {"reason", d.reason}, {"nodes", NodesJson(d.nodes)}});
    }
    Array r;
    for (const CollectableRow& row : collectable) r.push_back(Object{{"table", row.table}, {"key", row.key}});
    return Object{{"collectable", std::move(r)}, {"corrupt", std::move(c)}, {"missing", std::move(m)}};
}

CorruptionError::CorruptionError(CorruptItem item)
    : StoreError(Code::corrupt, Describe(item)), item_(std::move(item)) {}

std::string ReadManifestText(Container& container, std::int64_t revision) {
    Statement q(container, "SELECT manifest, manifest_sha256 FROM revision WHERE revision = ?");
    q.Bind(1, revision);
    if (!q.Step()) {
        throw CorruptionError(CorruptItem{"manifest", std::to_string(revision), "the revision row is missing", {}});
    }
    std::string text;
    try {
        text = Decompress(q.Blob(0));
    } catch (const StoreError& error) {
        throw CorruptionError(CorruptItem{"manifest", std::to_string(revision), error.what(), {}});
    }
    if (core::Sha256Hex(text) != q.Text(1)) {
        throw CorruptionError(CorruptItem{"manifest", std::to_string(revision),
                                          "the manifest does not hash to its manifest_sha256 " + q.Text(1), {}});
    }
    return text;
}

IntegrityReport CheckIntegrity(Container& container, const Value& current_manifest, VerifyLevel level) {
    IntegrityReport report;

    {
        Statement q(container, "PRAGMA foreign_key_check");
        while (q.Step()) {
            report.corrupt.push_back(CorruptItem{"foreign_key", q.Text(0),
                                                 "row " + std::to_string(q.Int(1)) + " references a missing " +
                                                     q.Text(2) + " row",
                                                 {}});
        }
    }
    {
        Statement q(container, "SELECT revision, manifest, manifest_sha256 FROM revision ORDER BY revision");
        while (q.Step()) {
            const std::string revision = std::to_string(q.Int(0));
            try {
                const std::string text = Decompress(q.Blob(1));
                if (core::Sha256Hex(text) != q.Text(2)) {
                    report.corrupt.push_back(
                        CorruptItem{"manifest", revision, "the manifest does not hash to its manifest_sha256", {}});
                }
            } catch (const StoreError& error) {
                report.corrupt.push_back(CorruptItem{"manifest", revision, error.what(), {}});
            }
        }
    }
    {
        const std::optional<std::string> uuid = container.Meta("project_uuid");
        Statement q(container,
                    "SELECT idempotency_key, outcome, project_uuid FROM operation ORDER BY committed_revision");
        while (q.Step()) {
            try {
                if (q.Text(2) != uuid) {
                    throw StoreError(StoreError::Code::corrupt, "the row belongs to project " + q.Text(2));
                }
                const Value outcome = core::json::Parse(Decompress(q.Blob(1)));
                if (!outcome.IsObject()) throw StoreError(StoreError::Code::corrupt, "the outcome is not an object");
            } catch (const std::exception& error) {
                report.corrupt.push_back(CorruptItem{"operation", q.Text(0), error.what(), {}});
            }
        }
    }
    {
        Statement q(container, "SELECT sha256, path FROM locator ORDER BY sha256");
        while (q.Step()) {
            const std::string sha256 = q.Text(0);
            const std::string path = q.Text(1);
            const auto hash = HashFile(std::filesystem::path(std::u8string(path.begin(), path.end())));
            if (!hash || *hash != sha256) {
                report.missing.push_back(
                    MissingDependency{sha256, path, hash ? "changed" : "absent", NodesBinding(current_manifest, sha256)});
            }
        }
    }
    {
        // Every resource a manifest lists is embedded in `blob` (or, in a non-portable project,
        // held by a locator): the current manifest, and with `full` every stored revision's.
        std::vector<std::pair<std::string, Value>> manifests{{"current", current_manifest}};
        if (level == VerifyLevel::full) {
            Statement q(container, "SELECT revision, manifest FROM revision ORDER BY revision");
            while (q.Step()) {
                try {
                    manifests.emplace_back(std::to_string(q.Int(0)), core::json::Parse(Decompress(q.Blob(1))));
                } catch (const std::exception&) {
                    // reported as a corrupt manifest above
                }
            }
        }
        std::set<std::string, std::less<>> reported;
        for (const auto& [revision, manifest] : manifests) {
            const auto* object = std::get_if<Object>(&manifest.data);
            const auto resources = object ? object->find("resources") : Object::const_iterator{};
            if (object == nullptr || resources == object->end() || !resources->second.IsObject()) continue;
            for (const auto& [sha256, entries] : std::get<Object>(resources->second.data)) {
                if (reported.count(sha256) != 0 || HasBlob(container, sha256) || FindLocator(container, sha256)) continue;
                reported.insert(sha256);
                report.corrupt.push_back(CorruptItem{
                    "blob", sha256,
                    "missing: " + (revision == "current" ? std::string("the current manifest") : "the manifest of revision " + revision) +
                        " lists resource " + sha256 + ", which is neither stored nor located",
                    NodesBinding(current_manifest, sha256)});
            }
        }
    }
    PlaneIntegrity planes = CheckPlaneIntegrity(container, current_manifest, level);
    for (CorruptItem& item : planes.corrupt) report.corrupt.push_back(std::move(item));
    report.collectable = std::move(planes.collectable);
    if (level == VerifyLevel::full) {
        {
            Statement q(container, "PRAGMA quick_check");
            while (q.Step()) {
                if (q.Text(0) != "ok") report.corrupt.push_back(CorruptItem{"sqlite", "quick_check", q.Text(0), {}});
            }
        }
        Statement q(container, "SELECT sha256 FROM blob ORDER BY sha256");
        while (q.Step()) {
            const std::string sha256 = q.Text(0);
            std::vector<AffectedNode> nodes = NodesBinding(current_manifest, sha256);
            // A chunk of a bound plane version was verified above and is reported with its plane.
            if (nodes.empty() && planes.verified_chunks.count(sha256) != 0) continue;
            try {
                ReadBlob(container, sha256);
            } catch (const StoreError& error) {
                if (error.code() != StoreError::Code::corrupt) throw;
                report.corrupt.push_back(CorruptItem{"blob", sha256, error.what(), std::move(nodes)});
            }
        }
    }
    return report;
}

}  // namespace uzp::store
