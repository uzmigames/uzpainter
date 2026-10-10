#pragma once

// Authoritative raster planes (`docs/architecture/09-project-file-format.md` §1, §4;
// `04-layer-stack-and-compositing.md` §1, §2).
//
// A paint layer or paint effect holds one plane per channel (`paint.planes{channel → plane_id}`,
// or `paint.plane` in a mask stack). Each plane is one `plane` row with a persistent `plane_id`
// (an id of the project counter), its texture set, stack, channel, UV tile, native format, size
// and chunk size; nothing is unique across planes, so any number of planes share one
// set/stack/channel/tile and none aliases or is flattened into another.
//
// The pixels of a plane are immutable versions (`plane_version`). A version lists its non-empty
// 1024×1024 chunks (`plane_chunk (version_id, chunk_x, chunk_y, sha256)`; chunk coordinates
// index the evaluator's tiles inside the plane, not UV tiles); each chunk's texels are one
// content-addressed zstd blob in `blob`, and a chunk without a row reads as the empty value (every
// byte 0). `chunk_root` is the SHA-256 of the canonical JSON of the version's
// `[[chunk_x, chunk_y, sha256], ...]` list sorted by `(chunk_x, chunk_y)`. An edit creates a new
// version: blobs only for chunks whose bytes the store does not hold, hash rows for every chunk.
//
// The manifest binds each plane to a version: the paint object of the owning node carries
// `plane_versions {"<plane_id>": {"chunk_root": <hex>, "version_id": <n>}}` beside `planes` /
// `plane` (a manifest key the document model keeps verbatim). The binding travels with the
// manifest, so its digest covers the pixels, a revert that copies a manifest copies its bindings,
// and deleting a node drops its bindings. Reads resolve the binding of the requested revision's
// manifest; the plane rows are written by the mutation commit (`WritePlaneRows`, run inside the
// commit transaction before the revision row).

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "store/container.h"
#include "uzp_core/document/document.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/ids.h"

namespace uzp::store {

/// Edge of a chunk in texels (the evaluator's tile, `04-…` §2).
inline constexpr int kChunkSize = 1024;
/// Largest plane edge accepted (the largest texture-set resolution, 8192, is far below it).
inline constexpr int kMaxPlaneEdge = 65536;
/// The manifest key of the bindings inside a paint object.
inline constexpr std::string_view kPlaneVersionsKey = "plane_versions";
/// `blob.mime` of a chunk.
inline constexpr std::string_view kChunkMime = "application/vnd.uzpainter.plane-chunk";

/// Bytes per texel of a plane stored in `format`: 1 (L8), 2 (L16, L16F), 3 (sRGB8, RGB8),
/// 4 (L32F), 6 (RGB16, RGB16F) or 12 (RGB32F). Texels are stored as the format's native
/// little-endian components, unmodified.
std::size_t TexelBytes(core::ChannelFormat format);

/// What a new plane is: its owner (a paint layer or paint effect of the working copy), the channel
/// (absent for the one plane of a mask-stack paint effect), the UV tile, native format and size.
struct PlaneSpec {
    core::Id node = core::kNoId;
    std::optional<core::ChannelType> channel;
    int udim = 1001;
    core::ChannelFormat format = core::ChannelFormat::sRGB8;
    int width = 1024;
    int height = 1024;
};

/// One `plane` row.
struct PlaneRow {
    core::Id plane_id = core::kNoId;
    core::Id set_id = core::kNoId;
    core::Id stack_id = core::kNoId;
    std::optional<core::ChannelType> channel;  // NULL for a mask-stack plane
    int tile_u = 0;
    int tile_v = 0;
    core::ChannelFormat format = core::ChannelFormat::sRGB8;
    int width = 0;
    int height = 0;
    int chunk_size = kChunkSize;
    std::int64_t created_revision = 0;

    int chunks_x() const { return (width + chunk_size - 1) / chunk_size; }
    int chunks_y() const { return (height + chunk_size - 1) / chunk_size; }
    /// Texel rectangle of chunk (x, y): width and height (the last row/column may be narrower).
    int chunk_width(int x) const;
    int chunk_height(int y) const;
};

/// The texels of a whole plane: `width × height`, row-major, top row first, `TexelBytes(format)`
/// bytes each.
struct PlaneImage {
    int width = 0;
    int height = 0;
    core::ChannelFormat format = core::ChannelFormat::sRGB8;
    std::string texels;

    bool operator==(const PlaneImage&) const = default;
};

struct ChunkRow {
    int x = 0;
    int y = 0;
    std::string sha256;

    bool operator==(const ChunkRow&) const = default;
};

/// SHA-256 of the canonical JSON `[[x, y, "<sha256>"], ...]` of `rows` sorted by `(x, y)`.
std::string ChunkRoot(std::vector<ChunkRow> rows);

/// A binding `{version_id, chunk_root}` of one plane.
struct VersionRef {
    std::int64_t version_id = 0;
    std::string chunk_root;

    bool operator==(const VersionRef&) const = default;
    core::json::Value ToJson() const;
};

/// A plane binding found in a manifest: the plane, the version (when well-formed), the owning
/// node's id and the JSON path of the binding; `error` says why a malformed entry is unusable.
struct ManifestBinding {
    core::Id plane_id = core::kNoId;
    std::optional<VersionRef> version;
    std::optional<core::Id> owner;
    std::string path;
    std::string error;
};

/// Every plane binding of a manifest (the `plane_versions` members of paint objects), in document
/// order.
std::vector<ManifestBinding> ManifestPlaneBindings(const core::json::Value& manifest);

/// A plane a paint object references (`planes` or `plane`), whether that object binds it, its
/// owner and the path of the paint object.
struct PlaneReference {
    core::Id plane_id = core::kNoId;
    std::optional<core::Id> owner;
    std::string path;
    bool bound = false;
};

/// Every plane reference of a manifest's paint objects, in document order.
std::vector<PlaneReference> ManifestPlaneReferences(const core::json::Value& manifest);

/// The texels of a chunk blob: `StoreError(corrupt)` when the blob is absent, does not hold
/// `expected_size` bytes, does not decompress ("unreadable payload") or does not hash to its key
/// ("SHA-256 mismatch").
std::string ReadChunkBlob(Container& container, std::string_view sha256, std::size_t expected_size);

/// A version staged by a running transaction, not yet committed.
struct StagedVersion {
    core::Id plane_id = core::kNoId;
    std::vector<ChunkRow> chunks;                         // every non-empty chunk, sorted
    std::map<std::string, std::string, std::less<>> bytes;  // texels of chunks the store lacks, by SHA-256
    std::string chunk_root;
};

/// Plane rows and versions staged for the next commit. Versions the committed manifest does not
/// bind are dropped.
struct PendingPlanes {
    std::map<core::Id, PlaneRow> planes;  // planes created by the transaction (created_revision unset)
    std::map<std::int64_t, StagedVersion> versions;

    void clear() {
        planes.clear();
        versions.clear();
    }
};

/// Creates a plane owned by `spec.node` in the edit's working copy: allocates its `plane_id` from
/// the project counter, sets it on the node's `paint.planes[channel]` (or `paint.plane`) and binds
/// it to a new empty version. Throws `core::ValueError` when the node is not a paint layer or
/// paint effect, already holds a plane on that channel, the channel form does not match its stack
/// (content: a channel; mask: none), the set has no UV tile `spec.udim`, or the size is outside
/// 1..`kMaxPlaneEdge`; `StoreError(conflict)` when the allocated id is already a stored plane.
core::Id StageNewPlane(Container& container, PendingPlanes& pending, core::Edit& edit, const PlaneSpec& spec);

/// Stages `image` as the content of `plane_id` (bound in the edit's working copy) and rebinds the
/// owning node to it: a new version (or the transaction's own staged version, replaced) whose
/// chunk rows list every non-empty chunk, with bytes kept only for chunks the store does not hold.
/// Content equal to the bound version changes nothing. Returns the binding. Throws
/// `core::ValueError` when no node binds the plane or the image's size or format differ from the
/// plane's.
VersionRef StagePlaneContent(Container& container, PendingPlanes& pending, core::Edit& edit, core::Id plane_id,
                             const PlaneImage& image);

/// The commit extension: checks that every paint node of the committed project binds exactly the
/// planes it references, each to a staged version of that plane or a stored one with the same
/// `chunk_root`, then inserts the staged plane rows, chunk blobs, versions and chunk rows bound by
/// it (`created_revision = snapshot.revision`). Throws `StoreError(conflict)` otherwise.
void WritePlaneRows(Container& container, const PendingPlanes& pending, const core::Snapshot& snapshot);

/// The `plane` row of `plane_id`, if any.
std::optional<PlaneRow> ReadPlaneRow(Container& container, core::Id plane_id);
/// The chunk rows of a stored version, sorted.
std::vector<ChunkRow> ReadChunkRows(Container& container, std::int64_t version_id);

/// The pixels `project` binds to `plane_id` (a staged version or a stored one). Throws
/// `StoreError(missing_resource)` when the project does not bind the plane, `CorruptionError`
/// (with the owning node) when stored rows or chunk bytes do not verify.
PlaneImage ReadPlaneIn(Container& container, const PendingPlanes& pending, const core::Project& project,
                       core::Id plane_id);
/// The pixels the manifest of `revision` binds to `plane_id`.
PlaneImage ReadPlaneAt(Container& container, std::int64_t revision, core::Id plane_id);
/// The texels of chunk (x, y) of the version the manifest of `revision` binds to `plane_id`
/// (`chunk_width × chunk_height` texels; zeros when the version has no row for it).
std::string ReadPlaneChunkAt(Container& container, std::int64_t revision, core::Id plane_id, int x, int y);

}  // namespace uzp::store
