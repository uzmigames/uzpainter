#include "render/mips.h"

#include "render/resample.h"

#include <array>
#include <cmath>
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

void Dispatch(uz::IRHICommandList& cmd, const ComputeKernel& kernel, const Params& params,
              uint32_t groupsX, uint32_t groupsY) {
    const std::array<uint32_t, 10> constants = {
        params.width,    params.height, params.enc,          params.srcSrv, params.dstUav,
        params.stateUav, params.cutoff, params.level0Texels, params.offset, params.count};
    cmd.SetPipeline(kernel.pipeline);
    cmd.SetRootConstants(kRootConstantsParam, constants.data(),
                         static_cast<uint32_t>(constants.size()));
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

Result<CoverageKernels> LoadCoverageKernels(EngineContext& context) {
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
        Result<ComputeKernel> created =
            context.Kernel(Kernel(std::string("mips_") + entry, Hlsl(), entry));
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
        resample_detail::ResampleDispatch dispatch;
    };
    std::vector<Level> chain(levels);
    chain[0].width = desc->width;
    chain[0].height = desc->height;
    chain[0].filtered = *base;
    uz::IRHIDevice& rhi = device.Rhi();
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
            context, format, previous.width, previous.height, rhi.GetTextureSRVIndex(source),
            level.width, level.height, rhi.GetTextureUAVIndex(level.filtered), filter);
        if (!dispatch) return Unexpected(dispatch.error());
        level.dispatch = *dispatch;
    }

    CoverageKernels kernels;
    uz::RHIBufferHandle state = uz::RHIBufferHandle::Invalid();
    Params params;
    if (coverage) {
        Result<CoverageKernels> loaded = LoadCoverageKernels(context);
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
        params.stateUav = rhi.GetBufferUAVIndex(state);
        params.cutoff = AlphaCutoffCode(options.alphaCutoff, format.encoding);
        params.level0Texels = desc->width * desc->height;
    }

    Result<void> done = context.SubmitAndWait([&](uz::IRHICommandList& cmd) {
        const uz::RHIBarrierDesc toCopy[2] = {
            Transition(texture, State::Common, State::CopySrc),
            Transition(chain[0].filtered, State::Common, State::CopyDst)};
        cmd.ResourceBarrier(toCopy, 2);
        cmd.CopyTextureRegion(texture, 0, 0, chain[0].filtered, 0, 0);
        const uz::RHIBarrierDesc toFilter[2] = {
            Transition(texture, State::CopySrc, State::CopyDst),
            Transition(chain[0].filtered, State::CopyDst, State::ShaderResource)};
        cmd.ResourceBarrier(toFilter, 2);
        const uz::RHIBarrierDesc flush = Transition(state, State::UnorderedAccess,
                                                    State::UnorderedAccess);
        if (coverage) {
            const uz::RHIBarrierDesc toUav = Transition(state, State::Common,
                                                        State::UnorderedAccess);
            cmd.ResourceBarrier(&toUav, 1);
            params.offset = kStateCount0;
            params.count = kStateRows - kStateCount0;
            Dispatch(cmd, kernels.clear, params, Groups(params.count, 64), 1);
            cmd.ResourceBarrier(&flush, 1);
            params.width = chain[0].width;
            params.height = chain[0].height;
            params.srcSrv = rhi.GetTextureSRVIndex(chain[0].filtered);
            Dispatch(cmd, kernels.count, params, Groups(params.width, 8), Groups(params.height, 8));
            cmd.ResourceBarrier(&flush, 1);
        }
        for (uint32_t k = 1; k < levels; ++k) {
            const Level& level = chain[k];
            const uz::RHIBarrierDesc toUav = Transition(level.filtered, State::Common,
                                                        State::UnorderedAccess);
            cmd.ResourceBarrier(&toUav, 1);
            resample_detail::Record(cmd, level.dispatch);
            uz::RHITextureHandle stored = level.filtered;
            if (coverage) {
                const uz::RHIBarrierDesc toRead[2] = {
                    Transition(level.filtered, State::UnorderedAccess, State::ShaderResource),
                    Transition(level.adjusted, State::Common, State::UnorderedAccess)};
                cmd.ResourceBarrier(toRead, 2);
                params.width = level.width;
                params.height = level.height;
                params.srcSrv = rhi.GetTextureSRVIndex(level.filtered);
                params.dstUav = rhi.GetTextureUAVIndex(level.adjusted);
                params.offset = 0;
                params.count = UnormMax(format.encoding) + 1;
                Dispatch(cmd, kernels.clear, params, Groups(params.count, 64), 1);
                cmd.ResourceBarrier(&flush, 1);
                Dispatch(cmd, kernels.histogram, params, Groups(level.width, 8),
                         Groups(level.height, 8));
                cmd.ResourceBarrier(&flush, 1);
                Dispatch(cmd, kernels.select, params, 1, 1);
                cmd.ResourceBarrier(&flush, 1);
                Dispatch(cmd, kernels.rowCount, params, Groups(level.height, 64), 1);
                cmd.ResourceBarrier(&flush, 1);
                Dispatch(cmd, kernels.prefix, params, 1, 1);
                cmd.ResourceBarrier(&flush, 1);
                Dispatch(cmd, kernels.apply, params, Groups(level.height, 64), 1);
                stored = level.adjusted;
            }
            const uz::RHIBarrierDesc toCopySrc = Transition(stored, State::UnorderedAccess,
                                                            State::CopySrc);
            cmd.ResourceBarrier(&toCopySrc, 1);
            cmd.CopyTextureRegion(stored, 0, 0, texture, k, 0);
            const uz::RHIBarrierDesc toNext = Transition(stored, State::CopySrc,
                                                         State::ShaderResource);
            cmd.ResourceBarrier(&toNext, 1);
        }
        const uz::RHIBarrierDesc after = Transition(texture, State::CopyDst, State::Common);
        cmd.ResourceBarrier(&after, 1);
    });
    scratch.Settle(done);
    return done;
}

}  // namespace uzp::render
