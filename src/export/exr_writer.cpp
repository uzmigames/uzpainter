#include "export/exr_writer.h"

#include "tinyexr.h"

#include <cstdlib>
#include <cstring>
#include <memory>
#include <span>
#include <stdexcept>
#include <string>

namespace uzp::exporter {

namespace {

/// The channel names of a layout, in file order, and the interleaved component each one holds.
struct Channel {
    const char* name;
    uint32_t component;
};
constexpr Channel kGrey[] = {{"Y", 0}};
constexpr Channel kRgb[] = {{"B", 2}, {"G", 1}, {"R", 0}};
constexpr Channel kRgba[] = {{"A", 3}, {"B", 2}, {"G", 1}, {"R", 0}};

std::span<const Channel> ChannelsOf(uint32_t channels) {
    if (channels == 1) return kGrey;
    if (channels == 3) return kRgb;
    if (channels == 4) return kRgba;
    throw std::invalid_argument("exr: only grey, RGB and RGBA are written (decision 090)");
}

[[noreturn]] void Fail(std::string_view what, const char* err) {
    std::string message = "exr: " + std::string(what);
    if (err != nullptr) {
        message += ": ";
        message += err;
        FreeEXRErrorMessage(err);
    }
    throw std::runtime_error(message);
}

}  // namespace

std::string EncodeExr(const ExrImage& image) {
    if (image.width == 0 || image.height == 0) throw std::invalid_argument("exr: empty image");
    const std::span<const Channel> channels = ChannelsOf(image.channels);
    const size_t pixels = size_t{image.width} * image.height;
    if (image.values.size() != pixels * image.channels) {
        throw std::invalid_argument("exr: the value count does not match the image size");
    }
    std::vector<std::vector<float>> planes(channels.size(), std::vector<float>(pixels));
    std::vector<unsigned char*> planePointers(channels.size());
    std::vector<EXRChannelInfo> infos(channels.size());
    std::vector<int> pixelTypes(channels.size(), TINYEXR_PIXELTYPE_FLOAT);
    for (size_t c = 0; c < channels.size(); ++c) {
        for (size_t p = 0; p < pixels; ++p) planes[c][p] = image.values[p * image.channels + channels[c].component];
        planePointers[c] = reinterpret_cast<unsigned char*>(planes[c].data());
        std::strncpy(infos[c].name, channels[c].name, sizeof(infos[c].name) - 1);
    }
    EXRHeader header;
    InitEXRHeader(&header);
    header.num_channels = static_cast<int>(channels.size());
    header.channels = infos.data();
    header.pixel_types = pixelTypes.data();
    header.requested_pixel_types = pixelTypes.data();
    header.compression_type = TINYEXR_COMPRESSIONTYPE_PIZ;
    EXRImage exr;
    InitEXRImage(&exr);
    exr.images = planePointers.data();
    exr.num_channels = static_cast<int>(channels.size());
    exr.width = static_cast<int>(image.width);
    exr.height = static_cast<int>(image.height);
    unsigned char* memory = nullptr;
    const char* err = nullptr;
    const size_t size = SaveEXRImageToMemory(&exr, &header, &memory, &err);
    if (size == 0 || memory == nullptr) Fail("SaveEXRImageToMemory failed", err);
    const std::unique_ptr<unsigned char, decltype(&std::free)> owned(memory, &std::free);
    return {reinterpret_cast<const char*>(memory), size};
}

ExrImage DecodeExr(std::string_view file) {
    const auto* bytes = reinterpret_cast<const unsigned char*>(file.data());
    EXRVersion version;
    if (ParseEXRVersionFromMemory(&version, bytes, file.size()) != TINYEXR_SUCCESS) {
        throw std::runtime_error("exr: not an OpenEXR file");
    }
    if (version.tiled || version.multipart || version.non_image) {
        throw std::runtime_error("exr: not a single-part scanline image");
    }
    EXRHeader header;
    InitEXRHeader(&header);
    const char* err = nullptr;
    if (ParseEXRHeaderFromMemory(&header, &version, bytes, file.size(), &err) != TINYEXR_SUCCESS) {
        Fail("ParseEXRHeaderFromMemory failed", err);
    }
    const std::unique_ptr<EXRHeader, decltype(&FreeEXRHeader)> headerOwner(&header, &FreeEXRHeader);
    const std::span<const Channel> channels = ChannelsOf(static_cast<uint32_t>(header.num_channels));
    for (size_t c = 0; c < channels.size(); ++c) {
        if (std::strcmp(header.channels[c].name, channels[c].name) != 0 ||
            header.pixel_types[c] != TINYEXR_PIXELTYPE_FLOAT) {
            throw std::runtime_error("exr: the channels are not FLOAT Y; B, G, R; or A, B, G, R");
        }
    }
    EXRImage exr;
    InitEXRImage(&exr);
    if (LoadEXRImageFromMemory(&exr, &header, bytes, file.size(), &err) != TINYEXR_SUCCESS) {
        Fail("LoadEXRImageFromMemory failed", err);
    }
    const std::unique_ptr<EXRImage, decltype(&FreeEXRImage)> imageOwner(&exr, &FreeEXRImage);
    ExrImage image;
    image.width = static_cast<uint32_t>(exr.width);
    image.height = static_cast<uint32_t>(exr.height);
    image.channels = static_cast<uint32_t>(channels.size());
    const size_t pixels = size_t{image.width} * image.height;
    image.values.resize(pixels * image.channels);
    for (size_t c = 0; c < channels.size(); ++c) {
        const auto* plane = reinterpret_cast<const float*>(exr.images[c]);
        for (size_t p = 0; p < pixels; ++p) image.values[p * image.channels + channels[c].component] = plane[p];
    }
    return image;
}

}  // namespace uzp::exporter
