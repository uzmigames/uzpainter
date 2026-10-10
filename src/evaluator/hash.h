#pragma once

// Subtree hashes of the evaluation DAG (docs/architecture/04-layer-stack-and-compositing.md §7):
// SHA-256 over a tagged byte stream of everything that determines a node's output for one
// channel, so equal hashes mean equal results and a changed revision re-evaluates exactly the
// nodes whose inputs changed.

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>

#include "uzp_core/manifest/sha256.h"

namespace uzp::evaluator {

using Digest = std::array<uint8_t, 32>;

/// Lower-case hexadecimal of a digest.
[[nodiscard]] std::string Hex(const Digest& digest);

/// Hash of a digest for unordered containers (its first eight bytes).
struct DigestHash {
    size_t operator()(const Digest& digest) const noexcept {
        size_t value = 0;
        for (size_t i = 0; i < sizeof(size_t); ++i) {
            value |= static_cast<size_t>(digest[i]) << (8 * i);
        }
        return value;
    }
};

/// Writes typed fields; every field is prefixed with a one-byte tag so that different field
/// sequences never produce the same stream.
class HashWriter {
public:
    HashWriter& U8(uint8_t value);
    HashWriter& U32(uint32_t value);
    HashWriter& U64(uint64_t value);
    HashWriter& F32(float value);
    HashWriter& F64(double value);
    HashWriter& Bool(bool value);
    HashWriter& Str(std::string_view value);
    HashWriter& Bytes(std::string_view bytes);
    HashWriter& Sub(const Digest& digest);

    [[nodiscard]] Digest Finish();

private:
    void Tag(uint8_t tag);
    core::Sha256 sha_;
};

}  // namespace uzp::evaluator
