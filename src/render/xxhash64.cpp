#include "render/xxhash64.h"

#include <bit>
#include <cstring>

namespace uzp::render {

namespace {

constexpr uint64_t kPrime1 = 0x9E3779B185EBCA87ull;
constexpr uint64_t kPrime2 = 0xC2B2AE3D27D4EB4Full;
constexpr uint64_t kPrime3 = 0x165667B19E3779F9ull;
constexpr uint64_t kPrime4 = 0x85EBCA77C2B2AE63ull;
constexpr uint64_t kPrime5 = 0x27D4EB2F165667C5ull;

// Lanes are read little-endian; Windows x64 is little-endian.
static_assert(std::endian::native == std::endian::little);

uint64_t Read64(const std::byte* p) {
    uint64_t v;
    std::memcpy(&v, p, sizeof(v));
    return v;
}

uint32_t Read32(const std::byte* p) {
    uint32_t v;
    std::memcpy(&v, p, sizeof(v));
    return v;
}

uint64_t Round(uint64_t acc, uint64_t lane) {
    acc += lane * kPrime2;
    acc = std::rotl(acc, 31);
    return acc * kPrime1;
}

uint64_t Merge(uint64_t acc, uint64_t lane) {
    acc ^= Round(0, lane);
    return acc * kPrime1 + kPrime4;
}

}  // namespace

uint64_t Xxh64(std::span<const std::byte> data, uint64_t seed) {
    const std::byte* p = data.data();
    const std::byte* const end = p + data.size();
    uint64_t acc;

    if (data.size() >= 32) {
        uint64_t v1 = seed + kPrime1 + kPrime2;
        uint64_t v2 = seed + kPrime2;
        uint64_t v3 = seed;
        uint64_t v4 = seed - kPrime1;
        const std::byte* const lastStripe = end - 32;
        do {
            v1 = Round(v1, Read64(p));
            v2 = Round(v2, Read64(p + 8));
            v3 = Round(v3, Read64(p + 16));
            v4 = Round(v4, Read64(p + 24));
            p += 32;
        } while (p <= lastStripe);
        acc = std::rotl(v1, 1) + std::rotl(v2, 7) + std::rotl(v3, 12) + std::rotl(v4, 18);
        acc = Merge(acc, v1);
        acc = Merge(acc, v2);
        acc = Merge(acc, v3);
        acc = Merge(acc, v4);
    } else {
        acc = seed + kPrime5;
    }

    acc += static_cast<uint64_t>(data.size());

    while (end - p >= 8) {
        acc ^= Round(0, Read64(p));
        acc = std::rotl(acc, 27) * kPrime1 + kPrime4;
        p += 8;
    }
    if (end - p >= 4) {
        acc ^= static_cast<uint64_t>(Read32(p)) * kPrime1;
        acc = std::rotl(acc, 23) * kPrime2 + kPrime3;
        p += 4;
    }
    while (p < end) {
        acc ^= static_cast<uint64_t>(std::to_integer<uint8_t>(*p)) * kPrime5;
        acc = std::rotl(acc, 11) * kPrime1;
        ++p;
    }

    acc ^= acc >> 33;
    acc *= kPrime2;
    acc ^= acc >> 29;
    acc *= kPrime3;
    acc ^= acc >> 32;
    return acc;
}

}  // namespace uzp::render
