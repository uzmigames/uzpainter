#pragma once

// `format_version` of a `.uzp` file (`docs/architecture/09-project-file-format.md` §5): semver
// in `meta.format_version` and in the manifest's `versions.format_version`. A reader refuses a
// newer major (and an older one, for which no migration exists) with an explicit error, reads a
// newer minor of its major as it is (unknown keys are kept verbatim by the manifest reader), and
// migrates an older minor in memory: the migrated manifest reaches the file only with the next
// commit, which writes it as a new revision and updates `meta.format_version`; the file is left
// untouched until then.

#include <compare>
#include <functional>
#include <string>
#include <string_view>
#include <vector>

#include "uzp_core/manifest/json.h"

namespace uzp::store {

struct FormatVersion {
    int major = 0;
    int minor = 0;
    int patch = 0;

    /// Throws `StoreError(version)` unless `text` is `<major>.<minor>.<patch>`.
    static FormatVersion Parse(std::string_view text);
    std::string ToString() const;
    auto operator<=>(const FormatVersion&) const = default;
};

/// One migration step: rewrites a manifest object of minor `from_minor` to minor `from_minor + 1`
/// of the reader's major.
struct Migration {
    int from_minor = 0;
    std::function<void(core::json::Object& manifest)> apply;
};

/// What a reader reads: its own version and the steps from each older minor of its major.
struct VersionPolicy {
    FormatVersion reader;
    std::vector<Migration> migrations;

    /// This build: `kFormatVersion` (`uzp_core/types/project.h`) and its migrations (none: 1.0
    /// is the first format).
    static VersionPolicy Current();
};

/// Throws `StoreError(version)` when `file` has a major other than the reader's.
void CheckReadable(const FormatVersion& file, const VersionPolicy& policy);

/// The manifest as this reader reads it. An older minor (or patch) is migrated step by step and
/// stamped with the reader's version; a newer minor or the same version is returned unchanged.
/// `migrated` tells whether anything changed. Throws `StoreError(version)` when a step is
/// missing or the manifest's `versions.format_version` disagrees with `meta.format_version`.
core::json::Value MigrateManifest(core::json::Value manifest, const FormatVersion& file, const VersionPolicy& policy,
                                  bool& migrated);

}  // namespace uzp::store
