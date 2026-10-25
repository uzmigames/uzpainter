#include "uzp_core/types/resource_url.h"

#include <cstdio>

#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

namespace uzp::core {

namespace {

constexpr std::string_view kResourcePrefix = "resource://project/";
constexpr std::string_view kVersionQuery = "?version=";
constexpr std::string_view kAssetPrefix = "uzasset://";

bool Unreserved(char c) {
    return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' ||
           c == '.' || c == '_' || c == '~';
}

bool AssetNameChar(char c) {
    return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '.' || c == '-';
}

bool AssetVersionChar(char c) {
    return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' ||
           c == '.' || c == '+' || c == '-';
}

template <typename Pred>
bool AllOf(std::string_view text, Pred pred) {
    if (text.empty()) return false;
    for (const char c : text) {
        if (!pred(c)) return false;
    }
    return true;
}

int HexValue(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

}  // namespace

std::string FormatResourceUrl(const ProjectResourceUrl& url) {
    if (url.name.empty()) throw ValueError("a resource URL needs a non-empty name");
    if (!IsSha256Hex(url.sha256)) throw ValueError("a resource URL needs a lower-case SHA-256");
    std::string out(kResourcePrefix);
    for (const char c : url.name) {
        if (Unreserved(c)) {
            out += c;
        } else {
            char buf[4];
            std::snprintf(buf, sizeof(buf), "%%%02X", static_cast<unsigned char>(c));
            out += buf;
        }
    }
    return out + std::string(kVersionQuery) + url.sha256;
}

ProjectResourceUrl ParseResourceUrl(std::string_view text) {
    const auto fail = [&]() -> ProjectResourceUrl {
        throw ValueError("not a project resource URL (resource://project/<name>?version=<sha256>): " +
                         std::string(text));
    };
    if (!text.starts_with(kResourcePrefix)) return fail();
    const std::string_view rest = text.substr(kResourcePrefix.size());
    const std::size_t query = rest.find(kVersionQuery);
    if (query == std::string_view::npos) return fail();
    const std::string_view encoded = rest.substr(0, query);
    ProjectResourceUrl url;
    url.sha256 = std::string(rest.substr(query + kVersionQuery.size()));
    if (!IsSha256Hex(url.sha256)) return fail();
    for (std::size_t i = 0; i < encoded.size(); ++i) {
        if (encoded[i] == '%') {
            if (i + 2 >= encoded.size()) return fail();
            const int hi = HexValue(encoded[i + 1]);
            const int lo = HexValue(encoded[i + 2]);
            if (hi < 0 || lo < 0) return fail();
            url.name += static_cast<char>(hi * 16 + lo);
            i += 2;
        } else if (Unreserved(encoded[i])) {
            url.name += encoded[i];
        } else {
            return fail();
        }
    }
    if (url.name.empty()) return fail();
    return url;
}

std::string FormatAssetUrl(const AssetUrl& url) {
    if (!AllOf(url.family, AssetNameChar) || !AllOf(url.id, AssetNameChar) ||
        !AllOf(url.version, AssetVersionChar)) {
        throw ValueError("an asset URL needs a family, an id and a version of the allowed characters");
    }
    return std::string(kAssetPrefix) + url.family + "/" + url.id + "@" + url.version;
}

AssetUrl ParseAssetUrl(std::string_view text) {
    const auto fail = [&]() -> AssetUrl {
        throw ValueError("not a pinned asset URL (uzasset://<family>/<id>@<version>): " +
                         std::string(text));
    };
    if (!text.starts_with(kAssetPrefix)) return fail();
    const std::string_view rest = text.substr(kAssetPrefix.size());
    const std::size_t slash = rest.find('/');
    const std::size_t at = rest.find('@');
    if (slash == std::string_view::npos || at == std::string_view::npos || at < slash) return fail();
    AssetUrl url{std::string(rest.substr(0, slash)), std::string(rest.substr(slash + 1, at - slash - 1)),
                 std::string(rest.substr(at + 1))};
    if (!AllOf(url.family, AssetNameChar) || !AllOf(url.id, AssetNameChar) ||
        !AllOf(url.version, AssetVersionChar)) {
        return fail();
    }
    return url;
}

bool IsObservationAsset(std::string_view text) {
    if (!text.starts_with(kAssetPrefix)) return false;
    const std::string_view rest = text.substr(kAssetPrefix.size());
    return rest.substr(0, rest.find_first_of("/@")) == kObservationFamily;
}

bool IsObservationPin(std::string_view text) {
    if (!IsObservationAsset(text)) return false;
    const std::string_view rest = text.substr(kAssetPrefix.size() + kObservationFamily.size());
    if (rest.size() != 1 + 64 + 2 || rest.front() != '/' || !rest.ends_with("@1")) return false;
    return AllOf(rest.substr(1, 64), [](char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); });
}

}  // namespace uzp::core
