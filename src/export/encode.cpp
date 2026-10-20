#include "export/encode.h"

#include "evaluator/arith.h"
#include "evaluator/cpu_store.h"
#include "evaluator/formats.h"
#include "evaluator/hwmath.h"
#include "evaluator/sources.h"
#include "export/exr_writer.h"
#include "export/guards.h"
#include "export/png_writer.h"
#include "uzp_core/types/errors.h"

#include <algorithm>
#include <array>
#include <stdexcept>

namespace uzp::exporter {

void CheckProcessing(const core::Project& project, const PlannedFile& file) {
    if (std::optional<std::string> refusal = ProcessingRefusal(project, file)) throw core::NotYetSupported(*refusal);
}

namespace {

/// The value a PNG writes for `v` of `channel`: a Height channel is written signed, v * 0.5 + 0.5
/// (recording R-090 P1: exact at 8 and 16 bits, decision 103).
float PngValue(const PlannedChannel& channel, float v) {
    const PlannedSource& s = channel.source;
    if (s.type == SourceType::documentMap && s.channel == core::ChannelType::Height) return v * 0.5f + 0.5f;
    return v;
}

/// Painter 12.1.5's sRGB encode of a linear value before its PNG write (decisions 091 and 126):
/// 12.92 x up to 0.0031308, else fma(1.055, exp2(0.41666 log2 x), -0.055) with the recording GPU's
/// log2 and exp2 (hwmath.h `Pow`: the product one float32 multiplication) and one fused rounding.
float SrgbExportEncode(float x) {
    if (x <= 0.0031308f) return 12.92f * x;
    return evaluator::arith::Fma(1.055f, evaluator::hw::Pow(x, 0.41666f), -0.055f);
}

/// The 16-bit PNG code of the operand of each sRGB8 code under OCIO with Painter's substance
/// config (encode.h `OcioSrgbPng16Code`): `export-ocio-encode` s3 BaseColor at PNG 16 (step 46)
/// against its PNG 8 (step 47), r1 and r2 identical.
constexpr uint16_t kOcioSrgbPng16[256] = {
    0u, 258u, 517u, 775u, 1033u, 1292u, 1551u, 1809u, 2067u, 2325u, 2584u, 2835u, 3073u, 3343u, 3600u, 3845u,
    4116u, 4375u, 4622u, 4893u, 5152u, 5401u, 5641u, 5900u, 6177u, 6418u, 6676u, 6950u, 7190u, 7446u, 7716u, 7956u,
    8210u, 8498u, 8736u, 9007u, 9270u, 9525u, 9774u, 10016u, 10286u, 10548u, 10804u, 11054u, 11298u, 11566u, 11827u, 12083u,
    12332u, 12604u, 12868u, 13128u, 13381u, 13630u, 13873u, 14112u, 14393u, 14668u, 14892u, 15157u, 15416u, 15671u, 15921u, 16207u,
    16448u, 16685u, 16995u, 17223u, 17447u, 17742u, 17959u, 18244u, 18524u, 18730u, 19002u, 19269u, 19531u, 19790u, 20044u, 20295u,
    20542u, 20846u, 21086u, 21322u, 21613u, 21842u, 22125u, 22348u, 22624u, 22895u, 23109u, 23374u, 23634u, 23892u, 24146u, 24397u,
    24694u, 24889u, 25179u, 25465u, 25653u, 25933u, 26209u, 26481u, 26750u, 27015u, 27278u, 27537u, 27794u, 28047u, 28298u, 28545u,
    28791u, 29033u, 29273u, 29590u, 29824u, 30057u, 30363u, 30590u, 30815u, 31112u, 31333u, 31624u, 31840u, 32125u, 32407u, 32616u,
    32893u, 33167u, 33438u, 33639u, 33906u, 34169u, 34430u, 34689u, 34945u, 35199u, 35450u, 35699u, 35947u, 36191u, 36434u, 36795u,
    37032u, 37268u, 37502u, 37734u, 38079u, 38307u, 38533u, 38757u, 39090u, 39310u, 39529u, 39854u, 40069u, 40388u, 40600u, 40914u,
    41122u, 41328u, 41635u, 41939u, 42141u, 42440u, 42638u, 42933u, 43129u, 43420u, 43708u, 43994u, 44183u, 44465u, 44745u, 44930u,
    45206u, 45479u, 45751u, 46021u, 46288u, 46554u, 46817u, 46992u, 47339u, 47511u, 47853u, 48023u, 48360u, 48527u, 48860u, 49025u,
    49354u, 49679u, 49841u, 50162u, 50322u, 50639u, 50954u, 51110u, 51422u, 51730u, 51884u, 52189u, 52491u, 52642u, 52941u, 53238u,
    53386u, 53680u, 53972u, 54262u, 54549u, 54693u, 54977u, 55260u, 55541u, 55820u, 55959u, 56236u, 56510u, 56783u, 57054u, 57324u,
    57592u, 57858u, 58122u, 58385u, 58647u, 58907u, 59165u, 59422u, 59678u, 59932u, 60184u, 60435u, 60685u, 60934u, 61181u, 61427u,
    61671u, 61915u, 62157u, 62398u, 62756u, 62994u, 63231u, 63466u, 63701u, 63934u, 64166u, 64397u, 64855u, 65083u, 65309u, 65535u,
};

/// The empty BaseColor's linear value, float32(0.8), and its code (s7, r1 and r2).
constexpr float kOcioEmptyBaseColor = 0.8f;
constexpr uint16_t kOcioEmptyBaseColorPng16 = 59396;

/// The value a channel stored as `format` holds for `v`: the document's store of `v` read back as
/// its operand (cpu_store.h `StoreValue`, `OperandOf`), where the measured padding writes a padded
/// value (decision 274).
float DocumentValue(float v, core::ChannelFormat format) {
    const evaluator::TileFormat tile = evaluator::TileFormatOf(format);
    return evaluator::OperandOf(evaluator::StoreValue(v, tile, 0), tile, 0);
}

/// The document format of channel `c` of `raster`, when it has one (`FileRaster::documentFormat`).
std::optional<core::ChannelFormat> DocumentFormat(const FileRaster& raster, uint32_t c) {
    return c < raster.documentFormat.size() ? raster.documentFormat[c] : std::nullopt;
}

/// True when channel `c` of `raster` was padded by its source (`FileRaster::padded`).
bool SourcePadded(const FileRaster& raster, uint32_t c) { return c < raster.padded.size() && raster.padded[c] != 0; }

/// True when every alpha (last component) of `raster` is 1.
bool OpaqueAlpha(const FileRaster& raster) {
    const size_t texels = size_t{raster.width} * raster.height;
    for (size_t t = 0; t < texels; ++t) {
        if (raster.values[t * raster.channels + raster.channels - 1] != 1.0f) return false;
    }
    return true;
}

}  // namespace

std::optional<uint16_t> OcioSrgbPng16Code(float v) {
    if (v == kOcioEmptyBaseColor) return kOcioEmptyBaseColorPng16;
    const std::array<float, 256>& operands = evaluator::arith::Srgb8OperandTable();
    const auto it = std::lower_bound(operands.begin(), operands.end(), v);
    if (it == operands.end() || *it != v) return std::nullopt;
    return kOcioSrgbPng16[it - operands.begin()];
}

EncodedImage EncodeFile(const PlannedFile& file, const FileRaster& raster, const Coverage* coverage,
                        InexactPadding inexact, std::vector<uint16_t>* samples) {
    if (samples != nullptr) samples->clear();
    if (file.layout == FileLayout::Statistics) {
        if (!raster.statistics) throw std::invalid_argument("export: a statistics file without statistics");
        return {*raster.statistics, FileLayout::Statistics};
    }
    const uint32_t components = file.layout == FileLayout::L    ? 1
                                : file.layout == FileLayout::LA ? 2
                                : file.layout == FileLayout::RGB ? 3
                                                                 : 4;
    if (raster.width != file.width || raster.height != file.height || raster.channels != components ||
        raster.values.size() != size_t{raster.width} * raster.height * components) {
        throw std::invalid_argument("export: the raster of " + file.relativePath + " does not match its size and layout");
    }
    if (!raster.documentFormat.empty() && raster.documentFormat.size() != components) {
        throw std::invalid_argument("export: the document formats of " + file.relativePath +
                                    " do not match its layout");
    }
    // An alpha of 1 everywhere is dropped (recordings R-085 P6/P7 for RGB+A, R-090 P6 for L+A).
    const bool alpha = file.layout == FileLayout::LA || file.layout == FileLayout::RGBA;
    const bool drop = alpha && OpaqueAlpha(raster);
    const uint32_t written = drop ? components - 1 : components;
    const FileLayout layout = !drop ? file.layout : file.layout == FileLayout::LA ? FileLayout::L : FileLayout::RGB;
    const size_t texels = size_t{raster.width} * raster.height;
    const ResolvedParameters& p = *file.parameters;
    if (p.fileFormat == FileFormat::exr) {
        // OpenEXR 32f: the float unchanged; 16f: the half rounded toward zero (R-090 P2).
        const bool half = p.bitDepth == BitDepth::f16;
        ExrImage image{raster.width, raster.height, written, {}, half};
        image.values.reserve(texels * written);
        for (size_t t = 0; t < texels; ++t) {
            for (uint32_t c = 0; c < written; ++c) {
                const float v = raster.values[t * components + c];
                image.values.push_back(half ? evaluator::arith::HalfToFloat(evaluator::arith::HalfTowardZero(v)) : v);
            }
        }
        if (coverage != nullptr) {
            // Each channel padded on its document operands (decision 274), or on the stored floats
            // when it has no document format; a filled texel stored as the document stores it, then
            // written as above.
            std::vector<float> operands(image.values);
            for (size_t t = 0; t < texels; ++t) {
                for (uint32_t c = 0; c < written; ++c) {
                    if (DocumentFormat(raster, c)) operands[t * written + c] = raster.values[t * components + c];
                }
            }
            if (ApplyPadding(file, *coverage, written, operands, inexact)) {
                for (size_t t = 0; t < texels; ++t) {
                    if (coverage->covered[t] != 0) continue;
                    for (uint32_t c = 0; c < written; ++c) {
                        if (SourcePadded(raster, c)) continue;
                        const std::optional<core::ChannelFormat> format = DocumentFormat(raster, c);
                        float v = operands[t * written + c];
                        if (format) v = DocumentValue(v, *format);
                        image.values[t * written + c] =
                            half ? evaluator::arith::HalfToFloat(evaluator::arith::HalfTowardZero(v)) : v;
                    }
                }
            }
        }
        return {EncodeExr(image), layout};
    }
    // PNG 8 and 16: the UNORM write rule at the file's depth (R-090 P1), of the sRGB encode of an
    // sRGB8 material channel's linear value (R-090 P10, decision 126).
    if (!raster.srgbEncoded.empty() && raster.srgbEncoded.size() != components) {
        throw std::invalid_argument("export: the sRGB flags of " + file.relativePath + " do not match its layout");
    }
    const uint32_t bits = p.bitDepth == BitDepth::u8 ? 8 : 16;
    const auto sample = [&](uint32_t c, float value) -> uint16_t {
        float v = PngValue(file.channels[c], value);
        const bool encoded = !raster.srgbEncoded.empty() && raster.srgbEncoded[c] != 0;
        if (encoded && raster.ocio && bits == 16) {
            // OCIO: Painter's recorded code (EvaluateFileOn refused every other value).
            const std::optional<uint16_t> code = OcioSrgbPng16Code(v);
            if (!code) throw std::invalid_argument("export: an unrecorded OCIO sRGB value in " + file.relativePath);
            return *code;
        }
        if (encoded) v = SrgbExportEncode(v);
        return static_cast<uint16_t>(evaluator::arith::WriteUnorm(v, bits));
    };
    PngImage image{raster.width, raster.height, written, bits, {}};
    image.samples.reserve(texels * written);
    for (size_t t = 0; t < texels; ++t) {
        for (uint32_t c = 0; c < written; ++c) image.samples.push_back(sample(c, raster.values[t * components + c]));
    }
    if (coverage != nullptr) {
        // Each channel padded on its document operands (decision 274), a filled texel stored as the
        // document stores it, then written as above; a channel without a document format padded on
        // its codes as UNORM operands, a filled texel written back by the write rule.
        std::vector<float> operands(image.samples.size());
        for (size_t t = 0; t < texels; ++t) {
            for (uint32_t c = 0; c < written; ++c) {
                const size_t i = t * written + c;
                operands[i] = DocumentFormat(raster, c) ? raster.values[t * components + c]
                                                        : evaluator::arith::UnormOperand(image.samples[i], bits);
            }
        }
        if (ApplyPadding(file, *coverage, written, operands, inexact)) {
            for (size_t t = 0; t < texels; ++t) {
                if (coverage->covered[t] != 0) continue;
                for (uint32_t c = 0; c < written; ++c) {
                    if (SourcePadded(raster, c)) continue;
                    const size_t i = t * written + c;
                    const std::optional<core::ChannelFormat> format = DocumentFormat(raster, c);
                    image.samples[i] = format ? sample(c, DocumentValue(operands[i], *format))
                                              : static_cast<uint16_t>(evaluator::arith::WriteUnorm(operands[i], bits));
                }
            }
        }
    }
    EncodedImage encoded{EncodePng(image), layout};
    if (samples != nullptr) *samples = std::move(image.samples);
    return encoded;
}

}  // namespace uzp::exporter
