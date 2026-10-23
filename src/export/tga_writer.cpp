#include "export/tga_writer.h"

#include <limits>
#include <stdexcept>

#define STB_IMAGE_WRITE_STATIC
#define STB_IMAGE_WRITE_IMPLEMENTATION
#define STBI_WRITE_NO_STDIO
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wunused-function"
#pragma clang diagnostic ignored "-Wmissing-field-initializers"
#include <stb_image_write.h>
#pragma clang diagnostic pop

namespace uzp::exporter {

std::string EncodeTga(const TgaImage& image) {
    if (image.width == 0 || image.height == 0 || image.width > 65535 || image.height > 65535 ||
        image.channels < 1 || image.channels > 4) {
        throw std::invalid_argument("TGA8: dimensions must be 1..65535 and channels 1..4");
    }
    const uint64_t size = uint64_t{image.width} * image.height * image.channels;
    if (size > std::numeric_limits<int>::max() || size != image.samples.size()) {
        throw std::invalid_argument("TGA8: sample count mismatch or raster exceeds signed-int indexing");
    }
    std::string bytes;
    const auto write = [](void* context, void* data, int count) {
        static_cast<std::string*>(context)->append(static_cast<const char*>(data), static_cast<size_t>(count));
    };
    // stb's globals are private to this unit and never changed: RLE on, vertical flip off.
    if (!stbi_write_tga_to_func(write, &bytes, static_cast<int>(image.width), static_cast<int>(image.height),
                               static_cast<int>(image.channels), image.samples.data())) {
        throw std::runtime_error("TGA8: stb failed to encode the image");
    }
    return bytes;
}

}  // namespace uzp::exporter
