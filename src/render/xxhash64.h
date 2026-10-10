#pragma once

// XXH64, the 64-bit xxHash, as specified by the xxHash specification (algorithm only; the key of
// the kernel cache, docs/architecture/13-engine-integration.md §2.4). Bit-exact with the reference
// implementation: tests/render/render_core_test.cpp checks it against reference digests.

#include <cstddef>
#include <cstdint>
#include <span>

namespace uzp::render {

/// XXH64 of `data` with `seed`.
[[nodiscard]] uint64_t Xxh64(std::span<const std::byte> data, uint64_t seed = 0);

}  // namespace uzp::render
