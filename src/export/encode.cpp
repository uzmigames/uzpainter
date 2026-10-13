#include "export/encode.h"

#include "evaluator/arith.h"
#include "evaluator/hwmath.h"
#include "evaluator/sources.h"
#include "export/exr_writer.h"
#include "export/png_writer.h"
#include "uzp_core/types/errors.h"

#include <algorithm>
#include <array>
#include <stdexcept>

namespace uzp::exporter {

namespace {

/// Recorded by R-090 and not fitted (decision 103); the owners of the remaining fits.
constexpr std::string_view kSrgb8NotRecorded =
    "recording R-090 P10 records BaseColor, Specular and Emissive only; decision 126";
constexpr std::string_view kL8MaterialNotRecorded =
    "tier0/semantics/export-l8-material records RGB and L files of one L8 channel under Legacy; decision 204";
constexpr std::string_view kDitherNotFitted = "recording R-090 P3, decision 103";
constexpr std::string_view kResizeNotFitted = "recording R-090 P4, decision 103";
constexpr std::string_view kPaddingNotFitted = "recording R-090 P5 and P9, decision 103";

[[noreturn]] void Refuse(const PlannedFile& file, const std::string& what, std::string_view owner) {
    throw core::NotYetSupported("export: " + file.rootPath + " map \"" + file.fileName + "\" (" + file.relativePath +
                                "): " + what + " (" + std::string(owner) + ")");
}

const core::TextureSet& SetOf(const core::Project& project, const PlannedFile& file) {
    for (const core::TextureSet& set : project.texture_sets) {
        if (set.id == file.textureSetId) return set;
    }
    throw std::invalid_argument("export: the texture set of " + file.relativePath + " is not in the project");
}

/// The stack channel of `source` when it is an sRGB8 documentMap channel of `file`'s stack.
std::optional<core::ChannelType> Srgb8Channel(const core::TextureSet& set, const PlannedFile& file,
                                              const PlannedSource& source) {
    if (source.type != SourceType::documentMap || !source.channel) return std::nullopt;
    for (const core::Stack& stack : set.stacks) {
        if (stack.id != file.stackId) continue;
        const auto it = stack.channels.find(*source.channel);
        if (it != stack.channels.end() && it->second.format == core::ChannelFormat::sRGB8) return *source.channel;
    }
    return std::nullopt;
}

/// The stack channel of `source` when it is an L8 documentMap channel of `file`'s stack.
std::optional<core::ChannelType> L8Channel(const core::TextureSet& set, const PlannedFile& file,
                                           const PlannedSource& source) {
    if (source.type != SourceType::documentMap || !source.channel) return std::nullopt;
    for (const core::Stack& stack : set.stacks) {
        if (stack.id != file.stackId) continue;
        const auto it = stack.channels.find(*source.channel);
        if (it != stack.channels.end() && it->second.format == core::ChannelFormat::L8) return *source.channel;
    }
    return std::nullopt;
}

bool IsUserChannel(core::ChannelType type) { return core::ToString(type).starts_with("User"); }

/// True when `file` is laid out as export-l8-material records an L8 material channel: an RGB file
/// whose R, G and B, or an L file whose L, each read that letter of one documentMap source.
bool RecordedL8Mapping(const PlannedFile& file) {
    const size_t letters = file.layout == FileLayout::RGB ? 3 : file.layout == FileLayout::L ? 1 : 0;
    if (letters == 0 || file.channels.size() != letters) return false;
    return std::all_of(file.channels.begin(), file.channels.end(), [&](const PlannedChannel& c) {
        return c.src == c.dest && c.source.type == file.channels[0].source.type &&
               c.source.name == file.channels[0].source.name;
    });
}

}  // namespace

void CheckProcessing(const core::Project& project, const PlannedFile& file) {
    if (file.layout == FileLayout::Statistics) return;
    const core::TextureSet& set = SetOf(project, file);
    const ResolvedParameters& p = *file.parameters;
    if (p.dithering) {
        // Dithering changes nothing at PNG 16 (recording R-090 P3: on equals off on every map); at
        // PNG 8 it is deterministic but not fitted; in OpenEXR no recording compares it with off.
        if (p.fileFormat == FileFormat::png && p.bitDepth == BitDepth::u8) {
            Refuse(file, "dithering at PNG 8 bits is recorded (deterministic) but not fitted", kDitherNotFitted);
        }
        if (p.fileFormat == FileFormat::exr) {
            Refuse(file, "dithering in OpenEXR is not compared with dithering off by any recording", kDitherNotFitted);
        }
    }
    const auto width = static_cast<uint32_t>(set.resolution.width);
    const auto height = static_cast<uint32_t>(set.resolution.height);
    if (file.width != width || file.height != height) {
        Refuse(file,
               "resizing " + std::to_string(width) + "x" + std::to_string(height) + " to " + std::to_string(file.width) +
                   "x" + std::to_string(file.height) + " (sizeLog2) is recorded but only partly fitted",
               kResizeNotFitted);
    }
    if (p.paddingAlgorithm != Padding::infinite && p.paddingAlgorithm != Padding::passthrough) {
        Refuse(file,
               "the padding \"" + std::string(PaddingName(p.paddingAlgorithm)) +
                   "\" with dilationDistance is recorded but not fitted",
               kPaddingNotFitted);
    }
    for (const PlannedChannel& channel : file.channels) {
        const std::optional<core::ChannelType> srgb8 = Srgb8Channel(set, file, channel.source);
        if (!srgb8 || IsUserChannel(*srgb8) || SrgbEncodedOnExport(*srgb8)) continue;
        Refuse(file,
               "the export encoding of the sRGB8 channel " + std::string(core::ToString(*srgb8)) +
                   " (linear like a User channel, or sRGB-encoded like BaseColor) is not recorded",
               kSrgb8NotRecorded);
    }
    if (p.fileFormat != FileFormat::png) return;
    for (const PlannedChannel& channel : file.channels) {
        // An L8 BaseColor, Specular or Emissive is written as the sRGB encode of its linear value
        // in srcChannel R, B and L and as the linear value in G (export-l8-material, decision 204),
        // recorded for the RGB and L files of one L8 channel under Legacy.
        const std::optional<core::ChannelType> l8 = L8Channel(set, file, channel.source);
        if (!l8 || !SrgbEncodedOnExport(*l8)) continue;
        const std::string what = "the PNG encoding of the L8 channel " + std::string(core::ToString(*l8));
        if (evaluator::PainterOcio(project)) Refuse(file, what + " under OCIO is not recorded", kL8MaterialNotRecorded);
        if (!RecordedL8Mapping(file)) {
            Refuse(file,
                   what + " in a file laid out " + std::string(FileLayoutName(file.layout)) +
                       " other than the channel's own R, G and B, or its L, alone is not recorded",
                   kL8MaterialNotRecorded);
        }
    }
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

EncodedImage EncodeFile(const PlannedFile& file, const FileRaster& raster, const Coverage* coverage) {
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
        if (coverage != nullptr && ApplyPadding(file, *coverage, written, image.values) && half) {
            for (float& v : image.values) v = evaluator::arith::HalfToFloat(evaluator::arith::HalfTowardZero(v));
        }
        return {EncodeExr(image), layout};
    }
    // PNG 8 and 16: the UNORM write rule at the file's depth (R-090 P1), of the sRGB encode of an
    // sRGB8 material channel's linear value (R-090 P10, decision 126).
    if (!raster.srgbEncoded.empty() && raster.srgbEncoded.size() != components) {
        throw std::invalid_argument("export: the sRGB flags of " + file.relativePath + " do not match its layout");
    }
    const uint32_t bits = p.bitDepth == BitDepth::u8 ? 8 : 16;
    PngImage image{raster.width, raster.height, written, bits, {}};
    image.samples.reserve(texels * written);
    for (size_t t = 0; t < texels; ++t) {
        for (uint32_t c = 0; c < written; ++c) {
            float v = PngValue(file.channels[c], raster.values[t * components + c]);
            const bool encoded = !raster.srgbEncoded.empty() && raster.srgbEncoded[c] != 0;
            if (encoded && raster.ocio && bits == 16) {
                // OCIO: Painter's recorded code (EvaluateFileOn refused every other value).
                const std::optional<uint16_t> code = OcioSrgbPng16Code(v);
                if (!code) throw std::invalid_argument("export: an unrecorded OCIO sRGB value in " + file.relativePath);
                image.samples.push_back(*code);
                continue;
            }
            if (encoded) v = SrgbExportEncode(v);
            image.samples.push_back(static_cast<uint16_t>(evaluator::arith::WriteUnorm(v, bits)));
        }
    }
    if (coverage != nullptr) {
        // The codes as UNORM operands, padded; the filled texels written back by the write rule.
        std::vector<float> stored(image.samples.size());
        for (size_t i = 0; i < stored.size(); ++i) stored[i] = evaluator::arith::UnormOperand(image.samples[i], bits);
        if (ApplyPadding(file, *coverage, written, stored)) {
            for (size_t t = 0; t < texels; ++t) {
                if (coverage->covered[t] != 0) continue;
                for (uint32_t c = 0; c < written; ++c) {
                    image.samples[t * written + c] =
                        static_cast<uint16_t>(evaluator::arith::WriteUnorm(stored[t * written + c], bits));
                }
            }
        }
    }
    return {EncodePng(image), layout};
}

}  // namespace uzp::exporter
