#pragma once

// Slice C1 of the native F gate (`docs/filter-observations-v2.md` section 11, F1-F4): admission
// and envelope only. It reads the admitted private evidence of one `filter-context-settings-a`
// capture from the private oracle store, under the compiled pins (`filter_gate_pins.h`), and
// checks it as `tools/parity/filter_context_settings_validation.py` (`manifest_request`, the
// receipt checks of `filter_context_validation.py`, the settings producer) specifies. The result
// is NOT a `VerifiedFilterContext`: panels, images, trace, context, settings and the H binding are
// later slices.
//
// - The public manifest is not an admitted blob: its bytes come from the caller and stay untrusted
//   until they match the caller's reference, their typed invariants equal the fixed request's and
//   each of their twelve references joins an admitted store entry.
// - All twelve store entries are checked before the first private blob is read. Every blob is
//   read whole through a handle fenced inside the store and rehashed; its size is checked.
// - The envelope registry is read at its locator before admission and again after it, on success
//   and on refusal. Its raw bytes must be the reviewed registry compiled into the gate, and its
//   current entry must stay typed-equal. A drift supersedes any other outcome.
// - Every comparison is typed (canonical JSON), so an integer never equals a double and +0 never
//   equals -0.
// - A refusal is `F_CAPTURE_INVALID` with fixed detail codes below. It never carries a path, an
//   observed value or a caller's text.

#include <cstdint>
#include <expected>
#include <filesystem>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "procedural/filter_gate_pins.h"
#include "procedural/filter_observation_import_v2.h"
#include "uzp_core/manifest/json.h"

namespace uzp::procedural {

/// The refusal reason of every F gate check.
inline constexpr std::string_view kFilterCaptureInvalid = "F_CAPTURE_INVALID";

/// The detail codes of slice C1 (the Python validator's stable codes, plus the store's own). A
/// registry drift seen after another refusal reports `F_SETTINGS_REGISTRY_DRIFT:<that code>`.
namespace filter_gate {
inline constexpr std::string_view kStoreUnavailable = "F_SETTINGS_STORE_UNAVAILABLE";
inline constexpr std::string_view kRegistryUnavailable = "F_SETTINGS_REGISTRY_UNAVAILABLE";
inline constexpr std::string_view kRegistryDrift = "F_SETTINGS_REGISTRY_DRIFT";
inline constexpr std::string_view kManifest = "F_SETTINGS_MANIFEST";
inline constexpr std::string_view kRecipe = "F_SETTINGS_RECIPE";
inline constexpr std::string_view kReferences = "F_SETTINGS_REFERENCES";
inline constexpr std::string_view kReceipt = "F_SETTINGS_RECEIPT";
inline constexpr std::string_view kProducer = "F_SETTINGS_PRODUCER";
inline constexpr std::string_view kImageBytes = "F_SETTINGS_IMAGE_BYTES";
inline constexpr std::string_view kInputs = "F_SETTINGS_INPUTS";
inline constexpr std::string_view kInputUnavailable = "F_SETTINGS_INPUT_UNAVAILABLE";
inline constexpr std::string_view kInputBytes = "F_SETTINGS_INPUT_BYTES";
}  // namespace filter_gate

/// One `private_records` reference of the manifest: exactly `record_id, kind, sha256, size_bytes`.
struct AdmittedRef {
    std::string record_id;
    std::string kind;
    std::string sha256;
    std::int64_t size_bytes = 0;

    bool operator==(const AdmittedRef&) const = default;
};

/// The authored-tests-only route to admission under authored pins and to the store's private test
/// seams; declared here, defined once in the shared test header
/// `tests/export/filter_gate_test_support.h`, never in a production source.
struct FilterGateTestAccess;
class AdmittedFilterCapture;
class AdmittedHostCapture;

/// The private oracle store, read-only (`tools/parity/store/store.py`): `store.json`, the entries
/// `corpora/<build>/<golden>/<record id>.json` and the blobs `blobs/<first two hex>/<sha256>`,
/// plus the locator of the envelope registry (a location only, never a policy). It writes nothing
/// and never reports a path.
class OracleStoreReader {
public:
    /// The store at `root`. The folder exists, is not a reparse point, has no reparse-point
    /// ancestor and is outside any UzPainter checkout (no ancestor holds both `.git` and
    /// `build.zig`). Its `store.json` is exactly `{schema: uzpainter/parity/store/1, hash: sha256}`.
    /// `registry` locates `parity/envelopes/registry.json`; it is read only by admission.
    static std::expected<OracleStoreReader, ImportRefusal> Open(const std::filesystem::path& root,
                                                               const std::filesystem::path& registry);

    /// The entry of `ref` under `build_id` and `golden_id` exists, is exactly
    /// `uzpainter/parity/store-entry/1` with `painter_build_id, golden_id, record_id, kind, sha256,
    /// size_bytes, file_name`, names this build, golden and record, and equals `ref`. The ids are
    /// validated before any path is built; `file_name` is metadata, never a locator. Reads the entry
    /// only, never the blob.
    [[nodiscard]] std::optional<ImportRefusal> RequireAdmitted(std::string_view build_id, std::string_view golden_id,
                                                               const AdmittedRef& ref) const;

private:
    OracleStoreReader(std::filesystem::path root, std::wstring final_root, std::filesystem::path registry)
        : root_(std::move(root)), final_root_(std::move(final_root)), registry_(std::move(registry)) {}
    /// The whole blob named `sha256`, rehashed, with exactly `size_bytes` bytes when given; nothing
    /// when it is missing, unreadable, fenced out, short, long or fails its hash.
    [[nodiscard]] std::optional<std::string> Blob(std::string_view sha256, std::optional<std::int64_t> size_bytes) const;
    /// The registry's raw bytes at its locator, or nothing.
    [[nodiscard]] std::optional<std::string> RegistryBytes() const;
    [[nodiscard]] std::optional<std::string> SnapshotAdmissionBytes(std::string_view capture_id,
                                                                  std::string_view policy_sha256) const;
    [[nodiscard]] std::optional<std::string> SnapshotPolicyBytes(std::string_view policy_sha256) const;

    friend class AdmittedFilterCapture;
    friend class AdmittedHostCapture;
    friend struct FilterGateTestAccess;
    std::filesystem::path root_;
    std::wstring final_root_;  ///< The root's final path (handle-resolved), the fence of every read.
    std::filesystem::path registry_;
    /// Private test seams, empty unless the test-only access sets them (no public setter, flag or
    /// override): `observe_` is told of every entry (`entry`), blob (`blob`) and registry
    /// (`registry`) read, before it happens; `before_final_registry_` runs once, right before
    /// admission's final registry read.
    std::function<void(std::string_view what)> observe_;
    std::function<void()> before_final_registry_;
};

/// The admitted evidence of one capture: the decoded manifest, record and environment, the ten
/// settings images' bytes by record id and the plane's bytes. No public constructor.
class AdmittedFilterCapture {
public:
    [[nodiscard]] const core::json::Object& Manifest() const { return manifest_; }
    /// The manifest's reference: exactly `kind` `filter_manifest`, `sha256`, `size_bytes`.
    [[nodiscard]] const core::json::Object& ManifestRef() const { return manifest_ref_; }
    [[nodiscard]] const core::json::Object& Record() const { return record_; }
    [[nodiscard]] const core::json::Object& Environment() const { return environment_; }
    /// The twelve references in their fixed order: the record, the environment, then the ten
    /// images in boundary order (configuration image, then physical size image).
    [[nodiscard]] const std::vector<AdmittedRef>& Refs() const { return refs_; }
    /// The bytes of one settings image reference (decoded by a later slice), or nothing.
    [[nodiscard]] const std::string* Image(std::string_view record_id) const;
    [[nodiscard]] const std::string& PlaneBytes() const { return plane_; }
    /// What the admission computed, hashes only: the manifest, record, environment and registry
    /// hashes, the envelope id, the producer and the gate's code hash.
    [[nodiscard]] core::json::Object Identity() const;

private:
    AdmittedFilterCapture() = default;
    /// The admission of `AdmitFilterCapture` under `pins` (the compiled pins on the real path),
    /// bracketed by the registry checks.
    static std::expected<AdmittedFilterCapture, ImportRefusal> Admit(std::string_view manifest_bytes,
                                                                     const core::json::Object& manifest_ref,
                                                                     const OracleStoreReader& store,
                                                                     const FilterGatePins& pins);
    /// The checks between the two registry reads, under the registry's current `entry`.
    static std::expected<AdmittedFilterCapture, ImportRefusal> AdmitUnder(std::string_view manifest_bytes,
                                                                          const core::json::Object& manifest_ref,
                                                                          const OracleStoreReader& store,
                                                                          const FilterGatePins& pins,
                                                                          const core::json::Object& entry);
    friend std::expected<AdmittedFilterCapture, ImportRefusal> AdmitFilterCapture(std::string_view,
                                                                                 const core::json::Object&,
                                                                                 const OracleStoreReader&);
    friend struct FilterGateTestAccess;
    core::json::Object manifest_;
    core::json::Object manifest_ref_;
    core::json::Object record_;
    core::json::Object environment_;
    std::vector<AdmittedRef> refs_;
    std::map<std::string, std::string, std::less<>> images_;
    std::string plane_;
    std::string registry_sha256_;
    std::string envelope_id_;
    std::string producer_;
};

/// Admits one capture under `CompiledFilterGatePins()`, in this order (a refusal stops at once):
/// 0. `kRegistryUnavailable` / `kRegistryDrift`: the registry at the store's locator is read; its
///    raw bytes must equal the compiled registry's, and its `current` entry is the approved envelope.
/// 1. `kManifest`: `manifest_ref` is exactly `kind` `filter_manifest`, a lowercase `sha256` and a
///    nonnegative `size_bytes` matching `manifest_bytes`. The bytes parse as strict JSON. Every
///    `private_records` item is a closed `private_record_ref`. `software.painter` is exactly
///    `product, version, build_id`. Without `private_records` and `software.painter`, the manifest
///    is typed-equal to the fixed request.
/// 2. `kRecipe`: the typed hash of `instruction_sequence` is recipe A's.
/// 3. `kReferences`: exactly twelve references with the fixed ids and kinds.
/// 4. `kReceipt`: all twelve store entries join before the first blob is read. Then the record and
///    environment blobs are read, rehashed and decoded. The record is closed `golden-private/1` at
///    its top level, key and recording shells. The environment is closed `oracle-environment/1`,
///    and the record's environment equals it.
/// 5. `kProducer`: `environment.recorder_version` is the compiled settings producer.
/// 6. `kReceipt`: the record's golden and tier `0`; the manifest's Painter declaration
///    (build_id is the entry's `painter_build`, version is its prefix before `+js-api.`, product
///    is the request's). The environment joins the entry by the Legacy rule (recorded basis, five
///    known fields, build, envelope hash in `envelope_sha256` plus `equivalent_envelopes`), with the
///    Legacy colour hash. The key holds the build, input pins, recipe hash, create settings plus
///    Legacy, Legacy defaults, no resources, no bake backend and no render state. The recordings
///    are exactly `r1 same_session`, `r2 after_save_reopen`, with one session id. The plane blob is
///    present.
/// 7. `kImageBytes`: the ten image blobs, rehashed with their sizes.
/// 8. `kInputs`, `kInputBytes`: the request's one `plane` input, read as the blob of its pinned
///    SHA-256 and rehashed.
/// 9. The registry is read again, on success and on refusal. Unreadable bytes, changed bytes or a
///    changed current entry give `kRegistryDrift` (`kRegistryDrift:<earlier code>` after a refusal).
std::expected<AdmittedFilterCapture, ImportRefusal> AdmitFilterCapture(std::string_view manifest_bytes,
                                                                     const core::json::Object& manifest_ref,
                                                                     const OracleStoreReader& store);

}  // namespace uzp::procedural
