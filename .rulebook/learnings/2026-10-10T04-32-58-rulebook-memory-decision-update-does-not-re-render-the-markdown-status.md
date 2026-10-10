# rulebook_memory decision update does not re-render the markdown status
**Source**: manual
**Date**: 2026-10-10
**Tags**: rulebook, tooling, decisions
What happens: `rulebook_memory {kind:"decision", action:"update", status}` writes the new status only to `.rulebook/decisions/NNN-<slug>.metadata.json`. The paired `NNN-<slug>.md` is not re-rendered, so its `**Status**:` line (line 3) keeps the old value (e.g. `proposed`). The metadata is the source of truth.

How it was detected: on 2026-10-10, comparing the 16 UzPainter decisions showed the `.md` saying `proposed` while the `.metadata.json` said `accepted` for 14 of them (001, 002, 003, 005, 006, 007, 009-016). Only 004 and 008, still `proposed` in the metadata, matched.

Workaround: after any decision status update, copy the `"status"` value from the `.metadata.json` into the `**Status**:` line of the matching `.md`, changing nothing else. Then check every pair (md status next to metadata status) to confirm they all match.