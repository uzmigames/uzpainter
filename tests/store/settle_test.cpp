// Settling evidence of the project store (`docs/architecture/09-project-file-format.md` §7; parent
// task phase1.8_project-store, items 3.1-3.5): the §7 scenarios run end to end on one store
// build, on content that holds a stored resource bound to a fill layer and two paint layers with
// multi-chunk planes on the same channel and UV tile. Recovery is checked as whole-file equality:
// every revision's manifest bytes, the pixels of every plane it binds, the bytes of every resource
// it names, the checkpoint rows and the operation rows equal what the file held before the fault.
// Built by `zig build uzp-store-settle-tests` with the test-only fault hooks (`src/store/fault.h`)
// and driven by tests/store/test_store_settle.py.
//
// Usage:
//   uzp-store-settle-tests run [case]                 run every case (or one); exit 0 when all pass
//   uzp-store-settle-tests list                       print the case names
//   uzp-store-settle-tests child <action> <file> [<plane>]
//                                                     open <file> and run <action>:
//                                                     kill-during-commit, kill-in-plane-commit or
//                                                     kill-after-commit (a stroke on <plane>), or
//                                                     compact-kill-during-vacuum,
//                                                     compact-kill-before-rename; each terminates
//                                                     the process with exit code 77
// Cases that need an interrupted worker start this executable again as a child.

#include <windows.h>

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
#include "store/planes.h"
#include "store/project_store.h"
#include "store/save.h"
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

constexpr const char* kUuid = "6f1c2a3e-0000-4000-8000-0000000000cc";
constexpr Id kSet = 1, kStack = 3;
const InsertPosition kTop = InsertPosition::FromStack(kSet, kStack);
constexpr unsigned kKilled = fault::kKillExitCode;
/// The paint planes: 2×2 chunks of sRGB8.
constexpr int kEdge = 2048;

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

fs::path WorkDir(const std::string& name) {
    const fs::path dir = fs::temp_directory_path() /
                         ("uzp-store-settle-tests-" + std::to_string(GetCurrentProcessId())) / name;
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

fs::path With(const fs::path& path, const char* suffix) {
    fs::path out = path;
    out += suffix;
    return out;
}

/// The temporary files of `compact` and `save_as` are gone.
bool NoTemporaries(const fs::path& path) {
    return !fs::exists(With(path, ".compact")) && !fs::exists(With(path, ".vacuum")) &&
           !fs::exists(With(path, ".compact-journal")) && !fs::exists(With(path, ".vacuum-journal"));
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

PlaneImage Synthetic(std::uint64_t seed) {
    PlaneImage image{kEdge, kEdge, ChannelFormat::sRGB8, {}};
    image.texels = Noise(static_cast<std::size_t>(kEdge) * kEdge * 3, seed * 0x9E3779B97F4A7C15ull + 1);
    return image;
}

/// `image` after a stroke `seed`: one texel, whose place `seed` decides, flipped in every byte
/// (the edit touches one chunk).
PlaneImage Stroke(PlaneImage image, std::uint64_t seed) {
    const std::size_t x = (seed * 397) % static_cast<std::uint64_t>(image.width);
    const std::size_t y = (seed * 131) % static_cast<std::uint64_t>(image.height);
    const std::size_t at = (y * static_cast<std::size_t>(image.width) + x) * 3;
    for (std::size_t i = 0; i < 3; ++i) image.texels[at + i] = static_cast<char>(image.texels[at + i] ^ 0x5a);
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
    meta.imported_at = "2026-10-11T00:00:00Z";
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

Session OpenSession(const fs::path& path, VerifyLevel verify = VerifyLevel::full) {
    ProjectStore::Opened opened = ProjectStore::Open(path, OpenOptions{verify, VersionPolicy::Current()});
    Session s{std::move(opened.store), std::make_unique<Document>(std::move(opened.state)), opened.report};
    s.store->Attach(*s.doc);
    return s;
}

bool Committed(const RequestOutcome& outcome) {
    return outcome.decision.admission == Admission::execute && outcome.result &&
           outcome.result->status == ResultStatus::committed;
}

MutationRequest LayerReq(const std::string& key, std::optional<std::int64_t> expected) {
    return MutationRequest{"layer_insert", json::Object{{"name", key}}, key, expected};
}

/// A committed fill-layer insertion named after its key.
void AddLayer(Session& s, const std::string& key) {
    CHECK(Committed(s.store->Submit(*s.doc, LayerReq(key, s.doc->revision()),
                                    [&](Edit& e) { e.Insert(kTop, NodeType::FillLayer, key); })));
}

void AddLayers(Session& s, const std::string& prefix, int count) {
    for (int i = 0; i < count; ++i) AddLayer(s, prefix + std::to_string(s.doc->revision() + 1));
}

/// The request of stroke `seed` on `plane`.
MutationRequest StrokeReq(const std::string& key, Id plane, std::uint64_t seed, std::optional<std::int64_t> expected) {
    return MutationRequest{"paint_stroke",
                           json::Object{{"plane", static_cast<std::int64_t>(plane)}, {"seed", static_cast<std::int64_t>(seed)}},
                           key, expected};
}

/// Submits stroke `seed` on `plane` over the plane's current content; `executed` tells whether the
/// call ran. A stroke is not idempotent: each execution changes the pixels again.
RequestOutcome SubmitStroke(Session& s, const MutationRequest& request, Id plane, std::uint64_t seed,
                            bool* executed = nullptr) {
    return s.store->Submit(*s.doc, request, [&, plane, seed](Edit& e) {
        if (executed != nullptr) *executed = true;
        s.store->WritePlane(e, plane, Stroke(s.store->ReadPlane(e.project(), plane), seed));
    });
}

void Paint(Session& s, const std::string& key, Id plane, std::uint64_t seed) {
    CHECK(Committed(SubmitStroke(s, StrokeReq(key, plane, seed, s.doc->revision()), plane, seed)));
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

std::string StoredManifest(Container& c, std::int64_t revision) {
    Statement q(c, "SELECT manifest FROM revision WHERE revision = ?");
    q.Bind(1, revision);
    if (!q.Step()) throw Failure{"no revision " + std::to_string(revision)};
    return Decompress(q.Blob(0));
}

/// What one revision holds: its manifest bytes, the SHA-256 of the pixels of every plane it binds
/// (with the plane's size and format) and of the bytes of every resource it names.
struct State {
    std::string manifest;
    std::map<Id, std::string> planes;
    std::map<std::string, std::string> resources;

    bool operator==(const State&) const = default;
};

std::string Digest(const PlaneImage& image) {
    return std::to_string(image.width) + "x" + std::to_string(image.height) + ":" +
           std::string(ToString(image.format)) + ":" + Sha256Hex(image.texels);
}

/// Everything the file holds that recovery must preserve.
struct FileState {
    std::map<std::int64_t, State> revisions;
    std::vector<CheckpointRow> checkpoints;
    std::vector<std::string> operations;  // key, request hash, committed revision

    bool operator==(const FileState&) const = default;
};

FileState Capture(ProjectStore& store) {
    Container& c = store.container();
    FileState file;
    // A committed plane version and a blob are immutable: each is read (and verified) once, through
    // the first revision that binds it.
    std::map<std::pair<Id, std::int64_t>, std::string> versions;
    std::map<std::string, std::string> blobs;
    for (const std::int64_t revision : Ints(c, "SELECT revision FROM revision ORDER BY revision")) {
        State state{ReadManifestText(c, revision), {}, {}};
        for (const ManifestBinding& binding : ManifestPlaneBindings(json::Parse(state.manifest))) {
            CHECK(binding.version);
            const auto key = std::pair{binding.plane_id, binding.version->version_id};
            if (versions.count(key) == 0) versions[key] = Digest(store.ReadPlane(revision, binding.plane_id));
            state.planes[binding.plane_id] = versions.at(key);
        }
        for (const auto& [sha256, names] : LoadManifest(state.manifest).resources) {
            if (blobs.count(sha256) == 0) {
                const std::string bytes = store.ReadResource(sha256);
                CHECK(Sha256Hex(bytes) == sha256);
                blobs[sha256] = Sha256Hex(bytes);
            }
            state.resources[sha256] = blobs.at(sha256);
        }
        file.revisions[revision] = std::move(state);
    }
    file.checkpoints = ReadCheckpoints(c);
    Statement q(c, "SELECT idempotency_key, request_hash, committed_revision FROM operation ORDER BY committed_revision");
    while (q.Step()) file.operations.push_back(q.Text(0) + "|" + q.Text(1) + "|" + std::to_string(q.Int(2)));
    return file;
}

/// The captured state of the file at `path` (opened with full verification, which must be clean).
FileState CaptureFile(const fs::path& path) {
    Session s = OpenSession(path);
    CHECK(s.report.ok() && s.report.collectable.empty());
    return Capture(*s.store);
}

/// `file`'s revisions restricted to `retained`.
std::map<std::int64_t, State> Retained(const FileState& file, const std::set<std::int64_t>& retained) {
    std::map<std::int64_t, State> out;
    for (const auto& [revision, state] : file.revisions) {
        if (retained.count(revision) != 0) out[revision] = state;
    }
    return out;
}

/// After a compaction: every plane, version, chunk row and blob is reachable from a retained
/// manifest and every reachable one is stored (computed from the manifests alone).
void CheckReachability(Container& c) {
    std::set<std::int64_t> versions, planes;
    std::set<std::string> hashes;
    for (const std::int64_t revision : Ints(c, "SELECT revision FROM revision")) {
        const std::string text = ReadManifestText(c, revision);
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
    std::set<std::string> blobs;
    {
        Statement q(c, "SELECT sha256 FROM blob");
        while (q.Step()) blobs.insert(q.Text(0));
    }
    CHECK(blobs == hashes);
}

/// The content of every case: a resource bound to a fill layer (revision 1) and two paint layers
/// A and B, each with a BaseColor plane on UV tile 1001 (revision 2).
struct Content {
    std::string resource;  // its SHA-256
    Id fill = kNoId;
    Id node_a = kNoId, node_b = kNoId;
    Id plane_a = kNoId, plane_b = kNoId;
};

constexpr std::uint64_t kSeedA = 101, kSeedB = 202;

Content BuildContent(Session& s) {
    Content content;
    const std::string bytes = Noise(300000, 77);
    CHECK(Committed(s.store->Submit(*s.doc, LayerReq("import", s.doc->revision()), [&](Edit& e) {
        content.resource = s.store->StageResource(bytes, "image/png");
        e.project().resources[content.resource] = {Meta(e.AllocateId(), "cloth.png", bytes.size())};
        content.fill = e.Insert(kTop, NodeType::FillLayer, "cloth");
        Layer& layer = *FindLayer(e.project(), content.fill);
        layer.fill->sources[ChannelType::BaseColor] = Source{BitmapSource{{content.resource, std::nullopt, {}}, "sRGB", {}}};
        layer.fill->active_channels = {ChannelType::BaseColor};
    })));
    CHECK(Committed(s.store->Submit(*s.doc, LayerReq("paint", s.doc->revision()), [&](Edit& e) {
        content.node_a = e.Insert(kTop, NodeType::PaintLayer, "paint A");
        content.node_b = e.Insert(kTop, NodeType::PaintLayer, "paint B");
        content.plane_a = s.store->CreatePlane(e, PlaneSpec{content.node_a, ChannelType::BaseColor, 1001, ChannelFormat::sRGB8, kEdge, kEdge});
        content.plane_b = s.store->CreatePlane(e, PlaneSpec{content.node_b, ChannelType::BaseColor, 1001, ChannelFormat::sRGB8, kEdge, kEdge});
        s.store->WritePlane(e, content.plane_a, Synthetic(kSeedA));
        s.store->WritePlane(e, content.plane_b, Synthetic(kSeedB));
    })));
    CHECK(s.doc->revision() == 2 && content.plane_a != content.plane_b);
    return content;
}

fs::path CreateProject(const fs::path& dir, Content& content) {
    const fs::path path = dir / "project.uzp";
    DocumentState state;
    state.project_uuid = kUuid;
    state.project = BaseProject();
    ProjectStore::Create(path, state);
    Session s = OpenSession(path);
    content = BuildContent(s);
    return path;
}

// ── Child processes ─────────────────────────────────────────────────────────────────────────

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

DWORD RunChild(const std::vector<std::string>& args) {
    const HANDLE process = StartChild(args);
    WaitForSingleObject(process, 300000);
    DWORD code = 0;
    GetExitCodeProcess(process, &code);
    CloseHandle(process);
    return code;
}

std::string Utf8(const fs::path& path) {
    const std::u8string text = path.u8string();
    return std::string(text.begin(), text.end());
}

/// The strokes the children submit: key, seed and the fault that ends them.
struct ChildStroke {
    const char* action;
    const char* key;
    std::uint64_t seed;
    fault::Fault fault;
};
constexpr ChildStroke kChildStrokes[] = {
    {"kill-during-commit", "stroke killed in COMMIT", 11, fault::Fault::kill_during_commit},
    {"kill-in-plane-commit", "stroke killed before its revision row", 12, fault::Fault::kill_before_revision_row},
    {"kill-after-commit", "stroke never acknowledged", 13, fault::Fault::kill_after_commit},
};

const ChildStroke& StrokeOf(const std::string& action) {
    for (const ChildStroke& stroke : kChildStrokes) {
        if (action == stroke.action) return stroke;
    }
    throw Failure{"no stroke for " + action};
}

/// The child's stroke, retried by the parent with its original request (key, arguments and
/// precondition `expected`).
RequestOutcome RetryChildStroke(Session& s, const std::string& action, Id plane, std::int64_t expected, bool* executed) {
    const ChildStroke& stroke = StrokeOf(action);
    return SubmitStroke(s, StrokeReq(stroke.key, plane, stroke.seed, expected), plane, stroke.seed, executed);
}

// ── 3.1 Interruptions, corruption and recovery equality (09 §7) ─────────────────────────────

/// Corrupts the copy at `path` through a raw connection (tampering outside the store).
void Tamper(const fs::path& path, const std::function<void(Container&)>& change) {
    Container c = Container::Open(path);
    change(c);
}

void ReplaceManifest(Container& c, std::int64_t revision) {
    std::string text = StoredManifest(c, revision);
    const std::size_t at = text.find("\"M_body\"");
    CHECK(at != std::string::npos);
    text.replace(at, 8, "\"M_bodx\"");
    Statement q(c, "UPDATE revision SET manifest = ? WHERE revision = ?");
    q.BindBlob(1, Compress(text)).Bind(2, revision).Run();
}

void Interruptions() {
    const fs::path dir = WorkDir("interruptions");
    Content content;
    const fs::path path = CreateProject(dir, content);
    std::int64_t approved = 0;
    {
        Session s = OpenSession(path);
        s.store->Save(*s.doc, SaveOptions{"approved", "", true});  // revision 2, protected
        approved = s.doc->revision();
        AddLayers(s, "fill ", kRetainedMutations + 5);
        Paint(s, "stroke A", content.plane_a, 1);
        Paint(s, "stroke B", content.plane_b, 2);
        s.store->Save(*s.doc);
    }
    const FileState before = CaptureFile(path);
    const std::int64_t head = before.revisions.rbegin()->first;
    const std::string bytes = ReadBytes(path);

    // A worker killed while SQLite writes the pages of COMMIT (hot journal, torn file), and one
    // killed between the plane rows and the revision row: the file reopens at `head`, identical.
    for (const char* action : {"kill-during-commit", "kill-in-plane-commit"}) {
        CHECK(RunChild({"child", action, Utf8(path), std::to_string(content.plane_a)}) == kKilled);
        if (std::string(action) == "kill-during-commit") CHECK(fs::exists(With(path, "-journal")) && ReadBytes(path) != bytes);
        CHECK(CaptureFile(path) == before);
        CHECK(!fs::exists(With(path, "-journal")) && ReadBytes(path) == bytes);
    }
    // A worker killed during `VACUUM INTO` of compact and before its rename: the file is unchanged.
    for (const char* action : {"compact-kill-during-vacuum", "compact-kill-before-rename"}) {
        CHECK(RunChild({"child", action, Utf8(path)}) == kKilled);
        CHECK(ReadBytes(path) == bytes);
        CHECK(CaptureFile(path) == before);
        CHECK(NoTemporaries(path));  // removed by the reopen
    }
    Session s = OpenSession(path);
    CHECK(s.report.ok() && s.doc->revision() == head);
    // In-process I/O failures of `VACUUM INTO` and of the rename: the error names the step.
    for (const auto& [kind, step] : {std::pair{fault::Fault::fail_during_vacuum, "VACUUM INTO"}, std::pair{fault::Fault::fail_rename, "rename"}}) {
        fault::Arm(kind);
        const auto error = EXPECT_THROW(StoreError, s.store->Compact(*s.doc));
        fault::Arm(fault::Fault::none);
        CHECK(Contains(error.what(), "compact") && Contains(error.what(), step));
        CHECK(ReadBytes(path) == bytes && NoTemporaries(path));
        CHECK(Capture(*s.store) == before);
    }

    // The killed strokes never landed: their original requests now execute, once each.
    for (const char* action : {"kill-during-commit", "kill-in-plane-commit"}) {
        bool executed = false;
        CHECK(Committed(RetryChildStroke(s, action, content.plane_a, s.doc->revision(), &executed)) && executed);
    }
    PlaneImage a = Stroke(Stroke(Stroke(Synthetic(kSeedA), 1), StrokeOf("kill-during-commit").seed), StrokeOf("kill-in-plane-commit").seed);
    CHECK(s.store->ReadPlane(s.doc->revision(), content.plane_a) == a);
    CHECK(s.store->ReadPlane(s.doc->revision(), content.plane_b) == Stroke(Synthetic(kSeedB), 2));

    // Compaction completes: every retained state equals its value before it, byte for byte.
    const FileState uncompacted = Capture(*s.store);
    const Retention retention = ComputeRetention(s.store->container());
    CHECK(retention.revisions.count(approved) == 1 && retention.revisions.count(approved + 1) == 0);
    const CompactResult result = s.store->Compact(*s.doc);
    CHECK(!result.collapsed.empty() && result.bytes_after < result.bytes_before);
    const std::map<std::int64_t, State> expected = Retained(uncompacted, retention.revisions);
    CHECK(Capture(*s.store).revisions == expected);
    CHECK(expected.at(approved).planes.at(content.plane_a) == Digest(Synthetic(kSeedA)));
    CheckReachability(s.store->container());
    s.Close();
    const FileState compacted = CaptureFile(path);
    CHECK(compacted.revisions == expected);
    const std::int64_t current = compacted.revisions.rbegin()->first;

    // Corruption, each on its own copy: a resource blob, a chunk blob of plane A, a retained older
    // manifest and the current manifest. Each is detected and names what it affects; what it does
    // not affect still reads exactly.
    const auto copy = [&](const std::string& name) {
        const fs::path target = dir / (name + ".uzp");
        fs::copy_file(path, target);
        return target;
    };
    const fs::path blob_copy = copy("corrupt-resource");
    Tamper(blob_copy, [&](Container& c) {
        std::string altered = Noise(300000, 77);
        altered[0] = static_cast<char>(altered[0] ^ 0x01);
        Statement q(c, "UPDATE blob SET data = ? WHERE sha256 = ?");
        q.BindBlob(1, Compress(altered)).Bind(2, content.resource).Run();
    });
    {
        Session bad = OpenSession(blob_copy);
        CHECK(bad.report.corrupt.size() == 1 && bad.report.corrupt[0].kind == "blob" && bad.report.corrupt[0].key == content.resource);
        CHECK(bad.report.corrupt[0].nodes.size() == 1 && bad.report.corrupt[0].nodes[0].id == content.fill);
        const auto error = EXPECT_THROW(CorruptionError, bad.store->ReadResource(content.resource));
        CHECK(Contains(error.what(), "node " + std::to_string(content.fill)));
        for (const std::int64_t revision : {approved, current}) {
            for (const auto& [plane, digest] : expected.at(revision).planes) CHECK(Digest(bad.store->ReadPlane(revision, plane)) == digest);
        }
    }
    const fs::path chunk_copy = copy("corrupt-chunk");
    Tamper(chunk_copy, [&](Container& c) {
        const VersionRef ref = *ManifestPlaneBindings(json::Parse(StoredManifest(c, current)))[0].version;
        const std::vector<ChunkRow> rows = ReadChunkRows(c, ref.version_id);
        CHECK(!rows.empty());
        std::string chunk = ReadChunkBlob(c, rows[0].sha256, static_cast<std::size_t>(kChunkSize) * kChunkSize * 3);
        chunk[5] = static_cast<char>(chunk[5] ^ 0x01);
        Statement q(c, "UPDATE blob SET data = ? WHERE sha256 = ?");
        q.BindBlob(1, Compress(chunk)).Bind(2, rows[0].sha256).Run();
    });
    {
        Session bad = OpenSession(chunk_copy);
        const Id damaged = ManifestPlaneBindings(json::Parse(StoredManifest(bad.store->container(), current)))[0].plane_id;
        const Id owner = damaged == content.plane_a ? content.node_a : content.node_b;
        const Id intact = damaged == content.plane_a ? content.plane_b : content.plane_a;
        CHECK(!bad.report.ok());
        for (const CorruptItem& item : bad.report.corrupt) {
            CHECK(item.kind == "plane" && item.key == std::to_string(damaged) && Contains(item.detail, "SHA-256 mismatch"));
            CHECK(item.nodes.size() == 1 && item.nodes[0].id == owner);
        }
        const auto error = EXPECT_THROW(CorruptionError, bad.store->ReadPlane(current, damaged));
        CHECK(Contains(error.what(), "node " + std::to_string(owner)));
        CHECK(Digest(bad.store->ReadPlane(current, intact)) == expected.at(current).planes.at(intact));
        CHECK(bad.store->ReadResource(content.resource) == Noise(300000, 77));
    }
    const fs::path old_manifest_copy = copy("corrupt-old-manifest");
    Tamper(old_manifest_copy, [&](Container& c) { ReplaceManifest(c, approved); });
    {
        Session bad = OpenSession(old_manifest_copy);
        CHECK(bad.report.corrupt.size() == 1 && bad.report.corrupt[0].kind == "manifest" &&
              bad.report.corrupt[0].key == std::to_string(approved) && Contains(bad.report.corrupt[0].detail, "manifest_sha256"));
        CHECK(bad.doc->revision() == current);
        CHECK(EXPECT_THROW(CorruptionError, bad.store->ReadPlane(approved, content.plane_a)).item().kind == "manifest");
        for (const auto& [plane, digest] : expected.at(current).planes) CHECK(Digest(bad.store->ReadPlane(current, plane)) == digest);
    }
    const fs::path current_manifest_copy = copy("corrupt-current-manifest");
    Tamper(current_manifest_copy, [&](Container& c) { ReplaceManifest(c, current); });
    const auto refused = EXPECT_THROW(CorruptionError, ProjectStore::Open(current_manifest_copy));
    CHECK(refused.item().kind == "manifest" && refused.item().key == std::to_string(current));
    // The project itself was never touched by any of it.
    CHECK(CaptureFile(path) == compacted);
}

// ── 3.2 Two paint layers on one channel and tile ────────────────────────────────────────────

void TwoLayers() {
    const fs::path dir = WorkDir("two-layers");
    Content content;
    const fs::path path = CreateProject(dir, content);
    const PlaneImage a0 = Synthetic(kSeedA), b0 = Synthetic(kSeedB);
    {
        Container c = Container::Open(path);
        Statement q(c, "SELECT COUNT(*), COUNT(DISTINCT set_id || '/' || stack_id || '/' || channel || '/' || tile_u || '/' || tile_v) FROM plane");
        CHECK(q.Step() && q.Int(0) == 2 && q.Int(1) == 1);  // one set, stack, channel and tile
    }
    std::int64_t saved = 0;
    PlaneImage a1;
    {
        Session s = OpenSession(path);  // reopen
        CHECK(s.store->ReadPlane(2, content.plane_a) == a0 && s.store->ReadPlane(2, content.plane_b) == b0);
        saved = s.store->Save(*s.doc).current;
        Paint(s, "edit A", content.plane_a, 5);  // only A changes
        a1 = Stroke(a0, 5);
        CHECK(s.store->ReadPlane(s.doc->revision(), content.plane_a) == a1);
        CHECK(s.store->ReadPlane(s.doc->revision(), content.plane_b) == b0);
    }
    // A stroke on B killed in COMMIT: recovered with A edited and B untouched.
    const FileState before = CaptureFile(path);
    CHECK(RunChild({"child", "kill-during-commit", Utf8(path), std::to_string(content.plane_b)}) == kKilled);
    CHECK(CaptureFile(path) == before);
    Session s = OpenSession(path);
    bool executed = false;
    CHECK(Committed(RetryChildStroke(s, "kill-during-commit", content.plane_b, s.doc->revision(), &executed)) && executed);
    const PlaneImage b1 = Stroke(b0, StrokeOf("kill-during-commit").seed);
    const std::int64_t edited = s.doc->revision();
    CHECK(s.store->ReadPlane(edited, content.plane_a) == a1 && s.store->ReadPlane(edited, content.plane_b) == b1);
    // Revert to the saved checkpoint: both planes come back, each to its own content.
    CHECK(Committed(s.store->Revert(*s.doc, MutationRequest{"project_revert", json::Object{{"checkpoint", DefaultCheckpointName(saved)}}, "revert", edited},
                                    DefaultCheckpointName(saved))));
    const std::int64_t reverted = s.doc->revision();
    CHECK(s.store->ReadPlane(reverted, content.plane_a) == a0 && s.store->ReadPlane(reverted, content.plane_b) == b0);
    // Enough mutations that compaction collapses the import revision, while the saved, edited and
    // reverted states stay retained.
    AddLayers(s, "fill ", kRetainedMutations - 3);
    const CompactResult result = s.store->Compact(*s.doc);
    CHECK(result.collapsed == (std::vector<std::int64_t>{0, 1}));
    s.Close();

    Session again = OpenSession(path);
    CHECK(again.report.ok() && again.report.collectable.empty());
    Container& c = again.store->container();
    // Every retained revision binds both planes, each to its own version: never shared, never one
    // plane's chunks in the other's version, and each reads its own pixels.
    const std::map<std::int64_t, std::pair<PlaneImage, PlaneImage>> pixels = {
        {saved, {a0, b0}}, {edited, {a1, b1}}, {reverted, {a0, b0}}, {again.doc->revision(), {a0, b0}}};
    for (const auto& [revision, images] : pixels) {
        CHECK(again.store->ReadPlane(revision, content.plane_a) == images.first);
        CHECK(again.store->ReadPlane(revision, content.plane_b) == images.second);
    }
    for (const std::int64_t revision : Ints(c, "SELECT revision FROM revision")) {
        const std::vector<ManifestBinding> bindings = ManifestPlaneBindings(json::Parse(ReadManifestText(c, revision)));
        if (bindings.empty()) continue;
        CHECK(bindings.size() == 2 && bindings[0].plane_id != bindings[1].plane_id);
        CHECK(bindings[0].version->version_id != bindings[1].version->version_id);
        std::set<std::string> first, second;
        for (const ChunkRow& row : ReadChunkRows(c, bindings[0].version->version_id)) first.insert(row.sha256);
        for (const ChunkRow& row : ReadChunkRows(c, bindings[1].version->version_id)) second.insert(row.sha256);
        CHECK(first.size() == 4 && second.size() == 4);
        for (const std::string& sha256 : first) CHECK(second.count(sha256) == 0);
    }
    CHECK(Count(c, "SELECT COUNT(*) FROM plane") == 2);
    CHECK(Count(c, "SELECT COUNT(DISTINCT plane_id) FROM plane_version") == 2);
}

// ── 3.3 Commit then die ─────────────────────────────────────────────────────────────────────

void CommitThenDie() {
    const fs::path dir = WorkDir("commit-then-die");
    Content content;
    const fs::path path = CreateProject(dir, content);
    // The worker commits a stroke durably and dies before the supervisor's acknowledgement.
    CHECK(RunChild({"child", "kill-after-commit", Utf8(path), std::to_string(content.plane_a)}) == kKilled);
    const PlaneImage painted = Stroke(Synthetic(kSeedA), StrokeOf("kill-after-commit").seed);
    const auto retries = [&](Session& s, std::int64_t current) {
        Container& c = s.store->container();
        const std::int64_t revisions = Count(c, "SELECT COUNT(*) FROM revision");
        const std::int64_t versions = Count(c, "SELECT COUNT(*) FROM plane_version");
        // The same request (key, arguments, original precondition 2): the stored outcome.
        bool executed = false;
        const RequestOutcome same = RetryChildStroke(s, "kill-after-commit", content.plane_a, 2, &executed);
        CHECK(same.decision.admission == Admission::stored_outcome && !executed && !same.result);
        CHECK(same.decision.record && same.decision.record->committed_revision == 3 && same.decision.current_revision == current);
        CHECK(std::get<json::Object>(same.decision.record->outcome.data).at("status") == json::Value("committed"));
        // A changed request with the same key: idempotency_conflict.
        const ChildStroke& stroke = StrokeOf("kill-after-commit");
        const RequestOutcome changed =
            SubmitStroke(s, StrokeReq(stroke.key, content.plane_a, stroke.seed + 1, 2), content.plane_a, stroke.seed + 1, &executed);
        CHECK(changed.decision.admission == Admission::idempotency_conflict && !executed && !changed.result);
        CHECK(changed.decision.record->committed_revision == 3);
        // Neither created a revision, a plane version or changed a pixel.
        CHECK(Count(c, "SELECT COUNT(*) FROM revision") == revisions && Count(c, "SELECT COUNT(*) FROM plane_version") == versions);
        CHECK(s.doc->revision() == current && s.store->ReadPlane(3, content.plane_a) == painted);
    };
    {
        Session s = OpenSession(path);
        CHECK(s.report.ok() && s.doc->revision() == 3);
        CHECK(s.store->ReadPlane(3, content.plane_a) == painted && s.store->ReadPlane(3, content.plane_b) == Synthetic(kSeedB));
        retries(s, 3);
        Paint(s, "later", content.plane_b, 9);  // the current revision moves on
        retries(s, 4);
    }
    Session s = OpenSession(path);
    retries(s, 4);
    CHECK(Count(s.store->container(), "SELECT COUNT(*) FROM operation WHERE idempotency_key = 'stroke never acknowledged'") == 1);
}

// ── 3.4 Replays after pruning ───────────────────────────────────────────────────────────────

void PrunedKeyReplay() {
    const fs::path dir = WorkDir("pruned");
    Content content;
    const fs::path path = CreateProject(dir, content);
    Session s = OpenSession(path);
    // k1: a non-idempotent stroke at revision 3 (precondition 2); k2 later, inside the window.
    CHECK(Committed(SubmitStroke(s, StrokeReq("k1", content.plane_a, 21, 2), content.plane_a, 21)));
    AddLayers(s, "fill ", 40);
    const std::int64_t k2_base = s.doc->revision();
    CHECK(Committed(SubmitStroke(s, StrokeReq("k2", content.plane_b, 22, k2_base), content.plane_b, 22)));
    AddLayers(s, "fill ", 20);
    s.store->Save(*s.doc);
    const std::int64_t head = s.doc->revision();
    const CompactResult result = s.store->Compact(*s.doc);
    CHECK(result.horizon >= 3 && s.doc->operation_horizon() == result.horizon);
    CHECK(Count(s.store->container(), "SELECT COUNT(*) FROM operation WHERE idempotency_key = 'k1'") == 0);
    CHECK(Count(s.store->container(), "SELECT COUNT(*) FROM operation WHERE idempotency_key = 'k2'") == 1);

    const auto replay_all = [&](Session& session) {
        Container& c = session.store->container();
        const std::int64_t revisions = Count(c, "SELECT COUNT(*) FROM revision");
        const std::int64_t versions = Count(c, "SELECT COUNT(*) FROM plane_version");
        const PlaneImage a = session.store->ReadPlane(head, content.plane_a);
        for (const std::optional<std::int64_t> precondition : {std::optional<std::int64_t>(2), std::optional<std::int64_t>()}) {
            bool executed = false;
            const RequestOutcome outcome =
                SubmitStroke(session, StrokeReq("k1", content.plane_a, 21, precondition), content.plane_a, 21, &executed);
            CHECK(outcome.decision.admission == Admission::outcome_unknown && !executed && !outcome.result);
            CHECK(outcome.decision.current_revision == head);
        }
        // A known key inside the window: the stored outcome, despite the newer current revision.
        bool executed = false;
        const RequestOutcome known = SubmitStroke(session, StrokeReq("k2", content.plane_b, 22, k2_base), content.plane_b, 22, &executed);
        CHECK(known.decision.admission == Admission::stored_outcome && !executed);
        CHECK(known.decision.record && known.decision.record->committed_revision == k2_base + 1 && known.decision.current_revision == head);
        CHECK(Count(c, "SELECT COUNT(*) FROM revision") == revisions && Count(c, "SELECT COUNT(*) FROM plane_version") == versions);
        CHECK(session.doc->revision() == head && session.store->ReadPlane(head, content.plane_a) == a);
        CHECK(a == Stroke(Synthetic(kSeedA), 21));  // k1 applied exactly once
    };
    replay_all(s);
    s.Close();
    Session reopened = OpenSession(path);
    CHECK(reopened.report.ok());
    replay_all(reopened);
    CHECK(reopened.store->Compact(*reopened.doc).collapsed.empty());  // nothing more to collapse
    replay_all(reopened);
}

// ── 3.5 Edit → revert → edit → reopen → compact ─────────────────────────────────────────────

void RevertEditReopenCompact() {
    const fs::path dir = WorkDir("revert-compact");
    Content content;
    const fs::path path = CreateProject(dir, content);  // revision 2 writes the approved chunks
    const PlaneImage a0 = Synthetic(kSeedA), b0 = Synthetic(kSeedB);
    std::int64_t reverted = 0;
    {
        Session s = OpenSession(path);
        s.store->Save(*s.doc, SaveOptions{"approved", "client sign-off", true});
        Paint(s, "edit 1", content.plane_a, 31);  // 3: a version only collapsed revisions bind
        Paint(s, "edit 1b", content.plane_a, 32); // 4: a version retained revisions bind after 4 collapses
        AddLayers(s, "between ", 80);             // 5..84
        CHECK(Committed(s.store->Revert(*s.doc, MutationRequest{"project_revert", json::Object{{"checkpoint", "approved"}}, "revert", 84},
                                        std::string("approved"))));
        reverted = s.doc->revision();
        CHECK(reverted == 85);
        CHECK(s.store->ReadPlane(reverted, content.plane_a) == a0 && s.store->ReadPlane(reverted, content.plane_b) == b0);
        Paint(s, "edit 2", content.plane_b, 33);  // 86
    }
    Session s = OpenSession(path);  // reopen
    CHECK(s.report.ok() && s.doc->revision() == 86);
    Container& before = s.store->container();
    const auto version_of = [&](Container& c, std::int64_t revision, Id plane) {
        for (const ManifestBinding& binding : ManifestPlaneBindings(json::Parse(ReadManifestText(c, revision)))) {
            if (binding.plane_id == plane) return binding.version->version_id;
        }
        throw Failure{"unbound plane"};
    };
    const std::int64_t version_edit1 = version_of(before, 3, content.plane_a);
    const std::int64_t version_edit1b = version_of(before, 4, content.plane_a);
    const std::int64_t version_approved_b = version_of(before, 2, content.plane_b);
    const Retention retention = ComputeRetention(before);
    std::set<std::int64_t> retained = {2};
    for (std::int64_t r = 37; r <= 86; ++r) retained.insert(r);
    CHECK(retention.revisions == retained);
    const std::map<std::int64_t, State> expected = Retained(Capture(*s.store), retention.revisions);
    CHECK(expected.at(2).planes.at(content.plane_a) == Digest(a0) && expected.at(2).planes.at(content.plane_b) == Digest(b0));
    CHECK(expected.at(50).planes.at(content.plane_a) == Digest(Stroke(Stroke(a0, 31), 32)));
    CHECK(expected.at(85).planes == expected.at(2).planes);
    CHECK(expected.at(86).planes.at(content.plane_b) == Digest(Stroke(b0, 33)));

    s.store->Compact(*s.doc);
    Container& after = s.store->container();
    CHECK(Capture(*s.store).revisions == expected);
    // The version only revision 3 bound is collected; the one revision 4 wrote stays, and so do
    // the approved chunks of both planes, written at revision 2, outside the mutation window.
    CHECK(Count(after, "SELECT COUNT(*) FROM plane_version WHERE version_id = " + std::to_string(version_edit1)) == 0);
    CHECK(Count(after, "SELECT created_revision FROM plane_version WHERE version_id = " + std::to_string(version_edit1b)) == 4);
    CHECK(Count(after, "SELECT created_revision FROM plane_version WHERE version_id = " + std::to_string(version_approved_b)) == 2);
    CheckReachability(after);
    s.Close();
    Session reopened = OpenSession(path);
    CHECK(reopened.report.ok() && reopened.report.collectable.empty());
    CHECK(Capture(*reopened.store).revisions == expected);
    // The protected checkpoint still reverts to its exact pixels after the compaction.
    CHECK(Committed(reopened.store->Revert(*reopened.doc,
                                           MutationRequest{"project_revert", json::Object{{"checkpoint", "approved"}}, "revert again", 86},
                                           std::string("approved"))));
    CHECK(reopened.store->ReadPlane(87, content.plane_a) == a0 && reopened.store->ReadPlane(87, content.plane_b) == b0);
}

// ── Child processes ─────────────────────────────────────────────────────────────────────────

int Child(const std::string& action, const fs::path& path, const std::string& plane_arg) {
    Session s = OpenSession(path, VerifyLevel::standard);
    if (action == "compact-kill-during-vacuum" || action == "compact-kill-before-rename") {
        fault::Arm(action == "compact-kill-during-vacuum" ? fault::Fault::kill_during_vacuum : fault::Fault::kill_before_rename);
        s.store->Compact(*s.doc);
    } else {
        const ChildStroke* stroke = nullptr;
        for (const ChildStroke& candidate : kChildStrokes) {
            if (action == candidate.action) stroke = &candidate;
        }
        if (stroke == nullptr || plane_arg.empty()) {
            std::fprintf(stderr, "unknown action %s\n", action.c_str());
            return 2;
        }
        const Id plane = static_cast<Id>(std::stoull(plane_arg));
        fault::Arm(stroke->fault);
        SubmitStroke(s, StrokeReq(stroke->key, plane, stroke->seed, s.doc->revision()), plane, stroke->seed);
    }
    std::fprintf(stderr, "the fault hook did not terminate the process\n");
    return 1;
}

std::vector<std::pair<const char*, std::function<void()>>> Cases() {
    return {
        {"interruptions", Interruptions},                         // 3.1
        {"two_layers", TwoLayers},                                // 3.2
        {"commit_then_die", CommitThenDie},                       // 3.3
        {"pruned_key_replay", PrunedKeyReplay},                   // 3.4
        {"revert_edit_reopen_compact", RevertEditReopenCompact},  // 3.5
    };
}

int Run(const std::string& only) {
    int failed = 0;
    int ran = 0;
    for (const auto& [name, body] : Cases()) {
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
        fs::remove_all(fs::temp_directory_path() / ("uzp-store-settle-tests-" + std::to_string(GetCurrentProcessId())), ec);
    }
    return failed == 0 && ran > 0 ? 0 : 1;
}

int Command(int argc, char** argv) {
    const std::string command = argc > 1 ? argv[1] : "";
    if (command == "run") return Run(argc > 2 ? argv[2] : "");
    if (command == "list" && argc == 2) {
        for (const auto& entry : Cases()) std::printf("%s\n", entry.first);
        return 0;
    }
    if (command == "child" && (argc == 4 || argc == 5)) return Child(argv[2], fs::path(argv[3]), argc == 5 ? argv[4] : "");
    std::fprintf(stderr, "usage: uzp-store-settle-tests run [case] | list | child <action> <file> [<plane>]\n");
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
