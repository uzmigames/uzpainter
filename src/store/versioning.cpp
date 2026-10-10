#include "store/versioning.h"

#include <charconv>

#include "store/container.h"
#include "uzp_core/types/project.h"

namespace uzp::store {

using core::json::Object;
using core::json::Value;

FormatVersion FormatVersion::Parse(std::string_view text) {
    FormatVersion v;
    int* parts[] = {&v.major, &v.minor, &v.patch};
    const char* p = text.data();
    const char* end = text.data() + text.size();
    for (int i = 0; i < 3; ++i) {
        const auto [next, ec] = std::from_chars(p, end, *parts[i]);
        if (ec != std::errc() || next == p || *parts[i] < 0) break;
        p = next;
        if (i == 2) {
            if (p == end) return v;
            break;
        }
        if (p == end || *p != '.') break;
        ++p;
    }
    throw StoreError(StoreError::Code::version, "format_version '" + std::string(text) + "' is not a semantic version");
}

std::string FormatVersion::ToString() const {
    return std::to_string(major) + "." + std::to_string(minor) + "." + std::to_string(patch);
}

VersionPolicy VersionPolicy::Current() { return VersionPolicy{FormatVersion::Parse(core::kFormatVersion), {}}; }

void CheckReadable(const FormatVersion& file, const VersionPolicy& policy) {
    if (file.major > policy.reader.major) {
        throw StoreError(StoreError::Code::version, "format_version " + file.ToString() +
                                                        " is newer than this reader supports (" +
                                                        policy.reader.ToString() + "): major " +
                                                        std::to_string(file.major) + " cannot be read");
    }
    if (file.major < policy.reader.major) {
        throw StoreError(StoreError::Code::version, "format_version " + file.ToString() +
                                                        " has no migration to major " +
                                                        std::to_string(policy.reader.major));
    }
}

Value MigrateManifest(Value manifest, const FormatVersion& file, const VersionPolicy& policy, bool& migrated) {
    migrated = false;
    CheckReadable(file, policy);
    auto* root = std::get_if<Object>(&manifest.data);
    if (root == nullptr) throw StoreError(StoreError::Code::corrupt, "the manifest is not a JSON object");
    const auto versions = root->find("versions");
    const Value* stamped = nullptr;
    if (versions != root->end() && versions->second.IsObject()) {
        const Object& v = std::get<Object>(versions->second.data);
        if (const auto it = v.find("format_version"); it != v.end()) stamped = &it->second;
    }
    if (stamped == nullptr || !stamped->IsString() ||
        FormatVersion::Parse(std::get<std::string>(stamped->data)) != file) {
        throw StoreError(StoreError::Code::version,
                         "the manifest's versions.format_version does not match meta.format_version " + file.ToString());
    }
    if (file >= policy.reader) return manifest;
    for (int minor = file.minor; minor < policy.reader.minor; ++minor) {
        const Migration* step = nullptr;
        for (const Migration& m : policy.migrations) {
            if (m.from_minor == minor) step = &m;
        }
        if (step == nullptr) {
            throw StoreError(StoreError::Code::version, "no migration from format " + std::to_string(file.major) + "." +
                                                            std::to_string(minor) + " to " +
                                                            std::to_string(file.major) + "." + std::to_string(minor + 1));
        }
        step->apply(*root);
    }
    auto& v = (*root)["versions"];
    if (!v.IsObject()) throw StoreError(StoreError::Code::version, "a migration removed the manifest's versions");
    std::get<Object>(v.data)["format_version"] = policy.reader.ToString();
    migrated = true;
    return manifest;
}

}  // namespace uzp::store
