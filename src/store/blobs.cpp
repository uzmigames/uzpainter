#include "store/blobs.h"

#include <fstream>
#include <vector>

#include "uzp_core/manifest/sha256.h"

namespace uzp::store {
namespace {

std::string Utf8(const std::filesystem::path& path) {
    const std::u8string text = path.u8string();
    return std::string(text.begin(), text.end());
}

std::string Hex(const std::array<std::uint8_t, 32>& digest) {
    static constexpr char kDigits[] = "0123456789abcdef";
    std::string hex;
    hex.reserve(64);
    for (const std::uint8_t byte : digest) {
        hex.push_back(kDigits[byte >> 4]);
        hex.push_back(kDigits[byte & 0x0f]);
    }
    return hex;
}

}  // namespace

std::string PutBlob(Container& container, std::string_view bytes, std::string_view mime) {
    std::string sha256 = core::Sha256Hex(bytes);
    if (HasBlob(container, sha256)) return sha256;
    const std::string frame = Compress(bytes);
    Statement q(container, "INSERT INTO blob (sha256, mime, size, zstd_size, data) VALUES (?, ?, ?, ?, ?)");
    q.Bind(1, sha256)
        .Bind(2, mime)
        .Bind(3, static_cast<std::int64_t>(bytes.size()))
        .Bind(4, static_cast<std::int64_t>(frame.size()))
        .BindBlob(5, frame)
        .Run();
    return sha256;
}

void PutBlobName(Container& container, const BlobName& name) {
    Statement q(container,
                "INSERT OR IGNORE INTO blob_meta (sha256, name, usage, origin, color_space, imported_at) "
                "VALUES (?, ?, ?, ?, ?, ?)");
    q.Bind(1, name.sha256)
        .Bind(2, name.name)
        .Bind(3, name.usage)
        .Bind(4, name.origin)
        .Bind(5, name.color_space)
        .Bind(6, name.imported_at)
        .Run();
}

void PutLocator(Container& container, std::string_view sha256, const std::filesystem::path& path) {
    Statement q(container, "INSERT OR REPLACE INTO locator (sha256, path) VALUES (?, ?)");
    q.Bind(1, sha256).Bind(2, Utf8(path)).Run();
}

bool HasBlob(Container& container, std::string_view sha256) {
    Statement q(container, "SELECT 1 FROM blob WHERE sha256 = ?");
    q.Bind(1, sha256);
    return q.Step();
}

std::optional<std::filesystem::path> FindLocator(Container& container, std::string_view sha256) {
    Statement q(container, "SELECT path FROM locator WHERE sha256 = ?");
    q.Bind(1, sha256);
    if (!q.Step()) return std::nullopt;
    const std::string text = q.Text(0);
    return std::filesystem::path(std::u8string(text.begin(), text.end()));
}

std::string ReadBlob(Container& container, std::string_view sha256) {
    Statement q(container, "SELECT size, data FROM blob WHERE sha256 = ?");
    q.Bind(1, sha256);
    if (!q.Step()) throw StoreError(StoreError::Code::missing_resource, "no stored blob " + std::string(sha256));
    if (q.IsNull(0) || q.Int(0) < 0) throw StoreError(StoreError::Code::corrupt, "blob " + std::string(sha256) + ": no size");
    std::string bytes;
    try {
        bytes = Decompress(q.Blob(1), static_cast<std::uint64_t>(q.Int(0)));
    } catch (const StoreError& error) {
        throw StoreError(StoreError::Code::corrupt, "blob " + std::string(sha256) + ": " + error.what());
    }
    if (core::Sha256Hex(bytes) != sha256) {
        throw StoreError(StoreError::Code::corrupt, "blob " + std::string(sha256) + ": the bytes do not hash to it");
    }
    return bytes;
}

std::optional<std::string> HashFile(const std::filesystem::path& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) return std::nullopt;
    core::Sha256 hash;
    std::vector<char> buffer(1 << 20);
    while (file) {
        file.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        const std::streamsize got = file.gcount();
        if (got > 0) hash.Update(std::string_view(buffer.data(), static_cast<std::size_t>(got)));
    }
    if (!file.eof()) return std::nullopt;
    return Hex(hash.Finish());
}

}  // namespace uzp::store
