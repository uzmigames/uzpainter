#pragma once

// The size census of owner answer Q11 (decision 024; `docs/architecture/09-project-file-format.md`
// §3, §7): the store's own instrumentation of first save, repeated one-parameter edits, a
// raster-plane edit, reopen time, bytes written per edit, compaction time, retained-history size
// and project versus external dependency bytes, run on the dependency content of a project and
// compared with the file size of the matched Painter project (`.spp`, only its size is read).
// The report holds numbers and identifiers only (`parity/reports/phase1/store-census.json`).
//
// The scripted sequence per project (`CensusProject`), in a work folder of its own:
//
// 1. first save: `Create` a portable project embedding every dependency file (the texturing
//    mesh, the mesh maps bound per texture set, further resources), then `save()`;
// 2. one fill-layer insertion, then `one_parameter_edits` mutations each changing one parameter
//    (the layer's BaseColor opacity);
// 3. a paint layer with a BaseColor raster plane of the first set's resolution (a disc of paint),
//    then an edit of that plane inside chunk (0, 0) only;
// 4. `save()`, close, reopen (timed), `compact` (timed);
// 5. the retained history and the project bytes of the compacted file.
//
// Bytes written per step are measured twice: the growth of the project file and the bytes the
// process wrote to disk (`GetProcessIoCounters` write transfer count: database pages, the rollback
// journal and its deletion included).

#include <cstdint>
#include <filesystem>
#include <map>
#include <string>
#include <vector>

#include "uzp_core/manifest/json.h"
#include "uzp_core/types/enums.h"

namespace uzp::store {

/// The report's `schema`.
inline constexpr std::string_view kCensusSchema = "uzpainter/store-census/1";
/// The inputs file's `schema` (`src/store/census_inputs.json`).
inline constexpr std::string_view kCensusInputsSchema = "uzpainter/store-census-inputs/1";
/// Owner Q11's candidate budget: the project file at most this fraction of the matched `.spp`.
inline constexpr double kCandidateBudget = 0.10;

struct CensusSetInput {
    std::string name;
    int resolution = 4096;
    std::map<core::MeshMapUsage, std::filesystem::path> mesh_maps;
};

struct CensusProjectInput {
    std::string id;
    std::filesystem::path spp;  // the matched Painter project: only its file size is read; empty when none
    std::filesystem::path mesh;
    std::vector<CensusSetInput> sets;
    std::vector<std::filesystem::path> resources;  // further dependency files (imported masks, ...)
    std::vector<std::string> not_measured;         // dependency content not available as files yet
};

struct CensusOptions {
    std::filesystem::path work_dir;  // one folder per project is created (and replaced) inside it
    int one_parameter_edits = 20;
};

/// The projects of an inputs document (`schema` `kCensusInputsSchema`: `projects` [{id, spp, mesh,
/// texture_sets [{name, resolution, mesh_maps {usage: file}}], resources [file | folder],
/// not_measured [id]}]) with every path relative to `assets_root`; a `resources` folder adds the
/// files directly inside it, sorted by name. Throws `StoreError(io)` for a missing dependency
/// file and `core::ValueError` for a malformed document, including an id that is not a plain
/// name (`[A-Za-z0-9_-]+`: it names a folder of `CensusOptions::work_dir`).
std::vector<CensusProjectInput> ReadCensusInputs(const core::json::Value& inputs, const std::filesystem::path& assets_root);

/// Runs the scripted sequence on one project and returns its measurements: `id`, `spp_bytes`,
/// `dependencies` {files, bytes, not_measured}, `first_save`, `layer_insert`,
/// `one_parameter_edits`, `raster_plane` {format, width, height, create, edit},
/// `reopen_seconds`, `compaction` {seconds, file_bytes_before, file_bytes_after},
/// `retained_history` {revisions, manifest_bytes, blob_bytes, operation_bytes, total_bytes},
/// `project_bytes`, `external_dependency_bytes`, `ratio_to_spp`, `within_candidate_budget`.
/// Each step is {seconds, file_growth_bytes, io_bytes_written}.
core::json::Value CensusProject(const CensusProjectInput& input, const CensusOptions& options);

/// The census report of `inputs`: {schema, task, date, candidate_budget_fraction, procedure,
/// projects [CensusProject]}.
core::json::Value RunCensus(const std::vector<CensusProjectInput>& inputs, const CensusOptions& options);

}  // namespace uzp::store
