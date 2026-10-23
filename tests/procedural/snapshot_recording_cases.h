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
