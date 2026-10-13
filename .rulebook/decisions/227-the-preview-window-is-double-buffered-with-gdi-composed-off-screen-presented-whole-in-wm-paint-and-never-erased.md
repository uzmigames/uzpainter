# 227. The preview window is double buffered with GDI: composed off screen, presented whole in WM_PAINT, never erased

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase2.1_preview-viewport-window, phase2.3_realtime-preview

## Context

The owner reported that the preview window (`UzPainter.exe --preview`, or a worker with `--preview`) flickers, and asked for double buffering. Real images have reached the window only since decision 212 gave it a default environment, which is why this showed up now.

The image path has no swap chain. Each render goes to new offscreen textures in one dispatch inside `SubmitAndWait`. Both targets are read back in full, converted to 8-bit BGRA on the CPU, and swapped into `pixels` only after the whole readback succeeds, on the thread that draws. No partial GPU frame ever reaches the window. The flicker came from how GDI drew the window:

1. **The class brush erased the window to black.** The vendored window class (`thirdparty/uzengine-render-core/platform/windows/platform_window.cpp`, verbatim in `MANIFEST.json`) registers `BLACK_BRUSH` with `CS_HREDRAW | CS_VREDRAW`. Its window procedure handles neither WM_PAINT nor WM_ERASEBKGND. On every invalidation (show, resize, restore, a DPI change), `DefWindowProc` filled the client area with black. The preview loop drew again only on its next pass. After a resize, that pass first ran a blocking render, so the black stayed up for a whole render. During a live border drag the loop waits inside Windows' modal size loop and never draws, so the window stayed black for the whole drag.
2. **The window had no back buffer.** `paint()` ran on every loop pass, about 66 times a second, whether or not anything had changed. It drew straight onto `GetDC(hwnd)`: it cleared the panel with `FillRect`, then drew its text with separate `DrawTextA` calls. Without an image it also cleared the view, then drew the message. The compositor can compose a frame between the clear and the text, so the text blinked.

The model panel's votes (one round):

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 The root causes are at the GDI level (the class-brush erase, clear-then-draw on the visible window, no repaint during the modal size loop), not GPU presentation | AGREE | AGREE | AGREE |
| C2 The fix is GDI double buffering: a persistent memory bitmap the size of the client area, composed only on change and presented by one BitBlt in WM_PAINT; the window subclassed to answer WM_ERASEBKGND without erasing and to recompose at a new size; the class brush set to NULL; no per-pass repaint; the vendored file untouched | PARTLY | AGREE | AGREE |
| C3 A flip-model DXGI swap chain is not warranted here | AGREE | AGREE | AGREE |
| C4 The regression test: a NULL class brush, a `presents` counter that stays put while idle and grows on a repaint, and a sampler paced by `DwmFlush` that fails on an erased view or a panel without its text | PARTLY | AGREE | AGREE |

Refinements adopted:

- C2 (GPT): the subclass is removed and its window property dropped before the window is destroyed. The bitmap is allocated, and checked, before it is selected. The frame covers the whole client area, so not erasing is safe.
- C4 (GPT): the class brush, the idle `presents` count and the repaint are the deterministic checks. The screen sampler is the integration check. It discards a sample whose client rectangle moved while it was taken, and pauses across the compositor's minimise and restore animations.

## Decision

1. **Double buffering with GDI** (`src/preview/preview.cpp`, `BackBuffer`).
   - Every frame is composed whole into a memory DC that holds a bitmap the size of the client area. A frame is the image stretched to the view (HALFTONE, with the brush origin set), or the message, then the panel and its text.
   - A frame is composed only when something it shows has changed: a new image or message, a newly taken frame's revision, or another client size. Composing a frame invalidates the window. WM_PAINT then presents the frame with one BitBlt (`BeginPaint`/`EndPaint`).
   - The loop no longer draws on every pass. An unchanged window is drawn again only when Windows asks for a repaint.
   - When WM_PAINT finds a client size the frame was not composed at, it composes the last image again first, stretched to the new size. This happens on a resize, and during a live drag while the loop waits in the modal size loop. The window keeps showing the last complete frame until the new render replaces it.
   - WM_SIZE presents a frame of the new size inside the size change. The loop waits for the next message (`MsgWaitForMultipleObjectsEx`, at most 15 ms) instead of sleeping 15 ms, so a resize sent from another thread is answered at once.
     - Without these two, the compositor showed the new size holding the old frame for up to one sleep. A sampler run counted this on 9 of 20 resizes.
     - With them, it counted 0 failures in 661 samples over 30 resizes and 30 repaints.
     - The build before this decision failed 86 of 225 samples over 10 resizes: 82 erased views and 4 panels without their text.
2. **Nothing erases the window.** Before the window is first shown, its class background brush is set to NULL (`SetClassLongPtrW`). The window procedure is subclassed with `SetWindowLongPtrW(GWLP_WNDPROC)` and `CallWindowProcW`; `SetWindowSubclass` is not used because comctl32 is not linked. The subclass answers WM_ERASEBKGND without erasing and handles WM_PAINT. The back buffer's pointer is kept in a window property, because the vendored procedure uses `GWLP_USERDATA` itself. The vendored file is not modified.
3. **No swap chain.** The image is read back to the CPU anyway, both for this window and for the captures. Presenting it through a flip-model DXGI swap chain would mean:
   - uploading the image again, or adding a pass into the back buffer;
   - presenting and resizing on the engine thread;
   - moving the GDI panel to a child window, or drawing its text on the GPU;
   - a Vulkan counterpart.
   None of this removes the GDI erase of the window, and it brings no visible gain for a read-only preview that renders at most 5 frames a second. The capture path is unchanged, so the `painter_viewport` goldens stay byte-identical.
4. **Instrumentation.** `PreviewStatus::presents` counts BitBlts of the back buffer. The worker's `preview_status` returns it as `presents`.

## Consequences

- `tests/preview/test_preview_window.py::test_window_presents_only_complete_frames` checks the window on the OCIO fixture (it needs the GPU and a desktop session):
  - the class brush is NULL;
  - `presents` does not change over 1 s while the window is idle, and grows after `RedrawWindow`;
  - a sampler paced by `DwmFlush` finds no erased view and no panel without its text. It runs through five resizes, a minimise and restore, ten `RedrawWindow` calls and a new evaluation.
- Errors are still shown in place of the image, as `preview.h` documents.
