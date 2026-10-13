// Native tests of the project store (`src/store/`; tasks phase1.4_store-container-operations and
// phase1.5_store-planes).
// Built by `zig build uzp-store-tests` with the test-only fault hooks (`src/store/fault.h`) and
// driven by tests/store/test_store.py.
//
// Usage:
//   uzp-store-tests run [case]              run every native case (or one); exit 0 when all pass
//   uzp-store-tests child <fault> <file>    open <file>, arm <fault> (kill-during-commit,
//                                           kill-after-commit or kill-in-plane-commit) and submit
//                                           one mutation; the hook terminates the process with
//                                           exit code 77
// Cases that need an interrupted process start this executable again as a child.

#include <windows.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <functional>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "store/blobs.h"
#include "store/commit.h"
#include "store/container.h"
#include "store/fault.h"
#include "store/integrity.h"
#include "store/planes.h"
#include "store/project_store.h"
#include "store/versioning.h"
#include "uzp_core/document/document.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/errors.h"

namespace {

using namespace uzp::core;
using namespace uzp::store;
namespace fs = std::filesystem;

struct Failure {
    std::string message;
};

#define CHECK(cond)                                                                                     \
    do {                                                                                                \
        if (!(cond)) throw Failure{std::string(__FILE__ ":") + std::to_string(__LINE__) + ": " #cond}; \
    } while (false)

template <typename E, typename F>
E ExpectThrow(F&& body, const char* what) {
    try {
        body();
    } catch (const E& error) {
        return error;
    }
    throw Failure{std::string("expected an exception: ") + what};
}

#define EXPECT_THROW(E, expr) ExpectThrow<E>([&] { expr; }, #expr)

bool Contains(std::string_view text, std::string_view part) { return text.find(part) != std::string_view::npos; }

constexpr const char* kUuid = "6f1c2a3e-0000-4000-8000-0000000000aa";
constexpr Id kSet = 1, kStack = 3;
const InsertPosition kTop = InsertPosition::FromStack(kSet, kStack);

Project BaseProject() {
    Project p;
    p.versions.app_version = "0.0.0";
    p.versions.evaluator_profile = "painter-12.1-isolated-linear";
    TextureSet set;
    set.id = p.AllocateId();
    set.name = "M_body";
    set.original_name = "M_body";
    set.material_id = "material-0";
    set.uv_tiles = {UVTile{p.AllocateId(), 1001, {}}};
    Stack stack;
    stack.id = p.AllocateId();
    stack.channels[ChannelType::BaseColor] = Channel{ChannelFormat::sRGB8, "", {}};
    set.stacks = {stack};
    p.texture_sets = {set};
    return p;
}

DocumentState NewState(Project project = BaseProject()) {
    DocumentState state;
    state.project_uuid = kUuid;
    state.project = std::move(project);
    return state;
}

MutationRequest Req(const std::string& key, std::optional<std::int64_t> expected, std::string name = "") {
    return MutationRequest{"layer_insert", json::Object{{"name", name.empty() ? key : name}}, key, expected};
}

/// A working directory per case under the system temp folder, emptied first.
fs::path WorkDir(const std::string& name) {
    const fs::path dir = fs::temp_directory_path() /
                         ("uzp-store-tests-" + std::to_string(GetCurrentProcessId())) / name;
    fs::remove_all(dir);
    fs::create_directories(dir);
    return dir;
}

std::string ReadBytes(const fs::path& path) {
    std::ifstream file(path, std::ios::binary);
    std::ostringstream bytes;
    bytes << file.rdbuf();
    return bytes.str();
}

void WriteBytes(const fs::path& path, std::string_view bytes) {
    std::ofstream file(path, std::ios::binary);
    file.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}

/// Incompressible bytes (xorshift).
std::string Noise(std::size_t size, std::uint64_t seed) {
    std::string bytes(size, '\0');
    std::uint64_t x = seed;
    for (char& c : bytes) {
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        c = static_cast<char>(x & 0xff);
    }
    return bytes;
}

ResourceMeta Meta(Id id, std::string name, std::size_t size) {
    ResourceMeta meta;
    meta.id = id;
    meta.name = std::move(name);
    meta.mime = "image/png";
    meta.size = static_cast<std::int64_t>(size);
    meta.usage = "TEXTURE";
    meta.origin = "import";
    meta.imported_at = "2026-10-10T00:00:00Z";
    meta.color_space = "sRGB";
    return meta;
}

/// A store and the document attached to it (the document is destroyed first).
struct Session {
    std::unique_ptr<ProjectStore> store;
    std::unique_ptr<Document> doc;
    IntegrityReport report;
    bool migrated = false;
};

Session OpenSession(const fs::path& path, const OpenOptions& options = {}) {
    ProjectStore::Opened opened = ProjectStore::Open(path, options);
    Session s{std::move(opened.store), std::make_unique<Document>(std::move(opened.state)), opened.report,
              opened.migrated};
    s.store->Attach(*s.doc);
    return s;
}

fs::path CreateProject(const fs::path& dir, CreateOptions options = {}, Project project = BaseProject()) {
    const fs::path path = dir / "project.uzp";
    ProjectStore::Create(path, NewState(std::move(project)), options);
    return path;
}

/// Inserts a fill layer named after the key.
RequestOutcome AddLayer(Session& s, const std::string& key, std::optional<std::int64_t> expected,
                        const std::string& name = "") {
    return s.store->Submit(*s.doc, Req(key, expected, name),
                           [&](Edit& e) { e.Insert(kTop, NodeType::FillLayer, name.empty() ? key : name); });
}

/// Imports `bytes` under `name` and binds them to a new fill layer's base colour; returns the layer.
Id ImportBound(Session& s, const std::string& key, const std::string& bytes, const std::string& name,
               RequestOutcome* outcome = nullptr) {
    Id uid = kNoId;
    RequestOutcome result = s.store->Submit(*s.doc, Req(key, s.doc->revision(), name), [&](Edit& e) {
        const std::string sha = s.store->StageResource(bytes, "image/png");
        CHECK(s.store->ReadResource(sha) == bytes);  // staged bytes read in the transaction (decision 240)
        e.project().resources[sha].push_back(Meta(e.AllocateId(), name, bytes.size()));
        uid = e.Insert(kTop, NodeType::FillLayer, name);
        Layer& layer = *FindLayer(e.project(), uid);
        layer.fill->sources[ChannelType::BaseColor] = Source{BitmapSource{{sha, std::nullopt, {}}, "sRGB", {}}};
        layer.fill->active_channels = {ChannelType::BaseColor};
    });
    if (outcome != nullptr) *outcome = result;
    return uid;
}

bool Committed(const RequestOutcome& outcome) {
    return outcome.decision.admission == Admission::execute && outcome.result &&
           outcome.result->status == ResultStatus::committed;
}

std::int64_t Count(Container& c, const std::string& sql) {
    Statement q(c, sql);
    return q.Step() ? q.Int(0) : -1;
}

std::string StoredManifest(Container& c, std::int64_t revision) {
    Statement q(c, "SELECT manifest FROM revision WHERE revision = ?");
    q.Bind(1, revision);
    if (!q.Step()) throw Failure{"no revision " + std::to_string(revision)};
    return Decompress(q.Blob(0));
}

/// Runs this executable again with `args`; returns its exit code.
DWORD RunChild(const std::vector<std::string>& args) {
    char exe[MAX_PATH];
    GetModuleFileNameA(nullptr, exe, MAX_PATH);
    std::string command = std::string("\"") + exe + "\"";
    for (const std::string& arg : args) command += " \"" + arg + "\"";
    STARTUPINFOA startup{};
    startup.cb = sizeof startup;
    PROCESS_INFORMATION process{};
    if (!CreateProcessA(exe, command.data(), nullptr, nullptr, FALSE, 0, nullptr, nullptr, &startup, &process)) {
        throw Failure{"cannot start the child process"};
    }
    WaitForSingleObject(process.hProcess, 300000);
    DWORD code = 0;
    GetExitCodeProcess(process.hProcess, &code);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return code;
}

// ── 2.2 Schema, journal mode, foreign keys, zstd payloads ───────────────────────────────────

void SchemaAndPragmas() {
    const fs::path dir = WorkDir("schema");
    const fs::path path = CreateProject(dir);
    {
        Session s = OpenSession(path);
        CHECK(Committed(AddLayer(s, "a", 0)));
    }
    Container c = Container::Open(path);
    for (const char* table : {"meta", "revision", "blob", "blob_meta", "plane", "plane_version", "plane_chunk",
                              "operation", "cache", "checkpoint", "locator"}) {
        CHECK(c.HasTable(table));
    }
    {
        Statement q(c, "PRAGMA journal_mode");
        CHECK(q.Step() && q.Text(0) == "delete");
    }
    CHECK(Count(c, "PRAGMA foreign_keys") == 1);
    const auto fk = EXPECT_THROW(StoreError, c.Exec("INSERT INTO operation (idempotency_key, committed_revision) VALUES ('x', 999)"));
    CHECK(Contains(fk.what(), "FOREIGN KEY"));
    CHECK(c.Meta("format_version") == "1.0.0");
    CHECK(c.Meta("project_uuid") == std::string(kUuid));
    CHECK(c.Meta("operation_horizon_revision") == "0");
    CHECK(c.Meta("compat_profile") == "painter-12.1-api-0.3.7");
    {
        Statement q(c, "SELECT manifest, manifest_sha256, kind, parent FROM revision WHERE revision = 1");
        CHECK(q.Step());
        const std::string frame = q.Blob(0);
        CHECK(frame.size() >= 4 && frame.compare(0, 4, "\x28\xb5\x2f\xfd") == 0);  // zstd frame magic
        const std::string text = Decompress(frame);
        CHECK(Sha256Hex(text) == q.Text(1));
        CHECK(text == SaveManifest(LoadManifest(text)));  // canonical
        CHECK(q.Text(2) == "mutation");
        CHECK(q.Int(3) == 0);
    }
    {
        Statement q(c, "SELECT outcome FROM operation WHERE idempotency_key = 'a'");
        CHECK(q.Step());
        const json::Value outcome = json::Parse(Decompress(q.Blob(0)));
        CHECK(std::get<json::Object>(outcome.data).at("committed_revision") == json::Value(1));
    }
    CHECK(!fs::exists(dir / "project.uzp-wal") && !fs::exists(dir / "project.uzp-journal"));
    EXPECT_THROW(StoreError, ProjectStore::Create(path, NewState()));  // exists
}

// ── 3.1 Commit atomicity ─────────────────────────────────────────────────────────────────────

void CommitAtomicity() {
    const fs::path dir = WorkDir("atomicity");
    const fs::path path = CreateProject(dir);
    {
        Session s = OpenSession(path);
        CHECK(Committed(AddLayer(s, "first", 0)));
    }
    const std::string before = ReadBytes(path);
    // The child dies while SQLite writes the database pages of the commit: the journal is hot.
    CHECK(RunChild({"child", "kill-during-commit", path.string()}) == fault::kKillExitCode);
    CHECK(fs::exists(dir / "project.uzp-journal"));
    CHECK(ReadBytes(path) != before);  // torn: the child wrote part of the new state

    {
        Session s = OpenSession(path);  // rolls the hot journal back
        CHECK(s.report.ok());
        CHECK(s.doc->revision() == 1);
        CHECK(!s.doc->FindOperation("killed"));
        Container& c = s.store->container();
        CHECK(Count(c, "SELECT COUNT(*) FROM revision") == 2);
        CHECK(Count(c, "SELECT COUNT(*) FROM operation WHERE idempotency_key = 'killed'") == 0);
        CHECK(Count(c, "SELECT COUNT(*) FROM blob") == 0);
        CHECK(!fs::exists(dir / "project.uzp-journal"));
        // The same request completes now: the new revision with its operation row.
        const RequestOutcome done = s.store->Submit(*s.doc, Req("killed", 1), [&](Edit& e) {
            const std::string sha = s.store->StageResource(Noise(200000, 7), "image/png");
            e.project().resources[sha] = {Meta(e.AllocateId(), "killed.png", 200000)};
            e.Insert(kTop, NodeType::FillLayer, "killed");
        });
        CHECK(Committed(done));
        CHECK(done.result->revision == 2);
    }
    Session s = OpenSession(path);
    CHECK(s.doc->revision() == 2);
    const auto record = s.doc->FindOperation("killed");
    CHECK(record && record->committed_revision == 2);
    CHECK(Count(s.store->container(), "SELECT revision FROM checkpoint WHERE name = 'current'") == 2);
}

// ── 3.2 Disk full during commit ──────────────────────────────────────────────────────────────

void DiskFull() {
    const fs::path dir = WorkDir("disk-full");
    const fs::path path = CreateProject(dir);
    Session s = OpenSession(path);
    CHECK(Committed(AddLayer(s, "first", 0)));
    const Snapshot before = s.doc->snapshot();

    fault::Arm(fault::Fault::disk_full);
    RequestOutcome full;
    ImportBound(s, "big", Noise(512 * 1024, 11), "big.png", &full);
    fault::Arm(fault::Fault::none);
    CHECK(full.result && full.result->status == ResultStatus::failed);
    CHECK(Contains(full.result->error, "disk_full"));
    CHECK(Contains(full.result->error, "database or disk is full"));
    CHECK(s.doc->revision() == 1 && *s.doc->snapshot().project == *before.project);
    CHECK(!s.doc->FindOperation("big"));
    Container& c = s.store->container();
    CHECK(Count(c, "SELECT COUNT(*) FROM revision") == 2);
    CHECK(Count(c, "SELECT COUNT(*) FROM operation") == 1);
    CHECK(Count(c, "SELECT COUNT(*) FROM blob") == 0);
    CHECK(Count(c, "SELECT revision FROM checkpoint WHERE name = 'current'") == 1);
    {
        Statement q(c, "PRAGMA integrity_check");
        CHECK(q.Step() && q.Text(0) == "ok");
    }
    // A failed mutation wrote no row: its retry is an unknown key with a current precondition.
    RequestOutcome retry;
    ImportBound(s, "big", Noise(512 * 1024, 11), "big.png", &retry);
    CHECK(Committed(retry) && retry.result->revision == 2);
    s.doc.reset();
    s.store.reset();
    Session reopened = OpenSession(path, OpenOptions{VerifyLevel::full, VersionPolicy::Current()});
    CHECK(reopened.report.ok());
    CHECK(reopened.doc->revision() == 2);
}

// ── 3.3 Corrupt blob, corrupt manifest ───────────────────────────────────────────────────────

void CorruptBlob() {
    const fs::path dir = WorkDir("corrupt-blob");
    const fs::path path = CreateProject(dir);
    const std::string bytes = "original resource bytes, stored unmodified";
    const std::string sha = Sha256Hex(bytes);
    Id uid = kNoId;
    {
        Session s = OpenSession(path);
        uid = ImportBound(s, "import", bytes, "cloth.png");
        CHECK(s.store->ReadResource(sha) == bytes);
    }
    {
        // Altered content in a valid zstd frame of the same size.
        Container c = Container::Open(path);
        std::string altered = bytes;
        altered[0] = 'O';
        Statement q(c, "UPDATE blob SET data = ? WHERE sha256 = ?");
        q.BindBlob(1, Compress(altered)).Bind(2, sha).Run();
    }
    {
        Session s = OpenSession(path, OpenOptions{VerifyLevel::full, VersionPolicy::Current()});
        CHECK(s.report.corrupt.size() == 1);
        const CorruptItem& item = s.report.corrupt[0];
        CHECK(item.kind == "blob" && item.key == sha);
        CHECK(item.nodes.size() == 1 && item.nodes[0].id == uid);
        CHECK(Contains(item.nodes[0].path, "sources.BaseColor.resource.sha256"));
        CHECK(s.report.missing.empty());
    }
    {
        Session s = OpenSession(path);  // standard verification does not hash blobs
        CHECK(s.report.ok());
        const auto error = EXPECT_THROW(CorruptionError, s.store->ReadResource(sha));
        CHECK(error.code() == StoreError::Code::corrupt);
        CHECK(error.item().kind == "blob" && error.item().nodes.size() == 1 && error.item().nodes[0].id == uid);
        CHECK(Contains(error.what(), "node " + std::to_string(uid)));
    }
    {
        // A damaged frame: the zstd checksum or the hash catches it.
        Container c = Container::Open(path);
        std::string frame = Compress(bytes);
        frame[frame.size() / 2] = static_cast<char>(frame[frame.size() / 2] ^ 0x5a);
        Statement q(c, "UPDATE blob SET data = ? WHERE sha256 = ?");
        q.BindBlob(1, frame).Bind(2, sha).Run();
    }
    Session s = OpenSession(path);
    const auto error = EXPECT_THROW(CorruptionError, s.store->ReadResource(sha));
    CHECK(error.item().nodes.size() == 1 && error.item().nodes[0].id == uid);
}

void CorruptManifest() {
    const fs::path dir = WorkDir("corrupt-manifest");
    const fs::path path = CreateProject(dir);
    {
        Session s = OpenSession(path);
        CHECK(Committed(AddLayer(s, "a", 0)));
        CHECK(Committed(AddLayer(s, "b", 1)));
    }
    const auto tamper = [&](std::int64_t revision) {
        Container c = Container::Open(path);
        std::string text = StoredManifest(c, revision);
        const std::size_t at = text.find("\"M_body\"");
        CHECK(at != std::string::npos);
        text.replace(at, 8, "\"M_bodx\"");
        Statement q(c, "UPDATE revision SET manifest = ? WHERE revision = ?");
        q.BindBlob(1, Compress(text)).Bind(2, revision).Run();
    };
    // An older revision: the file opens, and the report names the revision.
    tamper(1);
    {
        Session s = OpenSession(path);
        CHECK(s.report.corrupt.size() == 1);
        CHECK(s.report.corrupt[0].kind == "manifest" && s.report.corrupt[0].key == "1");
        CHECK(Contains(s.report.corrupt[0].detail, "manifest_sha256"));
        CHECK(s.doc->revision() == 2);
    }
    // The current revision: opening fails with the corruption.
    tamper(2);
    const auto error = EXPECT_THROW(CorruptionError, ProjectStore::Open(path));
    CHECK(error.item().kind == "manifest" && error.item().key == "2");
    CHECK(Contains(error.what(), "manifest_sha256"));
}

// ── 3.4 Commit then die ──────────────────────────────────────────────────────────────────────

void CommitThenDie() {
    const fs::path dir = WorkDir("commit-then-die");
    const fs::path path = CreateProject(dir);
    {
        Session s = OpenSession(path);
        CHECK(Committed(AddLayer(s, "first", 0)));
    }
    // The child commits durably and dies before its result is returned.
    CHECK(RunChild({"child", "kill-after-commit", path.string()}) == fault::kKillExitCode);

    Session s = OpenSession(path);
    CHECK(s.report.ok());
    CHECK(s.doc->revision() == 2);
    Container& c = s.store->container();
    const std::int64_t revisions = Count(c, "SELECT COUNT(*) FROM revision");
    CHECK(revisions == 3);
    // The retry (same key, same request, its original precondition) returns the stored outcome.
    const RequestOutcome retry = AddLayer(s, "killed", 1);
    CHECK(retry.decision.admission == Admission::stored_outcome);
    CHECK(!retry.result && retry.decision.record);
    CHECK(retry.decision.record->committed_revision == 2);
    CHECK(retry.decision.record->request_hash == Req("killed", 1).request_hash());
    CHECK(std::get<json::Object>(retry.decision.record->outcome.data).at("status") == json::Value("committed"));
    CHECK(Count(c, "SELECT COUNT(*) FROM revision") == revisions);
    // A changed request with the same key is a conflict, and creates nothing.
    const RequestOutcome changed = AddLayer(s, "killed", 1, "another name");
    CHECK(changed.decision.admission == Admission::idempotency_conflict);
    CHECK(!changed.result && changed.decision.record->committed_revision == 2);
    CHECK(Count(c, "SELECT COUNT(*) FROM revision") == revisions);
    // Still the stored outcome once the current revision is newer.
    CHECK(Committed(AddLayer(s, "later", 2)));
    const RequestOutcome late = AddLayer(s, "killed", 1);
    CHECK(late.decision.admission == Admission::stored_outcome && late.decision.current_revision == 3);
    CHECK(Count(c, "SELECT COUNT(*) FROM revision") == revisions + 1);
}

// ── 3.5 Unknown-key rules against the stored rows ────────────────────────────────────────────

void UnknownKeyRules() {
    const fs::path dir = WorkDir("unknown-key");
    const fs::path path = CreateProject(dir);
    Session s = OpenSession(path);
    Container& c = s.store->container();

    const RequestOutcome missing = AddLayer(s, "u1", std::nullopt);
    CHECK(missing.decision.admission == Admission::outcome_unknown && missing.decision.current_revision == 0);
    CHECK(!missing.result);
    const RequestOutcome stale = AddLayer(s, "u2", 5);
    CHECK(stale.decision.admission == Admission::stale_revision);
    CHECK(stale.decision.expected_revision == 5 && stale.decision.current_revision == 0);
    const RequestOutcome run = AddLayer(s, "u3", 0);
    CHECK(Committed(run) && run.result->revision == 1);
    CHECK(Count(c, "SELECT COUNT(*) FROM revision") == 2);
    CHECK(Committed(AddLayer(s, "u4", 1)));

    // The horizon comes from meta.operation_horizon_revision: a precondition below it is expired.
    c.SetMeta("operation_horizon_revision", "1");
    const RequestOutcome expired = AddLayer(s, "u5", 0);
    CHECK(expired.decision.admission == Admission::outcome_unknown && expired.decision.current_revision == 2);
    const RequestOutcome at_horizon = AddLayer(s, "u6", 1);
    CHECK(at_horizon.decision.admission == Admission::stale_revision);

    // Stored rows that cannot be read: the call cannot be resolved and is not executed.
    {
        Statement q(c, "UPDATE operation SET outcome = ? WHERE idempotency_key = 'u3'");
        q.BindBlob(1, "not zstd").Run();
    }
    const RequestOutcome unreadable = AddLayer(s, "u3", 2);
    CHECK(unreadable.decision.admission == Admission::outcome_unknown && !unreadable.result);
    CHECK(Count(c, "SELECT COUNT(*) FROM revision") == 3);
    s.doc.reset();
    s.store.reset();
    // Reopened, the row is reported and its key still cannot be executed again.
    Session reopened = OpenSession(path);
    CHECK(reopened.report.corrupt.size() == 1);
    CHECK(reopened.report.corrupt[0].kind == "operation" && reopened.report.corrupt[0].key == "u3");
    CHECK(!reopened.doc->FindOperation("u3") && reopened.doc->FindOperation("u4"));
    CHECK(AddLayer(reopened, "u3", 2).decision.admission == Admission::outcome_unknown);
    CHECK(Count(reopened.store->container(), "SELECT COUNT(*) FROM revision") == 3);
}

// ── 3.6 Deduplication ────────────────────────────────────────────────────────────────────────

void Deduplication() {
    const fs::path dir = WorkDir("dedup");
    const fs::path path = CreateProject(dir);
    const std::string bytes = Noise(64 * 1024, 3);
    const std::string sha = Sha256Hex(bytes);
    Session s = OpenSession(path);
    ImportBound(s, "import-a", bytes, "a.png");
    ImportBound(s, "import-b", bytes, "b.png");
    Container& c = s.store->container();
    CHECK(Count(c, "SELECT COUNT(*) FROM blob") == 1);
    CHECK(Count(c, "SELECT COUNT(*) FROM blob_meta WHERE sha256 = '" + sha + "'") == 2);
    {
        Statement q(c, "SELECT name, usage, color_space FROM blob_meta ORDER BY name");
        CHECK(q.Step() && q.Text(0) == "a.png" && q.Text(1) == "TEXTURE" && q.Text(2) == "sRGB");
        CHECK(q.Step() && q.Text(0) == "b.png");
        CHECK(!q.Step());
    }
    {
        Statement q(c, "SELECT size, zstd_size, length(data), mime FROM blob");
        CHECK(q.Step());
        CHECK(q.Int(0) == static_cast<std::int64_t>(bytes.size()) && q.Int(1) == q.Int(2) && q.Text(3) == "image/png");
    }
    CHECK(s.store->ReadResource(sha) == bytes);  // the original bytes, unmodified
    CHECK(s.doc->snapshot().project->resources.at(sha).size() == 2);
}

// ── 3.7 Versioning ───────────────────────────────────────────────────────────────────────────

void VersioningNewerMajor() {
    const fs::path dir = WorkDir("newer-major");
    const fs::path path = CreateProject(dir);
    Container::Open(path).SetMeta("format_version", "2.0.0");
    const std::string before = ReadBytes(path);
    const auto error = EXPECT_THROW(StoreError, ProjectStore::Open(path));
    CHECK(error.code() == StoreError::Code::version);
    CHECK(Contains(error.what(), "2.0.0") && Contains(error.what(), "newer") && Contains(error.what(), "1.0.0"));
    CHECK(ReadBytes(path) == before);
    CHECK(!fs::exists(dir / "project.uzp-journal"));
}

VersionPolicy NextMinorPolicy() {
    VersionPolicy policy{FormatVersion{1, 1, 0}, {}};
    policy.migrations.push_back(Migration{0, [](json::Object& manifest) { manifest["migrated_to_1_1"] = true; }});
    return policy;
}

void VersioningOlderMinor() {
    const fs::path dir = WorkDir("older-minor");
    Project project = BaseProject();
    project.extra["future_top"] = json::Object{{"kept", json::Array{1, "two"}}};
    project.versions.extra["future_versions_key"] = "kept";
    const fs::path path = CreateProject(dir, {}, project);
    {
        Session s = OpenSession(path);
        CHECK(Committed(AddLayer(s, "a", 0)));
    }
    const std::string before = ReadBytes(path);
    {
        Session s = OpenSession(path, OpenOptions{VerifyLevel::standard, NextMinorPolicy()});
        CHECK(s.migrated);
        const Project& p = *s.doc->snapshot().project;
        CHECK(p.versions.format_version == "1.1.0");
        CHECK(p.extra.at("migrated_to_1_1") == json::Value(true));
        CHECK(p.extra.at("future_top") == project.extra.at("future_top"));
        CHECK(p.versions.extra.at("future_versions_key") == json::Value("kept"));
    }
    CHECK(ReadBytes(path) == before);  // nothing written before the next commit
    CHECK(Container::Open(path).Meta("format_version") == "1.0.0");
    {
        Session s = OpenSession(path, OpenOptions{VerifyLevel::standard, NextMinorPolicy()});
        CHECK(Committed(AddLayer(s, "b", 1)));
    }
    {
        Container c = Container::Open(path);
        CHECK(c.Meta("format_version") == "1.1.0");
        const Project now = LoadManifest(StoredManifest(c, 2));
        CHECK(now.versions.format_version == "1.1.0" && now.extra.count("migrated_to_1_1") == 1);
        CHECK(now.extra.at("future_top") == project.extra.at("future_top"));
        CHECK(LoadManifest(StoredManifest(c, 1)).versions.format_version == "1.0.0");  // history unchanged
    }
    {
        Session s = OpenSession(path, OpenOptions{VerifyLevel::standard, NextMinorPolicy()});
        CHECK(!s.migrated);
    }
    // A reader of 1.0 opens the newer minor as it is, unknown keys kept.
    Session s = OpenSession(path);
    CHECK(!s.migrated);
    CHECK(s.doc->snapshot().project->extra.count("migrated_to_1_1") == 1);
    CHECK(Committed(AddLayer(s, "c", 2)));
    CHECK(LoadManifest(StoredManifest(s.store->container(), 3)).extra.count("migrated_to_1_1") == 1);
    // A missing migration step is an explicit error.
    const fs::path other = CreateProject(WorkDir("older-minor-gap"));
    VersionPolicy gap{FormatVersion{1, 2, 0}, {}};
    gap.migrations.push_back(Migration{1, [](json::Object&) {}});
    const auto error = EXPECT_THROW(StoreError, ProjectStore::Open(other, OpenOptions{VerifyLevel::standard, gap}));
    CHECK(error.code() == StoreError::Code::version && Contains(error.what(), "1.0 to 1.1"));
}

// ── 3.8 Portable and non-portable dependencies ───────────────────────────────────────────────

void NonPortableMissing() {
    const fs::path dir = WorkDir("non-portable");
    const fs::path path = CreateProject(dir, CreateOptions{false, {}, {}});
    const fs::path hdri = dir / "studio.hdr";
    const std::string bytes = Noise(4096, 5);
    WriteBytes(hdri, bytes);
    Id uid = kNoId;
    std::string sha;
    {
        Session s = OpenSession(path);
        CHECK(!s.store->portable());
        const RequestOutcome done = s.store->Submit(*s.doc, Req("link", 0), [&](Edit& e) {
            sha = s.store->StageLocator(hdri);
            CHECK(s.store->ReadResource(sha) == bytes);  // a staged locator is read too (decision 240)
            e.project().resources[sha] = {Meta(e.AllocateId(), "studio.hdr", bytes.size())};
            uid = e.Insert(kTop, NodeType::FillLayer, "lit");
            Layer& layer = *FindLayer(e.project(), uid);
            layer.fill->sources[ChannelType::BaseColor] = Source{BitmapSource{{sha, std::nullopt, {}}, "sRGB", {}}};
            layer.fill->active_channels = {ChannelType::BaseColor};
        });
        CHECK(Committed(done));
        CHECK(Count(s.store->container(), "SELECT COUNT(*) FROM blob") == 0);
        CHECK(Count(s.store->container(), "SELECT COUNT(*) FROM locator") == 1);
        CHECK(s.store->ReadResource(sha) == bytes);
    }
    {
        Session s = OpenSession(path);
        CHECK(s.report.ok());
    }
    fs::remove(hdri);
    Session s = OpenSession(path);
    CHECK(s.report.corrupt.empty() && s.report.missing.size() == 1);
    const MissingDependency& missing = s.report.missing[0];
    CHECK(missing.sha256 == sha && missing.reason == "absent" && Contains(missing.path, "studio.hdr"));
    CHECK(missing.nodes.size() == 1 && missing.nodes[0].id == uid);
    const auto error = EXPECT_THROW(StoreError, s.store->ReadResource(sha));
    CHECK(error.code() == StoreError::Code::missing_dependency);
    WriteBytes(hdri, "changed");
    s.doc.reset();
    s.store.reset();  // releases the project lock (one owner at a time)
    {
        Session changed = OpenSession(path);
        CHECK(changed.report.missing.size() == 1 && changed.report.missing[0].reason == "changed");
    }

    // A portable project embeds every dependency: no locators, and no commit without the bytes.
    const fs::path portable = CreateProject(WorkDir("portable"));
    Session p = OpenSession(portable);
    CHECK(p.store->portable());
    CHECK(EXPECT_THROW(StoreError, p.store->StageLocator(hdri)).code() == StoreError::Code::conflict);
    const std::string unknown = Sha256Hex("never staged");
    const RequestOutcome refused = p.store->Submit(*p.doc, Req("unstaged", 0), [&](Edit& e) {
        e.project().resources[unknown] = {Meta(e.AllocateId(), "ghost.png", 12)};
    });
    CHECK(refused.result && refused.result->status == ResultStatus::failed);
    CHECK(Contains(refused.result->error, "missing_resource"));
    CHECK(p.doc->revision() == 0 && Count(p.store->container(), "SELECT COUNT(*) FROM revision") == 1);
}

// ── 2.5 Round trip through the file ──────────────────────────────────────────────────────────

void RoundTrip() {
    const fs::path dir = WorkDir("round-trip");
    const fs::path path = CreateProject(dir);
    Snapshot last;
    std::vector<OperationRecord> records;
    {
        Session s = OpenSession(path);
        CHECK(Committed(AddLayer(s, "a", 0)));
        ImportBound(s, "import", "bytes of a bitmap", "bitmap.png");
        CHECK(Committed(AddLayer(s, "c", 2)));
        // A no-op and a failed call write nothing.
        const RequestOutcome noop = s.store->Submit(*s.doc, Req("noop", 3), [](Edit&) {});
        CHECK(noop.result && noop.result->status == ResultStatus::no_op);
        const RequestOutcome failed =
            s.store->Submit(*s.doc, Req("fails", 3), [](Edit&) { throw ValueError("rejected by the call"); });
        CHECK(failed.result && failed.result->status == ResultStatus::failed);
        last = s.doc->snapshot();
        records = s.doc->operations();
    }
    Session s = OpenSession(path, OpenOptions{VerifyLevel::full, VersionPolicy::Current()});
    CHECK(s.report.ok());
    CHECK(s.doc->revision() == 3 && *s.doc->snapshot().project == *last.project);
    CHECK(s.doc->operations() == records && records.size() == 3);
    Container& c = s.store->container();
    CHECK(Count(c, "SELECT COUNT(*) FROM operation") == 3);
    CHECK(Count(c, "SELECT COUNT(*) FROM revision") == 4);
    {
        Statement q(c, "SELECT manifest_sha256 FROM revision WHERE revision = 3");
        CHECK(q.Step() && q.Text(0) == ManifestDigest(*last.project));
    }
    // Commit extensions run inside the mutation's transaction; one that throws rolls it back.
    std::int64_t seen = -1;
    s.store->AddCommitExtension([&](Container& inner, const Snapshot& snapshot) {
        seen = snapshot.revision;
        CHECK(Count(inner, "SELECT COUNT(*) FROM revision WHERE revision = " + std::to_string(snapshot.revision)) == 0);
        if (snapshot.project->texture_sets[0].stacks[0].root_layers.size() > 4) throw std::runtime_error("plane rows refused");
    });
    CHECK(Committed(AddLayer(s, "d", 3)) && seen == 4);
    const RequestOutcome refused = AddLayer(s, "e", 4);
    CHECK(refused.result && refused.result->status == ResultStatus::failed && seen == 5);
    CHECK(Contains(refused.result->error, "plane rows refused"));
    CHECK(Count(c, "SELECT COUNT(*) FROM revision") == 5 && !s.doc->FindOperation("e"));
}

// ── phase1.5_store-planes: raster planes ─────────────────────────────────────────────────────

/// Deterministic synthetic texels (the test writer of 2.8): xorshift bytes seeded by `seed`.
PlaneImage Synthetic(ChannelFormat format, int width, int height, std::uint64_t seed) {
    PlaneImage image{width, height, format, {}};
    image.texels = Noise(static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * TexelBytes(format),
                         seed * 0x9E3779B97F4A7C15ull + 1);
    return image;
}

/// The texel bytes of chunk (x, y) cut out of a whole image.
std::string ChunkOf(const PlaneImage& image, int x, int y) {
    const std::size_t bpt = TexelBytes(image.format);
    const int w = std::min(kChunkSize, image.width - x * kChunkSize);
    const int h = std::min(kChunkSize, image.height - y * kChunkSize);
    std::string out;
    for (int r = 0; r < h; ++r) {
        const std::size_t at = ((static_cast<std::size_t>(y) * kChunkSize + r) * image.width +
                                static_cast<std::size_t>(x) * kChunkSize) * bpt;
        out.append(image.texels, at, static_cast<std::size_t>(w) * bpt);
    }
    return out;
}

/// Flips the bits of `mask` in every byte of texel (x, y) of `image`.
void Poke(PlaneImage& image, int x, int y, char mask) {
    const std::size_t bpt = TexelBytes(image.format);
    const std::size_t at = (static_cast<std::size_t>(y) * image.width + x) * bpt;
    for (std::size_t i = 0; i < bpt; ++i) image.texels[at + i] = static_cast<char>(image.texels[at + i] ^ mask);
}

RequestOutcome Mutate(Session& s, const std::string& key, const std::function<void(Edit&)>& call) {
    return s.store->Submit(*s.doc, Req(key, s.doc->revision()), call);
}

struct PaintPlane {
    Id node = kNoId;
    Id plane = kNoId;
};

/// A new paint layer named `name` with a BaseColor plane on UV tile 1001.
PaintPlane NewPaintPlane(Session& s, Edit& e, const std::string& name, ChannelFormat format, int width, int height) {
    const Id uid = e.Insert(kTop, NodeType::PaintLayer, name);
    return {uid, s.store->CreatePlane(e, PlaneSpec{uid, ChannelType::BaseColor, 1001, format, width, height})};
}

/// The binding of `plane` in `project`.
VersionRef BoundVersion(const Project& project, Id plane) {
    for (const ManifestBinding& binding : ManifestPlaneBindings(ProjectToJson(project))) {
        if (binding.plane_id == plane && binding.version) return *binding.version;
    }
    throw Failure{"plane " + std::to_string(plane) + " is not bound"};
}

std::vector<ChunkRow> VersionChunks(Container& c, std::int64_t version_id) { return ReadChunkRows(c, version_id); }

/// A mutation whose manifest copies the manifest of `revision` (the revert of 09 §4; the project
/// counter never goes back).
RequestOutcome RevertTo(Session& s, const std::string& key, std::int64_t revision) {
    const Project old = LoadManifest(StoredManifest(s.store->container(), revision));
    return Mutate(s, key, [&](Edit& e) {
        const Id next = e.project().next_id;
        e.project() = old;
        e.project().next_id = next;
    });
}

bool HasPlaneItem(const IntegrityReport& report, Id plane, std::string_view detail, Id node) {
    for (const CorruptItem& item : report.corrupt) {
        if (item.kind == "plane" && item.key == std::to_string(plane) && Contains(item.detail, detail) &&
            item.nodes.size() == 1 && item.nodes[0].id == node && Contains(item.nodes[0].path, "plane_versions")) {
            return true;
        }
    }
    return false;
}

// 3.1 Two paint layers with separate planes on the same channel and UV tile.
void PlanesNoAlias() {
    const fs::path dir = WorkDir("planes-no-alias");
    const fs::path path = CreateProject(dir);
    const PlaneImage a0 = Synthetic(ChannelFormat::sRGB8, 2048, 1024, 1);
    const PlaneImage b0 = Synthetic(ChannelFormat::sRGB8, 2048, 1024, 2);
    PaintPlane a, b;
    {
        Session s = OpenSession(path);
        CHECK(Committed(Mutate(s, "paint", [&](Edit& e) {
            a = NewPaintPlane(s, e, "paint A", ChannelFormat::sRGB8, 2048, 1024);
            b = NewPaintPlane(s, e, "paint B", ChannelFormat::sRGB8, 2048, 1024);
            s.store->WritePlane(e, a.plane, a0);
            s.store->WritePlane(e, b.plane, b0);
            CHECK(s.store->ReadPlane(e.project(), a.plane) == a0);  // the staged content
        })));
        CHECK(a.plane != b.plane);
    }
    {
        // Same set, stack, channel and tile; two rows, two versions.
        Container c = Container::Open(path);
        Statement q(c, "SELECT COUNT(*), COUNT(DISTINCT set_id || '/' || stack_id || '/' || channel || '/' || tile_u || '/' || tile_v) FROM plane");
        CHECK(q.Step() && q.Int(0) == 2 && q.Int(1) == 1);
        CHECK(ReadPlaneRow(c, a.plane)->channel == ChannelType::BaseColor && ReadPlaneRow(c, a.plane)->tile_u == 0);
        CHECK(Count(c, "SELECT COUNT(*) FROM plane_version") == 2);
    }
    std::int64_t painted = 0, edited = 0;
    const PlaneImage a1 = [&] {
        PlaneImage image = a0;
        Poke(image, 1500, 700, 0x11);
        return image;
    }();
    {
        Session s = OpenSession(path, OpenOptions{VerifyLevel::full, VersionPolicy::Current()});
        CHECK(s.report.ok() && s.report.collectable.empty());
        painted = s.doc->revision();
        CHECK(s.store->ReadPlane(painted, a.plane) == a0 && s.store->ReadPlane(painted, b.plane) == b0);
        CHECK(Committed(Mutate(s, "edit A", [&](Edit& e) { s.store->WritePlane(e, a.plane, a1); })));
        edited = s.doc->revision();
        CHECK(s.store->ReadPlane(edited, a.plane) == a1);
        CHECK(s.store->ReadPlane(edited, b.plane) == b0);  // byte-identical, untouched
        CHECK(BoundVersion(*s.doc->snapshot().project, b.plane) ==
              BoundVersion(LoadManifest(StoredManifest(s.store->container(), painted)), b.plane));
        CHECK(Committed(RevertTo(s, "revert", painted)));
        CHECK(s.store->ReadPlane(s.doc->revision(), a.plane) == a0);
        CHECK(s.store->ReadPlane(s.doc->revision(), b.plane) == b0);
    }
    Session s = OpenSession(path, OpenOptions{VerifyLevel::full, VersionPolicy::Current()});
    CHECK(s.report.ok());
    const Project& now = *s.doc->snapshot().project;
    CHECK(s.store->ReadPlane(now, a.plane) == a0 && s.store->ReadPlane(now, b.plane) == b0);
    CHECK(s.store->ReadPlane(edited, a.plane) == a1 && s.store->ReadPlane(edited, b.plane) == b0);
    // Neither plane aliases the other: distinct versions, each holding only its own plane's chunks.
    Container& c = s.store->container();
    const VersionRef va = BoundVersion(now, a.plane), vb = BoundVersion(now, b.plane);
    CHECK(va.version_id != vb.version_id && va.chunk_root != vb.chunk_root);
    for (int x = 0; x < 2; ++x) {
        CHECK(s.store->ReadPlaneChunk(s.doc->revision(), a.plane, x, 0) == ChunkOf(a0, x, 0));
        CHECK(s.store->ReadPlaneChunk(s.doc->revision(), b.plane, x, 0) == ChunkOf(b0, x, 0));
    }
    CHECK(Count(c, "SELECT COUNT(*) FROM plane") == 2);
    CHECK(Count(c, "SELECT COUNT(*) FROM plane_version") == 3);  // a0, b0, a1; the revert made none
}

// 3.2 Copy-on-write: an edit of one chunk of a 4×4-chunk plane.
void PlanesCopyOnWrite() {
    const fs::path dir = WorkDir("planes-cow");
    const fs::path path = CreateProject(dir);
    Session s = OpenSession(path);
    Container& c = s.store->container();
    const PlaneImage original = Synthetic(ChannelFormat::L8, 4096, 4096, 3);
    PaintPlane p;
    CHECK(Committed(Mutate(s, "paint", [&](Edit& e) {
        p = NewPaintPlane(s, e, "paint", ChannelFormat::L8, 4096, 4096);
        s.store->WritePlane(e, p.plane, original);
    })));
    const std::int64_t first = s.doc->revision();
    const VersionRef v1 = BoundVersion(*s.doc->snapshot().project, p.plane);
    const std::vector<ChunkRow> rows1 = VersionChunks(c, v1.version_id);
    CHECK(rows1.size() == 16);
    const std::int64_t blobs = Count(c, "SELECT COUNT(*) FROM blob");
    CHECK(blobs == 16);

    PlaneImage edited = original;
    Poke(edited, 2 * kChunkSize + 5, kChunkSize + 9, 0x42);  // inside chunk (2, 1)
    CHECK(Committed(Mutate(s, "edit", [&](Edit& e) { s.store->WritePlane(e, p.plane, edited); })));
    const VersionRef v2 = BoundVersion(*s.doc->snapshot().project, p.plane);
    CHECK(v2.version_id != v1.version_id);
    CHECK(Count(c, "SELECT COUNT(*) FROM blob") == blobs + 1);  // exactly one new chunk blob
    const std::vector<ChunkRow> rows2 = VersionChunks(c, v2.version_id);
    CHECK(rows2.size() == 16);
    int copied = 0;
    for (std::size_t i = 0; i < rows2.size(); ++i) {
        CHECK(rows2[i].x == rows1[i].x && rows2[i].y == rows1[i].y);
        if (rows2[i].sha256 == rows1[i].sha256) {
            ++copied;
        } else {
            CHECK(rows2[i].x == 2 && rows2[i].y == 1);
        }
    }
    CHECK(copied == 15);
    CHECK(VersionChunks(c, v1.version_id) == rows1);  // the previous version is unchanged
    CHECK(s.store->ReadPlane(first, p.plane) == original);
    CHECK(s.store->ReadPlane(s.doc->revision(), p.plane) == edited);

    // Writing the same content again changes nothing: no revision.
    const RequestOutcome same = Mutate(s, "same", [&](Edit& e) { s.store->WritePlane(e, p.plane, edited); });
    CHECK(same.result && same.result->status == ResultStatus::no_op);

    // A committed version refuses any change.
    const std::string vid = std::to_string(v1.version_id);
    CHECK(Contains(EXPECT_THROW(StoreError, c.Exec("INSERT INTO plane_chunk VALUES (" + vid + ", 9, 9, '" + rows1[0].sha256 + "')")).what(),
                   "immutable"));
    CHECK(Contains(EXPECT_THROW(StoreError, c.Exec("UPDATE plane_version SET chunk_root = 'x' WHERE version_id = " + vid)).what(),
                   "immutable"));
    CHECK(Contains(EXPECT_THROW(StoreError, c.Exec("UPDATE plane_chunk SET chunk_x = 7 WHERE version_id = " + vid)).what(),
                   "immutable"));
    CHECK(Contains(EXPECT_THROW(StoreError, c.Exec("UPDATE plane SET width = 1 WHERE plane_id = " + std::to_string(p.plane))).what(),
                   "immutable"));

    // A version no retained manifest binds is listed as collectable, not as a failure.
    c.Exec("INSERT INTO plane_version (version_id, plane_id, created_revision, chunk_root) VALUES (999, " +
           std::to_string(p.plane) + ", 1, '" + ChunkRoot({}) + "')");
    const IntegrityReport report = CheckIntegrity(c, ProjectToJson(*s.doc->snapshot().project), VerifyLevel::full);
    CHECK(report.ok());
    CHECK(report.collectable.size() == 1 && report.collectable[0] == (CollectableRow{"plane_version", 999}));
}

// 3.3 Reads resolve the manifest binding of the requested revision.
void PlanesBindingResolution() {
    const fs::path dir = WorkDir("planes-binding");
    const fs::path path = CreateProject(dir);
    std::vector<std::pair<std::int64_t, PlaneImage>> written;
    PaintPlane p;
    std::int64_t before = 0;
    {
        Session s = OpenSession(path);
        CHECK(Committed(AddLayer(s, "fill", 0)));
        before = s.doc->revision();
        for (std::uint64_t round = 0; round < 3; ++round) {
            const PlaneImage image = Synthetic(ChannelFormat::RGB16, 1024, 2048, 10 + round);
            CHECK(Committed(Mutate(s, "paint " + std::to_string(round), [&](Edit& e) {
                if (round == 0) p = NewPaintPlane(s, e, "paint", ChannelFormat::RGB16, 1024, 2048);
                s.store->WritePlane(e, p.plane, image);
            })));
            written.emplace_back(s.doc->revision(), image);
            CHECK(Committed(AddLayer(s, "unrelated " + std::to_string(round), s.doc->revision())));  // no plane change
        }
    }
    Session s = OpenSession(path);
    for (const auto& [revision, image] : written) {
        CHECK(s.store->ReadPlane(revision, p.plane) == image);
        CHECK(s.store->ReadPlane(revision + 1, p.plane) == image);  // bound unchanged by the next revision
    }
    CHECK(written[0].first < written[1].first && written[1].first < written[2].first);
    const auto unbound = EXPECT_THROW(StoreError, s.store->ReadPlane(before, p.plane));
    CHECK(unbound.code() == StoreError::Code::missing_resource);
}

// 3.4 A chunk without a row reads as the plane's empty value.
void PlanesEmptyChunks() {
    const fs::path dir = WorkDir("planes-empty");
    const fs::path path = CreateProject(dir);
    Session s = OpenSession(path);
    PlaneImage image{3072, 2048, ChannelFormat::RGB16F, {}};
    image.texels.assign(3072u * 2048u * 6u, '\0');
    const PlaneImage noise = Synthetic(ChannelFormat::RGB16F, 3072, 2048, 4);
    for (const auto& [cx, cy] : {std::pair{0, 0}, std::pair{2, 1}}) {
        for (int y = 0; y < kChunkSize; ++y) {
            const std::size_t at = ((static_cast<std::size_t>(cy) * kChunkSize + y) * 3072 + cx * kChunkSize) * 6;
            std::copy_n(noise.texels.data() + at, kChunkSize * 6, image.texels.data() + at);
        }
    }
    PaintPlane p, empty;
    CHECK(Committed(Mutate(s, "paint", [&](Edit& e) {
        p = NewPaintPlane(s, e, "sparse", ChannelFormat::RGB16F, 3072, 2048);
        empty = NewPaintPlane(s, e, "untouched", ChannelFormat::RGB16F, 3072, 2048);
        s.store->WritePlane(e, p.plane, image);
    })));
    Container& c = s.store->container();
    const std::int64_t revision = s.doc->revision();
    const VersionRef ref = BoundVersion(*s.doc->snapshot().project, p.plane);
    const std::vector<ChunkRow> rows = VersionChunks(c, ref.version_id);
    CHECK(rows.size() == 2 && rows[0].x == 0 && rows[0].y == 0 && rows[1].x == 2 && rows[1].y == 1);
    CHECK(s.store->ReadPlaneChunk(revision, p.plane, 1, 1) == std::string(std::size_t{kChunkSize} * kChunkSize * 6, '\0'));
    CHECK(s.store->ReadPlaneChunk(revision, p.plane, 2, 1) == ChunkOf(image, 2, 1));
    CHECK(s.store->ReadPlane(revision, p.plane) == image);
    // chunk_root: SHA-256 of the canonical JSON of the sorted (chunk_x, chunk_y, sha256) list.
    const std::string expected = Sha256Hex("[[0,0,\"" + rows[0].sha256 + "\"],[2,1,\"" + rows[1].sha256 + "\"]]");
    CHECK(ChunkRoot(rows) == expected && ref.chunk_root == expected);
    CHECK(ChunkRoot({rows[1], rows[0]}) == expected);
    {
        Statement q(c, "SELECT chunk_root FROM plane_version WHERE version_id = ?");
        q.Bind(1, ref.version_id);
        CHECK(q.Step() && q.Text(0) == expected);
    }
    // A plane never written has a version without chunk rows and reads as empty.
    const VersionRef none = BoundVersion(*s.doc->snapshot().project, empty.plane);
    CHECK(VersionChunks(c, none.version_id).empty() && none.chunk_root == Sha256Hex("[]"));
    const PlaneImage blank = s.store->ReadPlane(revision, empty.plane);
    CHECK(blank.width == 3072 && blank.texels == std::string(3072u * 2048u * 6u, '\0'));
}

// 3.5 Every channel format round-trips bit-exact, the mono plane of a mask stack included.
void PlanesNativeFormats() {
    const fs::path dir = WorkDir("planes-formats");
    const fs::path path = CreateProject(dir);
    const std::vector<ChannelFormat> formats = {ChannelFormat::sRGB8, ChannelFormat::L8,     ChannelFormat::RGB8,
                                                ChannelFormat::L16,   ChannelFormat::RGB16,  ChannelFormat::L16F,
                                                ChannelFormat::RGB16F, ChannelFormat::L32F,  ChannelFormat::RGB32F};
    CHECK(formats.size() == EnumTable<ChannelFormat>::names.size());
    std::vector<std::pair<Id, PlaneImage>> planes;
    {
        Session s = OpenSession(path);
        CHECK(Committed(Mutate(s, "formats", [&](Edit& e) {
            for (std::size_t i = 0; i < formats.size(); ++i) {
                const PlaneImage image = Synthetic(formats[i], 1500, 700, 20 + i);  // partial edge chunks
                const PaintPlane p = NewPaintPlane(s, e, "paint " + std::string(ToString(formats[i])), formats[i], 1500, 700);
                s.store->WritePlane(e, p.plane, image);
                planes.emplace_back(p.plane, image);
            }
            const Id holder = e.Insert(kTop, NodeType::FillLayer, "masked");
            FindLayer(e.project(), holder)->mask = Mask{};
            const Id effect = e.Insert(InsertPosition::Inside(holder, NodeStack::Mask), NodeType::PaintEffect, "mask paint");
            const PlaneImage mono = Synthetic(ChannelFormat::L8, 512, 512, 40);
            const Id plane = s.store->CreatePlane(e, PlaneSpec{effect, std::nullopt, 1001, ChannelFormat::L8, 512, 512});
            CHECK(FindEffect(e.project(), effect)->paint->mono_plane == plane);
            s.store->WritePlane(e, plane, mono);
            planes.emplace_back(plane, mono);
        })));
    }
    Session s = OpenSession(path, OpenOptions{VerifyLevel::full, VersionPolicy::Current()});
    CHECK(s.report.ok());
    for (const auto& [plane, image] : planes) {
        const PlaneImage back = s.store->ReadPlane(s.doc->revision(), plane);
        CHECK(back == image);
        const std::optional<PlaneRow> row = ReadPlaneRow(s.store->container(), plane);
        CHECK(row && row->format == image.format && row->width == image.width && row->chunk_size == kChunkSize);
        CHECK(s.store->ReadPlaneChunk(s.doc->revision(), plane, row->chunks_x() - 1, 0) ==
              ChunkOf(image, row->chunks_x() - 1, 0));
    }
    CHECK(!ReadPlaneRow(s.store->container(), planes.back().first)->channel);  // the mask plane has no channel
}

// 3.6 A worker killed between the plane rows and the revision row.
void PlanesInterruptedCommit() {
    const fs::path dir = WorkDir("planes-interrupted");
    const fs::path path = CreateProject(dir);
    const PlaneImage original = Synthetic(ChannelFormat::L8, 2048, 2048, 50);
    PaintPlane p;
    {
        Session s = OpenSession(path);
        CHECK(Committed(Mutate(s, "paint", [&](Edit& e) {
            p = NewPaintPlane(s, e, "paint", ChannelFormat::L8, 2048, 2048);
            s.store->WritePlane(e, p.plane, original);
        })));
    }
    std::string manifest;
    std::int64_t versions = 0, chunks = 0, blobs = 0;
    {
        Container c = Container::Open(path);
        manifest = StoredManifest(c, 1);
        versions = Count(c, "SELECT COUNT(*) FROM plane_version");
        chunks = Count(c, "SELECT COUNT(*) FROM plane_chunk");
        blobs = Count(c, "SELECT COUNT(*) FROM blob");
    }
    CHECK(RunChild({"child", "kill-in-plane-commit", path.string()}) == fault::kKillExitCode);

    {
        Session s = OpenSession(path, OpenOptions{VerifyLevel::full, VersionPolicy::Current()});
        CHECK(s.report.ok() && s.report.collectable.empty());
        CHECK(s.doc->revision() == 1);
        Container& c = s.store->container();
        CHECK(Count(c, "SELECT COUNT(*) FROM revision") == 2);
        CHECK(StoredManifest(c, 1) == manifest);
        CHECK(SaveManifest(*s.doc->snapshot().project) == manifest);
        CHECK(s.store->ReadPlane(1, p.plane) == original);
        CHECK(Count(c, "SELECT COUNT(*) FROM plane_version") == versions);
        CHECK(Count(c, "SELECT COUNT(*) FROM plane_chunk") == chunks);
        CHECK(Count(c, "SELECT COUNT(*) FROM blob") == blobs);
        CHECK(!s.doc->FindOperation("killed-plane"));
        // The edit commits now.
        const PlaneImage next = Synthetic(ChannelFormat::L8, 2048, 2048, 51);
        CHECK(Committed(s.store->Submit(*s.doc, Req("killed-plane", 1), [&](Edit& e) { s.store->WritePlane(e, p.plane, next); })));
        CHECK(s.store->ReadPlane(2, p.plane) == next && s.store->ReadPlane(1, p.plane) == original);
    }
    Session s = OpenSession(path, OpenOptions{VerifyLevel::full, VersionPolicy::Current()});
    CHECK(s.report.ok() && s.doc->revision() == 2);
}

// 3.7 Corruption: a chunk blob with altered bytes; a chunk row that no longer hashes to chunk_root.
void PlanesCorruption() {
    const PlaneImage a0 = Synthetic(ChannelFormat::sRGB8, 2048, 1024, 60);
    const PlaneImage b0 = Synthetic(ChannelFormat::sRGB8, 2048, 1024, 61);
    const auto make = [&](const std::string& name, PaintPlane& a, PaintPlane& b) {
        const fs::path path = CreateProject(WorkDir(name));
        Session s = OpenSession(path);
        CHECK(Committed(Mutate(s, "paint", [&](Edit& e) {
            a = NewPaintPlane(s, e, "paint A", ChannelFormat::sRGB8, 2048, 1024);
            b = NewPaintPlane(s, e, "paint B", ChannelFormat::sRGB8, 2048, 1024);
            s.store->WritePlane(e, a.plane, a0);
            s.store->WritePlane(e, b.plane, b0);
        })));
        return path;
    };

    // A chunk blob whose bytes were altered on disk (a valid frame of other bytes).
    PaintPlane a, b;
    fs::path path = make("planes-corrupt-blob", a, b);
    {
        Container c = Container::Open(path);
        const std::string sha = Sha256Hex(ChunkOf(a0, 1, 0));
        std::string altered = ChunkOf(a0, 1, 0);
        altered[17] = static_cast<char>(altered[17] ^ 0x01);
        Statement q(c, "UPDATE blob SET data = ? WHERE sha256 = ?");
        q.BindBlob(1, Compress(altered)).Bind(2, sha).Run();
    }
    {
        Session s = OpenSession(path);  // on open
        CHECK(s.report.corrupt.size() == 1);
        CHECK(HasPlaneItem(s.report, a.plane, "SHA-256 mismatch", a.node));
        const auto error = EXPECT_THROW(CorruptionError, s.store->ReadPlane(1, a.plane));
        CHECK(error.item().kind == "plane" && error.item().key == std::to_string(a.plane));
        CHECK(Contains(error.what(), "SHA-256 mismatch") && Contains(error.what(), "node " + std::to_string(a.node)));
        CHECK(s.store->ReadPlane(1, b.plane) == b0);  // the other layer is intact
    }
    {
        Container c = Container::Open(path);  // inspect --verify
        const IntegrityReport report = CheckIntegrity(c, json::Parse(StoredManifest(c, 1)), VerifyLevel::full);
        CHECK(report.corrupt.size() == 1 && HasPlaneItem(report, a.plane, "SHA-256 mismatch", a.node));
    }

    // A plane_chunk row changed to reference another blob.
    path = make("planes-corrupt-row", a, b);
    {
        Container c = Container::Open(path);
        c.Exec("DROP TRIGGER plane_chunk_immutable");  // tampering outside the store
        const VersionRef ref = BoundVersion(LoadManifest(StoredManifest(c, 1)), b.plane);
        Statement q(c, "UPDATE plane_chunk SET sha256 = ? WHERE version_id = ? AND chunk_x = 0 AND chunk_y = 0");
        q.Bind(1, Sha256Hex(ChunkOf(a0, 0, 0))).Bind(2, ref.version_id).Run();
    }
    {
        Container c = Container::Open(path);  // inspect --verify
        const IntegrityReport report = CheckIntegrity(c, json::Parse(StoredManifest(c, 1)), VerifyLevel::full);
        CHECK(report.corrupt.size() == 1 && HasPlaneItem(report, b.plane, "chunk_root mismatch", b.node));
    }
    Session s = OpenSession(path);  // on open
    CHECK(s.report.corrupt.size() == 1 && HasPlaneItem(s.report, b.plane, "chunk_root mismatch", b.node));
    const auto error = EXPECT_THROW(CorruptionError, s.store->ReadPlane(1, b.plane));
    CHECK(Contains(error.what(), "chunk_root mismatch") && Contains(error.what(), "node " + std::to_string(b.node)));
    CHECK(s.store->ReadPlane(1, a.plane) == a0);
}

// 2.1, 2.5, 2.7: the commit binds exactly the planes the nodes hold; plane rows are not unique.
void PlanesBindingRules() {
    const fs::path dir = WorkDir("planes-rules");
    const fs::path path = CreateProject(dir);
    Session s = OpenSession(path);
    Container& c = s.store->container();
    // A plane id set by hand has no content binding: the commit refuses it and writes nothing.
    const RequestOutcome unbound = Mutate(s, "unbound", [&](Edit& e) {
        const Id uid = e.Insert(kTop, NodeType::PaintLayer, "hand made");
        FindLayer(e.project(), uid)->paint->planes[ChannelType::BaseColor] = e.AllocateId();
    });
    CHECK(unbound.result && unbound.result->status == ResultStatus::failed);
    CHECK(Contains(unbound.result->error, "without a content binding"));
    CHECK(s.doc->revision() == 0 && Count(c, "SELECT COUNT(*) FROM plane") == 0);
    // A binding of a plane the node does not hold is refused too.
    const RequestOutcome stray = Mutate(s, "stray", [&](Edit& e) {
        const Id uid = e.Insert(kTop, NodeType::PaintLayer, "stray");
        FindLayer(e.project(), uid)->paint->extra["plane_versions"] =
            json::Object{{"77", VersionRef{1, ChunkRoot({})}.ToJson()}};
    });
    CHECK(stray.result && stray.result->status == ResultStatus::failed && Contains(stray.result->error, "does not hold"));
    // Wrong image size, a second plane on one channel, a fill layer: rejected by the call.
    PaintPlane p;
    const RequestOutcome wrong = Mutate(s, "wrong", [&](Edit& e) {
        p = NewPaintPlane(s, e, "paint", ChannelFormat::L8, 256, 256);
        s.store->WritePlane(e, p.plane, Synthetic(ChannelFormat::L8, 128, 128, 1));
    });
    CHECK(wrong.result && wrong.result->status == ResultStatus::failed && Contains(wrong.result->error, "256x256"));
    const RequestOutcome twice = Mutate(s, "twice", [&](Edit& e) {
        p = NewPaintPlane(s, e, "paint", ChannelFormat::L8, 256, 256);
        s.store->CreatePlane(e, PlaneSpec{p.node, ChannelType::BaseColor, 1001, ChannelFormat::L8, 256, 256});
    });
    CHECK(twice.result && twice.result->status == ResultStatus::failed && Contains(twice.result->error, "already holds"));
    const RequestOutcome fill = Mutate(s, "fill", [&](Edit& e) {
        const Id uid = e.Insert(kTop, NodeType::FillLayer, "fill");
        s.store->CreatePlane(e, PlaneSpec{uid, ChannelType::BaseColor, 1001, ChannelFormat::L8, 256, 256});
    });
    CHECK(fill.result && fill.result->status == ResultStatus::failed && Contains(fill.result->error, "not a paint"));
    const RequestOutcome tile = Mutate(s, "tile", [&](Edit& e) {
        const Id uid = e.Insert(kTop, NodeType::PaintLayer, "udim");
        s.store->CreatePlane(e, PlaneSpec{uid, ChannelType::BaseColor, 1002, ChannelFormat::L8, 256, 256});
    });
    CHECK(tile.result && tile.result->status == ResultStatus::failed && Contains(tile.result->error, "UV tile 1002"));
    CHECK(s.doc->revision() == 0 && Count(c, "SELECT COUNT(*) FROM plane_version") == 0);

    // Three planes on one set/stack/channel/tile coexist; deleting a node drops its binding.
    std::vector<PaintPlane> three(3);
    CHECK(Committed(Mutate(s, "three", [&](Edit& e) {
        for (int i = 0; i < 3; ++i) {
            three[static_cast<std::size_t>(i)] = NewPaintPlane(s, e, "layer " + std::to_string(i), ChannelFormat::L8, 256, 256);
            s.store->WritePlane(e, three[static_cast<std::size_t>(i)].plane, Synthetic(ChannelFormat::L8, 256, 256, 70 + static_cast<std::uint64_t>(i)));
        }
    })));
    CHECK(Count(c, "SELECT COUNT(*) FROM plane") == 3);
    CHECK(Committed(Mutate(s, "delete", [&](Edit& e) {
        auto& layers = e.project().texture_sets[0].stacks[0].root_layers;
        layers.erase(std::remove_if(layers.begin(), layers.end(), [&](const Layer& l) { return l.uid == three[0].node; }),
                     layers.end());
    })));
    CHECK(ManifestPlaneBindings(ProjectToJson(*s.doc->snapshot().project)).size() == 2);
    CHECK(s.store->ReadPlane(1, three[0].plane) == Synthetic(ChannelFormat::L8, 256, 256, 70));  // still in history
    s.doc.reset();
    s.store.reset();
    Session reopened = OpenSession(path);
    CHECK(reopened.report.ok() && reopened.report.collectable.empty());

    // A new project holds no planes.
    Project with_plane = BaseProject();
    const Id painted = InsertNode(with_plane, kTop, NodeType::PaintLayer, "paint");
    FindLayer(with_plane, painted)->paint->planes[ChannelType::BaseColor] = with_plane.AllocateId();
    EXPECT_THROW(ValueError, ProjectStore::Create(dir / "with-plane.uzp", NewState(with_plane)));
    CHECK(!fs::exists(dir / "with-plane.uzp"));
}

// ── Child processes ──────────────────────────────────────────────────────────────────────────

int Child(const std::string& fault_name, const fs::path& path) {
    Session s = OpenSession(path);
    const std::int64_t base = s.doc->revision();
    if (fault_name == "kill-during-commit") {
        fault::Arm(fault::Fault::kill_during_commit);
        s.store->Submit(*s.doc, Req("killed", base), [&](Edit& e) {
            const std::string sha = s.store->StageResource(Noise(200000, 7), "image/png");
            e.project().resources[sha] = {Meta(e.AllocateId(), "killed.png", 200000)};
            e.Insert(kTop, NodeType::FillLayer, "killed");
        });
    } else if (fault_name == "kill-after-commit") {
        fault::Arm(fault::Fault::kill_after_commit);
        AddLayer(s, "killed", base);
    } else if (fault_name == "kill-in-plane-commit") {
        const Id plane = ManifestPlaneBindings(ProjectToJson(*s.doc->snapshot().project)).at(0).plane_id;
        fault::Arm(fault::Fault::kill_before_revision_row);
        s.store->Submit(*s.doc, Req("killed-plane", base), [&](Edit& e) {
            s.store->WritePlane(e, plane, Synthetic(ChannelFormat::L8, 2048, 2048, 51));
        });
    } else {
        std::fprintf(stderr, "unknown fault %s\n", fault_name.c_str());
        return 2;
    }
    std::fprintf(stderr, "the fault hook did not terminate the process\n");
    return 1;
}

int Run(const std::string& only) {
    const std::vector<std::pair<const char*, std::function<void()>>> cases = {
        {"schema_and_pragmas", SchemaAndPragmas},     // 2.2
        {"commit_atomicity", CommitAtomicity},        // 3.1
        {"disk_full", DiskFull},                      // 3.2
        {"corrupt_blob", CorruptBlob},                // 3.3
        {"corrupt_manifest", CorruptManifest},        // 3.3
        {"commit_then_die", CommitThenDie},           // 3.4
        {"unknown_key_rules", UnknownKeyRules},       // 3.5
        {"deduplication", Deduplication},             // 3.6
        {"versioning_newer_major", VersioningNewerMajor},  // 3.7
        {"versioning_older_minor", VersioningOlderMinor},  // 3.7
        {"non_portable_missing", NonPortableMissing},  // 3.8
        {"round_trip", RoundTrip},                     // 2.3-2.6
        {"planes_no_alias", PlanesNoAlias},                    // planes 3.1
        {"planes_copy_on_write", PlanesCopyOnWrite},           // planes 3.2
        {"planes_binding_resolution", PlanesBindingResolution},  // planes 3.3
        {"planes_empty_chunks", PlanesEmptyChunks},            // planes 3.4
        {"planes_native_formats", PlanesNativeFormats},        // planes 3.5
        {"planes_interrupted_commit", PlanesInterruptedCommit},  // planes 3.6
        {"planes_corruption", PlanesCorruption},               // planes 3.7
        {"planes_binding_rules", PlanesBindingRules},          // planes 2.1, 2.5, 2.7
    };
    int failed = 0;
    int ran = 0;
    for (const auto& [name, body] : cases) {
        if (!only.empty() && only != name) continue;
        ++ran;
        fault::Arm(fault::Fault::none);
        try {
            body();
            std::printf("PASS %s\n", name);
        } catch (const Failure& failure) {
            ++failed;
            std::printf("FAIL %s: %s\n", name, failure.message.c_str());
        } catch (const std::exception& error) {
            ++failed;
            std::printf("FAIL %s: unexpected exception: %s\n", name, error.what());
        }
        std::fflush(stdout);
    }
    std::printf("%d cases, %d failed\n", ran, failed);
    if (failed == 0) {
        std::error_code ec;
        fs::remove_all(fs::temp_directory_path() / ("uzp-store-tests-" + std::to_string(GetCurrentProcessId())), ec);
    }
    return failed == 0 && ran > 0 ? 0 : 1;
}

int Command(int argc, char** argv) {
    const std::string command = argc > 1 ? argv[1] : "";
    if (command == "run") return Run(argc > 2 ? argv[2] : "");
    if (command == "child" && argc == 4) return Child(argv[2], fs::path(argv[3]));
    std::fprintf(stderr, "usage: uzp-store-tests run [case] | child <fault> <file>\n");
    return 2;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        return Command(argc, argv);
    } catch (const std::exception& error) {
        std::fprintf(stderr, "Error: %s\n", error.what());
    }
    return 3;
}
