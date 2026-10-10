#include "store/plane_integrity.h"

#include <map>
#include <optional>
#include <tuple>
#include <utility>

#include "store/planes.h"
#include "uzp_core/manifest/sha256.h"

namespace uzp::store {

using core::Id;
using core::json::Value;

namespace {

/// Where a version is bound: the nodes of its latest binding, and whether the current manifest
/// binds it.
struct Use {
    std::vector<AffectedNode> nodes;
    bool current = false;
};

using VersionKey = std::tuple<Id, std::int64_t, std::string>;  // plane, version, bound chunk_root

class Checker {
public:
    Checker(Container& container, VerifyLevel level) : container_(container), level_(level) {}

    void Scan(const Value& manifest, bool current) {
        for (const ManifestBinding& binding : ManifestPlaneBindings(manifest)) {
            std::vector<AffectedNode> nodes{AffectedNode{binding.owner, binding.path}};
            if (!binding.version) {
                Report(binding.plane_id, "malformed binding: " + binding.error, std::move(nodes));
                continue;
            }
            Use& use = bound_[VersionKey{binding.plane_id, binding.version->version_id, binding.version->chunk_root}];
            use.nodes = std::move(nodes);
            use.current = use.current || current;
        }
        for (const PlaneReference& reference : ManifestPlaneReferences(manifest)) {
            if (!reference.bound) {
                Report(reference.plane_id, "the plane has no content binding",
                       {AffectedNode{reference.owner, reference.path}});
            }
        }
    }

    PlaneIntegrity Finish() {
        std::set<std::int64_t> versions;
        std::set<Id> planes;
        for (const auto& [key, use] : bound_) {
            const auto& [plane_id, version_id, root] = key;
            versions.insert(version_id);
            planes.insert(plane_id);
            CheckVersion(plane_id, version_id, root, use);
        }
        {
            Statement q(container_, "SELECT version_id FROM plane_version ORDER BY version_id");
            while (q.Step()) {
                if (versions.count(q.Int(0)) == 0) out_.collectable.push_back(CollectableRow{"plane_version", q.Int(0)});
            }
        }
        {
            Statement q(container_, "SELECT plane_id FROM plane ORDER BY plane_id");
            while (q.Step()) {
                if (planes.count(static_cast<Id>(q.Int(0))) == 0) out_.collectable.push_back(CollectableRow{"plane", q.Int(0)});
            }
        }
        return std::move(out_);
    }

private:
    void Report(Id plane_id, std::string detail, std::vector<AffectedNode> nodes) {
        if (!reported_.insert(std::to_string(plane_id) + "\n" + detail).second) return;
        out_.corrupt.push_back(CorruptItem{"plane", std::to_string(plane_id), std::move(detail), std::move(nodes)});
    }

    void CheckVersion(Id plane_id, std::int64_t version_id, const std::string& root, const Use& use) {
        const std::string version = "plane_version " + std::to_string(version_id);
        std::optional<PlaneRow> row;
        try {
            row = ReadPlaneRow(container_, plane_id);
            if (!row) Report(plane_id, "the bound plane has no plane row", use.nodes);
        } catch (const StoreError& error) {
            Report(plane_id, error.what(), use.nodes);
        }
        std::string stored_root;
        {
            Statement q(container_, "SELECT plane_id, chunk_root FROM plane_version WHERE version_id = ?");
            q.Bind(1, version_id);
            if (!q.Step()) {
                Report(plane_id, "the binding names " + version + ", which is not stored", use.nodes);
                return;
            }
            if (q.IsNull(0) || static_cast<Id>(q.Int(0)) != plane_id) {
                Report(plane_id, "the binding names " + version + ", a version of plane " + q.Text(0), use.nodes);
                return;
            }
            stored_root = q.Text(1);
        }
        if (stored_root != root) {
            Report(plane_id, "chunk_root mismatch: the binding names " + root + ", " + version + " holds " + stored_root,
                   use.nodes);
        }
        const std::vector<ChunkRow> chunks = ReadChunkRows(container_, version_id);
        const std::string actual = ChunkRoot(chunks);
        if (actual != stored_root) {
            Report(plane_id, "chunk_root mismatch: the chunk rows of " + version + " hash to " + actual +
                                 ", not to its chunk_root " + stored_root, use.nodes);
        }
        if (!row) return;
        const bool hash_bytes = level_ == VerifyLevel::full || use.current;
        for (const ChunkRow& chunk : chunks) {
            const std::string where = version + " chunk (" + std::to_string(chunk.x) + "," + std::to_string(chunk.y) + ")";
            if (chunk.x < 0 || chunk.y < 0 || chunk.x >= row->chunks_x() || chunk.y >= row->chunks_y()) {
                Report(plane_id, where + " lies outside the plane", use.nodes);
                continue;
            }
            const std::size_t size = static_cast<std::size_t>(row->chunk_width(chunk.x)) *
                                     static_cast<std::size_t>(row->chunk_height(chunk.y)) * TexelBytes(row->format);
            if (hash_bytes) {
                auto cached = verified_.find(chunk.sha256);
                if (cached == verified_.end()) {
                    std::string error;
                    try {
                        ReadChunkBlob(container_, chunk.sha256, size);
                    } catch (const StoreError& failure) {
                        error = failure.what();
                    }
                    cached = verified_.emplace(chunk.sha256, std::move(error)).first;
                    out_.verified_chunks.insert(chunk.sha256);
                }
                if (!cached->second.empty()) Report(plane_id, where + ": " + cached->second, use.nodes);
                continue;
            }
            Statement q(container_, "SELECT size FROM blob WHERE sha256 = ?");
            q.Bind(1, chunk.sha256);
            if (!q.Step()) {
                Report(plane_id, where + " names blob " + chunk.sha256 + ", which is not stored", use.nodes);
            } else if (q.IsNull(0) || q.Int(0) != static_cast<std::int64_t>(size)) {
                Report(plane_id, where + ": blob " + chunk.sha256 + " holds " + q.Text(0) + " bytes, the chunk has " +
                                     std::to_string(size), use.nodes);
            }
        }
    }

    Container& container_;
    const VerifyLevel level_;
    std::map<VersionKey, Use> bound_;
    std::map<std::string, std::string, std::less<>> verified_;  // chunk hash -> error ("" when it verifies)
    std::set<std::string> reported_;
    PlaneIntegrity out_;
};

}  // namespace

PlaneIntegrity CheckPlaneIntegrity(Container& container, const Value& current_manifest, VerifyLevel level) {
    Checker checker(container, level);
    Statement q(container, "SELECT manifest, manifest_sha256 FROM revision ORDER BY revision");
    while (q.Step()) {
        Value manifest;
        try {
            const std::string text = Decompress(q.Blob(0));
            if (core::Sha256Hex(text) != q.Text(1)) continue;  // reported by CheckIntegrity
            manifest = core::json::Parse(text);
        } catch (const std::exception&) {
            continue;  // reported by CheckIntegrity
        }
        checker.Scan(manifest, false);
    }
    checker.Scan(current_manifest, true);
    return checker.Finish();
}

}  // namespace uzp::store
