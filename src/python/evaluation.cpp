// The CPU evaluation of the open project's committed revision, kept from one call to the next
// (evaluation.h).

#include "python/evaluation.h"

#include <mutex>
#include <optional>
#include <string>
#include <string_view>
#include <thread>
#include <utility>

#include "evaluator/geometry_mask.h"
#include "evaluator/sources.h"
#include "evaluator/templates.h"
#include "mesh/reload.h"
#include "store/container.h"

#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <immintrin.h>
#include <windows.h>

namespace uzp::python {

namespace {

/// The CPU evaluator's admission limits in the worker (those every call had before it was kept).
constexpr evaluator::AdmissionLimits kLimits{64ull << 30, 1 << 20};

/// Tiles the cache has allocated so far: an allocation adds a live tile, an eviction moves one
/// from live to evicted (the kept cache is never cleared).
std::uint64_t Allocations(const evaluator::TileCache& cache) {
    return cache.stats().liveTiles + cache.stats().evictions;
}

/// The control bits of this thread's SSE floating-point state (MXCSR: rounding, flush-to-zero,
/// denormals-are-zero, exception masks), which the evaluator's arithmetic runs under; the sticky
/// exception flags are left out.
std::uint32_t FloatControl() { return _mm_getcsr() & ~std::uint32_t{0x3F}; }

/// Whether the machine affords keeping `evaluation`: the memory its tiles hold (a 32-bit word per
/// stored value, of which the cache accounts at least a byte) is at most the physical memory still
/// available, so keeping it never takes more than half of what would otherwise be free.
bool Affordable(RevisionEvaluation& evaluation) {
    MEMORYSTATUSEX status{};
    status.dwLength = sizeof(status);
    return GlobalMemoryStatusEx(&status) && 4 * evaluation.cpu.store().AllocatedBytes() <= status.ullAvailPhys;
}

/// The evaluation of `snapshot` read from `open`'s store, with an empty cache.
std::shared_ptr<RevisionEvaluation> Build(const OpenProject& open, const core::Snapshot& snapshot) {
    auto evaluation = std::make_shared<RevisionEvaluation>(
        snapshot, std::make_shared<const evaluator::TemplateLibrary>(
                      evaluator::TemplateLibrary::Load(evaluator::TemplateLibrary::DefaultDirectory())));
    const core::Project& project = *snapshot.project;
    store::ProjectStore* store = open.store.get();
    evaluation->inputs.templateId = project.settings.template_id;  // the base values the project records
    // A resource the store does not hold is missing to the evaluator (`evaluator:missing_resource`);
    // a store failure is raised.
    evaluation->inputs.resources = std::make_shared<evaluator::DecodingResourceProvider>(
        [store](std::string_view sha256) -> std::optional<std::string> {
            try {
                return store->ReadResource(sha256);
            } catch (const store::StoreError& error) {
                if (error.code() == store::StoreError::Code::missing_resource) return std::nullopt;
                throw;
            }
        });
    if (project.mesh) {
        mesh::ImportResult imported =
            mesh::RederiveMesh(project, [store](const std::string& sha256) { return store->ReadResource(sha256); });
        evaluation->mesh = std::make_shared<const mesh::TexturingMesh>(std::move(imported.mesh));
        evaluation->inputs.geometry = std::make_shared<evaluator::MeshGeometryMasks>(evaluation->mesh);
    }
    return evaluation;
}

}  // namespace

RevisionEvaluation::RevisionEvaluation(core::Snapshot revision,
                                       std::shared_ptr<const evaluator::TemplateLibrary> library)
    : snapshot(std::move(revision)), floatControl(FloatControl()), templates(std::move(library)),
      cpu(templates, kLimits) {}

EvaluationLease::EvaluationLease(std::shared_ptr<OpenProject> open, std::shared_ptr<RevisionEvaluation> evaluation,
                                 bool kept)
    : m_open(std::move(open)), m_evaluation(std::move(evaluation)), m_kept(kept),
      m_clean(Allocations(m_evaluation->cpu.cache())) {}

EvaluationLease::EvaluationLease(EvaluationLease&& other) noexcept
    : m_open(std::move(other.m_open)), m_evaluation(std::move(other.m_evaluation)), m_kept(other.m_kept),
      m_clean(other.m_clean) {
    other.m_kept = false;
}

EvaluationLease::~EvaluationLease() {
    if (!m_evaluation) return;  // moved from
    m_evaluation->cpu.cache().UnpinAll();
    if (!m_kept) return;
    const bool clean = Allocations(m_evaluation->cpu.cache()) == m_clean;
    std::shared_ptr<RevisionEvaluation> dropped;
    std::lock_guard lock(m_open->evaluation_mutex);
    m_open->evaluation_leased = false;
    if (clean && m_open->document->snapshot().project == m_evaluation->snapshot.project && Affordable(*m_evaluation)) {
        m_open->evaluation = std::move(m_evaluation);
    } else {
        dropped = std::move(m_evaluation);  // released after the lock
    }
}

void EvaluationLease::Keep() { m_clean = Allocations(m_evaluation->cpu.cache()); }

EvaluationLease LeaseEvaluation(const std::shared_ptr<OpenProject>& open, const core::Snapshot& snapshot) {
    bool kept = false;
    std::shared_ptr<RevisionEvaluation> replaced;
    {
        std::lock_guard lock(open->evaluation_mutex);
        if (!open->evaluation_leased) {
            if (open->evaluation && open->evaluation->snapshot.project == snapshot.project &&
                open->evaluation->floatControl == FloatControl()) {
                open->evaluation_leased = true;
                return EvaluationLease(open, open->evaluation, true);
            }
            if (open->document->snapshot().project == snapshot.project) {
                open->evaluation_leased = true;
                kept = true;
                replaced = std::move(open->evaluation);
            }
        }
    }
    replaced.reset();  // another revision's evaluation never serves this one
    try {
        return EvaluationLease(open, Build(*open, snapshot), kept);
    } catch (...) {
        if (kept) {
            std::lock_guard lock(open->evaluation_mutex);
            open->evaluation_leased = false;
        }
        throw;
    }
}

void DropSupersededEvaluation(OpenProject& open) {
    std::shared_ptr<RevisionEvaluation> superseded;
    {
        std::lock_guard lock(open.evaluation_mutex);
        if (open.evaluation && open.evaluation->snapshot.project != open.document->snapshot().project) {
            superseded = std::move(open.evaluation);
        }
    }
    // Releasing its tiles takes a while (0.6 s for a 2048 x 2048 stack); the commit does not wait.
    if (superseded) std::thread([released = std::move(superseded)]() mutable { released.reset(); }).detach();
}

}  // namespace uzp::python
