// Included inside the native driver's namespace, after its common bake/check helpers.
// Analytic expectations use authored frames and constants, never ToTangentSpace.

BakeMesh NormalTriangle(bool curved = true) {
    BakeMesh mesh;
    mesh.name = "normal_low";
    mesh.positions = {{0, 0, 0}, {1, 0, 0}, {0, 1, 0}};
    mesh.uvs = {{0, 0}, {1, 0}, {0, 1}};
    mesh.normals = curved ? std::vector<Float3>{{0, 0, 1}, {0.6f, 0, 0.8f}, {0, 0.6f, 0.8f}}
                          : std::vector<Float3>(3, Float3{0, 0, 1});
    mesh.indices = {0, 1, 2};
    return mesh;
}

BakeMesh NormalHigh(Float3 normal) {
    BakeMesh high = fixtures::Plane("normal_high", -2, 2, -2, 2, 0.005f);
    const double length = std::sqrt(double(normal.x) * normal.x + double(normal.y) * normal.y + double(normal.z) * normal.z);
    normal = {float(normal.x / length), float(normal.y / length), float(normal.z / length)};
    high.normals.assign(high.positions.size(), normal);
    return high;
}

BakeRequest NormalRequest(const BakeMesh& low, const BakeMesh& high) {
    BakeRequest request = PlaneRequest(low);
    request.usages = {MeshMapUsage::Normal};
    request.detail.low_as_high = false;
    request.detail.max_height = request.detail.max_depth = 0.05f;
    request.high = {&high};
    return request;
}

std::uint16_t NormalCode(double value) {
    return static_cast<std::uint16_t>(std::floor(std::clamp(value * 0.5 + 0.5, 0.0, 1.0) * 65535.0 + 0.5));
}

void CheckNormalAt(const BakeResult& result, std::size_t pixel, std::array<double, 3> expected, int tolerance = 1) {
    CHECK(IsHit(result.texel_class[pixel]));
    CHECK_EQ(result.normal_raw.size(), std::size_t(result.width) * result.height * 3);
    for (std::size_t c = 0; c < 3; ++c) {
        CHECK(std::abs(int(result.normal_raw[3 * pixel + c]) - int(NormalCode(expected[c]))) <= tolerance);
    }
}

void CaseNormalPlane() {
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    for (Float3 expected : {Float3{0, 0, 1}, Float3{0.6f, 0, 0.8f}, Float3{0, 0.6f, 0.8f}}) {
        const BakeMesh high = NormalHigh(expected);
        const BakeResult result = Bake(baker, NormalRequest(low, high));
        CheckConservation(result);
        CHECK_EQ(result.texels.straight_hit, kCovered);
        CHECK(result.ao.empty() && result.ao_raw.empty());
        CHECK_EQ(result.rays_per_texel, 0u);
        for (std::size_t i = 0; i < kTexels; ++i) {
            if (UnderPlaneUv(i)) CheckNormalAt(result, i, {expected.x, expected.y, expected.z});
        }
    }
}

void CaseNormalCurvedModes() {
    EmbreeBaker baker;
    BakeMesh low = NormalTriangle();
    const BakeMesh high = NormalHigh({3, -2, 9});
    BakeRequest request = NormalRequest(low, high);
    request.output_size_log2[0] = request.output_size_log2[1] = 2;
    const BakeResult implicit = Bake(baker, request);
    request.normal.tangent_space = uzp::core::TangentSpace::PerVertex;
    const BakeResult vertex = Bake(baker, request);
    CHECK(SerializeResult(implicit) == SerializeResult(vertex));
    // At pixel (1,2), w=(1/4,3/8,3/8). Solve [T B N] v = normalize(3,-2,9).
    CheckNormalAt(vertex, 9, {0.08431174209781525, -0.4221293483374539, 0.9026064166715346});
    request.normal.tangent_space = uzp::core::TangentSpace::PerFragment;
    const BakeResult fragment = Bake(baker, request);
    CheckNormalAt(fragment, 9, {0.060301275595138155, -0.45994902396910253, 0.8858953953551565});
    CHECK(vertex.normal != fragment.normal);
    // Explicit independently authored per-corner frames must reproduce the generated Mikk frames.
    low.corner_tangents = {{{1, 0, 0, 1}}, {{0.8f, 0, -0.6f, 1}}, {{1, 0, 0, 1}}};
    const BakeResult supplied = Bake(baker, request);
    CheckNormalAt(supplied, 9, {0.060301275595138155, -0.45994902396910253, 0.8858953953551565});
}

void CaseNormalMirrored() {
    EmbreeBaker baker;
    const BakeMesh plain = fixtures::Plane("low", -1, 1, -1, 1, 0);
    BakeMesh mirrored = plain;
    for (auto& uv : mirrored.uvs) uv.x = 1.0f - uv.x;
    const BakeMesh high = NormalHigh({3, 2, 9});
    const double length = std::sqrt(94.0);
    for (auto mode : {uzp::core::TangentSpace::PerVertex, uzp::core::TangentSpace::PerFragment}) {
        BakeRequest request = NormalRequest(mirrored, high);
        request.normal.tangent_space = mode;
        const BakeResult result = Bake(baker, request);
        CheckConservation(result);
        for (std::size_t i = 0; i < kTexels; ++i) {
            if (UnderPlaneUv(i)) CheckNormalAt(result, i, {-3 / length, 2 / length, 9 / length});
        }
    }
}

void CaseNormalDirectX() {
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    for (Float3 normal : {Float3{0, 0, 1}, Float3{0, 0.6f, 0.8f}}) {
        const BakeMesh high = NormalHigh(normal);
        BakeRequest request = NormalRequest(low, high);
        const BakeResult gl = Bake(baker, request);
        request.normal.format = uzp::core::NormalMapFormat::DirectX;
        const BakeResult dx = Bake(baker, request);
        CHECK(gl.texel_class == dx.texel_class);
        if (normal.y == 0) {
            CHECK_EQ(gl.normal_raw[3 * (32 * 64 + 32) + 1], 32768);
            CHECK_EQ(dx.normal_raw[3 * (32 * 64 + 32) + 1], 32767);
        }
        for (std::size_t i = 0; i < kTexels; ++i) {
            CHECK_EQ(gl.normal_raw[3 * i], dx.normal_raw[3 * i]);
            CHECK_EQ(gl.normal_raw[3 * i + 2], dx.normal_raw[3 * i + 2]);
            CHECK_EQ(dx.normal_raw[3 * i + 1], IsHit(gl.texel_class[i]) ? 65535 - gl.normal_raw[3 * i + 1] : 0);
        }
    }
}

void CaseNormalNegativeZ() {
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    // Geometry still faces +Z; authored shading normals face below the tangent plane.
    const BakeMesh high = NormalHigh({0.6f, 0, -0.8f});
    const BakeResult result = Bake(baker, NormalRequest(low, high));
    std::size_t negative = 0;
    for (std::size_t i = 0; i < kTexels; ++i) {
        if (!IsHit(result.texel_class[i])) continue;
        CheckNormalAt(result, i, {0.6, 0, -0.8});
        negative += result.normal_raw[3 * i + 2] < 32768;
    }
    CHECK_EQ(negative, kCovered);
    CHECK(result.normal == result.normal_raw);
}

void CaseNormalHighInterpolation() {
    EmbreeBaker baker;
    const BakeMesh low = NormalTriangle(false);
    BakeMesh high = NormalTriangle();
    high.name = "high";
    for (auto& p : high.positions) p.z = 0.005f;
    BakeRequest request = NormalRequest(low, high);
    request.output_size_log2[0] = request.output_size_log2[1] = 2;
    const BakeResult result = Bake(baker, request);
    const double length = std::sqrt(0.225 * 0.225 * 2 + 0.85 * 0.85);
    CheckNormalAt(result, 9, {0.225 / length, 0.225 / length, 0.85 / length});
}

void CaseNormalHitClasses() {
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    BakeMesh high = NormalHigh({0, 0, 1});
    BakeRequest request = NormalRequest(low, high);
    request.hidden_mask.assign(kTexels, 1);
    BakeResult result = Bake(baker, request);
    CheckConservation(result);
    CHECK_EQ(result.texels.hidden, kCovered);
    request.hidden_mask.clear();
    for (auto& p : high.positions) p.z = 10;
    result = Bake(baker, request);
    CheckConservation(result);
    CHECK_EQ(result.texels.centre_miss, kCovered);
    high = fixtures::Plane("high", -2, 2, -2, 2, 0.005f, true);
    result = Bake(baker, request);
    CheckConservation(result);
    CHECK_EQ(result.texels.back_face_hit, kCovered);
    request.detail.ignore_backface = true;
    result = Bake(baker, request);
    CheckConservation(result);
    CHECK_EQ(result.texels.centre_miss, kCovered);
    high = NormalHigh({0, 0, 1});
    BakeMesh cage = low;
    for (auto& p : cage.positions) p.z = 0.02f;
    request.detail.cage_mode = CageMode::CustomFile;
    request.cage = {&cage};
    result = Bake(baker, request);
    CheckConservation(result);
    CHECK_EQ(result.texels.cage_hit, kCovered);
    CheckNormalAt(result, 32 * 64 + 32, {0, 0, 1});
}

void CaseNormalSingularFailure() {
    EmbreeBaker baker;
    BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    low.corner_tangents.assign(low.indices.size(), {0, 0, 1, 1});
    const BakeMesh high = NormalHigh({0, 0, 1});
    JobHandle job = baker.bake(NormalRequest(low, high));
    CHECK(job.wait() == JobStatus::Fail);
    CHECK(!job.error_message().empty());
    ExpectThrow<ValueError>([&] { (void)job.result(); });
    CHECK_EQ(baker.live_embree_objects(), 0);
}

void CaseNormalUsageIsolation() {
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    const BakeMesh high = NormalHigh({0, 0, 1});
    BakeRequest request = NormalRequest(low, high);
    const BakeResult normal = Bake(baker, request);
    request.ao.secondary_rays = 0;
    request.ao.min_distance = std::numeric_limits<float>::quiet_NaN();
    request.ao.max_distance = -1;
    request.ao.relative_to_bounding_box = true;
    CHECK(SerializeResult(Bake(baker, request)) == SerializeResult(normal));
    request = NormalRequest(low, high);
    request.usages = {MeshMapUsage::AO};
    const BakeResult ao = Bake(baker, request);
    CHECK(ao.normal.empty() && ao.normal_raw.empty());
    CHECK(SerializeResult(ao).starts_with("UZPBAKE3"));
    request.usages.push_back(MeshMapUsage::Normal);
    const BakeResult mixed = Bake(baker, request);
    CheckConservation(mixed);
    CHECK(mixed.ao == ao.ao && mixed.ao_raw == ao.ao_raw);
    CHECK(mixed.normal == normal.normal && mixed.normal_raw == normal.normal_raw);
    CHECK(mixed.texel_class == ao.texel_class && mixed.coverage == ao.coverage);
    CHECK(mixed.back_face_rays == ao.back_face_rays && mixed.self_hit_rays == ao.self_hit_rays);
    CHECK(SerializeResult(mixed).starts_with("UZPBAKE4"));
}

void CaseNormalRefusals() {
    EmbreeBaker baker;
    BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    const BakeMesh high = NormalHigh({0, 0, 1});
    BakeRequest request = NormalRequest(low, high);
    request.detail.subsampling = 2;
    ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    request = NormalRequest(low, high);
    request.common.dilation_width = 1;
    ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    request = NormalRequest(low, high);
    low.normal_frame_supported = false;
    ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    low.normal_frame_supported = true;
    low.corner_tangents = {{{1, 0, 0, 1}}};
    ExpectThrow<ValueError>([&] { baker.bake(request); });
    for (const std::array<float, 4>& tangent : {
             std::array<float, 4>{std::numeric_limits<float>::quiet_NaN(), 0, 0, 1},
             std::array<float, 4>{1, 0, 0, 0}, std::array<float, 4>{0, 0, 0, 1}}) {
        low.corner_tangents.assign(low.indices.size(), tangent);
        ExpectThrow<ValueError>([&] { baker.bake(request); });
    }
    low.corner_tangents.clear();
    request.normal.tangent_space = static_cast<uzp::core::TangentSpace>(99);
    ExpectThrow<ValueError>([&] { baker.bake(request); });
    request.normal.tangent_space = uzp::core::TangentSpace::PerVertex;
    request.normal.format = static_cast<uzp::core::NormalMapFormat>(99);
    ExpectThrow<ValueError>([&] { baker.bake(request); });
}

void CaseNormalMaterialSplit() {
    const std::string obj =
        "o joined\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 0.7\nvn 0 0 1\n"
        "usemtl first\nf 1/1/1 2/2/1 3/3/1\n"
        "usemtl second\nf 1/1/1 3/3/1 4/4/1\n";
    const auto source = ReadBakeMeshFile(obj, "split.obj", {});
    auto framed = source;
    uzp::mesh::ComputeTangents(framed);
    auto first = LowParts(source, 0);
    auto second = LowParts(source, 1);
    CHECK_EQ(first.size(), 1u);
    CHECK_EQ(second.size(), 1u);
    for (std::size_t face = 0; face < 2; ++face) {
        const BakeMesh& part = face == 0 ? first[0] : second[0];
        CHECK_EQ(part.corner_tangents.size(), 3u);
        for (std::size_t corner = 0; corner < 3; ++corner) {
            const auto index = framed.objects[0].triangles[face].corners[corner];
            CHECK(part.corner_tangents[corner] == framed.corners[index].tangent);
        }
    }
    const auto retained = first[0].corner_tangents;
    {
        struct RestoreFp {
            unsigned int saved = _mm_getcsr();
            ~RestoreFp() { _mm_setcsr(saved); }
        } restore;
        // Down/up/toward-zero rounding, FTZ and DAZ must not affect generated frames.
        for (unsigned int rounding : {0x2000u, 0x4000u, 0x6000u}) {
            const unsigned int caller = 0x1F80u | rounding | 0x8040u;
            _mm_setcsr(caller);
            const auto altered = LowParts(source, 0);
            CHECK_EQ(_mm_getcsr(), caller);
            CHECK(altered[0].corner_tangents == retained);
        }
    }
    EnsureNormalTangents(first[0]);
    CHECK(first[0].corner_tangents == retained);
    first[0].corner_tangents.clear();
    EnsureNormalTangents(first[0]);
    CHECK(first[0].corner_tangents != retained);  // A split-only Mikk rebuild loses the shared edge.
    auto transformed = source;
    transformed.objects[0].transform[12] = 1;
    const auto moved = LowParts(transformed, 0);
    CHECK(!moved[0].normal_frame_supported);
}

void CaseNormalRetainedCorners() {
    EmbreeBaker baker;
    BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    CHECK_EQ(low.indices[0], low.indices[3]);  // Same indexed vertex, two distinct corner frames.
    low.corner_tangents = {{{1, 0, 0, 1}}, {{1, 0, 0, 1}}, {{1, 0, 0, 1}},
                           {{0, 1, 0, 1}}, {{0, 1, 0, 1}}, {{0, 1, 0, 1}}};
    const BakeMesh high = NormalHigh({0.6f, 0, 0.8f});
    const BakeResult result = Bake(baker, NormalRequest(low, high));
    CheckNormalAt(result, 40 * 64 + 40, {0.6, 0, 0.8});
    CheckNormalAt(result, 24 * 64 + 24, {0, -0.6, 0.8});
}
