// Native tests of saving, retention, compaction, revert and the lock sidecar of the project store
// (`src/store/save.h`, `compact.h`, `lock.h`; task phase1.6_store-save-retention).
// Built by `zig build uzp-store-save-tests` with the test-only fault hooks (`src/store/fault.h`)
// and driven by tests/store/test_store_save.py.
//
// Usage:
//   uzp-store-save-tests run [case]                 run every native case (or one); exit 0 when all pass
//   uzp-store-save-tests child <action> <file> [<target>]
//                                                   open <file> and run <action>:
//                                                   compact-kill-during-vacuum, compact-kill-before-rename,
//                                                   save-as-kill-during-vacuum (to <target>) or kill-holding-lock
//                                                   (each terminates the process with exit code 77), or
//                                                   hold-lock (keep the project open until <target> exists)
// Cases that need an interrupted or a concurrent worker start this executable again as a child.

#include <windows.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include "store/compact.h"
#include "store/container.h"
#include "store/fault.h"
#include "store/integrity.h"
#include "store/lock.h"
#include "store/planes.h"
#include "store/project_store.h"
#include "store/save.h"
#include "uzp_core/document/document.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/manifest.h"
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

constexpr const char* kUuid = "6f1c2a3e-0000-4000-8000-0000000000bb";
constexpr Id kSet = 1, kStack = 3;
const InsertPosition kTop = InsertPosition::FromStack(kSet, kStack);
constexpr unsigned kKilled = fault::kKillExitCode;

Project BaseProject() {
    Project p;
    p.versions.app_version = "0.0.0";
    p.versions.evaluator_profile = "painter-12.1-layerq-linear";
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

MutationRequest Req(const std::string& key, std::optional<std::int64_t> expected, const std::string& tool = "layer_insert") {
    return MutationRequest{tool, json::Object{{"name", key}}, key, expected};
}

fs::path WorkDir(const std::string& name) {
    const fs::path dir = fs::temp_directory_path() /
                         ("uzp-store-save-tests-" + std::to_string(GetCurrentProcessId())) / name;
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

fs::path With(const fs::path& path, const char* suffix) {
    fs::path out = path;
    out += suffix;
    return out;
}

/// No `-wal`, `-shm` or `-journal` companion beside `path`.
bool AtRest(const fs::path& path) {
    return !fs::exists(With(path, "-wal")) && !fs::exists(With(path, "-shm")) && !fs::exists(With(path, "-journal"));
}

/// The temporary files of `compact` and `save_as` are gone.
bool NoTemporaries(const fs::path& path) {
    return !fs::exists(With(path, ".compact")) && !fs::exists(With(path, ".vacuum")) &&
           !fs::exists(With(path, ".compact-journal")) && !fs::exists(With(path, ".vacuum-journal"));
}

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

PlaneImage Synthetic(int width, int height, std::uint64_t seed) {
    PlaneImage image{width, height, ChannelFormat::L8, {}};
    image.texels = Noise(static_cast<std::size_t>(width) * static_cast<std::size_t>(height), seed * 0x9E3779B97F4A7C15ull + 1);
    return image;
}

/// `image` with texel (x, y) flipped (inside chunk (x / 1024, y / 1024)).
PlaneImage Poked(PlaneImage image, int x, int y) {
    const std::size_t at = static_cast<std::size_t>(y) * static_cast<std::size_t>(image.width) + static_cast<std::size_t>(x);
    image.texels[at] = static_cast<char>(image.texels[at] ^ 0x5a);
    return image;
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

    void Close() {
        doc.reset();
        if (store) store->Close();
        store.reset();
    }
};

Session OpenSession(const fs::path& path, VerifyLevel verify = VerifyLevel::standard) {
    ProjectStore::Opened opened = ProjectStore::Open(path, OpenOptions{verify, VersionPolicy::Current()});
    Session s{std::move(opened.store), std::make_unique<Document>(std::move(opened.state)), opened.report};
    s.store->Attach(*s.doc);
    return s;
}

fs::path CreateProject(const fs::path& dir, const std::string& name = "project.uzp") {
    const fs::path path = dir / name;
    DocumentState state;
    state.project_uuid = kUuid;
    state.project = BaseProject();
    ProjectStore::Create(path, state);
    return path;
}

bool Committed(const RequestOutcome& outcome) {
    return outcome.decision.admission == Admission::execute && outcome.result &&
           outcome.result->status == ResultStatus::committed;
}

RequestOutcome Mutate(Session& s, const std::string& key, const std::function<void(Edit&)>& call) {
    return s.store->Submit(*s.doc, Req(key, s.doc->revision()), call);
}

/// A committed fill-layer insertion named after its key.
void AddLayer(Session& s, const std::string& key) {
    CHECK(Committed(Mutate(s, key, [&](Edit& e) { e.Insert(kTop, NodeType::FillLayer, key); })));
}

void AddLayers(Session& s, const std::string& prefix, int count) {
    for (int i = 0; i < count; ++i) AddLayer(s, prefix + std::to_string(s.doc->revision() + 1));
}

/// A committed mutation creating a paint layer with an L8 BaseColor plane holding `image`.
Id Paint(Session& s, const std::string& key, const PlaneImage& image) {
    Id plane = kNoId;
    CHECK(Committed(Mutate(s, key, [&](Edit& e) {
        const Id uid = e.Insert(kTop, NodeType::PaintLayer, key);
        plane = s.store->CreatePlane(e, PlaneSpec{uid, ChannelType::BaseColor, 1001, image.format, image.width, image.height});
        s.store->WritePlane(e, plane, image);
    })));
    return plane;
}

void Repaint(Session& s, const std::string& key, Id plane, const PlaneImage& image) {
    CHECK(Committed(Mutate(s, key, [&](Edit& e) { s.store->WritePlane(e, plane, image); })));
}

RequestOutcome RevertRequest(Session& s, const std::string& key, std::int64_t revision) {
    return s.store->Revert(*s.doc, MutationRequest{"project_revert", json::Object{{"revision", revision}}, key, s.doc->revision()},
                           revision);
}

std::int64_t Count(Container& c, const std::string& sql) {
    Statement q(c, sql);
    return q.Step() ? q.Int(0) : -1;
}

std::vector<std::int64_t> Ints(Container& c, const std::string& sql) {
    Statement q(c, sql);
    std::vector<std::int64_t> out;
    while (q.Step()) out.push_back(q.Int(0));
    return out;
}

std::vector<std::string> Texts(Container& c, const std::string& sql) {
    Statement q(c, sql);
    std::vector<std::string> out;
    while (q.Step()) out.push_back(q.Text(0));
    return out;
}

std::vector<std::int64_t> Range(std::int64_t first, std::int64_t last) {
    std::vector<std::int64_t> out;
    for (std::int64_t i = first; i <= last; ++i) out.push_back(i);
    return out;
}

std::string StoredManifest(Container& c, std::int64_t revision) {
    Statement q(c, "SELECT manifest FROM revision WHERE revision = ?");
    q.Bind(1, revision);
    if (!q.Step()) throw Failure{"no revision " + std::to_string(revision)};
    return Decompress(q.Blob(0));
}

/// The manifest of a revert: the manifest of `revision` with the project counter of `counter`.
std::string WithCounter(const std::string& manifest, const std::string& counter) {
    Project project = LoadManifest(manifest);
    project.next_id = LoadManifest(counter).next_id;
    return SaveManifest(project);
}

/// The manifest and the pixels of every bound plane of each retained revision.
struct State {
    std::string manifest;
    std::map<Id, PlaneImage> planes;

    bool operator==(const State&) const = default;
};

std::map<std::int64_t, State> RetainedStates(ProjectStore& store) {
    std::map<std::int64_t, State> states;
    for (const std::int64_t revision : Ints(store.container(), "SELECT revision FROM revision ORDER BY revision")) {
        State state{StoredManifest(store.container(), revision), {}};
        for (const ManifestBinding& binding : ManifestPlaneBindings(json::Parse(state.manifest))) {
            state.planes[binding.plane_id] = store.ReadPlane(revision, binding.plane_id);
        }
        states[revision] = std::move(state);
    }
    return states;
}

/// 3.5: computed from the retained manifests alone, every plane, version, chunk row and blob is
/// reachable and every reachable one is stored.
void CheckReachability(Container& c) {
    std::set<std::int64_t> versions;
    std::set<std::int64_t> planes;
    std::set<std::string> hashes;
    for (const std::int64_t revision : Ints(c, "SELECT revision FROM revision")) {
        const std::string text = StoredManifest(c, revision);
        for (const auto& [sha256, names] : LoadManifest(text).resources) hashes.insert(sha256);
        for (const ManifestBinding& binding : ManifestPlaneBindings(json::Parse(text))) {
            CHECK(binding.version);
            versions.insert(binding.version->version_id);
            planes.insert(static_cast<std::int64_t>(binding.plane_id));
        }
    }
    for (const std::int64_t version : versions) {
        for (const ChunkRow& row : ReadChunkRows(c, version)) hashes.insert(row.sha256);
    }
    const auto as_set = [](const std::vector<std::int64_t>& v) { return std::set<std::int64_t>(v.begin(), v.end()); };
    CHECK(as_set(Ints(c, "SELECT version_id FROM plane_version")) == versions);
    CHECK(as_set(Ints(c, "SELECT plane_id FROM plane")) == planes);
    for (const std::int64_t version : Ints(c, "SELECT DISTINCT version_id FROM plane_chunk")) CHECK(versions.count(version) == 1);
    const std::vector<std::string> blobs = Texts(c, "SELECT sha256 FROM blob");
    CHECK(std::set<std::string>(blobs.begin(), blobs.end()) == hashes);
    for (const std::string& sha256 : Texts(c, "SELECT DISTINCT sha256 FROM blob_meta")) CHECK(hashes.count(sha256) == 1);
    const IntegrityReport report = CheckIntegrity(c, json::Parse(StoredManifest(c, ReadCurrentRevision(c))), VerifyLevel::full);
    CHECK(report.ok() && report.collectable.empty());
}

// ── Child processes ─────────────────────────────────────────────────────────────────────────

/// Starts this executable with `args`; the caller waits on the handle.
HANDLE StartChild(const std::vector<std::string>& args) {
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
    CloseHandle(process.hThread);
    return process.hProcess;
}

DWORD Wait(HANDLE process) {
    WaitForSingleObject(process, 300000);
    DWORD code = 0;
    GetExitCodeProcess(process, &code);
    CloseHandle(process);
    return code;
}

DWORD RunChild(const std::vector<std::string>& args) { return Wait(StartChild(args)); }

std::string Utf8(const fs::path& path) {
    const std::u8string text = path.u8string();
    return std::string(text.begin(), text.end());
}

// ── 3.1 Checkpoints and the dirty flag ──────────────────────────────────────────────────────

void Checkpoints() {
    const fs::path dir = WorkDir("checkpoints");
    const fs::path path = CreateProject(dir);
    {
        Session s = OpenSession(path);
        CHECK(s.doc->NeedsSaving() && s.store->NeedsSaving());  // never saved
        AddLayers(s, "edit ", 7);
        CHECK(s.store->Save(*s.doc) == (uzp::core::Checkpoints{7, 7, std::nullopt}));
        CHECK(!s.doc->NeedsSaving() && !s.store->NeedsSaving());
        CHECK(ReadCheckpoint(s.store->container(), "save-7")->revision == 7);

        // The scenario of the spec: last named checkpoint 7, mutation 8, save.
        AddLayer(s, "edit 8");
        CHECK(s.doc->NeedsSaving() && s.store->NeedsSaving());
        const uzp::core::Checkpoints saved = s.store->Save(*s.doc);
        CHECK(saved == (uzp::core::Checkpoints{8, 8, 7}));
        CHECK(s.doc->checkpoints() == saved && s.store->CheckpointState() == saved);
        CHECK(!s.doc->NeedsSaving() && !s.store->NeedsSaving());
        CHECK(ReadCheckpoint(s.store->container(), "previous")->revision == 7);
        CHECK(s.store->Save(*s.doc) == saved);  // nothing to save: previous stays
        CHECK(s.doc->checkpoints() == saved);

        // Named saves with a note; a reserved name is refused.
        const uzp::core::Checkpoints named = s.store->Save(*s.doc, SaveOptions{"alpha", "first look", false});
        CHECK(named == saved);
        const std::optional<CheckpointRow> alpha = ReadCheckpoint(s.store->container(), "alpha");
        CHECK(alpha && alpha->revision == 8 && alpha->note == "first look" && !alpha->is_protected);
        for (const char* reserved : {"current", "previous"}) {
            const auto refused = EXPECT_THROW(StoreError, s.store->Save(*s.doc, SaveOptions{reserved, "", false}));
            CHECK(refused.code() == StoreError::Code::conflict);
        }
    }
    // Reopened: the checkpoints come back from the file.
    Session s = OpenSession(path);
    CHECK(s.doc->checkpoints() == (uzp::core::Checkpoints{8, 8, 7}) && !s.doc->NeedsSaving());

    // Exact after a revert: revision 9 copies revision 7 (with the counter of revision 8).
    const RequestOutcome reverted = s.store->Revert(
        *s.doc, MutationRequest{"project_revert", json::Object{{"checkpoint", "save-7"}}, "revert", 8}, std::string("save-7"));
    CHECK(Committed(reverted) && s.doc->revision() == 9);
    Container& c = s.store->container();
    CHECK(StoredManifest(c, 9) == WithCounter(StoredManifest(c, 7), StoredManifest(c, 8)));
    CHECK(LoadManifest(StoredManifest(c, 9)).next_id == LoadManifest(StoredManifest(c, 8)).next_id);
    CHECK(Ints(c, "SELECT revision FROM revision ORDER BY revision") == Range(0, 9));  // append-only
    CHECK(s.doc->NeedsSaving() && s.store->NeedsSaving());
    CHECK(s.store->Save(*s.doc) == (uzp::core::Checkpoints{9, 9, 8}) && !s.doc->NeedsSaving());

    // An unknown checkpoint fails the revert explicitly and writes nothing.
    const RequestOutcome unknown = s.store->Revert(
        *s.doc, MutationRequest{"project_revert", json::Object{{"checkpoint", "nope"}}, "revert nope", 9}, std::string("nope"));
    CHECK(unknown.result && unknown.result->status == ResultStatus::failed && Contains(unknown.result->error, "not_retained"));
    CHECK(s.doc->revision() == 9);

    // Exact after save_as_copy: the copy does not save the project.
    AddLayer(s, "edit 10");
    CHECK(s.doc->NeedsSaving() && s.store->NeedsSaving());
    s.store->SaveAsCopy(dir / "copy.uzp");
    CHECK(s.doc->NeedsSaving() && s.store->NeedsSaving());
    CHECK(s.doc->checkpoints() == (uzp::core::Checkpoints{10, 9, 8}));
}

// ── 3.2 Retention window ────────────────────────────────────────────────────────────────────

void RetentionWindow() {
    const fs::path dir = WorkDir("retention");
    const fs::path path = CreateProject(dir);
    Session s = OpenSession(path);
    Container& c = s.store->container();
    // 60 mutations; named checkpoints a (2), approved (4, protected), b (6), c (8); save at 60.
    const std::map<std::int64_t, SaveOptions> saves = {
        {2, {"a", "", false}}, {4, {"approved", "", true}}, {6, {"b", "", false}}, {8, {"c", "", false}}};
    for (std::int64_t revision = 1; revision <= 60; ++revision) {
        AddLayer(s, "m" + std::to_string(revision));
        if (const auto save = saves.find(revision); save != saves.end()) s.store->Save(*s.doc, save->second);
    }
    CHECK(s.store->Save(*s.doc) == (uzp::core::Checkpoints{60, 60, 8}));
    c.Exec("INSERT INTO cache (key, revision, evaluator_profile, sha256) VALUES ('tile', 60, 'p', 'x')");

    std::vector<std::int64_t> expected = {4, 8};
    for (std::int64_t r = 11; r <= 60; ++r) expected.push_back(r);
    const Retention retention = ComputeRetention(c);
    CHECK(std::vector<std::int64_t>(retention.revisions.begin(), retention.revisions.end()) == expected);
    CHECK(retention.mutations == Range(11, 60) && retention.protected_revisions == std::set<std::int64_t>{4});

    const CompactResult result = s.store->Compact(*s.doc);
    CHECK(result.retained == expected);
    CHECK(result.collapsed == (std::vector<std::int64_t>{0, 1, 2, 3, 5, 6, 7, 9, 10}));
    CHECK(result.removed_checkpoints == (std::vector<std::string>{"a", "b"}));
    CHECK(result.horizon == 10 && result.removed_operations == 8);  // revision 0 has no operation row
    CHECK(result.bytes_after > 0 && result.bytes_after < result.bytes_before);

    Container& after = s.store->container();
    CHECK(Ints(after, "SELECT revision FROM revision ORDER BY revision") == expected);
    CHECK(Ints(after, "SELECT committed_revision FROM operation ORDER BY committed_revision") == expected);
    CHECK(Texts(after, "SELECT name FROM checkpoint ORDER BY name") ==
          (std::vector<std::string>{"approved", "c", "current", "previous", "save-60"}));
    CHECK(ReadCheckpoint(after, "approved")->is_protected && ReadCheckpoint(after, "approved")->revision == 4);
    CHECK(after.Meta("operation_horizon_revision") == "10" && s.doc->operation_horizon() == 10);
    CHECK(Count(after, "SELECT COUNT(*) FROM cache") == 0);
    CHECK(s.doc->checkpoints() == (uzp::core::Checkpoints{60, 60, 8}) && !s.doc->NeedsSaving());
    CHECK(AtRest(path) && NoTemporaries(path));

    // Compaction is idempotent; a collapsed revision cannot be reverted to, a protected one can.
    CHECK(s.store->Compact(*s.doc).collapsed.empty());
    const RequestOutcome collapsed = RevertRequest(s, "revert 5", 5);
    CHECK(collapsed.result && collapsed.result->status == ResultStatus::failed &&
          Contains(collapsed.result->error, "not_retained") && s.doc->revision() == 60);
    CHECK(Committed(RevertRequest(s, "revert 4", 4)) && s.doc->revision() == 61);

    s.Close();
    Session reopened = OpenSession(path, VerifyLevel::full);
    CHECK(reopened.report.ok() && reopened.report.collectable.empty());
    CHECK(reopened.doc->checkpoints() == (uzp::core::Checkpoints{61, 60, 8}) && reopened.doc->operation_horizon() == 10);
}

// ── 3.3 Protected checkpoints (QG-05) ───────────────────────────────────────────────────────

void ProtectedCheckpoint() {
    const fs::path dir = WorkDir("protected");
    const fs::path path = CreateProject(dir);
    Session s = OpenSession(path);
    const PlaneImage approved = Synthetic(2048, 1024, 1);
    const Id plane = Paint(s, "paint", approved);
    s.store->Save(*s.doc, SaveOptions{"approved", "client sign-off", true});
    Container& c = s.store->container();
    const std::string manifest = StoredManifest(c, 1);
    const CheckpointRow row = *ReadCheckpoint(c, "approved");
    CHECK(row.is_protected && row.revision == 1);

    Repaint(s, "repaint", plane, Poked(approved, 10, 10));
    for (const bool protect : {false, true}) {
        const auto refused = EXPECT_THROW(StoreError, s.store->Save(*s.doc, SaveOptions{"approved", "", protect}));
        CHECK(refused.code() == StoreError::Code::protected_checkpoint && Contains(refused.what(), "'approved'"));
    }
    const auto refused_as = EXPECT_THROW(StoreError, s.store->SaveAs(*s.doc, dir / "other.uzp", SaveOptions{"approved", "", false}));
    CHECK(refused_as.code() == StoreError::Code::protected_checkpoint && !fs::exists(dir / "other.uzp"));
    CHECK(s.store->path() == path && fs::exists(LockPath(path)) && !fs::exists(LockPath(dir / "other.uzp")));
    CHECK(*ReadCheckpoint(c, "approved") == row && s.doc->NeedsSaving());

    // Far outside the mutation window, then compacted: still there, byte for byte.
    AddLayers(s, "later ", kRetainedMutations + 5);
    const CompactResult result = s.store->Compact(*s.doc);
    CHECK(std::count(result.collapsed.begin(), result.collapsed.end(), 1) == 0 && result.collapsed.back() > 1);
    Container& after = s.store->container();
    CHECK(*ReadCheckpoint(after, "approved") == row);
    CHECK(StoredManifest(after, 1) == manifest);
    CHECK(s.store->ReadPlane(1, plane) == approved);
    s.Close();
    Session reopened = OpenSession(path, VerifyLevel::full);
    CHECK(reopened.report.ok());
    CHECK(StoredManifest(reopened.store->container(), 1) == manifest && reopened.store->ReadPlane(1, plane) == approved);
}

// ── 3.4 Edit → revert → edit → reopen → compact ─────────────────────────────────────────────

void RevertEditReopenCompact() {
    const fs::path dir = WorkDir("revert-compact");
    const fs::path path = CreateProject(dir);
    const PlaneImage i0 = Synthetic(2048, 1024, 2);
    const PlaneImage i1 = Poked(i0, 5, 5), i1b = Poked(i1, 6, 6);  // chunk (0,0) edited twice
    const PlaneImage i2 = Poked(i0, 1500, 7);                       // chunk (1,0) of the approved content
    Id plane = kNoId;
    std::int64_t reverted = 0;
    {
        Session s = OpenSession(path);
        plane = Paint(s, "paint", i0);  // revision 1: the approved chunks are written here
        s.store->Save(*s.doc, SaveOptions{"approved", "", true});
        Repaint(s, "edit 1", plane, i1);   // 2: a version only collapsed revisions bind
        Repaint(s, "edit 1b", plane, i1b); // 3: a version retained revisions bind after 3 collapses
        AddLayers(s, "between ", 80);      // 4..83
        const RequestOutcome back = s.store->Revert(
            *s.doc, MutationRequest{"project_revert", json::Object{{"checkpoint", "approved"}}, "revert", 83},
            std::string("approved"));
        CHECK(Committed(back));
        reverted = s.doc->revision();
        CHECK(reverted == 84 && s.store->ReadPlane(reverted, plane) == i0);
        Container& c = s.store->container();
        CHECK(StoredManifest(c, 84) == WithCounter(StoredManifest(c, 1), StoredManifest(c, 83)));
        CHECK(ManifestPlaneBindings(json::Parse(StoredManifest(c, 84)))[0].version ==
              ManifestPlaneBindings(json::Parse(StoredManifest(c, 1)))[0].version);
        Repaint(s, "edit 2", plane, i2);  // 85
    }
    Session s = OpenSession(path);  // reopen
    CHECK(s.report.ok() && s.doc->revision() == 85);
    Container& before = s.store->container();
    const std::int64_t version_i1 = ManifestPlaneBindings(json::Parse(StoredManifest(before, 2)))[0].version->version_id;
    const std::int64_t version_i1b = ManifestPlaneBindings(json::Parse(StoredManifest(before, 3)))[0].version->version_id;
    const std::string chunk_i1 = ReadChunkRows(before, version_i1)[0].sha256;

    std::vector<std::int64_t> retained = {1};
    for (std::int64_t r = 36; r <= 85; ++r) retained.push_back(r);
    const Retention retention = ComputeRetention(before);
    CHECK(std::vector<std::int64_t>(retention.revisions.begin(), retention.revisions.end()) == retained);
    std::map<std::int64_t, State> expected = RetainedStates(*s.store);
    for (auto it = expected.begin(); it != expected.end();) it = retention.revisions.count(it->first) ? std::next(it) : expected.erase(it);
    CHECK(expected.size() == retained.size());
    CHECK(expected.at(1).planes.at(plane) == i0 && expected.at(50).planes.at(plane) == i1b);
    CHECK(expected.at(84).planes.at(plane) == i0 && expected.at(85).planes.at(plane) == i2);

    s.store->Compact(*s.doc);
    Container& after = s.store->container();
    CHECK(RetainedStates(*s.store) == expected);
    // The version of revision 2 is collected with its chunk; that of revision 3 stays, bound by
    // retained revisions although revision 3 itself was collapsed.
    CHECK(Count(after, "SELECT COUNT(*) FROM plane_version WHERE version_id = " + std::to_string(version_i1)) == 0);
    CHECK(Count(after, "SELECT COUNT(*) FROM blob WHERE sha256 = '" + chunk_i1 + "'") == 0);
    CHECK(Count(after, "SELECT created_revision FROM plane_version WHERE version_id = " + std::to_string(version_i1b)) == 3);
    CheckReachability(after);
    s.Close();
    Session reopened = OpenSession(path, VerifyLevel::full);
    CHECK(reopened.report.ok() && reopened.report.collectable.empty());
    CHECK(RetainedStates(*reopened.store) == expected);
}

// ── 3.5 Garbage collection ──────────────────────────────────────────────────────────────────

void GarbageCollection() {
    const fs::path dir = WorkDir("gc");
    const fs::path path = CreateProject(dir);
    Session s = OpenSession(path);
    const std::string kept = Noise(5000, 11), dropped = Noise(7000, 12);
    Id dropped_layer = kNoId, gone_plane = kNoId;
    std::string kept_sha, dropped_sha;
    CHECK(Committed(Mutate(s, "import", [&](Edit& e) {
        kept_sha = s.store->StageResource(kept, "image/png");
        dropped_sha = s.store->StageResource(dropped, "image/png");
        e.project().resources[kept_sha] = {Meta(e.AllocateId(), "kept.png", kept.size())};
        e.project().resources[dropped_sha] = {Meta(e.AllocateId(), "dropped.png", dropped.size())};
        const Id keeper = e.Insert(kTop, NodeType::FillLayer, "keeper");
        FindLayer(e.project(), keeper)->fill->sources[ChannelType::BaseColor] =
            Source{BitmapSource{{kept_sha, std::nullopt, {}}, "sRGB", {}}};
        FindLayer(e.project(), keeper)->fill->active_channels = {ChannelType::BaseColor};
        dropped_layer = e.Insert(kTop, NodeType::FillLayer, "dropper");
        FindLayer(e.project(), dropped_layer)->fill->sources[ChannelType::BaseColor] =
            Source{BitmapSource{{dropped_sha, std::nullopt, {}}, "sRGB", {}}};
        FindLayer(e.project(), dropped_layer)->fill->active_channels = {ChannelType::BaseColor};
    })));
    const Id kept_plane = Paint(s, "kept paint", Synthetic(1024, 1024, 21));
    gone_plane = Paint(s, "gone paint", Synthetic(1024, 2048, 22));
    // Revision 4 drops the second resource and the second paint layer.
    CHECK(Committed(Mutate(s, "drop", [&](Edit& e) {
        e.project().resources.erase(dropped_sha);
        auto& layers = e.project().texture_sets[0].stacks[0].root_layers;
        layers.erase(std::remove_if(layers.begin(), layers.end(),
                                    [&](const Layer& l) { return l.uid == dropped_layer || l.name == "gone paint"; }),
                     layers.end());
    })));
    AddLayers(s, "after ", kRetainedMutations + 3);
    Container& c = s.store->container();
    const std::int64_t blobs = Count(c, "SELECT COUNT(*) FROM blob");
    CHECK(blobs == 2 + 1 + 2);  // two resources, one chunk, two chunks

    const CompactResult result = s.store->Compact(*s.doc);
    CHECK(result.removed_planes == 1 && result.removed_versions == 1 && result.removed_chunks == 2);
    CHECK(result.removed_blobs == 3);  // the dropped resource and the two chunks of the gone plane
    Container& after = s.store->container();
    CheckReachability(after);
    CHECK(Count(after, "SELECT COUNT(*) FROM blob WHERE sha256 = '" + dropped_sha + "'") == 0);
    CHECK(Count(after, "SELECT COUNT(*) FROM blob_meta WHERE sha256 = '" + dropped_sha + "'") == 0);
    CHECK(Count(after, "SELECT COUNT(*) FROM plane WHERE plane_id = " + std::to_string(gone_plane)) == 0);
    CHECK(s.store->ReadResource(kept_sha) == kept);
    CHECK(s.store->ReadPlane(s.doc->revision(), kept_plane) == Synthetic(1024, 1024, 21));
    // A later commit still works on the compacted file, and a new plane gets a fresh id.
    const Id fresh = Paint(s, "fresh", Synthetic(1024, 1024, 23));
    CHECK(fresh > gone_plane);
    CheckReachability(s.store->container());
}

// ── 3.6 Replays after pruning ───────────────────────────────────────────────────────────────

void PrunedKeyReplay() {
    const fs::path dir = WorkDir("pruned");
    const fs::path path = CreateProject(dir);
    Session s = OpenSession(path);
    AddLayers(s, "pre ", 3);
    const MutationRequest k1 = Req("k1", 3);  // non-idempotent: each execution inserts a layer
    CHECK(Committed(s.store->Submit(*s.doc, k1, [&](Edit& e) { e.Insert(kTop, NodeType::FillLayer, "k1"); })));
    CHECK(s.doc->revision() == 4);
    MutationRequest k2;
    for (int i = 0; i < 55; ++i) {
        if (s.doc->revision() == 49) {
            k2 = Req("k2", 49);
            CHECK(Committed(s.store->Submit(*s.doc, k2, [&](Edit& e) { e.Insert(kTop, NodeType::FillLayer, "k2"); })));
        } else {
            AddLayer(s, "fill " + std::to_string(s.doc->revision() + 1));
        }
    }
    CHECK(s.doc->revision() == 59);
    const CompactResult result = s.store->Compact(*s.doc);
    CHECK(result.horizon == 9 && s.doc->operation_horizon() == 9);
    CHECK(!s.doc->FindOperation("k1") && Count(s.store->container(), "SELECT COUNT(*) FROM operation WHERE idempotency_key = 'k1'") == 0);

    const auto replay_all = [&](Session& session) {
        const std::int64_t revisions = Count(session.store->container(), "SELECT COUNT(*) FROM revision");
        for (const std::optional<std::int64_t> precondition : {std::optional<std::int64_t>(3), std::optional<std::int64_t>()}) {
            MutationRequest replay = k1;
            replay.expected_revision = precondition;
            bool executed = false;
            const RequestOutcome outcome = session.store->Submit(*session.doc, replay, [&](Edit& e) {
                executed = true;
                e.Insert(kTop, NodeType::FillLayer, "k1 again");
            });
            CHECK(outcome.decision.admission == Admission::outcome_unknown && !executed && !outcome.result);
            CHECK(outcome.decision.current_revision == 59);
        }
        // A known key inside the window: the stored outcome, despite the newer current revision.
        bool executed = false;
        const RequestOutcome known = session.store->Submit(*session.doc, k2, [&](Edit&) { executed = true; });
        CHECK(known.decision.admission == Admission::stored_outcome && !executed);
        CHECK(known.decision.record && known.decision.record->committed_revision == 50);
        CHECK(Count(session.store->container(), "SELECT COUNT(*) FROM revision") == revisions);
        CHECK(session.doc->revision() == 59);
    };
    replay_all(s);
    s.Close();
    Session reopened = OpenSession(path);
    replay_all(reopened);
}

// ── 3.7 save_as and save_as_copy ────────────────────────────────────────────────────────────

void SaveAsAndCopy() {
    const fs::path dir = WorkDir("save-as");
    const fs::path original = CreateProject(dir, "a.uzp");
    Session s = OpenSession(original);
    const Id plane = Paint(s, "paint", Synthetic(1024, 1024, 31));
    AddLayer(s, "dirty");
    const std::string manifest = StoredManifest(s.store->container(), 2);
    CHECK(s.doc->NeedsSaving());
    const std::string bytes = ReadBytes(original);

    // save_as_copy: a closed, portable copy; the project keeps its path, lock and dirty state.
    const fs::path copy = dir / "copy.uzp";
    s.store->SaveAsCopy(copy);
    CHECK(s.store->path() == original && s.store->lock_path() == LockPath(original) && fs::exists(LockPath(original)));
    CHECK(s.doc->NeedsSaving() && s.store->NeedsSaving());
    CHECK(ReadBytes(original) == bytes);
    CHECK(fs::exists(copy) && !fs::exists(LockPath(copy)) && AtRest(copy) && NoTemporaries(copy));
    {
        Session c = OpenSession(copy, VerifyLevel::full);
        CHECK(c.report.ok() && c.doc->revision() == 2 && SaveManifest(*c.doc->snapshot().project) == manifest);
        CHECK(c.doc->NeedsSaving());
        CHECK(c.store->ReadPlane(2, plane) == Synthetic(1024, 1024, 31));
        Statement q(c.store->container(), "PRAGMA journal_mode");
        CHECK(q.Step() && q.Text(0) == "delete");
    }
    CHECK(!fs::exists(LockPath(copy)));
    CHECK(EXPECT_THROW(StoreError, s.store->SaveAsCopy(copy)).code() == StoreError::Code::exists);

    // save_as: the project, saved, relocates with its lock; the original file is unchanged.
    const fs::path target = dir / "b.uzp";
    const uzp::core::Checkpoints saved = s.store->SaveAs(*s.doc, target);
    CHECK(saved == (uzp::core::Checkpoints{2, 2, std::nullopt}) && s.doc->checkpoints() == saved);
    CHECK(!s.doc->NeedsSaving() && !s.store->NeedsSaving());
    CHECK(s.store->path() == target && s.store->lock_path() == LockPath(target));
    CHECK(fs::exists(LockPath(target)) && !fs::exists(LockPath(original)));
    CHECK(ReadBytes(original) == bytes && AtRest(target) && NoTemporaries(target));
    AddLayer(s, "after save_as");  // lands in the target
    CHECK(s.doc->revision() == 3 && Count(s.store->container(), "SELECT MAX(revision) FROM revision") == 3);
    {
        Session a = OpenSession(original);  // the original: not saved, at its old revision
        CHECK(a.doc->revision() == 2 && a.doc->NeedsSaving());
    }
    CHECK(EXPECT_THROW(StoreError, s.store->SaveAs(*s.doc, copy)).code() == StoreError::Code::exists);
    // A target whose lock a live worker holds is refused.
    const fs::path busy = dir / "busy.uzp";
    WriteBytes(LockPath(busy), "pid=" + std::to_string(CurrentOwner().pid) + "\nstarted=" + std::to_string(CurrentOwner().started) + "\n");
    CHECK(EXPECT_THROW(StoreError, s.store->SaveAs(*s.doc, busy)).code() == StoreError::Code::locked);
    CHECK(!fs::exists(busy) && s.store->path() == target);
    s.Close();
    CHECK(!fs::exists(LockPath(target)) && AtRest(target));
    Session b = OpenSession(target, VerifyLevel::full);
    CHECK(b.report.ok() && b.doc->revision() == 3 && b.doc->checkpoints() == (uzp::core::Checkpoints{3, 2, std::nullopt}));
}

// ── 3.8 Interrupted rewrites ────────────────────────────────────────────────────────────────

/// A project with history to compact: a plane and enough mutations to collapse some.
fs::path HistoryProject(const fs::path& dir) {
    const fs::path path = CreateProject(dir);
    Session s = OpenSession(path);
    Paint(s, "paint", Synthetic(1024, 1024, 41));
    AddLayers(s, "fill ", kRetainedMutations + 4);
    s.Close();
    return path;
}

void InterruptedRewrite() {
    using fault::Fault;
    struct Op {
        const char* name;
        std::function<void(Session&, const fs::path&)> run;
    };
    const std::vector<Op> ops = {
        {"compact", [](Session& s, const fs::path&) { s.store->Compact(*s.doc); }},
        {"save_as", [](Session& s, const fs::path& target) { s.store->SaveAs(*s.doc, target); }},
        {"save_as_copy", [](Session& s, const fs::path& target) { s.store->SaveAsCopy(target); }},
    };
    for (const Op& op : ops) {
        for (const auto& [fault_kind, step] : {std::pair{Fault::fail_during_vacuum, "VACUUM INTO"}, std::pair{Fault::fail_rename, "rename"}}) {
            const fs::path dir = WorkDir(std::string("io-") + op.name + "-" + (fault_kind == Fault::fail_rename ? "rename" : "vacuum"));
            const fs::path path = HistoryProject(dir);
            const fs::path target = dir / "target.uzp";
            const std::string bytes = ReadBytes(path);
            Session s = OpenSession(path);
            const std::int64_t revision = s.doc->revision();
            const uzp::core::Checkpoints checkpoints = s.doc->checkpoints();
            fault::Arm(fault_kind);
            const auto error = EXPECT_THROW(StoreError, op.run(s, target));
            fault::Arm(Fault::none);
            CHECK(Contains(error.what(), op.name) && Contains(error.what(), step));
            CHECK(ReadBytes(path) == bytes && !fs::exists(target) && NoTemporaries(path) && NoTemporaries(target));
            CHECK(s.store->path() == path && fs::exists(LockPath(path)) && !fs::exists(LockPath(target)));
            CHECK(s.doc->revision() == revision && s.doc->checkpoints() == checkpoints);
            AddLayer(s, "still works");  // the store stays usable on the original file
            s.Close();
            Session reopened = OpenSession(path, VerifyLevel::full);
            CHECK(reopened.report.ok() && reopened.doc->revision() == revision + 1);
        }
    }
    // A worker killed during VACUUM INTO or before the rename of compact, and during the
    // VACUUM INTO of save_as: the original file is unchanged and reopens; no partial file stays.
    for (const char* action : {"compact-kill-during-vacuum", "compact-kill-before-rename", "save-as-kill-during-vacuum"}) {
        const fs::path dir = WorkDir(action);
        const fs::path path = HistoryProject(dir);
        const fs::path target = dir / "target.uzp";
        const std::string bytes = ReadBytes(path);
        CHECK(RunChild({"child", action, Utf8(path), Utf8(target)}) == kKilled);
        CHECK(ReadBytes(path) == bytes && !fs::exists(target));
        CHECK(fs::exists(LockPath(path)));  // the killed worker's, stale
        if (Contains(action, "compact")) CHECK(fs::exists(With(path, ".compact")) || fs::exists(With(path, ".vacuum")));
        Session reopened = OpenSession(path, VerifyLevel::full);
        CHECK(reopened.report.ok() && NoTemporaries(path));
        CHECK(reopened.doc->revision() == kRetainedMutations + 5 && Count(reopened.store->container(), "SELECT COUNT(*) FROM revision") == kRetainedMutations + 6);
        // The same rewrite now completes.
        if (Contains(action, "compact")) {
            CHECK(!reopened.store->Compact(*reopened.doc).collapsed.empty());
        } else {
            reopened.store->SaveAs(*reopened.doc, target);
            CHECK(reopened.store->path() == target && NoTemporaries(target));
        }
    }
}

// ── 3.9 Files at rest are portable ──────────────────────────────────────────────────────────

void Portability() {
    const fs::path dir = WorkDir("portable");
    const fs::path path = HistoryProject(dir);
    CHECK(AtRest(path) && !fs::exists(LockPath(path)));  // after close
    const fs::path moved = WorkDir("portable-elsewhere") / "moved.uzp";
    {
        Session s = OpenSession(path);
        s.store->Compact(*s.doc);
        CHECK(AtRest(path) && NoTemporaries(path));  // after compact
        s.store->SaveAs(*s.doc, dir / "saved.uzp");
        CHECK(AtRest(dir / "saved.uzp") && AtRest(path));  // after save_as
        s.Close();
    }
    for (const fs::path& file : {path, dir / "saved.uzp"}) {
        const std::string header = ReadBytes(file).substr(0, 20);
        CHECK(header.compare(0, 15, "SQLite format 3") == 0 && header[18] == 1 && header[19] == 1);  // rollback journal, not WAL
    }
    fs::copy_file(dir / "saved.uzp", moved);
    Session s = OpenSession(moved, VerifyLevel::full);
    CHECK(s.report.ok() && s.report.collectable.empty() && s.doc->revision() == kRetainedMutations + 5);
    CHECK(!s.doc->NeedsSaving());
    Statement q(s.store->container(), "PRAGMA journal_mode");
    CHECK(q.Step() && q.Text(0) == "delete");
}

// ── 3.10 Lock sidecar ───────────────────────────────────────────────────────────────────────

void LockSidecar() {
    const fs::path dir = WorkDir("lock");
    const fs::path path = CreateProject(dir);
    CHECK(!fs::exists(LockPath(path)));  // the creating store was destroyed
    {
        Session s = OpenSession(path);
        CHECK(LockPath(path) == With(path, ".lock") && ReadLockOwner(LockPath(path)) == CurrentOwner());
        const auto refused = EXPECT_THROW(StoreError, ProjectStore::Open(path));
        CHECK(refused.code() == StoreError::Code::locked && Contains(refused.what(), std::to_string(GetCurrentProcessId())));
        s.doc.reset();
        s.store->Close();
        CHECK(!fs::exists(LockPath(path)) && AtRest(path));
        CHECK(EXPECT_THROW(StoreError, s.store->NeedsSaving()).code() == StoreError::Code::io);  // closed
        s.store->Close();  // idempotent
    }
    // Another live worker holds the project: refused until it closes.
    const fs::path release = dir / "release";
    HANDLE holder = StartChild({"child", "hold-lock", Utf8(path), Utf8(release)});
    for (int i = 0; i < 600 && !fs::exists(LockPath(path)); ++i) Sleep(50);
    for (int i = 0; i < 600 && !ReadLockOwner(LockPath(path)); ++i) Sleep(50);
    const std::optional<LockOwner> other = ReadLockOwner(LockPath(path));
    CHECK(other && other->pid == GetProcessId(holder) && OwnerAlive(*other));
    const auto busy = EXPECT_THROW(StoreError, ProjectStore::Open(path));
    CHECK(busy.code() == StoreError::Code::locked && Contains(busy.what(), std::to_string(other->pid)));
    WriteBytes(release, "go");
    CHECK(Wait(holder) == 0 && !fs::exists(LockPath(path)));

    // A worker killed while holding the lock leaves a stale lock: detected and replaced.
    CHECK(RunChild({"child", "kill-holding-lock", Utf8(path), ""}) == kKilled);
    const std::optional<LockOwner> dead = ReadLockOwner(LockPath(path));
    CHECK(dead && dead->pid != GetCurrentProcessId() && !OwnerAlive(*dead));
    {
        Session s = OpenSession(path);
        CHECK(ReadLockOwner(LockPath(path)) == CurrentOwner());
        s.Close();
        CHECK(!fs::exists(LockPath(path)) && AtRest(path));
    }
    // A reused pid (another start time) and an unreadable lock are stale too.
    for (const std::string& content : {"pid=" + std::to_string(GetCurrentProcessId()) + "\nstarted=1\n", std::string("garbage")}) {
        WriteBytes(LockPath(path), content);
        Session s = OpenSession(path);
        CHECK(ReadLockOwner(LockPath(path)) == CurrentOwner());
        s.Close();
        CHECK(!fs::exists(LockPath(path)));
    }
}

// ── Child processes ─────────────────────────────────────────────────────────────────────────

int Child(const std::string& action, const fs::path& path, const fs::path& target) {
    Session s = OpenSession(path);
    if (action == "compact-kill-during-vacuum") {
        fault::Arm(fault::Fault::kill_during_vacuum);
        s.store->Compact(*s.doc);
    } else if (action == "compact-kill-before-rename") {
        fault::Arm(fault::Fault::kill_before_rename);
        s.store->Compact(*s.doc);
    } else if (action == "save-as-kill-during-vacuum") {
        fault::Arm(fault::Fault::kill_during_vacuum);
        s.store->SaveAs(*s.doc, target);
    } else if (action == "kill-holding-lock") {
        TerminateProcess(GetCurrentProcess(), kKilled);
    } else if (action == "hold-lock") {
        for (int i = 0; i < 6000 && !fs::exists(target); ++i) Sleep(50);
        s.Close();
        return 0;
    } else {
        std::fprintf(stderr, "unknown action %s\n", action.c_str());
        return 2;
    }
    std::fprintf(stderr, "the fault hook did not terminate the process\n");
    return 1;
}

int Run(const std::string& only) {
    const std::vector<std::pair<const char*, std::function<void()>>> cases = {
        {"checkpoints", Checkpoints},                          // 3.1
        {"retention_window", RetentionWindow},                 // 3.2
        {"protected_checkpoint", ProtectedCheckpoint},         // 3.3
        {"revert_edit_reopen_compact", RevertEditReopenCompact},  // 3.4
        {"garbage_collection", GarbageCollection},             // 3.5
        {"pruned_key_replay", PrunedKeyReplay},                // 3.6
        {"save_as_and_copy", SaveAsAndCopy},                   // 3.7
        {"interrupted_rewrite", InterruptedRewrite},           // 3.8
        {"portability", Portability},                          // 3.9
        {"lock_sidecar", LockSidecar},                         // 3.10
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
        fs::remove_all(fs::temp_directory_path() / ("uzp-store-save-tests-" + std::to_string(GetCurrentProcessId())), ec);
    }
    return failed == 0 && ran > 0 ? 0 : 1;
}

int Command(int argc, char** argv) {
    const std::string command = argc > 1 ? argv[1] : "";
    if (command == "run") return Run(argc > 2 ? argv[2] : "");
    if (command == "child" && (argc == 4 || argc == 5)) return Child(argv[2], fs::path(argv[3]), fs::path(argc == 5 ? argv[4] : ""));
    std::fprintf(stderr, "usage: uzp-store-save-tests run [case] | child <action> <file> [<target>]\n");
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
