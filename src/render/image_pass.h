#pragma once

// Shared pieces of UzPainter's GPU image passes (docs/architecture/13-engine-integration.md §4.1):
// jump-flood dilation (dilation.h), resampling (resample.h) and mip generation (mips.h).
//
// The passes run inside one engine request (engine_thread.h): each validates its textures,
// records its dispatches into one submission and waits for it within the request's deadline.
// Every texture handed to a pass is in the `Common` state on entry and is left in it.
//
// Arithmetic (src/render/shaders/image_common.hlsli): exact integer arithmetic on unorm codes
// and single IEEE float operations in a fixed order (kernels are IEEE-strict, `-Gis`), so each
// pass equals its CPU reference (tests/render/reference/) bit for bit and repeats byte for byte.
// Unorm results are written with Painter's float-to-UNORM rule (parity/semantics/
// resampling.json): the value truncated to n + 4 fractional bits, then the nearest code, ties
// down. 16-bit float results are rounded to the nearest half, ties to even. Float inputs are
// expected in the normal float32 range: a float32 denormal may be flushed to zero by the GPU.

#include "render/backend.h"
#include "render/engine_thread.h"
#include "render/kernel_cache.h"

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace uzp::render {

/// How a texel channel is stored.
enum class TexelEncoding : uint8_t { Unorm8, Unorm16, Float16, Float32 };

/// A format the image passes read and write: `channels` channels of `encoding`.
struct ImagePassFormat {
    uint32_t channels = 0;
    TexelEncoding encoding = TexelEncoding::Unorm8;
};

/// The image-pass layout of `format`: 8- and 16-bit unorm, 16- and 32-bit float, with one, two
/// or four channels (`R8Unorm` ... `RGBA32Float`). Empty for every other format (sRGB-typed,
/// BGRA, three-channel, integer, block-compressed and depth formats): sRGB colour is held as
/// codes in an unorm format and filtered with `ColourMode::Srgb`.
[[nodiscard]] std::optional<ImagePassFormat> ImagePassFormatOf(uz::RHIFormat format);

/// The largest width or height an image pass accepts (D3D12's 2D texture limit).
inline constexpr uint32_t kMaxImagePassDimension = 16384;

/// How the colour channels of a filtered image are interpreted (resampling and mips).
enum class ColourMode : uint8_t {
    /// Every channel is filtered as stored.
    Linear,
    /// 8-bit unorm channels 0-2 hold sRGB codes: decoded to linear (IEC 61966-2-1, a 256-entry
    /// float32 table), filtered in float and encoded to the code whose interval holds the result
    /// (`round(255 encode(v))`, through 255 float32 thresholds). Channel 3 is linear.
    Srgb,
    /// Channels 0-2 of a four-channel image hold a vector (unorm: 2c/M - 1, float: as stored):
    /// filtered, then renormalised (a zero sum gives (0, 0, 1)). Channel 3 is linear.
    Normal,
};

namespace image_pass_detail {

/// `image_common.hlsli`, the include every image-pass kernel declares.
[[nodiscard]] KernelInclude CommonInclude();

/// A kernel of an image pass: `hlsl` with `entryPoint`, the common include and `extra`.
[[nodiscard]] KernelSource Kernel(std::string name, std::string_view hlsl, std::string entryPoint,
                                  std::vector<KernelInclude> extra = {});

/// `source` as `device` runs it: unchanged on DX12 (the descriptor heap); on Vulkan in the
/// fixed-slot model of image_common.hlsli (kernel_bindings.h, decision 313): `UZP_DST_FORMAT` of
/// `output` (the image-pass format of the one storage image it writes) or `UZP_NO_STORAGE_IMAGE`,
/// and `UZP_RW_BUFFERS` when it writes structured buffers, with its entry point named `main`
/// (`VulkanEntryPoint`).
[[nodiscard]] KernelSource ForDevice(const IDevice& device, KernelSource source,
                                     std::optional<uz::RHIFormat> output, bool rwBuffers);

/// `source` with its entry point compiled as `main` (the define `<entry>=main`): the vendored
/// Vulkan backend creates every compute pipeline with the entry point `main`
/// (`vulkan_resources.cpp`), and SPIR-V keeps the HLSL function's name.
[[nodiscard]] KernelSource VulkanEntryPoint(KernelSource source);

/// The bytes of the staging buffer `CopyMip` needs to copy a `width` x `height` image of
/// `format` into a mip other than 0 on `device`: 0 on DX12.
[[nodiscard]] uint64_t CopyStagingBytes(const IDevice& device, ImagePassFormat format,
                                        uint32_t width, uint32_t height);

/// Records the copy of mip 0 of `src` (`width` texels wide, one array slice) into mip `dstMip`
/// of `dst`, which has that size; `src` in `CopySrc`, `dst` in `CopyDst`. DX12:
/// `CopyTextureRegion`. The vendored Vulkan command list does not implement `CopyTextureRegion`
/// (the RHI's default is a no-op): mip 0 is copied with `CopyTexture` (mip 0 to mip 0), another
/// mip through `staging` (`CopyStagingBytes`, copy-source and copy-destination usage, in
/// `Common` before and after).
void CopyMip(const IDevice& device, uz::IRHICommandList& cmd, uz::RHITextureHandle src,
             uz::RHITextureHandle dst, uint32_t dstMip, ImagePassFormat format, uint32_t width,
             uz::RHIBufferHandle staging);

/// `request_failed {backend, reason}` for an invalid pass input.
[[nodiscard]] Unexpected Invalid(const IDevice& device, std::string reason);

/// The description of a live single-subresource-array 2D texture of an image-pass format with
/// at least `usage`; `request_failed` naming `role` otherwise.
Result<uz::RHITextureDesc> RequireTexture(IDevice& device, uz::RHITextureHandle texture,
                                          uz::RHITextureUsage usage, std::string_view role);

/// Whether two handles name the same texture.
[[nodiscard]] constexpr bool SameTexture(uz::RHITextureHandle a, uz::RHITextureHandle b) {
    return a.index == b.index && a.generation == b.generation;
}

/// Thread groups covering `count` items with groups of `size`.
[[nodiscard]] constexpr uint32_t Groups(uint32_t count, uint32_t size) {
    return (count + size - 1) / size;
}

/// The value of `TexelEncoding` in the kernels (`ENC_*` in image_common.hlsli).
[[nodiscard]] constexpr uint32_t EncodingConstant(TexelEncoding encoding) {
    return static_cast<uint32_t>(encoding);
}

/// Scratch textures and buffers of one pass. Destroyed with the object, except after a wait
/// that timed out: the GPU may still use them then, so they are deliberately kept (the engine
/// keeps its device in that case as well, engine_thread.h).
class Scratch {
public:
    explicit Scratch(IDevice& device) : m_device(device) {}
    ~Scratch();
    Scratch(const Scratch&) = delete;
    Scratch& operator=(const Scratch&) = delete;

    Result<uz::RHITextureHandle> Texture(const uz::RHITextureDesc& desc);
    Result<uz::RHIBufferHandle> Buffer(const uz::RHIBufferDesc& desc);
    /// Records the outcome of the pass's wait (keeps the resources after a timeout).
    void Settle(const Result<void>& done);

private:
    IDevice& m_device;
    std::vector<uz::RHITextureHandle> m_textures;
    std::vector<uz::RHIBufferHandle> m_buffers;
    bool m_keep = false;
};

/// One whole-resource state transition of a texture or buffer.
[[nodiscard]] uz::RHIBarrierDesc Transition(uz::RHITextureHandle texture,
                                            uz::RHIResourceState before,
                                            uz::RHIResourceState after);
[[nodiscard]] uz::RHIBarrierDesc Transition(uz::RHIBufferHandle buffer,
                                            uz::RHIResourceState before,
                                            uz::RHIResourceState after);

}  // namespace image_pass_detail

}  // namespace uzp::render
