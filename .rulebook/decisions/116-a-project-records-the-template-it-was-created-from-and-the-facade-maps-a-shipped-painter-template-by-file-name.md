# 116. A project records the template it was created from, and the facade maps a shipped Painter template by its file name

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.24_python-api-facade, phase1.25_pilot-wand, phase1.20_pyapi-facade, phase1.21_pyapi-dispatcher-lifecycle, phase1.8_project-store, phase1.18_export-engine, phase1.14_compositor-core, phase2.6_mcp-typed-tool-families

## Context

Decision 110 left `project.create(template_file_path=...)` raising `NotYetSupported`, owned by phase1.24. Its reason: a UzPainter project did not record its template, so a non-default template would export with the default template's base values.

Measured facts:

- **Authored templates.** UzPainter ships 26 templates and "default" (`assets/templates/*.json`). Each names the shipped Painter file it reproduces, for example `painter_template: "templates/Blender.spt"`.
  - The channel sets and formats are checked against the private golden `defaults-templates/project-templates`. In it, Painter creates one project per shipped template through `project.create(template_file_path=...)`, both recordings.
  - The base values are checked against the `base-values-<template>` goldens by the evaluator tests.
- **The base values were never read.** The evaluator, the export plan and the diagnostics take a template id, and every caller passed "default".
- **Default resolution.** The template capture shows that a template also sets the texture set resolution when the settings give none: 2048 for Dota 2, both Maxwell templates, Unity HD Render Pipeline (Metallic Standard) and Unreal Engine; 1024 for the other 21. UzPainter's project default is 1024.
- **Channel labels.** Dota 2 labels its user channels User0-User3. The labels are Painter's own text; no other template sets one. A label changes no texture.
- **Clean room.** UzPainter never reads, parses, hashes or copies a `.spt` file. File names are public facts.
- **Scope.** No Assets3D script passes a template, so gate G1 does not need it. The MCP `project_create {template}` tool (phase2.6) maps onto the native create. The `.uzp` manifest keeps unknown keys verbatim (09 §5), and the store task phase1.8 is still open.

The model panel, one round (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| B1 a typed `ProjectSettings` template id, read by export, diagnostics and `reload_mesh` | PARTLY: one authority, no separate argument; validate before mutation; test save, open and reload | PARTLY: do not clash with phase1.8's schema work | PARTLY: only if phase1.24 compares `project-templates` |
| B2 map a shipped template by its exact file name; the file must exist and is never opened | PARTLY: the missing-file behaviour needs a recording | AGREE: exact basename, case as recorded | AGREE |
| B3 evidence: the facade replays `project-templates` | PARTLY: also prove the export reads the recorded template | PARTLY: base values need their own chain | AGREE |
| B-alt keep `NotYetSupported` and split it out | not required | a viable fallback | acceptable only without the replay |

The conditions are met here, so B1-B3 are adopted:
- the field is optional and absent for "default", so no `format_version` change and no pinned digest moves (Kimi);
- `Settings.template` is the one input (GPT);
- `project-templates` is compared in this task (Grok);
- a native test exports a template's base value (GPT, Kimi).

## Decision

1. **The project records its template.**
   - `core::ProjectSettings::template_id` (default "default") is written to the manifest's `settings.template` only when it is not "default". `manifest.schema.json` gains that optional key.
   - Export, the export job, the `UzPainter.exe export` verb and every diagnostic read their base values from it.
   - `reload_mesh` gives the texture sets it adds the channels of the project's template.
2. **Native API.**
   - `uzpainter.project.Settings(template=<id>)` creates the stacks from an installed template. An unknown id raises `ValueError` listing the installed ids before anything is created.
   - `project.templates()` lists `{id, name, painter_template}`, and `project.template()` reads the open project's id.
   - The settings' resolution overrides the template's. A template's own resolution is the authored `default_resolution`, from the template capture, set for the five 2048 templates.
3. **The facade maps `template_file_path`** to the installed template whose shipped file has exactly the same file name.
   - The file must exist; UzPainter never opens it.
   - A path with no such file raises `NotYetSupported` naming recording **P24-A**. Any other name raises `NotYetSupported` before anything changes: a custom template is a release gap.
   - A user-edited copy of a shipped template under its shipped name is treated as the shipped template.
4. **Evidence.**
   - `test_pyapi_facade_tier0.py` replays `project-templates` through the facade with the recorder's own `project.create(template_file_path=...)` code. The shelf is a folder of empty files with the shipped names, because Painter's application shelf is recording P21-D.
   - Every template's texture sets, resolution, stacks, channels and formats are compared exactly, as created and after save and reopen.
   - Labels are compared without their text. The four user-channel labels of Dota 2 are a named residual that the test requires: their text is Painter's and is not shipped.
   - `test_pyapi_native.py` exports Dota 2's empty Glossiness channel after save and reopen. It reads 178/255, the base value of the recorded template; the default template has no such channel.

5. **Scope split with phase1.25 (coordinator, from the Codex audit).**
   - phase1.24's acceptance asked for the three pipeline scripts "end to end". The pinned `painter_export.py` exports the wand's BaseColor at PNG 16. That export is refused before writing (decision 103, R-090), and phase1.25_pilot-wand item 2.6 owns its fit. phase1.25 in turn requires phase1.24 accepted: a cycle.
   - phase1.24 is accepted without the wand's exported maps, as a recorded scope split (decision-069 pattern). Its proposal, spec and items 3.2 and 4.1 claim that create and sync return their results and that export runs its pinned bytes and ends in that explicit refusal. They make no claim about the exported maps.
   - phase1.25 owns the export of the sRGB8 material channels at PNG 16 (item 2.6) and the end-to-end export acceptance of the pipeline (items 3.1, 4.1). Its prerequisite item 1.1 says so.
   - The capability manifest lists `export_project_textures` of both packages in the context `srgb8-material-channels` as a `release-gap` owned by phase1.25_pilot-wand item 2.6. `test_capability_conformance.py` calls that export and requires `NotYetSupported` with the revision unchanged.

## Recordings this decision names (not recorded; owner action)

- **P24-A, a template path that is not a template.** `project.create(plane, template_file_path=p)` with `p` a missing `.spt` path, and with `p` an existing file that is not a template: whether it raises (type, message) or creates. Both recordings.

## Alternatives Considered

- **Keep `NotYetSupported`** (B-alt). Rejected: the evaluator already holds the 26 templates, and the only missing piece was recording the choice.
- **Read the `.spt` file.** Rejected: the clean-room rules forbid parsing Adobe's files.
- **Ship Dota 2's channel labels.** Not done: they are Painter's text. Shipping them is an owner question on the clean-room rules.

## Consequences

- phase2.6's `project_create {template}` maps onto `Settings(template=...)`.
- The capability entries of `project.templates`, `project.template` and `Settings.template` follow the trace (decision 112).
