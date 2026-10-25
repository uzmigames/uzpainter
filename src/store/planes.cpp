#include "store/planes.h"

#include <algorithm>
#include <charconv>
#include <set>
#include <utility>

#include "store/blobs.h"
#include "store/bundle_codec.h"
#include "store/integrity.h"
#include "store/filter_observations.h"
#include "store/snapshots.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

#if defined(UZP_STORE_FAULT_HOOKS)
#include "store/fault.h"
#endif

namespace uzp::store {

using core::Id;
using core::json::Array;
using core::json::Object;
using core::json::Value;

namespace {

std::optional<Id> OwnId(const Object& object) {
    for (const char* key : {"id", "uid"}) {
        const auto it = object.find(key);
        if (it != object.end() && it->second.IsInt() && std::get<std::int64_t>(it->second.data) > 0) {
            return static_cast<Id>(std::get<std::int64_t>(it->second.data));
        }
    }
    return std::nullopt;
}

std::optional<Id> PlaneIdOf(const Value& value) {
    if (!value.IsInt()) return std::nullopt;
    const std::int64_t id = std::get<std::int64_t>(value.data);
    if (id <= 0) return std::nullopt;
    return static_cast<Id>(id);
}

std::optional<Id> ParsePlaneKey(std::string_view key) {
    if (key.empty() || key.front() == '0') return std::nullopt;
    Id id = 0;
    const auto [end, ec] = std::from_chars(key.data(), key.data() + key.size(), id);
    if (ec != std::errc() || end != key.data() + key.size() || id > core::kMaxId) return std::nullopt;
    return id;
}

/// The binding value `{chunk_root, version_id}`, or the reason it is malformed.
std::optional<VersionRef> ParseVersionRef(const Value& value, std::string& error) {
    const Object* object = std::get_if<Object>(&value.data);
    if (object == nullptr) {
        error = "the binding is not an object";
        return std::nullopt;
    }
    const auto version = object->find("version_id");
    const auto root = object->find("chunk_root");
    if (version == object->end() || !version->second.IsInt() || std::get<std::int64_t>(version->second.data) <= 0) {
        error = "the binding has no positive integer version_id";
        return std::nullopt;
    }
    if (root == object->end() || !root->second.IsString() ||
        !core::IsSha256Hex(std::get<std::string>(root->second.data))) {
        error = "the binding has no SHA-256 chunk_root";
        return std::nullopt;
    }
    return VersionRef{std::get<std::int64_t>(version->second.data), std::get<std::string>(root->second.data)};
}

/// The planes and bindings of one paint object (`paint` member of a node).
struct PaintPlanes {
    std::optional<Id> owner;
    std::string path;  // of the paint object
    std::vector<Id> references;
    std::vector<ManifestBinding> bindings;
};

PaintPlanes ReadPaintPlanes(const Object& paint, const std::string& path, std::optional<Id> owner) {
    PaintPlanes out{owner, path, {}, {}};
    if (const auto planes = paint.find("planes"); planes != paint.end()) {
        if (const auto* map = std::get_if<Object>(&planes->second.data)) {
            for (const auto& [channel, id] : *map) {
                if (const auto plane = PlaneIdOf(id)) out.references.push_back(*plane);
            }
        }
    }
    if (const auto plane = paint.find("plane"); plane != paint.end()) {
        if (const auto id = PlaneIdOf(plane->second)) out.references.push_back(*id);
    }
    const auto versions = paint.find(kPlaneVersionsKey);
    if (versions == paint.end()) return out;
    const std::string base = path + "." + std::string(kPlaneVersionsKey);
    const auto* map = std::get_if<Object>(&versions->second.data);
    if (map == nullptr) {
        out.bindings.push_back(ManifestBinding{core::kNoId, std::nullopt, owner, base, "plane_versions is not an object"});
        return out;
    }
    for (const auto& [key, value] : *map) {
        ManifestBinding binding{core::kNoId, std::nullopt, owner, base + "." + key, {}};
        if (const auto id = ParsePlaneKey(key)) {
            binding.plane_id = *id;
            binding.version = ParseVersionRef(value, binding.error);
        } else {
            binding.error = "'" + key + "' is not a plane id";
        }
        out.bindings.push_back(std::move(binding));
    }
    return out;
}

void WalkPaint(const Value& value, const std::string& path, std::optional<Id> owner, std::vector<PaintPlanes>& out) {
    if (const auto* array = std::get_if<Array>(&value.data)) {
        for (std::size_t i = 0; i < array->size(); ++i) {
            WalkPaint((*array)[i], path + "[" + std::to_string(i) + "]", owner, out);
        }
    } else if (const auto* object = std::get_if<Object>(&value.data)) {
        const std::optional<Id> id = OwnId(*object);
        const std::optional<Id> here = id ? id : owner;
        for (const auto& [key, member] : *object) {
            const std::string child = path.empty() ? key : path + "." + key;
            if (key == "paint") {
                if (const auto* paint = std::get_if<Object>(&member.data)) out.push_back(ReadPaintPlanes(*paint, child, here));
            } else {
                WalkPaint(member, child, here, out);
            }
        }
    }
}

/// The paint objects of the manifest's nodes and the procedural snapshot entries (`snapshots.h`:
/// each entry holds one `plane` and its `plane_versions`, as a mask-stack paint object does), in
/// document order. The snapshot signatures and the top-level Filter source observations are not
/// walked for paint objects.
std::vector<PaintPlanes> ManifestPaintPlanes(const Value& manifest) {
    std::vector<PaintPlanes> out;
    const auto* top = std::get_if<Object>(&manifest.data);
    if (top == nullptr) return out;
    for (const auto& [key, member] : *top) {
        // The top-level Filter source observations hold a project projection, never live paint
        // objects (filter_observations.h); only that top-level key is skipped.
        if (key == kFilterObservationsKey) continue;
        if (key != kSnapshotsKey) {
            WalkPaint(member, key, std::nullopt, out);
            continue;
        }
        const auto* entries = std::get_if<Object>(&member.data);
        if (entries == nullptr) continue;  // reported by the snapshot checks (snapshots.h)
        for (const auto& [signature, entry] : *entries) {
            if (const auto* object = std::get_if<Object>(&entry.data)) {
                out.push_back(ReadPaintPlanes(*object, key + "." + signature, std::nullopt));
            }
        }
    }
    return out;
}

/// The binding of `plane_id` in `manifest`: the node and path that bind it.
struct Bound {
    VersionRef version;
    std::vector<AffectedNode> nodes;
};

std::optional<Bound> FindBinding(const Value& manifest, Id plane_id) {
    for (const ManifestBinding& binding : ManifestPlaneBindings(manifest)) {
        if (binding.plane_id == plane_id && binding.version) {
            return Bound{*binding.version, {AffectedNode{binding.owner, binding.path}}};
        }
    }
    return std::nullopt;
}

[[noreturn]] void Corrupt(Id plane_id, std::string detail, const std::vector<AffectedNode>& nodes) {
    throw CorruptionError(CorruptItem{"plane", std::to_string(plane_id), std::move(detail), nodes});
}

std::int64_t NextVersionId(Container& container, const PendingPlanes& pending) {
    Statement q(container, "SELECT COALESCE(MAX(version_id), 0) FROM plane_version");
    std::int64_t next = q.Step() ? q.Int(0) : 0;
    if (!pending.versions.empty()) next = std::max(next, pending.versions.rbegin()->first);
    return next + 1;
}

/// Where a node of the working copy sits, and its paint content.
struct PaintNode {
    core::PaintContent* paint = nullptr;
    Id node = core::kNoId;
    Id set = core::kNoId;
    Id stack = core::kNoId;
    bool mask = false;
};

/// The paint node `pick` selects in `project`, if any.
template <typename Pick>
std::optional<PaintNode> FindPaintNode(core::Project& project, Pick&& pick) {
    std::optional<PaintNode> found;
    core::ForEachNode(project, [&](const core::NodeVisit& visit) {
        if (found) return;
        const core::PaintContent* paint = visit.layer ? (visit.layer->paint ? &*visit.layer->paint : nullptr)
                                                      : (visit.effect->paint ? &*visit.effect->paint : nullptr);
        const Id uid = visit.layer ? visit.layer->uid : visit.effect->uid;
        if (!pick(uid, paint)) return;
        found = PaintNode{nullptr, uid, visit.texture_set, visit.stack,
                          visit.effect != nullptr && visit.owner_stack == core::NodeStack::Mask};
    });
    if (!found) return std::nullopt;
    if (core::Layer* layer = core::FindLayer(project, found->node)) {
        found->paint = layer->paint ? &*layer->paint : nullptr;
    } else if (core::Effect* effect = core::FindEffect(project, found->node)) {
        found->paint = effect->paint ? &*effect->paint : nullptr;
    }
    return found;
}

bool References(const core::PaintContent& paint, Id plane_id) {
    if (paint.mono_plane == plane_id) return true;
    return std::any_of(paint.planes.begin(), paint.planes.end(), [&](const auto& entry) { return entry.second == plane_id; });
}

void SetBinding(core::PaintContent& paint, Id plane_id, const VersionRef& ref) {
    Value& versions = paint.extra[std::string(kPlaneVersionsKey)];
    if (!versions.IsObject()) versions = Object{};
    std::get<Object>(versions.data)[std::to_string(plane_id)] = ref.ToJson();
}

std::optional<VersionRef> BindingOf(const core::PaintContent& paint, Id plane_id) {
    const auto versions = paint.extra.find(kPlaneVersionsKey);
    if (versions == paint.extra.end() || !versions->second.IsObject()) return std::nullopt;
    const Object& map = std::get<Object>(versions->second.data);
    const auto entry = map.find(std::to_string(plane_id));
    if (entry == map.end()) return std::nullopt;
    std::string error;
    return ParseVersionRef(entry->second, error);
}

std::string ChunkBytesOf(const PlaneRow& row, const std::string& texels, int x, int y) {
    const std::size_t bpt = TexelBytes(row.format);
    const int w = row.chunk_width(x);
    const int h = row.chunk_height(y);
    std::string chunk(static_cast<std::size_t>(w) * static_cast<std::size_t>(h) * bpt, '\0');
    const std::size_t stride = static_cast<std::size_t>(row.width) * bpt;
    const std::size_t line = static_cast<std::size_t>(w) * bpt;
    for (int r = 0; r < h; ++r) {
        const std::size_t src = (static_cast<std::size_t>(y) * row.chunk_size + r) * stride +
                                static_cast<std::size_t>(x) * row.chunk_size * bpt;
        std::copy_n(texels.data() + src, line, chunk.data() + static_cast<std::size_t>(r) * line);
    }
    return chunk;
}

void PutChunk(const PlaneRow& row, std::string& texels, int x, int y, std::string_view chunk) {
    const std::size_t bpt = TexelBytes(row.format);
    const std::size_t stride = static_cast<std::size_t>(row.width) * bpt;
    const std::size_t line = static_cast<std::size_t>(row.chunk_width(x)) * bpt;
    for (int r = 0; r < row.chunk_height(y); ++r) {
        const std::size_t dst = (static_cast<std::size_t>(y) * row.chunk_size + r) * stride +
                                static_cast<std::size_t>(x) * row.chunk_size * bpt;
        std::copy_n(chunk.data() + static_cast<std::size_t>(r) * line, line, texels.data() + dst);
    }
}

std::size_t ChunkByteCount(const PlaneRow& row, int x, int y) {
    return static_cast<std::size_t>(row.chunk_width(x)) * static_cast<std::size_t>(row.chunk_height(y)) *
           TexelBytes(row.format);
}

bool AllZero(std::string_view bytes) {
    return std::all_of(bytes.begin(), bytes.end(), [](char c) { return c == '\0'; });
}

/// The version of `row` holding `image` (checked against the row): every non-empty chunk listed,
/// bytes kept only for chunks the store does not hold.
StagedVersion BuildVersion(Container& container, const PlaneRow& row, const PlaneImage& image) {
    const Id plane_id = row.plane_id;
    if (image.width != row.width || image.height != row.height || image.format != row.format) {
        throw core::ValueError("plane: plane " + std::to_string(plane_id) + " is " + std::to_string(row.width) + "x" +
                               std::to_string(row.height) + " " + std::string(core::ToString(row.format)) +
                               ", the image " + std::to_string(image.width) + "x" + std::to_string(image.height) + " " +
                               std::string(core::ToString(image.format)));
    }
    if (image.texels.size() != static_cast<std::size_t>(image.width) * static_cast<std::size_t>(image.height) *
                                   TexelBytes(image.format)) {
        throw core::ValueError("plane: the image holds " + std::to_string(image.texels.size()) + " bytes, not width x height texels");
    }
    StagedVersion version{plane_id, {}, {}, {}};
    for (int x = 0; x < row.chunks_x(); ++x) {
        for (int y = 0; y < row.chunks_y(); ++y) {
            std::string chunk = ChunkBytesOf(row, image.texels, x, y);
            if (AllZero(chunk)) continue;  // an empty chunk has no row
            std::string sha256 = core::Sha256Hex(chunk);
            if (version.bytes.count(sha256) == 0 && !HasBlob(container, sha256)) version.bytes.emplace(sha256, std::move(chunk));
            version.chunks.push_back(ChunkRow{x, y, std::move(sha256)});
        }
    }
    version.chunk_root = ChunkRoot(version.chunks);
    return version;
}

/// A stored version after its rows were checked against the binding.
struct LoadedVersion {
    PlaneRow row;
    std::vector<ChunkRow> chunks;
};

LoadedVersion LoadVersion(Container& container, Id plane_id, const Bound& bound) {
    const std::int64_t vid = bound.version.version_id;
    const std::optional<PlaneRow> row = ReadPlaneRow(container, plane_id);
    if (!row) Corrupt(plane_id, "the bound plane has no plane row", bound.nodes);
    Statement q(container, "SELECT plane_id, chunk_root FROM plane_version WHERE version_id = ?");
    q.Bind(1, vid);
    if (!q.Step()) Corrupt(plane_id, "the binding names plane_version " + std::to_string(vid) + ", which is not stored", bound.nodes);
    if (q.IsNull(0) || static_cast<Id>(q.Int(0)) != plane_id) {
        Corrupt(plane_id, "the binding names plane_version " + std::to_string(vid) + " of plane " + q.Text(0), bound.nodes);
    }
    if (q.Text(1) != bound.version.chunk_root) {
        Corrupt(plane_id, "chunk_root mismatch: the binding names " + bound.version.chunk_root + ", plane_version " +
                              std::to_string(vid) + " holds " + q.Text(1), bound.nodes);
    }
    LoadedVersion loaded{*row, ReadChunkRows(container, vid)};
    const std::string root = ChunkRoot(loaded.chunks);
    if (root != bound.version.chunk_root) {
        Corrupt(plane_id, "chunk_root mismatch: the chunk rows of plane_version " + std::to_string(vid) + " hash to " +
                              root + ", not to its chunk_root " + bound.version.chunk_root, bound.nodes);
    }
    for (const ChunkRow& chunk : loaded.chunks) {
        if (chunk.x < 0 || chunk.y < 0 || chunk.x >= row->chunks_x() || chunk.y >= row->chunks_y()) {
            Corrupt(plane_id, "plane_version " + std::to_string(vid) + " lists chunk (" + std::to_string(chunk.x) + "," +
                                  std::to_string(chunk.y) + ") outside the plane", bound.nodes);
        }
    }
    return loaded;
}

std::string LoadChunk(Container& container, Id plane_id, const LoadedVersion& version, const ChunkRow& chunk,
                      const Bound& bound) {
    try {
        return ReadChunkBlob(container, chunk.sha256, ChunkByteCount(version.row, chunk.x, chunk.y));
    } catch (const StoreError& error) {
        Corrupt(plane_id, "plane_version " + std::to_string(bound.version.version_id) + " chunk (" +
                              std::to_string(chunk.x) + "," + std::to_string(chunk.y) + "): " + error.what(), bound.nodes);
    }
}

PlaneImage AssembleStored(Container& container, Id plane_id, const Bound& bound) {
    const LoadedVersion version = LoadVersion(container, plane_id, bound);
    PlaneImage image{version.row.width, version.row.height, version.row.format, {}};
    image.texels.assign(static_cast<std::size_t>(image.width) * static_cast<std::size_t>(image.height) *
                            TexelBytes(image.format), '\0');
    for (const ChunkRow& chunk : version.chunks) {
        PutChunk(version.row, image.texels, chunk.x, chunk.y, LoadChunk(container, plane_id, version, chunk, bound));
    }
    return image;
}

Bound BindingAt(Container& container, std::int64_t revision, Id plane_id) {
    const Value manifest = core::json::Parse(ReadManifestText(container, revision));
    std::optional<Bound> bound = FindBinding(manifest, plane_id);
    if (!bound) {
        throw StoreError(StoreError::Code::missing_resource,
                         "revision " + std::to_string(revision) + " binds no plane " + std::to_string(plane_id));
    }
    return std::move(*bound);
}

}  // namespace

std::size_t TexelBytes(core::ChannelFormat format) {
    switch (format) {
        case core::ChannelFormat::L8: return 1;
        case core::ChannelFormat::L16:
        case core::ChannelFormat::L16F: return 2;
        case core::ChannelFormat::sRGB8:
        case core::ChannelFormat::RGB8: return 3;
        case core::ChannelFormat::L32F: return 4;
        case core::ChannelFormat::RGB16:
        case core::ChannelFormat::RGB16F: return 6;
        case core::ChannelFormat::RGB32F: return 12;
    }
    throw core::ValueError("plane: unknown channel format");
}

int PlaneRow::chunk_width(int x) const { return std::min(chunk_size, width - x * chunk_size); }
int PlaneRow::chunk_height(int y) const { return std::min(chunk_size, height - y * chunk_size); }

std::string ChunkRoot(std::vector<ChunkRow> rows) {
    std::sort(rows.begin(), rows.end(), [](const ChunkRow& a, const ChunkRow& b) {
        return a.x != b.x ? a.x < b.x : a.y < b.y;
    });
    Array list;
    list.reserve(rows.size());
    for (const ChunkRow& row : rows) list.push_back(Array{row.x, row.y, row.sha256});
    return core::Sha256Hex(core::json::WriteCanonical(list));
}

std::optional<VersionRef> ParseBinding(const Value& value, std::string& error) { return ParseVersionRef(value, error); }

Value VersionRef::ToJson() const { return Object{{"chunk_root", chunk_root}, {"version_id", version_id}}; }

std::vector<ManifestBinding> ManifestPlaneBindings(const Value& manifest) {
    std::vector<ManifestBinding> out;
    for (PaintPlanes& paint : ManifestPaintPlanes(manifest)) {
        for (ManifestBinding& binding : paint.bindings) out.push_back(std::move(binding));
    }
    return out;
}

std::vector<PlaneReference> ManifestPlaneReferences(const Value& manifest) {
    std::vector<PlaneReference> out;
    for (const PaintPlanes& paint : ManifestPaintPlanes(manifest)) {
        for (const Id plane : paint.references) {
            const bool bound = std::any_of(paint.bindings.begin(), paint.bindings.end(),
                                           [&](const ManifestBinding& b) { return b.plane_id == plane && b.version; });
            out.push_back(PlaneReference{plane, paint.owner, paint.path, bound});
        }
    }
    return out;
}

std::string ReadChunkBlob(Container& container, std::string_view sha256, std::size_t expected_size) {
    Statement q(container, "SELECT size, data FROM blob WHERE sha256 = ?");
    q.Bind(1, sha256);
    if (!q.Step()) throw StoreError(StoreError::Code::corrupt, "blob " + std::string(sha256) + " is not stored");
    if (q.IsNull(0) || q.Int(0) != static_cast<std::int64_t>(expected_size)) {
        throw StoreError(StoreError::Code::corrupt, "blob " + std::string(sha256) + " holds " + q.Text(0) +
                                                        " bytes, the chunk has " + std::to_string(expected_size));
    }
    std::string bytes;
    try {
        bytes = Decompress(q.Blob(1), expected_size);
    } catch (const StoreError& error) {
        throw StoreError(StoreError::Code::corrupt, "blob " + std::string(sha256) + ": unreadable payload: " + error.what());
    }
    const std::string actual = core::Sha256Hex(bytes);
    if (actual != sha256) {
        throw StoreError(StoreError::Code::corrupt,
                         "SHA-256 mismatch: blob " + std::string(sha256) + " holds bytes that hash to " + actual);
    }
    return bytes;
}

std::optional<PlaneRow> ReadPlaneRow(Container& container, Id plane_id) {
    Statement q(container,
                "SELECT set_id, stack_id, channel, tile_u, tile_v, format, width, height, chunk_size, created_revision "
                "FROM plane WHERE plane_id = ?");
    q.Bind(1, static_cast<std::int64_t>(plane_id));
    if (!q.Step()) return std::nullopt;
    PlaneRow row;
    row.plane_id = plane_id;
    row.set_id = static_cast<Id>(q.Int(0));
    row.stack_id = static_cast<Id>(q.Int(1));
    if (!q.IsNull(2)) {
        row.channel = core::FromString<core::ChannelType>(q.Text(2));
        if (!row.channel) throw StoreError(StoreError::Code::corrupt, "plane " + std::to_string(plane_id) + ": unknown channel " + q.Text(2));
    }
    row.tile_u = static_cast<int>(q.Int(3));
    row.tile_v = static_cast<int>(q.Int(4));
    const auto format = core::FromString<core::ChannelFormat>(q.Text(5));
    if (!format) throw StoreError(StoreError::Code::corrupt, "plane " + std::to_string(plane_id) + ": unknown format " + q.Text(5));
    row.format = *format;
    row.width = static_cast<int>(q.Int(6));
    row.height = static_cast<int>(q.Int(7));
    row.chunk_size = static_cast<int>(q.Int(8));
    row.created_revision = q.Int(9);
    if (row.width < 1 || row.height < 1 || row.width > kMaxPlaneEdge || row.height > kMaxPlaneEdge || row.chunk_size < 1) {
        throw StoreError(StoreError::Code::corrupt, "plane " + std::to_string(plane_id) + ": invalid size");
    }
    return row;
}

std::vector<ChunkRow> ReadChunkRows(Container& container, std::int64_t version_id) {
    Statement q(container,
                "SELECT chunk_x, chunk_y, sha256 FROM plane_chunk WHERE version_id = ? ORDER BY chunk_x, chunk_y");
    q.Bind(1, version_id);
    std::vector<ChunkRow> rows;
    while (q.Step()) rows.push_back(ChunkRow{static_cast<int>(q.Int(0)), static_cast<int>(q.Int(1)), q.Text(2)});
    return rows;
}

Id StageNewPlane(Container& container, PendingPlanes& pending, core::Edit& edit, const PlaneSpec& spec) {
    if (spec.width < 1 || spec.height < 1 || spec.width > kMaxPlaneEdge || spec.height > kMaxPlaneEdge) {
        throw core::ValueError("plane: size " + std::to_string(spec.width) + "x" + std::to_string(spec.height) +
                               " is outside 1.." + std::to_string(kMaxPlaneEdge));
    }
    core::Project& project = edit.project();
    std::optional<PaintNode> node = FindPaintNode(project, [&](Id uid, const core::PaintContent*) { return uid == spec.node; });
    if (!node || node->paint == nullptr) {
        throw core::ValueError("plane: node " + std::to_string(spec.node) + " is not a paint layer or paint effect");
    }
    if (node->mask) {
        if (spec.channel) throw core::ValueError("plane: a mask-stack paint effect holds one plane, without a channel");
        if (node->paint->mono_plane) throw core::ValueError("plane: node " + std::to_string(spec.node) + " already holds plane " + std::to_string(*node->paint->mono_plane));
    } else {
        if (!spec.channel) throw core::ValueError("plane: a content paint node holds one plane per channel; name the channel");
        if (const auto it = node->paint->planes.find(*spec.channel); it != node->paint->planes.end()) {
            throw core::ValueError("plane: node " + std::to_string(spec.node) + " already holds plane " +
                                   std::to_string(it->second) + " on " + std::string(core::ToString(*spec.channel)));
        }
    }
    const auto set = std::find_if(project.texture_sets.begin(), project.texture_sets.end(),
                                  [&](const core::TextureSet& s) { return s.id == node->set; });
    if (spec.udim < 1001 || set == project.texture_sets.end() ||
        std::none_of(set->uv_tiles.begin(), set->uv_tiles.end(), [&](const core::UVTile& t) { return t.udim == spec.udim; })) {
        throw core::ValueError("plane: the texture set of node " + std::to_string(spec.node) + " has no UV tile " +
                               std::to_string(spec.udim));
    }

    const Id plane_id = edit.AllocateId();
    if (pending.planes.count(plane_id) != 0 || ReadPlaneRow(container, plane_id)) {
        throw StoreError(StoreError::Code::conflict, "plane id " + std::to_string(plane_id) +
                                                         " is already a stored plane (the project counter went back)");
    }
    PlaneRow row;
    row.plane_id = plane_id;
    row.set_id = node->set;
    row.stack_id = node->stack;
    row.channel = spec.channel;
    row.tile_u = (spec.udim - 1001) % 10;
    row.tile_v = (spec.udim - 1001) / 10;
    row.format = spec.format;
    row.width = spec.width;
    row.height = spec.height;
    pending.planes[plane_id] = row;

    if (spec.channel) {
        node->paint->planes[*spec.channel] = plane_id;
    } else {
        node->paint->mono_plane = plane_id;
    }
    const std::int64_t vid = NextVersionId(container, pending);
    pending.versions[vid] = StagedVersion{plane_id, {}, {}, ChunkRoot({})};
    SetBinding(*node->paint, plane_id, VersionRef{vid, pending.versions[vid].chunk_root});
    return plane_id;
}

VersionRef StagePlaneContent(Container& container, PendingPlanes& pending, core::Edit& edit, Id plane_id,
                             const PlaneImage& image) {
    std::optional<PaintNode> node = FindPaintNode(edit.project(), [&](Id, const core::PaintContent* paint) {
        return paint != nullptr && References(*paint, plane_id);
    });
    if (!node || node->paint == nullptr) throw core::ValueError("plane: no node holds plane " + std::to_string(plane_id));
    const std::optional<VersionRef> current = BindingOf(*node->paint, plane_id);
    if (!current) {
        throw core::ValueError("plane: node " + std::to_string(node->node) + " holds plane " + std::to_string(plane_id) +
                               " without a content binding");
    }
    std::optional<PlaneRow> row;
    if (const auto staged = pending.planes.find(plane_id); staged != pending.planes.end()) {
        row = staged->second;
    } else {
        row = ReadPlaneRow(container, plane_id);
    }
    if (!row) throw StoreError(StoreError::Code::conflict, "plane " + std::to_string(plane_id) + " has no plane row");
    StagedVersion version = BuildVersion(container, *row, image);
    if (version.chunk_root == current->chunk_root) return *current;  // same content: nothing changes

    const auto own = pending.versions.find(current->version_id);
    const std::int64_t vid = own != pending.versions.end() && own->second.plane_id == plane_id
                                 ? current->version_id  // this transaction's own version: replaced
                                 : NextVersionId(container, pending);
    const VersionRef ref{vid, version.chunk_root};
    pending.versions[vid] = std::move(version);
    SetBinding(*node->paint, plane_id, ref);
    return ref;
}

std::vector<Id> StageBitmap(Container& container, PendingPlanes& pending, core::Edit& edit, Id node_id,
                            const std::vector<core::ChannelType>& channels, std::string_view bitmap) {
    core::Project& project = edit.project();
    const std::optional<PaintNode> node =
        FindPaintNode(project, [&](Id uid, const core::PaintContent*) { return uid == node_id; });
    if (!node || node->paint == nullptr) {
        throw core::ValueError("bitmap: node " + std::to_string(node_id) + " is not a paint layer or paint effect");
    }
    if (node->mask) {
        throw core::NotYetSupported("bitmap: node " + std::to_string(node_id) +
                                    " is a mask-stack paint effect, whose plane format is not recorded "
                                    "(phase4.1_nodes-paint-layers item 2.5)");
    }
    if (channels.empty()) throw core::ValueError("bitmap: name at least one channel of the paint node");
    if (project.settings.workflow != core::ProjectWorkflow::Default) {
        throw core::NotYetSupported("bitmap: a paint plane outside the Default workflow (phase4.5_uv-tiles)");
    }
    const core::TextureSet* set = nullptr;
    for (const core::TextureSet& candidate : project.texture_sets) {
        if (candidate.id == node->set) set = &candidate;
    }
    const core::Stack* stack = core::FindStack(project, node->set, node->stack);
    if (set == nullptr || stack == nullptr) {
        throw core::ValueError("bitmap: node " + std::to_string(node_id) + " is in no stack");
    }
    // Every channel is checked and the bitmap decoded for it before anything is staged.
    std::map<core::ChannelType, PlaneImage> images;
    for (const core::ChannelType channel : channels) {
        const auto found = stack->channels.find(channel);
        if (found == stack->channels.end()) {
            throw core::ValueError("bitmap: the stack of node " + std::to_string(node_id) + " has no channel " +
                                   std::string(core::ToString(channel)));
        }
        const core::ChannelFormat format = found->second.format;
        PlaneImage image;
        try {
            image = codec::IsExrFormat(format) ? codec::DecodeExr(bitmap, format) : codec::DecodePng(bitmap, format);
        } catch (const StoreError& error) {
            throw core::NotYetSupported("bitmap: the bitmap does not hold " + std::string(core::ToString(format)) +
                                        " texels as they are (" + error.what() +
                                        "); converting a bitmap into the format of a plane is not recorded "
                                        "(phase4.1_nodes-paint-layers item 2.5)");
        }
        if (image.width != set->resolution.width || image.height != set->resolution.height) {
            throw core::NotYetSupported("bitmap: a " + std::to_string(image.width) + "x" + std::to_string(image.height) +
                                        " bitmap into a " + std::to_string(set->resolution.width) + "x" +
                                        std::to_string(set->resolution.height) +
                                        " plane; resampling into a plane is not recorded "
                                        "(phase4.1_nodes-paint-layers item 2.5)");
        }
        images[channel] = std::move(image);
    }
    std::vector<Id> planes;
    for (auto& [channel, image] : images) {
        Id plane_id = core::kNoId;
        if (const auto held = node->paint->planes.find(channel); held != node->paint->planes.end()) {
            plane_id = held->second;
        } else {
            plane_id = StageNewPlane(container, pending, edit,
                                     PlaneSpec{node_id, channel, 1001, image.format, image.width, image.height});
        }
        StagePlaneContent(container, pending, edit, plane_id, image);
        planes.push_back(plane_id);
    }
    return planes;
}

VersionRef StageVersion(Container& container, PendingPlanes& pending, const PlaneRow& row, const PlaneImage& image) {
    StagedVersion version = BuildVersion(container, row, image);
    const std::int64_t vid = NextVersionId(container, pending);
    const VersionRef ref{vid, version.chunk_root};
    pending.versions[vid] = std::move(version);
    return ref;
}

void WritePlaneRows(Container& container, const PendingPlanes& pending, const core::Snapshot& snapshot) {
    const Value manifest = core::ProjectToJson(*snapshot.project);
    std::vector<std::pair<Id, VersionRef>> staged;
    std::map<Id, std::string> holders;  // plane -> the object that holds it
    for (const PaintPlanes& paint : ManifestPaintPlanes(manifest)) {
        const std::string where = paint.owner ? "node " + std::to_string(*paint.owner) : paint.path;
        for (const Id plane : paint.references) {
            const auto [held, inserted] = holders.emplace(plane, where);
            if (!inserted) {
                throw StoreError(StoreError::Code::conflict, where + " holds plane " + std::to_string(plane) +
                                                                 ", which " + held->second + " already holds");
            }
        }
        std::set<Id> bound;
        for (const ManifestBinding& binding : paint.bindings) {
            if (!binding.version) {
                throw StoreError(StoreError::Code::conflict, where + ": " + binding.path + ": " + binding.error);
            }
            if (std::find(paint.references.begin(), paint.references.end(), binding.plane_id) == paint.references.end()) {
                throw StoreError(StoreError::Code::conflict, where + " binds plane " + std::to_string(binding.plane_id) +
                                                                 ", which it does not hold");
            }
            bound.insert(binding.plane_id);
            const VersionRef& ref = *binding.version;
            if (const auto it = pending.versions.find(ref.version_id); it != pending.versions.end()) {
                if (it->second.plane_id != binding.plane_id || it->second.chunk_root != ref.chunk_root) {
                    throw StoreError(StoreError::Code::conflict,
                                     where + ": the binding of plane " + std::to_string(binding.plane_id) +
                                         " does not match staged version " + std::to_string(ref.version_id));
                }
                staged.emplace_back(binding.plane_id, ref);
                continue;
            }
            Statement q(container, "SELECT plane_id, chunk_root FROM plane_version WHERE version_id = ?");
            q.Bind(1, ref.version_id);
            if (!q.Step() || static_cast<Id>(q.Int(0)) != binding.plane_id || q.Text(1) != ref.chunk_root) {
                throw StoreError(StoreError::Code::conflict,
                                 where + ": plane " + std::to_string(binding.plane_id) + " is bound to version " +
                                     std::to_string(ref.version_id) + ", which is not a stored version of it with chunk_root " +
                                     ref.chunk_root);
            }
        }
        for (const Id plane : paint.references) {
            if (bound.count(plane) == 0) {
                throw StoreError(StoreError::Code::conflict,
                                 where + " holds plane " + std::to_string(plane) + " without a content binding");
            }
        }
    }

    for (const auto& [plane_id, ref] : staged) {
        if (const auto created = pending.planes.find(plane_id); created != pending.planes.end() && !ReadPlaneRow(container, plane_id)) {
            const PlaneRow& row = created->second;
            Statement q(container,
                        "INSERT INTO plane (plane_id, set_id, stack_id, channel, tile_u, tile_v, format, width, height, "
                        "chunk_size, created_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)");
            q.Bind(1, static_cast<std::int64_t>(plane_id))
                .Bind(2, static_cast<std::int64_t>(row.set_id))
                .Bind(3, static_cast<std::int64_t>(row.stack_id));
            if (row.channel) {
                q.Bind(4, core::ToString(*row.channel));
            } else {
                q.BindNull(4);
            }
            q.Bind(5, std::int64_t{row.tile_u})
                .Bind(6, std::int64_t{row.tile_v})
                .Bind(7, core::ToString(row.format))
                .Bind(8, std::int64_t{row.width})
                .Bind(9, std::int64_t{row.height})
                .Bind(10, std::int64_t{row.chunk_size})
                .Bind(11, snapshot.revision)
                .Run();
        } else if (!ReadPlaneRow(container, plane_id)) {
            throw StoreError(StoreError::Code::conflict, "plane " + std::to_string(plane_id) + " has no plane row");
        }
        const StagedVersion& version = pending.versions.at(ref.version_id);
        for (const auto& [sha256, bytes] : version.bytes) {
            if (PutBlob(container, bytes, kChunkMime) != sha256) {
                throw StoreError(StoreError::Code::conflict, "staged chunk bytes do not hash to " + sha256);
            }
        }
        Statement insert_version(container,
                                 "INSERT INTO plane_version (version_id, plane_id, created_revision, chunk_root) VALUES (?, ?, ?, ?)");
        insert_version.Bind(1, ref.version_id)
            .Bind(2, static_cast<std::int64_t>(plane_id))
            .Bind(3, snapshot.revision)
            .Bind(4, version.chunk_root)
            .Run();
        Statement insert_chunk(container, "INSERT INTO plane_chunk (version_id, chunk_x, chunk_y, sha256) VALUES (?, ?, ?, ?)");
        for (const ChunkRow& chunk : version.chunks) {
            if (!HasBlob(container, chunk.sha256)) {
                throw StoreError(StoreError::Code::conflict, "plane " + std::to_string(plane_id) + ": chunk blob " +
                                                                 chunk.sha256 + " is neither stored nor staged");
            }
            insert_chunk.Reset();
            insert_chunk.Bind(1, ref.version_id).Bind(2, std::int64_t{chunk.x}).Bind(3, std::int64_t{chunk.y}).Bind(4, chunk.sha256).Run();
        }
    }
#if defined(UZP_STORE_FAULT_HOOKS)
    fault::AfterPlaneRows();
#endif
}

VersionRef InsertPlaneVersion(Container& container, const PlaneRow& row, std::int64_t version_id,
                              std::int64_t created_revision, const PlaneImage& image) {
    if (image.width != row.width || image.height != row.height || image.format != row.format ||
        image.texels.size() != static_cast<std::size_t>(image.width) * static_cast<std::size_t>(image.height) *
                                   TexelBytes(image.format)) {
        throw core::ValueError("plane " + std::to_string(row.plane_id) + ": the image does not match the plane row");
    }
    if (!ReadPlaneRow(container, row.plane_id)) {
        Statement q(container,
                    "INSERT INTO plane (plane_id, set_id, stack_id, channel, tile_u, tile_v, format, width, height, "
                    "chunk_size, created_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)");
        q.Bind(1, static_cast<std::int64_t>(row.plane_id))
            .Bind(2, static_cast<std::int64_t>(row.set_id))
            .Bind(3, static_cast<std::int64_t>(row.stack_id));
        if (row.channel) {
            q.Bind(4, core::ToString(*row.channel));
        } else {
            q.BindNull(4);
        }
        q.Bind(5, std::int64_t{row.tile_u})
            .Bind(6, std::int64_t{row.tile_v})
            .Bind(7, core::ToString(row.format))
            .Bind(8, std::int64_t{row.width})
            .Bind(9, std::int64_t{row.height})
            .Bind(10, std::int64_t{row.chunk_size})
            .Bind(11, created_revision)
            .Run();
    }
    std::vector<ChunkRow> chunks;
    for (int x = 0; x < row.chunks_x(); ++x) {
        for (int y = 0; y < row.chunks_y(); ++y) {
            const std::string chunk = ChunkBytesOf(row, image.texels, x, y);
            if (AllZero(chunk)) continue;  // an empty chunk has no row
            chunks.push_back(ChunkRow{x, y, PutBlob(container, chunk, kChunkMime)});
        }
    }
    const VersionRef ref{version_id, ChunkRoot(chunks)};
    Statement version(container,
                      "INSERT INTO plane_version (version_id, plane_id, created_revision, chunk_root) VALUES (?, ?, ?, ?)");
    version.Bind(1, version_id)
        .Bind(2, static_cast<std::int64_t>(row.plane_id))
        .Bind(3, created_revision)
        .Bind(4, ref.chunk_root)
        .Run();
    Statement insert_chunk(container, "INSERT INTO plane_chunk (version_id, chunk_x, chunk_y, sha256) VALUES (?, ?, ?, ?)");
    for (const ChunkRow& chunk : chunks) {
        insert_chunk.Reset();
        insert_chunk.Bind(1, version_id).Bind(2, std::int64_t{chunk.x}).Bind(3, std::int64_t{chunk.y}).Bind(4, chunk.sha256).Run();
    }
    return ref;
}

PlaneImage ReadPlaneIn(Container& container, const PendingPlanes& pending, const core::Project& project, Id plane_id) {
    const std::optional<Bound> bound = FindBinding(core::ProjectToJson(project), plane_id);
    if (!bound) throw StoreError(StoreError::Code::missing_resource, "the project binds no plane " + std::to_string(plane_id));
    const auto staged = pending.versions.find(bound->version.version_id);
    if (staged == pending.versions.end() || staged->second.plane_id != plane_id) {
        return AssembleStored(container, plane_id, *bound);
    }
    std::optional<PlaneRow> row;
    if (const auto created = pending.planes.find(plane_id); created != pending.planes.end()) {
        row = created->second;
    } else {
        row = ReadPlaneRow(container, plane_id);
    }
    if (!row) Corrupt(plane_id, "the bound plane has no plane row", bound->nodes);
    PlaneImage image{row->width, row->height, row->format, {}};
    image.texels.assign(static_cast<std::size_t>(row->width) * static_cast<std::size_t>(row->height) * TexelBytes(row->format), '\0');
    for (const ChunkRow& chunk : staged->second.chunks) {
        const auto bytes = staged->second.bytes.find(chunk.sha256);
        PutChunk(*row, image.texels, chunk.x, chunk.y,
                 bytes != staged->second.bytes.end()
                     ? bytes->second
                     : LoadChunk(container, plane_id, LoadedVersion{*row, staged->second.chunks}, chunk, *bound));
    }
    return image;
}

PlaneImage ReadPlaneAt(Container& container, std::int64_t revision, Id plane_id) {
    return AssembleStored(container, plane_id, BindingAt(container, revision, plane_id));
}

std::string ReadPlaneChunkAt(Container& container, std::int64_t revision, Id plane_id, int x, int y) {
    const Bound bound = BindingAt(container, revision, plane_id);
    const LoadedVersion version = LoadVersion(container, plane_id, bound);
    if (x < 0 || y < 0 || x >= version.row.chunks_x() || y >= version.row.chunks_y()) {
        throw core::ValueError("plane: chunk (" + std::to_string(x) + "," + std::to_string(y) + ") is outside plane " +
                               std::to_string(plane_id));
    }
    for (const ChunkRow& chunk : version.chunks) {
        if (chunk.x == x && chunk.y == y) return LoadChunk(container, plane_id, version, chunk, bound);
    }
    return std::string(ChunkByteCount(version.row, x, y), '\0');  // no row: the empty value
}

}  // namespace uzp::store
