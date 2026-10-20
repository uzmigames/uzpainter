#pragma once

// The shipped export presets and their compatibility alias table (docs/architecture/08-export.md
// §4; task phase1.17_export-presets, decision 095).
//
// UzPainter ships UzmiGames-authored presets in `assets/export-presets/<id>.json`, each one
// `exportPresets[]` entry of the documented configuration form ({name, maps}) whose `name` is its
// UzPainter id, beside its provenance record `<id>.provenance.json`
// (`uzpainter/export-preset-provenance/1`, `src/export/preset-provenance.schema.json`). A preset
// reference (`defaultExportPreset`, `exportList[].exportPreset`) that names no inline preset
// resolves here: a shipped id, a Painter preset name of the alias table, or Painter's
// `resource://starter_assets/<Painter name>` URL with no query or a recorded `?version=`. Painter
// names are internal compatibility aliases only (CLR-06): the shipped files carry UzPainter ids.
//
// A preset whose layout no Painter recording confirms yet (provenance `parity.layout`
// "unconfirmed") is refused with `core::NotYetSupported` naming the recording that confirms it,
// before anything is planned or written.

#include <cstdint>
#include <filesystem>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include "export/config.h"

namespace uzp::exporter {

/// One alias: a Painter preset name that keeps working as a preset reference, the shipped preset
/// that answers to it, and the `?version=` values of its `resource://starter_assets/` URL that are
/// recorded (UzmiGames' own observations, the preset's provenance record), and the recording that
/// settles any other query.
struct PresetAlias {
    std::string_view painterName;
    std::string_view presetId;
    std::span<const std::string_view> versions;
    std::string_view recording;
};

/// The alias table, in shipped-preset order.
[[nodiscard]] std::span<const PresetAlias> PresetAliases();
/// The ids of the shipped presets (`assets/export-presets/<id>.json`).
[[nodiscard]] std::span<const std::string_view> ShippedPresetIds();

/// The shipped preset a preset reference names: its id, an alias's Painter name, or
/// `resource://starter_assets/<Painter name>` with no query or `?version=<recorded version>`;
/// nullopt for any other text. Throws `core::NotYetSupported` naming the alias's recording (R-095,
/// or R-314 for the glTF preset) for an alias's URL with an unrecorded query (decision 095).
[[nodiscard]] std::optional<std::string> ShippedPresetId(std::string_view reference);

/// Whether a shipped preset's layout is confirmed (provenance `parity.layout`).
enum class PresetLayout : uint8_t {
    /// Defined by a UzmiGames pipeline script, which is its own source.
    pipeline,
    /// Confirmed against Painter's recorded outputs for the preset it answers to.
    confirmed,
    /// Written by hand from public sources; no recording confirms it yet.
    unconfirmed,
    /// Defined by UzmiGames from a consumer's format definition, with no Painter preset that
    /// answers to it (the UzEngine preset, 08-export.md §4): its `uzengine` targets.
    consumer,
};

struct ShippedPreset {
    std::string id;
    /// The preset, `name` == `id`.
    PresetSpec spec;
    PresetLayout layout = PresetLayout::unconfirmed;
    /// The recordings that settle the preset's pending parity (provenance `parity.pending`).
    std::vector<std::string> pendingRecordings;
};

/// Reads `<directory>/<id>.json` and `<directory>/<id>.provenance.json`. Throws
/// `core::ManifestError` naming the preset when either is missing or malformed (the preset is
/// parsed as an `exportPresets[]` entry, so its errors are `core::ValueError`s naming the file),
/// when the preset's `name` is not its id, or when the record names another preset.
[[nodiscard]] ShippedPreset LoadShippedPreset(const std::filesystem::path& directory, std::string_view id);

/// `assets/export-presets` beside the running executable.
[[nodiscard]] std::filesystem::path DefaultPresetDirectory();

}  // namespace uzp::exporter
