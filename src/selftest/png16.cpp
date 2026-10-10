// Stage `png16`: the 16-bit pattern written as a 16-bit grayscale PNG with spng and decoded back
// from the file, compared bit for bit (no 8-bit truncation). The source is the GPU readback of
// `compute-readback` when that stage ran, else the CPU pattern (runs without a GPU).

#include "hardware_slice.h"

#include <spng.h>

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <memory>
#include <string>

namespace uzp::selftest {

namespace {

struct SpngContext {
    spng_ctx* ctx;
    explicit SpngContext(int flags) : ctx(spng_ctx_new(flags)) {}
    ~SpngContext() { spng_ctx_free(ctx); }
    SpngContext(const SpngContext&) = delete;
    SpngContext& operator=(const SpngContext&) = delete;
};

std::string SpngError(const char* call, int code) {
    return std::string(call) + " failed: " + spng_strerror(code);
}

}  // namespace

StageOutcome RunPng16(SelftestContext& context) {
    const bool fromGpu = !context.readback.empty();
    return Png16RoundTrip(fromGpu ? context.readback : ExpectedPattern(),
                          fromGpu ? "gpu-readback" : "cpu-pattern",
                          context.options.outDir / "selftest-pattern16.png");
}

StageOutcome Png16RoundTrip(const std::vector<uint16_t>& source, const char* sourceName,
                            const std::filesystem::path& file) {
    const std::vector<uint16_t> expected = ExpectedPattern();
    Details details = {{"source", sourceName},
                       {"file", file.string()},
                       {"spng_version", spng_version_string()}};

    // Encode: 16-bit grayscale; SPNG_FMT_PNG takes host-endian samples and writes big-endian.
    {
        SpngContext enc(SPNG_CTX_ENCODER);
        if (!enc.ctx) return StageOutcome::Fail("spng encoder context not created", details);
        int rc = spng_set_option(enc.ctx, SPNG_ENCODE_TO_BUFFER, 1);
        spng_ihdr ihdr{};
        ihdr.width = kPatternWidth;
        ihdr.height = kPatternHeight;
        ihdr.bit_depth = 16;
        ihdr.color_type = SPNG_COLOR_TYPE_GRAYSCALE;
        if (rc == 0) rc = spng_set_ihdr(enc.ctx, &ihdr);
        if (rc == 0) {
            rc = spng_encode_image(enc.ctx, source.data(), source.size() * sizeof(uint16_t),
                                   SPNG_FMT_PNG, SPNG_ENCODE_FINALIZE);
        }
        if (rc != 0) return StageOutcome::Fail(SpngError("spng_encode_image", rc), details);
        size_t size = 0;
        int error = 0;
        std::unique_ptr<void, decltype(&std::free)> png(
            spng_get_png_buffer(enc.ctx, &size, &error), &std::free);
        if (!png) return StageOutcome::Fail(SpngError("spng_get_png_buffer", error), details);
        std::ofstream out(file, std::ios::binary);
        out.write(static_cast<const char*>(png.get()), static_cast<std::streamsize>(size));
        out.close();
        if (!out) return StageOutcome::Fail("cannot write " + file.string(), details);
        details.emplace_back("png_bytes", std::to_string(size));
    }

    // Decode the file back.
    std::ifstream in(file, std::ios::binary);
    const std::vector<char> bytes((std::istreambuf_iterator<char>(in)),
                                  std::istreambuf_iterator<char>());
    if (bytes.empty()) return StageOutcome::Fail("cannot read back " + file.string(), details);
    SpngContext dec(0);
    if (!dec.ctx) return StageOutcome::Fail("spng decoder context not created", details);
    int rc = spng_set_png_buffer(dec.ctx, bytes.data(), bytes.size());
    spng_ihdr ihdr{};
    if (rc == 0) rc = spng_get_ihdr(dec.ctx, &ihdr);
    if (rc != 0) return StageOutcome::Fail(SpngError("spng_get_ihdr", rc), details);
    details.emplace_back("decoded_bit_depth", std::to_string(ihdr.bit_depth));
    if (ihdr.width != kPatternWidth || ihdr.height != kPatternHeight || ihdr.bit_depth != 16 ||
        ihdr.color_type != SPNG_COLOR_TYPE_GRAYSCALE) {
        return StageOutcome::Fail("decoded header is not " + std::to_string(kPatternWidth) + "x" +
                                      std::to_string(kPatternHeight) + " 16-bit grayscale",
                                  details);
    }
    size_t decodedSize = 0;
    rc = spng_decoded_image_size(dec.ctx, SPNG_FMT_PNG, &decodedSize);
    if (rc != 0 || decodedSize != expected.size() * sizeof(uint16_t)) {
        return StageOutcome::Fail("decoded image size " + std::to_string(decodedSize) +
                                      " is not 16 bits per sample",
                                  details);
    }
    std::vector<uint16_t> decoded(expected.size());
    rc = spng_decode_image(dec.ctx, decoded.data(), decodedSize, SPNG_FMT_PNG, 0);
    if (rc != 0) return StageOutcome::Fail(SpngError("spng_decode_image", rc), details);

    size_t mismatches = 0;
    for (size_t i = 0; i < decoded.size(); ++i) mismatches += decoded[i] != expected[i];
    details.emplace_back("mismatches", std::to_string(mismatches));
    if (mismatches != 0) {
        return StageOutcome::Fail(std::to_string(mismatches) +
                                      " decoded samples differ from the 16-bit pattern",
                                  details);
    }
    return StageOutcome::Pass(std::move(details));
}

}  // namespace uzp::selftest
