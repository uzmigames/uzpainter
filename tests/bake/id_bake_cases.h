// ID cases (phase3.4_baker-id, decision 337). Included inside the native driver's namespace after
// the Position cases; they use `BevelHit` and the fixtures. Expected labels are analytic: which
// authored high mesh lies under each texel.

BakeRequest IdLabelsRequest(BakeRequest request) {
    request.usages = {MeshMapUsage::ID};
    request.id.source = IdColorSource::MeshId;
    request.id.generator = std::nullopt;  // the label map only: every generator is refused
    return request;
}

void CheckLabelsOffHits(const BakeResult& r) {
    CHECK_EQ(r.id_labels.size(), std::size_t(r.width) * r.height);
    for (std::size_t i = 0; i < r.id_labels.size(); ++i) {
        CHECK_EQ(IsHit(r.texel_class[i]), r.id_labels[i] != 0);
        CHECK(r.id_labels[i] <= r.id_label_meshes.size());
    }
}

void CaseIdPlane() {
    // Two high planes split at x = 0 under the low plane [-1, 1]^2: label 1 left, label 2 right.
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    const BakeMesh left = fixtures::Plane("left", -2, 0, -2, 2, 0.005f);
    const BakeMesh right = fixtures::Plane("right", 0, 2, -2, 2, 0.003f);
    BakeRequest request = PlaneRequest(low);
    request.detail.low_as_high = false;
    request.detail.max_height = request.detail.max_depth = 0.05f;
    request.high = {&left, &right};
    request = IdLabelsRequest(request);
    const BakeResult r = Bake(baker, request);
    CheckConservation(r);
    CheckLabelsOffHits(r);
    CHECK((r.id_label_meshes == std::vector<std::string>{"left", "right"}));
    CHECK_EQ(r.texels.straight_hit, kCovered);
    std::uint64_t counts[3] = {0, 0, 0};
    for (std::size_t i = 0; i < kTexels; ++i) {
        if (!UnderPlaneUv(i)) continue;
        const double x = 4.0 * ((i % 64 + 0.5) / 64.0) - 2.0;
        CHECK_EQ(r.id_labels[i], x < 0.0 ? 1 : 2);
        ++counts[r.id_labels[i]];
    }
    CHECK_EQ(counts[1], kCovered / 2);
    CHECK_EQ(counts[2], kCovered / 2);
    CHECK(r.ao.empty() && r.position.empty() && r.world_normal.empty());
}

void CaseIdSphere() {
    // The sphere on the ground low as high, as one part and as two (ground, then sphere): the
    // label is the part the hit lies on.
    EmbreeBaker baker;
    const BakeMesh whole = fixtures::SphereOnGround();
    const BakeResult one = Bake(baker, IdLabelsRequest(SphereRequest(whole, 7)));
    CheckConservation(one);
    CheckLabelsOffHits(one);
    CHECK((one.id_label_meshes == std::vector<std::string>{"sphere_on_ground"}));
    // Split the fixture by UV half: the ground's triangles come first.
    BakeMesh ground = whole, sphere = whole;
    ground.name = "ground";
    sphere.name = "sphere";
    ground.indices.clear();
    sphere.indices.clear();
    for (std::size_t t = 0; t < whole.indices.size(); t += 3) {
        const bool on_ground = whole.uvs[whole.indices[t]].x < 0.5f;
        for (std::size_t k = 0; k < 3; ++k) (on_ground ? ground : sphere).indices.push_back(whole.indices[t + k]);
    }
    BakeRequest request = IdLabelsRequest(SphereRequest(ground, 7));
    request.low = {&ground, &sphere};
    const BakeResult two = Bake(baker, request);
    CheckConservation(two);
    CheckLabelsOffHits(two);
    std::uint64_t labels[3] = {0, 0, 0};
    for (std::size_t i = 0; i < two.id_labels.size(); ++i) {
        if (!two.id_labels[i]) continue;
        const double u = (i % two.width + 0.5) / two.width;
        CHECK_EQ(two.id_labels[i], u < 0.5 ? 1 : 2);
        ++labels[two.id_labels[i]];
    }
    CHECK(labels[1] > 0 && labels[2] > 0);
    // The split changes the labels, never the hits.
    CHECK(two.texel_class == one.texel_class);
}

void CaseIdBevel() {
    // The bevelled cube with highs matched by name: the cube's islands hit cube_high (label 1), the
    // knob's hits knob_high_ignorebf (label 2), and the decoy (label 3) is never hit.
    EmbreeBaker baker;
    Bevel fixture;
    const BakeResult r = Bake(baker, IdLabelsRequest(fixture.Request(0.07f)));
    CheckConservation(r);
    CheckLabelsOffHits(r);
    CHECK((r.id_label_meshes == std::vector<std::string>{"cube_high", "knob_high_ignorebf", "decoy_high"}));
    std::uint64_t hits = 0;
    for (std::uint32_t y = 0; y < kAtlasH; ++y) {
        for (std::uint32_t x = 0; x < kAtlasW; ++x) {
            const std::size_t i = std::size_t(y) * kAtlasW + x;
            Vec3d point, normal;
            std::uint32_t mesh = 0;
            if (!BevelHit(x, y, 0.07, point, normal, mesh)) {
                CHECK_EQ(r.id_labels[i], 0);
                continue;
            }
            CHECK_EQ(r.id_labels[i], mesh + 1);
            ++hits;
        }
    }
    CHECK_EQ(hits, r.texels.straight_hit);
    // With FilterMethod Always the decoy over the top face takes its rays: back-face hits, no label.
    BakeRequest always = IdLabelsRequest(fixture.Request(0.07f));
    always.detail.filter_method = FilterMethod::Always;
    const BakeResult a = Bake(baker, always);
    CheckLabelsOffHits(a);
    CHECK(a.texels.back_face_hit > 0);
}

void CaseIdThreadsInProcess() {
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest request = IdLabelsRequest(fixture.Request(0.07f));
    std::string reference;
    for (std::uint32_t threads : {1u, 4u, std::max(1u, std::thread::hardware_concurrency())}) {
        request.threads = threads;
        const std::string bytes = SerializeResult(Bake(baker, request));
        if (reference.empty()) reference = bytes;
        CHECK(bytes == reference);
    }
}

void CaseIdIsolation() {
    // With AO it shares the primary hits and leaves AO's bytes alone; an AO result has no ID block.
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest both = IdLabelsRequest(fixture.Request(0.07f));
    both.usages = {MeshMapUsage::AO, MeshMapUsage::ID};
    const BakeResult a = Bake(baker, fixture.Request(0.07f));
    const BakeResult b = Bake(baker, both);
    const BakeResult l = Bake(baker, IdLabelsRequest(fixture.Request(0.07f)));
    CHECK(b.ao_raw == a.ao_raw && b.texel_class == a.texel_class && b.id_labels == l.id_labels);
    CHECK(a.id_labels.empty() && SerializeResult(a).find("IDM1") == std::string::npos);
}

void CaseIdRefusals() {
    EmbreeBaker baker;
    Bevel fixture;
    for (IdColorSource source : {IdColorSource::VertexColor, IdColorSource::MaterialColor, IdColorSource::FileId,
                                 IdColorSource::Submesh}) {
        BakeRequest request = IdLabelsRequest(fixture.Request(0.07f));
        request.id.source = source;
        const std::string message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
        CHECK(Contains(message, "ColorSource") && Contains(message, "phase3.4_baker-id"));
    }
    for (IdColorGenerator generator : {IdColorGenerator::Random, IdColorGenerator::HueShift, IdColorGenerator::Grayscale}) {
        BakeRequest request = IdLabelsRequest(fixture.Request(0.07f));
        request.id.generator = generator;
        const std::string message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
        CHECK(Contains(message, "ColorGenerator") && Contains(message, "phase3.4_baker-id"));
    }
    BakeRequest defaults = fixture.Request(0.07f);  // Painter's defaults: Material color, Hue shift
    defaults.usages = {MeshMapUsage::ID};
    ExpectThrow<NotYetSupported>([&] { baker.bake(defaults); });
    BakeRequest request = IdLabelsRequest(fixture.Request(0.07f));
    request.detail.subsampling = 4;
    std::string message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    CHECK(Contains(message, "SubSampling") && Contains(message, "phase3.4_baker-id"));
    request = IdLabelsRequest(fixture.Request(0.07f));
    request.common.dilation_width = 1;
    message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    CHECK(Contains(message, "DilationWidth") && Contains(message, "phase3.4_baker-id"));
    CHECK(baker.caps().parity_owner_tasks.at(MeshMapUsage::ID) == "phase3.4_baker-id");
}

void CaseIdParameters() {
    // ID's values are stored per texture set, saved and mapped; the generator always maps, so a
    // parameter-made ID bake is refused until a golden settles the palette.
    EmbreeBaker baker;
    Bevel fixture;
    const BakeRequest base = ParameterDistanceUnits(IdLabelsRequest(fixture.Request(0.07f)));
    BakingParameters params("bevelled_cube");
    const auto common = params.common();
    const auto id = params.baker(MeshMapUsage::ID);
    using Pair = std::pair<std::int64_t, std::int64_t>;
    BakingParameters::set({{common.at("OutputSize"), Pair{base.output_size_log2[0], base.output_size_log2[1]}},
                           {common.at("DilationWidth"), std::int64_t{0}},
                           {common.at("FilterMethod"), EnumLabel{"By mesh name"}},
                           {common.at("MaxHeight"), static_cast<double>(base.detail.max_height)},
                           {common.at("MaxDepth"), static_cast<double>(base.detail.max_depth)},
                           {common.at("RelativeScale"), false}});
    MappedRequest mapped = RequestFromParameters(params, base);
    CHECK(mapped.request.id.source == IdColorSource::MaterialColor);  // Painter's defaults
    CHECK(mapped.request.id.generator == IdColorGenerator::HueShift);
    BakingParameters::set({{id.at("ColorSource"), EnumLabel{"Mesh ID / Polygroup"}},
                           {id.at("ColorGenerator"), EnumLabel{"Grayscale"}}});
    mapped = RequestFromParameters(params, base);
    CHECK(mapped.request.id.source == IdColorSource::MeshId);
    CHECK(mapped.request.id.generator == IdColorGenerator::Grayscale);
    std::string message = ExpectThrow<NotYetSupported>([&] { baker.bake(mapped.request); });
    CHECK(Contains(message, "Grayscale") && Contains(message, "phase3.4_baker-id"));
    // The mapped request without its generator is the label request.
    mapped.request.id.generator = std::nullopt;
    CHECK(SerializeResult(Bake(baker, mapped.request)) == SerializeResult(Bake(baker, base)));
    const uzp::core::BakeSettings saved = ToBakeSettings(params);
    CHECK(saved.per_baker.at("ID").at("ColorSource") == uzp::core::json::Value("Mesh ID / Polygroup"));
    BakingParameters loaded("bevelled_cube");
    LoadBakeSettings(loaded, saved);
    CHECK(ToBakeSettings(loaded) == saved);
    BakingSession session({"a", "b"});
    message = ExpectThrow<NotYetSupported>([&] { session.set_linked_group({"a", "b"}, "a", MeshMapUsage::ID); });
    CHECK(Contains(message, "phase3.4_baker-id"));
    CHECK(StoresBakerValues(MeshMapUsage::ID));
}
