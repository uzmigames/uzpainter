#include "render/dilation.h"

#include "render/image_pass.h"
#include "render/kernel_bindings.h"

#include <algorithm>
#include <array>
#include <string_view>
#include <utility>

namespace uzp::render {

namespace {

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wc23-extensions"
constexpr char kDilationHlsl[] = {
#embed "shaders/dilation_jfa.hlsl"
};
#pragma clang diagnostic pop

using namespace image_pass_detail;
using State = uz::RHIResourceState;

constexpr std::string_view Hlsl() { return {kDilationHlsl, sizeof(kDilationHlsl)}; }

/// Root constants of dilation_jfa.hlsl (`Params`).
struct Params {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t step = 0;
    uint32_t srcSeeds = 0;
    uint32_t dstSeeds = 0;
    uint32_t coverageSrv = 0;
    uint32_t colourSrv = 0;
    uint32_t outputUav = 0;
    uint32_t maxDistanceSq = 0;
};

/// One dispatch: its kernel, root constants and the names of what it binds (kernel_bindings.h).
struct Pass {
    const ComputeKernel* kernel = nullptr;
    Params params;
    KernelBindings bindings;
};

void Dispatch(uz::IRHICommandList& cmd, const Pass& pass) {
    const Params& params = pass.params;
    const std::array<uint32_t, 9> constants = {
        params.width,       params.height,    params.step,      params.srcSeeds,     params.dstSeeds,
        params.coverageSrv, params.colourSrv, params.outputUav, params.maxDistanceSq};
    cmd.SetPipeline(pass.kernel->pipeline);
    pass.bindings.Record(cmd, constants);
    cmd.Dispatch(Groups(params.width, 8), Groups(params.height, 8), 1);
}

}  // namespace

std::vector<uint32_t> JumpFloodSteps(uint32_t width, uint32_t height, uint32_t maxDistance) {
    const uint32_t extent = std::max(width, height);
    const uint32_t reach = std::min(maxDistance, extent == 0 ? 0u : extent - 1);
    std::vector<uint32_t> steps;
    if (reach == 0) return steps;
    uint32_t n = 1;
    while (n <= reach) n *= 2;
    steps.push_back(1);
    for (uint32_t step = n / 2; step >= 1; step /= 2) steps.push_back(step);
    return steps;
}

Result<void> Dilate(EngineContext& context, const DilationDesc& desc) {
    IDevice& device = context.Device();
    using Usage = uz::RHITextureUsage;
    Result<uz::RHITextureDesc> colour = RequireTexture(
        device, desc.colour, Usage::ShaderResource | Usage::CopySrc, "colour");
    if (!colour) return Unexpected(colour.error());
    Result<uz::RHITextureDesc> coverage =
        RequireTexture(device, desc.coverage, Usage::ShaderResource, "coverage");
    if (!coverage) return Unexpected(coverage.error());
    Result<uz::RHITextureDesc> output = RequireTexture(
        device, desc.output, Usage::UnorderedAccess | Usage::CopyDst, "output");
    if (!output) return Unexpected(output.error());
    if (SameTexture(desc.colour, desc.coverage) || SameTexture(desc.colour, desc.output) ||
        SameTexture(desc.coverage, desc.output)) {
        return Invalid(device, "the colour, coverage and output textures must be distinct");
    }
    if (coverage->width != colour->width || coverage->height != colour->height ||
        output->width != colour->width || output->height != colour->height) {
        return Invalid(device, "the coverage and output textures must have the colour's size");
    }
    if (output->format != colour->format) {
        return Invalid(device, "the output format differs from the colour format");
    }

    const ImagePassFormat format = *ImagePassFormatOf(colour->format);
    const uint32_t width = colour->width;
    const uint32_t height = colour->height;
    const std::vector<uint32_t> steps = JumpFloodSteps(width, height, desc.maxDistance);
    if (steps.empty()) {
        return context.SubmitAndWait([&](uz::IRHICommandList& cmd) {
            const uz::RHIBarrierDesc before[2] = {
                Transition(desc.colour, State::Common, State::CopySrc),
                Transition(desc.output, State::Common, State::CopyDst)};
            cmd.ResourceBarrier(before, 2);
            CopyMip(device, cmd, desc.colour, desc.output, 0, format, colour->width, uz::RHIBufferHandle::Invalid());
            const uz::RHIBarrierDesc after[2] = {
                Transition(desc.colour, State::CopySrc, State::Common),
                Transition(desc.output, State::CopyDst, State::Common)};
            cmd.ResourceBarrier(after, 2);
        });
    }

    Result<ComputeKernel> seedKernel = context.Kernel(
        ForDevice(device, Kernel("dilation_seed", Hlsl(), "SeedMain"), std::nullopt, true));
    if (!seedKernel) return Unexpected(seedKernel.error());
    Result<ComputeKernel> stepKernel = context.Kernel(
        ForDevice(device, Kernel("dilation_step", Hlsl(), "StepMain"), std::nullopt, true));
    if (!stepKernel) return Unexpected(stepKernel.error());
    Result<ComputeKernel> resolveKernel = context.Kernel(ForDevice(
        device, Kernel("dilation_resolve", Hlsl(), "ResolveMain"), output->format, true));
    if (!resolveKernel) return Unexpected(resolveKernel.error());

    Scratch scratch(device);
    uz::RHIBufferDesc seedDesc;
    seedDesc.sizeBytes = uint64_t{width} * height * sizeof(uint32_t);
    seedDesc.stride = sizeof(uint32_t);
    seedDesc.usage = uz::RHIBufferUsage::UnorderedAccess;
    seedDesc.debugName = "dilation_seeds";
    std::array<uz::RHIBufferHandle, 2> seeds{};
    for (uz::RHIBufferHandle& buffer : seeds) {
        Result<uz::RHIBufferHandle> created = scratch.Buffer(seedDesc);
        if (!created) return Unexpected(created.error());
        buffer = *created;
    }
    const uint64_t limitSq = uint64_t{desc.maxDistance} * desc.maxDistance;

    // The dispatches in order: the seeds into buffer 0, one step per jump length alternating the
    // buffers, the resolve from the last one written.
    std::vector<Pass> passes;
    const auto add = [&](const ComputeKernel& kernel) -> Pass& {
        Pass& pass = passes.emplace_back(Pass{&kernel, Params{}, KernelBindings(device)});
        pass.params.width = width;
        pass.params.height = height;
        pass.params.maxDistanceSq =
            static_cast<uint32_t>(std::min<uint64_t>(limitSq, 0xFFFFFFFFull));
        return pass;
    };
    uint32_t current = 0;
    {
        Pass& seed = add(*seedKernel);
        seed.params.dstSeeds = seed.bindings.RwBuffer(seeds[current]);
        seed.params.coverageSrv = seed.bindings.Texture(desc.coverage);
    }
    for (const uint32_t step : steps) {
        Pass& pass = add(*stepKernel);
        pass.params.step = step;
        pass.params.srcSeeds = pass.bindings.RwBuffer(seeds[current]);
        pass.params.dstSeeds = pass.bindings.RwBuffer(seeds[1 - current]);
        current = 1 - current;
    }
    {
        Pass& resolve = add(*resolveKernel);
        resolve.params.srcSeeds = resolve.bindings.RwBuffer(seeds[current]);
        resolve.params.colourSrv = resolve.bindings.Texture(desc.colour);
        resolve.params.outputUav = resolve.bindings.Output(desc.output);
    }
    for (const Pass& pass : passes) {
        if (Result<void> named = pass.bindings.Validate(); !named) return named;
    }

    Result<void> done = context.SubmitAndWait([&](uz::IRHICommandList& cmd) {
        // The output starts as a copy of the colour: covered and out-of-reach texels keep it.
        const uz::RHIBarrierDesc toCopy[2] = {
            Transition(desc.colour, State::Common, State::CopySrc),
            Transition(desc.output, State::Common, State::CopyDst)};
        cmd.ResourceBarrier(toCopy, 2);
        CopyMip(device, cmd, desc.colour, desc.output, 0, format, width, uz::RHIBufferHandle::Invalid());
        const uz::RHIBarrierDesc toCompute[5] = {
            Transition(desc.colour, State::CopySrc, State::ShaderResource),
            Transition(desc.coverage, State::Common, State::ShaderResource),
            Transition(desc.output, State::CopyDst, State::UnorderedAccess),
            Transition(seeds[0], State::Common, State::UnorderedAccess),
            Transition(seeds[1], State::Common, State::UnorderedAccess)};
        cmd.ResourceBarrier(toCompute, 5);
        const uz::RHIBarrierDesc flush[2] = {
            Transition(seeds[0], State::UnorderedAccess, State::UnorderedAccess),
            Transition(seeds[1], State::UnorderedAccess, State::UnorderedAccess)};

        for (size_t i = 0; i < passes.size(); ++i) {
            if (i > 0) cmd.ResourceBarrier(flush, 2);
            Dispatch(cmd, passes[i]);
        }

        const uz::RHIBarrierDesc after[5] = {
            Transition(desc.colour, State::ShaderResource, State::Common),
            Transition(desc.coverage, State::ShaderResource, State::Common),
            Transition(desc.output, State::UnorderedAccess, State::Common),
            Transition(seeds[0], State::UnorderedAccess, State::Common),
            Transition(seeds[1], State::UnorderedAccess, State::Common)};
        cmd.ResourceBarrier(after, 5);
    });
    scratch.Settle(done);
    return done;
}

}  // namespace uzp::render
