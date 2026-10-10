#pragma once

// Where the evaluator gets the bytes a bitmap source names (docs/architecture/03-project-model.md
// §3: resources are addressed by the SHA-256 of their bytes). The project store supplies the
// product's provider (P1-STORE); tests supply decoded fixtures.

#include "evaluator/tile_store.h"

#include <map>
#include <memory>
#include <optional>
#include <string>
#include <string_view>

namespace uzp::evaluator {

class IResourceProvider {
public:
    virtual ~IResourceProvider() = default;
    /// The decoded samples of the resource whose bytes hash to `sha256`, or null when unknown.
    [[nodiscard]] virtual std::shared_ptr<const DecodedImage> Fetch(std::string_view sha256) const = 0;
};

/// A provider over images registered by hash.
class MapResourceProvider final : public IResourceProvider {
public:
    void Add(std::string sha256, std::shared_ptr<const DecodedImage> image) {
        m_images[std::move(sha256)] = std::move(image);
    }
    std::shared_ptr<const DecodedImage> Fetch(std::string_view sha256) const override {
        const auto it = m_images.find(sha256);
        return it == m_images.end() ? nullptr : it->second;
    }

private:
    std::map<std::string, std::shared_ptr<const DecodedImage>, std::less<>> m_images;
};

}  // namespace uzp::evaluator
