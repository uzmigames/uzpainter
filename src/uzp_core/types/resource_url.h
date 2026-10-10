#pragma once

// Resource URL forms (`docs/architecture/03-project-model.md` §3):
//
// - `resource://project/<name>?version=<sha256>`: a project resource, valid across sessions and
//   machines. The name is percent-encoded except for RFC 3986 unreserved characters.
// - `uzasset://<family>/<id>@<version>`: a pinned procedural asset (`05-procedural-content.md`).
//   Family and id use [a-z0-9_.-]; the version uses [A-Za-z0-9_.+-].

#include <string>
#include <string_view>

namespace uzp::core {

struct ProjectResourceUrl {
    std::string name;
    std::string sha256;

    bool operator==(const ProjectResourceUrl&) const = default;
};

struct AssetUrl {
    std::string family;
    std::string id;
    std::string version;

    bool operator==(const AssetUrl&) const = default;
};

std::string FormatResourceUrl(const ProjectResourceUrl& url);
/// Throws `ValueError` when `text` is not a valid project resource URL.
ProjectResourceUrl ParseResourceUrl(std::string_view text);

std::string FormatAssetUrl(const AssetUrl& url);
/// Throws `ValueError` when `text` is not a valid pinned asset URL.
AssetUrl ParseAssetUrl(std::string_view text);

}  // namespace uzp::core
