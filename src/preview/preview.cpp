#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "preview/preview.h"

#include "platform_window.h"
#include "input.h"
#include "render/engine_thread.h"

#include <windows.h>

#include <algorithm>
#include <cmath>
#include <vector>

namespace uzp::preview {

namespace {

/// The panel at the window's right edge, in pixels.
constexpr int kPanelWidth = 300;
/// The largest side the viewport renders at; the window stretches the image beyond it.
constexpr uint32_t kMaxRenderSide = 1024;
/// The window property that holds its `BackBuffer` (the vendored window procedure keeps
/// `GWLP_USERDATA` for itself).
constexpr wchar_t kBackBufferProperty[] = L"UzPainterPreviewBackBuffer";

void FillText(HDC dc, RECT rect, const std::string& text, COLORREF colour) {
    SetTextColor(dc, colour);
    DrawTextA(dc, text.c_str(), static_cast<int>(text.size()), &rect, DT_LEFT | DT_TOP | DT_WORDBREAK);
}

/// The window's back buffer (double buffering, decision 227). A whole frame (the image or the
/// message, then the panel and its text) is composed off screen into a bitmap the size of the
/// client area, and WM_PAINT presents it with one BitBlt, so the window never shows a cleared or
/// half-drawn frame. Nothing erases the window: the vendored class's black background brush is
/// removed and WM_ERASEBKGND is answered without erasing. The vendored window procedure is
/// subclassed, not edited (it is verbatim, thirdparty/uzengine-render-core/MANIFEST.json). Every
/// call runs on the window's thread.
class BackBuffer {
public:
    /// Draws a whole frame of `width` x `height` into `dc`.
    using Composer = std::function<void(HDC dc, int width, int height)>;

    BackBuffer(HWND hwnd, Composer compose, std::atomic<std::uint64_t>& presents)
        : m_hwnd(hwnd), m_compose(std::move(compose)), m_presents(presents), m_dc(CreateCompatibleDC(nullptr)) {
        SetClassLongPtrW(hwnd, GCLP_HBRBACKGROUND, 0);
        SetPropW(hwnd, kBackBufferProperty, this);
        m_original = reinterpret_cast<WNDPROC>(
            SetWindowLongPtrW(hwnd, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(&BackBuffer::Procedure)));
    }

    ~BackBuffer() {
        SetWindowLongPtrW(m_hwnd, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(m_original));
        RemovePropW(m_hwnd, kBackBufferProperty);
        if (m_dc) {
            if (m_bitmap) SelectObject(m_dc, m_initialBitmap);
            DeleteDC(m_dc);
        }
        if (m_bitmap) DeleteObject(m_bitmap);
    }

    BackBuffer(const BackBuffer&) = delete;
    BackBuffer& operator=(const BackBuffer&) = delete;

    /// Composes a new frame at the client size and presents it; nothing while the client area is
    /// empty (minimised).
    void Refresh() {
        RECT client{};
        GetClientRect(m_hwnd, &client);
        if (!Compose(client.right, client.bottom)) return;
        InvalidateRect(m_hwnd, nullptr, FALSE);
        UpdateWindow(m_hwnd);
    }

private:
    static LRESULT CALLBACK Procedure(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
        auto* self = static_cast<BackBuffer*>(GetPropW(hwnd, kBackBufferProperty));
        switch (message) {
            case WM_ERASEBKGND: return 1;  // the frame covers the whole client area
            case WM_PAINT: self->Present(); return 0;
            case WM_SIZE: {
                const LRESULT result = CallWindowProcW(self->m_original, hwnd, message, wparam, lparam);
                // Presented inside the size change, so the compositor never shows the new size
                // holding the old frame.
                if (wparam != SIZE_MINIMIZED) RedrawWindow(hwnd, nullptr, nullptr, RDW_INVALIDATE | RDW_UPDATENOW);
                return result;
            }
            default: return CallWindowProcW(self->m_original, hwnd, message, wparam, lparam);
        }
    }

    /// Composes a frame of `width` x `height`; false for an empty client area.
    bool Compose(int width, int height) {
        if (!m_dc || width <= 0 || height <= 0) return false;
        if (width != m_width || height != m_height) {
            HDC window = GetDC(m_hwnd);
            if (!window) return false;
            HBITMAP bitmap = CreateCompatibleBitmap(window, width, height);
            ReleaseDC(m_hwnd, window);
            if (!bitmap) return false;
            HGDIOBJ previous = SelectObject(m_dc, bitmap);
            if (m_bitmap) {
                DeleteObject(m_bitmap);
            } else {
                m_initialBitmap = previous;
            }
            m_bitmap = bitmap;
            m_width = width;
            m_height = height;
        }
        m_compose(m_dc, width, height);
        return true;
    }

    /// WM_PAINT: one BitBlt of the whole frame. At a client size the frame was not composed at (a
    /// resize, also a live one while the preview loop waits inside the modal size loop) the last
    /// image is composed again first, stretched, so the window never shows an erase.
    void Present() {
        PAINTSTRUCT paint{};
        HDC dc = BeginPaint(m_hwnd, &paint);
        RECT client{};
        GetClientRect(m_hwnd, &client);
        if (dc && ((client.right == m_width && client.bottom == m_height && m_bitmap) ||
                   Compose(client.right, client.bottom))) {
            BitBlt(dc, 0, 0, m_width, m_height, m_dc, 0, 0, SRCCOPY);
            ++m_presents;
        }
        EndPaint(m_hwnd, &paint);
    }

    HWND m_hwnd;
    Composer m_compose;
    std::atomic<std::uint64_t>& m_presents;
    WNDPROC m_original = nullptr;
    HDC m_dc;
    HBITMAP m_bitmap = nullptr;
    HGDIOBJ m_initialBitmap = nullptr;
    int m_width = 0;
    int m_height = 0;
};

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
    // A project that names no environment is lit by the installation's default (decision 212).
    const std::string named = project ? project->display.environment.resource.value_or("") : "";
    const bool isDefault = project && named.empty();
    const std::string hash = isDefault ? std::string(kDefaultEnvironmentSha256) : named;
    if (hash != m_state.environmentHash || isDefault != m_state.environmentDefault) {
        m_state.environmentHash = hash;
        m_state.environmentDefault = isDefault;
        m_state.environmentBytes.reset();
        m_state.environmentError.clear();
        if (isDefault) {
            std::expected<std::shared_ptr<const std::string>, std::string> shipped = DefaultEnvironment();
            if (shipped) {
                m_state.environmentBytes = *shipped;
            } else {
                m_state.environmentError = shipped.error();
            }
        } else if (!hash.empty()) {
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
    status.presents = m_presents;
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
    HWND hwnd = static_cast<HWND>(window.GetNativeHandle());

    std::shared_ptr<const PreviewFrame> current;
    std::shared_ptr<const PreviewFrame> sceneOf;  // the frame `scene` was built from
    ViewportScene scene;
    LightingCache lightingCache;
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
        std::expected<ViewportScene, std::string> next = SceneOf(*current, lightingCache);
        if (!next) return next.error();
        scene = std::move(*next);
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

    // One whole frame of the window, drawn into the back buffer.
    const auto compose = [&](HDC dc, int width, int height) {
        const int viewWidth = std::max(1, width - kPanelWidth);
        RECT view{0, 0, viewWidth, height};
        if (!pixels.empty()) {
            BITMAPINFO info{};
            info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
            info.bmiHeader.biWidth = static_cast<LONG>(imageWidth);
            info.bmiHeader.biHeight = -static_cast<LONG>(imageHeight);  // rows top first
            info.bmiHeader.biPlanes = 1;
            info.bmiHeader.biBitCount = 32;
            info.bmiHeader.biCompression = BI_RGB;
            SetStretchBltMode(dc, HALFTONE);
            SetBrushOrgEx(dc, 0, 0, nullptr);  // required after selecting HALFTONE
            StretchDIBits(dc, 0, 0, viewWidth, height, 0, 0, static_cast<int>(imageWidth),
                          static_cast<int>(imageHeight), pixels.data(), &info, DIB_RGB_COLORS, SRCCOPY);
        } else {
            HBRUSH brush = CreateSolidBrush(RGB(32, 32, 32));
            FillRect(dc, &view, brush);
            DeleteObject(brush);
            SetBkMode(dc, TRANSPARENT);
            RECT text{16, 16, viewWidth - 16, height - 16};
            FillText(dc, text, message, RGB(230, 160, 120));
        }
        RECT panel{viewWidth, 0, width, height};
        HBRUSH brush = CreateSolidBrush(RGB(24, 24, 28));
        FillRect(dc, &panel, brush);
        DeleteObject(brush);
        SetBkMode(dc, TRANSPARENT);
        const std::string status =
            std::string("painter_viewport - read-only preview, not parity evidence (decision 018)\n\n") +
            "display: OCIO, Painter's substance config, Default - sRGB (decision 042)\n\n" +
            (current ? "revision " + std::to_string(current->revision) : std::string("no evaluation yet")) +
            "\n\nleft drag: orbit    wheel: zoom\n\n";
        FillText(dc, RECT{viewWidth + 12, 12, width - 12, height / 2}, status, RGB(200, 200, 200));
        FillText(dc, RECT{viewWidth + 12, height / 2, width - 12, height - 12}, kIrayUnavailable, RGB(220, 190, 90));
    };

    // Subclassed before the window is first shown, so no frame of it is ever erased.
    std::optional<BackBuffer> backBuffer;
    backBuffer.emplace(hwnd, compose, m_presents);
    bool composed = false;  // the back buffer holds the frame of the current state
    window.Show();
    m_windowOpen = true;

    while (!m_stop && window.PumpMessages()) {
        input.PrepareFrame();
        if (std::optional<std::shared_ptr<const PreviewFrame>> taken = m_feed->Frames().Take()) {
            current = std::move(*taken);
            ++m_taken;
            dirty = true;
            composed = false;  // the panel names the frame's revision
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
                composed = false;
            }
            // Only a changed frame is composed and presented; WM_PAINT presents it again whenever
            // Windows asks.
            if (!composed) {
                backBuffer->Refresh();
                composed = true;
            }
        }
        // At most 15 ms until the next pass, and none once a message arrives: a resize sent from
        // another thread is answered, and painted, at once.
        MsgWaitForMultipleObjectsEx(0, nullptr, 15, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
    }
    m_windowOpen = false;
    backBuffer.reset();
    window.Destroy();
    input.Shutdown();
    engine.Stop();
}

}  // namespace uzp::preview
