#pragma once

// Generational export publication (docs/architecture/08-export.md §5; task
// phase1.17_export-publication-receipts, decision 097; EXP-06, QG-03). Every export writes its
// files and its receipt into a new generation directory under exportPath, verifies them, and
// publishes them by one atomic durable update of the delivery pointer:
//
//   <exportPath>/current.json                       the pointer (`kCurrentSchema`)
//   <exportPath>/publication.lock                   the coordinated publication lock
//   <exportPath>/generations/<NNNNNN>/files/<relativePath>   the planned files
//   <exportPath>/generations/<NNNNNN>/plan.json     the plan (PlanJson, canonical)
//   <exportPath>/generations/<NNNNNN>/receipt.json  the receipt (receipt.h)
//
// Publication, in order, all under the publication lock:
// 1. every file checked, evaluated, padded and encoded in memory (EncodeExport): a refusal or a
//    failure here writes nothing;
// 2. a new generation claimed: the next number after every existing one, created only if absent;
// 3. each file written and flushed to disk (a file's `.uztexture` derivative right after it, and a
//    `.uzmat` after its stack's last file, write.h), then read back and verified against its encoding (size and
//    SHA-256); then plan.json and receipt.json, flushed and verified the same way;
// 4. the pointer written to `current.json.uzp-staging`, flushed, and renamed over `current.json`
//    (MoveFileEx, replace existing, write through).
// A failure at any step before the rename removes the new generation and returns the failure: the
// previous generation stays selected and the host keeps running. A process killed before the
// rename leaves the generation unreferenced; `RecoverExport` completes or discards it.
//
// A generation is complete when its receipt reads as a receipt of that generation, its plan.json
// is the plan the receipt's plan hash names, and every file the receipt lists has the size and
// SHA-256 the receipt records. Complete generations are immutable and never removed. Staging names
// (`*.uzp-staging`) never appear in a receipt or in the pointer.

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "export/plan.h"
#include "export/receipt.h"
#include "export/write.h"

namespace uzp::exporter {

/// The pointer's JSON schema id: {schema, generation, receipt, receipt_sha256}.
inline constexpr std::string_view kCurrentSchema = "uzpainter/export-current/1";
inline constexpr std::string_view kCurrentFile = "current.json";
inline constexpr std::string_view kGenerationsDir = "generations";
inline constexpr std::string_view kLockFile = "publication.lock";
inline constexpr std::string_view kStagingSuffix = ".uzp-staging";
/// How long an operation waits for the publication lock by default.
inline constexpr std::chrono::milliseconds kLockTimeout{30000};

/// A UTF-8 path as a filesystem path.
[[nodiscard]] std::filesystem::path Utf8Path(std::string_view text);
/// A filesystem path as UTF-8 with `/` separators.
[[nodiscard]] std::string Utf8String(const std::filesystem::path& path);

/// The coordinated publication lock of an exportPath (`publication.lock`, held open without
/// sharing). Publication, fixed-name copies, recovery and the locked fixed-name reader hold it for
/// their whole run, so none of them overlaps another; the OS releases it when its process dies.
/// Move-only.
class PublicationLock {
public:
    /// Takes the lock of `exportPath` (created when absent), waiting up to `timeout` while another
    /// holder has it. Fails with an `export:` failure naming the lock on timeout or an I/O error.
    [[nodiscard]] static render::Result<PublicationLock> Acquire(const std::filesystem::path& exportPath,
                                                                 std::chrono::milliseconds timeout = kLockTimeout);

    PublicationLock() = default;
    PublicationLock(PublicationLock&& other) noexcept;
    PublicationLock& operator=(PublicationLock&& other) noexcept;
    PublicationLock(const PublicationLock&) = delete;
    PublicationLock& operator=(const PublicationLock&) = delete;
    ~PublicationLock();

    [[nodiscard]] bool held() const { return handle_ != nullptr; }
    /// Releases the lock; nothing when not held.
    void Release() noexcept;

private:
    explicit PublicationLock(void* handle) : handle_(handle) {}
    void* handle_ = nullptr;  // the lock file's Windows HANDLE, open while held
};

/// The delivery pointer.
struct CurrentPointer {
    std::string generation;
    /// "generations/<generation>/receipt.json".
    std::string receipt;
    std::string receiptSha256;
};

/// `current.json` of `exportPath`: nullopt when there is none; an `export:` failure when it does
/// not read as a pointer of `kCurrentSchema` whose receipt path is its generation's.
[[nodiscard]] render::Result<std::optional<CurrentPointer>> ReadCurrent(const std::filesystem::path& exportPath);

/// What a generation directory holds.
struct GenerationState {
    std::string id;
    bool complete = false;
    /// Why it is not complete.
    std::string problem;
    /// Complete generations: their receipt and the SHA-256 of its bytes.
    std::optional<ReceiptSummary> receipt;
    std::string receiptSha256;
};

/// `<exportPath>/generations/<id>`.
[[nodiscard]] std::filesystem::path GenerationPath(const std::filesystem::path& exportPath, std::string_view id);
/// Verifies generation `id` of `exportPath` (see above).
[[nodiscard]] GenerationState InspectGeneration(const std::filesystem::path& exportPath, std::string_view id);
/// The generation ids under `exportPath`, in increasing order (directories named by digits only).
[[nodiscard]] std::vector<std::string> ListGenerations(const std::filesystem::path& exportPath);

struct PublishRequest {
    BuildIdentity identity;
    /// PlanContext::projectPath of the plan (the manifest's project source).
    std::string projectPath;
    std::chrono::milliseconds lockTimeout = kLockTimeout;
    /// The diagnostic measure export (write.h, decision 286): not conformant, its receipt marked
    /// `non_conformant`. Never set by production: only `UzPainter.exe run --diagnostic-measure-export`.
    std::optional<DiagnosticMeasure> diagnostic;
    /// Called after encoding and again after acquiring the lock, before creating a generation.
    /// A failed checkpoint publishes nothing (cancellation, deadline or device failure).
    std::function<render::Result<void>()> beforePublish;
};

struct Publication {
    std::string generation;
    /// The generation directory, its receipt and the SHA-256 of the receipt's bytes.
    std::filesystem::path directory;
    std::filesystem::path receipt;
    std::string receiptSha256;
    /// In plan order, each `.uztexture` derivative after its file and each `.uzmat` after its stack's last file;
    /// `path` is the file in the generation's `files/`.
    std::vector<WrittenFile> files;
};

/// Publishes `plan` (compiled from revision `revision` of `project`) as a new generation (see
/// above). Throws `core::NotYetSupported` or `core::ValueError` before anything is evaluated for an
/// unrecorded processing or padding; returns the evaluator's failure or an `export:` failure, with
/// the previous generation still selected.
[[nodiscard]] render::Result<Publication> PublishExport(const core::Project& project, std::int64_t revision,
                                                        const ExportPlan& plan, const SourceInputs& inputs,
                                                        const evaluator::TemplateLibrary& templates,
                                                        evaluator::ITileStore& store, evaluator::TileCache& cache,
                                                        const PublishRequest& request);

/// What recovery found and did.
struct RecoveryReport {
    std::optional<std::string> currentBefore;
    std::optional<std::string> currentAfter;
    /// The complete generation published by rolling the pointer forward, when there was one.
    std::optional<std::string> published;
    /// Incomplete generations removed, with why each was incomplete.
    std::vector<std::pair<std::string, std::string>> removed;
    /// The selected generation, when it does not verify: reported, never touched.
    std::optional<std::pair<std::string, std::string>> damaged;
    /// A leftover staging pointer removed.
    bool removedStagingPointer = false;
};

/// `uzpainter export --recover`, under the publication lock: the newest complete generation newer
/// than the selected one (or any, when none is selected) is published, as its export had done
/// everything but the pointer's rename; every other incomplete generation is removed; complete
/// generations and the selected one are never removed. A pointer that does not read, or an
/// exportPath that is not a folder, fails the recovery before anything changes.
[[nodiscard]] render::Result<RecoveryReport> RecoverExport(const std::filesystem::path& exportPath,
                                                           std::chrono::milliseconds lockTimeout = kLockTimeout);

namespace publish_detail {

/// Writes `bytes` to `path` (replacing it) and flushes it to disk.
[[nodiscard]] render::Result<void> WriteDurable(const std::filesystem::path& path, std::string_view bytes);
/// Renames `from` over `to` durably (MoveFileEx, replace existing, write through).
[[nodiscard]] render::Result<void> RenameDurable(const std::filesystem::path& from, const std::filesystem::path& to);
/// The bytes of `path`, or nullopt when it cannot be read.
[[nodiscard]] std::optional<std::string> ReadBytes(const std::filesystem::path& path);
/// True when `path` holds `bytes` bytes with SHA-256 `sha256`; otherwise `problem` says why.
[[nodiscard]] bool Verifies(const std::filesystem::path& path, std::uint64_t bytes, std::string_view sha256,
                            std::string& problem);
[[nodiscard]] render::Unexpected Fail(std::string reason);

}  // namespace publish_detail

}  // namespace uzp::exporter
