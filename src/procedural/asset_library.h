#pragma once

// The UzPainter asset library (docs/architecture/05-procedural-content.md §3, §5;
// 03-project-model.md §3; decisions 006 and 324): the procedural assets UzPainter itself ships,
// each pinned as `uzasset://<family>/<id>@<version>`, each with its provenance record, and the
// internal compatibility alias table that lets `resource.search` resolve a Painter asset name.
//
// Layout of a library directory (shipped as `bin/assets/procedural/`, `assets/procedural/` in
// the repository):
//
//     library.json   {"schema": "uzpainter/asset-library/1", "records": [<path>, ...],
//                     "aliases": "<path>"}
//     <record>.json  one provenance record per pinned asset (`kRecordSchema`)
//     <aliases>.json the alias table (`kAliasSchema`)
//
// Clean room (decision 006): a record names UzPainter's own implementation, written from public
// literature. Its sources are papers, books, standards or an approved public documentation
// source (`docs/approved-sources.md`); its licence is Apache-2.0; it carries a UzPainter name,
// never a Painter asset name of the alias table. The library holds no Adobe content: no `.sbsar`,
// no captured output, no preset tree.
//
// Pinning: a project names an asset by its full URL, version included. `Resolve` returns that
// exact version or refuses: there is no "latest", no nearest version and no alias in a pin.
//
// Aliases: Painter names (shelf, usage, name) mapped to library assets. An alias may name only an
// asset whose parity status is `exact`: resolving a Painter name to anything else would
// substitute a different asset (05 §2). A Painter name with no alias is refused, never answered
// with a similar asset.

#include "procedural/seam.h"

#include "uzp_core/manifest/json.h"
#include "uzp_core/types/project.h"

#include <expected>
#include <filesystem>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace uzp::procedural {

inline constexpr std::string_view kLibrarySchema = "uzpainter/asset-library/1";
inline constexpr std::string_view kRecordSchema = "uzpainter/asset-provenance/1";
inline constexpr std::string_view kAliasSchema = "uzpainter/asset-aliases/1";
/// The shelf of UzPainter's own library in `resource.search` queries (`s:uzpainter`).
inline constexpr std::string_view kLibraryShelf = "uzpainter";
/// The reason of a pin whose exact version the library does not hold.
inline constexpr std::string_view kNotInLibrary = "pinned version not in the asset library";
/// The reason of a Painter asset name that maps to no certified family.
inline constexpr std::string_view kNoCertifiedFamily = "no certified family";

/// One source of a provenance record: a paper, a book, a standard or an approved public
/// documentation source (`approved-source`, with its id in `docs/approved-sources.md`).
struct ProvenanceSource {
    std::string kind;
    std::string citation;
    std::string approvedSourceId;  ///< `approved-source` only.
};

/// One pinned asset of the library and its provenance record (05 §3).
struct AssetRecord {
    core::AssetUrl asset;
    std::string name;   ///< The UzPainter name (`Resource.gui_name`).
    std::string usage;  ///< A `resource.Usage` member name (GENERATOR, FILTER, PROCEDURAL, ...).
    std::string author;
    std::string license;
    std::vector<ProvenanceSource> sources;
    /// The effective defaults of every declared parameter (booleans as integers).
    Params defaults;
    CertifiedDomain domain;
    ParityStatus status;     ///< `corpusIds` = {calibration, held-out}.
    std::string report;      ///< The certification report that gives the status (path or "").
    core::json::Value json;  ///< The record as stored.
    std::filesystem::path file;
};

/// One alias: a Painter asset name on a Painter shelf, for a usage.
struct AssetAlias {
    std::string shelf;  ///< The shelf as a query names it (`starterassets`).
    std::string usage;
    std::string painterName;
    core::AssetUrl asset;
};

/// Why a search was refused: a release gap (`NotYetSupported`) or procedural content UzPainter
/// does not hold (`UnsupportedProcedural`).
struct SearchRefusal {
    enum class Kind : uint8_t { NotYetSupported, UnsupportedProcedural };
    Kind kind = Kind::NotYetSupported;
    std::string message;
    UnsupportedProcedural procedural;  ///< `UnsupportedProcedural` only.
};

class AssetLibrary {
public:
    /// Loads and checks the library at `root` (its `library.json`). Every problem refuses the
    /// whole library, with the file and the reason.
    static std::expected<AssetLibrary, std::string> Load(const std::filesystem::path& root);
    /// An empty library (no asset, no alias).
    AssetLibrary() = default;

    [[nodiscard]] const std::vector<AssetRecord>& records() const { return m_records; }
    [[nodiscard]] const std::vector<AssetAlias>& aliases() const { return m_aliases; }

    /// The record pinned at exactly `asset`'s version, or null.
    [[nodiscard]] const AssetRecord* Find(const core::AssetUrl& asset) const;
    /// `Find`, or `UnsupportedProcedural{asset, "pinned version not in the asset library"}`
    /// naming the versions the library holds of that asset. No other version is substituted.
    [[nodiscard]] std::expected<const AssetRecord*, UnsupportedProcedural> Resolve(
        const core::AssetUrl& asset) const;

    /// `resource.search(query)` over this library (decision 324 §3). Implemented terms:
    /// `s:<shelf>`, `u:<usage>` and the exact name `n:<name>=` (a backslash escapes the next
    /// character). `s:uzpainter` lists the library by UzPainter names. Any other shelf, or none,
    /// is Painter's library: only an exact name is answered, through the alias table, and a name
    /// with no alias raises `UnsupportedProcedural{name, "no certified family"}`. Every other
    /// query form is a release gap: Painter's query grammar beyond these terms is unrecorded.
    [[nodiscard]] std::expected<std::vector<const AssetRecord*>, SearchRefusal> Search(
        std::string_view query) const;

private:
    std::vector<AssetRecord> m_records;
    std::vector<AssetAlias> m_aliases;
};

/// The certified editable domain of a provenance record, in the certification harness's JSON
/// form (`tools/parity/proc_cert/batch.py` `Domain`), plus an optional `presets` list.
std::expected<CertifiedDomain, std::string> ParseDomain(const core::json::Value& document);

/// The `resource.Usage` member names a record may carry.
[[nodiscard]] const std::vector<std::string>& AssetUsages();

/// Every `uzasset://` URL the project pins (procedural sources and effects, smart presets),
/// sorted and unique.
[[nodiscard]] std::vector<std::string> PinnedAssets(const core::Project& project);

/// The first pin of `project` the library does not hold at its exact version (or that is not a
/// valid asset URL), as `UnsupportedProcedural`; empty when every pin resolves.
[[nodiscard]] std::optional<UnsupportedProcedural> CheckPins(const core::Project& project,
                                                             const AssetLibrary& library);

/// `bin/assets/procedural` beside the running executable, or `UZP_ASSET_LIBRARY` when set.
[[nodiscard]] std::filesystem::path DefaultLibraryRoot();

/// The library at `DefaultLibraryRoot()`, loaded once per process.
[[nodiscard]] const std::expected<AssetLibrary, std::string>& ShippedLibrary();

}  // namespace uzp::procedural
