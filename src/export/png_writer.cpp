#include "export/png_writer.h"

#include <zlib.h>

#include <algorithm>
#include <array>
#include <cstddef>
#include <limits>
#include <stdexcept>
#include <string_view>

namespace uzp::exporter {

namespace {

constexpr std::string_view kSignature{"\x89PNG\r\n\x1a\n", 8};
/// pHYs: 2835 pixels per metre (72 per inch) on both axes, unit metre.
constexpr uint32_t kPixelsPerMetre = 2835;
/// The IDAT payload size; the last chunk holds the rest.
constexpr size_t kIdatSize = 8192;

enum Filter : uint8_t { kNone = 0, kSub = 1, kPaeth = 4 };

void PutU32(std::string& out, uint32_t v) {
    out.push_back(static_cast<char>(v >> 24));
    out.push_back(static_cast<char>((v >> 16) & 0xFF));
    out.push_back(static_cast<char>((v >> 8) & 0xFF));
    out.push_back(static_cast<char>(v & 0xFF));
}

void PutChunk(std::string& out, std::string_view type, std::string_view data) {
    PutU32(out, static_cast<uint32_t>(data.size()));
    const size_t start = out.size();
    out.append(type);
    out.append(data);
    uLong crc = crc32(0L, Z_NULL, 0);
    const auto* bytes = reinterpret_cast<const Bytef*>(out.data() + start);
    crc = crc32(crc, bytes, static_cast<uInt>(out.size() - start));
    PutU32(out, static_cast<uint32_t>(crc));
}

/// The cost of a filtered byte: its distance from zero as a signed byte.
uint32_t Cost(uint8_t v) { return v < 128 ? v : 256u - v; }

uint8_t Paeth(int a, int b, int c) {
    const int p = a + b - c;
    const int pa = p > a ? p - a : a - p;
    const int pb = p > b ? p - b : b - p;
    const int pc = p > c ? p - c : c - p;
    if (pa <= pb && pa <= pc) return static_cast<uint8_t>(a);
    if (pb <= pc) return static_cast<uint8_t>(b);
    return static_cast<uint8_t>(c);
}

/// Appends the filter byte and the filtered `row` (above: the previous raw row, zero for the first).
void FilterRow(const uint8_t* row, const uint8_t* above, size_t stride, size_t bpp, std::vector<uint8_t>& sub,
               std::vector<uint8_t>& paeth, std::vector<uint8_t>& out) {
    uint64_t none = 0;
    uint64_t subCost = 0;
    uint64_t paethCost = 0;
    for (size_t i = 0; i < stride; ++i) {
        const int a = i >= bpp ? row[i - bpp] : 0;
        const int b = above[i];
        const int c = i >= bpp ? above[i - bpp] : 0;
        sub[i] = static_cast<uint8_t>(row[i] - a);
        paeth[i] = static_cast<uint8_t>(row[i] - Paeth(a, b, c));
        none += Cost(row[i]);
        subCost += Cost(sub[i]);
        paethCost += Cost(paeth[i]);
    }
    Filter best = kNone;
    uint64_t bestCost = none;
    if (subCost < bestCost) {
        best = kSub;
        bestCost = subCost;
    }
    if (paethCost < bestCost) best = kPaeth;
    out.push_back(best);
    const uint8_t* chosen = best == kNone ? row : best == kSub ? sub.data() : paeth.data();
    out.insert(out.end(), chosen, chosen + stride);
}

/// One zlib stream of `data` (level 6, window bits 15, memory level 8, Z_FILTERED).
std::string Deflate(const std::vector<uint8_t>& data) {
    z_stream zs{};
    if (deflateInit2(&zs, 6, Z_DEFLATED, 15, 8, Z_FILTERED) != Z_OK) {
        throw std::runtime_error("png: deflateInit2 failed");
    }
    std::string out;
    std::array<unsigned char, 1 << 16> buffer{};
    size_t offset = 0;
    int status = Z_OK;
    while (status != Z_STREAM_END) {
        if (zs.avail_in == 0 && offset < data.size()) {
            const size_t n = std::min<size_t>(data.size() - offset, std::numeric_limits<uInt>::max() / 2);
            zs.next_in = const_cast<Bytef*>(data.data() + offset);
            zs.avail_in = static_cast<uInt>(n);
            offset += n;
        }
        zs.next_out = buffer.data();
        zs.avail_out = static_cast<uInt>(buffer.size());
        status = deflate(&zs, offset == data.size() ? Z_FINISH : Z_NO_FLUSH);
        if (status != Z_OK && status != Z_STREAM_END && status != Z_BUF_ERROR) {
            deflateEnd(&zs);
            throw std::runtime_error("png: deflate failed");
        }
        out.append(reinterpret_cast<const char*>(buffer.data()), buffer.size() - zs.avail_out);
    }
    deflateEnd(&zs);
    return out;
}

}  // namespace

std::string EncodePng(const PngImage& image) {
    if (image.width == 0 || image.height == 0) throw std::invalid_argument("png: empty image");
    if (image.channels != 1 && image.channels != 3) {
        throw std::invalid_argument("png: only grey and RGB are written (decision 090)");
    }
    if (image.bitDepth != 16) throw std::invalid_argument("png: only 16 bits per sample are written (decision 090)");
    const size_t samplesPerRow = size_t{image.width} * image.channels;
    if (image.samples.size() != samplesPerRow * image.height) {
        throw std::invalid_argument("png: the sample count does not match the image size");
    }
    const size_t bpp = size_t{image.channels} * 2;
    const size_t stride = samplesPerRow * 2;
    std::vector<uint8_t> raw(stride);
    std::vector<uint8_t> above(stride, 0);
    std::vector<uint8_t> sub(stride);
    std::vector<uint8_t> paeth(stride);
    std::vector<uint8_t> filtered;
    filtered.reserve((stride + 1) * image.height);
    for (uint32_t y = 0; y < image.height; ++y) {
        const uint16_t* samples = image.samples.data() + size_t{y} * samplesPerRow;
        for (size_t i = 0; i < samplesPerRow; ++i) {
            raw[2 * i] = static_cast<uint8_t>(samples[i] >> 8);
            raw[2 * i + 1] = static_cast<uint8_t>(samples[i] & 0xFF);
        }
        FilterRow(raw.data(), above.data(), stride, bpp, sub, paeth, filtered);
        std::swap(raw, above);
    }
    const std::string compressed = Deflate(filtered);

    std::string out(kSignature);
    std::string ihdr;
    PutU32(ihdr, image.width);
    PutU32(ihdr, image.height);
    ihdr.push_back(static_cast<char>(image.bitDepth));
    ihdr.push_back(static_cast<char>(image.channels == 1 ? 0 : 2));  // colour type: grey, RGB
    ihdr.push_back(0);                                               // deflate
    ihdr.push_back(0);                                               // adaptive filtering
    ihdr.push_back(0);                                               // not interlaced
    PutChunk(out, "IHDR", ihdr);
    std::string phys;
    PutU32(phys, kPixelsPerMetre);
    PutU32(phys, kPixelsPerMetre);
    phys.push_back(1);  // unit: metre
    PutChunk(out, "pHYs", phys);
    for (size_t offset = 0; offset < compressed.size(); offset += kIdatSize) {
        PutChunk(out, "IDAT", std::string_view(compressed).substr(offset, kIdatSize));
    }
    PutChunk(out, "IEND", {});
    return out;
}

}  // namespace uzp::exporter
