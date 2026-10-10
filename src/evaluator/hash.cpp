#include "evaluator/hash.h"

#include <bit>

namespace uzp::evaluator {

namespace {

enum Tag : uint8_t { kU8 = 1, kU32, kU64, kF32, kF64, kBool, kStr, kBytes, kSub };

void PutLittle(core::Sha256& sha, uint64_t value, size_t bytes) {
    char buffer[8];
    for (size_t i = 0; i < bytes; ++i) buffer[i] = static_cast<char>((value >> (8 * i)) & 0xFF);
    sha.Update(std::string_view(buffer, bytes));
}

}  // namespace

std::string Hex(const Digest& digest) {
    static constexpr char kDigits[] = "0123456789abcdef";
    std::string text;
    text.reserve(64);
    for (const uint8_t byte : digest) {
        text.push_back(kDigits[byte >> 4]);
        text.push_back(kDigits[byte & 0xF]);
    }
    return text;
}

void HashWriter::Tag(uint8_t tag) { PutLittle(sha_, tag, 1); }

HashWriter& HashWriter::U8(uint8_t value) {
    Tag(kU8);
    PutLittle(sha_, value, 1);
    return *this;
}

HashWriter& HashWriter::U32(uint32_t value) {
    Tag(kU32);
    PutLittle(sha_, value, 4);
    return *this;
}

HashWriter& HashWriter::U64(uint64_t value) {
    Tag(kU64);
    PutLittle(sha_, value, 8);
    return *this;
}

HashWriter& HashWriter::F32(float value) {
    Tag(kF32);
    PutLittle(sha_, std::bit_cast<uint32_t>(value), 4);
    return *this;
}

HashWriter& HashWriter::F64(double value) {
    Tag(kF64);
    PutLittle(sha_, std::bit_cast<uint64_t>(value), 8);
    return *this;
}

HashWriter& HashWriter::Bool(bool value) {
    Tag(kBool);
    PutLittle(sha_, value ? 1 : 0, 1);
    return *this;
}

HashWriter& HashWriter::Str(std::string_view value) {
    Tag(kStr);
    PutLittle(sha_, value.size(), 8);
    sha_.Update(value);
    return *this;
}

HashWriter& HashWriter::Bytes(std::string_view bytes) {
    Tag(kBytes);
    PutLittle(sha_, bytes.size(), 8);
    sha_.Update(bytes);
    return *this;
}

HashWriter& HashWriter::Sub(const Digest& digest) {
    Tag(kSub);
    sha_.Update(std::string_view(reinterpret_cast<const char*>(digest.data()), digest.size()));
    return *this;
}

Digest HashWriter::Finish() { return sha_.Finish(); }

}  // namespace uzp::evaluator
