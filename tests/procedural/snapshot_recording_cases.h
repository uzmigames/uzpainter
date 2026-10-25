// Included inside the native procedural test harness's anonymous namespace.
int RunSnapshotRecording(const fs::path& work) {
    namespace core = uzp::core;
    namespace store = uzp::store;
    namespace exporter = uzp::exporter;
    namespace json = uzp::core::json;
    ProceduralRequest request;
    request.asset = core::ParseAssetUrl("uzasset://test/noise@1");
    request.params = {{"gain", 0.5}, {"offset", ParamVector{{int64_t{1}, 2.0}}}};
    request.meshClass = "quad";
    request.output = {8, ChannelFormat::U16, "raw", 1};
    request.outputId = "grey";
    request.settings = {{"normal_map_format", std::string("OpenGL")}};
    const auto signature = SignatureJson(request);
    const auto parsed = RequestFromSignature(signature);
    Check(parsed && Signature(*parsed) == Signature(request), "recording signature roundtrip preserves every field",
          parsed ? Signature(*parsed) : parsed.error());
    for (const auto& [key, ignored] : std::get<json::Object>(signature.data)) {
        auto broken = std::get<json::Object>(signature.data);
        broken.erase(key);
        Check(!RequestFromSignature(broken), "recording refuses missing signature field " + key);
    }
    auto extra = std::get<json::Object>(signature.data);
    extra["unknown"] = 1;
    Check(!RequestFromSignature(extra), "recording refuses unknown signature field");
    auto pinnedAsset = std::get<json::Object>(signature.data);
    pinnedAsset["asset"] = "uzasset://test/noise@1";
    Check(!RequestFromSignature(pinnedAsset), "recording refuses a duplicated asset version");
    auto wideSeed = std::get<json::Object>(signature.data);
    wideSeed["seed"] = int64_t{-1};
    const auto fullSeed = RequestFromSignature(wideSeed);
    Check(fullSeed && fullSeed->seed == std::numeric_limits<uint64_t>::max() &&
              SignatureJson(*fullSeed) == json::Value(wideSeed),
          "recording retains the documented two's-complement uint64 seed encoding");
    auto nested = std::get<json::Object>(signature.data);
    auto output = std::get<json::Object>(nested.at("output").data);
    output["channels"] = 4;
    nested["output"] = output;
    Check(!RequestFromSignature(nested), "recording refuses output without a plane format");

    core::Project meshProject;
    meshProject.mesh.emplace();
    meshProject.mesh->resource = std::string(64, '1');
    ProceduralRequest meshRequest = request;
    meshRequest.settings = EvaluationSettings(meshProject);
    SnapshotBackend meshBackend;
    meshBackend.Add(meshRequest, SnapshotRaster{meshRequest.output, std::string(128, '\0')});
    meshProject.mesh->resource = std::string(64, '2');
    ProceduralRequest reloaded = meshRequest;
    reloaded.settings = EvaluationSettings(meshProject);
    Check(!meshBackend.CanEvaluate(reloaded), "mesh replacement invalidates a snapshot with identical class and settings");
    meshProject.mesh->resource = std::string(64, '1');
    reloaded.settings = EvaluationSettings(meshProject);
    Check(meshBackend.CanEvaluate(reloaded), "restoring exact mesh bytes restores the snapshot signature");

    meshProject.mesh->import_report = {
        {"source", json::Object{{"name", "quad.gltf"}, {"size", 256}}},
        {"external_files", json::Array{json::Object{{"uri", "quad.bin"}, {"sha256", std::string(64, '3')}, {"size", 128}}}},
        {"units", json::Object{{"scale_to_internal", 1.0}}},
    };
    meshRequest.settings = EvaluationSettings(meshProject);
    SnapshotBackend externalBackend;
    externalBackend.Add(meshRequest, SnapshotRaster{meshRequest.output, std::string(128, '\0')});
    auto externalFiles = std::get<json::Array>(meshProject.mesh->import_report.at("external_files").data);
    std::get<json::Object>(externalFiles[0].data)["sha256"] = std::string(64, '4');
    meshProject.mesh->import_report["external_files"] = externalFiles;
    reloaded.settings = EvaluationSettings(meshProject);
    Check(!externalBackend.CanEvaluate(reloaded), "external glTF buffer replacement invalidates a snapshot with the same root file");
    std::get<json::Object>(externalFiles[0].data)["sha256"] = std::string(64, '3');
    meshProject.mesh->import_report["external_files"] = externalFiles;
    meshProject.mesh->import_report["source"] = json::Object{{"name", "renamed.gltf"}, {"size", 256}};
    reloaded.settings = EvaluationSettings(meshProject);
    Check(externalBackend.CanEvaluate(reloaded), "mesh source metadata does not invalidate the exact geometry snapshot");
    meshProject.mesh->import_report["units"] = json::Object{{"scale_to_internal", 2.0}};
    reloaded.settings = EvaluationSettings(meshProject);
    Check(!externalBackend.CanEvaluate(reloaded), "changed mesh import settings invalidate the snapshot");

    core::Id generator = core::kNoId;
    core::DocumentState initial;
    initial.project_uuid = "6f1c2a3e-0000-4000-8000-0000000a3271";
    initial.project = GeneratorProject(generator);
    auto projectStore = store::ProjectStore::Create(work / "snapshot-recording.uzp", initial);
    core::Document document(initial);
    projectStore->Attach(document);
    ProceduralRequest capture = request;
    capture.settings = EvaluationSettings(*document.snapshot().project);
    store::PlaneImage captureImage;
    captureImage.width = captureImage.height = 8;
    captureImage.format = core::ChannelFormat::L16;
    for (int i = 0; i < 128; ++i) captureImage.texels.push_back(static_cast<char>(i * 37));
    const std::string exportFile = store::codec::EncodePng(captureImage);
    core::DocumentState foreignState = initial;
    foreignState.project_uuid = "6f1c2a3e-0000-4000-8000-0000000a3272";
    core::Document foreignDocument(foreignState);
    Check(!RecordSnapshotExport(*projectStore, foreignDocument, capture, exportFile, initial.project_uuid, 0) &&
              foreignDocument.revision() == 0 && document.revision() == 0 &&
              store::ReadCurrentRevision(projectStore->container()) == 0,
          "foreign Document refuses even when caller supplies the destination store UUID");
    core::Document detachedDocument(initial);
    Check(!RecordSnapshotExport(*projectStore, detachedDocument, capture, exportFile, initial.project_uuid, 0) &&
              detachedDocument.revision() == 0 && store::ReadCurrentRevision(projectStore->container()) == 0,
          "same-UUID detached Document cannot report a memory-only snapshot commit");
    auto otherStore = store::ProjectStore::Create(work / "other-snapshot-recording.uzp", initial);
    otherStore->Attach(detachedDocument);
    Check(!RecordSnapshotExport(*projectStore, detachedDocument, capture, exportFile, initial.project_uuid, 0) &&
              detachedDocument.HasCommitSink(otherStore.get()) && detachedDocument.revision() == 0 &&
              store::ReadCurrentRevision(projectStore->container()) == 0 &&
              store::ReadCurrentRevision(otherStore->container()) == 0,
          "same-UUID Document attached to another store refuses without replacing its sink");
    detachedDocument.SetCommitSink([](const core::Snapshot&, const core::OperationRecord&) {});
    Check(!detachedDocument.HasCommitSink(otherStore.get()) &&
              !RecordSnapshotExport(*projectStore, detachedDocument, capture, exportFile, initial.project_uuid, 0),
          "replacing the commit sink clears its store ownership token");
    otherStore->Close();
    Check(!RecordSnapshotExport(*projectStore, document, capture, exportFile, "foreign", 0) && document.revision() == 0,
          "foreign recording refuses before a transaction");
    Check(!RecordSnapshotExport(*projectStore, document, capture, exportFile, initial.project_uuid, 1) && document.revision() == 0,
          "stale recording refuses before a transaction");
    ProceduralRequest unpinned = capture;
    unpinned.settings.erase("mesh.sha256");
    Check(!RecordSnapshotExport(*projectStore, document, unpinned, exportFile, initial.project_uuid, 0) && document.revision() == 0,
          "missing mesh fingerprint cannot bypass recording admission");
    Check(!RecordSnapshotExport(*projectStore, document, capture, "invalid", initial.project_uuid, 0) && document.revision() == 0,
          "malformed export never changes the project");
    const auto committed = RecordSnapshotExport(*projectStore, document, capture, exportFile, initial.project_uuid, 0);
    Check(committed && committed->result && committed->result->status == core::ResultStatus::committed && document.revision() == 1,
          "a validated export records in exactly one transaction");
    projectStore->Save(document);
    projectStore->Close();
    auto reopened = store::ProjectStore::Open(work / "snapshot-recording.uzp");
    core::Document restored(std::move(reopened.state));
    const auto recorded = SnapshotBackend::Load(*reopened.store, *restored.snapshot().project);
    const auto stored = recorded ? recorded->Stored(capture) : std::expected<const SnapshotRaster*, UnsupportedProcedural>(std::unexpect, Refuse("test", "load failed"));
    Check(stored && (*stored)->bytes == captureImage.texels, "ingested export survives save and reopen byte for byte");
    reopened.store->Close();

    for (const ChannelFormat format : {ChannelFormat::U8, ChannelFormat::U16}) {
        for (const uint32_t channels : {1u, 3u}) {
            const RasterSpec spec{8, format, "raw", channels};
            const auto planeFormat = SnapshotPlaneFormat(spec);
            store::PlaneImage image;
            image.width = image.height = 8;
            image.format = *planeFormat;
            const size_t bytes = size_t{8 * 8 * channels} * (format == ChannelFormat::U8 ? 1 : 2);
            for (size_t i = 0; i < bytes; ++i) image.texels.push_back(static_cast<char>(i * 71));
            const std::string encoded = store::codec::EncodePng(image);
            const auto decoded = SnapshotExportTexels(encoded, spec);
            Check(decoded && *decoded == image.texels, "recording PNG retains all codes " + std::string(FormatName(format)) + "/" + std::to_string(channels));
            RasterSpec wrong = spec;
            wrong.resolution = 16;
            Check(!SnapshotExportTexels(encoded, wrong), "recording PNG refuses different dimensions " + std::string(FormatName(format)) + "/" + std::to_string(channels));
        }
    }
    for (const bool half : {false, true}) {
        exporter::ExrImage image;
        image.width = image.height = 8;
        image.channels = 3;
        image.half = half;
        const float values[] = {0.0f, -0.0f, 0.5f, -1.0f, 65504.0f, 0x1p-24f};
        for (size_t i = 0; i < 8 * 8 * 3; ++i) image.values.push_back(values[i % 6]);
        const RasterSpec spec{8, half ? ChannelFormat::F16 : ChannelFormat::F32, "raw", 3};
        const auto decoded = SnapshotExportTexels(exporter::EncodeExr(image), spec);
        const uint16_t halfCodes[] = {0x0000, 0x8000, 0x3800, 0xbc00, 0x7bff, 0x0001};
        const uint32_t floatCodes[] = {0x00000000, 0x80000000, 0x3f000000, 0xbf800000, 0x477fe000, 0x33800000};
        std::string expected;
        for (size_t i = 0; i < image.values.size(); ++i) {
            const uint32_t code = half ? halfCodes[i % 6] : floatCodes[i % 6];
            for (unsigned byte = 0; byte < (half ? 2u : 4u); ++byte) {
                expected.push_back(static_cast<char>((code >> (8 * byte)) & 255));
            }
        }
        Check(decoded && *decoded == expected, "recording EXR preserves finite codes, signed zero and subnormals " + std::string(FormatName(spec.format)));
        if (decoded) {
            SnapshotBackend backend;
            ProceduralRequest served = request;
            served.output = spec;
            backend.Add(served, SnapshotRaster{spec, *decoded});
            const auto stored = backend.Stored(served);
            Check(stored && (*stored)->bytes == *decoded, "recording bytes are served unchanged " + std::string(FormatName(spec.format)));
        }
        RasterSpec wrong = spec;
        wrong.format = half ? ChannelFormat::F32 : ChannelFormat::F16;
        Check(!SnapshotExportTexels(exporter::EncodeExr(image), wrong), "recording EXR refuses implicit precision conversion " + std::string(FormatName(spec.format)));
    }
    return Finish();
}


// `source_metadata` (store/snapshots.h): the image outputs a recording observed, beside the
// signature. Synthetic CPU evidence; no Painter is involved.
int RunSnapshotSourceMetadata(const fs::path& work) {
    namespace core = uzp::core;
    namespace store = uzp::store;
    namespace json = uzp::core::json;
    core::Id generator = core::kNoId;
    core::DocumentState initial;
    initial.project_uuid = "6f1c2a3e-0000-4000-8000-0000000a3281";
    initial.project = GeneratorProject(generator);
    ProceduralRequest capture;
    capture.asset = core::ParseAssetUrl("uzasset://test/noise@1");
    capture.params = {{"gain", 0.5}};
    capture.meshClass = "quad";
    capture.output = {8, ChannelFormat::U16, "raw", 1};
    capture.outputId = "grey";
    capture.settings = EvaluationSettings(initial.project);
    store::PlaneImage image;
    image.width = image.height = 8;
    image.format = core::ChannelFormat::L16;
    for (int i = 0; i < 128; ++i) image.texels.push_back(static_cast<char>(i * 29));
    const std::string exportFile = store::codec::EncodePng(image);
    const std::string signatureKey = SignatureHash(capture);
    const std::string exportHash = core::Sha256Hex(exportFile);
    const std::vector<std::string> outputs{"grey", "mask"};
    const json::Value expectedMetadata = store::SourceMetadataJson(SignatureJson(capture), outputs);
    const auto entryOf = [&](const core::Project& project) -> const json::Object* {
        const auto member = project.extra.find(std::string(store::kSnapshotsKey));
        if (member == project.extra.end()) return nullptr;
        const auto& entries = std::get<json::Object>(member->second.data);
        const auto it = entries.find(signatureKey);
        return it == entries.end() ? nullptr : &std::get<json::Object>(it->second.data);
    };
    const auto committed = [](const auto& outcome) {
        return outcome && outcome->result && outcome->result->status == core::ResultStatus::committed;
    };
    const auto reason = [](const auto& refused, std::string_view expected) {
        return !refused && refused.error().reason == expected;
    };

    {
        auto legacy = store::ProjectStore::Create(work / "legacy-metadata.uzp", initial);
        core::Document document(initial);
        legacy->Attach(document);
        const auto outcome = RecordSnapshotExport(*legacy, document, capture, exportFile, initial.project_uuid, 0);
        Check(committed(outcome), "metadata: a recording without metadata commits");
        const json::Object* entry = entryOf(*document.snapshot().project);
        Check(entry && entry->size() == 4 && !entry->contains(store::kSourceMetadataKey),
              "metadata: an entry recorded without metadata keeps exactly its four members");
        // The authored pre-metadata entry: the signature, this project, and the store's own plane binding.
        const json::Object legacyEntry =
            entry ? json::Object{{"signature", SignatureJson(capture)},
                                 {"project_uuid", initial.project_uuid},
                                 {"plane", entry->at("plane")},
                                 {"plane_versions", entry->at("plane_versions")}}
                  : json::Object{};
        Check(entry && json::WriteCanonical(json::Value(*entry)) == json::WriteCanonical(json::Value(legacyEntry)),
              "metadata: an entry recorded without metadata has exactly the pre-metadata canonical bytes");
        Check(outcome && outcome->committed &&
                  outcome->committed->idempotency_key == "snapshot-" + signatureKey + "-" + exportHash &&
                  outcome->committed->request_hash ==
                      core::RequestHash("procedural_snapshot",
                                        {{"signature_sha256", signatureKey}, {"export_sha256", exportHash}}),
              "metadata: without metadata the operation key and arguments are unchanged");
        legacy->Save(document);
        legacy->Close();
        auto reopened = store::ProjectStore::Open(work / "legacy-metadata.uzp");
        const auto backend = SnapshotBackend::Load(*reopened.store, reopened.state.project);
        Check(backend && reason(backend->ImageOutputs(capture), kNoImageOutputs),
              "metadata: a snapshot recorded without metadata reports its outputs as unknown");
        reopened.store->Close();
    }

    const fs::path path = work / "source-metadata.uzp";
    auto metadataStore = store::ProjectStore::Create(path, initial);
    core::Document document(initial);
    metadataStore->Attach(document);
    const auto outputsOnly = [](std::vector<std::string> names) {
        return store::SourceMetadata{std::move(names), std::nullopt, std::nullopt, std::nullopt};
    };
    const std::vector<std::pair<std::string, std::vector<std::string>>> invalid{
        {"empty", {}}, {"absent output", {"mask"}}, {"repeated", {"grey", "grey"}}, {"empty name", {"grey", ""}}};
    for (const auto& [name, bad] : invalid) {
        const auto refused =
            RecordSnapshotExport(*metadataStore, document, capture, exportFile, initial.project_uuid, 0, outputsOnly(bad));
        Check(!refused && document.revision() == 0 && store::ReadCurrentRevision(metadataStore->container()) == 0,
              "metadata: " + name + " image outputs are refused before a transaction");
    }
    const auto recorded =
        RecordSnapshotExport(*metadataStore, document, capture, exportFile, initial.project_uuid, 0, outputsOnly(outputs));
    Check(committed(recorded) && document.revision() == 1, "metadata: recorded image outputs commit with the snapshot");
    const std::string metadataHash = core::Sha256Hex(json::WriteCanonical(expectedMetadata));
    Check(recorded && recorded->committed &&
              recorded->committed->idempotency_key == "snapshot-" + signatureKey + "-" + exportHash + "-" + metadataHash &&
              recorded->committed->request_hash ==
                  core::RequestHash("procedural_snapshot", {{"signature_sha256", signatureKey},
                                                            {"export_sha256", exportHash},
                                                            {"source_metadata_sha256", metadataHash}}),
          "metadata: the metadata hash joins the operation key and arguments");
    const json::Object* entry = entryOf(*document.snapshot().project);
    Check(entry && entry->size() == 5 && entry->at(std::string(store::kSourceMetadataKey)) == expectedMetadata &&
              std::get<std::string>(std::get<json::Object>(expectedMetadata.data).at("asset").data) ==
                  "uzasset://test/noise@1",
          "metadata: the entry stores the schema, the exact pin and the ordered outputs under the unchanged signature hash");

    const auto replay =
        RecordSnapshotExport(*metadataStore, document, capture, exportFile, initial.project_uuid, 1, outputsOnly(outputs));
    Check(replay && replay->decision.admission == core::Admission::stored_outcome && document.revision() == 1,
          "metadata: the identical recording replays its stored outcome");
    bool otherReplayed = true;
    try {
        const std::vector<std::string> other{"mask", "grey"};
        const auto changed =
            RecordSnapshotExport(*metadataStore, document, capture, exportFile, initial.project_uuid, 1, outputsOnly(other));
        otherReplayed = changed && (changed->decision.admission == core::Admission::stored_outcome || committed(changed));
    } catch (const std::exception&) {
        otherReplayed = false;
    }
    Check(!otherReplayed && document.revision() == 1 &&
              entryOf(*document.snapshot().project)->at(std::string(store::kSourceMetadataKey)) == expectedMetadata,
          "metadata: other metadata neither replays the recording nor changes the immutable snapshot");
    bool bareReplayed = true;
    try {
        const auto bare = RecordSnapshotExport(*metadataStore, document, capture, exportFile, initial.project_uuid, 1);
        bareReplayed = bare && (bare->decision.admission == core::Admission::stored_outcome || committed(bare));
    } catch (const std::exception&) {
        bareReplayed = false;
    }
    Check(!bareReplayed && document.revision() == 1, "metadata: a recording without metadata does not replay one with it");

    const std::vector<std::pair<std::string, std::function<void(json::Object&)>>> edits{
        {"schema", [](json::Object& e) { std::get<json::Object>(e.at("source_metadata").data)["schema"] = std::string("other/1"); }},
        {"pin", [](json::Object& e) { std::get<json::Object>(e.at("source_metadata").data)["asset"] = std::string("uzasset://test/noise@2"); }},
        {"duplicate", [](json::Object& e) {
             std::get<json::Object>(e.at("source_metadata").data)["image_outputs"] = json::Array{std::string("grey"), std::string("grey")};
         }},
        {"absent output", [](json::Object& e) {
             std::get<json::Object>(e.at("source_metadata").data)["image_outputs"] = json::Array{std::string("mask")};
         }},
        {"non-string output", [](json::Object& e) {
             std::get<json::Object>(e.at("source_metadata").data)["image_outputs"] = json::Array{std::string("grey"), int64_t{1}};
         }},
        {"extra member", [](json::Object& e) { std::get<json::Object>(e.at("source_metadata").data)["extra"] = int64_t{1}; }},
        {"null", [](json::Object& e) { e["source_metadata"] = nullptr; }},
    };
    for (const auto& [name, mutate] : edits) {
        json::Value member = document.snapshot().project->extra.at(std::string(store::kSnapshotsKey));
        mutate(std::get<json::Object>(std::get<json::Object>(member.data).at(signatureKey).data));
        const auto parsed = store::SnapshotEntries(member);
        Check(parsed.size() == 1 && !parsed[0].error.empty() && !parsed[0].source_metadata &&
                  !store::SnapshotProblem(parsed[0], initial.project_uuid).empty(),
              "metadata: an entry with a bad " + name + " is malformed");
        bool refused = false;
        try {
            const auto edited = metadataStore->Submit(
                document, {"metadata-test", json::Object{}, "bad-metadata-" + name, document.revision()},
                [&](core::Edit& edit) { edit.project().extra[std::string(store::kSnapshotsKey)] = member; });
            refused = !committed(std::optional<core::RequestOutcome>(edited));
        } catch (const std::exception&) {
            refused = true;
        }
        Check(refused && document.revision() == 1 &&
                  entryOf(*document.snapshot().project)->at(std::string(store::kSourceMetadataKey)) == expectedMetadata,
              "metadata: a bad " + name + " is refused at commit without mutation");
    }

    metadataStore->Save(document);
    metadataStore->Close();
    const auto bundle = work / "source-metadata-bundle";
    store::ExportBundle(path, bundle);
    store::ImportBundle(bundle, work / "source-metadata-imported.uzp");
    for (const fs::path& file : {path, work / "source-metadata-imported.uzp"}) {
        const std::string where = file == path ? "reopen" : "bundle import";
        auto reopened = store::ProjectStore::Open(file);
        const auto backend = SnapshotBackend::Load(*reopened.store, reopened.state.project);
        auto read = backend ? backend->ImageOutputs(capture) : std::expected<std::vector<std::string>, UnsupportedProcedural>(std::unexpect, Refuse("test", "load failed"));
        Check(read && *read == outputs, "metadata: recorded image outputs survive " + where);
        if (read) read->push_back("changed");
        const auto again = backend ? backend->ImageOutputs(capture) : read;
        Check(again && *again == outputs, "metadata: a returned list is a copy (" + where + ")");
        const auto stored = backend ? backend->Stored(capture) : std::expected<const SnapshotRaster*, UnsupportedProcedural>(std::unexpect, Refuse("test", "load failed"));
        Check(stored && (*stored)->bytes == image.texels, "metadata: the stored raster is unchanged (" + where + ")");
        ProceduralRequest neighbour = capture;
        neighbour.params["gain"] = 0.75;
        Check(backend && reason(backend->ImageOutputs(neighbour), kNoSnapshot),
              "metadata: another signature never borrows the recorded outputs (" + where + ")");
        reopened.store->Close();
    }

    const std::vector<std::string> reordered{"mask", "grey"};
    Check(json::WriteCanonical(store::SourceMetadataJson(SignatureJson(capture), reordered)) !=
              json::WriteCanonical(expectedMetadata),
          "metadata: the order of the outputs changes the canonical metadata and its hash");

    // A capture receipt only ever names the singleton output of its signature.
    const std::string resource = "resource://shelf/noise?version=1";
    const json::Array single{std::string("grey")};
    const auto source = [&](const std::string& name, const json::Array& list, const std::string& active) {
        return json::Object{{"resource", name}, {"outputs", list}, {"active_output", active}};
    };
    const auto receipt = [](const json::Object& first, const json::Object& second) {
        return json::Value(json::Object{{"readback", json::Object{{"sources", json::Array{first, second}}}}});
    };
    const auto read = ReceiptImageOutputs(receipt(source(resource, single, "grey"), source(resource, single, "grey")),
                                          resource, capture);
    Check(read && *read == std::vector<std::string>{"grey"}, "metadata: a receipt's paired readback gives its singleton output");
    const json::Array extra{std::string("grey"), std::string("mask")};
    Check(!ReceiptImageOutputs(receipt(source(resource, extra, "grey"), source(resource, extra, "grey")), resource, capture),
          "metadata: a receipt with an extra output refuses (no capture domain widening)");
    Check(!ReceiptImageOutputs(receipt(source(resource, single, "mask"), source(resource, single, "mask")), resource, capture),
          "metadata: a receipt whose active output differs from the signature refuses");
    Check(!ReceiptImageOutputs(receipt(source(resource, single, "grey"), source(resource, single, "mask")), resource, capture),
          "metadata: paired sources with different active outputs refuse");
    Check(!ReceiptImageOutputs(receipt(source(resource, single, "grey"), source(resource, extra, "grey")), resource, capture),
          "metadata: paired sources with different outputs refuse");
    Check(!ReceiptImageOutputs(receipt(source(resource, single, "grey"), source("resource://shelf/other?version=1", single, "grey")),
                               resource, capture),
          "metadata: a paired source of another resource refuses");
    const json::Array other{std::string("mask")};
    Check(!ReceiptImageOutputs(receipt(source(resource, other, "grey"), source(resource, other, "grey")), resource, capture),
          "metadata: outputs without the signature's output refuse");
    const json::Array numbers{int64_t{1}};
    Check(!ReceiptImageOutputs(receipt(source(resource, numbers, "grey"), source(resource, numbers, "grey")), resource, capture),
          "metadata: non-string outputs refuse");
    Check(!ReceiptImageOutputs(json::Object{{"readback", json::Object{{"sources", json::Array{source(resource, single, "grey")}}}}},
                               resource, capture),
          "metadata: a receipt without both paired sources refuses");
    Check(!ReceiptImageOutputs(receipt(json::Object{{"resource", resource}, {"active_output", std::string("grey")}},
                                       json::Object{{"resource", resource}, {"active_output", std::string("grey")}}),
                               resource, capture),
          "metadata: sources without outputs refuse");
    Check(!ReceiptImageOutputs(receipt(json::Object{{"resource", resource}, {"outputs", single}},
                                       json::Object{{"resource", resource}, {"outputs", single}}),
                               resource, capture),
          "metadata: sources without an active output refuse");
    Check(!ReceiptImageOutputs(json::Object{}, resource, capture), "metadata: a receipt without readback refuses");

    // Schema /2: optional observations; an empty observation differs from an absent one.
    const json::Value signature = SignatureJson(capture);
    // An authored descriptor in the bridge's serialization (painter_side.described), not Painter data.
    const json::Object gain{{"value", 0.5},
                            {"name", std::string("gain")},
                            {"short_name", std::string("gain")},
                            {"label", std::string("Authored gain")},
                            {"widget_type", std::string("Slider")},
                            {"enum_values", json::Object{}},
                            {"properties", json::Object{{"min", int64_t{0}}, {"max", int64_t{1}}}}};
    const store::SourceMetadata observed{{"grey", "mask"}, std::vector<std::string>{},
                                         std::vector<std::string>{"authored preset"}, json::Object{{"gain", gain}}};
    const json::Value v2 = store::SourceMetadataJson(signature, observed);
    const auto reread = store::ParseSourceMetadata(signature, v2);
    Check(std::get<std::string>(std::get<json::Object>(v2.data).at("schema").data) == store::kSourceMetadataSchemaV2 &&
              reread && *reread == observed && reread->image_inputs && reread->image_inputs->empty(),
          "metadata v2: optional observations roundtrip and an empty observation stays present");
    Check(json::WriteCanonical(store::SourceMetadataJson(signature, outputsOnly(outputs))) == json::WriteCanonical(expectedMetadata),
          "metadata v2: outputs alone are still written as schema /1");
    const std::vector<std::pair<std::string, std::function<void(json::Object&)>>> invalidV2{
        {"repeated input", [](json::Object& m) { m["image_inputs"] = json::Array{std::string("a"), std::string("a")}; }},
        {"non-string preset", [](json::Object& m) { m["presets"] = json::Array{int64_t{1}}; }},
        {"non-object property", [](json::Object& m) { m["properties"] = json::Object{{"gain", int64_t{1}}}; }},
        {"property whose name differs from its key", [gain](json::Object& m) {
             json::Object renamed = gain;
             renamed["name"] = std::string("other");
             m["properties"] = json::Object{{"gain", renamed}};
         }},
        {"property with an undocumented widget", [gain](json::Object& m) {
             json::Object widget = gain;
             widget["widget_type"] = std::string("Knob");
             m["properties"] = json::Object{{"gain", widget}};
         }},
        {"property missing a getter", [gain](json::Object& m) {
             json::Object partial = gain;
             partial.erase("label");
             m["properties"] = json::Object{{"gain", partial}};
         }},
        {"property with a non-integer enum value", [gain](json::Object& m) {
             json::Object labels = gain;
             labels["enum_values"] = json::Object{{"On", std::string("1")}};
             m["properties"] = json::Object{{"gain", labels}};
         }},
        {"property with a null value", [gain](json::Object& m) {
             json::Object empty = gain;
             empty["value"] = nullptr;
             m["properties"] = json::Object{{"gain", empty}};
         }},
        {"property with a vector value (no typed codec)", [gain](json::Object& m) {
             json::Object vector = gain;
             vector["value"] = json::Array{0.25, 0.75};
             m["properties"] = json::Object{{"gain", vector}};
         }},
        {"property with a boolean value", [gain](json::Object& m) {
             json::Object flag = gain;
             flag["value"] = true;
             m["properties"] = json::Object{{"gain", flag}};
         }},
        {"unknown member", [](json::Object& m) { m["defaults"] = json::Object{}; }},
        {"v1 with a v2 member", [](json::Object& m) { m["schema"] = std::string(store::kSourceMetadataSchema); }},
    };
    for (const auto& [name, mutate] : invalidV2) {
        json::Object broken = std::get<json::Object>(v2.data);
        mutate(broken);
        Check(!store::ParseSourceMetadata(signature, broken), "metadata v2: a " + name + " is refused");
    }
    ProceduralRequest second = capture;
    second.params["gain"] = 0.25;
    const store::SourceMetadata secondObserved = observed;
    {
        auto v2Store = store::ProjectStore::Create(work / "source-metadata-v2.uzp", initial);
        core::Document v2Document(initial);
        v2Store->Attach(v2Document);
        const auto stored = RecordSnapshotExport(*v2Store, v2Document, second, exportFile, initial.project_uuid, 0, secondObserved);
        Check(committed(stored), "metadata v2: observations commit with the snapshot");
        v2Store->Save(v2Document);
        v2Store->Close();
    }
    auto v2Reopened = store::ProjectStore::Open(work / "source-metadata-v2.uzp");
    const auto v2Backend = SnapshotBackend::Load(*v2Reopened.store, v2Reopened.state.project);
    const auto v2Metadata = v2Backend ? v2Backend->Metadata(second)
                                      : std::expected<store::SourceMetadata, UnsupportedProcedural>(std::unexpect, Refuse("test", "load failed"));
    Check(v2Metadata && *v2Metadata == secondObserved, "metadata v2: observations survive save and reopen");
    Check(v2Backend && reason(v2Backend->Metadata(capture), kNoSnapshot),
          "metadata v2: another signature never borrows the observations");
    v2Reopened.store->Close();

    // A receipt's full observations: identical paired sources and typed parameters.
    json::Object parameters;
    for (const auto& [name, value] : capture.params) parameters[name] = ParamJson(value);
    const auto fullSource = [&](json::Object extra) {
        json::Object built{{"resource", resource}, {"outputs", single}, {"active_output", std::string("grey")},
                           {"parameters", parameters}, {"inputs", json::Array{}}};
        for (auto& [key, value] : extra) built[key] = std::move(value);
        return built;
    };
    const json::Object observedSource =
        fullSource({{"presets", json::Array{std::string("authored preset")}}, {"properties", json::Object{{"gain", gain}}}});
    const auto fullRead = ReceiptSourceMetadata(receipt(observedSource, observedSource), resource, capture);
    Check(fullRead && fullRead->image_outputs == std::vector<std::string>{"grey"} && fullRead->image_inputs &&
              fullRead->image_inputs->empty() && fullRead->presets == std::vector<std::string>{"authored preset"} &&
              fullRead->properties == json::Object{{"gain", gain}},
          "metadata receipt: the paired readback gives every observation");
    const json::Object unobservedSource = fullSource({});
    const auto unobservedRead = ReceiptSourceMetadata(receipt(unobservedSource, unobservedSource), resource, capture);
    Check(unobservedRead && unobservedRead->image_inputs && !unobservedRead->presets && !unobservedRead->properties,
          "metadata receipt: unobserved presets and properties stay absent");
    json::Object otherPresets = observedSource;
    otherPresets["presets"] = json::Array{};
    Check(!ReceiptSourceMetadata(receipt(observedSource, otherPresets), resource, capture),
          "metadata receipt: paired sources with different observations refuse");
    json::Object retyped = observedSource;
    std::get<json::Object>(retyped["parameters"].data)["gain"] = std::string("0.5");
    Check(!ReceiptSourceMetadata(receipt(retyped, retyped), resource, capture),
          "metadata receipt: a parameter of another type refuses");
    json::Object extraParameter = observedSource;
    std::get<json::Object>(extraParameter["parameters"].data)["extra"] = int64_t{1};
    Check(!ReceiptSourceMetadata(receipt(extraParameter, extraParameter), resource, capture),
          "metadata receipt: parameters other than the signature's refuse");
    // Parameters compare through the signature's own codec (ParamJson, numbers by value): a real
    // readback double 15.0 matches the signature's 15, and -0.0 is the same identity as 0.0.
    ProceduralRequest integral = capture;
    integral.params["gain"] = 15.0;
    json::Object integralSource = observedSource;
    std::get<json::Object>(integralSource["parameters"].data)["gain"] = 15.0;
    const auto integralRead = ReceiptSourceMetadata(receipt(integralSource, integralSource), resource, integral);
    Check(bool(integralRead) && json::WriteCanonical(ParamJson(integral.params.at("gain"))) == "15",
          "metadata receipt: an integral double parameter matches the signature's value encoding",
          integralRead ? std::string() : integralRead.error());
    ProceduralRequest zeroCapture = capture;
    zeroCapture.params["gain"] = 0.0;
    json::Object zeroSource = observedSource;
    std::get<json::Object>(zeroSource["parameters"].data)["gain"] = 0.0;
    json::Object negativeZeroSource = zeroSource;
    std::get<json::Object>(negativeZeroSource["parameters"].data)["gain"] = -0.0;
    ProceduralRequest negativeZeroCapture = capture;
    negativeZeroCapture.params["gain"] = -0.0;
    const auto negativeRead = ReceiptSourceMetadata(receipt(negativeZeroSource, negativeZeroSource), resource, zeroCapture);
    Check(bool(negativeRead) && SignatureHash(zeroCapture) == SignatureHash(negativeZeroCapture),
          "metadata receipt: a parameter's signed zero is one signature identity and is accepted",
          negativeRead ? std::string() : negativeRead.error());
    json::Object signedGain = gain;
    signedGain["value"] = 0.0;
    json::Object zeroObservation = zeroSource;
    zeroObservation["properties"] = json::Object{{"gain", signedGain}};
    json::Object negativeZeroObservation = zeroObservation;
    signedGain["value"] = -0.0;
    negativeZeroObservation["properties"] = json::Object{{"gain", signedGain}};
    const bool signKept = json::WriteCanonical(json::Value(-0.0)) != json::WriteCanonical(json::Value(0.0));
    Check(signKept && !ReceiptSourceMetadata(receipt(zeroObservation, negativeZeroObservation), resource, zeroCapture),
          "metadata receipt: paired observations that differ only in the sign of zero refuse",
          "canonical -0.0 is " + json::WriteCanonical(json::Value(-0.0)));
    json::Object badDescriptor = observedSource;
    json::Object renamedGain = gain;
    renamedGain["name"] = std::string("other");
    badDescriptor["properties"] = json::Object{{"gain", renamedGain}};
    Check(!ReceiptSourceMetadata(receipt(badDescriptor, badDescriptor), resource, capture),
          "metadata receipt: a malformed property descriptor refuses");
    return Finish();
}
