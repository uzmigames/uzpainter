// Thickness cases (phase3.4_baker-thickness, decision 341). Included inside the native driver's
// namespace after the Height cases; they use `BevelHit` and the fixtures. Each ray's direction is
// decision 302's sample (`TexelSample`, `HemisphereDirection`, checked by the `sampling` case)
// around the inward normal; its expected distance is analytic: the slab's depth over the ray's
// cosine, the chord of the sphere, the exit from the chamfered cube's planes.

/// `request` baking Thickness alone with `rays` rays, absolute distances in centimetres, as the
/// evidence request: the per-ray classes and distances, no normalisation.
BakeRequest ThicknessRequest(BakeRequest request, std::uint32_t rays, float min_cm, float max_cm) {
    request.usages = {MeshMapUsage::Thickness};
    request.thickness.secondary_rays = rays;
    request.thickness.min_distance = min_cm;
    request.thickness.max_distance = max_cm;
    request.thickness.relative_to_bounding_box = false;
    request.thickness.normalization = std::nullopt;
    return request;
}

/// The inward direction of ray `s` of texel `texel` around the outward unit normal `n`.
Vec3d InwardRay(const BakeResult& r, std::size_t texel, std::uint32_t s, const Vec3d& n) {
    const std::uint32_t rays = r.thickness.settings.secondary_rays;
    return HemisphereDirection(r.thickness.settings.distribution, TexelSample(texel, s, rays), {-n.x, -n.y, -n.z});
}

ThicknessRayClass RayClassAt(const BakeResult& r, std::size_t texel, std::uint32_t s) {
    return static_cast<ThicknessRayClass>(r.thickness_ray_class[texel * r.thickness.settings.secondary_rays + s]);
}

float RayDistanceAt(const BakeResult& r, std::size_t texel, std::uint32_t s) {
    return r.thickness_ray_distance[texel * r.thickness.settings.secondary_rays + s];
}

/// Non-hit texels cast nothing; hit texels cast every ray; an escaped ray holds distance 0; the
/// totals count the classes; AO's ray totals stay apart.
void CheckThicknessEvidence(const BakeResult& r) {
    const std::uint32_t rays = r.thickness.settings.secondary_rays;
    const std::size_t texels = std::size_t(r.width) * r.height;
    CHECK_EQ(r.thickness_ray_class.size(), texels * rays);
    CHECK_EQ(r.thickness_ray_distance.size(), texels * rays);
    RayClassCounts seen;
    for (std::size_t i = 0; i < texels; ++i) {
        for (std::uint32_t s = 0; s < rays; ++s) {
            const ThicknessRayClass cls = RayClassAt(r, i, s);
            const float distance = RayDistanceAt(r, i, s);
            CHECK_EQ(cls == ThicknessRayClass::NotCast, !IsHit(r.texel_class[i]));
            if (cls == ThicknessRayClass::NotCast || cls == ThicknessRayClass::Escaped) CHECK(distance == 0.0f);
            if (cls == ThicknessRayClass::Escaped) ++seen.escaped;
            if (cls == ThicknessRayClass::FrontHit) ++seen.front_hit;
            if (cls == ThicknessRayClass::BackFaceHit) ++seen.back_face_hit;
            if (cls == ThicknessRayClass::SelfHit) ++seen.self_hit;
        }
    }
    const RayClassCounts& t = r.thickness.rays;
    CHECK_EQ(t.escaped, seen.escaped);
    CHECK_EQ(t.front_hit, seen.front_hit);
    CHECK_EQ(t.back_face_hit, seen.back_face_hit);
    CHECK_EQ(t.self_hit, seen.self_hit);
    CHECK_EQ(t.escaped + t.front_hit + t.back_face_hit + t.self_hit, (r.texels.straight_hit + r.texels.cage_hit) * rays);
    if (r.ao_raw.empty()) CHECK_EQ(r.rays.escaped + r.rays.front_hit + r.rays.back_face_hit + r.rays.self_hit, 0u);
}

void CaseThicknessPlane() {
    // A slab under the low plane: its top at z = 0.005 facing up, its bottom 0.25 below facing down,
    // both 200 wide, at 2.54 cm per mesh unit. An inward ray at cosine c to -z meets the bottom's
    // back face 0.25 / c away, or escapes beyond max_distance (10 mesh units).
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    const BakeMesh slab = fixtures::Merge("slab", {fixtures::Plane("top", -100, 100, -100, 100, 0.005f),
                                                   fixtures::Plane("bottom", -100, 100, -100, 100, -0.245f, true)});
    BakeRequest base = PlaneRequest(low);
    base.detail.low_as_high = false;
    base.scale_to_internal = 2.54;
    base.detail.max_height = base.detail.max_depth = 0.05f * 2.54f;
    base.high = {&slab};
    for (Distribution distribution : {Distribution::Cosine, Distribution::Uniform}) {
        BakeRequest request = ThicknessRequest(base, 16, 1e-4f * 2.54f, 10.0f * 2.54f);
        request.thickness.distribution = distribution;
        const BakeResult r = Bake(baker, request);
        CheckConservation(r);
        CheckThicknessEvidence(r);
        CHECK_EQ(r.texels.straight_hit, kCovered);
        std::uint64_t checked = 0;
        for (std::size_t i = 0; i < kTexels; ++i) {
            if (!UnderPlaneUv(i)) continue;
            for (std::uint32_t s = 0; s < 16; ++s) {
                const double c = -InwardRay(r, i, s, {0, 0, 1}).z;
                CHECK(c >= 0.0);
                const double depth = 0.25 / c;
                if (std::abs(depth - 10.0) < 1e-3) continue;  // on the window's end
                if (depth > 10.0) {
                    CHECK(RayClassAt(r, i, s) == ThicknessRayClass::Escaped);
                    continue;
                }
                CHECK(RayClassAt(r, i, s) == ThicknessRayClass::BackFaceHit);
                CHECK(Near(RayDistanceAt(r, i, s), depth * 2.54, 1e-5 * (1.0 + depth)));
                ++checked;
            }
        }
        CHECK(checked > kCovered * 8);
        CHECK(r.thickness.settings.distribution == distribution);
    }
    // Without the bottom the surface is open: every ray escapes.
    const BakeMesh top = fixtures::Plane("top", -100, 100, -100, 100, 0.005f);
    base.high = {&top};
    const BakeResult open = Bake(baker, ThicknessRequest(base, 16, 1e-4f * 2.54f, 10.0f * 2.54f));
    CheckThicknessEvidence(open);
    CHECK_EQ(open.thickness.rays.escaped, kCovered * 16);
}

void CaseThicknessSphere() {
    // The sphere on the ground low as high, baked with WorldSpaceNormal and Position for each hit's
    // normal and point: a sphere texel's rays not within 60 degrees of grazing meet the far side
    // from inside (a back face) at the chord of the radius-0.5 sphere through the hit point, within
    // the tessellation's 0.0055 radial error over a cosine of at least 0.5; the open ground's rays
    // all escape downwards.
    EmbreeBaker baker;
    const BakeMesh low = fixtures::SphereOnGround();
    BakeRequest request = ThicknessRequest(SphereRequest(low, 7), 8, 1e-4f, 2.0f);
    request.usages = {MeshMapUsage::Thickness, MeshMapUsage::WorldSpaceNormal, MeshMapUsage::Position};
    request.position.normalization = PositionNormalization::None;
    const BakeResult r = Bake(baker, request);
    CheckConservation(r);
    CheckThicknessEvidence(r);
    std::uint64_t ground = 0, chords = 0;
    for (std::size_t i = 0; i < std::size_t(r.width) * r.height; ++i) {
        if (!IsHit(r.texel_class[i])) continue;
        if ((i % r.width + 0.5) / r.width < 0.5) {
            for (std::uint32_t s = 0; s < 8; ++s) CHECK(RayClassAt(r, i, s) == ThicknessRayClass::Escaped);
            ++ground;
            continue;
        }
        const Vec3d q{r.position[3 * i], r.position[3 * i + 1], r.position[3 * i + 2] - 0.5};  // from the centre
        const Vec3d n{r.world_normal[3 * i], r.world_normal[3 * i + 1], r.world_normal[3 * i + 2]};
        const double length = std::sqrt(q.x * q.x + q.y * q.y + q.z * q.z);
        for (std::uint32_t s = 0; s < 8; ++s) {
            const Vec3d d = InwardRay(r, i, s, n);
            const double b = d.x * q.x + d.y * q.y + d.z * q.z;
            if (-b / length < 0.5) continue;  // near grazing: the tessellation dominates
            const double chord = -b + std::sqrt(b * b - (length * length - 0.25));
            CHECK(RayClassAt(r, i, s) == ThicknessRayClass::BackFaceHit);
            CHECK(Near(RayDistanceAt(r, i, s), chord, 0.025));
            ++chords;
        }
    }
    CHECK(ground > 0 && chords > 0);
}

/// The distance from `p` along the unit `d` to the boundary of the chamfered cube (its 6 face, 12
/// edge and 8 corner planes), leaving it; infinite when no plane is ahead.
double ChamferExit(const Vec3d& p, const Vec3d& d) {
    const double m = 1.0 - kBevel;
    double best = kInf;
    const auto plane = [&](double nx, double ny, double nz, double h) {
        const double nd = nx * d.x + ny * d.y + nz * d.z;
        if (nd > 0.0) best = std::min(best, (h - (nx * p.x + ny * p.y + nz * p.z)) / nd);
    };
    for (double s : {-1.0, 1.0}) {
        plane(s, 0, 0, 1);
        plane(0, s, 0, 1);
        plane(0, 0, s, 1);
        for (double t : {-1.0, 1.0}) {
            plane(s, t, 0, 1 + m);
            plane(0, s, t, 1 + m);
            plane(s, 0, t, 1 + m);
            for (double u : {-1.0, 1.0}) plane(s, t, u, 1 + 2 * m);
        }
    }
    return best;
}

void CaseThicknessBevel() {
    // The bevelled cube with highs matched by name: a cube texel's rays leave the chamfered cube
    // through a back face at the analytic exit distance, or escape beyond 1.5; the knob's rays look
    // down at nothing nearer than the decoy, 1.98 below: they escape.
    EmbreeBaker baker;
    Bevel fixture;
    // The rays are drawn around the baked normal (WorldSpaceNormal): the analytic facet normal
    // equals it within float precision, but a zero component's sign (-0 from the interpolation)
    // selects the sample frame (decision 302's orthonormal basis).
    BakeRequest request = ThicknessRequest(fixture.Request(0.07f), 8, 1e-4f, 1.5f);
    request.usages = {MeshMapUsage::Thickness, MeshMapUsage::WorldSpaceNormal};
    const BakeResult r = Bake(baker, request);
    CheckConservation(r);
    CheckThicknessEvidence(r);
    std::uint64_t exits = 0, escapes = 0, knob = 0;
    for (std::uint32_t y = 0; y < kAtlasH; ++y) {
        for (std::uint32_t x = 0; x < kAtlasW; ++x) {
            Vec3d point, normal;
            std::uint32_t mesh = 0;
            if (!BevelHit(x, y, 0.07, point, normal, mesh)) continue;
            const std::size_t i = std::size_t(y) * kAtlasW + x;
            const Vec3d baked{r.world_normal[3 * i], r.world_normal[3 * i + 1], r.world_normal[3 * i + 2]};
            CHECK(Near(baked.x, normal.x, 1e-6) && Near(baked.y, normal.y, 1e-6) && Near(baked.z, normal.z, 1e-6));
            for (std::uint32_t s = 0; s < 8; ++s) {
                const ThicknessRayClass cls = RayClassAt(r, i, s);
                if (mesh == 1) {
                    CHECK(cls == ThicknessRayClass::Escaped);
                    ++knob;
                    continue;
                }
                const double exit = ChamferExit(point, InwardRay(r, i, s, baked));
                if (exit < 1e-3 || std::abs(exit - 1.5) < 1e-4) continue;  // on an edge, or the window's end
                if (exit > 1.5) {
                    CHECK(cls == ThicknessRayClass::Escaped);
                    ++escapes;
                    continue;
                }
                CHECK(cls == ThicknessRayClass::BackFaceHit);
                CHECK(Near(RayDistanceAt(r, i, s), exit, 1e-4));
                ++exits;
            }
        }
    }
    CHECK(exits > 0 && escapes > 0 && knob == kIslandTexels * 8);
}

void CaseThicknessThreadsInProcess() {
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest request = ThicknessRequest(fixture.Request(0.07f), 8, 1e-4f, 1.5f);
    std::string reference;
    for (std::uint32_t threads : {1u, 4u, std::max(1u, std::thread::hardware_concurrency())}) {
        request.threads = threads;
        const std::string bytes = SerializeResult(Bake(baker, request));
        if (reference.empty()) reference = bytes;
        CHECK(bytes == reference);
    }
}

void CaseThicknessRecord() {
    // The settings and the effective distances are recorded, relative ones as fractions of the
    // box size the request names; the JSON is the binding's effective_normalization.
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest request = ThicknessRequest(fixture.Request(0.07f), 8, 1e-4f, 0.25f);
    request.thickness.relative_to_bounding_box = true;
    request.project_bounds = BoundingBox{{-1.5f, -1.5f, -1.0f}, {1.5f, 1.5f, 3.02f}};
    request.box_size_metric = BoxSizeMetric::LargestExtent;
    const BakeResult r = Bake(baker, request);
    CheckThicknessEvidence(r);
    const ThicknessRecord& record = r.thickness;
    CHECK(Near(record.box_size, 4.02, 1e-6));
    CHECK(record.max_distance == static_cast<float>(double(0.25f) * record.box_size));
    CHECK(record.min_distance == static_cast<float>(double(1e-4f) * record.box_size));
    CHECK(record.settings.relative_to_bounding_box && !record.settings.normalization);
    using uzp::core::json::Value;
    const uzp::core::json::Object json = ThicknessRecordJson(record);
    CHECK(json.at("MaximizeRange").IsNull() && json.at("value").IsNull() && json.at("range").IsNull());
    CHECK(json.at("NbSecondary") == Value(std::int64_t{8}) && json.at("Distribution") == Value("Cosine"));
    CHECK(json.at("MaxDistanceRelativeScale") == Value(true) && json.at("unit") == Value("centimetre"));
    CHECK(json.at("effective_max_distance") == Value(static_cast<double>(record.max_distance)));
    // The same window in absolute centimetres gives the same rays.
    BakeRequest absolute = ThicknessRequest(fixture.Request(0.07f), 8, record.min_distance, record.max_distance);
    const BakeResult a = Bake(baker, absolute);
    CHECK(a.thickness_ray_class == r.thickness_ray_class && a.thickness_ray_distance == r.thickness_ray_distance);
    // Combined with AO it shares the primary hits and leaves AO's bytes and ray totals alone.
    BakeRequest both = ThicknessRequest(fixture.Request(0.07f), 8, 1e-4f, 1.5f);
    both.usages = {MeshMapUsage::AO, MeshMapUsage::Thickness};
    const BakeResult ao = Bake(baker, fixture.Request(0.07f));
    const BakeResult b = Bake(baker, both);
    const BakeResult t = Bake(baker, ThicknessRequest(fixture.Request(0.07f), 8, 1e-4f, 1.5f));
    CHECK(b.ao_raw == ao.ao_raw && b.ao == ao.ao && b.texel_class == ao.texel_class);
    CHECK(b.rays.escaped == ao.rays.escaped && b.rays.front_hit == ao.rays.front_hit);
    CHECK(b.rays.back_face_hit == ao.rays.back_face_hit && b.rays.self_hit == ao.rays.self_hit);
    CHECK(b.thickness_ray_class == t.thickness_ray_class && b.thickness_ray_distance == t.thickness_ray_distance);
    CHECK(SerializeResult(ao).find("THK1") == std::string::npos && SerializeResult(b).find("THK1") != std::string::npos);
}

void CaseThicknessRefusals() {
    EmbreeBaker baker;
    Bevel fixture;
    for (ThicknessNormalization normalization :
         {ThicknessNormalization::RelativeToRayDistances, ThicknessNormalization::RelativeToMinMax,
          ThicknessNormalization::None}) {
        BakeRequest request = ThicknessRequest(fixture.Request(0.07f), 8, 1e-4f, 1.5f);
        request.thickness.normalization = normalization;
        const std::string message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
        CHECK(Contains(message, "MaximizeRange") && Contains(message, "phase3.4_baker-thickness") &&
              Contains(message, "decision 341"));
    }
    BakeRequest defaults = fixture.Request(0.07f);  // Painter's defaults: Relative to min/max
    defaults.usages = {MeshMapUsage::Thickness};
    std::string message = ExpectThrow<NotYetSupported>([&] { baker.bake(defaults); });
    CHECK(Contains(message, "Relative to min/max (per UV tile)"));
    BakeRequest request = ThicknessRequest(fixture.Request(0.07f), 8, 1e-4f, 1.5f);
    request.detail.subsampling = 2;
    message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    CHECK(Contains(message, "SubSampling") && Contains(message, "phase3.4_baker-thickness"));
    request = ThicknessRequest(fixture.Request(0.07f), 8, 1e-4f, 1.5f);
    request.common.dilation_width = 2;
    message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    CHECK(Contains(message, "DilationWidth") && Contains(message, "phase3.4_baker-thickness"));
    request = ThicknessRequest(fixture.Request(0.07f), 8, 1e-4f, 1.5f);
    request.output_size_log2[0] = request.output_size_log2[1] = 12;  // 2^24 texels x 8 rays
    message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    CHECK(Contains(message, "2^26") && Contains(message, "phase3.4_baker-thickness"));
    request = ThicknessRequest(fixture.Request(0.07f), 8, 1e-4f, 1.5f);
    request.thickness.relative_to_bounding_box = true;
    request.project_bounds = BoundingBox{{-1, -1, -1}, {1, 1, 1}};
    message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });  // no box-size metric
    CHECK(Contains(message, "phase3.5_embree-bakers"));
    request = ThicknessRequest(fixture.Request(0.07f), 0, 1e-4f, 1.5f);
    ExpectThrow<ValueError>([&] { baker.bake(request); });
    request = ThicknessRequest(fixture.Request(0.07f), 8, 1.5f, 1.5f);
    ExpectThrow<ValueError>([&] { baker.bake(request); });
    CHECK(baker.caps().parity_owner_tasks.at(MeshMapUsage::Thickness) == "phase3.4_baker-thickness");
}

void CaseThicknessParameters() {
    // Thickness's values are stored per texture set, saved in bake_settings.per_baker.Thickness and
    // mapped to the request with AO's ray refusals; the baker refuses every normalisation the
    // mapping always sets.
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest base = fixture.Request(0.07f);
    base.usages = {MeshMapUsage::Thickness};
    BakingParameters params("bevelled_cube");
    const auto common = params.common();
    const auto thickness = params.baker(MeshMapUsage::Thickness);
    CHECK(std::get<EnumLabel>(thickness.at("MaximizeRange").value()).label == "Relative to min/max (per UV tile)");
    using Pair = std::pair<std::int64_t, std::int64_t>;
    BakingParameters::set({{common.at("OutputSize"), Pair{base.output_size_log2[0], base.output_size_log2[1]}},
                           {common.at("DilationWidth"), std::int64_t{0}},
                           {common.at("FilterMethod"), EnumLabel{"By mesh name"}},
                           {common.at("MaxHeight"), static_cast<double>(base.detail.max_height)},
                           {common.at("MaxDepth"), static_cast<double>(base.detail.max_depth)},
                           {common.at("RelativeScale"), false}});
    MappedRequest mapped = RequestFromParameters(params, base);
    const ThicknessSettings& painter = mapped.request.thickness;  // Painter's defaults
    CHECK(painter.secondary_rays == 64 && painter.distribution == Distribution::Cosine);
    CHECK(painter.relative_to_bounding_box && painter.max_distance == 0.1f);
    CHECK(painter.normalization == ThicknessNormalization::RelativeToMinMax);
    std::string message = ExpectThrow<NotYetSupported>([&] { baker.bake(mapped.request); });
    CHECK(Contains(message, "phase3.4_baker-thickness"));
    BakingParameters::set({{thickness.at("NbSecondary"), std::int64_t{8}},
                           {thickness.at("MinDistance"), 1e-4},
                           {thickness.at("MaxDistance"), 1.0},
                           {thickness.at("MaxDistanceRelativeScale"), false},
                           {thickness.at("Distribution"), EnumLabel{"Uniform"}},
                           {thickness.at("MaximizeRange"), EnumLabel{"None"}}});
    mapped = RequestFromParameters(params, base);
    CHECK(mapped.request.thickness.normalization == ThicknessNormalization::None);
    ExpectThrow<NotYetSupported>([&] { baker.bake(mapped.request); });
    // The mapped request without its normalisation is the evidence request.
    mapped.request.thickness.normalization = std::nullopt;
    BakeRequest expected = ThicknessRequest(fixture.Request(0.07f), 8, 1e-4f, 1.0f);
    expected.thickness.distribution = Distribution::Uniform;
    CHECK(SerializeResult(Bake(baker, mapped.request)) == SerializeResult(Bake(baker, expected)));
    // AO's refusals hold for Thickness's own Spread and Self occlusion.
    BakingParameters::set({{thickness.at("Spread"), 90.0}});
    message = ExpectThrow<NotYetSupported>([&] { RequestFromParameters(params, base); });
    CHECK(Contains(message, "Spread") && Contains(message, "phase3.4_baker-thickness"));
    BakingParameters::set({{thickness.at("Spread"), 180.0},
                           {thickness.at("FilterMethodSecondary"), EnumLabel{"Only same mesh name"}}});
    message = ExpectThrow<NotYetSupported>([&] { RequestFromParameters(params, base); });
    CHECK(Contains(message, "FilterMethodSecondary") && Contains(message, "phase3.4_baker-thickness"));
    // Saved and loaded with the texture set's other values; a wrong label refuses the whole load.
    const uzp::core::BakeSettings saved = ToBakeSettings(params);
    CHECK(saved.per_baker.at("Thickness").at("NbSecondary") == uzp::core::json::Value(std::int64_t{8}));
    CHECK(saved.per_baker.at("Thickness").at("Distribution") == uzp::core::json::Value("Uniform"));
    BakingParameters loaded("bevelled_cube");
    LoadBakeSettings(loaded, saved);
    CHECK(ToBakeSettings(loaded) == saved);
    uzp::core::BakeSettings wrong = saved;
    wrong.per_baker["Thickness"]["MaximizeRange"] = uzp::core::json::Value("Manual");  // a Height label
    ExpectThrow<ValueError>([&] { LoadBakeSettings(loaded, wrong); });
    CHECK(ToBakeSettings(loaded) == saved);
    // Thickness values are the set's own: no link group (owner task).
    BakingSession session({"a", "b"});
    message = ExpectThrow<NotYetSupported>([&] { session.set_linked_group({"a", "b"}, "a", MeshMapUsage::Thickness); });
    CHECK(Contains(message, "phase3.4_baker-thickness"));
    BakingParameters::set({{session.parameters("a").baker(MeshMapUsage::Thickness).at("NbSecondary"), std::int64_t{4}}});
    CHECK(std::get<std::int64_t>(session.parameters("b").baker(MeshMapUsage::Thickness).at("NbSecondary").value()) == 64);
    CHECK(StoresBakerValues(MeshMapUsage::Thickness) && !StoresBakerValues(MeshMapUsage::Curvature));
}
