"""`substance_painter.logging`: messages to the script's log over the native `uzpainter.logging`
(10 §4; `python/FACADE.md` §9).

The six severities are members of an enumeration, not integers: Painter reads each back by its
name (`p22b-host-application` s5-s10, both recordings; decision 297). `log` takes one of them and
writes through the native module, whose severities are integers.
"""

from __future__ import annotations

import enum

import uzpainter

MODULE = "substance_painter.logging"


class Severity(enum.Enum):
    """The severity of a log message."""

    INFO = uzpainter.logging.INFO
    WARNING = uzpainter.logging.WARNING
    ERROR = uzpainter.logging.ERROR
    DBG_INFO = uzpainter.logging.DBG_INFO
    DBG_WARNING = uzpainter.logging.DBG_WARNING
    DBG_ERROR = uzpainter.logging.DBG_ERROR


Severity.__module__ = MODULE

INFO = Severity.INFO
WARNING = Severity.WARNING
ERROR = Severity.ERROR
DBG_INFO = Severity.DBG_INFO
DBG_WARNING = Severity.DBG_WARNING
DBG_ERROR = Severity.DBG_ERROR


def log(severity: Severity, channel: str, message: str) -> None:
    """Log a message of `severity` on `channel`."""
    if not isinstance(severity, Severity):
        raise TypeError("the severity must be one of substance_painter.logging's severities")
    uzpainter.logging.log(severity.value, channel, message)


def info(message: str) -> None:
    """Log an information message."""
    uzpainter.logging.info(message)


def warning(message: str) -> None:
    """Log a warning message."""
    uzpainter.logging.warning(message)


def error(message: str) -> None:
    """Log an error message."""
    uzpainter.logging.error(message)
