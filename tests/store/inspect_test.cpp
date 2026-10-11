// Native tests of `uzpainter inspect`, `export-bundle` (with the bundle import of
// `ProjectStore::Open`) and the size census of the project store (`src/store/inspect.h`,
// `bundle.h`, `bundle_codec.h`, `census.h`, `cli.h`; task phase1.7_store-inspect-census).
// Built by `zig build uzp-store-inspect-tests` and driven by tests/store/test_store_inspect.py.
//
// Usage:
//   uzp-store-inspect-tests run [case]              run every native case (or one); exit 0 when all pass
//   uzp-store-inspect-tests child hold-lock <file> <release>
//                                                   open <file> (taking its lock) and keep it open until
//                                                   <release> exists
//   uzp-store-inspect-tests fixture <dir>           write the fixture project <dir>/fixture.uzp
//   uzp-store-inspect-tests png-decode <png> <format> <out>
//                                                   decode <png> as plane format <format>, write its texels
//   uzp-store-inspect-tests cli <verb> [args...]    run a store verb of UzPainter.exe (`cli.h`)

#include <windows.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <functional>
#include <memory>
#include <optional>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include "store/bundle.h"
#include "store/bundle_codec.h"
#include "store/census.h"
#include "store/cli.h"
#include "store/container.h"
#include "store/fault.h"
#include "store/inspect.h"
#include "store/integrity.h"
#include "store/lock.h"
#include "store/planes.h"
#include "store/project_store.h"
#include "uzp_core/document/document.h"
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

std::string Utf8(const fs::path& path) {
    const std::u8string text = path.u8string();
    return std::string(text.begin(), text.end());
}

fs::path WorkDir(const std::string& name) {
    const fs::path dir = fs::temp_directory_path() /
                         ("uzp-store-inspect-tests-" + std::to_string(GetCurrentProcessId())) / name;
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

std::string Noise(std::size_t size, std::uint64_t seed) {
    std::string bytes(size, '\0');
    std::uint64_t x = seed * 0x9E3779B97F4A7C15ull + 1;
    for (char& c : bytes) {
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        c = static_cast<char>(x & 0xff);
    }
    return bytes;
}

PlaneImage Synthetic(int width, int height, ChannelFormat format, std::uint64_t seed) {
    return PlaneImage{width, height, format,
                      Noise(static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * TexelBytes(format), seed)};
}

// ── JSON access ────────────────────────────────────────────────────────────────────────────

/// The member at a dotted path (`a.b.0.c`; numbers index arrays); throws `Failure` when absent.
const json::Value& At(const json::Value& value, const std::string& path) {
    if (path.empty()) return value;
    const json::Value* at = &value;
    std::size_t start = 0;
    while (start <= path.size()) {
        const std::size_t end = std::min(path.find('.', start), path.size());
        const std::string key = path.substr(start, end - start);
        if (const auto* object = std::get_if<json::Object>(&at->data)) {
            const auto it = object->find(key);
            if (it == object->end()) throw Failure{"no member " + path};
            at = &it->second;
        } else if (const auto* array = std::get_if<json::Array>(&at->data)) {
            const std::size_t index = static_cast<std::size_t>(std::stoul(key));
            if (index >= array->size()) throw Failure{"no element " + path};
            at = &(*array)[index];
        } else {
            throw Failure{"not a container at " + path};
        }
        start = end + 1;
    }
    return *at;
}

std::int64_t IntAt(const json::Value& value, const std::string& path) {
    const json::Value& v = At(value, path);
    if (!v.IsInt()) throw Failure{path + " is not an integer"};
    return std::get<std::int64_t>(v.data);
}

double NumberAt(const json::Value& value, const std::string& path) {
    const json::Value& v = At(value, path);
    if (v.IsInt()) return static_cast<double>(std::get<std::int64_t>(v.data));
    if (!v.IsDouble()) throw Failure{path + " is not a number"};
    return std::get<double>(v.data);
}

std::string TextAt(const json::Value& value, const std::string& path) {
    const json::Value& v = At(value, path);
    if (!v.IsString()) throw Failure{path + " is not a string"};
    return std::get<std::string>(v.data);
}

std::size_t SizeAt(const json::Value& value, const std::string& path) {
    const json::Value& v = At(value, path);
    if (const auto* array = std::get_if<json::Array>(&v.data)) return array->size();
    throw Failure{path + " is not a list"};
}

// ── The fixture project ────────────────────────────────────────────────────────────────────

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

Session OpenSession(const fs::path& path, const OpenOptions& options = {}) {
    ProjectStore::Opened opened = ProjectStore::Open(path, options);
    Session s{std::move(opened.store), std::make_unique<Document>(std::move(opened.state)), opened.report};
    s.store->Attach(*s.doc);
    return s;
}

bool Committed(const RequestOutcome& outcome) {
    return outcome.decision.admission == Admission::execute && outcome.result &&
           outcome.result->status == ResultStatus::committed;
}

void Mutate(Session& s, const std::string& key, const std::function<void(Edit&)>& call) {
    CHECK(Committed(s.store->Submit(*s.doc, MutationRequest{"test", json::Object{{"key", key}}, key, s.doc->revision()}, call)));
}

ResourceMeta Meta(Project& p, std::string name, std::string mime, std::size_t size, std::string usage) {
    ResourceMeta meta;
    meta.id = p.AllocateId();
    meta.name = std::move(name);
    meta.mime = std::move(mime);
    meta.size = static_cast<std::int64_t>(size);
    meta.usage = std::move(usage);
    meta.origin = "import";
    meta.imported_at = "2026-10-10T00:00:00Z";
    meta.color_space = "Raw";
    return meta;
}

struct Fixture {
    fs::path path;
    std::string mesh, mask, normal;  // SHA-256 of the resources
    Id set = kNoId, stack = kNoId;
    Id fill = kNoId, paint_a = kNoId, paint_b = kNoId;
    Id plane_a = kNoId, plane_b = kNoId;
    std::int64_t first_revision = 0;  // the revision before the planes
};

/// A project with a mesh, a mask bound by a fill layer, an imported normal mesh map and two
/// paint layers whose planes are L8 1500×1100 (two chunk columns and rows) and RGB32F 300×200.
Fixture MakeFixture(const fs::path& dir, bool portable = true) {
    Fixture f;
    f.path = dir / "fixture.uzp";
    const std::string mesh = "FBX" + Noise(5000, 1), mask = Noise(3000, 2), normal = Noise(4000, 3);
    f.mesh = Sha256Hex(mesh);
    f.mask = Sha256Hex(mask);
    f.normal = Sha256Hex(normal);

    DocumentState state;
    state.project_uuid = kUuid;
    Project& p = state.project;
    p.versions.app_version = "0.0.0";
    p.versions.evaluator_profile = "painter-12.1-isolated-linear";
    TextureSet set;
    set.id = f.set = p.AllocateId();
    set.name = "M_body";
    set.original_name = "M_body";
    set.material_id = "material-0";
    set.uv_tiles = {UVTile{p.AllocateId(), 1001, {}}};
    Stack stack;
    stack.id = f.stack = p.AllocateId();
    stack.channels[ChannelType::BaseColor] = Channel{ChannelFormat::sRGB8, "", {}};
    stack.channels[ChannelType::Height] = Channel{ChannelFormat::L16F, "", {}};
    set.stacks = {stack};
    MeshMapBinding normal_map;
    normal_map.resource = f.normal;
    normal_map.format = ChannelFormat::RGB16;
    normal_map.color_space = "Raw";
    ImportedProvenance provenance;
    provenance.source_path = "A3D/body/normal.png";
    provenance.source_sha256 = f.normal;
    provenance.units = "m";
    normal_map.provenance = provenance;
    set.mesh_maps[MeshMapUsage::Normal] = normal_map;
    p.texture_sets = {set};
    p.resources[f.mesh] = {Meta(p, "body.fbx", "model/fbx", mesh.size(), "MESH")};
    p.resources[f.mask] = {Meta(p, "M_band.png", "image/png", mask.size(), "TEXTURE")};
    p.resources[f.normal] = {Meta(p, "normal.png", "image/png", normal.size(), "TEXTURE")};
    p.mesh = MeshReference{f.mesh, json::Object{{"triangles", 12}}, {}};

    CreateOptions options;
    options.portable = portable;
    options.resources = {{mesh, "model/fbx"}, {mask, "image/png"}, {normal, "image/png"}};
    ProjectStore::Create(f.path, state, options);

    Session s = OpenSession(f.path);
    s.store->Save(*s.doc);
    const InsertPosition top = InsertPosition::FromStack(f.set, f.stack);
    Mutate(s, "fill", [&](Edit& e) {
        f.fill = e.Insert(top, NodeType::FillLayer, "Mask fill");
        for (Layer& layer : e.project().texture_sets[0].stacks[0].root_layers) {
            if (layer.uid != f.fill) continue;
            if (!layer.fill) layer.fill = FillContent{};
            layer.fill->sources[ChannelType::BaseColor] = Source{BitmapSource{ResourceBinding{f.mask, "M_band", {}}, "sRGB", {}}};
            layer.fill->active_channels.insert(ChannelType::BaseColor);
        }
    });
    f.first_revision = s.doc->revision();
    Mutate(s, "paint-a", [&](Edit& e) {
        f.paint_a = e.Insert(top, NodeType::PaintLayer, "Paint A");
        f.plane_a = s.store->CreatePlane(e, PlaneSpec{f.paint_a, ChannelType::BaseColor, 1001, ChannelFormat::L8, 1500, 1100});
        s.store->WritePlane(e, f.plane_a, Synthetic(1500, 1100, ChannelFormat::L8, 11));
    });
    Mutate(s, "paint-b", [&](Edit& e) {
        f.paint_b = e.Insert(top, NodeType::PaintLayer, "Paint B");
        f.plane_b = s.store->CreatePlane(e, PlaneSpec{f.paint_b, ChannelType::Height, 1001, ChannelFormat::RGB32F, 300, 200});
        s.store->WritePlane(e, f.plane_b, Synthetic(300, 200, ChannelFormat::RGB32F, 12));
    });
    s.store->Save(*s.doc, SaveOptions{"approved", "fixture", true});
    s.Close();
    return f;
}

// ── Child processes ────────────────────────────────────────────────────────────────────────

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

// ── Cases ──────────────────────────────────────────────────────────────────────────────────

/// 3.1: every field of 09 §6, `--revision`, the sizes and the CLI.
void InspectFields() {
    const fs::path dir = WorkDir("inspect_fields");
    const Fixture f = MakeFixture(dir);
    const json::Value r = Inspect(f.path);

    CHECK(TextAt(r, "project.uuid") == kUuid);
    CHECK(std::get<bool>(At(r, "project.portable").data));
    CHECK(TextAt(r, "versions.format_version") == "1.0.0" && TextAt(r, "versions.file_format_version") == "1.0.0");
    CHECK(TextAt(r, "versions.app_version") == "0.0.0");
    CHECK(At(r, "versions.painter_reference").IsObject());
    CHECK(TextAt(r, "profiles.evaluator_profile") == "painter-12.1-isolated-linear");
    CHECK(TextAt(r, "profiles.compat_profile") == "painter-12.1-api-0.3.7");
    CHECK(TextAt(r, "settings.normal_map_format") == "OpenGL");
    CHECK(TextAt(r, "mesh.resource") == f.mesh);

    // Texture sets, channels, the layer tree with its bindings.
    CHECK(SizeAt(r, "texture_sets") == 1 && TextAt(r, "texture_sets.0.name") == "M_body");
    CHECK(IntAt(r, "texture_sets.0.uv_tiles.0") == 1001);
    CHECK(TextAt(r, "texture_sets.0.stacks.0.channels.BaseColor.format") == "sRGB8");
    CHECK(TextAt(r, "texture_sets.0.stacks.0.channels.Height.format") == "L16F");
    const json::Value& layers = At(r, "texture_sets.0.stacks.0.layers");
    CHECK(SizeAt(layers, "") == 3);
    CHECK(TextAt(layers, "0.name") == "Paint B" && TextAt(layers, "0.kind") == "paint");
    CHECK(IntAt(layers, "0.bindings.planes.0.plane_id") == static_cast<std::int64_t>(f.plane_b));
    CHECK(TextAt(layers, "0.bindings.planes.0.channel") == "Height");
    CHECK(TextAt(layers, "0.bindings.planes.0.format") == "RGB32F" && IntAt(layers, "0.bindings.planes.0.width") == 300);
    CHECK(IsSha256Hex(TextAt(layers, "0.bindings.planes.0.chunk_root")) && IntAt(layers, "0.bindings.planes.0.version_id") > 0);
    CHECK(IntAt(layers, "1.bindings.planes.0.plane_id") == static_cast<std::int64_t>(f.plane_a));
    CHECK(TextAt(layers, "2.name") == "Mask fill" && SizeAt(layers, "2.bindings.planes") == 0);
    CHECK(TextAt(layers, "2.bindings.resources.0.sha256") == f.mask);
    CHECK(Contains(TextAt(layers, "2.bindings.resources.0.path"), "fill.sources.BaseColor.resource.sha256"));

    // Mesh maps with provenance.
    CHECK(TextAt(r, "texture_sets.0.mesh_maps.0.usage") == "Normal");
    CHECK(TextAt(r, "texture_sets.0.mesh_maps.0.resource") == f.normal);
    CHECK(TextAt(r, "texture_sets.0.mesh_maps.0.provenance.kind") == "imported");
    CHECK(TextAt(r, "texture_sets.0.mesh_maps.0.provenance.source_path") == "A3D/body/normal.png");

    // Resource table.
    CHECK(SizeAt(r, "resources") == 3);
    bool mask_row = false;
    for (const json::Value& row : std::get<json::Array>(At(r, "resources").data)) {
        CHECK(TextAt(row, "storage") == "embedded" && IntAt(row, "stored_bytes") > 0);
        if (TextAt(row, "sha256") == f.mask) {
            mask_row = TextAt(row, "name") == "M_band.png" && IntAt(row, "bytes") == 3000 && TextAt(row, "usage") == "TEXTURE" &&
                       TextAt(row, "mime") == "image/png";
        }
    }
    CHECK(mask_row);

    // Checkpoints, sizes, recipe digest.
    bool approved = false;
    for (const json::Value& row : std::get<json::Array>(At(r, "checkpoints").data)) {
        if (TextAt(row, "name") == "approved") approved = std::get<bool>(At(row, "protected").data) && IntAt(row, "revision") == IntAt(r, "revision.current");
    }
    CHECK(approved);
    CHECK(IntAt(r, "sizes.file_bytes") == static_cast<std::int64_t>(fs::file_size(f.path)));
    CHECK(IntAt(r, "sizes.resources.count") == 3 && IntAt(r, "sizes.resources.bytes") == 5003 + 3000 + 4000);
    CHECK(IntAt(r, "sizes.plane_chunks.count") == 5 && IntAt(r, "sizes.plane_chunks.bytes") == 1500 * 1100 + 300 * 200 * 12);
    CHECK(IntAt(r, "sizes.manifests.count") == IntAt(r, "revisions.count") && IntAt(r, "sizes.manifests.stored_bytes") > 0);
    CHECK(IntAt(r, "sizes.cache.count") == 0 && IntAt(r, "sizes.operations.count") == 3);
    CHECK(IntAt(r, "sizes.external_dependencies.count") == 0 && IntAt(r, "sizes.external_dependencies.bytes") == 0);
    CHECK(!std::get<bool>(At(r, "recipe_digest.available").data));
    CHECK(Contains(TextAt(r, "recipe_digest.reason"), "phase2.2_recipe-and-diagnostics"));
    CHECK(!std::get_if<json::Object>(&r.data)->count("verify"));

    // --revision: the revision before the planes.
    const json::Value earlier = Inspect(f.path, InspectOptions{f.first_revision, false});
    CHECK(IntAt(earlier, "revision.number") == f.first_revision && IntAt(earlier, "revision.current") == IntAt(r, "revision.current"));
    CHECK(SizeAt(earlier, "texture_sets.0.stacks.0.layers") == 1);
    CHECK(TextAt(earlier, "revision.manifest_sha256") != TextAt(r, "revision.manifest_sha256"));
    EXPECT_THROW(CorruptionError, Inspect(f.path, InspectOptions{999, false}));

    // The CLI prints the same report; usage errors exit 2.
    const fs::path out = dir / "inspect.json";
    std::FILE* file = nullptr;
    CHECK(_wfopen_s(&file, out.c_str(), L"wb") == 0);
    const int status = RunStoreCommand({"inspect", Utf8(f.path), "--verify"}, file, stderr);
    std::fclose(file);
    CHECK(status == kCliOk);
    const json::Value printed = json::Parse(ReadBytes(out));
    CHECK(std::get<bool>(At(printed, "verify.ok").data));
    CHECK(At(printed, "texture_sets") == At(r, "texture_sets") && At(printed, "resources") == At(r, "resources"));
    CHECK(RunStoreCommand({"inspect"}, stdout, stderr) == kCliUsage);
    CHECK(RunStoreCommand({"inspect", Utf8(f.path), "--revision", "x"}, stdout, stderr) == kCliUsage);
    CHECK(RunStoreCommand({"inspect", Utf8(dir / "absent.uzp")}, stdout, stderr) == kCliFailed);
}

/// 3.1: inspect (and --verify) while another process holds the project open; nothing waits, the
/// lock stays the child's and the file is unchanged.
void InspectWhileLocked() {
    const fs::path dir = WorkDir("inspect_while_locked");
    const Fixture f = MakeFixture(dir);
    const std::string bytes = ReadBytes(f.path);
    const fs::path release = dir / "release";
    HANDLE holder = StartChild({"child", "hold-lock", Utf8(f.path), Utf8(release)});
    for (int i = 0; i < 600 && !ReadLockOwner(LockPath(f.path)); ++i) Sleep(50);
    const std::optional<LockOwner> owner = ReadLockOwner(LockPath(f.path));
    CHECK(owner && owner->pid != GetCurrentProcessId() && OwnerAlive(*owner));
    EXPECT_THROW(StoreError, ProjectStore::Open(f.path));  // the project is held

    const auto start = std::chrono::steady_clock::now();
    const json::Value plain = Inspect(f.path);
    const json::Value verified = Inspect(f.path, InspectOptions{std::nullopt, true});
    CHECK(std::chrono::steady_clock::now() - start < std::chrono::seconds(30));
    CHECK(TextAt(plain, "project.uuid") == kUuid && std::get<bool>(At(verified, "verify.ok").data));
    CHECK(ReadLockOwner(LockPath(f.path)) == owner);  // still the child's lock, untouched
    CHECK(ReadBytes(f.path) == bytes);

    WriteBytes(release, "");
    CHECK(Wait(holder) == 0);
    CHECK(!fs::exists(LockPath(f.path)));
}

/// 3.1: a non-portable project lists project-file bytes and external dependency bytes separately.
void InspectExternalDependencies() {
    const fs::path dir = WorkDir("inspect_external_dependencies");
    const std::string hdr = Noise(7000, 21);
    WriteBytes(dir / "studio.hdr", hdr);
    DocumentState state;
    state.project_uuid = kUuid;
    Project& p = state.project;
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
    const std::string sha = Sha256Hex(hdr);
    p.resources[sha] = {Meta(p, "studio.hdr", "image/vnd.radiance", hdr.size(), "ENVIRONMENT")};
    p.display.environment.resource = sha;
    CreateOptions options;
    options.portable = false;
    options.locators = {dir / "studio.hdr"};
    const fs::path path = dir / "linked.uzp";
    ProjectStore::Create(path, state, options)->Close();

    const json::Value r = Inspect(path);
    CHECK(!std::get<bool>(At(r, "project.portable").data));
    CHECK(TextAt(r, "resources.0.storage") == "locator" && IntAt(r, "resources.0.stored_bytes") == 0);
    CHECK(IntAt(r, "sizes.external_dependencies.count") == 1);
    CHECK(IntAt(r, "sizes.external_dependencies.bytes") == 7000);
    CHECK(IntAt(r, "sizes.external_dependencies.missing") == 0);
    CHECK(IntAt(r, "sizes.resources.count") == 0);  // nothing of it inside the project file
    CHECK(IntAt(r, "sizes.file_bytes") == static_cast<std::int64_t>(fs::file_size(path)));
    fs::remove(dir / "studio.hdr");
    const json::Value gone = Inspect(path, InspectOptions{std::nullopt, true});
    CHECK(IntAt(gone, "sizes.external_dependencies.missing") == 1);
    CHECK(!std::get<bool>(At(gone, "verify.ok").data) && TextAt(gone, "verify.missing.0.reason") == "absent");
}

/// Runs `sql` on `path` with foreign keys off (to damage a fixture as a faulty writer would).
void Damage(const fs::path& path, const std::string& sql) {
    Container c = Container::Open(path);
    c.Exec("PRAGMA foreign_keys = OFF");
    c.Exec("DROP TRIGGER IF EXISTS plane_version_immutable");
    c.Exec(sql);
}

std::string CliVerify(const fs::path& dir, const fs::path& project, int& status) {
    const fs::path out = dir / "verify.json";
    std::FILE* file = nullptr;
    if (_wfopen_s(&file, out.c_str(), L"wb") != 0) throw Failure{"cannot write verify.json"};
    status = RunStoreCommand({"inspect", Utf8(project), "--verify"}, file, stderr);
    std::fclose(file);
    return ReadBytes(out);
}

/// 3.2: `--verify` fails on a broken plane binding and on a missing blob; the plain report does not
/// verify and still prints.
void VerifyFailures() {
    const fs::path dir = WorkDir("verify_failures");
    {
        const Fixture f = MakeFixture(dir);
        int status = -1;
        CliVerify(dir, f.path, status);
        CHECK(status == kCliOk);
        // Broken plane binding: the bound version of plane A now holds another chunk_root.
        const json::Value before = Inspect(f.path);
        const std::int64_t vid = IntAt(before, "texture_sets.0.stacks.0.layers.1.bindings.planes.0.version_id");
        Damage(f.path, "UPDATE plane_version SET chunk_root = '" + std::string(64, '0') + "' WHERE version_id = " + std::to_string(vid));
        const json::Value r = json::Parse(CliVerify(dir, f.path, status));
        CHECK(status == kCliFailed && !std::get<bool>(At(r, "verify.ok").data));
        CHECK(TextAt(r, "verify.corrupt.0.kind") == "plane" && TextAt(r, "verify.corrupt.0.key") == std::to_string(f.plane_a));
        CHECK(Contains(TextAt(r, "verify.corrupt.0.detail"), "chunk_root mismatch"));
        CHECK(IntAt(r, "verify.corrupt.0.nodes.0.id") == static_cast<std::int64_t>(f.paint_a));
        CHECK(TextAt(Inspect(f.path), "project.uuid") == kUuid);  // without --verify the report still prints
    }
    for (const char* which : {"resource", "chunk"}) {
        const fs::path sub = WorkDir(std::string("verify_failures_") + which);
        const Fixture f = MakeFixture(sub);
        std::string missing = f.mask;
        if (std::string(which) == "chunk") {
            Container c = Container::OpenReadOnly(f.path);
            Statement q(c, "SELECT sha256 FROM plane_chunk ORDER BY sha256 LIMIT 1");
            CHECK(q.Step());
            missing = q.Text(0);
        }
        Damage(f.path, "DELETE FROM blob WHERE sha256 = '" + missing + "'");
        int status = -1;
        const json::Value r = json::Parse(CliVerify(sub, f.path, status));
        CHECK(status == kCliFailed && !std::get<bool>(At(r, "verify.ok").data));
        bool named = false;
        for (const json::Value& item : std::get<json::Array>(At(r, "verify.corrupt").data)) {
            const std::string kind = TextAt(item, "kind"), key = TextAt(item, "key"), detail = TextAt(item, "detail");
            if (std::string(which) == "resource") {
                named = named || (kind == "blob" && key == missing && Contains(detail, "missing") && SizeAt(item, "nodes") >= 1);
            } else {
                named = named || kind == "foreign_key" || (kind == "plane" && Contains(detail, missing));
            }
        }
        CHECK(named);
        if (std::string(which) == "resource") {
            bool listed = false;
            for (const json::Value& row : std::get<json::Array>(At(Inspect(f.path), "resources").data)) {
                listed = listed || (TextAt(row, "sha256") == missing && TextAt(row, "storage") == "missing");
            }
            CHECK(listed);
        }
    }
}

/// 3.3: export-bundle → project.open of the bundle directory → equal manifest digest and planes;
/// the ZIP form holds the same files; a damaged bundle is refused and leaves no project.
void BundleRoundTrip() {
    const fs::path dir = WorkDir("bundle_round_trip");
    const Fixture f = MakeFixture(dir);
    const fs::path bundle = dir / "bundle";
    const BundleSummary summary = ExportBundle(f.path, bundle);
    CHECK(summary.resources == 3 && summary.mesh_maps == 1 && summary.planes == 2);
    CHECK(fs::exists(bundle / "manifest.json") && fs::exists(bundle / "bundle.json") && !fs::exists(dir / "bundle.partial"));
    CHECK(fs::exists(bundle / "res" / (f.mesh + ".fbx")) && fs::exists(bundle / "res" / (f.mask + ".png")));
    CHECK(fs::exists(bundle / "meshmaps" / "M_body_Normal.png"));
    CHECK(fs::exists(bundle / "planes" / (std::to_string(f.plane_a) + ".png")));
    CHECK(fs::exists(bundle / "planes" / (std::to_string(f.plane_b) + ".exr")));
    CHECK(Sha256Hex(ReadBytes(bundle / "manifest.json")) == summary.manifest_sha256);
    EXPECT_THROW(StoreError, ExportBundle(f.path, bundle));  // exists

    // project.open on the bundle directory.
    Session source = OpenSession(f.path);
    Session imported = OpenSession(bundle);
    const fs::path target = BundleImportTarget(bundle);
    CHECK(imported.store->path() == target && fs::exists(target));
    CHECK(imported.report.ok());
    CHECK(ManifestDigest(*imported.doc->snapshot().project) == summary.manifest_sha256);
    CHECK(ManifestDigest(*source.doc->snapshot().project) == summary.manifest_sha256);
    CHECK(imported.doc->revision() == source.doc->revision() && imported.store->project_uuid() == kUuid);
    for (const Id plane : {f.plane_a, f.plane_b}) {
        CHECK(imported.store->ReadPlane(imported.doc->revision(), plane) == source.store->ReadPlane(source.doc->revision(), plane));
    }
    CHECK(imported.store->ReadResource(f.mesh) == source.store->ReadResource(f.mesh));
    const json::Value verify = Inspect(target, InspectOptions{std::nullopt, true});
    CHECK(std::get<bool>(At(verify, "verify.ok").data));
    // No operation row comes along: a retried key with an older precondition is expired, not stale (§4).
    CHECK(IntAt(verify, "project.operation_horizon_revision") == imported.doc->revision());
    const RequestOutcome retried = imported.store->Submit(
        *imported.doc, MutationRequest{"test", json::Object{{"key", "retried"}}, "retried", imported.doc->revision() - 1}, [](Edit&) {});
    CHECK(retried.decision.admission == Admission::outcome_unknown);
    // The imported project keeps working: a further edit commits.
    Mutate(imported, "after-import", [&](Edit& e) {
        e.Insert(InsertPosition::FromStack(f.set, f.stack), NodeType::FillLayer, "After import");
    });
    imported.Close();
    source.Close();
    EXPECT_THROW(StoreError, ProjectStore::Open(bundle));  // the import target exists now

    // An explicit target, an older revision.
    const fs::path older = dir / "older";
    ExportBundle(f.path, older, f.first_revision);
    {
        ImportBundle(older, dir / "older-import.uzp");
        Session s = OpenSession(dir / "older-import.uzp", OpenOptions{VerifyLevel::full, VersionPolicy::Current()});
        CHECK(s.store->path() == dir / "older-import.uzp" && s.doc->revision() == f.first_revision && s.report.ok());
        s.Close();
    }

    // ZIP: the same files (the Python driver also opens it with zipfile).
    const fs::path zip = dir / "bundle.ZIP";
    ExportBundle(f.path, zip);
    const std::string archive = ReadBytes(zip);
    CHECK(archive.substr(0, 4) == std::string("PK\x03\x04", 4) && Contains(archive, "manifest.json") && Contains(archive, "bundle.json"));
    CHECK(Contains(archive, ReadBytes(bundle / "manifest.json")));

    // A damaged plane file is refused; no project is left.
    const fs::path broken = dir / "broken";
    fs::copy(bundle, broken, fs::copy_options::recursive);
    std::string png = ReadBytes(broken / "planes" / (std::to_string(f.plane_a) + ".png"));
    png[png.size() / 2] = static_cast<char>(png[png.size() / 2] ^ 0x40);
    WriteBytes(broken / "planes" / (std::to_string(f.plane_a) + ".png"), png);
    const StoreError error = EXPECT_THROW(StoreError, ProjectStore::Open(broken));
    CHECK(error.code() == StoreError::Code::corrupt);
    CHECK(!fs::exists(BundleImportTarget(broken)) && !fs::exists(LockPath(BundleImportTarget(broken))));
    // A manifest that does not hash to manifest_sha256 is refused.
    const fs::path edited = dir / "edited";
    fs::copy(bundle, edited, fs::copy_options::recursive);
    WriteBytes(edited / "manifest.json", ReadBytes(edited / "manifest.json") + " ");
    CHECK(EXPECT_THROW(StoreError, ImportBundle(edited, dir / "edited.uzp")).code() == StoreError::Code::corrupt);
    CHECK(!fs::exists(dir / "edited.uzp"));

    // Texture sets "Body" and "body": their mesh maps get two files, not one on NTFS.
    DocumentState cased;
    cased.project_uuid = kUuid;
    Project& p = cased.project;
    p.versions.app_version = "0.0.0";
    p.versions.evaluator_profile = "painter-12.1-isolated-linear";
    const std::string mesh = "FBX" + Noise(500, 41);
    p.resources[Sha256Hex(mesh)] = {Meta(p, "cased.fbx", "model/fbx", mesh.size(), "MESH")};
    p.mesh = MeshReference{Sha256Hex(mesh), json::Object{{"triangles", 12}}, {}};
    CreateOptions options;
    options.resources = {{mesh, "model/fbx"}};
    std::uint64_t seed = 42;
    for (const char* name : {"Body", "body"}) {
        const std::string normal = Noise(400, ++seed);
        TextureSet set;
        set.id = p.AllocateId();
        set.name = set.original_name = name;
        set.material_id = std::string("material-") + name;
        set.uv_tiles = {UVTile{p.AllocateId(), 1001, {}}};
        Stack stack;
        stack.id = p.AllocateId();
        set.stacks = {stack};
        MeshMapBinding map;
        map.resource = Sha256Hex(normal);
        map.color_space = "Raw";
        ImportedProvenance provenance;
        provenance.source_sha256 = map.resource;
        map.provenance = provenance;
        set.mesh_maps[MeshMapUsage::Normal] = map;
        p.texture_sets.push_back(set);
        p.resources[map.resource] = {Meta(p, std::string(name) + "_normal.png", "image/png", normal.size(), "TEXTURE")};
        options.resources.push_back({normal, "image/png"});
    }
    ProjectStore::Create(dir / "cased.uzp", cased, options);
    CHECK(ExportBundle(dir / "cased.uzp", dir / "cased").mesh_maps == 2);
    CHECK(std::distance(fs::directory_iterator(dir / "cased" / "meshmaps"), fs::directory_iterator{}) == 2);
    ImportBundle(dir / "cased", dir / "cased.import.uzp");  // every resource file hashes
}

/// The bundle codecs: every plane format round-trips bit-exact through PNG or OpenEXR.
void CodecFormats() {
    std::uint64_t seed = 100;
    for (const ChannelFormat format : {ChannelFormat::sRGB8, ChannelFormat::L8, ChannelFormat::RGB8, ChannelFormat::L16,
                                       ChannelFormat::RGB16, ChannelFormat::L16F, ChannelFormat::RGB16F, ChannelFormat::L32F,
                                       ChannelFormat::RGB32F}) {
        for (const auto& [w, h] : {std::pair{1, 1}, std::pair{37, 5}, std::pair{300, 129}}) {
            const PlaneImage image = Synthetic(w, h, format, ++seed);
            const bool exr = codec::IsExrFormat(format);
            const std::string bytes = exr ? codec::EncodeExr(image) : codec::EncodePng(image);
            const PlaneImage back = exr ? codec::DecodeExr(bytes, format) : codec::DecodePng(bytes, format);
            CHECK(back == image);
        }
    }
    // A PNG read as another format, and a truncated file, are refused.
    const std::string png = codec::EncodePng(Synthetic(8, 8, ChannelFormat::L16, 1));
    EXPECT_THROW(StoreError, codec::DecodePng(png, ChannelFormat::L8));
    EXPECT_THROW(StoreError, codec::DecodePng(png.substr(0, png.size() - 20), ChannelFormat::L16));
    const std::string exr = codec::EncodeExr(Synthetic(8, 8, ChannelFormat::RGB16F, 2));
    EXPECT_THROW(StoreError, codec::DecodeExr(exr, ChannelFormat::L16F));
    CHECK(codec::Crc32("123456789") == 0xCBF43926u);
}

/// 3.4: the census instrumentation on a scripted edit sequence.
void CensusSequence() {
    const fs::path dir = WorkDir("census_sequence");
    const fs::path assets = dir / "assets";
    fs::create_directories(assets / "masks");
    WriteBytes(assets / "piece.fbx", Noise(200000, 31));
    WriteBytes(assets / "normal.png", Noise(50000, 32));
    WriteBytes(assets / "masks" / "M_a.png", Noise(20000, 33));
    WriteBytes(assets / "masks" / "M_b.png", Noise(10000, 34));
    WriteBytes(assets / "piece.spp", Noise(4000000, 35));
    const json::Value inputs = json::Parse(R"({
        "schema": "uzpainter/store-census-inputs/1",
        "projects": [{
            "id": "piece_v1", "spp": "piece.spp", "mesh": "piece.fbx",
            "texture_sets": [{"name": "Piece", "resolution": 2048, "mesh_maps": {"Normal": "normal.png"}}],
            "resources": ["masks"], "not_measured": ["painter_baked_mesh_maps"]
        }]
    })");
    const std::vector<CensusProjectInput> projects = ReadCensusInputs(inputs, assets);
    CHECK(projects.size() == 1 && projects[0].resources.size() == 2 && projects[0].sets[0].mesh_maps.size() == 1);
    const json::Value report = RunCensus(projects, CensusOptions{dir / "work", 6});
    CHECK(TextAt(report, "schema") == "uzpainter/store-census/1" && NumberAt(report, "candidate_budget_fraction") == 0.1);
    const json::Value& p = At(report, "projects.0");
    CHECK(TextAt(p, "id") == "piece_v1" && IntAt(p, "spp_bytes") == 4000000);
    CHECK(IntAt(p, "dependencies.files") == 4 && IntAt(p, "dependencies.bytes") == 280000);
    CHECK(TextAt(p, "dependencies.not_measured.0") == "painter_baked_mesh_maps");
    CHECK(IntAt(p, "first_save.file_growth_bytes") > 280000 && IntAt(p, "first_save.io_bytes_written") > 280000);
    CHECK(NumberAt(p, "first_save.seconds") >= 0);
    CHECK(IntAt(p, "one_parameter_edits.count") == 6);
    CHECK(NumberAt(p, "one_parameter_edits.io_bytes_written.mean") > 0);
    CHECK(IntAt(p, "one_parameter_edits.io_bytes_written.total") >= IntAt(p, "one_parameter_edits.io_bytes_written.max"));
    CHECK(IntAt(p, "one_parameter_edits.file_growth_bytes.max") < 100000);  // an edit costs what it changes
    CHECK(IntAt(p, "one_parameter_edits.manifest_stored_bytes_mean") > 0);
    CHECK(IntAt(p, "raster_plane.width") == 2048 && TextAt(p, "raster_plane.format") == "sRGB8");
    CHECK(IntAt(p, "raster_plane.create.stored_chunk_bytes") > 0);
    CHECK(IntAt(p, "raster_plane.edit.stored_chunk_bytes") > 0);  // one new chunk blob
    CHECK(IntAt(p, "raster_plane.edit.stored_chunk_bytes") <= 1024 * 1024 * 3);
    CHECK(NumberAt(p, "reopen_seconds") > 0 && NumberAt(p, "compaction.seconds") > 0);
    CHECK(IntAt(p, "compaction.file_bytes_after") <= IntAt(p, "compaction.file_bytes_before"));
    CHECK(IntAt(p, "retained_history.revisions") == 6 + 3);  // all but the current: first save, layer, 6 edits, plane create
    CHECK(IntAt(p, "retained_history.manifest_bytes") > 0 && IntAt(p, "retained_history.blob_bytes") > 0);
    CHECK(IntAt(p, "retained_history.total_bytes") ==
          IntAt(p, "retained_history.manifest_bytes") + IntAt(p, "retained_history.blob_bytes") + IntAt(p, "retained_history.operation_bytes"));
    const fs::path uzp = dir / "work" / "piece_v1" / "piece_v1.uzp";
    CHECK(IntAt(p, "project_bytes") == static_cast<std::int64_t>(fs::file_size(uzp)));
    CHECK(IntAt(p, "external_dependency_bytes") == 0);
    CHECK(NumberAt(p, "ratio_to_spp") > 0 && std::get<bool>(At(p, "within_candidate_budget").data) == (NumberAt(p, "ratio_to_spp") <= 0.1));
    CHECK(!fs::exists(LockPath(uzp)) && std::get<bool>(At(Inspect(uzp, InspectOptions{std::nullopt, true}), "verify.ok").data));
    // A missing dependency is an error naming it.
    const json::Value bad = json::Parse(R"({"schema": "uzpainter/store-census-inputs/1", "projects": [{"id": "x", "spp": "",
        "mesh": "absent.fbx", "texture_sets": [], "resources": [], "not_measured": []}]})");
    CHECK(Contains(EXPECT_THROW(StoreError, ReadCensusInputs(bad, assets)).what(), "absent.fbx"));
    // An id is a plain name: it names a folder of the work dir that the census replaces.
    for (const std::string id : {"", "..", ".", "a/b", "a\\\\b", "C:/x", "piece v1"}) {
        const json::Value unsafe = json::Parse(R"({"schema": "uzpainter/store-census-inputs/1", "projects": [{"id": ")" + id +
                                               R"(", "spp": "", "mesh": "piece.fbx", "texture_sets": [{"name": "Piece", "resolution": 2048,
            "mesh_maps": {}}], "resources": [], "not_measured": []}]})");
        CHECK(Contains(EXPECT_THROW(ValueError, ReadCensusInputs(unsafe, assets)).what(), "is not a plain name"));
    }
}

// ── Commands ───────────────────────────────────────────────────────────────────────────────

int Run(const std::string& only) {
    const std::vector<std::pair<const char*, std::function<void()>>> cases = {
        {"inspect_fields", InspectFields},                              // 3.1
        {"inspect_while_locked", InspectWhileLocked},                   // 3.1
        {"inspect_external_dependencies", InspectExternalDependencies},  // 3.1
        {"verify_failures", VerifyFailures},                            // 3.2
        {"bundle_round_trip", BundleRoundTrip},                         // 3.3
        {"codec_formats", CodecFormats},                                // 3.3
        {"census_sequence", CensusSequence},                            // 3.4
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
        fs::remove_all(fs::temp_directory_path() / ("uzp-store-inspect-tests-" + std::to_string(GetCurrentProcessId())), ec);
    }
    return failed == 0 && ran > 0 ? 0 : 1;
}

int Command(int argc, char** argv) {
    const std::string command = argc > 1 ? argv[1] : "";
    if (command == "run") return Run(argc > 2 ? argv[2] : "");
    if (command == "child" && argc == 5 && std::string(argv[2]) == "hold-lock") {
        Session s = OpenSession(fs::path(argv[3]));
        for (int i = 0; i < 6000 && !fs::exists(fs::path(argv[4])); ++i) Sleep(50);
        s.Close();
        return 0;
    }
    if (command == "fixture" && argc == 3) {
        fs::create_directories(argv[2]);
        MakeFixture(fs::path(argv[2]));
        return 0;
    }
    if (command == "png-decode" && argc == 5) {
        const auto format = FromString<ChannelFormat>(argv[3]);
        if (!format) return 2;
        WriteBytes(argv[4], codec::DecodePng(ReadBytes(argv[2]), *format).texels);
        return 0;
    }
    if (command == "cli" && argc >= 3) return RunStoreCommand(std::vector<std::string>(argv + 2, argv + argc), stdout, stderr);
    std::fprintf(stderr,
                 "usage: uzp-store-inspect-tests run [case] | child hold-lock <file> <release> | fixture <dir> | "
                 "png-decode <png> <format> <out> | cli <verb> [args...]\n");
    return 2;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        return Command(argc, argv);
    } catch (const Failure& failure) {
        std::fprintf(stderr, "Error: %s\n", failure.message.c_str());
    } catch (const std::exception& error) {
        std::fprintf(stderr, "Error: %s\n", error.what());
    }
    return 3;
}
