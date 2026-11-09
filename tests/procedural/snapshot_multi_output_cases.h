// Included inside the native procedural test harness's anonymous namespace.
// Multi-output captures (decision 412 §3, decision 413): plugged image inputs in the signature, the
// `/4` source metadata and the receipt of a multi-output capture. Authored values only.
int RunSnapshotMultiOutput(const fs::path& work) {
    namespace core = uzp::core;
    namespace store = uzp::store;
    namespace exporter = uzp::exporter;
    namespace json = uzp::core::json;
    const std::string resource = "resource://shelf/authored?version=1";
    const std::string bitmap(64, 'b');

    // Plugged inputs: a colour by its working value (numbers by value), a bitmap by hash and
    // colour space; an unplugged input is absent.
    ProceduralRequest request;
    request.asset = core::ParseAssetUrl("uzasset://snapshot/" + core::Sha256Hex(resource) + "@1");
    request.params = {{"gain", 0.5}, {"$randomseed", int64_t{0}}};
    request.preset = "authored preset";
    request.meshClass = "quad";
    request.output = {8, ChannelFormat::F32, "raw", 3};
    request.outputId = "first";
    request.sourceInputs = {{"mask", InputSource{{}, {}, std::array<double, 3>{0.25, 1.0, 0.0}}},
                            {"detail", InputSource{bitmap, "Data", std::nullopt}}};
    const json::Value signature = SignatureJson(request);
    const auto& inputs = std::get<json::Object>(std::get<json::Object>(signature.data).at("inputs").data);
    Check(json::WriteCanonical(inputs.at("mask")) == R"({"working_colour":[0.25,1,0]})" &&
              json::WriteCanonical(inputs.at("detail")) == R"({"bitmap_sha256":")" + bitmap + R"(","colour_space":"Data"})",
          "multi-output: plugged inputs enter the signature by working value and by bitmap hash and colour space");
    const auto reread = RequestFromSignature(signature);
    Check(reread && reread->sourceInputs == request.sourceInputs && Signature(*reread) == Signature(request),
          "multi-output: a signature with plugged inputs reads back exactly");
    ProceduralRequest floats = request;
    floats.sourceInputs["mask"].workingColour = std::array<double, 3>{0.25, 1.0, -0.0};
    Check(SignatureHash(floats) == SignatureHash(request), "multi-output: working colour components compare by value");
    ProceduralRequest both = request;
    both.inputs["mask"] = ImageInput{RasterSpec{8, ChannelFormat::U8, "raw", 1}, std::string(64, 'c')};
    bool collision = false;
    try {
        (void)SignatureJson(both);
    } catch (const core::ValueError&) {
        collision = true;
    }
    Check(collision, "multi-output: a name that is both a raster input and a plugged source refuses");
    const auto withInput = [&](json::Value input) {
        json::Value changed = signature;
        std::get<json::Object>(std::get<json::Object>(changed.data)["inputs"].data)["mask"] = std::move(input);
        return RequestFromSignature(changed);
    };
    Check(!withInput(json::Object{{"working_colour", json::Array{0.25, 1.0}}}), "multi-output: a two-component colour refuses");
    Check(!withInput(json::Object{{"working_colour", json::Array{0.25, true, 0.0}}}), "multi-output: a boolean colour component refuses");
    Check(!withInput(json::Object{{"working_colour", json::Array{0.25, 1.0, 0.0}}, {"colour_space", std::string("Data")}}),
          "multi-output: a colour input with an extra field refuses");
    Check(!withInput(json::Object{{"bitmap_sha256", std::string("ABC")}, {"colour_space", std::string("Data")}}),
          "multi-output: a bitmap input without a lowercase SHA-256 refuses");
    Check(!withInput(json::Object{{"bitmap_sha256", bitmap}, {"colour_space", std::string()}}),
          "multi-output: a bitmap input without a colour space refuses");

    // Schema /4: preset parameters, input sources and the output contexts.
    const json::Object refused{{"raised", json::Object{{"type", std::string("EditionContextException")},
                                                        {"message", std::string("authored refusal")}}}};
    const json::Object contexts{
        {"split", json::Object{{"output_mapping", refused}, {"mask_output", refused}}},
        {"material", json::Object{{"output_mapping", json::Object{{"Height", std::string("second")}, {"Normal", std::string("first")}}},
                                  {"mask_output", std::string("authored_alpha")},
                                  {"active_channels", json::Array{}},
                                  {"active_output", refused}}}};
    const json::Object inputSources{
        {"mask", json::Object{{"class", std::string("SourceUniformColor")}, {"working", json::Array{0.25, 1.0, 0.0}}}},
        {"detail", json::Object{{"class", std::string("SourceBitmap")}, {"sha256", bitmap}, {"colour_space", std::string("Data")}}},
        {"unplugged", json::Object{{"raised", json::Object{{"type", std::string("ValueError")}, {"message", std::string("authored")}}}}},
        {"alias", json::Object{{"class", std::string("SourceBitmap")},
                               {"resource_id", json::Object{{"raised", json::Object{{"type", std::string("ValueError")},
                                                                                   {"message", std::string("authored alias")}}}}},
                               {"colour_space", std::string("Data")}}}};
    store::SourceMetadata metadata;
    metadata.image_outputs = {"first", "second"};
    metadata.image_inputs = std::vector<std::string>{"mask", "detail", "unplugged", "alias"};
    metadata.presets = std::vector<std::string>{"authored preset"};
    metadata.preset_parameters = json::Object{{"authored preset", json::Object{{"gain", 0.25}, {"$randomseed", int64_t{0}}}}};
    metadata.input_sources = inputSources;
    metadata.contexts = contexts;
    const json::Value v4 = store::SourceMetadataJson(signature, metadata);
    const auto v4Read = store::ParseSourceMetadata(signature, v4);
    Check(std::get<std::string>(std::get<json::Object>(v4.data).at("schema").data) == store::kSourceMetadataSchemaV4 &&
              v4Read && *v4Read == metadata,
          "metadata v4: preset parameters, input sources and contexts roundtrip",
          v4Read ? std::string() : v4Read.error());
    store::SourceMetadata older = metadata;
    older.preset_parameters.reset();
    older.input_sources.reset();
    older.contexts.reset();
    Check(std::get<std::string>(std::get<json::Object>(store::SourceMetadataJson(signature, older).data).at("schema").data) ==
              store::kSourceMetadataSchemaV2,
          "metadata v4: without its members the metadata keeps its older schema");
    const std::vector<std::pair<std::string, std::function<void(json::Object&)>>> invalidV4{
        {"preset parameters of another preset", [](json::Object& m) {
             m["preset_parameters"] = json::Object{{"other", json::Object{{"gain", 0.25}, {"$randomseed", int64_t{0}}}}};
         }},
        {"preset parameters missing a parameter", [](json::Object& m) {
             m["preset_parameters"] = json::Object{{"authored preset", json::Object{{"gain", 0.25}}}};
         }},
        {"a boolean preset parameter", [](json::Object& m) {
             m["preset_parameters"] = json::Object{{"authored preset", json::Object{{"gain", true}, {"$randomseed", int64_t{0}}}}};
         }},
        {"input sources missing an input", [](json::Object& m) {
             std::get<json::Object>(m["input_sources"].data).erase("unplugged");
         }},
        {"a colour input other than the signature's", [](json::Object& m) {
             std::get<json::Object>(std::get<json::Object>(m["input_sources"].data)["mask"].data)["working"] = json::Array{0.5, 1.0, 0.0};
         }},
        {"a bitmap input of another colour space", [](json::Object& m) {
             std::get<json::Object>(std::get<json::Object>(m["input_sources"].data)["detail"].data)["colour_space"] = std::string("sRGB");
         }},
        {"a plugged input recorded as unplugged", [](json::Object& m) {
             std::get<json::Object>(m["input_sources"].data)["mask"] =
                 json::Object{{"raised", json::Object{{"type", std::string("ValueError")}, {"message", std::string("x")}}}};
         }},
        {"an unplugged bitmap that reads its resource", [](json::Object& m) {
             auto& alias = std::get<json::Object>(std::get<json::Object>(m["input_sources"].data)["alias"].data);
             alias["resource_id"] = json::Object{{"returned", std::string("ResourceID")}};
         }},
        {"an unplugged bitmap without its colour space", [](json::Object& m) {
             std::get<json::Object>(std::get<json::Object>(m["input_sources"].data)["alias"].data).erase("colour_space");
         }},
        {"an unknown input source class", [](json::Object& m) {
             std::get<json::Object>(m["input_sources"].data)["unplugged"] = json::Object{{"class", std::string("SourceReference")}};
         }},
        {"a material mapping to an unlisted output", [](json::Object& m) {
             auto& material = std::get<json::Object>(std::get<json::Object>(m["contexts"].data)["material"].data);
             material["output_mapping"] = json::Object{{"Height", std::string("unlisted")}};
         }},
        {"a material mapping keyed by a non-channel", [](json::Object& m) {
             auto& material = std::get<json::Object>(std::get<json::Object>(m["contexts"].data)["material"].data);
             material["output_mapping"] = json::Object{{"Colour", std::string("first")}};
         }},
        {"an empty mask output", [](json::Object& m) {
             auto& material = std::get<json::Object>(std::get<json::Object>(m["contexts"].data)["material"].data);
             material["mask_output"] = std::string();
         }},
        {"a split context without its mask output", [](json::Object& m) {
             std::get<json::Object>(std::get<json::Object>(m["contexts"].data)["split"].data).erase("mask_output");
         }},
        {"a /4 member under /3", [](json::Object& m) { m["schema"] = std::string(store::kSourceMetadataSchemaV3); }},
        {"a /4 schema without its members", [](json::Object& m) {
             m.erase("preset_parameters");
             m.erase("input_sources");
             m.erase("contexts");
         }},
    };
    for (const auto& [name, mutate] : invalidV4) {
        json::Object changed = std::get<json::Object>(v4.data);
        mutate(changed);
        Check(!store::ParseSourceMetadata(signature, changed), "metadata v4: " + name + " refuses");
    }

    // A /4 snapshot of a 3-channel output: committed, served and observed exactly after reopen.
    core::Id generator = core::kNoId;
    core::DocumentState initial;
    initial.project_uuid = "6f1c2a3e-0000-4000-8000-0000000a4130";
    initial.project = GeneratorProject(generator);
    ProceduralRequest stored = request;
    stored.settings = EvaluationSettings(initial.project);
    const json::Value storedSignature = SignatureJson(stored);
    exporter::ExrImage image;
    image.width = image.height = 8;
    image.channels = 3;
    for (size_t i = 0; i < 8 * 8 * 3; ++i) image.values.push_back(static_cast<float>(i % 7) * 0.125f);
    const std::string exportFile = exporter::EncodeExr(image);
    {
        auto created = store::ProjectStore::Create(work / "multi-output.uzp", initial);
        core::Document document(initial);
        created->Attach(document);
        const auto outcome = RecordSnapshotExport(*created, document, stored, exportFile, initial.project_uuid, 0, metadata);
        Check(outcome && outcome->result && outcome->result->status == core::ResultStatus::committed,
              "metadata v4: a 3-channel snapshot with /4 metadata commits", outcome ? std::string() : outcome.error());
        created->Save(document);
        created->Close();
    }
    {
        auto reopened = store::ProjectStore::Open(work / "multi-output.uzp");
        const auto backend = SnapshotBackend::Load(*reopened.store, reopened.state.project);
        const auto served = backend ? backend->Stored(stored) : decltype(backend->Stored(stored))(std::unexpect);
        const auto observed = backend ? backend->Metadata(stored) : decltype(backend->Metadata(stored))(std::unexpect);
        const auto expectedTexels = SnapshotExportTexels(exportFile, stored.output);
        Check(backend && served && expectedTexels && (*served)->bytes == *expectedTexels && observed && *observed == metadata,
              "metadata v4: the 3-channel snapshot keeps its texels and observations after reopen",
              backend ? std::string() : backend.error());
        reopened.store->Close();
    }

    // The receipt of a multi-output capture (python/uzpainter_snapshot/bridge.py record_outputs).
    const json::Object properties{};
    const json::Object id{{"url", resource}, {"context", std::string("shelf")}, {"name", std::string("authored")},
                          {"version", std::string("1")}};
    const auto source = [&](json::Object observed) {
        return json::Object{{"resource", resource},
                            {"resource_id", id},
                            {"parameters", json::Object{{"gain", 0.5}, {"$randomseed", int64_t{0}}}},
                            {"inputs", json::Array{std::string("mask"), std::string("detail"), std::string("unplugged"),
                                                   std::string("alias")}},
                            {"outputs", json::Array{std::string("first"), std::string("second")}},
                            {"presets", json::Array{std::string("authored preset")}},
                            {"properties", properties},
                            {"active_output", std::string("second")},
                            {"input_sources", std::move(observed)}};
    };
    const std::string url = "resource://project1/authored-bitmap?version=1";
    json::Object painterInputs = inputSources;
    painterInputs["detail"] = json::Object{{"class", std::string("SourceBitmap")}, {"resource", url},
                                           {"colour_space", std::string("Data")}};
    json::Object material = std::get<json::Object>(contexts.at("material").data);
    material["parameters"] = json::Object{{"gain", 0.5}, {"$randomseed", int64_t{0}}};
    material["input_sources"] = painterInputs;
    const auto receipt = [&](json::Object first, json::Object second, json::Object materialContext) {
        return json::Object{
            {"readback", json::Object{{"sources", json::Array{std::move(first), std::move(second)}},
                                      {"bitmaps", json::Object{{"C:/work/inputs/0.png", url}}}}},
            {"bitmaps", json::Object{{"C:/work/inputs/0.png", bitmap}}},
            {"preset_parameters", *metadata.preset_parameters},
            {"contexts", json::Object{{"split", contexts.at("split")}, {"material", std::move(materialContext)}}}};
    };
    ProceduralRequest captured = request;
    captured.preset = std::nullopt;
    const auto read = ReceiptMultiOutputMetadata(receipt(source(painterInputs), source(painterInputs), material), resource, captured);
    Check(read && read->image_outputs == metadata.image_outputs && read->input_sources == inputSources &&
              read->contexts == contexts && read->preset_parameters == metadata.preset_parameters &&
              read->observed_resource_id && read->typed_effective_parameters,
          "multi-output receipt: the state's observations, a bitmap by its staged file's hash",
          read ? std::string() : read.error());
    json::Object otherOutput = source(painterInputs);
    otherOutput["active_output"] = std::string("first");
    Check(!ReceiptMultiOutputMetadata(receipt(source(painterInputs), otherOutput, material), resource, captured),
          "multi-output receipt: paired sources that differ refuse");
    json::Object otherMaterial = material;
    otherMaterial["parameters"] = json::Object{{"gain", 1.0}, {"$randomseed", int64_t{0}}};
    Check(!ReceiptMultiOutputMetadata(receipt(source(painterInputs), source(painterInputs), otherMaterial), resource, captured),
          "multi-output receipt: a material source of another state refuses");
    json::Object foreignBitmap = painterInputs;
    std::get<json::Object>(foreignBitmap["detail"].data)["resource"] = std::string("resource://project1/other?version=1");
    Check(!ReceiptMultiOutputMetadata(receipt(source(foreignBitmap), source(foreignBitmap), material), resource, captured),
          "multi-output receipt: a bitmap the capture did not stage refuses");
    ProceduralRequest unlisted = captured;
    unlisted.outputId = "third";
    Check(!ReceiptMultiOutputMetadata(receipt(source(painterInputs), source(painterInputs), material), resource, unlisted),
          "multi-output receipt: an output the source does not list refuses");
    ProceduralRequest otherColour = captured;
    otherColour.sourceInputs["mask"].workingColour = std::array<double, 3>{0.5, 1.0, 0.0};
    Check(!ReceiptMultiOutputMetadata(receipt(source(painterInputs), source(painterInputs), material), resource, otherColour),
          "multi-output receipt: a signature whose plugged colour is not the read-back one refuses");
    json::Object noIdentity = source(painterInputs);
    noIdentity.erase("resource_id");
    Check(!ReceiptMultiOutputMetadata(receipt(noIdentity, noIdentity, material), resource, captured),
          "multi-output receipt: a source without its observed ResourceID refuses");
    return Finish();
}
