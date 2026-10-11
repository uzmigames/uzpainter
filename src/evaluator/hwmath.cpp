#include "evaluator/hwmath.h"

#include <bit>
#include <cmath>
#include <limits>
#include <mutex>
#include <stdexcept>

#include "zlib.h"

namespace uzp::evaluator::hw {

namespace {

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wc23-extensions"
constexpr unsigned char kRcpTable[] = {
#embed "tables/hw-rcp.zlib"
};
constexpr unsigned char kSqrtTable[] = {
#embed "tables/hw-sqrt.zlib"
};
constexpr unsigned char kRsqrtTable[] = {
#embed "tables/hw-rsqrt.zlib"
};
constexpr unsigned char kLog2HiTable[] = {
#embed "tables/hw-lg2-hi.zlib"
};
constexpr unsigned char kLog2LoTable[] = {
#embed "tables/hw-lg2-lo.zlib"
};
constexpr unsigned char kExp2PosTable[] = {
#embed "tables/hw-ex2-pos.zlib"
};
constexpr unsigned char kExp2NegTable[] = {
#embed "tables/hw-ex2-neg.zlib"
};
#pragma clang diagnostic pop

constexpr uint32_t kExponentMask = 0x7F800000u;
constexpr uint32_t kOne = 0x3F800000u;
constexpr uint32_t kQuietNaN = 0x7FC00000u;

uint32_t Entries(Op op) { return op == Op::Rcp ? kRcpEntries : kRootEntries; }

std::vector<uint32_t> Inflate(Op op) {
    const std::span<const unsigned char> packed = Compressed(op);
    std::vector<uint32_t> words(Entries(op) / 16);
    z_stream stream{};
    stream.next_in = const_cast<Bytef*>(packed.data());
    stream.avail_in = static_cast<uInt>(packed.size());
    stream.next_out = reinterpret_cast<Bytef*>(words.data());
    stream.avail_out = static_cast<uInt>(words.size() * sizeof(uint32_t));
    int status = inflateInit(&stream);
    if (status == Z_OK) status = inflate(&stream, Z_FINISH);
    const bool complete = status == Z_STREAM_END && stream.avail_out == 0;
    inflateEnd(&stream);
    if (!complete) {
        // The tables are part of the build; a damaged one is a build defect, not an input error.
        throw std::runtime_error("evaluator: embedded hardware arithmetic table is damaged");
    }
    return words;
}

std::vector<uint32_t> InflateValues(Table table) {
    const std::span<const unsigned char> packed = Compressed(table);
    std::vector<uint32_t> values(kTableEntries);
    z_stream stream{};
    stream.next_in = const_cast<Bytef*>(packed.data());
    stream.avail_in = static_cast<uInt>(packed.size());
    stream.next_out = reinterpret_cast<Bytef*>(values.data());
    stream.avail_out = static_cast<uInt>(values.size() * sizeof(uint32_t));
    int status = inflateInit(&stream);
    if (status == Z_OK) status = inflate(&stream, Z_FINISH);
    const bool complete = status == Z_STREAM_END && stream.avail_out == 0;
    inflateEnd(&stream);
    if (!complete) throw std::runtime_error("evaluator: embedded hardware arithmetic table is damaged");
    // Second differences back to the bit patterns (modulo 2^32).
    uint32_t previous = 0;
    uint32_t beforePrevious = 0;
    for (uint32_t& value : values) {
        const uint32_t bits = value + 2u * previous - beforePrevious;
        beforePrevious = previous;
        previous = bits;
        value = bits;
    }
    return values;
}

/// `v` (exact in double) rounded toward zero to float32.
float TowardZero(double v) {
    float r = static_cast<float>(v);
    if (std::fabs(static_cast<double>(r)) > std::fabs(v)) {
        r = std::bit_cast<float>(std::bit_cast<uint32_t>(r) - 1u);
    }
    return r;
}

/// `bits` moved by `delta` units in the last place (same sign, finite normal result).
float Nudge(float value, int delta) {
    return std::bit_cast<float>(std::bit_cast<uint32_t>(value) + static_cast<uint32_t>(delta));
}

/// The index of y in [1, 4) of the normal y = z 4^k and k.
uint32_t RootIndex(uint32_t bits, int& k) {
    const int e = static_cast<int>((bits >> 23) & 0xFFu) - 127;
    k = e >= 0 ? e / 2 : -((1 - e) / 2);  // floor(e / 2)
    const uint32_t z = static_cast<uint32_t>(static_cast<int64_t>(bits) - (int64_t{k} << 24));
    return z - kOne;
}

}  // namespace

std::span<const unsigned char> Compressed(Op op) {
    switch (op) {
        case Op::Rcp: return {kRcpTable, sizeof(kRcpTable)};
        case Op::Sqrt: return {kSqrtTable, sizeof(kSqrtTable)};
        case Op::Rsqrt: return {kRsqrtTable, sizeof(kRsqrtTable)};
    }
    return {};
}

const std::vector<uint32_t>& Words(Op op) {
    static std::once_flag once[3];
    static std::vector<uint32_t> words[3];
    const size_t i = static_cast<size_t>(op);
    std::call_once(once[i], [&] { words[i] = Inflate(op); });
    return words[i];
}

int Delta(Op op, uint32_t index) {
    const uint32_t word = Words(op)[index >> 4];
    return static_cast<int>((word >> ((index & 15u) * 2u)) & 3u) - 2;
}

float RsqrtCorrect(float y) {
    if (std::isnan(y) || y < 0.0f) return std::bit_cast<float>(kQuietNaN);
    if (y == 0.0f) return std::bit_cast<float>(0x7F800000u);
    if (std::isinf(y)) return 0.0f;
    float c = static_cast<float>(1.0 / std::sqrt(static_cast<double>(y)));
    const double Y = static_cast<double>(y);
    for (int i = 0; i < 4; ++i) {
        // m^2 is exact in double (m has 25 significant bits); fma rounds m^2 y - 1 once, so its
        // sign is exact.
        const float up = std::bit_cast<float>(std::bit_cast<uint32_t>(c) + 1u);
        const float down = std::bit_cast<float>(std::bit_cast<uint32_t>(c) - 1u);
        const double mUp = (static_cast<double>(c) + static_cast<double>(up)) * 0.5;
        const double mDown = (static_cast<double>(down) + static_cast<double>(c)) * 0.5;
        if (std::fma(mUp * mUp, Y, -1.0) < 0.0) c = up;
        else if (std::fma(mDown * mDown, Y, -1.0) > 0.0) c = down;
        else break;
    }
    return c;
}

float Rcp(float x) {
    const uint32_t bits = std::bit_cast<uint32_t>(x);
    const uint32_t sign = bits & 0x80000000u;
    const uint32_t magnitude = bits & 0x7FFFFFFFu;
    if (magnitude > kExponentMask) return std::bit_cast<float>(kQuietNaN);
    if (magnitude == kExponentMask) return std::bit_cast<float>(sign);
    if (magnitude < 0x00800000u) return std::bit_cast<float>(sign | kExponentMask);
    const float c = 1.0f / std::bit_cast<float>(magnitude);
    if (std::bit_cast<uint32_t>(c) < 0x00800000u) return std::bit_cast<float>(sign);  // below 2^-126
    const float r = Nudge(c, Delta(Op::Rcp, magnitude & 0x7FFFFFu));
    return std::bit_cast<float>(sign | std::bit_cast<uint32_t>(r));
}

float Sqrt(float y) {
    const uint32_t bits = std::bit_cast<uint32_t>(y);
    if ((bits & 0x7FFFFFFFu) > kExponentMask) return std::bit_cast<float>(kQuietNaN);
    if ((bits & 0x7FFFFFFFu) < 0x00800000u) return std::bit_cast<float>(bits & 0x80000000u);
    if (bits & 0x80000000u) return std::bit_cast<float>(kQuietNaN);
    if (bits == kExponentMask) return y;
    int k = 0;
    const uint32_t index = RootIndex(bits, k);
    return Nudge(std::sqrt(y), Delta(Op::Sqrt, index));
}

float Rsqrt(float y) {
    const uint32_t bits = std::bit_cast<uint32_t>(y);
    if ((bits & 0x7FFFFFFFu) > kExponentMask) return std::bit_cast<float>(kQuietNaN);
    if ((bits & 0x7FFFFFFFu) < 0x00800000u) return std::bit_cast<float>((bits & 0x80000000u) | kExponentMask);
    if (bits & 0x80000000u) return std::bit_cast<float>(kQuietNaN);
    if (bits == kExponentMask) return 0.0f;
    int k = 0;
    const uint32_t index = RootIndex(bits, k);
    return Nudge(RsqrtCorrect(y), Delta(Op::Rsqrt, index));
}

std::span<const unsigned char> Compressed(Table table) {
    switch (table) {
        case Table::Log2Hi: return {kLog2HiTable, sizeof(kLog2HiTable)};
        case Table::Log2Lo: return {kLog2LoTable, sizeof(kLog2LoTable)};
        case Table::Exp2Pos: return {kExp2PosTable, sizeof(kExp2PosTable)};
        case Table::Exp2Neg: return {kExp2NegTable, sizeof(kExp2NegTable)};
    }
    return {};
}

const std::vector<uint32_t>& Values(Table table) {
    static std::once_flag once[4];
    static std::vector<uint32_t> values[4];
    const size_t i = static_cast<size_t>(table);
    std::call_once(once[i], [&] { values[i] = InflateValues(table); });
    return values[i];
}

std::vector<unsigned char> CompressValues(const std::vector<uint32_t>& values) {
    std::vector<uint32_t> differences(values.size());
    uint32_t previous = 0;
    uint32_t beforePrevious = 0;
    for (size_t i = 0; i < values.size(); ++i) {
        differences[i] = values[i] - 2u * previous + beforePrevious;
        beforePrevious = previous;
        previous = values[i];
    }
    const uLong raw = static_cast<uLong>(differences.size() * sizeof(uint32_t));
    uLongf size = compressBound(raw);
    std::vector<unsigned char> out(size);
    compress2(out.data(), &size, reinterpret_cast<const Bytef*>(differences.data()), raw, 9);
    out.resize(size);
    return out;
}

float Log2(float x) {
    const uint32_t bits = std::bit_cast<uint32_t>(x);
    const uint32_t magnitude = bits & 0x7FFFFFFFu;
    if (magnitude > kExponentMask) return std::bit_cast<float>(kQuietNaN);
    if (magnitude < 0x00800000u) return -std::numeric_limits<float>::infinity();  // zeros, subnormals
    if (bits & 0x80000000u) return std::bit_cast<float>(kQuietNaN);
    if (bits == kExponentMask) return x;
    const int e = static_cast<int>(bits >> 23) - 127;
    const uint32_t m = bits & 0x7FFFFFu;
    if (e >= 0) {
        const float hi = std::bit_cast<float>(Values(Table::Log2Hi)[m]);
        return e == 0 ? hi : TowardZero(static_cast<double>(e) + static_cast<double>(hi));
    }
    const float lo = std::bit_cast<float>(Values(Table::Log2Lo)[m]);
    return e == -1 ? lo : TowardZero(static_cast<double>(e + 1) + static_cast<double>(lo));
}

float Exp2(float y) {
    if (std::isnan(y)) return std::bit_cast<float>(kQuietNaN);
    const double a = std::fabs(static_cast<double>(y));
    const bool negative = y < 0.0f;
    if (a >= 256.0) return negative ? 0.0f : std::numeric_limits<float>::infinity();
    const double k = std::floor(a);
    const uint32_t j = static_cast<uint32_t>(std::floor((a - k) * 8388608.0));
    const uint32_t bits = Values(negative ? Table::Exp2Neg : Table::Exp2Pos)[j];
    // 2^k scales the table value exactly in double; the float32 range decides the result.
    const int power = negative ? -static_cast<int>(k) : static_cast<int>(k);
    const double scaled = std::ldexp(static_cast<double>(std::bit_cast<float>(bits)), power);
    if (scaled < 0x1.0p-126) return 0.0f;
    if (scaled >= 0x1.0p128) return std::numeric_limits<float>::infinity();
    return static_cast<float>(scaled);
}

float Pow(float x, float g) {
    const float product = g * Log2(x);
    return Exp2(product);
}

}  // namespace uzp::evaluator::hw
