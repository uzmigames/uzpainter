#pragma once

// The `HlslBackend` host (docs/architecture/05-procedural-content.md §2, §3): UzPainter's own
// procedural families, registered per pinned asset, evaluated as generated HLSL compute kernels
// compiled through the render core (DXIL or SPIR-V, IEEE-strict `-Gis`, `precise` arithmetic in
// the primitive library) and cached by content hash (render/kernel_cache.h: XXH64 over source,
// includes, defines, target and compiler; the engine keeps one pipeline per key).
//
// A family is one or more kernel passes. Each pass's HLSL body defines
// `float4 ProcTexel(int2 texel)` over the generated wrapper (`GenerateKernel`), which gives it:
//
// - `ProcParam(i)`: word i of the pass's parameter block (a structured buffer);
// - `ProcInput(slot, p)` and `ProcInputSize(slot)`: up to four input slots, each a request
//   image input or the output of an earlier pass, as RGBA float32 textures (missing channels
//   read 0);
// - `g_resolution` (the output resolution) and `g_seed` (the request's seed);
// - the primitive library (`proc_primitives.hlsli`, the mirror of primitives.h).
//
// Every pass but the last writes the whole output texture; the last writes the request's tile.
// `texel` is the texel's position in the whole texture. The host writes float32 only: a family
// whose domain certifies another output format is refused at registration (quantisation rules
// belong to the families that are fitted to them).
//
// The seam (seam.h) selects this backend only for an asset whose parity status is `exact`, and
// only inside its certified domain. `EvaluateCandidate` evaluates a registered family inside its
// domain whatever its status: a diagnostic lane for certification and tests, which the seam
// never selects. `EvaluateReference` is the CPU reference lane of the same families (each
// family's `Reference`, bit for bit the kernel's texels).

#include "procedural/seam.h"

#include "render/engine_thread.h"
#include "render/kernel_cache.h"

#include <expected>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace uzp::procedural {

/// An input slot of a pass: a request image input by name, or the output of an earlier pass.
struct PassInput {
    std::string requestInput;  ///< Used when `pass` is negative.
    int32_t pass = -1;
};

struct KernelPass {
    std::string name;  ///< Diagnostic name of the kernel.
    /// HLSL defining `float4 ProcTexel(int2 texel)`.
    std::string body;
    std::vector<uint32_t> params;
    std::vector<PassInput> inputs;  ///< At most `kMaxPassInputs`.
};

inline constexpr size_t kMaxPassInputs = 4;

/// What a family declares when it is registered.
struct FamilyRecord {
    core::AssetUrl asset;
    CertifiedDomain domain;
    ParityStatus status;
    /// The provenance record (public sources, author, corpus ids; 05 §3).
    std::string provenance;
};

class IHlslFamily {
public:
    virtual ~IHlslFamily() = default;
    [[nodiscard]] virtual const FamilyRecord& Record() const = 0;
    /// The kernel passes of a request inside the domain.
    [[nodiscard]] virtual std::vector<KernelPass> Plan(const ProceduralRequest& request) const = 0;
    /// The CPU reference of the same request: the kernels' texels bit for bit.
    [[nodiscard]] virtual Raster Reference(const ProceduralRequest& request,
                                           const InputImages& inputs) const = 0;
};

/// The kernel of one pass: the wrapper, the body and the primitive library's includes.
[[nodiscard]] render::KernelSource GenerateKernel(const KernelPass& pass);

/// Why `inputs` cannot feed `request`: the first image input it lacks, or whose raster does not
/// have the declared resolution and channels; empty when every input is valid. Evaluation then
/// fails loudly (`request_failed`); the input's bytes are hashed by whoever decoded them.
[[nodiscard]] std::optional<std::string> CheckInputs(const ProceduralRequest& request,
                                                     const InputImages& inputs);

class HlslBackend final : public IProceduralBackend {
public:
    /// `engine` may be null (no GPU): `Evaluate` then fails with `gpu_backend_unavailable`, and
    /// the CPU reference lane still works.
    explicit HlslBackend(render::Engine* engine) : m_engine(engine) {}

    /// Registers a family under its pinned asset. Refused (with the reason) for an asset that is
    /// already registered, or a domain whose output is not float32 with 1 to 4 channels.
    /// Families are registered before any evaluation.
    std::expected<void, std::string> Register(std::shared_ptr<const IHlslFamily> family);

    [[nodiscard]] std::string_view Name() const override { return "hlsl"; }
    [[nodiscard]] ParityStatus Status(const core::AssetUrl& asset) const override;
    [[nodiscard]] bool CanEvaluate(const ProceduralRequest& request) const override;
    [[nodiscard]] std::optional<UnsupportedProcedural> Refusal(
        const ProceduralRequest& request) const override;
    RasterFuture Evaluate(const ProceduralRequest& request, const InputImages& inputs) override;

    /// The diagnostic lane: a registered family inside its domain, whatever its status.
    RasterFuture EvaluateCandidate(const ProceduralRequest& request, const InputImages& inputs);
    /// The CPU reference lane: a registered family inside its domain, whatever its status;
    /// `request_failed` with the refusal or the invalid input otherwise.
    render::Result<Raster> EvaluateReference(const ProceduralRequest& request,
                                             const InputImages& inputs) const;

    /// The kernels a request compiles, pass by pass (their `render::KernelKey` is the cache key).
    std::expected<std::vector<render::KernelSource>, UnsupportedProcedural> Kernels(
        const ProceduralRequest& request) const;

private:
    const IHlslFamily* Find(const core::AssetUrl& asset) const;
    /// The refusal of a request for the candidate lanes: unknown asset or outside the domain.
    std::optional<UnsupportedProcedural> CandidateRefusal(const ProceduralRequest& request) const;
    RasterFuture Run(const ProceduralRequest& request, const InputImages& inputs);

    render::Engine* m_engine;
    std::map<std::string, std::shared_ptr<const IHlslFamily>> m_families;
};

}  // namespace uzp::procedural
