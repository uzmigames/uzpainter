# 28. CI: GitHub runs hosted CPU-only CI; GPU and Painter-oracle checks run locally on the owner's machine

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase0.5_private-oracle-store

## Context

Stated by the owner on 2026-10-10 ("nao vamos ter CI que usa GPU no github"). Supersedes the CI-runner part of decision 022 (Q9b), which had made the owner's machine a self-hosted GitHub runner; the platform part of 022 (Windows 10/11 x64, DX12 + Vulkan, one folder) stays.

## Decision

There is no GPU CI on GitHub and no self-hosted GitHub Actions runner. GitHub Actions runs only hosted, CPU-only jobs (type-check, lint, tests that need neither a GPU nor Painter; GPU and oracle tests skip there with an explicit reason). Every check that needs the GPU (DX12/Vulkan hardware slices, native GPU tests, path tracer) or the private oracle store and licensed Painter runs locally on the owner's machine through a documented local command, and its report is recorded as gate evidence.

## Consequences

Remove the self-hosted `oracle` job and runner-registration steps; gates that need GPU or oracle evidence accept a local run report (command, machine, build hash, results) instead of a CI run; GPU-dependent pytest tests skip on machines without a suitable GPU; the private oracle store never leaves the owner's machine.
