// Native resolution persistence is tested separately by tests/uzp_core.
int RunResolution(const fs::path& work) {
    namespace core = uzp::core;
    using Mode = core::ProceduralResolutionMode;
    AssetLibrary library;
    core::ProceduralRef ref;
    ref.asset = "uzasset://snapshot/resolution@1";
    UseContext context;
    context.output = RasterSpec{1024, ChannelFormat::F32, "raw", 1};
    const auto size = [&](uint32_t expected) {
        const auto request = RequestFor(ref, context, library);
        return request && request->output.resolution == expected;
    };
    const auto refused = [&] {
        const auto request = RequestFor(ref, context, library);
        return !request && request.error().field == "resolution_override";
    };
    context.output.resolution = 64;
    Check(size(64), "no override preserves synthetic 64px contexts");
    ref.resolution_override = core::Resolution{512, 512, {}};
    Check(size(512), "legacy override resolves its explicit dimensions instead of ignoring them");
    ref.resolution_override = core::Resolution{512, 256, {}};
    Check(refused(), "legacy rectangular override is refused");
    context.output.resolution = 1024;
    core::ProceduralResolutionOverride choice{Mode::Auto, {512, 256}, -1, {}};
    for (const auto& [offset, expected] : std::array<std::pair<int, uint32_t>, 2>{{{-3, 128}, {3, 8192}}}) {
        choice.log2_offset = offset;
        ref.resolution_override = choice;
        Check(size(expected), "Auto reaches raster bounds exactly without clamp");
    }
    choice.log2_offset = -1;
    ref.resolution_override = choice;
    const auto before = RequestFor(ref, context, library);
    Check(size(512), "Auto uses parent plus integer offset and ignores manual value");
    context.output.resolution = 2048;
    const auto after = RequestFor(ref, context, library);
    Check(size(1024) && before && after && Signature(*before) != Signature(*after),
          "Auto resize changes effective output and snapshot signature");
    for (int offset : {std::numeric_limits<int>::min(), std::numeric_limits<int>::max(), -31, 31, -5, 3}) {
        choice.log2_offset = offset;
        ref.resolution_override = choice;
        Check(refused(), "Auto out-of-domain offsets are refused without clamp or overflow");
    }
    choice.log2_offset = 0;
    ref.resolution_override = choice;
    context.output.resolution = 0;
    Check(refused(), "Auto without parent resolution is refused");
    context.output.resolution = 1024;
    for (Mode mode : {Mode::Custom, Mode::Manual}) {
        choice = {mode, {256, 256}, std::numeric_limits<int>::max(), {}};
        ref.resolution_override = choice;
        const auto fixed = RequestFor(ref, context, library);
        context.output.resolution = 2048;
        const auto resized = RequestFor(ref, context, library);
        Check(size(256) && fixed && resized && Signature(*fixed) == Signature(*resized),
              "Custom/Manual uses value, ignores offset and does not follow resize");
        choice.value = {256, 512};
        ref.resolution_override = choice;
        Check(refused(), "Custom/Manual rectangular output is refused");
    }
    for (Mode mode : {Mode::TextureSet, Mode::UVTile}) {
        choice = {mode, {256, 256}, std::numeric_limits<int>::min(), {}};
        ref.resolution_override = choice;
        Check(refused(), "set/tile mode needs its explicit context");
        auto& dimensions = mode == Mode::TextureSet ? context.textureSetResolution : context.uvTileResolution;
        dimensions = core::Resolution{4096, 4096, {}};
        Check(size(4096), "set/tile mode uses its context and ignores offset");
        dimensions = core::Resolution{4096, 2048, {}};
        Check(refused(), "rectangular set/tile context is refused");
        dimensions.reset();
    }
    for (Mode mode : {Mode::Asset, Mode::Document}) {
        ref.resolution_override = core::ProceduralResolutionOverride{mode, {256, 256}, 0, {}};
        Check(refused(), "Asset/Document does not invent procedural dimensions from vector semantics");
    }
    ref.resolution_override = core::ProceduralResolutionOverride{Mode::Custom, {256, 256}, 0, {}};
    context.content = ImageInput{context.output, std::string(64, 'a')};
    Check(refused(), "known filter context refuses resolution override");
    int submits = 0;
    const ProceduralSeam seam(nullptr, nullptr);
    const SubmitEdit submit = [&](const std::function<void(core::Edit&)>&) {
        ++submits;
        return core::RequestOutcome{};
    };
    Check(!SetEffectProcedural(1, ref, context, library, seam, submit) && submits == 0,
          "resolution refusal precedes transaction submission");
    context.content.reset();
    ref.resolution_override = core::ProceduralResolutionOverride{Mode::Manual, {256, 256},
                                                                  std::numeric_limits<int>::max(), {{"future", 7}}};
    const auto original = RequestFor(ref, context, library);
    core::Id generator = core::kNoId;
    core::DocumentState state;
    state.project_uuid = "6f1c2a3e-0000-4000-8000-00000000a326";
    state.project = GeneratorProject(generator);
    state.project.texture_sets[0].stacks[0].root_layers[0].content_effects[0].procedural = ref;
    const fs::path file = work / "resolution.uzp";
    auto store = uzp::store::ProjectStore::Create(file, state);
    core::Document document(state);
    store->Attach(document);
    store->Save(document);
    store->Close();
    auto reopened = uzp::store::ProjectStore::Open(file);
    const auto& restored = GeneratorOf(reopened.state.project)->procedural;
    Check(restored.has_value(), "save/reopen retains procedural reference");
    if (restored) {
        const auto request = RequestFor(*restored, context, library);
        Check(*restored == ref && original && request && Signature(*original) == Signature(*request),
              "save/reopen preserves mode value offset extras and effective signature");
    }
    reopened.store->Close();
    return Finish();
}
