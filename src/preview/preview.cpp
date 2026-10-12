#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "preview/preview.h"

#include "evaluator/arith.h"
#include "evaluator/diagnostics.h"
#include "platform_window.h"
#include "input.h"
#include "python/display.h"
#include "render/engine_thread.h"

#include <windows.h>

#include <algorithm>
#include <cmath>
#include <unordered_map>
#include <vector>

namespace uzp::preview {

namespace {

/// The panel at the window's right edge, in pixels.
constexpr int kPanelWidth = 300;
/// The largest side the viewport renders at; the window stretches the image beyond it.
constexpr uint32_t kMaxRenderSide = 1024;

/// The first `components` components of a raster with `available` per texel.
std::optional<MaterialMap> Components(uint32_t width, uint32_t height, uint32_t available,
                                      const std::vector<float>& values, uint32_t components) {
    if (width == 0 || height == 0 || available == 0) return std::nullopt;
    MaterialMap map{width, height, components, {}};
    map.values.resize(size_t{width} * height * components);
    for (size_t i = 0; i < size_t{width} * height; ++i) {
        for (uint32_t c = 0; c < components; ++c) {
            map.values[i * components + c] = values[i * available + std::min(c, available - 1)];
        }
    }
    return map;
}

std::optional<MaterialMap> MapOfEvaluated(const EvaluatedMap& evaluated, uint32_t components) {
    if (const auto* channel = std::get_if<std::shared_ptr<const evaluator::ChannelResult>>(&evaluated)) {
        if (!*channel) return std::nullopt;
        const evaluator::DiagnosticMap map = evaluator::MapOf(**channel);
        return Components(map.width, map.height, map.components, map.values, components);
    }
    const auto& normal = std::get<std::shared_ptr<const evaluator::VirtualNormalResult>>(evaluated);
    if (!normal) return std::nullopt;
    return Components(normal->width, normal->height, 3, normal->texels, components);
}

void FillText(HDC dc, RECT rect, const std::string& text, COLORREF colour) {
    SetTextColor(dc, colour);
    DrawTextA(dc, text.c_str(), static_cast<int>(text.size()), &rect, DT_LEFT | DT_TOP | DT_WORDBREAK);
}

}  // namespace

std::optional<MaterialSlot> SlotOf(core::ChannelType channel) {
    using core::ChannelType;
    switch (channel) {
        case ChannelType::BaseColor: return MaterialSlot::BaseColor;
        case ChannelType::BaseMetalness:
        case ChannelType::Metallic: return MaterialSlot::Metalness;
        case ChannelType::SpecularRoughness:
        case ChannelType::Roughness: return MaterialSlot::Roughness;
        case ChannelType::Normal: return MaterialSlot::Normal;
        default: return std::nullopt;
    }
}

void PreviewFeed::Update(std::int64_t revision, std::shared_ptr<const core::Project> project,
                         std::shared_ptr<const mesh::TexturingMesh> mesh, const ResourceReader& read) {
    m_state.revision = revision;
    const std::string hash = project ? project->display.environment.resource.value_or("") : "";
    if (hash != m_state.environmentHash) {
        m_state.environmentHash = hash;
        m_state.environmentBytes.reset();
        m_state.environmentError.clear();
        if (!hash.empty()) {
            std::optional<std::string> bytes = read(hash);
            if (bytes) {
                m_state.environmentBytes = std::make_shared<const std::string>(std::move(*bytes));
            } else {
                m_state.environmentError = "missing environment: the project holds no bytes for sha256 " + hash +
                                           " (RES-03: no substitute)";
            }
        }
    }
    m_state.project = std::move(project);
    if (mesh) m_state.mesh = std::move(mesh);
}

void PreviewFeed::Record(core::Id set, MaterialSlot slot, EvaluatedMap map) {
    m_state.maps[{set, slot}] = std::move(map);
}

void PreviewFeed::Publish() { m_frames.Publish(std::make_shared<const PreviewFrame>(m_state)); }

std::vector<MaterialInputs> MaterialsOf(const PreviewFrame& frame) {
    std::vector<MaterialInputs> materials;
    if (!frame.project) return materials;
    for (const core::TextureSet& set : frame.project->texture_sets) {
        MaterialInputs inputs;
        const auto find = [&](MaterialSlot slot) -> const EvaluatedMap* {
            const auto it = frame.maps.find({set.id, slot});
            return it == frame.maps.end() ? nullptr : &it->second;
        };
        if (const EvaluatedMap* m = find(MaterialSlot::BaseColor)) inputs.baseColor = MapOfEvaluated(*m, 3);
        if (const EvaluatedMap* m = find(MaterialSlot::Metalness)) inputs.metalness = MapOfEvaluated(*m, 1);
        if (const EvaluatedMap* m = find(MaterialSlot::Roughness)) inputs.roughness = MapOfEvaluated(*m, 1);
        if (const EvaluatedMap* m = find(MaterialSlot::Normal)) inputs.normal = MapOfEvaluated(*m, 3);
        materials.push_back(std::move(inputs));
    }
    return materials;
}

PreviewHost::PreviewHost(PreviewOptions options, std::shared_ptr<PreviewFeed> feed)
    : m_options(std::move(options)), m_feed(std::move(feed)) {
    m_thread = std::thread([this] { Run(); });
}

PreviewHost::~PreviewHost() {
    m_stop = true;
    m_stall = false;
    if (m_thread.joinable()) m_thread.join();
}

void PreviewHost::Stall(bool stalled) { m_stall = stalled; }

PreviewStatus PreviewHost::Status() const {
    PreviewStatus status;
    status.windowOpen = m_windowOpen;
    status.stalled = m_stalled;
    status.framesPublished = m_feed->Frames().Published();
    status.framesTaken = m_taken;
    status.framesRendered = m_rendered;
    status.revisionShown = m_revisionShown;
    std::lock_guard lock(m_errorMutex);
    status.lastError = m_lastError;
    return status;
}

void PreviewHost::WaitClosed() {
    if (m_thread.joinable()) m_thread.join();
}

void PreviewHost::Run() {
    const auto setError = [this](std::string error) {
        std::lock_guard lock(m_errorMutex);
        m_lastError = std::move(error);
    };

    render::EngineOptions engineOptions;
    engineOptions.device.backend = m_options.backend;
    engineOptions.requestDeadline = m_options.deadline;
    render::Engine engine(engineOptions);

    uz::InputSystem input;
    input.Init();
    uz::PlatformWindow window;
    window.SetInputSystem(&input);
    uz::WindowDesc desc;
    desc.title = m_options.title.c_str();
    desc.width = 960;
    desc.height = 600;
    if (!window.Create(desc)) {
        setError(kWindowNotCreated);
        engine.Stop();
        return;
    }
    window.Show();
    m_windowOpen = true;
    HWND hwnd = static_cast<HWND>(window.GetNativeHandle());

    std::shared_ptr<const PreviewFrame> current;
    std::shared_ptr<const PreviewFrame> sceneOf;  // the frame `scene` was built from
    ViewportScene scene;
    std::unordered_map<std::string, std::shared_ptr<const EnvironmentLighting>> lightingCache;
    std::shared_ptr<const mesh::TexturingMesh> cameraMesh;
    OrbitCamera camera;
    std::string message = "waiting for the first evaluation";
    std::vector<uint8_t> pixels;  // BGRA, rows top first
    uint32_t imageWidth = 0;
    uint32_t imageHeight = 0;
    bool dirty = true;
    auto lastRender = std::chrono::steady_clock::now() - m_options.period;

    const auto prepare = [&]() -> std::optional<std::string> {
        if (!current || !current->project) return std::string("waiting for the first evaluation");
        if (sceneOf == current) return std::nullopt;
        const core::Project& project = *current->project;
        ViewportScene next;
        // The display state of the display presets (src/python/display.h, decision 132): its view,
        // its config pin and the active preset's clear colour.
        const core::json::Object preset = python::display::PresetOf(project);
        std::string view(kDefaultSrgbView);
        std::string displayHash;
        if (const auto display = preset.find("display");
            display != preset.end() && display->second.IsObject()) {
            const core::json::Object& d = std::get<core::json::Object>(display->second.data);
            if (const auto it = d.find("view"); it != d.end() && it->second.IsString()) {
                view = std::get<std::string>(it->second.data);
            }
            if (const auto it = d.find("config_sha256"); it != d.end() && it->second.IsString()) {
                displayHash = std::get<std::string>(it->second.data);
            }
        }
        next.display = ConfigurationOf(project, view);
        if (next.display.mode == kOcioMode && next.display.configHash.empty()) next.display.configHash = displayHash;
        if (const auto background = preset.find("background");
            background != preset.end() && background->second.IsObject()) {
            const core::json::Object& b = std::get<core::json::Object>(background->second.data);
            if (const auto it = b.find("srgb8"); it != b.end() && it->second.IsArray() &&
                                                 std::get<core::json::Array>(it->second.data).size() == 3) {
                const core::json::Array& rgb = std::get<core::json::Array>(it->second.data);
                for (size_t c = 0; c < 3; ++c) {
                    if (rgb[c].IsInt()) {
                        next.background[c] = static_cast<float>(
                            evaluator::arith::SrgbDecode(static_cast<double>(std::get<std::int64_t>(rgb[c].data)) / 255.0));
                    }
                }
            }
        }
        if (std::optional<std::string> unsupported = UnsupportedConfiguration(next.display)) return unsupported;
        if (!current->mesh) return std::string("the evaluation carries no mesh (the project has none)");
        if (!current->environmentError.empty()) return current->environmentError;
        if (current->environmentHash.empty()) {
            return std::string("the project names no environment (RES-03: no substitute)");
        }
        std::shared_ptr<const EnvironmentLighting>& lighting = lightingCache[current->environmentHash];
        if (!lighting) {
            std::expected<EnvironmentImage, std::string> image = DecodeEnvironment(*current->environmentBytes);
            if (!image) {
                lightingCache.erase(current->environmentHash);
                return image.error();
            }
            lighting = std::make_shared<const EnvironmentLighting>(PrecomputeLighting(*image));
        }
        next.mesh = current->mesh;
        next.materials = MaterialsOf(*current);
        next.lighting = lighting;
        next.environmentRotationDegrees = project.display.environment.rotation;
        next.environmentExposure = project.display.environment.exposure;
        scene = std::move(next);
        sceneOf = current;
        if (cameraMesh != scene.mesh) {
            camera = FitCamera(*scene.mesh);
            cameraMesh = scene.mesh;
        }
        return std::nullopt;
    };

    const auto renderFrame = [&]() {
        RECT client{};
        GetClientRect(hwnd, &client);
        const int viewWidth = std::max(1, static_cast<int>(client.right) - kPanelWidth);
        const int viewHeight = std::max(1, static_cast<int>(client.bottom));
        if (std::optional<std::string> problem = prepare()) {
            message = *problem;
            pixels.clear();
            imageWidth = imageHeight = 0;
            if (current) setError(message);
            return;
        }
        const double scale = std::min(1.0, static_cast<double>(kMaxRenderSide) / std::max(viewWidth, viewHeight));
        const uint32_t width = std::max(1u, static_cast<uint32_t>(viewWidth * scale));
        const uint32_t height = std::max(1u, static_cast<uint32_t>(viewHeight * scale));
        render::Result<ViewportImage> image =
            engine
                .Submit(current,
                        [&](render::EngineContext& context, const PreviewFrame&) {
                            return RenderViewport(context, scene, camera, width, height);
                        })
                .get();
        if (!image) {
            message = image.error().Describe();
            pixels.clear();
            imageWidth = imageHeight = 0;
            setError(message);
            return;
        }
        imageWidth = image->width;
        imageHeight = image->height;
        pixels.resize(size_t{imageWidth} * imageHeight * 4);
        for (size_t i = 0; i < size_t{imageWidth} * imageHeight; ++i) {
            pixels[i * 4 + 0] = DisplayCode8(image->display[i * 4 + 2]);
            pixels[i * 4 + 1] = DisplayCode8(image->display[i * 4 + 1]);
            pixels[i * 4 + 2] = DisplayCode8(image->display[i * 4 + 0]);
            pixels[i * 4 + 3] = 255;
        }
        message.clear();
        setError("");
        ++m_rendered;
        m_revisionShown = current->revision;
    };

    const auto paint = [&]() {
        RECT client{};
        GetClientRect(hwnd, &client);
        const int viewWidth = std::max(1, static_cast<int>(client.right) - kPanelWidth);
        HDC dc = GetDC(hwnd);
        if (!dc) return;
        RECT view{0, 0, viewWidth, client.bottom};
        if (!pixels.empty()) {
            BITMAPINFO info{};
            info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
            info.bmiHeader.biWidth = static_cast<LONG>(imageWidth);
            info.bmiHeader.biHeight = -static_cast<LONG>(imageHeight);  // rows top first
            info.bmiHeader.biPlanes = 1;
            info.bmiHeader.biBitCount = 32;
            info.bmiHeader.biCompression = BI_RGB;
            SetStretchBltMode(dc, HALFTONE);
            StretchDIBits(dc, 0, 0, viewWidth, client.bottom, 0, 0, static_cast<int>(imageWidth),
                          static_cast<int>(imageHeight), pixels.data(), &info, DIB_RGB_COLORS, SRCCOPY);
        } else {
            HBRUSH brush = CreateSolidBrush(RGB(32, 32, 32));
            FillRect(dc, &view, brush);
            DeleteObject(brush);
            SetBkMode(dc, TRANSPARENT);
            RECT text{16, 16, viewWidth - 16, client.bottom - 16};
            FillText(dc, text, message, RGB(230, 160, 120));
        }
        RECT panel{viewWidth, 0, client.right, client.bottom};
        HBRUSH brush = CreateSolidBrush(RGB(24, 24, 28));
        FillRect(dc, &panel, brush);
        DeleteObject(brush);
        SetBkMode(dc, TRANSPARENT);
        const std::string status =
            std::string("painter_viewport - read-only preview, not parity evidence (decision 018)\n\n") +
            "display: OCIO, Painter's substance config, Default - sRGB (decision 042)\n\n" +
            (current ? "revision " + std::to_string(current->revision) : std::string("no evaluation yet")) +
            "\n\nleft drag: orbit    wheel: zoom\n\n";
        FillText(dc, RECT{viewWidth + 12, 12, client.right - 12, client.bottom / 2}, status, RGB(200, 200, 200));
        FillText(dc, RECT{viewWidth + 12, client.bottom / 2, client.right - 12, client.bottom - 12}, kIrayUnavailable,
                 RGB(220, 190, 90));
        ReleaseDC(hwnd, dc);
    };

    while (!m_stop && window.PumpMessages()) {
        input.PrepareFrame();
        if (std::optional<std::shared_ptr<const PreviewFrame>> taken = m_feed->Frames().Take()) {
            current = std::move(*taken);
            ++m_taken;
            dirty = true;
        }
        // Test hook (item 3.2): the thread blocks here, holding `current`.
        while (m_stall && !m_stop) {
            m_stalled = true;
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
        m_stalled = false;
        if (input.IsMouseDown(uz::MouseButton::Left) && (input.GetMouseDeltaX() != 0.0f || input.GetMouseDeltaY() != 0.0f)) {
            camera.yawDegrees -= input.GetMouseDeltaX() * 0.4;
            camera.pitchDegrees = std::clamp(camera.pitchDegrees + input.GetMouseDeltaY() * 0.4, -89.0, 89.0);
            dirty = true;
        }
        if (input.GetScrollDelta() != 0.0f) {
            camera.distance *= std::pow(0.9, static_cast<double>(input.GetScrollDelta()));
            dirty = true;
        }
        input.EndFrame();
        if (window.WasResized()) {
            window.ClearResizedFlag();
            dirty = true;
        }
        const auto now = std::chrono::steady_clock::now();
        if (!window.IsMinimized()) {
            if (dirty && now - lastRender >= m_options.period) {
                renderFrame();
                dirty = false;
                lastRender = now;
            }
            paint();
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(15));
    }
    m_windowOpen = false;
    window.Destroy();
    input.Shutdown();
    engine.Stop();
}

}  // namespace uzp::preview
