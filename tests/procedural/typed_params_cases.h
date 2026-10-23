// Included by procedural_test.cpp inside its test namespace. Authored JSON fixtures only.
int RunTypedParams() {
    namespace json = uzp::core::json;
    const auto parse = [](std::string_view text) { return ParamFromJson(json::Parse(text)); };
    const auto vector = parse("[1,2.5,3]");
    const auto equivalent = parse("[1.0,2.5,3.0]");
    const auto color = parse(R"({"type":"color","working_space":"Linear sRGB","components":[1,2.5,3],"alpha":null})");
    Check(vector && equivalent && color, "documented vector and working-space color forms parse");
    if (!vector || !equivalent || !color) return Finish();
    const Params stored{{"vector", *vector}, {"color", *color}};
    Params copied = stored;
    Check(copied == stored, "typed parameter maps compare copied stored representations");
    std::get<ParamVector>(copied.at("vector")).components[0] = int64_t{2};
    Check(copied != stored, "parameter map equality detects a changed vector component");
    copied = stored;
    std::get<ParamColor>(copied.at("color")).alpha = 1.0;
    Check(copied != stored, "parameter map equality detects changed color alpha");
    Check(ParamJson(*vector) == ParamJson(*equivalent) && ParamJson(*vector) != ParamJson(*color),
          "vector components normalize by value without colliding with colors");
    Check(ParamJson(*parse("true")) == json::Value(1) && ParamJson(1.0) == json::Value(1) &&
              ParamJson(std::string("1")) == json::Value("1"), "legacy scalar encodings stay unchanged");
    const auto large = parse("[9007199254740993,0]");
    const auto rounded = parse("[9007199254740992.0,0.0]");
    Check(large && rounded && ParamJson(*large) != ParamJson(*rounded),
          "vector integer precision is preserved beyond binary64 exact integers");
    for (const char* invalid : {"null", "[]", "[1]", "[1,2,3,4,5]", "[true,0]", "[1,\"2\"]", "[[1,2],0]",
             R"({"type":"color","working_space":"Linear sRGB","components":[1,2,3]})",
             R"({"type":"color","working_space":"","components":[1,2,3],"alpha":null})",
             R"({"type":"color","working_space":"Linear sRGB","components":[1,2],"alpha":null})",
             R"({"type":"color","working_space":"Linear sRGB","components":[1,true,3],"alpha":null})",
             R"({"type":"color","working_space":"Linear sRGB","components":[1,2,3],"alpha":false})",
             R"({"type":"color","working_space":"Linear sRGB","components":[1,2,3],"alpha":null,"extra":0})",
             R"({"type":"vector","working_space":"Linear sRGB","components":[1,2,3],"alpha":null})"}) {
        Check(!parse(invalid), "invalid structured parameter refused", invalid);
    }
    for (size_t count : {size_t{2}, size_t{3}, size_t{4}}) {
        ParamVector values{std::vector<ParamNumber>(count, 0.5)};
        const auto decoded = ParamFromJson(ParamJson(values));
        Check(decoded && ParamJson(*decoded) == ParamJson(values), "each documented vector width round-trips");
    }
    for (ParamValue invalid : {ParamValue{ParamVector{{1.0}}}, ParamValue{ParamVector{{std::nan(""), 0.0}}},
                              ParamValue{ParamColor{"", {0.0, 0.0, 0.0}, {}}},
                              ParamValue{ParamColor{"Linear sRGB", {0.0, 0.0, 0.0}, std::numeric_limits<double>::infinity()}}}) {
        bool refused = false;
        try { (void)ParamJson(invalid); } catch (const uzp::core::ValueError&) { refused = true; }
        Check(refused, "invalid native structured value cannot acquire a snapshot signature");
    }
    auto request = SyntheticRequest();
    const std::string scalarSignature = Signature(request);
    request.params["amount"] = *vector;
    const std::string vectorSignature = Signature(request);
    request.params["amount"] = *equivalent;
    Check(Signature(request) == vectorSignature && vectorSignature != scalarSignature,
          "typed request signatures preserve numeric equivalence and scalar separation");
    request.params["amount"] = *color;
    const std::string colorSignature = Signature(request);
    auto alpha = std::get<ParamColor>(*color);
    alpha.alpha = 1.0;
    request.params["amount"] = alpha;
    const std::string alphaSignature = Signature(request);
    alpha.working_space = "ACEScg";
    request.params["amount"] = alpha;
    Check(colorSignature != vectorSignature && alphaSignature != colorSignature && Signature(request) != alphaSignature,
          "color alpha presence and working space each alter the signature");
    SyntheticExact synthetic;
    auto domain = synthetic.Record().domain;
    request = SyntheticRequest();
    request.params["amount"] = *vector;
    const auto outside = CheckDomain(request, domain);
    Check(outside && outside->field == "params.amount" && outside->reason == kOutsideDomain,
          "structured values cannot enter a scalar certified range");
    domain.parameters["amount"] = ParamRule{std::nullopt, {*equivalent}};
    domain.constraints.clear();
    Check(!CheckDomain(request, domain), "explicit vector domain sets compare normalized complete values");
    request.params["amount"] = *color;
    Check(CheckDomain(request, domain).has_value(), "vector domain sets refuse colors with identical components");
    domain.parameters["amount"] = ParamRule{std::nullopt, {*color}};
    Check(!CheckDomain(request, domain), "explicit color domain sets retain their tagged identity");
    request.params["amount"] = alpha;
    Check(CheckDomain(request, domain).has_value(), "color domain sets refuse changed alpha or working space");
    domain.parameters["amount"] = ParamRule{std::nullopt, {int64_t{9007199254740992}}};
    request.params["amount"] = int64_t{9007199254740993};
    const bool adjacentRefused = CheckDomain(request, domain).has_value();
    request.params["amount"] = 9007199254740992.0;
    const bool integralAccepted = !CheckDomain(request, domain);
    domain.parameters["amount"] = ParamRule{std::nullopt, {int64_t{9007199254740993}}};
    Check(adjacentRefused && integralAccepted && CheckDomain(request, domain).has_value(),
          "scalar set equality retains int64 precision and exact mixed numeric equality");
    domain.parameters["amount"] = ParamRule{std::nullopt, {std::nan("")}};
    request.params["amount"] = std::nan("");
    Check(CheckDomain(request, domain).has_value(), "NaN never equals a scalar set member");
    domain.parameters["amount"] = ParamRule{std::pair{0.0, 0x1p53}, {}};
    request.params["amount"] = int64_t{9007199254740993};
    const auto integerRange = CheckDomain(request, domain);
    Check(integerRange && integerRange->value == "9007199254740993",
          "range refuses the integer above 2^53 without rounding its diagnostic");
    request.params["amount"] = int64_t{9007199254740992};
    Check(!CheckDomain(request, domain), "range accepts its exact positive integer endpoint");
    domain.parameters["amount"] = ParamRule{std::pair{-0x1p53, 0.0}, {}};
    request.params["amount"] = int64_t{-9007199254740993};
    Check(CheckDomain(request, domain).has_value(), "range refuses the integer below negative 2^53");
    domain.parameters["amount"] = ParamRule{std::pair{-0x1p63, 0x1p63}, {}};
    for (const int64_t limit : {std::numeric_limits<int64_t>::min(), std::numeric_limits<int64_t>::max()}) {
        request.params["amount"] = limit;
        Check(!CheckDomain(request, domain), "range handles an exact int64 extreme without unsafe conversion");
    }
    domain.parameters["amount"] = ParamRule{std::pair{-0x1p63 + 1024.0, 0x1p63 - 1024.0}, {}};
    for (const int64_t limit : {std::numeric_limits<int64_t>::min(), std::numeric_limits<int64_t>::max()}) {
        request.params["amount"] = limit;
        Check(CheckDomain(request, domain).has_value(), "narrowed range refuses an int64 extreme");
    }
    domain.parameters["amount"] = ParamRule{std::pair{-0x1p63, 0x1p63}, {}};
    for (const int64_t value : {int64_t{9007199254740993}, int64_t{-9007199254740993}}) {
        request.params["amount"] = value;
        domain.constraints = {LinearConstraint{{{"amount", value > 0 ? 1.0 : -1.0}}, 0x1p53}};
        Check(CheckDomain(request, domain).has_value(), "constraint retains the integer unit beyond signed 2^53");
    }
    request.params["amount"] = std::numeric_limits<int64_t>::max();
    domain.constraints = {LinearConstraint{{{"amount", -1.0}}, -0x1p63}};
    Check(CheckDomain(request, domain).has_value(), "constraint distinguishes INT64_MAX from rounded 2^63");
    request.params["amount"] = std::numeric_limits<int64_t>::min();
    volatile double runtimeCoefficient = -1.0;
    volatile double runtimeMaximum = 0x1p63;
    domain.constraints = {LinearConstraint{{{"amount", runtimeCoefficient}}, runtimeMaximum}};
    const auto minimumConstraint = CheckDomain(request, domain);
    Check(!minimumConstraint, "constraint accepts the exact negated INT64_MIN boundary",
          minimumConstraint ? minimumConstraint->Describe() : "");
    domain.parameters["amount"] = ParamRule{std::pair{0.0, 1e308}, {}};
    request.params["amount"] = 1e308;
    domain.constraints = {LinearConstraint{{{"amount", 2.0}}, 1e308}};
    const auto overflow = CheckDomain(request, domain);
    Check(overflow && overflow->certified.find("exact arithmetic unavailable") != std::string::npos,
          "constraint product overflow refuses instead of treating NaN as a satisfied inequality");
    request.params["amount"] = std::numeric_limits<double>::min();
    domain.constraints = {LinearConstraint{{{"amount", std::numeric_limits<double>::min()}}, 0.0}};
    const auto underflow = CheckDomain(request, domain);
    Check(underflow && underflow->certified.find("exact arithmetic unavailable") != std::string::npos,
          "constraint unrepresentable product tail refuses instead of disappearing into zero");
    request.params["amount"] = std::numeric_limits<double>::denorm_min();
    domain.constraints = {LinearConstraint{{{"amount", 1.0}}, std::numeric_limits<double>::denorm_min()}};
    Check(!CheckDomain(request, domain), "exact representable subnormal product remains admissible");
    request.params["amount"] = 1e308;
    request.params["bias"] = 1e308;
    domain.parameters["bias"] = ParamRule{std::pair{0.0, 1e308}, {}};
    domain.constraints = {LinearConstraint{{{"amount", 1.0}, {"bias", 1.0}}, 1e308}};
    const auto expansionOverflow = CheckDomain(request, domain);
    Check(expansionOverflow && expansionOverflow->certified.find("exact arithmetic unavailable") != std::string::npos,
          "constraint expansion overflow refuses even when each product is finite");
    uzp::core::ProceduralRef ref;
    ref.asset = "uzasset://test-probe/typed@1";
    ref.params = {{"vector", ParamJson(*vector)}, {"color", ParamJson(*color)}, {"enabled", true}};
    UseContext context;
    AssetLibrary library;
    const auto admitted = RequestFor(ref, context, library);
    Check(admitted && ParamJson(admitted->params.at("vector")) == ParamJson(*vector) &&
              ParamJson(admitted->params.at("color")) == ParamJson(*color) &&
              ParamJson(admitted->params.at("enabled")) == json::Value(1),
          "project request admission preserves typed values before backend selection");
    ref.params["vector"] = json::Array{1};
    const auto malformed = RequestFor(ref, context, library);
    Check(!malformed && malformed.error().field == "params.vector", "malformed project parameter refuses at admission");
    return Finish();
}
