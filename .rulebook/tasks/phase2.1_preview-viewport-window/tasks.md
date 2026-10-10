## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand

## 2. Implementation
- [ ] 2.1 Environment precomputation for split-sum IBL (prefiltered radiance, BRDF lookup) and SH irradiance from the project environment
- [ ] 2.2 Forward `painter_viewport` pass with GGX/Smith/Schlick/Burley lobes, the project's material parameters and MikkTSpace normal mapping
- [ ] 2.3 Display transform shared with captures: Legacy `Linear`, Legacy `ACES`, OCIO with pinned config and view; explicit error for unsupported configurations
- [ ] 2.4 Preview thread reading the double-buffered last evaluation without blocking the engine thread
- [ ] 2.5 Preview window (`--preview <file.uzp>` and attached mode): read-only, orbit camera only, low frame rate, `painter_iray` panel stating the mode is unavailable until a capture exists
- [ ] 2.6 Viewport regression goldens on UzmiGames-authored sphere, plane and bevelled-cube fixtures, keyed by build, adapter and driver

## 3. Tests
- [ ] 3.1 Viewport regression goldens exact for a fixed build, adapter and driver on the self-hosted GPU runner
- [ ] 3.2 Preview-thread stall hook: evaluation and export complete with unchanged results and no wait on the preview thread
- [ ] 3.3 Window opened, minimised, resized and closed during evaluation: no effect on evaluation results or revision order
- [ ] 3.4 Unsupported display configuration (including ACE mode) fails before rendering

## 4. Acceptance
- [ ] 4.1 Every §3 test green; results attached to `phase2.3_realtime-preview`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
