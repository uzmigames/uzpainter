#pragma once

// The CPU evaluation of the open project's committed revision, kept from one call to the next
// (B19 of parity/reports/phase2/practical-e2e.md, decision 246).
//
// An export job, a texture-space or `painter_viewport` capture and a diagnostic read one committed
// revision on the CPU evaluator (the evaluator the export's goldens are compared with). Everything
// that evaluation reads is fixed by the revision: the project itself (its stacks, settings,
// template, colour management and evaluator profile), the bitmaps and the mesh its stored bytes
// give (each checked against its SHA-256), the installed templates (read once per evaluation, as
// the worker's GPU evaluator reads them once per process) and the admission limits (constants).
// So the inputs and the tile cache one call builds serve every later call on the same revision,
// which evaluates only what no earlier call did: an export of a revision already exported,
// captured or diagnosed encodes its files without evaluating the stack again.
//
// - Key: the open project (its store), the revision's own `core::Project` object (a later commit
//   is another object, even when it restores an earlier state) and the calling thread's
//   floating-point control state, which the evaluator's arithmetic runs under.
// - At most one revision is kept, never longer than the project is open: a call on the document's
//   current revision replaces an evaluation of another revision, and every commit drops the
//   evaluation it superseded (`DropSupersededEvaluation`, from `Session::NotifyDurableChange`). A
//   call on an older revision (a job queued before a commit) evaluates privately and leaves the
//   kept evaluation alone.
// - A lease is exclusive: it takes the evaluation out of the open project, and its end puts it back
//   only under the two rules below and while its revision is the current one. A call that finds
//   the evaluation leased (a capture while an export job runs) evaluates on a private evaluation
//   that is never kept, as every call did before.
// - Kept only when clean. A tile is cached when it is allocated, before the operation that fills it
//   runs, so an evaluation that failed, threw or was cancelled may leave a tile that never received
//   its values. When the lease ends, the evaluation is dropped if any tile was allocated after the
//   last `Keep()`; a call that refused before allocating a tile keeps it.
// - Kept only when affordable: the memory its tiles hold must not exceed the physical memory the
//   machine still has available when the call ends; otherwise it is dropped, as before.

#include <cstdint>
#include <memory>

#include "evaluator/evaluator.h"
#include "export/plan.h"
#include "python/session.h"
#include "uzp_core/document/document.h"

namespace uzp::mesh {
struct TexturingMesh;
}

namespace uzp::python {

/// Everything a CPU evaluation of one committed revision reads, and the tiles it computed.
struct RevisionEvaluation {
    RevisionEvaluation(core::Snapshot revision, std::shared_ptr<const evaluator::TemplateLibrary> library);

    /// The revision: its `core::Project` object is the key.
    core::Snapshot snapshot;
    /// The MXCSR control bits of the thread that built it: part of the key.
    std::uint32_t floatControl = 0;
    std::shared_ptr<const evaluator::TemplateLibrary> templates;
    /// The project's template, the store's bitmaps (decoded once, checked against their SHA-256)
    /// and the geometry masks of the texturing mesh. `beforeFile` is empty: an export job sets its
    /// own on a copy.
    exporter::SourceInputs inputs;
    /// The texturing mesh re-derived from the stored bytes; null when the project has none.
    std::shared_ptr<const mesh::TexturingMesh> mesh;
    evaluator::CpuEvaluator cpu;
};

/// The exclusive use of a `RevisionEvaluation` for one call (see above). Move-only.
class EvaluationLease {
public:
    EvaluationLease(std::shared_ptr<OpenProject> open, std::shared_ptr<RevisionEvaluation> evaluation, bool kept);
    EvaluationLease(EvaluationLease&& other) noexcept;
    EvaluationLease& operator=(EvaluationLease&&) = delete;
    EvaluationLease(const EvaluationLease&) = delete;
    EvaluationLease& operator=(const EvaluationLease&) = delete;
    /// Unpins every tile; returns the open project's evaluation, kept when clean (see above).
    ~EvaluationLease();

    [[nodiscard]] RevisionEvaluation& operator*() const { return *m_evaluation; }
    [[nodiscard]] RevisionEvaluation* operator->() const { return m_evaluation.get(); }

    /// Every evaluation run through the lease so far succeeded: the tiles they allocated serve
    /// later calls.
    void Keep();

private:
    std::shared_ptr<OpenProject> m_open;
    std::shared_ptr<RevisionEvaluation> m_evaluation;
    /// The open project's kept evaluation (else a private one, dropped with the lease).
    bool m_kept = false;
    /// The cache's allocations at the last `Keep()` (or when the lease began).
    std::uint64_t m_clean = 0;
};

/// The evaluation of `snapshot`, a committed revision of `open` (see above): the kept one when it
/// is of that revision, else one built from the store (the templates, the bitmaps decoded on first
/// use, the mesh re-derived from its bytes) with an empty cache.
[[nodiscard]] EvaluationLease LeaseEvaluation(const std::shared_ptr<OpenProject>& open, const core::Snapshot& snapshot);

/// Drops the evaluation `open` keeps when its revision is no longer the document's current one; its
/// memory is released on a thread of its own, so the commit that superseded it does not wait.
void DropSupersededEvaluation(OpenProject& open);

}  // namespace uzp::python
