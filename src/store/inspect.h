#pragma once

// `uzpainter inspect <file.uzp> [--revision N] [--verify]` (`docs/architecture/09-project-file-format.md`
// §6): the fields of a project file read without opening the project. Nothing here takes the
// project's lock sidecar, uses a GPU or writes to the file: the report is read through a
// read-only connection inside one read transaction, and `--verify` checks a consistent snapshot
// (`ReadSnapshot`) so a worker that holds the project keeps committing meanwhile.

#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>

#include "store/container.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/recipe.h"

namespace uzp::store {

struct InspectOptions {
    /// The revision whose manifest is described; `checkpoint('current')` when absent.
    std::optional<std::int64_t> revision;
    /// Also run every integrity rule of 09 §1 (`CheckIntegrity` with `VerifyLevel::full`).
    bool verify = false;
    /// The running application's recipe host (its version and template base values,
    /// `python::HostRecipe`); without one the recipe digest is unavailable.
    const core::RecipeHost* recipe = nullptr;
};

/// The reason of an unavailable recipe digest when the host resolves no base values (the store's
/// own test executable; `UzPainter.exe inspect` always passes its host).
inline constexpr std::string_view kRecipeHostMissing =
    "this host resolves no template base values; UzPainter.exe inspect reports the recipe digest";

/// The inspection report of `project`, a JSON object:
///
/// - `file`, `project` {uuid, portable, created, operation_horizon_revision};
/// - `revision` {number, current, kind, name, parent, created_at, manifest_sha256} and
///   `revisions` {count, first, last};
/// - `versions` {format_version (of the manifest and of `meta`), app_version, painter_reference}
///   and `profiles` {evaluator_profile, compat_profile};
/// - `settings` (the manifest's project settings), `mesh`, `texture_sets` (each with its UV
///   tiles, channels per stack, the layer tree with every node's resource and plane bindings,
///   and `mesh_maps` with their provenance);
/// - `resources`: one row per resource name {name, sha256, bytes, stored_bytes, mime, usage,
///   color_space, origin, storage: embedded | locator | missing};
/// - `checkpoints` {name, revision, created_at, note, protected};
/// - `sizes`: `file_bytes`, the project file's parts (`manifests`, `resources`,
///   `plane_chunks`, `operations`, `cache`) and, listed separately, `external_dependencies`
///   (the locator targets of a non-portable project: count, bytes, missing);
/// - `recipe_digest` {available: true, digest} of the revision's recipe dump (`InspectRecipe`),
///   or {available: false, reason} without a recipe host (`kRecipeHostMissing`) or when the dump
///   fails (a template the host does not hold);
/// - with `verify`: `verify` {ok, corrupt, missing, collectable} (`IntegrityReport::ToJson`).
///
/// Throws `StoreError` when the file is not a readable project (`not_a_project`, `version` for a
/// newer major, `io` for a file a killed worker left with a hot journal) and `CorruptionError`
/// when the requested revision's manifest does not verify.
core::json::Value Inspect(const std::filesystem::path& project, const InspectOptions& options = {});

/// The recipe dump (`core::DumpRecipe`) of `revision` (`checkpoint('current')` when absent), read
/// like the report: a read-only connection inside one read transaction, no lock, no GPU, so it is
/// the dump `uzpainter.project.dump_recipe()` returns for that revision while a worker holds the
/// project. Throws as `Inspect`, and what the dump throws.
core::json::Object InspectRecipe(const std::filesystem::path& project, std::optional<std::int64_t> revision,
                                 const core::RecipeHost& host);

/// Indented JSON (two spaces, keys in canonical order, numbers as the canonical writer spells
/// them), newline-terminated: the text `uzpainter inspect` prints and the census report.
std::string WriteIndented(const core::json::Value& value);

/// A consistent read-only copy of a project file taken without its lock (SQLite online backup
/// into a temporary file, removed with the snapshot). The source's read lock is held only while
/// the pages are copied.
class ReadSnapshot {
public:
    explicit ReadSnapshot(const std::filesystem::path& project);
    ~ReadSnapshot();
    ReadSnapshot(const ReadSnapshot&) = delete;
    ReadSnapshot& operator=(const ReadSnapshot&) = delete;

    Container& container() { return *container_; }

private:
    std::filesystem::path copy_;
    std::optional<Container> container_;
};

}  // namespace uzp::store
