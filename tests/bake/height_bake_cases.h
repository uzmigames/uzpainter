// Height cases (phase3.4_baker-height, decision 341). Included inside the native driver's namespace
// after the Opacity cases; they use `BevelHit`, `ChamferDepth` and the fixtures. Expected values are
// analytic: the authored plane heights, the offset of an inflated sphere and the chamfer depth of
// the bevelled cube.

/// `request` baking Height alone, as the evidence request: the signed distance, no normalisation.
BakeRequest HeightRequest(BakeRequest request) {
    request.usages = {MeshMapUsage::Height};
    request.height.normalization = std::nullopt;
    return request;
}

/// Hit texels hold the expected signed distance in centimetres; every other texel holds 0.
void CheckHeightAt(const BakeResult& r, std::size_t texel, double expected_cm, double tolerance = 1e-6) {
    CHECK(IsHit(r.texel_class[texel]));
    CHECK(Near(r.height_map[texel], expected_cm, tolerance));
}

void CaseHeightPlane() {
    // The low plane [-1, 1]^2 at z = 0 under a high plane split at x = 0: z = +0.005 on the left,
    // z = -0.003 on the right, in mesh units of 2.54 cm; the distances are given in centimetres.
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    const BakeMesh left = fixtures::Plane("left", -2, 0, -2, 2, 0.005f);
    const BakeMesh right = fixtures::Plane("right", 0, 2, -2, 2, -0.003f);
    BakeRequest request = PlaneRequest(low);
    request.detail.low_as_high = false;
    request.scale_to_internal = 2.54;
    request.detail.max_height = request.detail.max_depth = 0.05f * 2.54f;
    request.high = {&left, &right};
    const BakeResult r = Bake(baker, HeightRequest(request));
    CheckConservation(r);
    CheckZeroOffHits(r, r.height_map, 1);
    CHECK_EQ(r.texels.straight_hit, kCovered);
    std::uint64_t above = 0, below = 0;
    for (std::size_t i = 0; i < kTexels; ++i) {
        if (!UnderPlaneUv(i)) continue;
        const double x = 4.0 * ((i % 64 + 0.5) / 64.0) - 2.0;
        CheckHeightAt(r, i, (x < 0.0 ? 0.005 : -0.003) * 2.54);
        ++(x < 0.0 ? above : below);
    }
    CHECK_EQ(above, kCovered / 2);
    CHECK_EQ(below, kCovered / 2);
    CHECK(r.ao.empty() && r.opacity.empty() && r.position.empty());
    CHECK_EQ(r.rays.escaped + r.rays.front_hit + r.rays.back_face_hit + r.rays.self_hit, 0u);
    // A custom cage 0.05 above the low plane measures along the cage ray: the same signed distances.
    const BakeMesh cage = fixtures::Plane("cage", -1, 1, -1, 1, 0.05f);
    BakeRequest caged = HeightRequest(request);
    caged.detail.cage_mode = CageMode::CustomFile;
    caged.cage = {&cage};
    const BakeResult c = Bake(baker, caged);
    CheckConservation(c);
    CHECK_EQ(c.texels.cage_hit, kCovered);
    for (std::size_t i = 0; i < kTexels; ++i) {
        if (!UnderPlaneUv(i)) continue;
        const double x = 4.0 * ((i % 64 + 0.5) / 64.0) - 2.0;
        CheckHeightAt(c, i, (x < 0.0 ? 0.005 : -0.003) * 2.54);
    }
}

void CaseHeightSphere() {
    // Low as high, the low surface is its own high: every hit is at distance 0. Against the
    // sphere on the ground inflated by d along its vertex normals, the ground is d above wherever
    // the sphere is not in the way. The sphere's facets are scaled about its centre: the facet
    // planes lie d * cos(a) further out, a below the 5.3-degree half diagonal of a facet, and the
    // interpolated normal is within that angle of its facet's, so a hit lies between d * cos(6 deg)
    // and d / cos(6 deg).
    EmbreeBaker baker;
    const BakeMesh low = fixtures::SphereOnGround();
    const BakeResult self = Bake(baker, HeightRequest(SphereRequest(low, 7)));
    CheckConservation(self);
    CheckZeroOffHits(self, self.height_map, 1);
    for (std::size_t i = 0; i < self.height_map.size(); ++i) {
        if (IsHit(self.texel_class[i])) CHECK(std::abs(self.height_map[i]) <= 1e-6);
    }
    const double d = 0.01;
    BakeMesh high = low;
    high.name = "sphere_high";
    for (std::size_t v = 0; v < high.positions.size(); ++v) {
        const Float3 n = high.normals[v];
        high.positions[v] = {static_cast<float>(high.positions[v].x + d * n.x),
                             static_cast<float>(high.positions[v].y + d * n.y),
                             static_cast<float>(high.positions[v].z + d * n.z)};
    }
    BakeRequest request = HeightRequest(SphereRequest(low, 7));
    request.detail.low_as_high = false;
    request.detail.max_height = request.detail.max_depth = 0.05f;
    request.high = {&high};
    const BakeResult r = Bake(baker, request);
    CheckConservation(r);
    CheckZeroOffHits(r, r.height_map, 1);
    std::uint64_t ground = 0, sphere = 0;
    for (std::size_t i = 0; i < r.height_map.size(); ++i) {
        if (!IsHit(r.texel_class[i])) continue;
        const double u = (i % r.width + 0.5) / r.width;
        const double v = 1.0 - (i / r.width + 0.5) / r.height;
        if (u < 0.5) {
            const double x = -2.0 + 4.0 * (u - 0.01) / 0.48, y = -2.0 + 4.0 * (v - 0.01) / 0.98;
            if (x * x + y * y < 0.6 * 0.6) continue;  // under the sphere's inflated foot
            CheckHeightAt(r, i, d);
            ++ground;
            continue;
        }
        CHECK(r.height_map[i] >= d * std::cos(6.0 * std::numbers::pi / 180) - 1e-6);
        CHECK(r.height_map[i] <= d / std::cos(6.0 * std::numbers::pi / 180) + 1e-6);
        ++sphere;
    }
    CHECK(ground > 0 && sphere > 0);
}

void CaseHeightBevel() {
    // The bevelled cube with highs matched by name: the chamfered cube lies ChamferDepth below each
    // low face (negative), the knob's surface on its low plane (zero).
    EmbreeBaker baker;
    Bevel fixture;
    const BakeResult r = Bake(baker, HeightRequest(fixture.Request(0.07f)));
    CheckConservation(r);
    CheckZeroOffHits(r, r.height_map, 1);
    std::uint64_t hits = 0, chamfer = 0;
    for (std::uint32_t y = 0; y < kAtlasH; ++y) {
        for (std::uint32_t x = 0; x < kAtlasW; ++x) {
            Vec3d point, normal;
            std::uint32_t mesh = 0;
            if (!BevelHit(x, y, 0.07, point, normal, mesh)) continue;
            double expected = 0.0;
            for (std::uint32_t f = 0; f < 6 && mesh == 0; ++f) {
                if (!InIsland(f, x, y)) continue;
                double s = 0, t = 0;
                IslandCoords(f, x, y, 1, 0, 0, s, t);
                expected = -ChamferDepth(s, t);
            }
            CheckHeightAt(r, std::size_t(y) * kAtlasW + x, expected, 1e-5);
            if (expected < 0.0) ++chamfer;
            ++hits;
        }
    }
    CHECK_EQ(hits, r.texels.straight_hit);
    CHECK(chamfer > 0);
}

void CaseHeightThreadsInProcess() {
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest request = HeightRequest(fixture.Request(0.07f));
    std::string reference;
    for (std::uint32_t threads : {1u, 4u, std::max(1u, std::thread::hardware_concurrency())}) {
        request.threads = threads;
        const std::string bytes = SerializeResult(Bake(baker, request));
        if (reference.empty()) reference = bytes;
        CHECK(bytes == reference);
    }
}

void CaseHeightRecord() {
    // What was applied is recorded, and its JSON is the binding's effective_normalization.
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest request = HeightRequest(fixture.Request(0.07f));
    request.scale_to_internal = 0.5;
    request.detail.max_height = 0.05f * 0.5f;  // centimetres
    request.detail.max_depth = 0.07f * 0.5f;
    request.height.divisor = 4.0f;
    const BakeResult r = Bake(baker, request);
    const HeightNormalizationRecord& record = r.height_normalization;
    CHECK(!record.settings.normalization && record.settings.divisor == 4.0f);
    CHECK(record.scale_to_internal == 0.5 && !record.normalization_applied && !record.divisor_applied);
    using uzp::core::json::Value;
    const uzp::core::json::Object json = HeightNormalizationJson(record);
    CHECK(json.at("MaximizeRange").IsNull() && json.at("Divisor") == Value(4.0));
    CHECK(json.at("unit") == Value("centimetre") && json.at("scale_to_internal") == Value(0.5));
    CHECK(json.at("range").IsNull() && json.at("divisor_applied") == Value(false));
    CHECK(json.at("signed") == Value(true));
    // The divisor is not applied: the map equals the default divisor's, in centimetres.
    request.height.divisor = 1.0f;
    CHECK(Bake(baker, request).height_map == r.height_map);
    for (std::uint32_t y = 0; y < kAtlasH; ++y) {
        for (std::uint32_t x = 0; x < kAtlasW; ++x) {
            double s = 0, t = 0;
            Vec3d point, normal;
            std::uint32_t mesh = 0;
            if (!InIsland(0, x, y) || !BevelHit(x, y, 0.07, point, normal, mesh)) continue;
            IslandCoords(0, x, y, 1, 0, 0, s, t);
            CheckHeightAt(r, std::size_t(y) * kAtlasW + x, -ChamferDepth(s, t) * 0.5, 1e-5);
        }
    }
    // Combined with AO it shares the primary hits and leaves AO's bytes alone.
    BakeRequest both = fixture.Request(0.07f);
    both.usages = {MeshMapUsage::AO, MeshMapUsage::Height};
    both.height.normalization = std::nullopt;
    const BakeResult a = Bake(baker, fixture.Request(0.07f));
    const BakeResult b = Bake(baker, both);
    CHECK(b.ao_raw == a.ao_raw && b.ao == a.ao && b.texel_class == a.texel_class);
    CHECK(b.height_map == Bake(baker, HeightRequest(fixture.Request(0.07f))).height_map);
    CHECK(SerializeResult(a).find("HGT1") == std::string::npos && SerializeResult(b).find("HGT1") != std::string::npos);
}

void CaseHeightRefusals() {
    EmbreeBaker baker;
    Bevel fixture;
    for (HeightNormalization normalization :
         {HeightNormalization::RelativeToRayDistances, HeightNormalization::RelativeToLowMesh,
          HeightNormalization::RelativeToMinMax, HeightNormalization::Manual}) {
        BakeRequest request = HeightRequest(fixture.Request(0.07f));
        request.height.normalization = normalization;
        const std::string message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
        CHECK(Contains(message, "MaximizeRange") && Contains(message, "phase3.4_baker-height") &&
              Contains(message, "decision 341"));
    }
    BakeRequest defaults = fixture.Request(0.07f);  // Painter's defaults: Relative to low mesh
    defaults.usages = {MeshMapUsage::Height};
    std::string message = ExpectThrow<NotYetSupported>([&] { baker.bake(defaults); });
    CHECK(Contains(message, "Relative to low mesh (per UV tile)"));
    BakeRequest request = HeightRequest(fixture.Request(0.07f));
    request.detail.subsampling = 2;
    message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    CHECK(Contains(message, "SubSampling") && Contains(message, "phase3.4_baker-height"));
    request = HeightRequest(fixture.Request(0.07f));
    request.common.dilation_width = 2;
    message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    CHECK(Contains(message, "DilationWidth") && Contains(message, "phase3.4_baker-height"));
    request = HeightRequest(fixture.Request(0.07f));
    request.height.divisor = 0.0f;
    ExpectThrow<ValueError>([&] { baker.bake(request); });
    CHECK(baker.caps().parity_owner_tasks.at(MeshMapUsage::Height) == "phase3.4_baker-height");
}

void CaseHeightParameters() {
    // Height's values are stored per texture set, saved in bake_settings.per_baker.Height and mapped
    // to the request; the baker refuses every normalisation the mapping always sets.
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest base = ParameterDistanceUnits(HeightRequest(fixture.Request(0.07f)));
    base.height = HeightSettings{};
    BakingParameters params("bevelled_cube");
    const auto common = params.common();
    const auto height = params.baker(MeshMapUsage::Height);
    CHECK(std::get<EnumLabel>(height.at("MaximizeRange").value()).label == "Relative to low mesh (per UV tile)");
    CHECK(std::get<double>(height.at("Divisor").value()) == 1.0);
    using Pair = std::pair<std::int64_t, std::int64_t>;
    BakingParameters::set({{common.at("OutputSize"), Pair{base.output_size_log2[0], base.output_size_log2[1]}},
                           {common.at("DilationWidth"), std::int64_t{0}},
                           {common.at("FilterMethod"), EnumLabel{"By mesh name"}},
                           {common.at("MaxHeight"), static_cast<double>(base.detail.max_height)},
                           {common.at("MaxDepth"), static_cast<double>(base.detail.max_depth)},
                           {common.at("RelativeScale"), false}});
    MappedRequest mapped = RequestFromParameters(params, base);
    CHECK(mapped.request.height.normalization == HeightNormalization::RelativeToLowMesh);
    std::string message = ExpectThrow<NotYetSupported>([&] { baker.bake(mapped.request); });
    CHECK(Contains(message, "phase3.4_baker-height"));
    const std::vector<std::pair<std::string, HeightNormalization>> labels = {
        {"Relative to ray distances", HeightNormalization::RelativeToRayDistances},
        {"Relative to min/max (per UV tile)", HeightNormalization::RelativeToMinMax},
        {"Manual", HeightNormalization::Manual}};
    for (const auto& [text, expected] : labels) {
        BakingParameters::set({{height.at("MaximizeRange"), EnumLabel{text}}, {height.at("Divisor"), 2.5}});
        mapped = RequestFromParameters(params, base);
        CHECK(mapped.request.height.normalization == expected && mapped.request.height.divisor == 2.5f);
        ExpectThrow<NotYetSupported>([&] { baker.bake(mapped.request); });
    }
    // The mapped request without its normalisation is the evidence request.
    mapped.request.height.normalization = std::nullopt;
    BakeRequest expected = ParameterDistanceUnits(HeightRequest(fixture.Request(0.07f)));
    expected.height.divisor = 2.5f;
    CHECK(SerializeResult(Bake(baker, mapped.request)) == SerializeResult(Bake(baker, expected)));
    // Saved and loaded with the texture set's other values; a wrong label refuses the whole load.
    const uzp::core::BakeSettings saved = ToBakeSettings(params);
    CHECK(saved.per_baker.at("Height").at("MaximizeRange") == uzp::core::json::Value("Manual"));
    CHECK(saved.per_baker.at("Height").at("Divisor") == uzp::core::json::Value(2.5));
    BakingParameters loaded("bevelled_cube");
    LoadBakeSettings(loaded, saved);
    CHECK(ToBakeSettings(loaded) == saved);
    uzp::core::BakeSettings wrong = saved;
    wrong.per_baker["Height"]["MaximizeRange"] = uzp::core::json::Value("Automatic");
    ExpectThrow<ValueError>([&] { LoadBakeSettings(loaded, wrong); });
    CHECK(ToBakeSettings(loaded) == saved);
    // Out of range is refused like every key (decision 323).
    ExpectThrow<NotYetSupported>([&] { BakingParameters::set({{height.at("Divisor"), 1000.0}}); });
    // Height values are the set's own: no link group (owner task).
    BakingSession session({"a", "b"});
    message = ExpectThrow<NotYetSupported>([&] { session.set_linked_group({"a", "b"}, "a", MeshMapUsage::Height); });
    CHECK(Contains(message, "phase3.4_baker-height"));
    BakingParameters::set({{session.parameters("a").baker(MeshMapUsage::Height).at("Divisor"), 3.0}});
    CHECK(std::get<double>(session.parameters("b").baker(MeshMapUsage::Height).at("Divisor").value()) == 1.0);
    CHECK(StoresBakerValues(MeshMapUsage::Height) && !StoresBakerValues(MeshMapUsage::Curvature));
}
