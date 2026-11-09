#pragma once

// The export receipt (docs/architecture/08-export.md §5; task phase1.17_export-publication-receipts,
// decision 097; ARC-11, EXP-09, EXP-10, INT-21, QG-03). Every published generation carries one,
// `receipt.json` (schema `kReceiptSchema`, `src/export/schema/receipt.schema.json`):
//
// - the ARC-11 header (uzp_core/types/receipt.h: revision, evaluator_profile, compat_profile,
//   app_version, resource_hashes) plus `build`, the generation, the moment and the plan hash;
// - per written file: its path (the plan's relativePath, relative to the generation's `files/`),
//   bytes, SHA-256, format, bit depth, colour space, size, preset, layout, channel mapping, the
//   EXP-09 normal tag (`combined` with its relief round, or `geometry_only`) and its consumer gaps;
// - per `.uztexture` normal derivative (write.h `EncodedUzTexture`, decision 316), right after its
//   canonical file: a file of format `uztexture`, bit depth 8, linear, with `uztexture` {source (the
//   canonical file's path), binding `normal`, format (`BC5`, or `RGBA8` when routed), srgb, mips,
//   encoder, negative_z {policy, texels, first, routed}}; a routed one carries a Normal consumer gap
//   (a consumer that reconstructs Z still loses its sign);
// - per DDS derivative: its own complete-file hash, source canonical PNG16, BC format, sRGB,
//   mip count, encoder/settings, stored channels and lossy marker. `layout`/`channels` describe
//   the canonical mapping; `dds.stored_channels` distinguishes BC5 RG from BC7 RGBA storage;
// - the maps the plan does not write (`skipped`, with their kind and reason: QG-03);
// - the Assets3D manifest export block (`manifest_export`) in the form of Assets3D's
//   `manifest-schema-v2.json` `$defs/export` (sources, outputs, moment, preset, maps, comparison,
//   evidence, open_items), with `manifest_files`, the manifest `files` entries its keys name.
//   Their paths are relative to the generation; rebasing them under the Assets3D root is the
//   pipeline adapter's (phase1.23_pyapi-pipeline-adapter). The block replaces schema v1's
//   `exportacao` (fontes, saidas, momento, preset, mapas, comparacao, evidencias, pendencias),
//   which Assets3D retired (decision 097).
//
// A generation of the diagnostic measure export (write.h, decision 286) also carries
// `non_conformant`: {mode: "diagnostic-measure", decision: "286", bypassed: [{path, refusal}]}, the
// production refusals it bypassed per file, with `undecided: [{path, texels, rule}]` when a file
// holds texels written by a rule whose form is not recorded (decision 308), and its manifest
// export block names it in `open_items`
// (`kNonConformantNote`). A conformant generation has no `non_conformant`.
//
// A generation with a file whose `infinite` padding filled texels outside the UV islands
// (`EncodedFile::islandPadding`) relies on the owner's exception EXC-013 (decision 414: every
// covered texel exact, the padding free): it carries `exceptions_relied_on`: [{exception_id,
// version, decision, paths}], and its manifest export block names it in `open_items`
// (`IslandPaddingNote`). A file whose combined virtual normal was written on incomplete coverage
// (`EncodedFile::islandNormal`) relies on EXC-014 too (decision 417: its covered island-edge texels
// may differ, every other covered texel exact): a second entry lists those files, and the manifest
// export block names it (`kIslandNormalNote`). Such a generation is conformant, never exact;
// without such a file it has no `exceptions_relied_on`.
//
// resource_hashes is the set of resources the planned files read: the bitmaps of every channel DAG
// they evaluate (fills, content effects, masks, groups), the masks of a diagnostic's material and
// its enclosing groups, the mesh maps read, and the texturing mesh whose UV coverage drives the
// padding (and every geometry mask): its file and the files it reads beside it
// (`core::MeshResourceHashes`).

#include <cstdint>
#include <set>
#include <string>
#include <string_view>
#include <vector>

#include "export/plan.h"
#include "export/write.h"
#include "uzp_core/manifest/json.h"

namespace uzp::exporter {

/// The gap a consumer must close itself (08-export.md §4, §5.1 rows 2 and 8): SpecularWeight has
/// no slot in the consumers' materials, and its stated mapping belongs to the consumer.
inline constexpr std::string_view kSpecularWeightGap =
    "SpecularWeight has no slot in the consumer's material: its mapping (Specular = 0.5 x "
    "SpecularWeight in the hat v8 report) belongs to the consumer and is not applied by the export";
/// The gaps of the UzEngine consumer at U-UZE-RUNTIME a703c95 (08-export.md §4; uzmat_writer.h):
/// the SM5 route never reads albedo alpha as opacity, and no `.uzmat` pin or inline scene key binds
/// a height map (its `heightmapSrvIndex` has no verified route). Shared by the export receipt and
/// the `cook-uzengine` receipt (cli.h).
inline constexpr std::string_view kSm5OpacityGap =
    "opacity is carried in albedo alpha, which the bindless fixed-PBR path reads; the SM5 route never reads "
    "albedo alpha as opacity, so opacity is unsupported there (08-export.md §4)";
inline constexpr std::string_view kHeightGap =
    "no .uzmat pin and no inline scene-material key binds a height map in the pinned UzEngine format "
    "(U-UZE-RUNTIME a703c95); the heightmap slot has no verified route";
inline constexpr std::string_view kNoSlotGap = "the UzEngine material has no slot for this texture";
/// The `.uzmat` blend is an authored rule (write.h `EncodedUzMaterial`), not an engine fact.
inline constexpr std::string_view kBlendGap =
    "the blend is UzPainter's authored rule (Masked when the albedo derivative holds an alpha, Opaque "
    "otherwise): an alpha channel alone does not tell a cutout from a translucent surface, so no engine "
    "opacity behaviour is claimed; the consumer fixture (phase3.3_uze-consumer-fixture) decides it";

/// The receipt's JSON schema id.
inline constexpr std::string_view kReceiptSchema = "uzpainter/export-receipt/1";
/// `non_conformant.mode` of a diagnostic measure generation (decision 286), and its open item.
inline constexpr std::string_view kDiagnosticMeasureMode = "diagnostic-measure";
inline constexpr std::string_view kNonConformantNote =
    "NON-CONFORMANT: diagnostic measure export (decision 286), written past production's refusals; "
    "not Painter's output, never deliver it";
/// The manifest export block's open item of a generation relying on EXC-013 (above).
inline constexpr std::string_view kIslandPaddingNote =
    "RELIES ON EXC-013 v1 (decision 414): the `infinite` padding outside the UV islands of the listed files is "
    "not Painter's (the exact rule is phase4.1_export-island-padding-exact); every covered texel is exact";
/// The manifest export block's open item of a generation relying on EXC-014 (above).
inline constexpr std::string_view kIslandNormalNote =
    "RELIES ON EXC-014 v1 (decision 417): the covered island-edge texels of the listed combined virtual normals "
    "(covered, with an uncovered 8-neighbour) read the Height outside the UV islands and are not Painter's (the "
    "exact Height is phase4.1_export-island-padding-exact); every other covered texel is exact";
/// `non_conformant.undecided[].rule`: the uncovered texels of a combined virtual normal with a
/// bound Normal mesh map (write.h, decision 308).
inline constexpr std::string_view kUndecidedNormalRule =
    "decision 276 items 4 (b) and (c): the mesh map at the texel combined with the padded mesh-free normal "
    "encoded in OpenGL, normalise(reoriented(decode(F), decode(M))), is the best-known form, not recorded "
    "(decision 308)";

/// The application that publishes: ARC-11's app version and build, supplied by the caller (the
/// application or the test harness), never empty.
struct BuildIdentity {
    std::string appVersion;
    std::string build;
};

/// What a receipt is built from.
struct ReceiptInputs {
    const core::Project& project;
    std::int64_t revision = 0;
    const ExportPlan& plan;
    /// In plan order.
    const std::vector<EncodedFile>& encoded;
    /// The generation's id and the publication's moment (RFC 3339, UTC).
    std::string generation;
    std::string moment;
    /// PlanContext::projectPath: empty while the project was never saved.
    std::string projectPath;
    BuildIdentity identity;
    std::set<std::string> resourceHashes;
    evaluator::ExecutionIdentity execution{};
    core::json::Array proceduralSnapshots{};
};

/// The receipt (see above).
[[nodiscard]] core::json::Object BuildReceipt(const ReceiptInputs& inputs);

/// The SHA-256 of every resource the files of `plan` read (see above). Fails with the failures of
/// the DAG builders.
[[nodiscard]] render::Result<std::set<std::string>> ReadResourceHashes(const core::Project& project,
                                                                       const ExportPlan& plan,
                                                                       const evaluator::TemplateLibrary& templates,
                                                                       std::string_view templateId,
                                                                       const evaluator::IProceduralSourceProvider* procedurals = nullptr,
                                                                       core::json::Array* snapshots = nullptr);

/// A delivered file as a receipt lists it.
struct ReceiptFile {
    /// The plan's relativePath: the file's name under the generation's `files/`.
    std::string path;
    std::uint64_t bytes = 0;
    std::string sha256;
};

/// The part of a receipt that verifies a generation.
struct ReceiptSummary {
    std::string generation;
    std::string planHash;
    std::vector<ReceiptFile> files;
};

/// Reads the schema, generation, plan hash and files of a receipt's text. Throws
/// `core::ManifestError` when the text is not a receipt of `kReceiptSchema`, a field is missing or
/// mistyped, a hash is not lower-case SHA-256, or a path is not a relative path within the
/// generation.
[[nodiscard]] ReceiptSummary ReadReceipt(std::string_view text);

/// True when `path` is a `/`-separated relative path without empty, `.` or `..` components, a
/// drive, a backslash or a leading slash.
[[nodiscard]] bool IsDeliveryPath(std::string_view path);

}  // namespace uzp::exporter
