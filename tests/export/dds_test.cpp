// CPU JSON driver: Python independently reads DDS headers and decodes BC blocks with Pillow.
#include "../no_error_dialogs.h"

#include <algorithm>
#include <fstream>
#include <iostream>
#include <iterator>
#include <mutex>
#include <stdexcept>
#include <string>
#include <variant>

#include "export/cook_dds.h"
#include "export/dds.h"
#include "uzp_core/manifest/json.h"

namespace ex = uzp::exporter;
namespace json = uzp::core::json;

class RecordingEncoder final : public ex::BcEncoder {
public:
    explicit RecordingEncoder(bool fail) : fail_(fail) {}
    std::string_view Name() const override { return ex::EtcpakEncoder().Name(); }
    std::string_view Settings(ex::BcFormat format) const override {
        return ex::EtcpakEncoder().Settings(format);
    }
    void EncodeBlockRows(ex::BcFormat format, const uint32_t* src, uint32_t width,
                         uint32_t rows, uint8_t* dst) const override {
        if (fail_) throw std::runtime_error("encoder reached");
        json::Array pixels;
        for (uint64_t i = 0; i < uint64_t(width) * rows * 4; ++i) {
            for (unsigned c = 0; c < 4; ++c) pixels.emplace_back(int((src[i] >> (8 * c)) & 255));
        }
        {
            std::lock_guard lock(mutex_);
            calls_.emplace_back(json::Object{{"format", int(format)}, {"width", int(width)},
                                            {"blockRows", int(rows)}, {"rgba", std::move(pixels)}});
        }
        ex::EtcpakEncoder().EncodeBlockRows(format, src, width, rows, dst);
    }
    json::Array Calls() const { return calls_; }
private:
    bool fail_;
    mutable std::mutex mutex_;
    mutable json::Array calls_;
};

int main(int argc, char** argv) {
    try {
        if (argc != 2) throw std::invalid_argument("expected one JSON request path");
        std::ifstream stream(argv[1], std::ios::binary);
        if (!stream) throw std::invalid_argument("cannot read request");
        const std::string text{std::istreambuf_iterator<char>(stream), {}};
        const auto request = json::Parse(text);
        const auto& object = std::get<json::Object>(request.data);
        const auto integer = [&](const char* key) {
            return std::get<int64_t>(object.at(key).data);
        };
        const auto format = static_cast<ex::BcFormat>(integer("format"));
        const auto width = static_cast<uint32_t>(integer("width"));
        const auto height = static_cast<uint32_t>(integer("height"));
        ex::Dds result;
        json::Array calls;
        if (std::get<std::string>(object.at("operation").data) == "raw") {
            std::vector<std::vector<uint8_t>> mips;
            const auto& sizes = std::get<json::Array>(object.at("sizes").data);
            for (size_t i = 0; i < sizes.size(); ++i) {
                const auto size = std::get<int64_t>(sizes[i].data);
                if (size < 0 || size > 1048576) throw std::invalid_argument("driver payload limit");
                mips.emplace_back(static_cast<size_t>(size), static_cast<uint8_t>(17 + i));
            }
            result = ex::WriteDdsFile(format, width, height, mips);
        } else {
            ex::Rgba16Image image{width, height, {}};
            for (const auto& code : std::get<json::Array>(object.at("rgba").data)) {
                image.rgba.push_back(static_cast<uint16_t>(std::get<int64_t>(code.data)));
            }
            ex::DdsSpec spec;
            spec.format = format;
            spec.mips.mapClass = static_cast<ex::MipClass>(integer("mapClass"));
            if (object.contains("alphaThreshold")) {
                const auto& value = object.at("alphaThreshold");
                spec.mips.alphaThreshold = value.IsDouble() ? std::get<double>(value.data)
                    : static_cast<double>(std::get<int64_t>(value.data));
            }
            RecordingEncoder encoder(object.contains("failEncoder"));
            result = ex::CookDds(encoder, image, spec,
                static_cast<uint32_t>(object.contains("threads") ? integer("threads") : 1));
            calls = encoder.Calls();
        }
        json::Array bytes, mips;
        for (uint8_t byte : result.bytes) bytes.emplace_back(int(byte));
        for (const auto& mip : result.metadata.mips) {
            mips.emplace_back(json::Object{{"offset", mip.offset}, {"size", mip.size},
                {"width", int64_t(mip.width)}, {"height", int64_t(mip.height)}});
        }
        std::cout << json::WriteCanonical(json::Object{
            {"bytes", std::move(bytes)}, {"mips", std::move(mips)}, {"calls", std::move(calls)},
            {"format", int(result.metadata.format)}, {"srgb", result.metadata.srgb},
            {"width", int64_t(result.metadata.width)}, {"height", int64_t(result.metadata.height)}}) << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cout << json::WriteCanonical(json::Object{{"error", error.what()}}) << '\n';
        return 1;
    }
}
