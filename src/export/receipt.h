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

/// The receipt's JSON schema id.
inline constexpr std::string_view kReceiptSchema = "uzpainter/export-receipt/1";
/// `non_conformant.mode` of a diagnostic measure generation (decision 286), and its open item.
inline constexpr std::string_view kDiagnosticMeasureMode = "diagnostic-measure";
inline constexpr std::string_view kNonConformantNote =
    "NON-CONFORMANT: diagnostic measure export (decision 286), written past production's refusals; "
    "not Painter's output, never deliver it";
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
};

/// The receipt (see above).
[[nodiscard]] core::json::Object BuildReceipt(const ReceiptInputs& inputs);

/// The SHA-256 of every resource the files of `plan` read (see above). Fails with the failures of
/// the DAG builders.
[[nodiscard]] render::Result<std::set<std::string>> ReadResourceHashes(const core::Project& project,
                                                                       const ExportPlan& plan,
                                                                       const evaluator::TemplateLibrary& templates,
                                                                       std::string_view templateId);

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
