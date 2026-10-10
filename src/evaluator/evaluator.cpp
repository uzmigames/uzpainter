#include "evaluator/evaluator.h"

#include <string>

#include "evaluator/dag.h"
#include "evaluator/error.h"
#include "evaluator/gpu_store.h"

namespace uzp::evaluator {

namespace {

const core::TextureSet* FindSet(const core::Project& project, core::Id set) {
    for (const core::TextureSet& candidate : project.texture_sets) {
        if (candidate.id == set) return &candidate;
    }
    return nullptr;
}

render::Result<void> Admit(const core::Project& project, core::Id set, const AdmissionLimits& limits) {
    const core::TextureSet* found = FindSet(project, set);
    if (found == nullptr) {
        return EvalFail(EvalErrorKind::NotFound,
                        "texture set " + std::to_string(set) + " is not in the project");
    }
    return CheckTextureSet(limits, *found);
}

}  // namespace

render::Result<ChannelResult> EvaluateOn(const core::Project& project, const EvaluateRequest& request,
                                         const TemplateLibrary& templates, ITileStore& store,
                                         TileCache& cache) {
    render::Result<void> admitted = Admit(project, request.textureSet, cache.limits());
    if (!admitted) return render::Unexpected(admitted.error());
    render::Result<ChannelDag> dag = BuildDag(project, request.textureSet, request.stack,
                                              request.channel, templates, request.templateId);
    if (!dag) return render::Unexpected(dag.error());
    EvalEnvironment env{store, cache, request.resources.get()};
    return EvaluateChannel(*dag, env);
}

// ── Evaluator (GPU, engine thread) ───────────────────────────────────────────

struct Evaluator::State {
    State(render::IDevice& device, AdmissionLimits limits) : store(device), cache(limits) {}
    GpuTileStore store;
    TileCache cache;
};

Evaluator::Evaluator(render::Engine& engine, std::shared_ptr<const TemplateLibrary> templates,
                     EvaluatorOptions options)
    : m_engine(engine), m_templates(std::move(templates)), m_options(std::move(options)) {}

Evaluator::~Evaluator() { Shutdown(); }

render::Result<AdmissionLimits> Evaluator::Limits() const {
    if (m_options.limits) return *m_options.limits;
    render::Result<render::CapabilityReport> report = m_engine.Capabilities();
    if (!report) return render::Unexpected(report.error());
    return LimitsOf(report->admission);
}

render::Result<void> Evaluator::AdmitTextureSet(const core::Project& project, core::Id set) const {
    render::Result<AdmissionLimits> limits = Limits();
    if (!limits) return render::Unexpected(limits.error());
    return Admit(project, set, *limits);
}

render::Result<Evaluator::State*> Evaluator::StateFor(render::EngineContext& context) {
    if (m_shutdown) return EvalFail(EvalErrorKind::Internal, "the evaluator is shut down");
    if (!m_state) {
        render::Result<AdmissionLimits> limits = Limits();
        if (!limits) return render::Unexpected(limits.error());
        m_state = std::make_unique<State>(context.Device(), *limits);
    }
    return m_state.get();
}

std::future<render::Result<ChannelResult>> Evaluator::Evaluate(core::Snapshot snapshot,
                                                               EvaluateRequest request) {
    return m_engine.Submit(
        snapshot.project,
        [this, request = std::move(request)](render::EngineContext& context,
                                             const core::Project& project)
            -> render::Result<ChannelResult> {
            render::Result<State*> state = StateFor(context);
            if (!state) return render::Unexpected(state.error());
            (*state)->store.BeginRequest(context);
            render::Result<ChannelResult> result =
                EvaluateOn(project, request, *m_templates, (*state)->store, (*state)->cache);
            // Nothing stays queued across requests; a failed evaluation leaves nothing pinned.
            render::Result<void> flushed = (*state)->store.Flush();
            (*state)->cache.UnpinAll();
            (*state)->store.EndRequest();
            if (result && !flushed) return render::Unexpected(flushed.error());
            return result;
        });
}

std::future<render::Result<CacheStats>> Evaluator::Stats() {
    auto token = std::make_shared<const int>(0);
    return m_engine.Submit(token, [this](render::EngineContext& context, const int&)
                                      -> render::Result<CacheStats> {
        render::Result<State*> state = StateFor(context);
        if (!state) return render::Unexpected(state.error());
        return (*state)->cache.stats();
    });
}

void Evaluator::Shutdown() {
    if (m_shutdown) return;
    m_shutdown = true;
    auto token = std::make_shared<const int>(0);
    std::future<render::Result<void>> done =
        m_engine.Submit(token, [this](render::EngineContext&, const int&) -> render::Result<void> {
            if (m_state) {
                m_state->cache.UnpinAll();
                m_state->cache.Clear(m_state->store);
                m_state.reset();
            }
            return {};
        });
    // `engine_stopped` when the engine is gone: its device released the tiles with it.
    (void)done.get();
}

// ── CpuEvaluator ─────────────────────────────────────────────────────────────

CpuEvaluator::CpuEvaluator(std::shared_ptr<const TemplateLibrary> templates, AdmissionLimits limits)
    : m_templates(std::move(templates)), m_limits(limits), m_cache(limits) {}

render::Result<void> CpuEvaluator::AdmitTextureSet(const core::Project& project, core::Id set) const {
    return Admit(project, set, m_limits);
}

render::Result<ChannelResult> CpuEvaluator::Evaluate(const core::Project& project,
                                                     const EvaluateRequest& request) {
    render::Result<ChannelResult> result = EvaluateOn(project, request, *m_templates, m_store, m_cache);
    m_cache.UnpinAll();
    return result;
}

}  // namespace uzp::evaluator
