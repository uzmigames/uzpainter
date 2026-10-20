// Position cases (phase3.4_baker-position, decision 337). Included inside the native driver's
// namespace after the WorldSpaceNormal cases, whose `BevelHit` and checks they use. Expected values
// are analytic: the authored planes, the fixture's UV-to-position mapping, the sphere's radius and
// the chamfer depth of the bevelled cube.

BakeRequest PositionBevelRequest(const Bevel& fixture) {
    BakeRequest request = fixture.Request(0.07f);
    request.usages = {MeshMapUsage::Position};
    request.position.normalization = PositionNormalization::None;
    return request;
}

void CheckPositionAt(const BakeResult& r, std::size_t texel, const Vec3d& expected, double scale,
                     double tolerance = 1e-5) {
    CHECK(IsHit(r.texel_class[texel]));
    const PositionNormalizationRecord& record = r.position_normalization;
    if (record.channels == 3) {
        CHECK(Near(r.position[3 * texel], expected.x * scale, tolerance));
        CHECK(Near(r.position[3 * texel + 1], expected.y * scale, tolerance));
        CHECK(Near(r.position[3 * texel + 2], expected.z * scale, tolerance));
        return;
    }
    const PositionAxis axis = record.settings.axis;
    const double value = axis == PositionAxis::X ? expected.x : axis == PositionAxis::Y ? expected.y : expected.z;
    CHECK(Near(r.position[texel], value * scale, tolerance));
}

void CasePositionPlane() {
    // The low plane [-1, 1]^2 (UV [0.25, 0.75]^2) over a high plane at z = 0.005: the hit is
    // (4u - 2, 4v - 2, 0.005) mesh units, in centimetres at 2.54 cm per unit.
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    const BakeMesh high = NormalHigh({0, 0, 1});
    BakeRequest request = NormalRequest(low, high);
    request.usages = {MeshMapUsage::Position};
    request.position.normalization = PositionNormalization::None;
    request.scale_to_internal = 2.54;
    request.detail.max_height = request.detail.max_depth = 0.05f * 2.54f;  // centimetres
    for (const auto& [mode, axis] : std::vector<std::pair<PositionMode, PositionAxis>>{
             {PositionMode::AllAxis, PositionAxis::X},
             {PositionMode::OneAxis, PositionAxis::X},
             {PositionMode::OneAxis, PositionAxis::Y},
             {PositionMode::OneAxis, PositionAxis::Z}}) {
        request.position.mode = mode;
        request.position.axis = axis;
        const BakeResult r = Bake(baker, request);
        CheckConservation(r);
        CHECK_EQ(r.texels.straight_hit, kCovered);
        const std::size_t channels = mode == PositionMode::AllAxis ? 3 : 1;
        CHECK_EQ(r.position_normalization.channels, channels);
        CheckZeroOffHits(r, r.position, channels);
        for (std::size_t i = 0; i < kTexels; ++i) {
            if (!UnderPlaneUv(i)) continue;
            const double u = (i % 64 + 0.5) / 64.0;
            const double v = 1.0 - (i / 64 + 0.5) / 64.0;
            CheckPositionAt(r, i, {4 * u - 2, 4 * v - 2, 0.005}, 2.54);
        }
    }
}

void CasePositionSphere() {
    // The sphere on the ground low as high: ground hits at the fixture's UV-to-position mapping,
    // sphere hits on the tessellated sphere of radius 0.5 around (0, 0, 0.5).
    EmbreeBaker baker;
    const BakeMesh low = fixtures::SphereOnGround();
    BakeRequest request = SphereRequest(low, 7);
    request.usages = {MeshMapUsage::Position};
    request.position.normalization = PositionNormalization::None;
    const BakeResult r = Bake(baker, request);
    CheckConservation(r);
    CheckZeroOffHits(r, r.position, 3);
    std::uint64_t ground = 0, sphere = 0;
    const double inner = 0.5 * std::cos(std::numbers::pi / 24) * std::cos(std::numbers::pi / 48);
    for (std::size_t i = 0; i < std::size_t(r.width) * r.height; ++i) {
        if (!IsHit(r.texel_class[i])) continue;
        const double u = (i % r.width + 0.5) / r.width;
        const double v = 1.0 - (i / r.width + 0.5) / r.height;
        if (u < 0.5) {
            CheckPositionAt(r, i, {-2.0 + 4.0 * (u - 0.01) / 0.48, -2.0 + 4.0 * (v - 0.01) / 0.98, 0.0}, 1.0);
            ++ground;
            continue;
        }
        const double x = r.position[3 * i], y = r.position[3 * i + 1], z = r.position[3 * i + 2] - 0.5;
        const double radius = std::sqrt(x * x + y * y + z * z);
        CHECK(radius >= inner && radius <= 0.5 + 1e-5);
        ++sphere;
    }
    CHECK(ground > 0 && sphere > 0);
    CHECK_EQ(ground + sphere, r.texels.straight_hit);
}

void CasePositionBevel() {
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest request = PositionBevelRequest(fixture);
    for (PositionMode mode : {PositionMode::AllAxis, PositionMode::OneAxis}) {
        request.position.mode = mode;
        request.position.axis = PositionAxis::Y;
        const BakeResult r = Bake(baker, request);
        CheckConservation(r);
        CheckZeroOffHits(r, r.position, mode == PositionMode::AllAxis ? 3 : 1);
        std::uint64_t hits = 0;
        for (std::uint32_t y = 0; y < kAtlasH; ++y) {
            for (std::uint32_t x = 0; x < kAtlasW; ++x) {
                Vec3d point, normal;
                std::uint32_t mesh = 0;
                if (!BevelHit(x, y, 0.07, point, normal, mesh)) continue;
                CheckPositionAt(r, std::size_t(y) * kAtlasW + x, point, 1.0);
                ++hits;
            }
        }
        CHECK_EQ(hits, r.texels.straight_hit);
    }
}

void CasePositionThreadsInProcess() {
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest request = PositionBevelRequest(fixture);
    std::string reference;
    for (std::uint32_t threads : {1u, 4u, std::max(1u, std::thread::hardware_concurrency())}) {
        request.threads = threads;
        const std::string bytes = SerializeResult(Bake(baker, request));
        if (reference.empty()) reference = bytes;
        CHECK(bytes == reference);
    }
}

void CasePositionRecord() {
    // The applied normalisation is recorded, and its JSON is the binding's effective_normalization.
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest request = PositionBevelRequest(fixture);
    request.scale_to_internal = 0.5;
    request.position.mode = PositionMode::OneAxis;
    request.position.axis = PositionAxis::Z;
    request.position.scale = PositionNormalizationScale::PerMaterial;
    const BakeResult r = Bake(baker, request);
    const PositionNormalizationRecord& record = r.position_normalization;
    CHECK(record.settings.normalization == PositionNormalization::None);
    CHECK(record.settings.scale == PositionNormalizationScale::PerMaterial);
    CHECK(record.scale_to_internal == 0.5 && record.channels == 1 && !record.bounds_applied);
    using uzp::core::json::Value;
    const uzp::core::json::Object json = PositionNormalizationJson(record);
    CHECK(json.at("Mode") == Value("One axis") && json.at("Axis") == Value("Z"));
    CHECK(json.at("Normalization") == Value("None") && json.at("NormalizationScale") == Value("Per Material"));
    CHECK(json.at("unit") == Value("centimetre") && json.at("scale_to_internal") == Value(0.5));
    CHECK(json.at("bounds").IsNull() && json.at("bounds_applied") == Value(false));
    // Under None no bounds apply, so NormalizationScale changes nothing. The knob's surface lies at
    // z = 3 mesh units: 1.5 cm at 0.5 cm per unit.
    request.position.scale = PositionNormalizationScale::FullScene;
    const BakeResult full = Bake(baker, request);
    CHECK(full.position == r.position);
    Vec3d point, normal;
    std::uint32_t mesh = 0;
    for (std::uint32_t y = 0; y < kAtlasH; ++y) {
        for (std::uint32_t x = 0; x < kAtlasW; ++x) {
            if (BevelHit(x, y, 0.07, point, normal, mesh) && mesh == 1) CheckPositionAt(r, y * kAtlasW + x, point, 0.5);
        }
    }
    // Combined with AO it shares the primary hits and leaves AO's bytes alone.
    BakeRequest both = fixture.Request(0.07f);
    both.usages = {MeshMapUsage::AO, MeshMapUsage::Position};
    both.position.normalization = PositionNormalization::None;
    const BakeResult a = Bake(baker, fixture.Request(0.07f));
    const BakeResult b = Bake(baker, both);
    CHECK(b.ao_raw == a.ao_raw && b.texel_class == a.texel_class);
    CHECK(SerializeResult(a).find("POS1") == std::string::npos && SerializeResult(b).find("POS1") != std::string::npos);
}

void CasePositionRefusals() {
    EmbreeBaker baker;
    Bevel fixture;
    for (PositionNormalization normalization : {PositionNormalization::BBox, PositionNormalization::BSphere}) {
        BakeRequest request = PositionBevelRequest(fixture);
        request.position.normalization = normalization;
        const std::string message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
        CHECK(Contains(message, "Normalization") && Contains(message, "phase3.4_baker-position"));
    }
    BakeRequest defaults = fixture.Request(0.07f);  // Painter's defaults: BSphere, Full Scene
    defaults.usages = {MeshMapUsage::Position};
    ExpectThrow<NotYetSupported>([&] { baker.bake(defaults); });
    BakeRequest request = PositionBevelRequest(fixture);
    request.detail.subsampling = 2;
    std::string message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    CHECK(Contains(message, "SubSampling") && Contains(message, "phase3.4_baker-position"));
    request = PositionBevelRequest(fixture);
    request.common.dilation_width = 2;
    message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    CHECK(Contains(message, "DilationWidth") && Contains(message, "phase3.4_baker-position"));
    CHECK(baker.caps().parity_owner_tasks.at(MeshMapUsage::Position) == "phase3.4_baker-position");
}

void CasePositionParameters() {
    // Position's values are stored per texture set, saved in bake_settings.per_baker.Position and
    // mapped to the request; the baker refuses the labels it does not establish.
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest base = PositionBevelRequest(fixture);
    base.position = PositionSettings{};
    BakingParameters params("bevelled_cube");
    const auto common = params.common();
    const auto position = params.baker(MeshMapUsage::Position);
    CHECK(std::get<EnumLabel>(position.at("Normalization").value()).label == "BSphere");  // Painter's default
    using Pair = std::pair<std::int64_t, std::int64_t>;
    BakingParameters::set({{common.at("OutputSize"), Pair{base.output_size_log2[0], base.output_size_log2[1]}},
                           {common.at("DilationWidth"), std::int64_t{0}},
                           {common.at("FilterMethod"), EnumLabel{"By mesh name"}},
                           {common.at("MaxHeight"), static_cast<double>(base.detail.max_height)},
                           {common.at("MaxDepth"), static_cast<double>(base.detail.max_depth)},
                           {common.at("RelativeScale"), false}});
    MappedRequest mapped = RequestFromParameters(params, base);
    CHECK(mapped.request.position.normalization == PositionNormalization::BSphere);
    CHECK(mapped.request.position.scale == PositionNormalizationScale::FullScene);
    std::string message = ExpectThrow<NotYetSupported>([&] { baker.bake(mapped.request); });
    CHECK(Contains(message, "BSphere") && Contains(message, "phase3.4_baker-position"));
    BakingParameters::set({{position.at("Normalization"), EnumLabel{"None"}},
                           {position.at("Mode"), EnumLabel{"One axis"}},
                           {position.at("Axis"), EnumLabel{"Z"}},
                           {position.at("NormalizationScale"), EnumLabel{"Per Material"}}});
    mapped = RequestFromParameters(params, base);
    CHECK(mapped.request.position.mode == PositionMode::OneAxis && mapped.request.position.axis == PositionAxis::Z);
    CHECK(mapped.request.position.scale == PositionNormalizationScale::PerMaterial);
    BakeRequest expected = PositionBevelRequest(fixture);
    expected.position = mapped.request.position;
    CHECK(SerializeResult(Bake(baker, mapped.request)) == SerializeResult(Bake(baker, expected)));
    // Saved and loaded with the texture set's other values; a wrong label refuses the whole load.
    const uzp::core::BakeSettings saved = ToBakeSettings(params);
    CHECK(saved.per_baker.at("Position").at("Axis") == uzp::core::json::Value("Z"));
    BakingParameters loaded("bevelled_cube");
    LoadBakeSettings(loaded, saved);
    CHECK(ToBakeSettings(loaded) == saved);
    uzp::core::BakeSettings wrong = saved;
    wrong.per_baker["Position"]["Axis"] = uzp::core::json::Value("W");
    ExpectThrow<ValueError>([&] { LoadBakeSettings(loaded, wrong); });
    CHECK(ToBakeSettings(loaded) == saved);
    // Position values are the set's own: no link group (owner task), and ID still stores nothing.
    BakingSession session({"a", "b"});
    message = ExpectThrow<NotYetSupported>([&] { session.set_linked_group({"a", "b"}, "a", MeshMapUsage::Position); });
    CHECK(Contains(message, "phase3.4_baker-position"));
    BakingParameters::set({{session.parameters("a").baker(MeshMapUsage::Position).at("Axis"), EnumLabel{"Y"}}});
    CHECK(std::get<EnumLabel>(session.parameters("b").baker(MeshMapUsage::Position).at("Axis").value()).label == "X");
    CHECK(StoresBakerValues(MeshMapUsage::Position) && !StoresBakerValues(MeshMapUsage::Curvature));
}
