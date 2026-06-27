"""A tiny, standard-library Qt ``QDataStream`` codec for the WSJT-X UDP protocol.

WSJT-X serializes every datagram with Qt's ``QDataStream`` in **schema 3 /
``QDataStream::Qt_5_4``** format, **big-endian**, with **double-precision floats**
(the protocol header is explicit: "all are double precision i.e. 64-bit IEEE
format").  This module reimplements just the handful of type encodings the
protocol uses, with :mod:`struct` and nothing else, so the rest of the project
never depends on Qt or ``pywsjtx``.

Field encodings (from ``Network/NetworkMessage.hpp`` and the Qt datastream
format docs):

* integers — ``quint8``/``quint32``/``quint64`` and ``qint32``/``qint64``,
  big-endian two's-complement / unsigned.
* ``bool`` — one byte, ``0x00`` / ``0x01``.
* ``double`` — 8-byte IEEE-754 big-endian (WSJT-X serializes every float as a
  double).
* ``utf8`` — a ``QByteArray``: a ``quint32`` length followed by exactly that many
  UTF-8 bytes, **no terminator**.  Length ``0xFFFFFFFF`` is a *null* byte array
  (distinct from a zero-length *empty* one).
* ``QTime`` — ``quint32`` milliseconds since midnight (``0xFFFFFFFF`` = invalid).
* ``QDateTime`` — ``qint64`` Julian day, ``quint32`` ms since midnight, ``quint8``
  timespec (0=local, 1=UTC, 2=offset-from-UTC then a ``qint32`` offset).  WSJT-X
  avoids the time-zone forms.
* ``QColor`` — Qt's *QDataStream-version ≥ 7* form (the standard Qt 5.x layout,
  which Qt_5_4 uses): a ``qint8`` colour-spec then five ``quint16`` channels
  (alpha, red, green, blue, pad).  An *invalid* colour (spec ``0``) is how the
  protocol clears callsign highlighting.

The encoders/decoders are deliberately symmetric and round-trip tested against
byte fixtures, because this is exactly where wire-format bugs hide.
"""

from __future__ import annotations

import struct
from datetime import date, datetime, timedelta, timezone

# QByteArray / QString length sentinel for a *null* (as opposed to empty) value.
NULL_LENGTH = 0xFFFFFFFF
# QTime sentinel for an invalid time.
INVALID_QTIME = 0xFFFFFFFF
# Maximum quint32 — the protocol's "no change / not applicable" marker for the
# Rx DF, Frequency Tolerance and T/R Period fields.
QUINT32_MAX = 0xFFFFFFFF

# Julian Day Number of the Unix epoch (1970-01-01).  QDate stores dates as a
# Julian day; this constant converts to/from a proleptic-Gregorian date.
_JULIAN_DAY_UNIX_EPOCH = 2440588

# Qt QColor colour-spec enum values.
_QCOLOR_INVALID = 0
_QCOLOR_RGB = 1


class DecodeError(ValueError):
    """Raised when a datagram is truncated or otherwise unparseable."""


def _scale8to16(value: int) -> int:
    """Expand an 8-bit channel (0-255) to Qt's 16-bit channel (``c<<8 | c``)."""
    value &= 0xFF
    return (value << 8) | value


class Writer:
    """Accumulate big-endian ``QDataStream`` bytes.  Call :meth:`getvalue` at end."""

    __slots__ = ("_parts",)

    def __init__(self) -> None:
        self._parts: list[bytes] = []

    def getvalue(self) -> bytes:
        return b"".join(self._parts)

    # -- scalars --------------------------------------------------------------

    def u8(self, value: int) -> Writer:
        self._parts.append(struct.pack(">B", value & 0xFF))
        return self

    def u32(self, value: int) -> Writer:
        self._parts.append(struct.pack(">I", value & 0xFFFFFFFF))
        return self

    def u64(self, value: int) -> Writer:
        self._parts.append(struct.pack(">Q", value & 0xFFFFFFFFFFFFFFFF))
        return self

    def i8(self, value: int) -> Writer:
        self._parts.append(struct.pack(">b", value))
        return self

    def i32(self, value: int) -> Writer:
        self._parts.append(struct.pack(">i", value))
        return self

    def i64(self, value: int) -> Writer:
        self._parts.append(struct.pack(">q", value))
        return self

    def u16(self, value: int) -> Writer:
        self._parts.append(struct.pack(">H", value & 0xFFFF))
        return self

    def boolean(self, value: bool) -> Writer:
        return self.u8(1 if value else 0)

    def double(self, value: float) -> Writer:
        self._parts.append(struct.pack(">d", float(value)))
        return self

    # -- composite ------------------------------------------------------------

    def utf8(self, value: str | None) -> Writer:
        """Write a ``QByteArray``: ``quint32`` length + bytes (null = 0xFFFFFFFF)."""
        if value is None:
            return self.u32(NULL_LENGTH)
        raw = value.encode("utf-8")
        self.u32(len(raw))
        self._parts.append(raw)
        return self

    def qtime(self, ms_since_midnight: int | None) -> Writer:
        """Write a ``QTime`` as ms-since-midnight (``None`` → invalid)."""
        if ms_since_midnight is None:
            return self.u32(INVALID_QTIME)
        return self.u32(ms_since_midnight)

    def qdatetime(self, dt: datetime | None) -> Writer:
        """Write a ``QDateTime`` (UTC) as Julian day + ms + timespec.

        A ``None`` value is encoded as an invalid ``QDateTime`` (Julian day 0,
        invalid time, local spec) — matching how Qt streams a null datetime.
        """
        if dt is None:
            self.i64(0)
            self.u32(INVALID_QTIME)
            return self.u8(0)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        julian = dt.toordinal() - date(1970, 1, 1).toordinal() + _JULIAN_DAY_UNIX_EPOCH
        ms = (dt.hour * 3600 + dt.minute * 60 + dt.second) * 1000 + dt.microsecond // 1000
        self.i64(julian)
        self.u32(ms)
        return self.u8(1)  # 1 = UTC

    def qcolor(self, color: tuple[int, int, int] | tuple[int, int, int, int] | None) -> Writer:
        """Write a ``QColor``.

        ``color`` is an ``(r, g, b)`` or ``(r, g, b, a)`` tuple (0-255 each), or
        ``None`` for an **invalid** colour — which is how WSJT-X is told to clear
        highlighting for a callsign.
        """
        if color is None:
            self.i8(_QCOLOR_INVALID)
            for _ in range(5):
                self.u16(0)
            return self
        r, g, b = color[0], color[1], color[2]
        a = color[3] if len(color) > 3 else 255
        self.i8(_QCOLOR_RGB)
        self.u16(_scale8to16(a))
        self.u16(_scale8to16(r))
        self.u16(_scale8to16(g))
        self.u16(_scale8to16(b))
        self.u16(0)  # pad
        return self


class Reader:
    """Read big-endian ``QDataStream`` bytes, tracking a cursor."""

    __slots__ = ("_data", "_pos")

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    @property
    def pos(self) -> int:
        return self._pos

    def at_end(self) -> bool:
        return self._pos >= len(self._data)

    def remaining(self) -> bytes:
        return self._data[self._pos :]

    def _take(self, n: int) -> bytes:
        end = self._pos + n
        if end > len(self._data):
            raise DecodeError(
                f"datagram truncated: wanted {n} bytes at offset {self._pos}, "
                f"only {len(self._data) - self._pos} remain"
            )
        chunk = self._data[self._pos : end]
        self._pos = end
        return chunk

    # -- scalars --------------------------------------------------------------

    def u8(self) -> int:
        return struct.unpack(">B", self._take(1))[0]

    def u16(self) -> int:
        return struct.unpack(">H", self._take(2))[0]

    def u32(self) -> int:
        return struct.unpack(">I", self._take(4))[0]

    def u64(self) -> int:
        return struct.unpack(">Q", self._take(8))[0]

    def i8(self) -> int:
        return struct.unpack(">b", self._take(1))[0]

    def i32(self) -> int:
        return struct.unpack(">i", self._take(4))[0]

    def i64(self) -> int:
        return struct.unpack(">q", self._take(8))[0]

    def boolean(self) -> bool:
        return self.u8() != 0

    def double(self) -> float:
        return struct.unpack(">d", self._take(8))[0]

    # -- composite ------------------------------------------------------------

    def utf8(self) -> str | None:
        length = self.u32()
        if length == NULL_LENGTH:
            return None
        return self._take(length).decode("utf-8", "replace")

    def qtime(self) -> int | None:
        ms = self.u32()
        if ms == INVALID_QTIME:
            return None
        return ms

    def qdatetime(self) -> datetime | None:
        julian = self.i64()
        ms = self.u32()
        spec = self.u8()
        offset = 0
        if spec == 2:
            offset = self.i32()
        if ms == INVALID_QTIME or julian == 0:
            return None
        days = julian - _JULIAN_DAY_UNIX_EPOCH
        base = datetime(1970, 1, 1) + timedelta(days=days, milliseconds=ms)
        if spec == 1:  # UTC
            return base.replace(tzinfo=timezone.utc)
        if spec == 2:  # offset from UTC, in seconds
            return base.replace(tzinfo=timezone(timedelta(seconds=offset)))
        return base  # local / unspecified — naive

    def qcolor(self) -> tuple[int, int, int, int] | None:
        spec = self.i8()
        a, r, g, b = self.u16(), self.u16(), self.u16(), self.u16()
        self.u16()  # pad
        if spec == _QCOLOR_INVALID:
            return None
        return (r >> 8, g >> 8, b >> 8, a >> 8)


def qtime_to_text(ms: int | None) -> str | None:
    """Render a ``QTime`` (ms since midnight) as ``HH:MM:SS`` UTC, or ``None``."""
    if ms is None:
        return None
    seconds, _ = divmod(ms, 1000)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def qdatetime_to_text(dt: datetime | None) -> str | None:
    """Render a decoded ``QDateTime`` as an ISO-8601 string, or ``None``."""
    if dt is None:
        return None
    return dt.isoformat()
