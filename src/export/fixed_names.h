#pragma once

// Fixed-name delivery (docs/architecture/08-export.md §5; task phase1.17_export-publication-receipts,
// decision 097; EXP-06). A consumer that reads fixed file names (Unreal import, the Assets3D
// scripts of §5.1) reads one complete published generation, by one of two routes:
//
// - the generation-pinning delivery adapter (`OpenPinnedDelivery`): the generation `current.json`
//   names, verified file by file against its receipt, handed over as its immutable `files/`
//   directory, whose names are the plan's fixed names;
// - the coordinated publication lock (`LockedFixedNames`): a copy of a generation under fixed names
//   in a directory of the caller's choice (`CopyFixedNames`), read while the lock is held. Opening
//   it completes an interrupted copy first (roll forward from its journal), then verifies every
//   fixed-name file against the generation's receipt; the lock excludes every writer until the
//   reader releases it.
//
// A fixed-name copy runs under the publication lock and is journalled in the target directory
// (`fixed-names.journal.json`, `kJournalSchema`): {generation, files[], copied[], obsolete[]}.
// The journal is written before the first copy; each file is copied to `<name>.uzp-staging`,
// flushed and renamed over its fixed name, and only then recorded in `copied`; the previous
// generation's names that the new one lacks (`obsolete`) are removed last. Every journal update is
// durable (staging file, flush, rename). A reader that finds `copied` short of `files`, or
// `obsolete` not empty, rolls the copy forward from the generation the journal names before it
// reads anything, or fails before consumption when that generation is not complete.

#include <chrono>
#include <filesystem>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "export/publish.h"
#include "export/receipt.h"

namespace uzp::exporter {

inline constexpr std::string_view kJournalFile = "fixed-names.journal.json";
inline constexpr std::string_view kJournalSchema = "uzpainter/export-fixed-names/1";

/// One complete generation as a consumer reads it.
struct Delivery {
    std::string generation;
    /// The directory holding the files under their fixed names.
    std::filesystem::path directory;
    /// As the generation's receipt lists them.
    std::vector<ReceiptFile> files;
};

/// The generation-pinning delivery adapter: the generation `exportPath/current.json` names, after
/// every file of its receipt verified (size, SHA-256) and the receipt matched the pointer. Fails
/// before consumption when nothing is published or the generation does not verify.
[[nodiscard]] render::Result<Delivery> OpenPinnedDelivery(const std::filesystem::path& exportPath);

/// Copies the published generation of `exportPath` under its fixed names into `directory` (see
/// above), completing an interrupted earlier copy first. A fixed name that is the journal, or,
/// when `directory` is `exportPath`, one of the publication's own names (`current.json`,
/// `generations`, `publication.lock`), is refused before anything is copied.
[[nodiscard]] render::Result<Delivery> CopyFixedNames(const std::filesystem::path& exportPath,
                                                      const std::filesystem::path& directory,
                                                      std::chrono::milliseconds lockTimeout = kLockTimeout);

/// Under the publication lock, completes an interrupted fixed-name copy into `directory`: the
/// generation it rolled forward, or nullopt when the copy was complete (or there is none).
[[nodiscard]] render::Result<std::optional<std::string>> RecoverFixedNames(
    const std::filesystem::path& exportPath, const std::filesystem::path& directory,
    std::chrono::milliseconds lockTimeout = kLockTimeout);

/// The fixed-name directory `directory` read under the publication lock of `exportPath`: opening
/// takes the lock, rolls an interrupted copy forward and verifies every fixed-name file against
/// its generation's receipt; the lock is held until the object is destroyed (or `Release`).
class LockedFixedNames {
public:
    [[nodiscard]] static render::Result<LockedFixedNames> Open(const std::filesystem::path& exportPath,
                                                               const std::filesystem::path& directory,
                                                               std::chrono::milliseconds lockTimeout = kLockTimeout);

    [[nodiscard]] const Delivery& delivery() const { return delivery_; }
    void Release() noexcept { lock_.Release(); }

private:
    LockedFixedNames(PublicationLock lock, Delivery delivery)
        : lock_(std::move(lock)), delivery_(std::move(delivery)) {}
    PublicationLock lock_;
    Delivery delivery_;
};

}  // namespace uzp::exporter
