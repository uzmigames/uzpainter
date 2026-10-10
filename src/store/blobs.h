#pragma once

// Content-addressed resource storage (`docs/architecture/09-project-file-format.md` §1-§2).
//
// Resource bytes are stored once per SHA-256 in `blob`, zstd-compressed and unmodified (the
// decompressed bytes are the imported file); every name under which the project knows them is a
// separate `blob_meta` row, so two imports of identical bytes share one blob and keep two names.
// A portable project (the default) embeds every dependency. An explicitly non-portable project
// may instead keep a `{path, sha256}` locator (`locator` table) and reports a locator whose file
// is absent or changed as a missing dependency on open.

#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <string_view>

#include "store/container.h"

namespace uzp::store {

/// One `blob_meta` row.
struct BlobName {
    std::string sha256;
    std::string name;
    std::string usage;
    std::string origin;
    std::string color_space;
    std::string imported_at;
};

/// Inserts the bytes unless a blob with their SHA-256 exists; returns the SHA-256.
std::string PutBlob(Container& container, std::string_view bytes, std::string_view mime);

/// Inserts the name unless the blob already has a row with that name.
void PutBlobName(Container& container, const BlobName& name);

/// Inserts or replaces the locator of `sha256`.
void PutLocator(Container& container, std::string_view sha256, const std::filesystem::path& path);

bool HasBlob(Container& container, std::string_view sha256);
std::optional<std::filesystem::path> FindLocator(Container& container, std::string_view sha256);

/// The stored bytes of `sha256`, decompressed and verified against the hash. Throws
/// `StoreError(corrupt)` (no affected nodes; the project store adds them) when the payload does
/// not decompress or does not hash to `sha256`, `StoreError(missing_resource)` when absent.
std::string ReadBlob(Container& container, std::string_view sha256);

/// SHA-256 of a file's bytes, or nothing when it cannot be read.
std::optional<std::string> HashFile(const std::filesystem::path& path);

}  // namespace uzp::store
