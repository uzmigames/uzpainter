// Opacity cases (phase3.4_baker-opacity, decision 341). Included inside the native driver's
// namespace after the ID cases; they use `BevelHit` and the fixtures. Expected values are analytic:
// which texels' primary rays meet an authored high surface front-on.

BakeRequest OpacityRequest(BakeRequest request) {
    request.usages = {MeshMapUsage::Opacity};
    return request;
}

/// The opacity map is 1 exactly on hit texels and 0 everywhere else: nothing is filled.
void CheckOpacityIsCoverage(const BakeResult& r) {
    CHECK_EQ(r.opacity.size(), std::size_t(r.width) * r.height);
    std::uint64_t opaque = 0;
    for (std::size_t i = 0; i < r.opacity.size(); ++i) {
        CHECK(r.opacity[i] == (IsHit(r.texel_class[i]) ? 1.0f : 0.0f));
        if (r.opacity[i] == 1.0f) ++opaque;
    }
    CHECK_EQ(opaque, r.texels.straight_hit + r.texels.cage_hit);
}

void CaseOpacityPlane() {
    // The low plane [-1, 1]^2 under a high plane over x in [-2, 0] only: the left half of the
    // covered texels is opaque, the right half misses (0, centre-miss class); a full high plane
    // makes every covered texel opaque.
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    const BakeMesh half = fixtures::Plane("half", -2, 0, -2, 2, 0.005f);
    BakeRequest request = PlaneRequest(low);
    request.detail.low_as_high = false;
    request.detail.max_height = request.detail.max_depth = 0.05f;
    request.high = {&half};
    const BakeResult r = Bake(baker, OpacityRequest(request));
    CheckConservation(r);
    CheckOpacityIsCoverage(r);
    CHECK_EQ(r.texels.straight_hit, kCovered / 2);
    CHECK_EQ(r.texels.centre_miss, kCovered / 2);
    for (std::size_t i = 0; i < kTexels; ++i) {
        const double x = 4.0 * ((i % 64 + 0.5) / 64.0) - 2.0;
        CHECK(r.opacity[i] == (UnderPlaneUv(i) && x < 0.0 ? 1.0f : 0.0f));
    }
    CHECK(r.ao.empty() && r.world_normal.empty() && r.position.empty() && r.id_labels.empty());
    CHECK_EQ(r.rays.escaped + r.rays.front_hit + r.rays.back_face_hit + r.rays.self_hit, 0u);
    const BakeMesh full = NormalHigh({0, 0, 1});
    request.high = {&full};
    const BakeResult f = Bake(baker, OpacityRequest(request));
    CheckOpacityIsCoverage(f);
    CHECK_EQ(f.texels.straight_hit, kCovered);
}

void CaseOpacitySphere() {
    // The sphere on the ground low as high: opaque on every straight hit; the back-face hits where
    // the sphere meets the ground stay 0.
    EmbreeBaker baker;
    const BakeMesh low = fixtures::SphereOnGround();
    const BakeResult r = Bake(baker, OpacityRequest(SphereRequest(low, 7)));
    CheckConservation(r);
    CheckOpacityIsCoverage(r);
    CHECK(r.texels.straight_hit > 0 && r.texels.back_face_hit > 0);
}

void CaseOpacityBevel() {
    // The bevelled cube with highs matched by name: opaque exactly where the analytic primary ray
    // meets the chamfered cube or the knob; at max_depth 0.04 the deeper chamfer bands miss.
    EmbreeBaker baker;
    Bevel fixture;
    for (float depth : {0.04f, 0.07f}) {
        const BakeResult r = Bake(baker, OpacityRequest(fixture.Request(depth)));
        CheckConservation(r);
        CheckOpacityIsCoverage(r);
        std::uint64_t opaque = 0;
        for (std::uint32_t y = 0; y < kAtlasH; ++y) {
            for (std::uint32_t x = 0; x < kAtlasW; ++x) {
                Vec3d point, normal;
                std::uint32_t mesh = 0;
                const bool hit = BevelHit(x, y, depth, point, normal, mesh);
                CHECK(r.opacity[std::size_t(y) * kAtlasW + x] == (hit ? 1.0f : 0.0f));
                if (hit) ++opaque;
            }
        }
        CHECK_EQ(opaque, r.texels.straight_hit);
        if (depth == 0.04f) CHECK_EQ(r.texels.centre_miss, 6 * 96u);
    }
}

void CaseOpacityThreadsInProcess() {
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest request = OpacityRequest(fixture.Request(0.07f));
    std::string reference;
    for (std::uint32_t threads : {1u, 4u, std::max(1u, std::thread::hardware_concurrency())}) {
        request.threads = threads;
        const std::string bytes = SerializeResult(Bake(baker, request));
        if (reference.empty()) reference = bytes;
        CHECK(bytes == reference);
    }
}

void CaseOpacityIsolation() {
    // With AO it shares the primary hits and leaves AO's bytes alone; an AO result has no OPA1 block.
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest both = fixture.Request(0.07f);
    both.usages = {MeshMapUsage::AO, MeshMapUsage::Opacity};
    const BakeResult a = Bake(baker, fixture.Request(0.07f));
    const BakeResult b = Bake(baker, both);
    const BakeResult o = Bake(baker, OpacityRequest(fixture.Request(0.07f)));
    CHECK(b.ao_raw == a.ao_raw && b.ao == a.ao && b.texel_class == a.texel_class && b.opacity == o.opacity);
    CHECK(a.opacity.empty() && SerializeResult(a).find("OPA1") == std::string::npos);
    CHECK(SerializeResult(o).find("OPA1") != std::string::npos);
}

void CaseOpacityRefusals() {
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest request = OpacityRequest(fixture.Request(0.07f));
    request.detail.subsampling = 2;
    std::string message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    CHECK(Contains(message, "SubSampling") && Contains(message, "phase3.4_baker-opacity"));
    request = OpacityRequest(fixture.Request(0.07f));
    request.common.dilation_width = 4;
    message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    CHECK(Contains(message, "DilationWidth") && Contains(message, "phase3.4_baker-opacity"));
    CHECK(baker.caps().parity_owner_tasks.at(MeshMapUsage::Opacity) == "phase3.4_baker-opacity");
    // Opacity has no parameters of its own, so nothing is stored for it.
    BakingParameters params("bevelled_cube");
    CHECK(params.baker(MeshMapUsage::Opacity).empty());
}
