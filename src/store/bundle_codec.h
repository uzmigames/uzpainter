#pragma once

// File formats of the export bundle (`bundle.h`, `docs/architecture/09-project-file-format.md`
// §6): PNG and OpenEXR at a raster plane's native precision, and ZIP. Self-contained, no zlib:
//
// - PNG (8- and 16-bit greyscale or RGB, the formats sRGB8, L8, RGB8, L16, RGB16) is written with
//   stored deflate blocks and read with a complete inflate decoder (stored, fixed and dynamic
//   Huffman blocks) and all five scanline filters, so a PNG another tool recompressed reads back;
//   interlaced, palette and alpha PNGs are refused.
// - OpenEXR (half or float, channel `Y` or `B`,`G`,`R`: L16F, RGB16F, L32F, RGB32F) is written as
//   a single-part scanline file without compression; the reader refuses any other compression,
//   tiled, deep and multi-part files.
// - ZIP entries are stored (method 0) with CRC-32, UTF-8 names and ZIP64 records wherever a size,
//   an offset or the entry count needs them.
//
// Every reader throws `StoreError(corrupt)` for malformed input and names what it refused.

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string>
#include <string_view>
#include <vector>

#include "store/planes.h"
#include "uzp_core/types/enums.h"

namespace uzp::store::codec {

/// CRC-32 (ISO 3309, as PNG and ZIP use it) of `bytes`, continuing from `crc`.
std::uint32_t Crc32(std::string_view bytes, std::uint32_t crc = 0);

/// The bytes of a zlib stream (RFC 1950 wrapping RFC 1951 deflate), Adler-32 checked.
std::string Inflate(std::string_view zlib_stream);

/// True for the formats a bundle stores as OpenEXR (L16F, RGB16F, L32F, RGB32F); the others are PNG.
bool IsExrFormat(core::ChannelFormat format);

/// The PNG of a plane in an 8- or 16-bit format (`sRGB8` carries an `sRGB` chunk).
std::string EncodePng(const PlaneImage& image);
/// The plane a PNG holds, read as `format` (its colour type and bit depth must match it).
PlaneImage DecodePng(std::string_view bytes, core::ChannelFormat format);

/// The uncompressed scanline OpenEXR of a plane in a half or float format.
std::string EncodeExr(const PlaneImage& image);
/// The plane an OpenEXR holds, read as `format` (its channels and pixel type must match it).
PlaneImage DecodeExr(std::string_view bytes, core::ChannelFormat format);

/// Writes a ZIP archive entry by entry.
class ZipWriter {
public:
    /// Creates `path` (truncating it). Throws `StoreError(io)` when it cannot be written.
    explicit ZipWriter(const std::filesystem::path& path);
    /// Appends `bytes` stored under `name` (forward slashes).
    void Add(std::string_view name, std::string_view bytes);
    /// Writes the central directory and closes the file.
    void Finish();

private:
    struct Entry {
        std::string name;
        std::uint32_t crc = 0;
        std::uint64_t size = 0;
        std::uint64_t offset = 0;
    };
    void Write(std::string_view bytes);

    std::filesystem::path path_;
    std::ofstream file_;
    std::uint64_t offset_ = 0;
    std::vector<Entry> entries_;
};

}  // namespace uzp::store::codec
