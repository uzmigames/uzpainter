#include "store/compact.h"

#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include <algorithm>
#include <utility>

#include "store/commit.h"
#include "store/integrity.h"
#include "store/planes.h"
#include "store/project_store.h"
#include "store/save.h"
#include "uzp_core/manifest/json.h"

#if defined(UZP_STORE_FAULT_HOOKS)
#include "store/fault.h"
#endif

namespace uzp::store {

using core::json::Array;
using core::json::Object;
using core::json::Value;

namespace {

std::string Utf8(const std::filesystem::path& path) {
    const std::u8string text = path.u8string();
    return std::string(text.begin(), text.end());
}

bool IsSha256(std::string_view text) {
    return text.size() == 64 && std::all_of(text.begin(), text.end(), [](char c) {
               return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
           });
}

/// Every SHA-256 a manifest names, as a value or as an object key (the `resources` map).
void CollectHashes(const Value& value, std::set<std::string, std::less<>>& out) {
    if (const auto* text = std::get_if<std::string>(&value.data)) {
        if (IsSha256(*text)) out.insert(*text);
    } else if (const auto* array = std::get_if<Array>(&value.data)) {
        for (const Value& item : *array) CollectHashes(item, out);
    } else if (const auto* object = std::get_if<Object>(&value.data)) {
        for (const auto& [key, member] : *object) {
            if (IsSha256(key)) out.insert(key);
            CollectHashes(member, out);
        }
    }
}

std::int64_t Scalar(Container& container, const std::string& sql) {
    Statement q(container, sql);
    return q.Step() && !q.IsNull(0) ? q.Int(0) : 0;
}

/// Runs a DELETE and returns the number of rows it removed.
std::int64_t Delete(Container& container, const std::string& sql) {
    container.Exec(sql);
    return Scalar(container, "SELECT changes()");
}

void RemoveQuietly(const std::filesystem::path& path) {
    std::error_code ec;
    std::filesystem::remove(path, ec);
    std::filesystem::path journal = path;
    journal += "-journal";
    std::filesystem::remove(journal, ec);
}

std::uintmax_t FileBytes(const std::filesystem::path& path) {
    std::error_code ec;
    const std::uintmax_t size = std::filesystem::file_size(path, ec);
    return ec ? 0 : size;
}

}  // namespace

Retention ComputeRetention(Container& container) {
    Retention retention;
    retention.current = ReadCurrentRevision(container);
    retention.named = ReadNamedRevision(container);
    retention.previous = ReadPreviousRevision(container);
    {
        Statement q(container, "SELECT revision FROM revision WHERE kind = 'mutation' ORDER BY revision DESC LIMIT ?");
        q.Bind(1, std::int64_t{kRetainedMutations});
        while (q.Step()) retention.mutations.push_back(q.Int(0));
        std::reverse(retention.mutations.begin(), retention.mutations.end());
    }
    {
        Statement q(container, "SELECT revision FROM checkpoint WHERE protected = 1 AND revision IS NOT NULL");
        while (q.Step()) retention.protected_revisions.insert(q.Int(0));
    }
    retention.revisions.insert(retention.current);
    if (retention.named) retention.revisions.insert(*retention.named);
    if (retention.previous) retention.revisions.insert(*retention.previous);
    retention.revisions.insert(retention.mutations.begin(), retention.mutations.end());
    retention.revisions.insert(retention.protected_revisions.begin(), retention.protected_revisions.end());
    return retention;
}

Reachable ComputeReachable(Container& container) {
    Reachable reachable;
    std::vector<std::int64_t> revisions;
    {
        Statement q(container, "SELECT revision FROM revision ORDER BY revision");
        while (q.Step()) revisions.push_back(q.Int(0));
    }
    for (const std::int64_t revision : revisions) {
        Value manifest;
        try {
            manifest = core::json::Parse(ReadManifestText(container, revision));
        } catch (const core::json::ParseError& error) {
            throw CorruptionError(CorruptItem{"manifest", std::to_string(revision), error.what(), {}});
        }
        CollectHashes(manifest, reachable.hashes);
        for (const ManifestBinding& binding : ManifestPlaneBindings(manifest)) {
            if (!binding.version) {
                throw CorruptionError(CorruptItem{"plane", std::to_string(binding.plane_id),
                                                  "revision " + std::to_string(revision) +
                                                      ": malformed binding: " + binding.error,
                                                  {AffectedNode{binding.owner, binding.path}}});
            }
            reachable.planes.insert(binding.plane_id);
            reachable.versions.insert(binding.version->version_id);
        }
        for (const PlaneReference& reference : ManifestPlaneReferences(manifest)) reachable.planes.insert(reference.plane_id);
    }
    for (const std::int64_t version : reachable.versions) {
        Statement q(container, "SELECT plane_id FROM plane_version WHERE version_id = ?");
        q.Bind(1, version);
        if (q.Step() && !q.IsNull(0)) reachable.planes.insert(static_cast<core::Id>(q.Int(0)));
        for (const ChunkRow& chunk : ReadChunkRows(container, version)) reachable.hashes.insert(chunk.sha256);
    }
    return reachable;
}

CompactResult CollapseAndCollect(Container& container) {
    CompactResult result;
    Container::WriteTransaction transaction(container);
    const Retention retention = ComputeRetention(container);
    result.retained.assign(retention.revisions.begin(), retention.revisions.end());

    container.Exec("CREATE TEMP TABLE keep_revision (revision INTEGER PRIMARY KEY)");
    {
        Statement insert(container, "INSERT INTO keep_revision (revision) VALUES (?)");
        for (const std::int64_t revision : retention.revisions) {
            insert.Bind(1, revision).Run();
            insert.Reset();
        }
    }
    {
        Statement q(container,
                    "SELECT revision FROM revision WHERE revision NOT IN (SELECT revision FROM keep_revision) "
                    "ORDER BY revision");
        while (q.Step()) result.collapsed.push_back(q.Int(0));
    }

    // Named checkpoints: keep the protected ones and those naming the last named checkpoint or
    // `previous`; collapse the others.
    {
        Statement q(container, "SELECT name, revision, protected FROM checkpoint ORDER BY revision, name");
        std::vector<std::string> removed;
        while (q.Step()) {
            const std::string name = q.Text(0);
            if (name == kCurrentCheckpoint || name == kPreviousCheckpoint || q.Int(2) == 1) continue;
            const std::int64_t revision = q.Int(1);
            if (revision == retention.named || revision == retention.previous) continue;
            removed.push_back(name);
        }
        Statement erase(container, "DELETE FROM checkpoint WHERE name = ?");
        for (const std::string& name : removed) {
            erase.Bind(1, name).Run();
            erase.Reset();
        }
        result.removed_checkpoints = std::move(removed);
    }

    // Operation rows of collapsed revisions, then the revisions; the horizon only rises.
    result.horizon = ReadHorizon(container);
    if (!result.collapsed.empty()) result.horizon = std::max(result.horizon, result.collapsed.back());
    result.removed_operations =
        Delete(container, "DELETE FROM operation WHERE committed_revision NOT IN (SELECT revision FROM keep_revision)");
    Delete(container, "DELETE FROM revision WHERE revision NOT IN (SELECT revision FROM keep_revision)");
    container.SetMeta("operation_horizon_revision", std::to_string(result.horizon));
    container.Exec("DROP TABLE temp.keep_revision");
    container.Exec("DELETE FROM cache");

    // Everything the retained manifests do not reach.
    const Reachable reachable = ComputeReachable(container);
    container.Exec("CREATE TEMP TABLE keep_version (id INTEGER PRIMARY KEY)");
    container.Exec("CREATE TEMP TABLE keep_plane (id INTEGER PRIMARY KEY)");
    container.Exec("CREATE TEMP TABLE keep_hash (sha256 TEXT PRIMARY KEY)");
    {
        Statement version(container, "INSERT INTO keep_version (id) VALUES (?)");
        for (const std::int64_t id : reachable.versions) {
            version.Bind(1, id).Run();
            version.Reset();
        }
        Statement plane(container, "INSERT INTO keep_plane (id) VALUES (?)");
        for (const core::Id id : reachable.planes) {
            plane.Bind(1, static_cast<std::int64_t>(id)).Run();
            plane.Reset();
        }
        Statement hash(container, "INSERT INTO keep_hash (sha256) VALUES (?)");
        for (const std::string& sha256 : reachable.hashes) {
            hash.Bind(1, sha256).Run();
            hash.Reset();
        }
    }
    result.removed_chunks =
        Delete(container, "DELETE FROM plane_chunk WHERE version_id NOT IN (SELECT id FROM keep_version)");
    result.removed_versions =
        Delete(container, "DELETE FROM plane_version WHERE version_id NOT IN (SELECT id FROM keep_version)");
    result.removed_planes = Delete(container,
                                   "DELETE FROM plane WHERE plane_id NOT IN (SELECT id FROM keep_plane) "
                                   "AND plane_id NOT IN (SELECT plane_id FROM plane_version)");
    result.removed_blobs = Delete(container, "DELETE FROM blob WHERE sha256 NOT IN (SELECT sha256 FROM keep_hash)");
    Delete(container, "DELETE FROM blob_meta WHERE sha256 NOT IN (SELECT sha256 FROM keep_hash)");
    Delete(container, "DELETE FROM locator WHERE sha256 NOT IN (SELECT sha256 FROM keep_hash)");
    container.Exec("DROP TABLE temp.keep_version");
    container.Exec("DROP TABLE temp.keep_plane");
    container.Exec("DROP TABLE temp.keep_hash");
    transaction.Commit();
    return result;
}

std::string ErrorDetail(const StoreError& error) {
    const std::string text = error.what();
    const std::string prefix = std::string(CodeName(error.code())) + ": ";
    return text.compare(0, prefix.size(), prefix) == 0 ? text.substr(prefix.size()) : text;
}

std::filesystem::path SiblingPath(const std::filesystem::path& target, std::string_view suffix) {
    std::filesystem::path path = target;
    path += ".";
    path += std::string(suffix);
    return path;
}

void RemoveTemporaryFiles(const std::filesystem::path& project) {
    RemoveQuietly(SiblingPath(project, "compact"));
    RemoveQuietly(SiblingPath(project, "vacuum"));
}

void VacuumInto(Container& source, const std::filesystem::path& output) {
    RemoveQuietly(output);  // VACUUM INTO needs an absent (or empty) output
    try {
        Statement vacuum(source, "VACUUM INTO ?");
        vacuum.Bind(1, Utf8(output));
#if defined(UZP_STORE_FAULT_HOOKS)
        fault::EnterVacuum();
#endif
        try {
            vacuum.Run();
        } catch (...) {
#if defined(UZP_STORE_FAULT_HOOKS)
            fault::LeaveVacuum();
#endif
            throw;
        }
#if defined(UZP_STORE_FAULT_HOOKS)
        fault::LeaveVacuum();
#endif
    } catch (const StoreError& error) {
        RemoveQuietly(output);
        throw StoreError(error.code(), "VACUUM INTO " + Utf8(output) + " failed: " + ErrorDetail(error));
    }
}

void RenameFile(const std::filesystem::path& from, const std::filesystem::path& to, bool replace) {
    bool failed = false;
    DWORD error = 0;
#if defined(UZP_STORE_FAULT_HOOKS)
    if (fault::BeforeRename()) {
        failed = true;
        error = ERROR_WRITE_FAULT;
    }
#endif
    if (!failed) {
        const DWORD flags = MOVEFILE_WRITE_THROUGH | (replace ? MOVEFILE_REPLACE_EXISTING : 0);
        if (!MoveFileExW(from.c_str(), to.c_str(), flags)) {
            failed = true;
            error = GetLastError();
        }
    }
    if (failed) {
        throw StoreError(StoreError::Code::io, "rename of " + Utf8(from) + " to " + Utf8(to) + " failed (error " +
                                                   std::to_string(error) + ")");
    }
}

CompactResult ProjectStore::Compact(core::Document& document) {
    std::lock_guard lock(mutex_);
    return CompactLocked(document);
}

CompactResult ProjectStore::CompactLocked(core::Document& document) {
    CheckDocument(document);
    const std::filesystem::path work = SiblingPath(path_, "compact");
    const std::filesystem::path output = SiblingPath(path_, "vacuum");
    RemoveTemporaryFiles(path_);
    CompactResult result;
    try {
        // The project file is only read until the rename: the copy is collapsed and collected,
        // and `VACUUM INTO` writes the compacted file from it.
        std::error_code ec;
        std::filesystem::copy_file(path_, work, std::filesystem::copy_options::overwrite_existing, ec);
        if (ec) {
            throw StoreError(StoreError::Code::io, "copy of " + Utf8(path_) + " to " + Utf8(work) + " failed: " + ec.message());
        }
        {
            Container copy = Container::Open(work);
            try {
                result = CollapseAndCollect(copy);
            } catch (const StoreError& error) {
                throw StoreError(error.code(), "collapse and collect in " + Utf8(work) + " failed: " + ErrorDetail(error));
            }
            result.bytes_before = FileBytes(path_);
            VacuumInto(copy, output);
        }
        RemoveQuietly(work);
        {
            Container closing = std::move(container_);  // Windows renames over a closed file only
        }
        try {
            RenameFile(output, path_, true);
        } catch (...) {
            container_ = Container::Open(path_);
            throw;
        }
        container_ = Container::Open(path_);
        container_.EnsureDeleteJournal();
    } catch (const StoreError& error) {
        RemoveTemporaryFiles(path_);
        throw StoreError(error.code(), "compact " + Utf8(path_) + ": " + ErrorDetail(error));
    }
    result.bytes_after = FileBytes(path_);
    document.SetOperationHorizon(result.horizon);
    return result;
}

}  // namespace uzp::store
