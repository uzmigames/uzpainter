#include "render/mips.h"

#include "render/kernel_bindings.h"
#include "render/resample.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <optional>
#include <string_view>
#include <vector>

namespace uzp::render {

namespace {

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wc23-extensions"
constexpr char kMipsHlsl[] = {
#embed "shaders/mips.hlsl"
};
#pragma clang diagnostic pop

using namespace image_pass_detail;
using State = uz::RHIResourceState;

constexpr std::string_view Hlsl() { return {kMipsHlsl, sizeof(kMipsHlsl)}; }

/// State-buffer layout of mips.hlsl: 65536 histogram bins, the selection words from
/// `kStateCount0`, then one word per row from `kStateRows`.
constexpr uint32_t kStateCount0 = 65536;
constexpr uint32_t kStateRows = 65544;

/// Root constants of mips.hlsl (`Params`).
struct Params {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t enc = 0;
    uint32_t srcSrv = 0;
    uint32_t dstUav = 0;
    uint32_t stateUav = 0;
    uint32_t cutoff = 0;
    uint32_t level0Texels = 0;
    uint32_t offset = 0;
    uint32_t count = 0;
};

/// Records one coverage dispatch binding the state buffer, `source` (sampled) when valid and
/// `destination` (written) when valid. One of each class never runs out of slots.
void Dispatch(uz::IRHICommandList& cmd, IDevice& device, const ComputeKernel& kernel,
              Params params, uz::RHIBufferHandle state, uz::RHITextureHandle source,
              uz::RHITextureHandle destination, uint32_t groupsX, uint32_t groupsY) {
    KernelBindings bindings(device);
    params.stateUav = bindings.RwBuffer(state);
    if (source.IsValid()) params.srcSrv = bindings.Texture(source);
    if (destination.IsValid()) params.dstUav = bindings.Output(destination);
    const std::array<uint32_t, 10> constants = {
        params.width,    params.height, params.enc,          params.srcSrv, params.dstUav,
        params.stateUav, params.cutoff, params.level0Texels, params.offset, params.count};
    cmd.SetPipeline(kernel.pipeline);
    bindings.Record(cmd, constants);
    cmd.Dispatch(groupsX, groupsY, 1);
}

struct CoverageKernels {
    ComputeKernel clear;
    ComputeKernel count;
    ComputeKernel histogram;
    ComputeKernel select;
    ComputeKernel rowCount;
    ComputeKernel prefix;
    ComputeKernel apply;
};

/// The dispatches of one level: its filter, and with alpha coverage clear, histogram, select,
/// row count, prefix and apply.
constexpr uint32_t kCoverageDispatchesPerLevel = 7;
/// The coverage dispatches before the first level: clear and count.
constexpr uint32_t kCoveragePrologueDispatches = 2;

Result<CoverageKernels> LoadCoverageKernels(EngineContext& context, uz::RHIFormat format) {
    CoverageKernels kernels;
    const std::array<std::pair<const char*, ComputeKernel*>, 7> entries = {{
        {"ClearMain", &kernels.clear},
        {"CountMain", &kernels.count},
        {"HistogramMain", &kernels.histogram},
        {"SelectMain", &kernels.select},
        {"RowCountMain", &kernels.rowCount},
        {"PrefixMain", &kernels.prefix},
        {"ApplyMain", &kernels.apply},
    }};
    for (const auto& [entry, kernel] : entries) {
        // Only ApplyMain writes a texture (the adjusted level).
        const std::optional<uz::RHIFormat> output =
            kernel == &kernels.apply ? std::optional<uz::RHIFormat>(format) : std::nullopt;
        Result<ComputeKernel> created = context.Kernel(ForDevice(
            context.Device(), Kernel(std::string("mips_") + entry, Hlsl(), entry), output, true));
        if (!created) return Unexpected(created.error());
        *kernel = *created;
    }
    return kernels;
}

uint32_t UnormMax(TexelEncoding encoding) {
    return encoding == TexelEncoding::Unorm8 ? 255u : 65535u;
}

}  // namespace

uint32_t AlphaCutoffCode(float cutoff, TexelEncoding encoding) {
    const uint32_t m = UnormMax(encoding);
    const double code = std::ceil(static_cast<double>(cutoff) * m);
    if (!(code >= 1.0)) return 1;
    return code >= m ? m : static_cast<uint32_t>(code);
}

Result<void> GenerateMips(EngineContext& context, uz::RHITextureHandle texture,
                          const MipOptions& options) {
    IDevice& device = context.Device();
    using Usage = uz::RHITextureUsage;
    Result<uz::RHITextureDesc> desc =
        RequireTexture(device, texture, Usage::CopySrc | Usage::CopyDst, "mip chain");
    if (!desc) return Unexpected(desc.error());
    const ImagePassFormat format = *ImagePassFormatOf(desc->format);
    Result<void> mode = resample_detail::CheckColourMode(device, format, options.colour);
    if (!mode) return mode;
    const bool coverage = options.preserveAlphaCoverage;
    const bool unorm =
        format.encoding == TexelEncoding::Unorm8 || format.encoding == TexelEncoding::Unorm16;
    if (coverage && (!unorm || format.channels != 4)) {
        return Invalid(device, "alpha-coverage preservation needs a four-channel unorm format");
    }
    if (coverage && !(options.alphaCutoff > 0.0f && options.alphaCutoff <= 1.0f)) {
        return Invalid(device, "the alpha cutoff must lie in (0, 1]");
    }
    const uint32_t levels = desc->mipLevels;
    if (levels <= 1) return {};

    Scratch scratch(device);
    auto levelTexture = [&](uint32_t width, uint32_t height,
                            const char* name) -> Result<uz::RHITextureHandle> {
        uz::RHITextureDesc level;
        level.width = width;
        level.height = height;
        level.format = desc->format;
        level.usage = Usage::ShaderResource | Usage::UnorderedAccess | Usage::CopySrc |
                      Usage::CopyDst;
        level.debugName = name;
        return scratch.Texture(level);
    };
    Result<uz::RHITextureHandle> base = levelTexture(desc->width, desc->height, "mip_level0");
    if (!base) return Unexpected(base.error());
    struct Level {
        uint32_t width = 0;
        uint32_t height = 0;
        uz::RHITextureHandle filtered = uz::RHITextureHandle::Invalid();
        uz::RHITextureHandle adjusted = uz::RHITextureHandle::Invalid();
        std::optional<resample_detail::ResampleDispatch> dispatch;
    };
    std::vector<Level> chain(levels);
    chain[0].width = desc->width;
    chain[0].height = desc->height;
    chain[0].filtered = *base;
    const ResampleOptions filter{ResampleFilter::Box, ResampleWrap::Clamp, options.colour};
    for (uint32_t k = 1; k < levels; ++k) {
        Level& level = chain[k];
        level.width = MipExtent(desc->width, k);
        level.height = MipExtent(desc->height, k);
        Result<uz::RHITextureHandle> filtered =
            levelTexture(level.width, level.height, "mip_filtered");
        if (!filtered) return Unexpected(filtered.error());
        level.filtered = *filtered;
        if (coverage) {
            Result<uz::RHITextureHandle> adjusted =
                levelTexture(level.width, level.height, "mip_coverage");
            if (!adjusted) return Unexpected(adjusted.error());
            level.adjusted = *adjusted;
        }
        const Level& previous = chain[k - 1];
        const uz::RHITextureHandle source = coverage && k > 1 ? previous.adjusted
                                                              : previous.filtered;
        Result<resample_detail::ResampleDispatch> dispatch = resample_detail::Prepare(
            context, desc->format, source, previous.width, previous.height, level.filtered,
            level.width, level.height, filter);
        if (!dispatch) return Unexpected(dispatch.error());
        level.dispatch = std::move(*dispatch);
    }

    // Vulkan copies a level into its mip through a staging buffer (image_pass.h `CopyMip`), sized
    // for the largest, level 1.
    uz::RHIBufferHandle staging = uz::RHIBufferHandle::Invalid();
    if (const uint64_t bytes = CopyStagingBytes(device, format, chain[1].width, chain[1].height);
        bytes > 0) {
        uz::RHIBufferDesc stagingDesc;
        stagingDesc.sizeBytes = bytes;
        stagingDesc.usage = uz::RHIBufferUsage::CopySrc | uz::RHIBufferUsage::CopyDst;
        stagingDesc.debugName = "mip_copy_staging";
        Result<uz::RHIBufferHandle> created = scratch.Buffer(stagingDesc);
        if (!created) return Unexpected(created.error());
        staging = *created;
    }

    CoverageKernels kernels;
    uz::RHIBufferHandle state = uz::RHIBufferHandle::Invalid();
    Params params;
    if (coverage) {
        Result<CoverageKernels> loaded = LoadCoverageKernels(context, desc->format);
        if (!loaded) return Unexpected(loaded.error());
        kernels = *loaded;
        uz::RHIBufferDesc stateDesc;
        stateDesc.sizeBytes =
            (uint64_t{kStateRows} + MipExtent(desc->height, 1)) * sizeof(uint32_t);
        stateDesc.stride = sizeof(uint32_t);
        stateDesc.usage = uz::RHIBufferUsage::UnorderedAccess;
        stateDesc.debugName = "mip_coverage_state";
        Result<uz::RHIBufferHandle> created = scratch.Buffer(stateDesc);
        if (!created) return Unexpected(created.error());
        state = *created;
        params.enc = EncodingConstant(format.encoding);
        params.cutoff = AlphaCutoffCode(options.alphaCutoff, format.encoding);
        params.level0Texels = desc->width * desc->height;
    }
    const uz::RHITextureHandle none = uz::RHITextureHandle::Invalid();
    const uz::RHIBarrierDesc flush = Transition(state, State::UnorderedAccess,
                                                State::UnorderedAccess);

    // Level 0 copied into the first scratch level; with alpha coverage the state cleared and
    // level 0's covered texels counted.
    const auto prologue = [&](uz::IRHICommandList& cmd) {
        const uz::RHIBarrierDesc toCopy[2] = {
            Transition(texture, State::Common, State::CopySrc),
            Transition(chain[0].filtered, State::Common, State::CopyDst)};
        cmd.ResourceBarrier(toCopy, 2);
        CopyMip(device, cmd, texture, chain[0].filtered, 0, format, desc->width, uz::RHIBufferHandle::Invalid());
        const uz::RHIBarrierDesc toFilter[2] = {
            Transition(texture, State::CopySrc, State::CopyDst),
            Transition(chain[0].filtered, State::CopyDst, State::ShaderResource)};
        cmd.ResourceBarrier(toFilter, 2);
        if (!coverage) return;
        const uz::RHIBarrierDesc toUav = Transition(state, State::Common, State::UnorderedAccess);
        cmd.ResourceBarrier(&toUav, 1);
        Params clear = params;
        clear.offset = kStateCount0;
        clear.count = kStateRows - kStateCount0;
        Dispatch(cmd, device, kernels.clear, clear, state, none, none, Groups(clear.count, 64), 1);
        cmd.ResourceBarrier(&flush, 1);
        Params count = params;
        count.width = chain[0].width;
        count.height = chain[0].height;
        Dispatch(cmd, device, kernels.count, count, state, chain[0].filtered, none,
                 Groups(count.width, 8), Groups(count.height, 8));
        cmd.ResourceBarrier(&flush, 1);
    };
    // Level k filtered from the stored level k - 1, adjusted for alpha coverage, copied into
    // mip k of the texture and left readable for level k + 1.
    const auto recordLevel = [&](uz::IRHICommandList& cmd, uint32_t k) {
        const Level& level = chain[k];
        const uz::RHIBarrierDesc toUav = Transition(level.filtered, State::Common,
                                                    State::UnorderedAccess);
        cmd.ResourceBarrier(&toUav, 1);
        resample_detail::Record(cmd, *level.dispatch);
        uz::RHITextureHandle stored = level.filtered;
        if (coverage) {
            const uz::RHIBarrierDesc toRead[2] = {
                Transition(level.filtered, State::UnorderedAccess, State::ShaderResource),
                Transition(level.adjusted, State::Common, State::UnorderedAccess)};
            cmd.ResourceBarrier(toRead, 2);
            Params p = params;
            p.width = level.width;
            p.height = level.height;
            p.offset = 0;
            p.count = UnormMax(format.encoding) + 1;
            Dispatch(cmd, device, kernels.clear, p, state, none, none, Groups(p.count, 64), 1);
            cmd.ResourceBarrier(&flush, 1);
            Dispatch(cmd, device, kernels.histogram, p, state, level.filtered, none,
                     Groups(level.width, 8), Groups(level.height, 8));
            cmd.ResourceBarrier(&flush, 1);
            Dispatch(cmd, device, kernels.select, p, state, none, none, 1, 1);
            cmd.ResourceBarrier(&flush, 1);
            Dispatch(cmd, device, kernels.rowCount, p, state, level.filtered, none,
                     Groups(level.height, 64), 1);
            cmd.ResourceBarrier(&flush, 1);
            Dispatch(cmd, device, kernels.prefix, p, state, none, none, 1, 1);
            cmd.ResourceBarrier(&flush, 1);
            Dispatch(cmd, device, kernels.apply, p, state, level.filtered, level.adjusted,
                     Groups(level.height, 64), 1);
            stored = level.adjusted;
        }
        const uz::RHIBarrierDesc toCopySrc = Transition(stored, State::UnorderedAccess,
                                                        State::CopySrc);
        cmd.ResourceBarrier(&toCopySrc, 1);
        CopyMip(device, cmd, stored, texture, k, format, level.width, staging);
        const uz::RHIBarrierDesc toNext = Transition(stored, State::CopySrc,
                                                     State::ShaderResource);
        cmd.ResourceBarrier(&toNext, 1);
    };

    // One submission on DX12. A device that bounds the dispatches of a submission (Vulkan's
    // descriptor snapshots, backend.h `MaxDispatchesPerSubmission`) gets consecutive levels in
    // later submissions, in queue order; every resource keeps its state between them.
    const uint64_t limit = device.MaxDispatchesPerSubmission();
    const uint32_t perLevel = coverage ? kCoverageDispatchesPerLevel : 1;
    Result<void> done;
    for (uint32_t next = 1; next < levels;) {
        const bool first = next == 1;
        uint64_t used = first && coverage ? kCoveragePrologueDispatches : 0;
        uint32_t end = next;
        do {
            used += perLevel;
            ++end;
        } while (end < levels && used + perLevel <= limit);
        const bool last = end == levels;
        done = context.SubmitAndWait([&](uz::IRHICommandList& cmd) {
            if (first) prologue(cmd);
            for (uint32_t k = next; k < end; ++k) recordLevel(cmd, k);
            if (last) {
                const uz::RHIBarrierDesc after = Transition(texture, State::CopyDst,
                                                            State::Common);
                cmd.ResourceBarrier(&after, 1);
            }
        });
        if (!done) break;
        next = end;
    }
    scratch.Settle(done);
    return done;
}

}  // namespace uzp::render
