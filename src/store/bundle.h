#pragma once

// `uzpainter export-bundle <file.uzp> <dir|zip>` and the bundle import of `project.open`
// (`docs/architecture/09-project-file-format.md` §6): one revision of a project as plain files for
// archive tools and humans, importable back into a `.uzp` with the same manifest digest and plane
// pixels. Layout (a directory, or the same paths inside a ZIP whose name ends in `.zip`):
//
// | Path | Content |
// |---|---|
// | `manifest.json` | The revision's canonical manifest, byte for byte (its SHA-256 is `manifest_sha256`) |
// | `res/<sha256>.<ext>` | Every resource that is not a mesh map, original bytes |
// | `meshmaps/<set>_<usage>.<ext>` | Every mesh-map resource, original bytes (`<sha256>.<ext>` when the name is taken) |
// | `planes/<plane_id>.png` / `.exr` | Every bound raster plane at its native precision (PNG for 8/16-bit, OpenEXR for half/float; `bundle_codec.h`) |
// | `bundle.json` | The index: `schema` `uzpainter/bundle/1`, `project_uuid`, `revision`, `manifest_sha256`, `resources` [{sha256, file, mime, bytes}], `planes` [{plane_id, file, format, width, height, set_id, stack_id, channel, tile_u, tile_v, version_id, chunk_root}] |
//
// The export reads a snapshot of the file (`ReadSnapshot`): no project lock, no GPU, and the
// source is never written. Every byte is verified on the way out (manifest digest, resource
// SHA-256, plane chunk rows and blobs). The bundle is written beside the target as
// `<target>.partial` and renamed when complete, so a failed export leaves no target.

#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <string_view>

namespace uzp::store {

/// `bundle.json`'s `schema`.
inline constexpr std::string_view kBundleSchema = "uzpainter/bundle/1";

struct BundleSummary {
    std::int64_t revision = 0;
    std::string manifest_sha256;
    std::int64_t resources = 0;
    std::int64_t mesh_maps = 0;
    std::int64_t planes = 0;
};

/// Exports `revision` (default `checkpoint('current')`) of `project` to `target`: a ZIP when its
/// name ends in `.zip` (any case), a directory otherwise. Throws `StoreError(exists)` when
/// `target` exists, `CorruptionError` when content does not verify and `StoreError(io)` when
/// the bundle cannot be written.
BundleSummary ExportBundle(const std::filesystem::path& project, const std::filesystem::path& target,
                           std::optional<std::int64_t> revision = std::nullopt);

/// True when `path` is a directory holding `bundle.json` (`project.open` imports it).
bool IsBundleDirectory(const std::filesystem::path& path);

/// The `.uzp` `project.open` creates for a bundle directory: `<dir>.uzp` beside it.
std::filesystem::path BundleImportTarget(const std::filesystem::path& bundle);

/// Creates the portable project `target` from the bundle directory `bundle`: the same project
/// uuid, one revision (the bundle's number, `kind = checkpoint`, `checkpoint('current')`) whose
/// manifest is `manifest.json` byte for byte, every resource embedded and every plane bound with
/// its version id and `chunk_root`. Everything is checked before the file is committed: the
/// manifest against `manifest_sha256` (and its canonical form), each resource file against its
/// SHA-256, each plane's pixels against the `chunk_root` its manifest binding names. Throws
/// `StoreError(exists)` when `target` exists, `StoreError(corrupt)` for a bundle that does not
/// verify (the target is removed) and `StoreError(io)` for unreadable files.
void ImportBundle(const std::filesystem::path& bundle, const std::filesystem::path& target);

}  // namespace uzp::store
