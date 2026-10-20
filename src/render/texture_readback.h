#pragma once

// GPU texture readback at native precision (docs/architecture/13-engine-integration.md §2.3,
// §2.4, §4.1): every parity comparison and every export reads its texels through here.
//
// - Per-request ownership: each request allocates its own staging buffer (`Readback` memory)
//   and owns it until the request completes, fails or is drained.
// - Aligned pitch: the copy writes rows at `ReadbackRowPitch` (the row size rounded up to the
//   256 bytes `CopyTextureToBuffer` requires); results come back tightly packed.
// - Fence-linked map: each request's copy is its own submission; its staging buffer is mapped
//   only after the wait for that submission's fence returned `signaled`. Any other wait result
//   fails the request with the wait's error (`timeout` or `device_removed`) and no texels.
// - Drain: completes or fails every outstanding request in submission order and releases every
//   staging buffer.
// - Native formats, no conversion: texel bytes are copied as the GPU stores them (8-bit and
//   16-bit unorm, 16- and 32-bit float, 32-bit uint; one to four channels).
//
// A `TextureReadback` lives inside one engine request (engine_thread.h) and uses its context:
// submissions go through the engine's queue and every wait is bounded by the request's deadline.
// The textures read must stay alive until their requests have completed.

#include "render/backend.h"
#include "render/engine_thread.h"

#include <cstddef>
#include <cstdint>
#include <deque>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace uzp::render {

/// The row-pitch alignment of a texture-to-buffer copy (DX12
/// `D3D12_TEXTURE_DATA_PITCH_ALIGNMENT`).
inline constexpr uint32_t kReadbackPitchAlignment = 256;

/// The staging-buffer row pitch of a row of `rowBytes` bytes: the next multiple of 256.
[[nodiscard]] constexpr uint64_t ReadbackRowPitch(uint64_t rowBytes) {
    return (rowBytes + kReadbackPitchAlignment - 1) / kReadbackPitchAlignment *
           kReadbackPitchAlignment;
}

/// The row pitch of rows of `bytesPerTexel`-byte texels: the next multiple of both 256 (DX12's
/// pitch alignment) and the texel size, so the pitch is also a whole number of texels — Vulkan's
/// `bufferRowLength` is counted in texels (`vulkan_command_list.cpp` divides the pitch by the texel
/// size). For the power-of-two texel sizes this is `ReadbackRowPitch(rowBytes)`; for `RGB32Float`
/// (12 bytes) it is a multiple of 768.
[[nodiscard]] constexpr uint64_t ReadbackRowPitch(uint64_t rowBytes, uint32_t bytesPerTexel) {
    uint64_t a = kReadbackPitchAlignment;
    uint64_t b = bytesPerTexel == 0 ? 1 : bytesPerTexel;
    while (b != 0) {
        const uint64_t r = a % b;
        a = b;
        b = r;
    }
    const uint64_t alignment = kReadbackPitchAlignment / a * (bytesPerTexel == 0 ? 1 : bytesPerTexel);
    return (rowBytes + alignment - 1) / alignment * alignment;
}

/// How a readable format stores a texel: `channels` channels of `bytesPerChannel` bytes each.
struct TexelLayout {
    uint32_t channels = 0;
    uint32_t bytesPerChannel = 0;

    [[nodiscard]] uint32_t BytesPerTexel() const { return channels * bytesPerChannel; }
    friend bool operator==(const TexelLayout&, const TexelLayout&) = default;
};

/// The texel layout of a format readback supports; empty for `Unknown`, block-compressed and
/// depth/stencil formats.
///
/// Three-channel `RGB8`, `RGB16` and `RGB16F` data has no GPU format of its own (only `RGB32F`
/// has); it is held in the four-channel format of its depth and read back with
/// `ReadbackDesc::channels = 3`.
[[nodiscard]] std::optional<TexelLayout> ReadbackLayout(uz::RHIFormat format);

/// Why `format` is not read back on `backend`, by name; empty when it is. Vulkan refuses
/// `RGB32Float`: the owner's RTX 4090 has no optimal-tiling features for `R32G32B32_SFLOAT`
/// (decision 310 §8).
[[nodiscard]] std::optional<std::string> ReadbackRefusal(Backend backend, uz::RHIFormat format);

/// One readback: one subresource (mip level, array slice or volume slice) of one texture.
struct ReadbackDesc {
    /// The texture to read; created with `CopySrc` usage.
    uz::RHITextureHandle texture = uz::RHITextureHandle::Invalid();
    uint32_t mipLevel = 0;
    /// The array slice, or the Z slice of a volume texture.
    uint32_t arraySlice = 0;
    /// The state the texture is in when the copy runs. The copy moves it to `CopySrc` and back.
    uz::RHIResourceState state = uz::RHIResourceState::Common;
    /// Channels returned per texel: 0 returns all of the format's channels, 1 to 4 the first
    /// `channels` of them (bytes copied as stored).
    uint32_t channels = 0;
};

/// Texels read back at the texture's native precision.
struct ReadbackImage {
    uz::RHIFormat format = uz::RHIFormat::Unknown;  ///< The texture's format.
    uint32_t width = 0;                             ///< Of the read subresource.
    uint32_t height = 0;
    uint32_t channels = 0;                          ///< Channels per returned texel.
    uint32_t bytesPerChannel = 0;
    /// Rows top to bottom, each `RowBytes()` long with no padding; texel bytes exactly as the
    /// GPU stores them (little-endian channels in the format's channel order).
    std::vector<std::byte> texels;

    [[nodiscard]] size_t TexelBytes() const { return size_t{channels} * bytesPerChannel; }
    [[nodiscard]] size_t RowBytes() const { return TexelBytes() * width; }
};

/// Identifies one request of one `TextureReadback`; ids increase in submission order.
using ReadbackId = uint64_t;

/// A request's terminal state, as `Drain()` reports it.
struct ReadbackOutcome {
    ReadbackId id = 0;
    Result<ReadbackImage> image;
};

class TextureReadback {
public:
    explicit TextureReadback(EngineContext& context);
    /// `Drain()`; the outcomes are discarded.
    ~TextureReadback();
    TextureReadback(const TextureReadback&) = delete;
    TextureReadback& operator=(const TextureReadback&) = delete;

    /// Validates the request, allocates its staging buffer and submits its copy. On an error
    /// nothing stays allocated and nothing was submitted.
    Result<ReadbackId> Request(const ReadbackDesc& desc);

    /// Waits for the request's copy (bounded by the engine request's deadline), maps its staging
    /// buffer only when the wait returned `signaled` and returns the texels; returns the wait's
    /// error otherwise. The request is terminal afterwards; its staging buffer is released.
    Result<ReadbackImage> Complete(ReadbackId id);

    /// Completes or fails every outstanding request in submission order and releases every
    /// staging buffer.
    std::vector<ReadbackOutcome> Drain();

    /// Requests submitted and not yet completed.
    [[nodiscard]] size_t Outstanding() const { return m_pending.size(); }
    /// Staging buffers this object holds: those of outstanding requests, plus those of requests
    /// whose wait timed out while the GPU may still write them (released by `Drain()` once their
    /// copy has completed or the device is lost; a GPU that never completes keeps them, as the
    /// engine then keeps its device).
    [[nodiscard]] size_t StagingBuffers() const { return m_pending.size() + m_heldBack.size(); }

private:
    struct Pending {
        ReadbackId id = 0;
        uint64_t fence = 0;
        uz::RHIBufferHandle staging = uz::RHIBufferHandle::Invalid();
        uz::RHIFormat format = uz::RHIFormat::Unknown;
        TexelLayout layout;
        uint32_t channels = 0;
        uint32_t width = 0;
        uint32_t height = 0;
        uint64_t rowPitch = 0;
    };

    Result<ReadbackImage> Finish(const Pending& pending);
    void ReleaseHeldBack();

    EngineContext& m_context;
    IDevice& m_device;
    std::deque<Pending> m_pending;
    /// (fence value, staging buffer) of requests whose wait timed out.
    std::vector<std::pair<uint64_t, uz::RHIBufferHandle>> m_heldBack;
    ReadbackId m_nextId = 1;
};

}  // namespace uzp::render
