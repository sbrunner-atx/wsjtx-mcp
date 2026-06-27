"""Unit tests for the QDataStream codec — the place wire-format bugs hide."""

from __future__ import annotations

import struct
from datetime import datetime, timezone

import pytest

from wsjtx_mcp.qdatastream import (
    INVALID_QTIME,
    NULL_LENGTH,
    DecodeError,
    Reader,
    Writer,
    qdatetime_to_text,
    qtime_to_text,
)


def test_integer_round_trip():
    w = Writer()
    w.u8(0xAB).u32(0xDEADBEEF).u64(0x0123456789ABCDEF).i32(-5).i64(-1).u16(0x1234)
    r = Reader(w.getvalue())
    assert r.u8() == 0xAB
    assert r.u32() == 0xDEADBEEF
    assert r.u64() == 0x0123456789ABCDEF
    assert r.i32() == -5
    assert r.i64() == -1
    assert r.u16() == 0x1234
    assert r.at_end()


def test_big_endian_layout():
    assert Writer().u32(1).getvalue() == b"\x00\x00\x00\x01"
    assert Writer().u64(1).getvalue() == b"\x00\x00\x00\x00\x00\x00\x00\x01"


def test_bool_is_one_byte():
    assert Writer().boolean(True).getvalue() == b"\x01"
    assert Writer().boolean(False).getvalue() == b"\x00"
    assert Reader(b"\x01").boolean() is True
    assert Reader(b"\x00").boolean() is False


def test_double_serialization():
    w = Writer().double(0.25)
    assert w.getvalue() == struct.pack(">d", 0.25)
    assert Reader(w.getvalue()).double() == 0.25


def test_utf8_round_trip_and_length_prefix():
    w = Writer().utf8("WSJT-X")
    data = w.getvalue()
    assert data[:4] == struct.pack(">I", 6)
    assert data[4:] == b"WSJT-X"
    assert Reader(data).utf8() == "WSJT-X"


def test_utf8_null_vs_empty_are_distinct():
    null = Writer().utf8(None).getvalue()
    empty = Writer().utf8("").getvalue()
    assert null == struct.pack(">I", NULL_LENGTH)
    assert empty == struct.pack(">I", 0)
    assert Reader(null).utf8() is None
    assert Reader(empty).utf8() == ""


def test_utf8_multibyte():
    assert Reader(Writer().utf8("grüße ✓").getvalue()).utf8() == "grüße ✓"


def test_qtime_round_trip_and_invalid():
    ms = (12 * 3600 + 34 * 60 + 56) * 1000
    assert Reader(Writer().qtime(ms).getvalue()).qtime() == ms
    assert Writer().qtime(None).getvalue() == struct.pack(">I", INVALID_QTIME)
    assert Reader(Writer().qtime(None).getvalue()).qtime() is None


def test_qtime_to_text():
    assert qtime_to_text((1 * 3600 + 2 * 60 + 3) * 1000) == "01:02:03"
    assert qtime_to_text(None) is None


def test_qdatetime_utc_round_trip():
    dt = datetime(2026, 6, 27, 2, 27, 30, tzinfo=timezone.utc)
    data = Writer().qdatetime(dt).getvalue()
    back = Reader(data).qdatetime()
    assert back == dt
    assert qdatetime_to_text(back).startswith("2026-06-27T02:27:30")


def test_qdatetime_none_is_invalid():
    data = Writer().qdatetime(None).getvalue()
    assert Reader(data).qdatetime() is None


def test_qcolor_rgb_round_trip():
    data = Writer().qcolor((255, 0, 128)).getvalue()
    # qint8 spec=1, then five quint16: alpha, r, g, b, pad
    assert data[0] == 1
    assert len(data) == 1 + 5 * 2
    assert Reader(data).qcolor() == (255, 0, 128, 255)


def test_qcolor_invalid_clears():
    data = Writer().qcolor(None).getvalue()
    assert data[0] == 0
    assert data == b"\x00" + b"\x00" * 10
    assert Reader(data).qcolor() is None


def test_qcolor_channel_scaling():
    # 8-bit 0xAB expands to 0xABAB on the wire.
    data = Writer().qcolor((0xAB, 0xAB, 0xAB)).getvalue()
    # skip spec byte + alpha(2): red is bytes [3:5]
    assert data[3:5] == b"\xab\xab"


def test_reader_truncation_raises():
    with pytest.raises(DecodeError):
        Reader(b"\x00\x01").u32()
