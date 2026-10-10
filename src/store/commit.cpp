#include "store/commit.h"

#include <utility>

#include "store/blobs.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"

#if defined(UZP_STORE_FAULT_HOOKS)
#include "store/fault.h"
#endif

namespace uzp::store {

using core::json::Object;
using core::json::Value;

namespace {

std::string Names(const std::vector<core::ResourceMeta>& entries) {
    std::string names;
    for (const core::ResourceMeta& entry : entries) names += (names.empty() ? "" : ", ") + entry.name;
    return names;
}

core::OperationRecord RowRecord(Statement& q, std::string_view project_uuid, std::string key) {
    core::OperationRecord record;
    record.idempotency_key = std::move(key);
    record.project_uuid = q.Text(0);
    record.request_hash = q.Text(1);
    record.committed_revision = q.Int(3);
    if (record.project_uuid != project_uuid) {
        throw StoreError(StoreError::Code::corrupt,
                         "operation " + record.idempotency_key + " belongs to project " + record.project_uuid);
    }
    try {
        record.outcome = core::json::Parse(Decompress(q.Blob(2)));
    } catch (const std::exception& error) {
        throw StoreError(StoreError::Code::corrupt,
                         "operation " + record.idempotency_key + ": outcome unreadable: " + error.what());
    }
    if (!record.outcome.IsObject()) {
        throw StoreError(StoreError::Code::corrupt, "operation " + record.idempotency_key + ": outcome is not an object");
    }
    return record;
}

}  // namespace

void WriteResources(Container& container, const core::Project& project, const PendingContent& pending, bool portable) {
    for (const auto& [sha256, entries] : project.resources) {
        if (!HasBlob(container, sha256)) {
            if (const auto staged = pending.blobs.find(sha256); staged != pending.blobs.end()) {
                if (PutBlob(container, staged->second.bytes, staged->second.mime) != sha256) {
                    throw StoreError(StoreError::Code::conflict, "staged bytes do not hash to " + sha256);
                }
            } else if (const auto locator = pending.locators.find(sha256); !portable && locator != pending.locators.end()) {
                PutLocator(container, sha256, locator->second);
            } else if (portable || !FindLocator(container, sha256)) {
                throw StoreError(StoreError::Code::missing_resource,
                                 "resource " + sha256 + " (" + Names(entries) + ") has no stored or staged bytes" +
                                     (portable ? "; a portable project embeds every dependency" : ""));
            }
        }
        for (const core::ResourceMeta& entry : entries) {
            PutBlobName(container,
                        BlobName{sha256, entry.name, entry.usage, entry.origin, entry.color_space, entry.imported_at});
        }
    }
}

void WriteRevision(Container& container, std::int64_t revision, std::optional<std::int64_t> parent,
                   std::string_view kind, const core::Project& project) {
    const std::string manifest = core::SaveManifest(project);
    Statement q(container,
                "INSERT INTO revision (revision, parent, created_at, kind, name, manifest, manifest_sha256) "
                "VALUES (?, ?, ?, ?, NULL, ?, ?)");
    q.Bind(1, revision);
    if (parent) {
        q.Bind(2, *parent);
    } else {
        q.BindNull(2);
    }
    q.Bind(3, UtcNow()).Bind(4, kind).BindBlob(5, Compress(manifest)).Bind(6, core::Sha256Hex(manifest)).Run();

    const Value json = core::ProjectToJson(project);
    const Object& versions = std::get<Object>(std::get<Object>(json.data).at("versions").data);
    for (const char* key : {"format_version", "app_version", "evaluator_profile", "compat_profile"}) {
        container.SetMeta(key, std::get<std::string>(versions.at(key).data));
    }
    container.SetMeta("painter_reference", core::json::WriteCanonical(versions.at("painter_reference")));
}

void CommitMutation(Container& container, const core::Snapshot& snapshot, const core::OperationRecord& record,
                    const PendingContent& pending, bool portable, const std::vector<CommitExtension>& extensions) {
    Container::WriteTransaction transaction(container);
    const std::int64_t current = ReadCurrentRevision(container);
    if (snapshot.revision != current + 1 || record.committed_revision != snapshot.revision) {
        throw StoreError(StoreError::Code::conflict, "revision " + std::to_string(snapshot.revision) +
                                                         " does not follow the stored current revision " +
                                                         std::to_string(current));
    }
    if (container.Meta("project_uuid") != record.project_uuid) {
        throw StoreError(StoreError::Code::conflict, "the operation record names project " + record.project_uuid);
    }
    WriteResources(container, *snapshot.project, pending, portable);
    for (const CommitExtension& extension : extensions) extension(container, snapshot);
    WriteRevision(container, snapshot.revision, current, "mutation", *snapshot.project);
    Statement op(container,
                 "INSERT INTO operation (idempotency_key, project_uuid, request_hash, outcome, committed_revision, "
                 "created_at) VALUES (?, ?, ?, ?, ?, ?)");
    op.Bind(1, record.idempotency_key)
        .Bind(2, record.project_uuid)
        .Bind(3, record.request_hash)
        .BindBlob(4, Compress(core::json::WriteCanonical(record.outcome)))
        .Bind(5, record.committed_revision)
        .Bind(6, UtcNow())
        .Run();
    Statement checkpoint(container, "UPDATE checkpoint SET revision = ?, created_at = ? WHERE name = 'current'");
    checkpoint.Bind(1, snapshot.revision).Bind(2, UtcNow()).Run();
    transaction.Commit();
#if defined(UZP_STORE_FAULT_HOOKS)
    fault::AfterDurableCommit();
#endif
}

std::int64_t ReadCurrentRevision(Container& container) {
    Statement q(container, "SELECT revision FROM checkpoint WHERE name = 'current'");
    if (!q.Step() || q.IsNull(0)) throw StoreError(StoreError::Code::corrupt, "no checkpoint 'current'");
    return q.Int(0);
}

std::int64_t ReadHorizon(Container& container) {
    const std::optional<std::string> text = container.Meta("operation_horizon_revision");
    if (!text) return 0;
    try {
        std::size_t used = 0;
        const long long horizon = std::stoll(*text, &used);
        if (used == text->size() && horizon >= 0) return horizon;
    } catch (const std::exception&) {
    }
    throw StoreError(StoreError::Code::corrupt, "meta.operation_horizon_revision '" + *text + "' is not a revision");
}

std::optional<core::OperationRecord> ReadOperation(Container& container, std::string_view project_uuid,
                                                   std::string_view key) {
    Statement q(container,
                "SELECT project_uuid, request_hash, outcome, committed_revision FROM operation WHERE idempotency_key = ?");
    q.Bind(1, key);
    if (!q.Step()) return std::nullopt;
    return RowRecord(q, project_uuid, std::string(key));
}

std::vector<core::OperationRecord> ReadOperations(Container& container, std::string_view project_uuid,
                                                  std::vector<std::string>& unreadable) {
    Statement q(container,
                "SELECT project_uuid, request_hash, outcome, committed_revision, idempotency_key FROM operation "
                "ORDER BY committed_revision, idempotency_key");
    std::vector<core::OperationRecord> records;
    while (q.Step()) {
        try {
            records.push_back(RowRecord(q, project_uuid, q.Text(4)));
        } catch (const StoreError&) {
            unreadable.push_back(q.Text(4));
        }
    }
    return records;
}

core::AdmissionDecision DecideStored(Container& container, std::string_view project_uuid,
                                     const core::MutationRequest& request, std::int64_t fallback_revision) {
    core::AdmissionInput input;
    input.request_hash = request.request_hash();
    input.expected_revision = request.expected_revision;
    try {
        input.current_revision = ReadCurrentRevision(container);
        input.horizon_revision = ReadHorizon(container);
        input.known = ReadOperation(container, project_uuid, request.idempotency_key);
    } catch (const StoreError&) {
        input.records_readable = false;
        input.current_revision = fallback_revision;
        input.known.reset();
    }
    return core::DecideAdmission(input);
}

}  // namespace uzp::store
