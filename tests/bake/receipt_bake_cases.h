// Evidence, accounting, receipt and publication cases (phase3.3_baker-evidence-publication items
// 2.1-2.4, 3.1 and 3.2; decision 347). Included inside the native driver's namespace after the
// Thickness cases. Every expected count is authored from the fixture's geometry: which texel
// centres and which open texel squares a UV rectangle reaches, and which primary rays meet an
// authored high surface front-on. Parity with Painter is not claimed.

namespace receipt_cases {

/// A UV range [lo, hi] in texels, at least 0.1 texel from any texel centre or boundary: the
/// texels whose centre lies in it and those whose open square overlaps it.
struct Span {
    double lo, hi;
    std::uint32_t centre_first() const { return static_cast<std::uint32_t>(std::ceil(lo - 0.5)); }
    std::uint32_t centre_last() const { return static_cast<std::uint32_t>(std::floor(hi - 0.5)); }
    std::uint32_t used_first() const { return static_cast<std::uint32_t>(std::floor(lo)); }
    std::uint32_t used_last() const { return static_cast<std::uint32_t>(std::ceil(hi)) - 1; }
    std::uint64_t centre() const { return centre_last() - centre_first() + 1; }
    std::uint64_t used() const { return used_last() - used_first() + 1; }
};

/// The off-boundary plane: [-1, 1]^2 at z = 0 facing up, on the UV square whose texel span is
/// [16.6, 47.3] on u and, from the top row, [16.7, 47.4] on v at 64 x 64: 30 x 30 texel centres,
/// 32 x 32 used texels, a ring of 124.
constexpr Span kPlaneU{16.6, 47.3};
constexpr Span kPlaneRows{16.7, 47.4};

BakeMesh OffsetPlane(std::string name, float z, Span u = kPlaneU) {
    return fixtures::Plane(std::move(name), -1, 1, -1, 1, z, false,
                           {static_cast<float>(u.lo / 64.0), static_cast<float>(16.6 / 64.0)},
                           {static_cast<float>(u.hi / 64.0), static_cast<float>(47.3 / 64.0)});
}

BakeRequest OffsetPlaneRequest(const BakeMesh& low, const BakeMesh& high, std::vector<MeshMapUsage> usages) {
    BakeRequest request = PlaneRequest(low);
    request.usages = std::move(usages);
    request.detail.low_as_high = false;
    request.detail.max_height = request.detail.max_depth = 0.05f;
    request.high = {&high};
    return request;
}

/// The expected accounting of one usage.
struct Expected {
    std::uint64_t centre = 0, used = 0;
    UsedSurfaceCounts classes;
    std::uint64_t fallback = 0, padding = 0, changed = 0;
    FidelityEvidence fidelity = FidelityEvidence::UsedSurfaceAsBaked;
};

void CheckAccount(const UsageAccount& a, const Expected& e) {
    CHECK_EQ(a.coverage.centre_texels, e.centre);
    CHECK_EQ(a.coverage.conservative_texels, e.used);
    const UsedSurfaceCounts& s = a.used_surface;
    CHECK_EQ(s.hit_straight, e.classes.hit_straight);
    CHECK_EQ(s.hit_cage, e.classes.hit_cage);
    CHECK_EQ(s.miss, e.classes.miss);
    CHECK_EQ(s.hidden, e.classes.hidden);
    CHECK_EQ(s.ring_extended, e.classes.ring_extended);
    CHECK_EQ(s.ring_no_hit_neighbour, e.classes.ring_no_hit_neighbour);
    CHECK_EQ(s.repaired, 0u);
    // The conservation identity: seven disjoint classes, summing to the used surface.
    CHECK_EQ(s.hit_straight + s.hit_cage + s.miss + s.hidden + s.ring_extended + s.ring_no_hit_neighbour + s.repaired,
             a.coverage.conservative_texels);
    CHECK_EQ(a.fallback_texels, e.fallback);
    CHECK_EQ(a.padding_texels, e.padding);
    CHECK_EQ(a.changed_used_texels, e.changed);
    CHECK(a.surface_modified == (e.fallback > 0));
    CHECK(a.fidelity_evidence == e.fidelity);
}

std::uint64_t Ones(const std::vector<std::uint8_t>& mask) {
    return static_cast<std::uint64_t>(std::count_if(mask.begin(), mask.end(), [](std::uint8_t v) { return v != 0; }));
}

}  // namespace receipt_cases

void CaseAccountingPlane() {
    using namespace receipt_cases;
    EmbreeBaker baker;
    const BakeMesh low = OffsetPlane("low", 0.0f);
    const std::uint64_t centre = kPlaneU.centre() * kPlaneRows.centre();
    const std::uint64_t used = kPlaneU.used() * kPlaneRows.used();
    CHECK_EQ(centre, 900u);
    CHECK_EQ(used, 1024u);
    const std::uint64_t ring = used - centre;

    // A full high plane: every centre texel hits; the ring holds no value.
    const BakeMesh full = NormalHigh({0, 0, 1});
    BakeRequest request = OffsetPlaneRequest(low, full, {MeshMapUsage::AO, MeshMapUsage::Normal});
    BakeResult r = Bake(baker, request);
    CheckConservation(r);
    CHECK_EQ(Ones(r.used_surface), used);
    Expected e{centre, used, {}, 0, kTexels - used, 0};
    e.classes.hit_straight = centre;
    e.classes.ring_no_hit_neighbour = ring;
    for (MeshMapUsage usage : request.usages) CheckAccount(AccountUsage(request, r, usage), e);
    UsageAccount normal = AccountUsage(request, r, MeshMapUsage::Normal);
    CHECK_EQ(normal.parts.size(), 1u);
    CHECK(normal.parts[0].name == "low" && normal.parts[0].hits == centre && normal.parts[0].misses == 0);
    CHECK(normal.parts[0].z_negative_texels && *normal.parts[0].z_negative_texels == 0);
    CHECK(!AccountUsage(request, r, MeshMapUsage::AO).parts[0].z_negative_texels);

    // High normals facing away from the low surface: every hit has a negative tangent Z, reported
    // and left as baked.
    const BakeMesh away = NormalHigh({1, 0, -1});
    BakeRequest away_request = OffsetPlaneRequest(low, away, {MeshMapUsage::Normal});
    const BakeResult a = Bake(baker, away_request);
    normal = AccountUsage(away_request, a, MeshMapUsage::Normal);
    CHECK_EQ(*normal.parts[0].z_negative_texels, centre);
    CHECK_EQ(normal.used_surface.hit_straight, centre);
    CHECK_EQ(normal.changed_used_texels, 0u);

    // The high plane over x <= 0 only: texel columns 17..31 hit, 32..46 miss (centre misses).
    const BakeMesh half = fixtures::Plane("half", -2, 0, -2, 2, 0.005f);
    request = OffsetPlaneRequest(low, half, {MeshMapUsage::AO, MeshMapUsage::Normal});
    r = Bake(baker, request);
    CheckConservation(r);
    e.classes.hit_straight = 15 * kPlaneRows.centre();
    e.classes.miss = 15 * kPlaneRows.centre();
    for (MeshMapUsage usage : request.usages) CheckAccount(AccountUsage(request, r, usage), e);
    normal = AccountUsage(request, r, MeshMapUsage::Normal);
    CHECK(normal.parts[0].hits == 450 && normal.parts[0].misses == 450);

    // The neutral fallback (Normal only): the misses and the ring take the flat normal, RAW is kept.
    BakeRequest fallback = OffsetPlaneRequest(low, half, {MeshMapUsage::Normal});
    const BakeResult plain = Bake(baker, fallback);
    fallback.neutral_fallback = true;
    const BakeResult f = Bake(baker, fallback);
    CHECK(f.normal_raw == plain.normal_raw);
    CHECK_EQ(f.fallback_texels, 450u + ring);
    Expected ef = e;
    ef.fallback = 450 + ring;
    ef.changed = 450 + ring;
    ef.fidelity = FidelityEvidence::ContainsFallback;
    CheckAccount(AccountUsage(fallback, f, MeshMapUsage::Normal), ef);
    const auto neutral = NeutralNormalCodes(uzp::core::NormalMapFormat::OpenGL);
    CHECK(neutral[0] == 32768 && neutral[1] == 32768 && neutral[2] == 65535);
    CHECK(NeutralNormalCodes(uzp::core::NormalMapFormat::DirectX)[1] == 32767);
    for (std::size_t i = 0; i < kTexels; ++i) {
        const bool set = f.used_surface[i] && !IsHit(f.texel_class[i]);
        for (std::size_t c = 0; c < 3; ++c) CHECK_EQ(f.normal[3 * i + c], set ? neutral[c] : plain.normal[3 * i + c]);
    }
    BakeRequest refused = OffsetPlaneRequest(low, half, {MeshMapUsage::AO, MeshMapUsage::Normal});
    refused.neutral_fallback = true;
    const std::string message = ExpectThrow<NotYetSupported>([&] { baker.bake(refused); });
    CHECK(Contains(message, "AO") && Contains(message, "decision 347"));

    // A custom cage: every centre texel is a cage hit.
    const BakeMesh cage = OffsetPlane("cage", 0.02f);
    request = OffsetPlaneRequest(low, full, {MeshMapUsage::AO});
    request.detail.cage_mode = CageMode::CustomFile;
    request.cage = {&cage};
    r = Bake(baker, request);
    CheckConservation(r);
    Expected ec{centre, used, {}, 0, kTexels - used, 0};
    ec.classes.hit_cage = centre;
    ec.classes.ring_no_hit_neighbour = ring;
    CheckAccount(AccountUsage(request, r, MeshMapUsage::AO), ec);

    // The hidden mask over columns 32..63: their centre texels are hidden; ring texels stay ring
    // (no ray is cast for them, mask or not).
    request = OffsetPlaneRequest(low, full, {MeshMapUsage::AO});
    request.hidden_mask.assign(kTexels, 0);
    for (std::size_t i = 0; i < kTexels; ++i) request.hidden_mask[i] = i % 64 >= 32 ? 1 : 0;
    r = Bake(baker, request);
    CheckConservation(r);
    Expected eh{centre, used, {}, 0, kTexels - used, 0};
    eh.classes.hit_straight = 15 * kPlaneRows.centre();
    eh.classes.hidden = 15 * kPlaneRows.centre();
    eh.classes.ring_no_hit_neighbour = ring;
    CheckAccount(AccountUsage(request, r, MeshMapUsage::AO), eh);

    // AO with DilationWidth 1: the ring is extended from its hit neighbours (and nothing outside
    // it is reached); with 2 the next ring outside the used surface is extended too. Extension is
    // not a modification of the used surface.
    request = OffsetPlaneRequest(low, full, {MeshMapUsage::AO});
    request.common.dilation_width = 1;
    r = Bake(baker, request);
    CheckConservation(r);
    Expected ed{centre, used, {}, 0, kTexels - used, ring};
    ed.classes.hit_straight = centre;
    ed.classes.ring_extended = ring;
    CheckAccount(AccountUsage(request, r, MeshMapUsage::AO), ed);
    CHECK_EQ(Ones(r.extension), ring);
    CHECK_EQ(r.dilated_texels, ring);
    request.common.dilation_width = 2;
    r = Bake(baker, request);
    CheckAccount(AccountUsage(request, r, MeshMapUsage::AO), ed);
    CHECK_EQ(Ones(r.extension), ring + (34u * 34u - used));
}

namespace receipt_cases {

/// The cube-sphere: the cube [-1, 1]^3's faces as `n` x `n` grids from exact lattice points,
/// projected on the unit sphere (smooth normals), face f on atlas cell f of 128 x 64 with its
/// island spanning texels [4.6, 27.1] of the cell on both axes: 22 x 22 centres, 24 x 24 used.
constexpr Span kSphereIsland{4.6, 27.1};

BakeMesh CubeSphere(std::uint32_t n) {
    BakeMesh mesh;
    mesh.name = "cube_sphere";
    for (std::uint32_t f = 0; f < 6; ++f) {
        const fixtures::CubeFace& face = fixtures::kCubeFaces[f];
        const double cx = (f % 4) * 32.0, cy = (f / 4) * 32.0;
        const auto base = static_cast<std::uint32_t>(mesh.positions.size());
        for (std::uint32_t j = 0; j <= n; ++j) {
            for (std::uint32_t i = 0; i <= n; ++i) {
                const double s = static_cast<double>(i) / n, t = static_cast<double>(j) / n;
                const double p[3] = {face.a.x + (face.b.x - face.a.x) * s + (face.d.x - face.a.x) * t,
                                     face.a.y + (face.b.y - face.a.y) * s + (face.d.y - face.a.y) * t,
                                     face.a.z + (face.b.z - face.a.z) * s + (face.d.z - face.a.z) * t};
                const double length = std::sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2]);
                const Float3 q{static_cast<float>(p[0] / length), static_cast<float>(p[1] / length),
                               static_cast<float>(p[2] / length)};
                mesh.positions.push_back(q);
                mesh.normals.push_back(q);
                const double u = cx + kSphereIsland.lo + (kSphereIsland.hi - kSphereIsland.lo) * s;
                const double row = cy + kSphereIsland.hi - (kSphereIsland.hi - kSphereIsland.lo) * t;
                mesh.uvs.push_back({static_cast<float>(u / 128.0), static_cast<float>(1.0 - row / 64.0)});
            }
        }
        for (std::uint32_t j = 0; j < n; ++j) {
            for (std::uint32_t i = 0; i < n; ++i) {
                const std::uint32_t a = base + j * (n + 1) + i, b = a + 1, c = b + n + 1, d = a + n + 1;
                for (std::uint32_t k : {a, b, c, a, c, d}) mesh.indices.push_back(k);
            }
        }
    }
    return mesh;
}

}  // namespace receipt_cases

void CaseAccountingSphere() {
    // The cube-sphere baked low as high: it is convex, so every primary ray, which starts outside
    // it and passes through its own texel's surface point, meets a front face first.
    using namespace receipt_cases;
    EmbreeBaker baker;
    const BakeMesh low = CubeSphere(8);
    BakeRequest request;
    request.texture_set = "sphere";
    request.input_revision = "fixture-r1";
    request.scale_to_internal = 1.0;
    request.usages = {MeshMapUsage::AO};
    request.output_size_log2[0] = fixtures::kAtlasWidthLog2;
    request.output_size_log2[1] = fixtures::kAtlasHeightLog2;
    request.detail.max_height = request.detail.max_depth = 0.05f;
    request.ao.secondary_rays = 4;
    request.ao.min_distance = 1e-4f;
    request.low = {&low};
    request.threads = 4;
    const std::uint64_t centre = 6 * kSphereIsland.centre() * kSphereIsland.centre();
    const std::uint64_t used = 6 * kSphereIsland.used() * kSphereIsland.used();
    CHECK_EQ(centre, 6 * 484u);
    CHECK_EQ(used, 6 * 576u);
    const std::uint64_t texels = 128 * 64;
    BakeResult r = Bake(baker, request);
    CheckConservation(r);
    Expected e{centre, used, {}, 0, texels - used, 0};
    e.classes.hit_straight = centre;
    e.classes.ring_no_hit_neighbour = used - centre;
    CheckAccount(AccountUsage(request, r, MeshMapUsage::AO), e);
    // The used surface is exactly the six islands' 24 x 24 texel blocks.
    for (std::uint32_t y = 0; y < 64; ++y) {
        for (std::uint32_t x = 0; x < 128; ++x) {
            const std::uint32_t cell = (y / 32) * 4 + x / 32;
            const std::uint32_t lx = x % 32, ly = y % 32;
            const bool inside = cell < 6 && lx >= kSphereIsland.used_first() && lx <= kSphereIsland.used_last() &&
                                ly >= kSphereIsland.used_first() && ly <= kSphereIsland.used_last();
            CHECK_EQ(r.used_surface[y * 128 + x] != 0, inside);
        }
    }
    request.common.dilation_width = 1;
    r = Bake(baker, request);
    e.classes.ring_extended = used - centre;
    e.classes.ring_no_hit_neighbour = 0;
    e.changed = used - centre;  // every AO hit value is nonzero, so each extended ring texel changed
    CheckAccount(AccountUsage(request, r, MeshMapUsage::AO), e);
}

void CaseAccountingBevel() {
    // The bevelled cube with highs (islands on texel boundaries: no ring). At max_depth 0.04 each
    // cube face has 480 hits and 96 centre misses; the knob's island hits everywhere.
    using namespace receipt_cases;
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest request = fixture.Request(0.04f);
    const std::uint64_t texels = kAtlasW * kAtlasH;
    BakeResult r = Bake(baker, request);
    CheckConservation(r);
    Expected e{7 * kIslandTexels, 7 * kIslandTexels, {}, 0, texels - 7 * kIslandTexels, 0};
    e.classes.hit_straight = 6 * 480 + kIslandTexels;
    e.classes.miss = 6 * 96;
    CheckAccount(AccountUsage(request, r, MeshMapUsage::AO), e);
    const UsageAccount a = AccountUsage(request, r, MeshMapUsage::AO);
    CHECK(a.parts.size() == 2 && a.parts[0].name == "cube_low" && a.parts[1].name == "knob_low");
    CHECK(a.parts[0].hits == 6 * 480u && a.parts[0].misses == 6 * 96u);
    CHECK(a.parts[1].hits == kIslandTexels && a.parts[1].misses == 0);
    // The top face hidden.
    request.hidden_mask.assign(texels, 0);
    for (std::uint32_t y = 32; y < kAtlasH; ++y) {
        for (std::uint32_t x = 0; x < 32; ++x) request.hidden_mask[y * kAtlasW + x] = 1;
    }
    r = Bake(baker, request);
    e.classes.hit_straight = 5 * 480 + kIslandTexels;
    e.classes.miss = 5 * 96;
    e.classes.hidden = kIslandTexels;
    CheckAccount(AccountUsage(request, r, MeshMapUsage::AO), e);
    // Dilation 8 writes padding only: no used texel changes.
    request.hidden_mask.clear();
    request.common.dilation_width = 8;
    r = Bake(baker, request);
    e.classes.hit_straight = 6 * 480 + kIslandTexels;
    e.classes.miss = 6 * 96;
    e.classes.hidden = 0;
    CheckAccount(AccountUsage(request, r, MeshMapUsage::AO), e);
    CHECK(r.dilated_texels > 0 && Ones(r.extension) == r.dilated_texels);
}

void CaseAccountingBuriedFace() {
    // Two low parts under the high cube [-1, 1]^3 (outward): the lid at z = 1 and a face buried
    // inside at z = 0. The lid's rays meet the cube's top front-on; the buried face's rays travel
    // inside the cube and meet its bottom's back face: misses, never filled. Each part's island
    // spans 21 x 30 centres and 23 x 32 used texels.
    using namespace receipt_cases;
    EmbreeBaker baker;
    constexpr Span kLidU{6.6, 28.3}, kBuriedU{35.6, 57.3};
    const BakeMesh lid = fixtures::Plane("lid", -0.9f, 0.9f, -0.9f, 0.9f, 1.0f, false,
                                         {static_cast<float>(kLidU.lo / 64.0), static_cast<float>(16.6 / 64.0)},
                                         {static_cast<float>(kLidU.hi / 64.0), static_cast<float>(47.3 / 64.0)});
    const BakeMesh buried = fixtures::Plane("buried", -0.9f, 0.9f, -0.9f, 0.9f, 0.0f, false,
                                            {static_cast<float>(kBuriedU.lo / 64.0), static_cast<float>(16.6 / 64.0)},
                                            {static_cast<float>(kBuriedU.hi / 64.0), static_cast<float>(47.3 / 64.0)});
    const BakeMesh box = fixtures::Box("box_high", 1.0f, false);
    BakeRequest request = PlaneRequest(lid);
    request.usages = {MeshMapUsage::AO, MeshMapUsage::Normal};
    request.detail.low_as_high = false;
    request.detail.max_height = 0.05f;
    request.detail.max_depth = 1.2f;
    request.low = {&lid, &buried};
    request.high = {&box};
    const std::uint64_t part_centre = kLidU.centre() * kPlaneRows.centre();
    const std::uint64_t part_used = kLidU.used() * kPlaneRows.used();
    CHECK(part_centre == 630 && part_used == 736);
    CHECK(kBuriedU.centre() * kPlaneRows.centre() == part_centre && kBuriedU.used() * kPlaneRows.used() == part_used);
    BakeResult r = Bake(baker, request);
    CheckConservation(r);
    CHECK_EQ(r.texels.back_face_hit, part_centre);
    Expected e{2 * part_centre, 2 * part_used, {}, 0, kTexels - 2 * part_used, 0};
    e.classes.hit_straight = part_centre;
    e.classes.miss = part_centre;
    e.classes.ring_no_hit_neighbour = 2 * (part_used - part_centre);
    for (MeshMapUsage usage : request.usages) {
        const UsageAccount a = AccountUsage(request, r, usage);
        CheckAccount(a, e);
        CHECK(a.parts.size() == 2 && a.parts[0].name == "lid" && a.parts[1].name == "buried");
        CHECK(a.parts[0].hits == part_centre && a.parts[0].misses == 0);
        CHECK(a.parts[1].hits == 0 && a.parts[1].misses == part_centre);
        if (usage == MeshMapUsage::Normal) CHECK(*a.parts[0].z_negative_texels == 0 && *a.parts[1].z_negative_texels == 0);
    }
    // Marked hidden, the buried face's texels are hidden instead of missed.
    request.hidden_mask.assign(kTexels, 0);
    for (std::size_t i = 0; i < kTexels; ++i) request.hidden_mask[i] = i % 64 >= 32 ? 1 : 0;
    r = Bake(baker, request);
    e.classes.miss = 0;
    e.classes.hidden = part_centre;
    const UsageAccount a = AccountUsage(request, r, MeshMapUsage::AO);
    CheckAccount(a, e);
    CHECK(a.parts[1].hits == 0 && a.parts[1].misses == 0);
}

namespace receipt_cases {

std::set<std::string> Keys(const uzp::core::json::Object& object) {
    std::set<std::string> keys;
    for (const auto& [key, value] : object) keys.insert(key);
    return keys;
}

const uzp::core::json::Object& Obj(const uzp::core::json::Value& value) {
    return std::get<uzp::core::json::Object>(value.data);
}

const uzp::core::json::Array& Arr(const uzp::core::json::Value& value) {
    return std::get<uzp::core::json::Array>(value.data);
}

ReceiptContext Context() {
    ReceiptContext context;
    context.job_id = 7;
    context.header.revision = 3;
    context.header.evaluator_profile = "painter-12.1-isolated-linear";
    context.header.compat_profile = std::string(uzp::core::kCompatProfile);
    context.header.app_version = "0.0.0";
    context.header.resource_hashes = {uzp::core::Sha256Hex("mesh file")};
    context.build_hash = "test-build";
    return context;
}

}  // namespace receipt_cases

void CaseReceiptContent() {
    using namespace receipt_cases;
    using uzp::core::json::Value;
    EmbreeBaker baker;
    const BakeMesh low = OffsetPlane("low", 0.0f);
    const BakeMesh half = fixtures::Plane("half", -2, 0, -2, 2, 0.005f);
    BakeRequest request = OffsetPlaneRequest(low, half, {MeshMapUsage::AO, MeshMapUsage::Normal});
    const BakeResult r = Bake(baker, request);
    const BakeReceipt receipt = BuildReceipt(request, r, baker.caps(), Context());
    const uzp::core::json::Object json = ReceiptJson(receipt);

    // Every field of 06-baking.md section 4, the record header and parity_status.
    CHECK((Keys(json) == std::set<std::string>{"app_version", "compat_profile", "evaluator_profile", "input_revision",
                                               "inputs", "job_id", "parity_status", "resource_hashes", "revision",
                                               "settings_hash", "status", "texture_set", "tools", "usages"}));
    CHECK(json.at("job_id") == Value(7) && json.at("texture_set") == Value("fixture") &&
          json.at("input_revision") == Value("fixture-r1") && json.at("status") == Value("Success") &&
          json.at("parity_status") == Value("pending-evidence"));
    CHECK(uzp::core::HeaderFromJson(json) == Context().header);
    const auto& tools = Obj(json.at("tools"));
    CHECK((Keys(tools) == std::set<std::string>{"backend", "backend_version", "baker_version", "build_hash", "isa_or_gpu"}));
    CHECK(tools.at("backend") == Value("embree") && tools.at("baker_version") == Value(kBakerVersion) &&
          tools.at("backend_version") == Value(baker.caps().embree_version) &&
          tools.at("isa_or_gpu") == Value(baker.caps().isa) && tools.at("build_hash") == Value("test-build"));
    const auto& inputs = Obj(json.at("inputs"));
    CHECK((Keys(inputs) == std::set<std::string>{"hidden_mask", "low_mesh_hashes", "parts"}));
    CHECK(inputs.at("hidden_mask").IsNull());
    CHECK(Arr(inputs.at("low_mesh_hashes")) == uzp::core::json::Array{Value(MeshContentHash(low))});
    const auto& part = Obj(Arr(inputs.at("parts")).at(0));
    CHECK(part.at("name") == Value("low"));
    CHECK(Arr(part.at("high_meshes")) == uzp::core::json::Array{Value(MeshContentHash(half))});
    CHECK(part.at("cage") == Value(uzp::core::json::Object{{"frontal", Value(0.05f * 1.0)},
                                                            {"rear", Value(0.05f * 1.0)},
                                                            {"relative", false}}));
    CHECK(json.at("settings_hash") == Value(SettingsHash(request)));

    // Hashes match the stored maps: every usage's map and raw are the evidence files' bytes.
    const std::vector<EvidenceFile> files = EvidenceFiles(request, r);
    const auto file_sha = [&](MeshMapUsage usage, const std::string& name) {
        const std::string path = EvidenceDirectory(request) + "/" + UsageName(usage) + "/" + name;
        for (const EvidenceFile& file : files) {
            if (file.path == path) return file.sha256;
        }
        throw Failure("no evidence file " + path);
    };
    const auto& usages = Arr(json.at("usages"));
    CHECK_EQ(usages.size(), 2u);
    for (std::size_t u = 0; u < 2; ++u) {
        const MeshMapUsage usage = request.usages[u];
        const auto& entry = Obj(usages[u]);
        CHECK((Keys(entry) == std::set<std::string>{"changed_used_texels", "coverage", "effective_normalization",
                                                    "fallback_texels", "fidelity_evidence", "map", "padding_texels",
                                                    "parts", "raw", "surface_modified", "usage", "used_surface"}));
        CHECK(entry.at("usage") == Value(UsageName(usage)));
        CHECK(entry.at("map") == Value(file_sha(usage, "map.png")) && entry.at("raw") == Value(file_sha(usage, "raw.png")));
        CHECK(entry.at("map") == Value(uzp::core::Sha256Hex(EncodeMapFile(*CompatibleMap(r, usage)))));
        CHECK((Keys(Obj(entry.at("coverage"))) == std::set<std::string>{"centre_texels", "conservative_texels"}));
        CHECK((Keys(Obj(entry.at("used_surface"))) ==
               std::set<std::string>{"hidden", "hit_cage", "hit_straight", "miss", "repaired", "ring_extended",
                                     "ring_no_hit_neighbour"}));
        CHECK(Obj(entry.at("coverage")).at("conservative_texels") == Value(1024));
        CHECK(Obj(entry.at("used_surface")).at("miss") == Value(450));
        CHECK(entry.at("fidelity_evidence") == Value("used_surface_as_baked"));
        CHECK(entry.at("surface_modified") == Value(false) && entry.at("fallback_texels") == Value(0));
        const auto& usage_part = Obj(Arr(entry.at("parts")).at(0));
        CHECK((Keys(usage_part) == std::set<std::string>{"hits", "misses", "name", "z_negative_texels"}));
        CHECK(usage_part.at("z_negative_texels").IsNull() == (usage == MeshMapUsage::AO));
        CHECK(Obj(entry.at("effective_normalization")).empty());
    }
    // The canonical bytes parse back to the same object.
    CHECK(uzp::core::json::Parse(ReceiptBytes(receipt)) == Value(json));

    // The settings hash moves with an output-determining setting, never with the thread count.
    BakeRequest other = request;
    other.threads = 1;
    CHECK(SettingsHash(other) == SettingsHash(request));
    other.ao.secondary_rays = 8;
    CHECK(SettingsHash(other) != SettingsHash(request));
    // A hidden mask is hashed; a custom cage is named by its hash.
    BakeRequest masked = request;
    masked.hidden_mask.assign(kTexels, 0);
    const BakeReceipt masked_receipt = BuildReceipt(masked, Bake(baker, masked), baker.caps(), Context());
    CHECK(masked_receipt.inputs.hidden_mask &&
          *masked_receipt.inputs.hidden_mask == uzp::core::Sha256Hex(std::string(kTexels, '\0')));
    const BakeMesh cage = OffsetPlane("cage", 0.02f);
    BakeRequest caged = request;
    caged.detail.cage_mode = CageMode::CustomFile;
    caged.cage = {&cage};
    const BakeReceipt caged_receipt = BuildReceipt(caged, Bake(baker, caged), baker.caps(), Context());
    CHECK(caged_receipt.inputs.parts[0].cage.sha256 == MeshContentHash(cage));
    CHECK(caged_receipt.usages[0].account.used_surface.hit_cage == 450);

    // fidelity_evidence: with an enabled fallback, and on the diagnostic path.
    BakeRequest fallback = OffsetPlaneRequest(low, half, {MeshMapUsage::Normal});
    fallback.neutral_fallback = true;
    const BakeReceipt f = BuildReceipt(fallback, Bake(baker, fallback), baker.caps(), Context());
    CHECK(f.usages[0].account.fidelity_evidence == FidelityEvidence::ContainsFallback);
    CHECK(f.usages[0].account.fallback_texels == 574 && f.usages[0].account.surface_modified);
    CHECK(f.usages[0].map_sha256 != f.usages[0].raw_sha256);
    CHECK(Obj(Arr(ReceiptJson(f).at("usages"))[0]).at("fidelity_evidence") == Value("contains_fallback"));
    EmbreeBaker diagnostic(Config(8, true));
    const BakeReceipt d = BuildReceipt(request, Bake(diagnostic, request), diagnostic.caps(), Context());
    for (const ReceiptUsage& usage : d.usages) CHECK(usage.account.fidelity_evidence == FidelityEvidence::DiagnosticOnly);

    // A usage without a per-texel map has none; Position records its normalisation.
    BakeRequest thickness = request;
    thickness.usages = {MeshMapUsage::Thickness, MeshMapUsage::Position};
    thickness.thickness.normalization.reset();
    thickness.thickness.relative_to_bounding_box = false;
    thickness.thickness.secondary_rays = 2;
    thickness.position.normalization = PositionNormalization::None;
    const BakeResult t = Bake(baker, thickness);
    const BakeReceipt tr = BuildReceipt(thickness, t, baker.caps(), Context());
    CHECK(!tr.usages[0].map_sha256 && !tr.usages[0].raw_sha256);
    CHECK(tr.usages[0].effective_normalization == ThicknessRecordJson(t.thickness));
    CHECK(tr.usages[1].map_sha256 && tr.usages[1].effective_normalization == PositionNormalizationJson(t.position_normalization));
    ReceiptContext no_build = Context();
    no_build.build_hash.clear();
    ExpectThrow<ValueError>([&] { BuildReceipt(request, r, baker.caps(), no_build); });
}

void CaseEvidenceRegenerated() {
    // The evidence files written under cache/, deleted, and regenerated from the same request:
    // byte-identical, and the compatible map unchanged.
    using namespace receipt_cases;
    EmbreeBaker baker;
    const BakeMesh low = OffsetPlane("low", 0.0f);
    const BakeMesh full = NormalHigh({0, 0, 1});
    BakeRequest request = OffsetPlaneRequest(low, full, {MeshMapUsage::AO});
    request.common.dilation_width = 2;
    const BakeResult first = Bake(baker, request);
    const std::vector<std::uint16_t> map = first.ao;
    const std::vector<EvidenceFile> files = EvidenceFiles(request, first);
    CHECK(first.ao == map);
    CHECK_EQ(files.size(), 6u);
    const std::string base = EvidenceDirectory(request) + "/AO/";
    std::set<std::string> paths;
    for (const EvidenceFile& file : files) {
        paths.insert(file.path);
        CHECK(file.sha256 == uzp::core::Sha256Hex(file.bytes));
    }
    CHECK((paths == std::set<std::string>{base + "map.png", base + "raw.png", base + "hit.png", base + "coverage.png",
                                          base + "miss.png", base + "extension.png"}));
    CHECK(base.rfind("cache/bake/", 0) == 0);
    const std::filesystem::path root =
        std::filesystem::temp_directory_path() /
        ("uzp-bake-evidence-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    std::filesystem::remove_all(root);
    const auto read = [&](const EvidenceFile& file) {
        std::ifstream in(root / file.path, std::ios::binary);
        return std::string((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    };
    WriteEvidence(root, files);
    for (const EvidenceFile& file : files) CHECK(read(file) == file.bytes);
    std::filesystem::remove_all(root / "cache");
    const BakeResult again = Bake(baker, request);
    WriteEvidence(root, EvidenceFiles(request, again));
    for (const EvidenceFile& file : files) CHECK(read(file) == file.bytes);
    CHECK(again.ao == map && again.ao_raw == first.ao_raw);
    std::filesystem::remove_all(root);
    // The masks: the raw and map differ only where the extension mask is set.
    for (std::size_t i = 0; i < kTexels; ++i) CHECK(first.ao[i] == first.ao_raw[i] || first.extension[i] != 0);
    // A float map is stored in the float evidence container.
    BakeRequest opacity = OffsetPlaneRequest(low, full, {MeshMapUsage::Opacity});
    const BakeResult o = Bake(baker, opacity);
    const std::string bytes = EncodeMapFile(*CompatibleMap(o, MeshMapUsage::Opacity));
    CHECK(bytes.size() == 20 + 4 * kTexels && bytes.compare(0, 8, std::string("UZPF32\0\0", 8)) == 0);
}

namespace receipt_cases {

uzp::core::Project PublicationProject(int resolution) {
    using namespace uzp::core;
    Project project;
    project.versions.app_version = "0.0.0";
    project.versions.evaluator_profile = "painter-12.1-isolated-linear";
    TextureSet set;
    set.id = project.AllocateId();
    set.name = set.original_name = set.material_id = "fixture";
    set.resolution = {resolution, resolution, {}};
    set.uv_tiles = {UVTile{project.AllocateId(), 1001, {}}};
    Stack stack;
    stack.id = project.AllocateId();
    stack.channels[ChannelType::BaseColor] = Channel{ChannelFormat::sRGB8, "", {}};
    set.stacks.push_back(stack);
    project.texture_sets.push_back(set);
    return project;
}

struct Published {
    uzp::core::Document document;
    std::map<std::string, std::string> staged;
    StageResource stage;
    int calls = 0;

    explicit Published(uzp::core::Project project) : document(State(std::move(project))) {
        stage = [this](std::string bytes, std::string) {
            std::string sha = uzp::core::Sha256Hex(bytes);
            staged[sha] = std::move(bytes);
            return sha;
        };
    }
    static uzp::core::DocumentState State(uzp::core::Project project) {
        uzp::core::DocumentState state;
        state.project_uuid = "6f1c2a3e-0000-4000-8000-0000000003a7";
        state.project = std::move(project);
        return state;
    }
    PublicationOutcome Publish(const BakeRequest& request, const BakeResult& result, const Capabilities& caps) {
        PublicationContext context;
        context.job_id = 11;
        context.build_hash = "test-build";
        context.input_resources = {uzp::core::Sha256Hex("mesh file")};
        context.published_at = "2026-10-21T00:00:00Z";
        const std::string key = "bake-publish-" + std::to_string(++calls);
        return PublishBake(document, {"bake_publish", uzp::core::json::Object{{"key", key}}, key, document.revision()},
                           request, result, caps, context, stage);
    }
    uzp::core::TextureSet Set() const { return document.snapshot().project->texture_sets.front(); }
};

bool Failed(const PublicationOutcome& p, const std::string& type, const std::string& part) {
    return p.outcome.result && p.outcome.result->status == uzp::core::ResultStatus::failed &&
           p.outcome.result->error_type == type && Contains(p.outcome.result->error, part) && !p.receipt;
}

}  // namespace receipt_cases

void CasePublicationAtomic() {
    using namespace receipt_cases;
    using uzp::core::json::Value;
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    const BakeMesh full = NormalHigh({0, 0, 1});
    BakeRequest request = OffsetPlaneRequest(low, full, {MeshMapUsage::AO, MeshMapUsage::Normal});
    request.output_size_log2[0] = request.output_size_log2[1] = 7;
    request.input_revision = "0";
    const BakeResult r = Bake(baker, request);

    // Both usages bound with baked provenance, the receipt stored with them, one revision.
    Published p(PublicationProject(128));
    const PublicationOutcome done = p.Publish(request, r, baker.caps());
    CHECK(done.outcome.result);
    if (done.outcome.result->status != uzp::core::ResultStatus::committed) {
        throw Failure("publication did not commit: " + done.outcome.result->error_type + ": " +
                      done.outcome.result->error);
    }
    CHECK_EQ(p.document.revision(), 1);
    CHECK(done.receipt && done.receipt->header.revision == 0);
    const std::string receipt_bytes = p.staged.at(done.receipt_sha256);
    CHECK(receipt_bytes == ReceiptBytes(*done.receipt));
    CHECK(uzp::core::HeaderFromJson(Obj(uzp::core::json::Parse(receipt_bytes))).resource_hashes ==
          std::set<std::string>{uzp::core::Sha256Hex("mesh file")});
    const uzp::core::Project project = *p.document.snapshot().project;
    const uzp::core::TextureSet& set = project.texture_sets.front();
    CHECK_EQ(set.mesh_maps.size(), 2u);
    for (std::size_t u = 0; u < 2; ++u) {
        const MeshMapUsage usage = request.usages[u];
        const auto& binding = set.mesh_maps.at(*uzp::core::FromString<uzp::core::MeshMapUsage>(UsageName(usage)));
        CHECK(binding.format == (usage == MeshMapUsage::AO ? uzp::core::ChannelFormat::L16 : uzp::core::ChannelFormat::RGB16));
        CHECK(binding.resource == *done.receipt->usages[u].map_sha256);
        CHECK(p.staged.at(binding.resource) == EncodeMapFile(*CompatibleMap(r, usage)));
        CHECK(project.resources.at(binding.resource).front().mime == "image/png");
        const auto& baked = std::get<uzp::core::BakedProvenance>(binding.provenance);
        CHECK(baked.baker_version == kBakerVersion && baked.backend == uzp::core::BakerBackend::embree);
        CHECK(baked.settings_hash == SettingsHash(request));
        CHECK(baked.high_meshes == std::vector<std::string>{MeshContentHash(full)});
        CHECK(!baked.cage && baked.mesh_hashes == LowMeshHashes(request));
        CHECK(baked.extra.at("receipt") == Value(done.receipt_sha256));
        CHECK(baked.extra.at("parity_status") == Value("pending-evidence"));
        CHECK(baked.extra.at("fidelity_evidence") == Value("used_surface_as_baked"));
    }
    CHECK(project.resources.at(done.receipt_sha256).front().mime == "application/json");

    // A stale bake (it read revision 0; the document is at 1) is not published.
    const auto before = p.Set().mesh_maps;
    CHECK(Failed(p.Publish(request, r, baker.caps()), "ValueError", "stale"));
    CHECK(p.document.revision() == 1 && p.Set().mesh_maps == before);

    // One usage that cannot be bound: neither is bound.
    Published q(PublicationProject(128));
    for (MeshMapUsage other : {MeshMapUsage::Height, MeshMapUsage::ID, MeshMapUsage::Thickness, MeshMapUsage::Opacity}) {
        BakeRequest both = request;
        both.usages = {MeshMapUsage::Normal, other};
        both.height.normalization.reset();
        both.id.generator.reset();
        both.id.source = IdColorSource::MeshId;
        both.thickness.normalization.reset();
        both.thickness.relative_to_bounding_box = false;
        both.thickness.secondary_rays = 1;
        const BakeResult result = Bake(baker, both);
        CHECK(Failed(q.Publish(both, result, baker.caps()), "NotYetSupported", UsageOwnerTask(other)));
        CHECK(q.document.revision() == 0 && q.Set().mesh_maps.empty() && q.document.snapshot().project->resources.empty());
    }
    // An output size other than the set's resolution, a Normal convention other than the
    // project's and a diagnostic bake are refused; so is a commit the store refuses.
    Published small(PublicationProject(256));
    CHECK(Failed(small.Publish(request, r, baker.caps()), "NotYetSupported", "resampling"));
    uzp::core::Project directx = PublicationProject(128);
    directx.settings.normal_map_format = uzp::core::NormalMapFormat::DirectX;
    Published dx(std::move(directx));
    CHECK(Failed(dx.Publish(request, r, baker.caps()), "ValueError", "tangent space"));
    EmbreeBaker diagnostic(Config(8, true));
    Published diag(PublicationProject(128));
    CHECK(Failed(diag.Publish(request, Bake(diagnostic, request), diagnostic.caps()), "ValueError", "diagnostic"));
    Published sink(PublicationProject(128));
    sink.document.SetCommitSink([](const uzp::core::Snapshot&, const uzp::core::OperationRecord&) {
        throw std::runtime_error("injected commit failure");
    });
    const PublicationOutcome refused = sink.Publish(request, r, baker.caps());
    CHECK(refused.outcome.result && refused.outcome.result->status == uzp::core::ResultStatus::failed && !refused.receipt);
    CHECK(sink.document.revision() == 0 && sink.Set().mesh_maps.empty());
    for (Published* none : {&small, &dx, &diag}) CHECK(none->document.revision() == 0 && none->Set().mesh_maps.empty());
}
