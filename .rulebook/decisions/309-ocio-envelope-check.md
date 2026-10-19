# 309. An OCIO session is checked against the current envelope's OCIO identity: the host fields of its Legacy goldens and the five fields of its admitted OCIO goldens

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase0.9_oracle-envelope

## Context

Supervisor finding SUP-040. The registry's envelope hash covers the five envelope fields (decision 034 (a)) of a Legacy session: no `OCIO`, no `PAINTER_ACE_CONFIG`. The colour configuration hash is one of the five fields. So `python -m tools.parity.envelope check` reports `other_environment` (exit 3) in every OCIO session.

The OCIO goldens of decisions 068, 180, 198 and 215 were still recorded. Each decision noted the `other_environment` and went on. The only check was the recorder's colour guard (decisions 068 and 099): it refuses a manifest that names `OCIO` unless the session runs that configuration. Nothing compared the GPU, driver, OS or colour configuration file of those sessions with anything. That is a skipped mismatch, not an approved route. No decision, registry field or tool admitted an OCIO session against the envelope.

The last attempt (2026-10-18) ran on a Painter `12.1.5+js-api.1.1.20` OCIO session. Its colour configuration hash began `8f384af9`. Its envelope hash began `2353e048`; the registry's is `1497f649`. The check exited 3.

**Measured** on the private store, for the 291 admitted manifests of the current envelope that name an environment record:
- 258 Legacy goldens have the registry's envelope hash `1497f649…`. They include the ten canary goldens.
- The 10 admitted goldens that name `OCIO` `resources/ocio/substance/config.ocio` all have one envelope hash, `2353e048…`, and colour configuration hash `8f384af9…`. They include `wand-v1`, `export-presets-ocio`, `tunic-v10` and `ocio-sphere`.
- These 10 have the same four non-colour fields (build, GPU model, driver version, OS build) as the 258 Legacy goldens.
- The 23 Iray references (Tier 3) also have `2353e048…`, but their manifests name no `OCIO` setting.

## Decision

1. **`envelope check --request <manifest>`** reads the colour management a recording needs from the manifest's `OCIO` setting (`applied_by: environment_variable`), the setting the recorder's colour guard reads. `--ocio <configuration>` gives it directly, for a command without a manifest such as `resource-export-qual`. A manifest that names no `OCIO` is a Legacy recording, and the check answers exactly as without the option. So a Legacy request in an OCIO session is still `other_environment`, exit 3.
2. **The OCIO identity of the current envelope** is read from the private store (`tools/parity/envelope/ocio.py`):
   - *anchors*: the environment records of the current envelope's admitted goldens whose envelope hash is the registry's, or one the canary proved equivalent. Their four non-colour fields are the host that the canary and refresh vouch for;
   - *references*: the environment records of the current envelope's admitted goldens whose manifest names the same `OCIO` configuration.
3. **Admitted** (`ocio_reference`, exit 0) only when:
   - the running build is the current envelope's build;
   - the running four non-colour fields equal an anchor's. Then no GPU, driver, OS or Painter update happened since the canary, so decision 034 (d) asks for no new canary;
   - the running five-field envelope hash equals the references' hash.
4. **Refused**:
   - A host field that differs is `other_environment`, exit 3, naming the fields. The Legacy `envelope check` and the canary come first. The canary is Legacy, so it cannot run in an OCIO session.
   - A colour configuration that differs (another file, the same path with other contents, or a Legacy session for an OCIO request) is `other_environment`, exit 3.
   - An unseen or superseded build keeps its exit code (3 or 4).
   - The check refuses (exit 1) when there is no private store, no anchor, no reference, or an environment record it cannot read. It also refuses when the references disagree on their envelope hash, or carry other non-colour fields than the anchors. The first OCIO identity of an envelope, or a split one, needs its own decision.
5. **The ten current references are ratified** by the measurement above. They have one identity, and its host is the Legacy envelope's. Every later OCIO golden is recorded after a passing check, so it has the same identity. A wrong admission would show up as a split, and a split refuses.
6. **Nothing is relabelled.** The registry is read, never written: `equivalent_envelopes` holds only environments that the Legacy canary proved byte-identical, and an OCIO session is not one. The OCIO goldens keep their own environment records (decision 034 (a)). Oracle-to-golden comparisons still compare each golden's own record (`verdict.py`).
7. **A batch gates every group.** The scratch batch driver checks each group, Legacy or OCIO, before its first command, with `--request` (or `--ocio`) for that group's colour management. Every request in a group must need the same colour management as the group, or the batch stops. Any non-zero exit stops the whole batch. During capture, the recorder's own guards still verify the build, the session id, the host fields and the colour management.

## Alternatives Considered

- **Add the OCIO hash to `equivalent_envelopes`:** rejected. That would relabel the registry, and it is false: the canary is Legacy, and an OCIO session does not reproduce it.
- **A new registry field listing OCIO envelope hashes:** rejected. It changes the public registry, and it would need its own promotion and canary procedure. The admitted goldens already carry the identity.
- **Name one reference golden in each request:** rejected. It means more authoring for the same identity, and it is weaker: one golden instead of every admitted OCIO golden must agree.
- **Keep skipping the gate for OCIO groups:** rejected. It is the silent skip SUP-040 names.

## Consequences

- An OCIO recording window starts only after `envelope check --request <first request>` exits 0. The 2026-10-18 session's identity (`2353e048…`) equals the references', so that session would be admitted.
- A driver, GPU or OS update now refuses OCIO recordings until the Legacy check and canary have run. If the canary shows drift, the refresh has to re-record the OCIO goldens too. The refresh's corpus run is single-session Legacy, so that case needs its own decision when it first happens.
- Panel (2026-10-19; GPT-6 Astra, Kimi K3, Grok 4.5): all agreed on the Legacy path and on the rejected alternatives. Two raised the bootstrap of the references (item 5) and the colour homogeneity of a group (item 7); both are recorded above.
- Tests: `tests/parity/test_oracle_envelope.py` (`-k ocio`). It covers an OCIO request on the matching identity, a Legacy request on an OCIO session, an OCIO request on a Legacy session, a mismatch in each field (GPU, driver, OS, colour file contents), an unseen build, no reference, no store, split references, and references from another host.
