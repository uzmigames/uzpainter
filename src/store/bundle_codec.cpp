#include "store/bundle_codec.h"

#include <algorithm>
#include <array>
#include <cstdlib>
#include <cstring>
#include <map>
#include <optional>

#include "store/container.h"

namespace uzp::store::codec {
namespace {

using core::ChannelFormat;

[[noreturn]] void Corrupt(const std::string& what) { throw StoreError(StoreError::Code::corrupt, what); }

// ── Little/big-endian helpers ──────────────────────────────────────────────────────────────

void PutLe(std::string& out, std::uint64_t value, int bytes) {
    for (int i = 0; i < bytes; ++i) out.push_back(static_cast<char>((value >> (8 * i)) & 0xff));
}

void PutBe32(std::string& out, std::uint32_t value) {
    for (int i = 3; i >= 0; --i) out.push_back(static_cast<char>((value >> (8 * i)) & 0xff));
}

/// A bounds-checked reader over `bytes`; `what` names the format in errors.
class Reader {
public:
    Reader(std::string_view bytes, const char* what) : bytes_(bytes), what_(what) {}

    std::size_t pos() const { return pos_; }
    std::size_t size() const { return bytes_.size(); }
    void Seek(std::uint64_t pos) {
        if (pos > bytes_.size()) Corrupt(std::string(what_) + ": offset beyond the end of the file");
        pos_ = static_cast<std::size_t>(pos);
    }
    std::string_view Take(std::uint64_t count) {
        if (count > bytes_.size() - pos_) Corrupt(std::string(what_) + ": truncated");
        const std::string_view out = bytes_.substr(pos_, static_cast<std::size_t>(count));
        pos_ += static_cast<std::size_t>(count);
        return out;
    }
    std::uint64_t Le(int count) {
        const std::string_view b = Take(static_cast<std::uint64_t>(count));
        std::uint64_t value = 0;
        for (int i = count - 1; i >= 0; --i) value = (value << 8) | static_cast<std::uint8_t>(b[static_cast<std::size_t>(i)]);
        return value;
    }
    std::uint32_t Be32() {
        const std::string_view b = Take(4);
        std::uint32_t value = 0;
        for (char c : b) value = (value << 8) | static_cast<std::uint8_t>(c);
        return value;
    }
    std::string Zstring() {
        const std::size_t end = bytes_.find('\0', pos_);
        if (end == std::string_view::npos) Corrupt(std::string(what_) + ": unterminated name");
        std::string out(bytes_.substr(pos_, end - pos_));
        pos_ = end + 1;
        return out;
    }

private:
    std::string_view bytes_;
    const char* what_;
    std::size_t pos_ = 0;
};

std::uint32_t Adler32(std::string_view bytes) {
    std::uint32_t a = 1, b = 0;
    std::size_t i = 0;
    while (i < bytes.size()) {
        const std::size_t end = std::min(bytes.size(), i + 5552);
        for (; i < end; ++i) {
            a += static_cast<std::uint8_t>(bytes[i]);
            b += a;
        }
        a %= 65521;
        b %= 65521;
    }
    return (b << 16) | a;
}

// ── Inflate (RFC 1951) ─────────────────────────────────────────────────────────────────────

constexpr int kMaxBits = 15;

class BitReader {
public:
    explicit BitReader(std::string_view bytes) : bytes_(bytes) {}

    int Bits(int need) {
        std::uint64_t value = buffer_;
        while (count_ < need) {
            if (pos_ == bytes_.size()) Corrupt("deflate: stream truncated");
            value |= static_cast<std::uint64_t>(static_cast<std::uint8_t>(bytes_[pos_++])) << count_;
            count_ += 8;
        }
        buffer_ = value >> need;
        count_ -= need;
        return static_cast<int>(value & ((std::uint64_t{1} << need) - 1));
    }
    /// Drops the bits up to the next byte boundary.
    void Align() {
        buffer_ = 0;
        count_ = 0;
    }
    std::string_view TakeBytes(std::size_t count) {
        if (count > bytes_.size() - pos_) Corrupt("deflate: stored block truncated");
        const std::string_view out = bytes_.substr(pos_, count);
        pos_ += count;
        return out;
    }
    std::size_t pos() const { return pos_; }

private:
    std::string_view bytes_;
    std::size_t pos_ = 0;
    std::uint64_t buffer_ = 0;
    int count_ = 0;
};

struct Huffman {
    std::array<short, kMaxBits + 1> count{};
    std::vector<short> symbol;
};

/// Builds the canonical code of `lengths`; returns the number of unused codes (0 for a complete
/// code, negative when over-subscribed).
int Construct(Huffman& h, const short* lengths, int n) {
    h.count.fill(0);
    h.symbol.assign(static_cast<std::size_t>(n), 0);
    for (int s = 0; s < n; ++s) ++h.count[static_cast<std::size_t>(lengths[s])];
    if (h.count[0] == n) return 0;
    int left = 1;
    for (int len = 1; len <= kMaxBits; ++len) {
        left <<= 1;
        left -= h.count[static_cast<std::size_t>(len)];
        if (left < 0) return left;
    }
    std::array<short, kMaxBits + 1> offs{};
    for (int len = 1; len < kMaxBits; ++len) {
        offs[static_cast<std::size_t>(len + 1)] =
            static_cast<short>(offs[static_cast<std::size_t>(len)] + h.count[static_cast<std::size_t>(len)]);
    }
    for (int s = 0; s < n; ++s) {
        if (lengths[s] != 0) h.symbol[static_cast<std::size_t>(offs[static_cast<std::size_t>(lengths[s])]++)] = static_cast<short>(s);
    }
    return left;
}

int Decode(BitReader& in, const Huffman& h) {
    int code = 0, first = 0, index = 0;
    for (int len = 1; len <= kMaxBits; ++len) {
        code |= in.Bits(1);
        const int count = h.count[static_cast<std::size_t>(len)];
        if (code - count < first) return h.symbol[static_cast<std::size_t>(index + (code - first))];
        index += count;
        first += count;
        first <<= 1;
        code <<= 1;
    }
    Corrupt("deflate: invalid Huffman code");
}

constexpr std::array<short, 29> kLengthBase = {3,  4,  5,  6,  7,  8,  9,  10, 11,  13,  15,  17,  19,  23, 27,
                                               31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258};
constexpr std::array<short, 29> kLengthExtra = {0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2,
                                                2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0};
constexpr std::array<short, 30> kDistBase = {1,   2,   3,   4,   5,   7,    9,    13,   17,   25,   33,   49,    65,    97,    129,
                                             193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577};
constexpr std::array<short, 30> kDistExtra = {0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6,
                                              6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13};

void Codes(BitReader& in, std::string& out, const Huffman& lencode, const Huffman& distcode) {
    for (;;) {
        int symbol = Decode(in, lencode);
        if (symbol < 256) {
            out.push_back(static_cast<char>(symbol));
            continue;
        }
        if (symbol == 256) return;
        symbol -= 257;
        if (symbol >= 29) Corrupt("deflate: invalid length symbol");
        const std::size_t length = static_cast<std::size_t>(kLengthBase[static_cast<std::size_t>(symbol)] +
                                                            in.Bits(kLengthExtra[static_cast<std::size_t>(symbol)]));
        symbol = Decode(in, distcode);
        if (symbol < 0 || symbol >= 30) Corrupt("deflate: invalid distance symbol");
        const std::size_t dist = static_cast<std::size_t>(kDistBase[static_cast<std::size_t>(symbol)] +
                                                          in.Bits(kDistExtra[static_cast<std::size_t>(symbol)]));
        if (dist > out.size()) Corrupt("deflate: distance before the start of the output");
        const std::size_t from = out.size() - dist;
        for (std::size_t i = 0; i < length; ++i) out.push_back(out[from + i]);
    }
}

void Fixed(BitReader& in, std::string& out) {
    static const auto tables = [] {
        std::pair<Huffman, Huffman> t;
        std::array<short, 288> lengths{};
        for (int s = 0; s < 288; ++s) lengths[static_cast<std::size_t>(s)] = s < 144 ? 8 : s < 256 ? 9 : s < 280 ? 7 : 8;
        Construct(t.first, lengths.data(), 288);
        std::array<short, 30> dist{};
        dist.fill(5);
        Construct(t.second, dist.data(), 30);
        return t;
    }();
    Codes(in, out, tables.first, tables.second);
}

void Dynamic(BitReader& in, std::string& out) {
    static constexpr std::array<short, 19> kOrder = {16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15};
    const int nlen = in.Bits(5) + 257;
    const int ndist = in.Bits(5) + 1;
    const int ncode = in.Bits(4) + 4;
    if (nlen > 286 || ndist > 30) Corrupt("deflate: too many length or distance codes");
    std::array<short, 320> lengths{};
    for (int i = 0; i < ncode; ++i) lengths[static_cast<std::size_t>(kOrder[static_cast<std::size_t>(i)])] = static_cast<short>(in.Bits(3));
    Huffman lencode, distcode;
    if (Construct(lencode, lengths.data(), 19) != 0) Corrupt("deflate: incomplete code-length code");
    int index = 0;
    while (index < nlen + ndist) {
        int symbol = Decode(in, lencode);
        if (symbol < 16) {
            lengths[static_cast<std::size_t>(index++)] = static_cast<short>(symbol);
            continue;
        }
        short value = 0;
        int repeat = 0;
        if (symbol == 16) {
            if (index == 0) Corrupt("deflate: repeat without a previous length");
            value = lengths[static_cast<std::size_t>(index - 1)];
            repeat = 3 + in.Bits(2);
        } else if (symbol == 17) {
            repeat = 3 + in.Bits(3);
        } else {
            repeat = 11 + in.Bits(7);
        }
        if (index + repeat > nlen + ndist) Corrupt("deflate: too many code lengths");
        while (repeat-- > 0) lengths[static_cast<std::size_t>(index++)] = value;
    }
    if (lengths[256] == 0) Corrupt("deflate: no end-of-block code");
    int err = Construct(lencode, lengths.data(), nlen);
    if (err != 0 && (err < 0 || nlen != lencode.count[0] + lencode.count[1])) Corrupt("deflate: invalid literal/length code");
    err = Construct(distcode, lengths.data() + nlen, ndist);
    if (err != 0 && (err < 0 || ndist != distcode.count[0] + distcode.count[1])) Corrupt("deflate: invalid distance code");
    Codes(in, out, lencode, distcode);
}

// ── PNG ────────────────────────────────────────────────────────────────────────────────────

constexpr std::string_view kPngSignature("\x89PNG\r\n\x1a\n", 8);

struct PngLayout {
    int channels = 1;  // 1 grey, 3 RGB
    int bits = 8;      // 8 or 16
};

PngLayout PngLayoutOf(ChannelFormat format) {
    switch (format) {
        case ChannelFormat::L8:
            return {1, 8};
        case ChannelFormat::sRGB8:
        case ChannelFormat::RGB8:
            return {3, 8};
        case ChannelFormat::L16:
            return {1, 16};
        case ChannelFormat::RGB16:
            return {3, 16};
        default:
            throw StoreError(StoreError::Code::conflict,
                             "png: " + std::string(core::ToString(format)) + " is stored as OpenEXR, not PNG");
    }
}

void PutPngChunk(std::string& out, std::string_view type, std::string_view data) {
    PutBe32(out, static_cast<std::uint32_t>(data.size()));
    std::string body(type);
    body.append(data);
    out.append(body);
    PutBe32(out, Crc32(body));
}

int Paeth(int a, int b, int c) {
    const int p = a + b - c;
    const int pa = std::abs(p - a), pb = std::abs(p - b), pc = std::abs(p - c);
    if (pa <= pb && pa <= pc) return a;
    return pb <= pc ? b : c;
}

// ── OpenEXR ────────────────────────────────────────────────────────────────────────────────

constexpr std::uint32_t kExrMagic = 20000630;

struct ExrLayout {
    int channels = 1;     // 1 (Y) or 3 (B, G, R in the file; R, G, B in the plane)
    int pixel_type = 1;   // 1 HALF, 2 FLOAT
    int sample_bytes = 2;
};

ExrLayout ExrLayoutOf(ChannelFormat format) {
    switch (format) {
        case ChannelFormat::L16F:
            return {1, 1, 2};
        case ChannelFormat::RGB16F:
            return {3, 1, 2};
        case ChannelFormat::L32F:
            return {1, 2, 4};
        case ChannelFormat::RGB32F:
            return {3, 2, 4};
        default:
            throw StoreError(StoreError::Code::conflict,
                             "exr: " + std::string(core::ToString(format)) + " is stored as PNG, not OpenEXR");
    }
}

void PutAttribute(std::string& out, std::string_view name, std::string_view type, std::string_view value) {
    out.append(name);
    out.push_back('\0');
    out.append(type);
    out.push_back('\0');
    PutLe(out, value.size(), 4);
    out.append(value);
}

std::string Box(int width, int height) {
    std::string box;
    PutLe(box, 0, 4);
    PutLe(box, 0, 4);
    PutLe(box, static_cast<std::uint32_t>(width - 1), 4);
    PutLe(box, static_cast<std::uint32_t>(height - 1), 4);
    return box;
}

std::string FloatBytes(float value) {
    std::uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof bits);
    std::string out;
    PutLe(out, bits, 4);
    return out;
}

void CheckImage(const PlaneImage& image) {
    if (image.width < 1 || image.height < 1 ||
        image.texels.size() != static_cast<std::size_t>(image.width) * static_cast<std::size_t>(image.height) *
                                   TexelBytes(image.format)) {
        throw StoreError(StoreError::Code::conflict, "the plane image does not hold width x height texels");
    }
}

}  // namespace

std::uint32_t Crc32(std::string_view bytes, std::uint32_t crc) {
    static const auto table = [] {
        std::array<std::uint32_t, 256> t{};
        for (std::uint32_t n = 0; n < 256; ++n) {
            std::uint32_t c = n;
            for (int k = 0; k < 8; ++k) c = (c & 1) ? 0xedb88320u ^ (c >> 1) : c >> 1;
            t[n] = c;
        }
        return t;
    }();
    crc = ~crc;
    for (char ch : bytes) crc = table[(crc ^ static_cast<std::uint8_t>(ch)) & 0xff] ^ (crc >> 8);
    return ~crc;
}

std::string Inflate(std::string_view zlib_stream) {
    if (zlib_stream.size() < 6) Corrupt("zlib: stream truncated");
    const auto cmf = static_cast<std::uint8_t>(zlib_stream[0]);
    const auto flg = static_cast<std::uint8_t>(zlib_stream[1]);
    if ((cmf & 0x0f) != 8 || (cmf >> 4) > 7 || ((cmf << 8) | flg) % 31 != 0) Corrupt("zlib: not a deflate stream");
    if ((flg & 0x20) != 0) Corrupt("zlib: preset dictionaries are not supported");
    BitReader in(zlib_stream.substr(2));
    std::string out;
    for (bool last = false; !last;) {
        last = in.Bits(1) == 1;
        switch (in.Bits(2)) {
            case 0: {
                in.Align();
                const std::string_view header = in.TakeBytes(4);
                const unsigned len = static_cast<std::uint8_t>(header[0]) | (static_cast<unsigned>(static_cast<std::uint8_t>(header[1])) << 8);
                const unsigned nlen = static_cast<std::uint8_t>(header[2]) | (static_cast<unsigned>(static_cast<std::uint8_t>(header[3])) << 8);
                if (len != (~nlen & 0xffffu)) Corrupt("deflate: stored block length does not match its complement");
                out.append(in.TakeBytes(len));
                break;
            }
            case 1:
                Fixed(in, out);
                break;
            case 2:
                Dynamic(in, out);
                break;
            default:
                Corrupt("deflate: invalid block type");
        }
    }
    const std::size_t end = 2 + in.pos();  // the Adler-32 follows the last (partial) byte
    if (zlib_stream.size() < end + 4) Corrupt("zlib: Adler-32 missing");
    std::uint32_t adler = 0;
    for (std::size_t i = 0; i < 4; ++i) adler = (adler << 8) | static_cast<std::uint8_t>(zlib_stream[end + i]);
    if (adler != Adler32(out)) Corrupt("zlib: Adler-32 mismatch");
    return out;
}

bool IsExrFormat(ChannelFormat format) {
    return format == ChannelFormat::L16F || format == ChannelFormat::RGB16F || format == ChannelFormat::L32F ||
           format == ChannelFormat::RGB32F;
}

std::string EncodePng(const PlaneImage& image) {
    CheckImage(image);
    const PngLayout layout = PngLayoutOf(image.format);
    const std::size_t sample = static_cast<std::size_t>(layout.bits / 8);
    const std::size_t row = static_cast<std::size_t>(image.width) * static_cast<std::size_t>(layout.channels) * sample;

    std::string raw;
    raw.reserve((row + 1) * static_cast<std::size_t>(image.height));
    for (int y = 0; y < image.height; ++y) {
        raw.push_back('\0');  // filter: none
        const char* src = image.texels.data() + static_cast<std::size_t>(y) * row;
        if (sample == 1) {
            raw.append(src, row);
        } else {
            for (std::size_t i = 0; i < row; i += 2) {  // little-endian texels, big-endian PNG samples
                raw.push_back(src[i + 1]);
                raw.push_back(src[i]);
            }
        }
    }

    std::string zlib("\x78\x01", 2);
    for (std::size_t at = 0; at < raw.size();) {
        const std::size_t len = std::min<std::size_t>(65535, raw.size() - at);
        zlib.push_back(at + len == raw.size() ? '\x01' : '\x00');
        PutLe(zlib, len, 2);
        PutLe(zlib, ~len & 0xffff, 2);
        zlib.append(raw, at, len);
        at += len;
    }
    PutBe32(zlib, Adler32(raw));

    std::string out(kPngSignature);
    std::string ihdr;
    PutBe32(ihdr, static_cast<std::uint32_t>(image.width));
    PutBe32(ihdr, static_cast<std::uint32_t>(image.height));
    ihdr.push_back(static_cast<char>(layout.bits));
    ihdr.push_back(static_cast<char>(layout.channels == 1 ? 0 : 2));
    ihdr.append(3, '\0');  // deflate, adaptive filtering, no interlace
    PutPngChunk(out, "IHDR", ihdr);
    if (image.format == ChannelFormat::sRGB8) PutPngChunk(out, "sRGB", std::string(1, '\0'));
    constexpr std::size_t kIdat = std::size_t{8} << 20;
    for (std::size_t at = 0; at < zlib.size(); at += kIdat) {
        PutPngChunk(out, "IDAT", std::string_view(zlib).substr(at, kIdat));
    }
    PutPngChunk(out, "IEND", "");
    return out;
}

PlaneImage DecodePng(std::string_view bytes, ChannelFormat format) {
    const PngLayout layout = PngLayoutOf(format);
    Reader in(bytes, "png");
    if (in.Take(8) != kPngSignature) Corrupt("png: not a PNG file");
    int width = 0, height = 0;
    std::string zlib;
    bool header = false, end = false;
    while (!end) {
        const std::uint32_t length = in.Be32();
        const std::string_view body = in.Take(std::uint64_t{length} + 4);
        if (in.Be32() != Crc32(body)) Corrupt("png: chunk CRC mismatch");
        const std::string_view type = body.substr(0, 4);
        const std::string_view data = body.substr(4);
        if (type == "IHDR") {
            if (data.size() != 13) Corrupt("png: malformed IHDR");
            Reader h(data, "png");
            width = static_cast<int>(h.Be32());
            height = static_cast<int>(h.Be32());
            const std::string_view rest = h.Take(5);
            const int bits = static_cast<std::uint8_t>(rest[0]);
            const int colour = static_cast<std::uint8_t>(rest[1]);
            if (rest[2] != 0 || rest[3] != 0) Corrupt("png: unknown compression or filter method");
            if (rest[4] != 0) Corrupt("png: interlaced PNGs are not supported by the bundle reader");
            const int channels = colour == 0 ? 1 : colour == 2 ? 3 : 0;
            if (channels != layout.channels || bits != layout.bits) {
                Corrupt("png: colour type " + std::to_string(colour) + ", " + std::to_string(bits) + " bits per sample does not hold " +
                        std::string(core::ToString(format)));
            }
            if (width < 1 || height < 1 || width > kMaxPlaneEdge || height > kMaxPlaneEdge) Corrupt("png: invalid size");
            header = true;
        } else if (type == "IDAT") {
            if (!header) Corrupt("png: IDAT before IHDR");
            zlib.append(data);
        } else if (type == "IEND") {
            end = true;
        } else if ((static_cast<std::uint8_t>(type[0]) & 0x20) == 0) {
            Corrupt("png: unknown critical chunk " + std::string(type));
        }
    }
    if (!header) Corrupt("png: no IHDR");

    const std::size_t bpp = static_cast<std::size_t>(layout.channels * layout.bits / 8);
    const std::size_t row = static_cast<std::size_t>(width) * bpp;
    const std::string raw = Inflate(zlib);
    if (raw.size() != (row + 1) * static_cast<std::size_t>(height)) Corrupt("png: image data size does not match IHDR");

    PlaneImage image{width, height, format, std::string(row * static_cast<std::size_t>(height), '\0')};
    std::string previous(row, '\0');
    std::string current(row, '\0');
    for (int y = 0; y < height; ++y) {
        const std::size_t at = static_cast<std::size_t>(y) * (row + 1);
        const int filter = static_cast<std::uint8_t>(raw[at]);
        for (std::size_t i = 0; i < row; ++i) {
            const int x = static_cast<std::uint8_t>(raw[at + 1 + i]);
            const int a = i >= bpp ? static_cast<std::uint8_t>(current[i - bpp]) : 0;
            const int b = static_cast<std::uint8_t>(previous[i]);
            const int c = i >= bpp ? static_cast<std::uint8_t>(previous[i - bpp]) : 0;
            int value = 0;
            switch (filter) {
                case 0: value = x; break;
                case 1: value = x + a; break;
                case 2: value = x + b; break;
                case 3: value = x + (a + b) / 2; break;
                case 4: value = x + Paeth(a, b, c); break;
                default: Corrupt("png: unknown filter type " + std::to_string(filter));
            }
            current[i] = static_cast<char>(value & 0xff);
        }
        char* dst = image.texels.data() + static_cast<std::size_t>(y) * row;
        if (layout.bits == 8) {
            std::memcpy(dst, current.data(), row);
        } else {
            for (std::size_t i = 0; i < row; i += 2) {
                dst[i] = current[i + 1];
                dst[i + 1] = current[i];
            }
        }
        std::swap(previous, current);
    }
    return image;
}

std::string EncodeExr(const PlaneImage& image) {
    CheckImage(image);
    const ExrLayout layout = ExrLayoutOf(image.format);
    std::string out;
    PutLe(out, kExrMagic, 4);
    PutLe(out, 2, 4);  // version 2, single-part scanline

    std::string channels;
    for (const char* name : layout.channels == 1 ? std::vector<const char*>{"Y"} : std::vector<const char*>{"B", "G", "R"}) {
        channels.append(name);
        channels.push_back('\0');
        PutLe(channels, static_cast<std::uint32_t>(layout.pixel_type), 4);
        PutLe(channels, 0, 4);  // pLinear + reserved
        PutLe(channels, 1, 4);  // xSampling
        PutLe(channels, 1, 4);  // ySampling
    }
    channels.push_back('\0');
    PutAttribute(out, "channels", "chlist", channels);
    PutAttribute(out, "compression", "compression", std::string(1, '\0'));
    PutAttribute(out, "dataWindow", "box2i", Box(image.width, image.height));
    PutAttribute(out, "displayWindow", "box2i", Box(image.width, image.height));
    PutAttribute(out, "lineOrder", "lineOrder", std::string(1, '\0'));
    PutAttribute(out, "pixelAspectRatio", "float", FloatBytes(1.0f));
    PutAttribute(out, "screenWindowCenter", "v2f", FloatBytes(0.0f) + FloatBytes(0.0f));
    PutAttribute(out, "screenWindowWidth", "float", FloatBytes(1.0f));
    out.push_back('\0');

    const std::size_t sample = static_cast<std::size_t>(layout.sample_bytes);
    const std::size_t texel = sample * static_cast<std::size_t>(layout.channels);
    const std::size_t line = static_cast<std::size_t>(image.width) * texel;
    const std::uint64_t table = out.size();
    std::uint64_t offset = table + 8 * static_cast<std::uint64_t>(image.height);
    for (int y = 0; y < image.height; ++y) {
        PutLe(out, offset, 8);
        offset += 8 + line;
    }
    for (int y = 0; y < image.height; ++y) {
        PutLe(out, static_cast<std::uint32_t>(y), 4);
        PutLe(out, line, 4);
        const char* row = image.texels.data() + static_cast<std::size_t>(y) * line;
        for (int c = layout.channels - 1; c >= 0; --c) {  // file order B, G, R (or Y)
            for (int x = 0; x < image.width; ++x) {
                out.append(row + static_cast<std::size_t>(x) * texel + static_cast<std::size_t>(c) * sample, sample);
            }
        }
    }
    return out;
}

PlaneImage DecodeExr(std::string_view bytes, ChannelFormat format) {
    const ExrLayout layout = ExrLayoutOf(format);
    Reader in(bytes, "exr");
    if (in.Le(4) != kExrMagic) Corrupt("exr: not an OpenEXR file");
    const std::uint64_t version = in.Le(4);
    if ((version & 0xff) != 2) Corrupt("exr: unsupported version " + std::to_string(version & 0xff));
    if ((version & 0x200) != 0) Corrupt("exr: tiled files are not supported by the bundle reader");
    if ((version & 0x1800) != 0) Corrupt("exr: deep and multi-part files are not supported by the bundle reader");

    struct ChannelInfo {
        int type = 0;
        int xs = 0;
        int ys = 0;
    };
    std::map<std::string, ChannelInfo> channels;
    std::optional<int> compression;
    std::optional<std::array<std::int32_t, 4>> window;
    for (;;) {
        const std::string name = in.Zstring();
        if (name.empty()) break;
        const std::string type = in.Zstring();
        const std::uint64_t size = in.Le(4);
        Reader value(in.Take(size), "exr");
        if (name == "channels" && type == "chlist") {
            for (;;) {
                const std::string channel = value.Zstring();
                if (channel.empty()) break;
                ChannelInfo info;
                info.type = static_cast<int>(value.Le(4));
                value.Take(4);
                info.xs = static_cast<int>(value.Le(4));
                info.ys = static_cast<int>(value.Le(4));
                channels[channel] = info;
            }
        } else if (name == "compression" && type == "compression") {
            compression = static_cast<int>(value.Le(1));
        } else if (name == "dataWindow" && type == "box2i") {
            std::array<std::int32_t, 4> box{};
            for (std::int32_t& v : box) v = static_cast<std::int32_t>(static_cast<std::uint32_t>(value.Le(4)));
            window = box;
        }
    }
    if (!compression || !window || channels.empty()) Corrupt("exr: channels, compression or dataWindow missing");
    if (*compression != 0) {
        Corrupt("exr: compression " + std::to_string(*compression) + " is not supported by the bundle reader (uncompressed only)");
    }
    const std::vector<std::string> expected =
        layout.channels == 1 ? std::vector<std::string>{"Y"} : std::vector<std::string>{"B", "G", "R"};
    std::vector<std::string> names;
    for (const auto& [name, info] : channels) {
        names.push_back(name);
        if (info.type != layout.pixel_type || info.xs != 1 || info.ys != 1) {
            Corrupt("exr: channel " + name + " is not a full-resolution " + (layout.pixel_type == 1 ? "HALF" : "FLOAT") +
                    " channel of " + std::string(core::ToString(format)));
        }
    }
    if (names != expected) Corrupt("exr: the channels do not hold " + std::string(core::ToString(format)));
    const std::int64_t width = std::int64_t{(*window)[2]} - (*window)[0] + 1;
    const std::int64_t height = std::int64_t{(*window)[3]} - (*window)[1] + 1;
    if (width < 1 || height < 1 || width > kMaxPlaneEdge || height > kMaxPlaneEdge) Corrupt("exr: invalid dataWindow");

    const std::size_t sample = static_cast<std::size_t>(layout.sample_bytes);
    const std::size_t texel = sample * static_cast<std::size_t>(layout.channels);
    const std::size_t line = static_cast<std::size_t>(width) * texel;
    PlaneImage image{static_cast<int>(width), static_cast<int>(height), format,
                     std::string(line * static_cast<std::size_t>(height), '\0')};
    std::vector<std::uint64_t> offsets(static_cast<std::size_t>(height));
    for (std::uint64_t& offset : offsets) offset = in.Le(8);
    std::vector<bool> seen(static_cast<std::size_t>(height), false);
    for (const std::uint64_t offset : offsets) {
        in.Seek(offset);
        const std::int64_t y = static_cast<std::int32_t>(static_cast<std::uint32_t>(in.Le(4))) - std::int64_t{(*window)[1]};
        if (y < 0 || y >= height || seen[static_cast<std::size_t>(y)]) Corrupt("exr: invalid scanline chunk");
        seen[static_cast<std::size_t>(y)] = true;
        if (in.Le(4) != line) Corrupt("exr: scanline chunk size does not match the channels");
        const std::string_view data = in.Take(line);
        char* row = image.texels.data() + static_cast<std::size_t>(y) * line;
        std::size_t at = 0;
        for (int c = layout.channels - 1; c >= 0; --c) {
            for (std::int64_t x = 0; x < width; ++x, at += sample) {
                std::memcpy(row + static_cast<std::size_t>(x) * texel + static_cast<std::size_t>(c) * sample, data.data() + at, sample);
            }
        }
    }
    return image;
}

// ── ZIP ────────────────────────────────────────────────────────────────────────────────────

namespace {
constexpr std::uint64_t kZip32 = 0xffffffffu;
constexpr std::uint16_t kDosDate = (0 << 9) | (1 << 5) | 1;  // 1980-01-01
}  // namespace

ZipWriter::ZipWriter(const std::filesystem::path& path) : path_(path), file_(path, std::ios::binary | std::ios::trunc) {
    if (!file_) {
        const std::u8string text = path.u8string();
        throw StoreError(StoreError::Code::io, "cannot write " + std::string(text.begin(), text.end()));
    }
}

void ZipWriter::Write(std::string_view bytes) {
    file_.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    if (!file_) {
        const std::u8string text = path_.u8string();
        throw StoreError(StoreError::Code::io, "cannot write " + std::string(text.begin(), text.end()));
    }
    offset_ += bytes.size();
}

void ZipWriter::Add(std::string_view name, std::string_view bytes) {
    Entry entry{std::string(name), Crc32(bytes), bytes.size(), offset_};
    const bool zip64 = entry.size >= kZip32;
    std::string header;
    PutLe(header, 0x04034b50, 4);
    PutLe(header, zip64 ? 45 : 20, 2);
    PutLe(header, 0x0800, 2);  // UTF-8 names
    PutLe(header, 0, 2);       // stored
    PutLe(header, 0, 2);
    PutLe(header, kDosDate, 2);
    PutLe(header, entry.crc, 4);
    PutLe(header, zip64 ? kZip32 : entry.size, 4);
    PutLe(header, zip64 ? kZip32 : entry.size, 4);
    PutLe(header, entry.name.size(), 2);
    PutLe(header, zip64 ? 20 : 0, 2);
    header.append(entry.name);
    if (zip64) {
        PutLe(header, 0x0001, 2);
        PutLe(header, 16, 2);
        PutLe(header, entry.size, 8);
        PutLe(header, entry.size, 8);
    }
    Write(header);
    Write(bytes);
    entries_.push_back(std::move(entry));
}

void ZipWriter::Finish() {
    const std::uint64_t directory = offset_;
    for (const Entry& entry : entries_) {
        const bool zip64 = entry.size >= kZip32 || entry.offset >= kZip32;
        std::string header;
        PutLe(header, 0x02014b50, 4);
        PutLe(header, 45, 2);
        PutLe(header, zip64 ? 45 : 20, 2);
        PutLe(header, 0x0800, 2);
        PutLe(header, 0, 2);
        PutLe(header, 0, 2);
        PutLe(header, kDosDate, 2);
        PutLe(header, entry.crc, 4);
        PutLe(header, zip64 ? kZip32 : entry.size, 4);
        PutLe(header, zip64 ? kZip32 : entry.size, 4);
        PutLe(header, entry.name.size(), 2);
        PutLe(header, zip64 ? 28 : 0, 2);
        PutLe(header, 0, 2);  // comment
        PutLe(header, 0, 2);  // disk
        PutLe(header, 0, 2);  // internal attributes
        PutLe(header, 0, 4);  // external attributes
        PutLe(header, zip64 ? kZip32 : entry.offset, 4);
        header.append(entry.name);
        if (zip64) {
            PutLe(header, 0x0001, 2);
            PutLe(header, 24, 2);
            PutLe(header, entry.size, 8);
            PutLe(header, entry.size, 8);
            PutLe(header, entry.offset, 8);
        }
        Write(header);
    }
    const std::uint64_t size = offset_ - directory;
    const std::uint64_t count = entries_.size();
    std::string end;
    if (count >= 0xffff || size >= kZip32 || directory >= kZip32) {
        const std::uint64_t record = offset_;
        PutLe(end, 0x06064b50, 4);
        PutLe(end, 44, 8);
        PutLe(end, 45, 2);
        PutLe(end, 45, 2);
        PutLe(end, 0, 4);
        PutLe(end, 0, 4);
        PutLe(end, count, 8);
        PutLe(end, count, 8);
        PutLe(end, size, 8);
        PutLe(end, directory, 8);
        PutLe(end, 0x07064b50, 4);
        PutLe(end, 0, 4);
        PutLe(end, record, 8);
        PutLe(end, 1, 4);
    }
    PutLe(end, 0x06054b50, 4);
    PutLe(end, 0, 2);
    PutLe(end, 0, 2);
    PutLe(end, std::min<std::uint64_t>(count, 0xffff), 2);
    PutLe(end, std::min<std::uint64_t>(count, 0xffff), 2);
    PutLe(end, std::min(size, kZip32), 4);
    PutLe(end, std::min(directory, kZip32), 4);
    PutLe(end, 0, 2);
    Write(end);
    file_.close();
    if (!file_) {
        const std::u8string text = path_.u8string();
        throw StoreError(StoreError::Code::io, "cannot write " + std::string(text.begin(), text.end()));
    }
}

}  // namespace uzp::store::codec
