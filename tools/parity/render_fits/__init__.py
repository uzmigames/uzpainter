"""Render feasibility prototype and first Iray lobe fits (task `phase0.8_render-reference-fits`).

`docs/architecture/07-preview-and-render-parity.md` §3-§4 under the fixed render pipeline
(decisions 038, 042, 046): a CPU path-tracing prototype written from public sources only
(not shipped, never Tier 3 evidence), black-box fits of its lobe variants against the admitted
Iray references, the transport evidence, UzPainter's term (c) and the noise-floor report.
Report: `parity/reports/phase0/iray-noise-floor.md`; fits: `parity/semantics/iray.json`.
"""
