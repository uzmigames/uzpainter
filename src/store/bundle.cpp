#include "store/bundle.h"

#include <algorithm>
#include <cctype>
#include <fstream>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <utility>
#include <vector>

#include "store/blobs.h"
#include "store/bundle_codec.h"
#include "store/commit.h"
#include "store/container.h"
#include "store/inspect.h"
#include "store/integrity.h"
#include "store/lock.h"
#include "store/planes.h"
#include "store/versioning.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"

namespace uzp::store {

using core::json::Array;
using core::json::Object;
using core::json::Value;
namespace fs = std::filesystem;

namespace {

std::string Utf8(const fs::path& path) {
    const std::u8string text = path.u8string();
    return std::string(text.begin(), text.end());
}

fs::path FromUtf8(std::string_view text) { return fs::path(std::u8string(text.begin(), text.end())); }

[[noreturn]] void Corrupt(const std::string& what) { throw StoreError(StoreError::Code::corrupt, what); }

std::string ReadFile(const fs::path& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) throw StoreError(StoreError::Code::io, "cannot read " + Utf8(path));
    std::ostringstream bytes;
    bytes << file.rdbuf();
    if (file.bad()) throw StoreError(StoreError::Code::io, "cannot read " + Utf8(path));
    return bytes.str();
}

void WriteFile(const fs::path& path, std::string_view bytes) {
    std::error_code ec;
    fs::create_directories(path.parent_path(), ec);
    std::ofstream file(path, std::ios::binary | std::ios::trunc);
    file.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    file.close();
    if (!file) throw StoreError(StoreError::Code::io, "cannot write " + Utf8(path));
}

const Value* Member(const Value& value, std::string_view key) {
    const auto* object = std::get_if<Object>(&value.data);
    if (object == nullptr) return nullptr;
    const auto it = object->find(key);
    return it == object->end() ? nullptr : &it->second;
}

std::string Text(const Value& value, std::string_view key, std::string_view where) {
    const Value* member = Member(value, key);
    if (member == nullptr || !member->IsString()) Corrupt(std::string(where) + ": " + std::string(key) + " is not a string");
    return std::get<std::string>(member->data);
}

std::int64_t Int(const Value& value, std::string_view key, std::string_view where) {
    const Value* member = Member(value, key);
    if (member == nullptr || !member->IsInt()) Corrupt(std::string(where) + ": " + std::string(key) + " is not an integer");
    return std::get<std::int64_t>(member->data);
}

/// The file extension of a resource: from its MIME type, else from its name, else `bin`.
std::string Extension(std::string_view mime, std::string_view name) {
    static const std::map<std::string, std::string, std::less<>> by_mime = {
        {"image/png", "png"},           {"image/x-exr", "exr"},       {"image/exr", "exr"},
        {"image/aces", "exr"},          {"image/jpeg", "jpg"},        {"image/tiff", "tif"},
        {"image/x-tga", "tga"},         {"image/bmp", "bmp"},         {"image/vnd.radiance", "hdr"},
        {"image/svg+xml", "svg"},       {"model/fbx", "fbx"},         {"model/obj", "obj"},
        {"model/gltf-binary", "glb"},   {"model/gltf+json", "gltf"},  {"font/ttf", "ttf"},
        {"font/otf", "otf"},            {"application/json", "json"},
    };
    if (const auto it = by_mime.find(mime); it != by_mime.end()) return it->second;
    const std::size_t dot = name.rfind('.');
    if (dot != std::string_view::npos && dot + 1 < name.size()) {
        std::string ext(name.substr(dot + 1));
        if (std::all_of(ext.begin(), ext.end(), [](char c) { return std::isalnum(static_cast<unsigned char>(c)) != 0; })) {
            std::transform(ext.begin(), ext.end(), ext.begin(), [](char c) { return static_cast<char>(std::tolower(static_cast<unsigned char>(c))); });
            return ext;
        }
    }
    return "bin";
}

/// `text` with every character outside `[A-Za-z0-9._-]` replaced by `_`.
std::string SafeName(std::string_view text) {
    std::string out(text);
    for (char& c : out) {
        const auto u = static_cast<unsigned char>(c);
        if (!(std::isalnum(u) || c == '.' || c == '_' || c == '-')) c = '_';
    }
    return out.empty() ? std::string("_") : out;
}

/// `name` in ASCII lower case: bundle paths that differ only in case are one file on NTFS and in
/// a ZIP extracted there.
std::string Folded(std::string name) {
    std::transform(name.begin(), name.end(), name.begin(), [](char c) { return static_cast<char>(std::tolower(static_cast<unsigned char>(c))); });
    return name;
}

/// Where the files of a bundle go: a directory or a ZIP.
class Sink {
public:
    virtual ~Sink() = default;
    virtual void Put(const std::string& name, std::string_view bytes) = 0;
    virtual void Finish() = 0;
};

class DirectorySink : public Sink {
public:
    explicit DirectorySink(fs::path root) : root_(std::move(root)) { fs::create_directories(root_); }
    void Put(const std::string& name, std::string_view bytes) override { WriteFile(root_ / FromUtf8(name), bytes); }
    void Finish() override {}

private:
    fs::path root_;
};

class ZipSink : public Sink {
public:
    explicit ZipSink(const fs::path& path) : zip_(path) {}
    void Put(const std::string& name, std::string_view bytes) override { zip_.Add(name, bytes); }
    void Finish() override { zip_.Finish(); }

private:
    codec::ZipWriter zip_;
};

/// The verified bytes of resource `sha256`: embedded, or (non-portable) read through its locator.
std::string ResourceBytes(Container& container, const std::string& sha256, const Value& manifest) {
    if (HasBlob(container, sha256)) {
        try {
            return ReadBlob(container, sha256);
        } catch (const StoreError& error) {
            if (error.code() != StoreError::Code::corrupt) throw;
            throw CorruptionError(CorruptItem{"blob", sha256, error.what(), NodesBinding(manifest, sha256)});
        }
    }
    if (const std::optional<fs::path> locator = FindLocator(container, sha256)) {
        std::string bytes = ReadFile(*locator);
        if (core::Sha256Hex(bytes) != sha256) {
            throw StoreError(StoreError::Code::missing_dependency, Utf8(*locator) + " no longer hashes to " + sha256);
        }
        return bytes;
    }
    throw StoreError(StoreError::Code::missing_resource, "resource " + sha256 + " is neither stored nor located");
}

std::string BlobMime(Container& container, const std::string& sha256) {
    Statement q(container, "SELECT mime FROM blob WHERE sha256 = ?");
    q.Bind(1, sha256);
    return q.Step() && !q.IsNull(0) ? q.Text(0) : std::string();
}

/// A relative path inside the bundle (no root, no `..`).
fs::path Inside(const fs::path& bundle, const std::string& file) {
    const fs::path relative = FromUtf8(file);
    if (file.empty() || relative.is_absolute() || relative.has_root_name() || relative.has_root_directory()) {
        Corrupt("bundle.json: " + file + " is not a relative path");
    }
    for (const fs::path& part : relative) {
        if (part == "..") Corrupt("bundle.json: " + file + " leaves the bundle");
    }
    return bundle / relative;
}

}  // namespace

BundleSummary ExportBundle(const fs::path& project, const fs::path& requested, std::optional<std::int64_t> revision) {
    const fs::path target = requested.has_filename() ? requested : requested.parent_path();  // a trailing separator
    std::error_code ec;
    if (fs::exists(target, ec)) throw StoreError(StoreError::Code::exists, Utf8(target) + " already exists");
    std::string extension = Utf8(target.extension());
    std::transform(extension.begin(), extension.end(), extension.begin(),
                   [](char c) { return static_cast<char>(std::tolower(static_cast<unsigned char>(c))); });
    const bool zip = extension == ".zip";

    ReadSnapshot snapshot(project);
    Container& container = snapshot.container();
    if (!container.HasTable("meta")) throw StoreError(StoreError::Code::not_a_project, Utf8(project) + " is not a .uzp project");
    const std::optional<std::string> version_text = container.Meta("format_version");
    const std::optional<std::string> uuid = container.Meta("project_uuid");
    if (!version_text || !uuid) throw StoreError(StoreError::Code::not_a_project, Utf8(project) + " has no format_version or project_uuid");
    CheckReadable(FormatVersion::Parse(*version_text), VersionPolicy::Current());

    BundleSummary summary;
    summary.revision = revision.value_or(ReadCurrentRevision(container));
    const std::string text = ReadManifestText(container, summary.revision);
    const Value manifest = core::json::Parse(text);
    summary.manifest_sha256 = core::Sha256Hex(text);

    // Mesh-map resources go to meshmaps/, named after their first binding.
    std::map<std::string, std::string, std::less<>> mesh_map_files;
    std::set<std::string, std::less<>> used;  // case-folded (`Folded`)
    if (const Value* sets = Member(manifest, "texture_sets"); sets && sets->IsArray()) {
        for (const Value& set : std::get<Array>(sets->data)) {
            const Value* maps = Member(set, "mesh_maps");
            if (maps == nullptr || !maps->IsObject()) continue;
            const Value* name = Member(set, "name");
            const std::string set_name = name && name->IsString() ? std::get<std::string>(name->data) : "set";
            for (const auto& [usage, map] : std::get<Object>(maps->data)) {
                const Value* resource = Member(map, "resource");
                if (resource == nullptr || !resource->IsString()) continue;
                const std::string& sha256 = std::get<std::string>(resource->data);
                if (mesh_map_files.count(sha256) == 0) mesh_map_files[sha256] = SafeName(set_name + "_" + usage);
            }
        }
    }

    fs::path partial = target;
    partial += ".partial";
    fs::remove_all(partial, ec);  // a killed export's leftover
    try {
        std::unique_ptr<Sink> sink;
        if (zip) {
            sink = std::make_unique<ZipSink>(partial);
        } else {
            sink = std::make_unique<DirectorySink>(partial);
        }
        sink->Put("manifest.json", text);

        Array resources;
        if (const Value* listed = Member(manifest, "resources"); listed && listed->IsObject()) {
            for (const auto& [sha256, entries] : std::get<Object>(listed->data)) {
                const std::string bytes = ResourceBytes(container, sha256, manifest);
                std::string mime = BlobMime(container, sha256);
                std::string name;
                if (entries.IsArray() && !std::get<Array>(entries.data).empty()) {
                    const Value& first = std::get<Array>(entries.data).front();
                    if (const Value* n = Member(first, "name"); n && n->IsString()) name = std::get<std::string>(n->data);
                    if (const Value* m = Member(first, "mime"); mime.empty() && m && m->IsString()) mime = std::get<std::string>(m->data);
                }
                const std::string ext = Extension(mime, name);
                std::string file;
                if (const auto it = mesh_map_files.find(sha256); it != mesh_map_files.end()) {
                    file = "meshmaps/" + it->second + "." + ext;
                    if (used.count(Folded(file)) != 0) file = "meshmaps/" + sha256 + "." + ext;
                    ++summary.mesh_maps;
                } else {
                    file = "res/" + sha256 + "." + ext;
                }
                used.insert(Folded(file));
                sink->Put(file, bytes);
                resources.push_back(Object{{"sha256", sha256},
                                           {"file", file},
                                           {"mime", mime},
                                           {"bytes", static_cast<std::int64_t>(bytes.size())}});
                ++summary.resources;
            }
        }

        Array planes;
        for (const ManifestBinding& binding : ManifestPlaneBindings(manifest)) {
            if (!binding.version) {
                throw CorruptionError(CorruptItem{"plane", std::to_string(binding.plane_id), binding.error, {}});
            }
            const std::optional<PlaneRow> row = ReadPlaneRow(container, binding.plane_id);
            if (!row) {
                throw CorruptionError(CorruptItem{"plane", std::to_string(binding.plane_id), "the bound plane has no plane row", {}});
            }
            const PlaneImage image = ReadPlaneAt(container, summary.revision, binding.plane_id);
            const bool exr = codec::IsExrFormat(row->format);
            const std::string file = "planes/" + std::to_string(binding.plane_id) + (exr ? ".exr" : ".png");
            sink->Put(file, exr ? codec::EncodeExr(image) : codec::EncodePng(image));
            planes.push_back(Object{
                {"plane_id", static_cast<std::int64_t>(binding.plane_id)},
                {"file", file},
                {"format", std::string(core::ToString(row->format))},
                {"width", std::int64_t{row->width}},
                {"height", std::int64_t{row->height}},
                {"set_id", static_cast<std::int64_t>(row->set_id)},
                {"stack_id", static_cast<std::int64_t>(row->stack_id)},
                {"channel", row->channel ? Value(std::string(core::ToString(*row->channel))) : Value()},
                {"tile_u", std::int64_t{row->tile_u}},
                {"tile_v", std::int64_t{row->tile_v}},
                {"version_id", binding.version->version_id},
                {"chunk_root", binding.version->chunk_root},
            });
            ++summary.planes;
        }

        sink->Put("bundle.json", WriteIndented(Object{{"schema", std::string(kBundleSchema)},
                                                      {"project_uuid", *uuid},
                                                      {"revision", summary.revision},
                                                      {"manifest_sha256", summary.manifest_sha256},
                                                      {"resources", std::move(resources)},
                                                      {"planes", std::move(planes)}}));
        sink->Finish();
        sink.reset();
        fs::rename(partial, target);
    } catch (...) {
        fs::remove_all(partial, ec);
        throw;
    }
    return summary;
}

bool IsBundleDirectory(const fs::path& path) {
    std::error_code ec;
    return fs::is_directory(path, ec) && fs::is_regular_file(path / "bundle.json", ec);
}

fs::path BundleImportTarget(const fs::path& bundle) {
    fs::path dir = bundle;
    if (!dir.has_filename()) dir = dir.parent_path();  // a trailing separator
    fs::path target = dir;
    target += ".uzp";
    return target;
}

void ImportBundle(const fs::path& bundle, const fs::path& target) {
    std::error_code ec;
    if (fs::exists(target, ec)) throw StoreError(StoreError::Code::exists, Utf8(target) + " already exists");
    Value index;
    try {
        index = core::json::Parse(ReadFile(bundle / "bundle.json"));
    } catch (const core::json::ParseError& error) {
        Corrupt("bundle.json: " + std::string(error.what()));
    }
    if (Text(index, "schema", "bundle.json") != kBundleSchema) Corrupt("bundle.json: schema is not " + std::string(kBundleSchema));
    const std::string uuid = Text(index, "project_uuid", "bundle.json");
    const std::int64_t revision = Int(index, "revision", "bundle.json");
    const std::string digest = Text(index, "manifest_sha256", "bundle.json");
    if (uuid.empty() || revision < 0) Corrupt("bundle.json: invalid project_uuid or revision");

    const std::string text = ReadFile(bundle / "manifest.json");
    if (core::Sha256Hex(text) != digest) Corrupt("manifest.json does not hash to manifest_sha256 " + digest);
    core::Project project;
    try {
        project = core::LoadManifest(text);
    } catch (const std::exception& error) {
        Corrupt("manifest.json cannot be read: " + std::string(error.what()));
    }
    if (core::SaveManifest(project) != text) Corrupt("manifest.json is not in canonical form");
    const Value manifest = core::json::Parse(text);

    PendingContent pending;
    if (const Value* listed = Member(index, "resources"); listed && listed->IsArray()) {
        for (const Value& entry : std::get<Array>(listed->data)) {
            const std::string sha256 = Text(entry, "sha256", "bundle.json resources");
            const std::string file = Text(entry, "file", "bundle.json resources");
            std::string bytes = ReadFile(Inside(bundle, file));
            if (core::Sha256Hex(bytes) != sha256) Corrupt(file + " does not hash to " + sha256);
            const Value* mime = Member(entry, "mime");
            pending.blobs[sha256] = PendingContent::Bytes{std::move(bytes), mime && mime->IsString() ? std::get<std::string>(mime->data) : ""};
        }
    } else {
        Corrupt("bundle.json: resources is not a list");
    }

    std::map<core::Id, Value> plane_entries;
    if (const Value* listed = Member(index, "planes"); listed && listed->IsArray()) {
        for (const Value& entry : std::get<Array>(listed->data)) {
            const auto plane_id = static_cast<core::Id>(Int(entry, "plane_id", "bundle.json planes"));
            if (!plane_entries.emplace(plane_id, entry).second) Corrupt("bundle.json: plane " + std::to_string(plane_id) + " is listed twice");
        }
    } else {
        Corrupt("bundle.json: planes is not a list");
    }
    const std::vector<ManifestBinding> bindings = ManifestPlaneBindings(manifest);
    if (bindings.size() != plane_entries.size()) {
        Corrupt("bundle.json lists " + std::to_string(plane_entries.size()) + " planes, the manifest binds " +
                std::to_string(bindings.size()));
    }

    ProjectLock lock = ProjectLock::Acquire(target);
    Container container = Container::Create(target);
    try {
        Container::WriteTransaction transaction(container);
        container.CreateSchema();
        container.SetMeta("project_uuid", uuid);
        container.SetMeta("created", UtcNow());
        // No operation row survives: every precondition below the imported revision is expired (§4).
        container.SetMeta("operation_horizon_revision", std::to_string(revision));
        container.SetMeta("portable", "1");
        WriteResources(container, project, pending, true);
        for (const ManifestBinding& binding : bindings) {
            const std::string where = "plane " + std::to_string(binding.plane_id);
            if (!binding.version) Corrupt("manifest.json: " + where + ": " + binding.error);
            const auto found = plane_entries.find(binding.plane_id);
            if (found == plane_entries.end()) Corrupt("bundle.json does not list " + where);
            const Value& entry = found->second;
            if (Int(entry, "version_id", where) != binding.version->version_id ||
                Text(entry, "chunk_root", where) != binding.version->chunk_root) {
                Corrupt("bundle.json: " + where + " does not match the manifest's binding");
            }
            PlaneRow row;
            row.plane_id = binding.plane_id;
            row.set_id = static_cast<core::Id>(Int(entry, "set_id", where));
            row.stack_id = static_cast<core::Id>(Int(entry, "stack_id", where));
            if (const Value* channel = Member(entry, "channel"); channel && channel->IsString()) {
                row.channel = core::FromString<core::ChannelType>(std::get<std::string>(channel->data));
                if (!row.channel) Corrupt(where + ": unknown channel " + std::get<std::string>(channel->data));
            }
            row.tile_u = static_cast<int>(Int(entry, "tile_u", where));
            row.tile_v = static_cast<int>(Int(entry, "tile_v", where));
            const std::string format_text = Text(entry, "format", where);
            const auto format = core::FromString<core::ChannelFormat>(format_text);
            if (!format) Corrupt(where + ": unknown format " + format_text);
            row.format = *format;
            row.width = static_cast<int>(Int(entry, "width", where));
            row.height = static_cast<int>(Int(entry, "height", where));
            row.created_revision = revision;
            const std::string file = Text(entry, "file", where);
            const std::string bytes = ReadFile(Inside(bundle, file));
            const PlaneImage image = codec::IsExrFormat(row.format) ? codec::DecodeExr(bytes, row.format) : codec::DecodePng(bytes, row.format);
            if (image.width != row.width || image.height != row.height) Corrupt(file + ": the image size does not match bundle.json");
            const VersionRef ref = InsertPlaneVersion(container, row, binding.version->version_id, revision, image);
            if (ref.chunk_root != binding.version->chunk_root) {
                Corrupt(file + ": the pixels hash to chunk_root " + ref.chunk_root + ", the manifest binds " + binding.version->chunk_root);
            }
        }
        WriteRevision(container, revision, std::nullopt, "checkpoint", project);
        Statement checkpoint(container,
                             "INSERT INTO checkpoint (name, revision, created_at, note, protected) VALUES ('current', ?, ?, NULL, 0)");
        checkpoint.Bind(1, revision).Bind(2, UtcNow()).Run();
        transaction.Commit();
    } catch (...) {
        { Container closing = std::move(container); }  // the connection closes before the file goes
        fs::remove(target, ec);
        throw;
    }
}

}  // namespace uzp::store
