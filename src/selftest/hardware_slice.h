#pragma once

// The DX12 hardware-adapter qualification slice of `selftest`
// (docs/architecture/13-engine-integration.md §4.2), in run order:
//
//   dx12-device       DX12 device on the hardware adapter, Agility SDK runtime from D3D12\
//   shader-compile    one compute kernel compiled at run time by DXC to DXIL and to SPIR-V
//   compute-readback  the DXIL kernel writes a 16-bit pattern; read back through a mapped buffer
//   png16             the pattern written as a 16-bit PNG and decoded back equal
//   embree            an Embree intersection of a known ray with a known triangle
//
// Every stage is mandatory. `dx12-device` and `compute-readback` need a GPU and are skipped
// with the reason when the run has none (hosted CI, decision 028); the other three always run.

#include "harness.h"

#include <cstdint>
#include <vector>

namespace uzp::selftest {

/// Width and height of the 16-bit pattern. A row is 200 bytes, so the 256-byte row pitch of
/// the readback buffer pads every row.
inline constexpr uint32_t kPatternWidth = 100;
inline constexpr uint32_t kPatternHeight = 64;

/// The 16-bit value the kernel writes at (x, y). It is stored in an R16_FLOAT texture, so a value
/// whose exponent bits are all ones (an infinity or NaN as a half) has bit 14 flipped to stay a
/// finite half; the HLSL kernel (hardware_slice.cpp) computes the same function.
constexpr uint16_t PatternValue(uint32_t x, uint32_t y) {
    uint32_t v = (x * 0x9E37u + y * 0x7F4Au + 0x1234u) & 0xFFFFu;
    if (((v >> 10) & 0x1Fu) == 0x1Fu) v ^= 0x4000u;
    return static_cast<uint16_t>(v);
}

/// The whole pattern, row-major.
std::vector<uint16_t> ExpectedPattern();

void RegisterHardwareSlice(Selftest& selftest);

/// Destroys the GPU state of the run (device last).
void TeardownHardwareSlice(SelftestContext& context);

StageOutcome RunDx12Device(SelftestContext& context);
StageOutcome RunShaderCompile(SelftestContext& context);
StageOutcome RunComputeReadback(SelftestContext& context);
StageOutcome RunPng16(SelftestContext& context);
StageOutcome RunEmbree(SelftestContext& context);

}  // namespace uzp::selftest
