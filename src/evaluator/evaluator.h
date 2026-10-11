#pragma once

// The compositor's entry points (docs/architecture/04-layer-stack-and-compositing.md §7):
// `Evaluator` evaluates channels of revision snapshots on the engine thread with the GPU tile
// store and a tile cache bounded by the admission budget; `CpuEvaluator` is the same evaluation
// on the CPU store (the reference, and the path of a machine without a GPU).

#include "evaluator/admission.h"
#include "evaluator/cpu_store.h"
#include "evaluator/diagnostics.h"
#include "evaluator/evaluate.h"
#include "evaluator/height_to_normal.h"
#include "evaluator/resources.h"
#include "evaluator/templates.h"
#include "render/engine_thread.h"

#include <future>
#include <memory>
#include <optional>
#include <string>

#include "uzp_core/document/document.h"
#include "uzp_core/types/project.h"

namespace uzp::evaluator {

struct EvaluateRequest {
    core::Id textureSet = core::kNoId;
    core::Id stack = core::kNoId;
    core::ChannelType channel = core::ChannelType::BaseColor;
    /// The template the project was created from (its base values).
    std::string templateId{kDefaultTemplateId};
    /// The bytes of bitmap sources; may be null when the stack has none.
    std::shared_ptr<const IResourceProvider> resources;
    /// The rasters of `Mesh` geometry masks (geometry_mask.h); may be null when the stack has none.
    std::shared_ptr<const IGeometryMaskProvider> geometry;
};

struct EvaluatorOptions {
    /// Replaces the limits derived from the engine's capability report (tests).
    std::optional<AdmissionLimits> limits;
};

class Evaluator {
public:
    Evaluator(render::Engine& engine, std::shared_ptr<const TemplateLibrary> templates,
              EvaluatorOptions options = {});
    /// `Shutdown()`.
    ~Evaluator();
    Evaluator(const Evaluator&) = delete;
    Evaluator& operator=(const Evaluator&) = delete;

    /// The admission limits in force (the options' or the engine's); the engine's device error
    /// when there is no device.
    [[nodiscard]] render::Result<AdmissionLimits> Limits() const;

    /// Admits texture set `set` of `project` against the limits (03 §2: creation above the
    /// budget fails explicitly with `evaluator:texture_set_over_budget`).
    [[nodiscard]] render::Result<void> AdmitTextureSet(const core::Project& project,
                                                       core::Id set) const;

    /// Evaluates one channel of one stack of `snapshot` on the engine thread.
    [[nodiscard]] std::future<render::Result<ChannelResult>> Evaluate(core::Snapshot snapshot,
                                                                      EvaluateRequest request);

    /// Evaluates a virtual normal map or the geometry-only pass-through of `snapshot` on the
    /// engine thread (height_to_normal.h), tagged with the snapshot's revision.
    [[nodiscard]] std::future<render::Result<VirtualNormalResult>> EvaluateNormal(
        core::Snapshot snapshot, VirtualNormalRequest request);

    /// Evaluates the named diagnostic of `snapshot` on the engine thread (diagnostics.h): every
    /// evaluation it needs reads that one revision.
    [[nodiscard]] std::future<render::Result<DiagnosticOutput>> Diagnose(core::Snapshot snapshot,
                                                                         DiagnosticSource source,
                                                                         DiagnosticRequest request);

    /// The material views of layer `material` of `snapshot` on the engine thread (diagnostics.h).
    [[nodiscard]] std::future<render::Result<MaterialViews>> EvaluateMaterialViews(core::Snapshot snapshot,
                                                                                   core::Id material,
                                                                                   DiagnosticRequest request);

    /// The cache statistics as of the requests run so far.
    [[nodiscard]] std::future<render::Result<CacheStats>> Stats();

    /// Releases the GPU tiles on the engine thread; later requests fail with `engine_stopped`
    /// or an evaluator error. Idempotent.
    void Shutdown();

private:
    struct State;
    render::Result<State*> StateFor(render::EngineContext& context);

    render::Engine& m_engine;
    std::shared_ptr<const TemplateLibrary> m_templates;
    EvaluatorOptions m_options;
    std::unique_ptr<State> m_state;  ///< Created and used on the engine thread.
    bool m_shutdown = false;
};

class CpuEvaluator {
public:
    CpuEvaluator(std::shared_ptr<const TemplateLibrary> templates, AdmissionLimits limits);

    [[nodiscard]] render::Result<void> AdmitTextureSet(const core::Project& project,
                                                       core::Id set) const;
    [[nodiscard]] render::Result<ChannelResult> Evaluate(const core::Project& project,
                                                         const EvaluateRequest& request);
    /// A virtual normal map or the geometry-only pass-through of revision `revision`.
    [[nodiscard]] render::Result<VirtualNormalResult> EvaluateNormal(const core::Project& project,
                                                                     std::int64_t revision,
                                                                     const VirtualNormalRequest& request);

    /// The named diagnostic of revision `revision` (diagnostics.h).
    [[nodiscard]] render::Result<DiagnosticOutput> Diagnose(const core::Project& project, std::int64_t revision,
                                                            const DiagnosticSource& source,
                                                            const DiagnosticRequest& request);
    /// The material views of layer `material` of revision `revision` (diagnostics.h).
    [[nodiscard]] render::Result<MaterialViews> EvaluateMaterialViews(const core::Project& project,
                                                                      std::int64_t revision, core::Id material,
                                                                      const DiagnosticRequest& request);

    [[nodiscard]] CpuTileStore& store() { return m_store; }
    [[nodiscard]] TileCache& cache() { return m_cache; }
    [[nodiscard]] const AdmissionLimits& limits() const { return m_limits; }

private:
    std::shared_ptr<const TemplateLibrary> m_templates;
    AdmissionLimits m_limits;
    CpuTileStore m_store;
    TileCache m_cache;
};

/// Evaluates `request` against `project` on `store` with `cache` (the shared body of both
/// evaluators): builds the DAG, admits the texture set, evaluates every tile.
[[nodiscard]] render::Result<ChannelResult> EvaluateOn(const core::Project& project,
                                                       const EvaluateRequest& request,
                                                       const TemplateLibrary& templates,
                                                       ITileStore& store, TileCache& cache);

}  // namespace uzp::evaluator
