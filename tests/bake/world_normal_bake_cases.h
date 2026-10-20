// WorldSpaceNormal cases (phase3.4_baker-world-space-normal, decision 337). Included inside the
// native driver's namespace after the normal cases: it uses their helpers and the bevelled-cube
// fixture. Expected values are analytic (authored normals, the chamfer's facet normals, the
// sphere's radial direction), never the baker's own code.

/// The analytic hit of the distance-based primary ray of texel (x, y) of the bevelled cube with
/// highs (`Bevel::Request(max_depth)`): false where the ray misses. `point` is the high surface
/// point, `normal` the high facet's unit normal, `mesh` the high mesh's index in the request.
bool BevelHit(std::uint32_t x, std::uint32_t y, double max_depth, Vec3d& point, Vec3d& normal, std::uint32_t& mesh) {
    double s = 0, t = 0;
    for (std::uint32_t f = 0; f < 6; ++f) {
        if (!InIsland(f, x, y)) continue;
        IslandCoords(f, x, y, 1, 0, 0, s, t);
        const double depth = ChamferDepth(s, t);
        if (!(depth <= max_depth)) return false;
        const fixtures::CubeFace& face = fixtures::kCubeFaces[f];
        const Vec3d a{face.a.x, face.a.y, face.a.z}, b{face.b.x, face.b.y, face.b.z}, d{face.d.x, face.d.y, face.d.z};
        const Vec3d n{face.n.x, face.n.y, face.n.z};
        const Vec3d sd{(b.x - a.x) / 2, (b.y - a.y) / 2, (b.z - a.z) / 2};
        const Vec3d td{(d.x - a.x) / 2, (d.y - a.y) / 2, (d.z - a.z) / 2};
        const Vec3d centre{a.x + sd.x + td.x, a.y + sd.y + td.y, a.z + sd.z + td.z};
        point = {centre.x + s * sd.x + t * td.x - depth * n.x, centre.y + s * sd.y + t * td.y - depth * n.y,
                 centre.z + s * sd.z + t * td.z - depth * n.z};
        // The face, a 45-degree edge chamfer or a corner triangle (decision 306's fixture).
        const double m = 1.0 - kBevel;
        const double ws = std::abs(s) > m ? (s > 0 ? 1.0 : -1.0) : 0.0;
        const double wt = std::abs(t) > m ? (t > 0 ? 1.0 : -1.0) : 0.0;
        normal = {n.x + ws * sd.x + wt * td.x, n.y + ws * sd.y + wt * td.y, n.z + ws * sd.z + wt * td.z};
        const double length = std::sqrt(normal.x * normal.x + normal.y * normal.y + normal.z * normal.z);
        normal = {normal.x / length, normal.y / length, normal.z / length};
        mesh = 0;  // cube_high
        return true;
    }
    if (!InIsland(6, x, y)) return false;
    IslandCoords(6, x, y, 1, 0, 0, s, t);
    point = {0.5 * s, 0.5 * t, 3.0};  // the knob surface under its pass-through cover
    normal = {0, 0, 1};
    mesh = 1;  // knob_high_ignorebf
    return true;
}

bool Near(double value, double expected, double tolerance) { return std::abs(value - expected) <= tolerance; }

void CheckWorldNormalAt(const BakeResult& r, std::size_t texel, const Vec3d& expected, double tolerance = 1e-6) {
    CHECK(IsHit(r.texel_class[texel]));
    CHECK(Near(r.world_normal[3 * texel], expected.x, tolerance));
    CHECK(Near(r.world_normal[3 * texel + 1], expected.y, tolerance));
    CHECK(Near(r.world_normal[3 * texel + 2], expected.z, tolerance));
}

/// Every non-hit texel holds zero in `map` (`channels` floats per texel): nothing is filled.
void CheckZeroOffHits(const BakeResult& r, const std::vector<float>& map, std::size_t channels) {
    CHECK_EQ(map.size(), std::size_t(r.width) * r.height * channels);
    for (std::size_t i = 0; i < std::size_t(r.width) * r.height; ++i) {
        if (IsHit(r.texel_class[i])) continue;
        for (std::size_t c = 0; c < channels; ++c) CHECK(map[channels * i + c] == 0.0f);
    }
}

BakeRequest WorldNormalBevelRequest(const Bevel& fixture) {
    BakeRequest request = fixture.Request(0.07f);
    request.usages = {MeshMapUsage::WorldSpaceNormal};
    return request;
}

void CaseWorldNormalPlane() {
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    for (Float3 authored : {Float3{0, 0, 1}, Float3{0.6f, 0, 0.8f}, Float3{3, -2, 9}}) {
        const BakeMesh high = NormalHigh(authored);
        BakeRequest request = NormalRequest(low, high);
        request.usages = {MeshMapUsage::WorldSpaceNormal};
        const BakeResult r = Bake(baker, request);
        CheckConservation(r);
        CHECK_EQ(r.texels.straight_hit, kCovered);
        CHECK(r.ao.empty() && r.normal_raw.empty() && r.rays_per_texel == 0);
        CheckZeroOffHits(r, r.world_normal, 3);
        const double length = std::sqrt(double(authored.x) * authored.x + double(authored.y) * authored.y +
                                         double(authored.z) * authored.z);
        const Vec3d expected{authored.x / length, authored.y / length, authored.z / length};
        for (std::size_t i = 0; i < kTexels; ++i) {
            if (UnderPlaneUv(i)) CheckWorldNormalAt(r, i, expected);
        }
    }
}

void CaseWorldNormalSphere() {
    // The sphere on the ground baked low as high: the ground's own normal, and on the sphere the
    // interpolated vertex normals, within the tessellation's angle of the radial direction.
    EmbreeBaker baker;
    const BakeMesh low = fixtures::SphereOnGround();
    BakeRequest request = SphereRequest(low, 7);
    request.usages = {MeshMapUsage::WorldSpaceNormal};
    const BakeResult r = Bake(baker, request);
    CheckConservation(r);
    CheckZeroOffHits(r, r.world_normal, 3);
    std::uint64_t ground = 0, sphere = 0;
    for (std::size_t i = 0; i < std::size_t(r.width) * r.height; ++i) {
        if (!IsHit(r.texel_class[i])) continue;
        const double u = (i % r.width + 0.5) / r.width;
        const double v = 1.0 - (i / r.width + 0.5) / r.height;
        const Vec3d n{r.world_normal[3 * i], r.world_normal[3 * i + 1], r.world_normal[3 * i + 2]};
        CHECK(Near(std::sqrt(n.x * n.x + n.y * n.y + n.z * n.z), 1.0, 1e-6));
        if (u < 0.5) {
            CheckWorldNormalAt(r, i, {0, 0, 1});
            ++ground;
            continue;
        }
        // Latitude and longitude of the UV point (the fixture's mapping) give the radial direction.
        const double theta = std::numbers::pi * (0.99 - v) / 0.98;
        const double phi = 2.0 * std::numbers::pi * (u - 0.51) / 0.48;
        const Vec3d radial{std::sin(theta) * std::cos(phi), std::sin(theta) * std::sin(phi), std::cos(theta)};
        CHECK(n.x * radial.x + n.y * radial.y + n.z * radial.z > std::cos(std::numbers::pi / 24));
        ++sphere;
    }
    CHECK(ground > 0 && sphere > 0);
    CHECK_EQ(ground + sphere, r.texels.straight_hit);
}

void CaseWorldNormalBevel() {
    EmbreeBaker baker;
    Bevel fixture;
    const BakeResult r = Bake(baker, WorldNormalBevelRequest(fixture));
    CheckConservation(r);
    CheckZeroOffHits(r, r.world_normal, 3);
    std::uint64_t hits = 0, chamfer = 0;
    for (std::uint32_t y = 0; y < kAtlasH; ++y) {
        for (std::uint32_t x = 0; x < kAtlasW; ++x) {
            const std::size_t i = std::size_t(y) * kAtlasW + x;
            Vec3d point, normal;
            std::uint32_t mesh = 0;
            if (!BevelHit(x, y, 0.07, point, normal, mesh)) {
                CHECK(!IsHit(r.texel_class[i]));
                continue;
            }
            CheckWorldNormalAt(r, i, normal);
            ++hits;
            if (std::abs(normal.x) != 1.0 && std::abs(normal.y) != 1.0 && std::abs(normal.z) != 1.0) ++chamfer;
        }
    }
    CHECK_EQ(hits, r.texels.straight_hit);
    CHECK(chamfer > 0);  // edge and corner facets are exercised, not only the faces
}

void CaseWorldNormalThreadsInProcess() {
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest request = WorldNormalBevelRequest(fixture);
    std::string reference;
    for (std::uint32_t threads : {1u, 4u, std::max(1u, std::thread::hardware_concurrency())}) {
        request.threads = threads;
        const std::string bytes = SerializeResult(Bake(baker, request));
        if (reference.empty()) reference = bytes;
        CHECK(bytes == reference);
    }
}

void CaseWorldNormalIsolation() {
    // Combined with AO it shares the primary hits and leaves AO's bytes alone; alone it casts no
    // secondary ray. An AO-only result carries no WSN block (its canonical bytes are unchanged).
    EmbreeBaker baker;
    Bevel fixture;
    const BakeRequest ao_only = fixture.Request(0.07f);
    BakeRequest both = ao_only;
    both.usages = {MeshMapUsage::AO, MeshMapUsage::WorldSpaceNormal};
    const BakeResult a = Bake(baker, ao_only);
    const BakeResult b = Bake(baker, both);
    const BakeResult w = Bake(baker, WorldNormalBevelRequest(fixture));
    CHECK(a.world_normal.empty());
    CHECK(SerializeResult(a).find("WSN1") == std::string::npos);
    CHECK(b.ao_raw == a.ao_raw && b.texel_class == a.texel_class);
    CHECK(b.world_normal == w.world_normal);
    CHECK_EQ(w.rays.escaped + w.rays.front_hit + w.rays.back_face_hit + w.rays.self_hit, 0u);
}

void CaseWorldNormalRefusals() {
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest request = WorldNormalBevelRequest(fixture);
    request.detail.subsampling = 2;
    std::string message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    CHECK(Contains(message, "SubSampling") && Contains(message, "phase3.4_baker-world-space-normal"));
    request = WorldNormalBevelRequest(fixture);
    request.common.dilation_width = 4;
    message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    CHECK(Contains(message, "DilationWidth") && Contains(message, "phase3.4_baker-world-space-normal"));
    CHECK(baker.caps().parity_owner_tasks.at(MeshMapUsage::WorldSpaceNormal) == "phase3.4_baker-world-space-normal");
    CHECK(baker.caps().parity_status == "pending-evidence");
}
