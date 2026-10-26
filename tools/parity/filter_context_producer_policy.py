"""Reviewed F producer provenance, selected by protocol; never runtime attestation.

The recorder source digest is truncated to 64 bits and normalizes CRLF to LF.
Adding a producer requires a separately reviewed policy change, not a current-tree match.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FProducerProfile:
    profile_id: str
    recorder_version: str
    source_revision: str


APPROVED_F_PRODUCER = FProducerProfile(
    profile_id="uzpainter/filter-context-producer-profile/1",
    recorder_version="uzp-recorder/1+src.6fdbba920f54307b",
    source_revision="1b6bfc63332c4d38111fe830ecdcb77fe331f78d",
)

APPROVED_SETTINGS_F_PRODUCER = FProducerProfile(
    profile_id="uzpainter/filter-context-settings-producer-profile/1",
    recorder_version="uzp-recorder/1+src.89f3bbffae21361e",
    source_revision="7c3f819cf420a1b9369882893f0950036186a491",
)


def resolve_producer(recorder_version: str) -> FProducerProfile:
    """Resolve the exact approved literal; callers cannot supply a policy or trust flag."""
    if (
        type(recorder_version) is not str
        or recorder_version != APPROVED_F_PRODUCER.recorder_version
    ):
        raise ValueError("recorder source pin differs from approved F producer")
    return APPROVED_F_PRODUCER


def resolve_settings_producer(recorder_version: str) -> FProducerProfile:
    """The settings protocol's separate immutable producer; historical or future pins refuse."""
    if (
        type(recorder_version) is not str
        or recorder_version != APPROVED_SETTINGS_F_PRODUCER.recorder_version
    ):
        raise ValueError("recorder source pin differs from approved settings F producer")
    return APPROVED_SETTINGS_F_PRODUCER
