#pragma once

// The float32 reciprocal, square root and reciprocal square root of the GPU the Tier 0 goldens
// were recorded on (NVIDIA GeForce RTX 4090, D3D12), which Painter's blend kernels use
// (parity/semantics/blend-kernels.json): `Divide`, `ColorBurn`, `ColorDodge` and the HSV modes
// divide through the hardware reciprocal, `SoftLight` takes the hardware square root, the
// normal-map modes normalise through the hardware reciprocal square root. These results are
// faithful (within one unit in the last place) but not correctly rounded, so they are
// reproduced from measured tables on every backend, never from the host's or the GPU's own
// instructions:
//
//   Hw(x) = the correctly rounded result moved by d(x) units in the last place,
//
// with d in {-2, -1, 0, 1} read from `src/evaluator/tables/hw-<op>.zlib`. Each table is a zlib
// stream of little-endian uint32 words holding sixteen 2-bit codes each (code = d + 2, entry i
// at bits 2 (i mod 16) of word i / 16), measured over every float32 of the reduced domain by
// `uzp-evaluator-tests fp-hardware`:
//
//   rcp:   entry m for x = 1 + m 2^-23 in [1, 2) (2^23 entries); 1/x of any normal x scales by
//          its exponent;
//   sqrt, rsqrt: entry i for the i-th float32 in [1, 4) (2^24 entries); y = z 4^k scales the
//          result by 2^k (2^-k).
//
// Inputs outside the normal range follow the measured hardware (the `fp-hardware` case checks
// them): subnormal inputs count as zero of their sign; 1/(+-0) = +-inf, 1/(+-inf) = +-0, and a
// reciprocal below the smallest normal is +-0; sqrt(+-0) = +-0, sqrt(+inf) = +inf, rsqrt(+-0) =
// +-inf, rsqrt(+inf) = +0; sqrt and rsqrt of a negative number and every NaN give the quiet NaN.

#include <cstdint>
#include <span>
#include <vector>

namespace uzp::evaluator::hw {

enum class Op : uint8_t { Rcp, Sqrt, Rsqrt };

inline constexpr uint32_t kRcpEntries = 1u << 23;
inline constexpr uint32_t kRootEntries = 1u << 24;

/// The packed delta words of `op` (16 entries per word), inflated once from the embedded table.
[[nodiscard]] const std::vector<uint32_t>& Words(Op op);

/// The measured offset d of entry `index` of `op`, in units in the last place.
[[nodiscard]] int Delta(Op op, uint32_t index);

/// 1 / sqrt(y) correctly rounded to float32 (the reference the rsqrt table is relative to).
[[nodiscard]] float RsqrtCorrect(float y);

/// The hardware results (see above).
[[nodiscard]] float Rcp(float x);
[[nodiscard]] float Sqrt(float y);
[[nodiscard]] float Rsqrt(float y);

/// The table of `op` as stored: the zlib stream of `Words(op)` (the `fp-hardware` case writes a
/// measured table in this form for comparison).
[[nodiscard]] std::span<const unsigned char> Compressed(Op op);

}  // namespace uzp::evaluator::hw
