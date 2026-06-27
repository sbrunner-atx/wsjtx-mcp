"""Build/parse round-trips and field decoding for the WSJT-X message catalog."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from wsjtx_mcp import protocol
from wsjtx_mcp.qdatastream import QUINT32_MAX, DecodeError, Writer


def _header(message_type: int, instance_id: str, schema: int = protocol.SCHEMA) -> Writer:
    w = Writer()
    w.u32(protocol.MAGIC).u32(schema).u32(message_type).utf8(instance_id)
    return w


# --- parsing inbound datagrams ----------------------------------------------


def test_parse_rejects_bad_magic():
    bad = Writer().u32(0x12345678).u32(3).u32(0).utf8("x").getvalue()
    with pytest.raises(DecodeError):
        protocol.parse(bad)


def test_parse_heartbeat():
    w = _header(protocol.HEARTBEAT, "WSJT-X")
    w.u32(3).utf8("2.7.0").utf8("abcdef")
    msg = protocol.parse(w.getvalue())
    assert msg.type_name == "Heartbeat"
    assert msg.id == "WSJT-X"
    assert msg.fields == {"max_schema": 3, "version": "2.7.0", "revision": "abcdef"}


def test_parse_heartbeat_schema2_without_max_schema():
    # Older WSJT-X: no "max schema" field -> assume schema 2, tolerate the rest.
    w = _header(protocol.HEARTBEAT, "WSJT-X")
    msg = protocol.parse(w.getvalue())
    assert msg.fields["max_schema"] == 2


def test_parse_status_full():
    w = _header(protocol.STATUS, "WSJT-X")
    (
        w.u64(14_074_000)
        .utf8("FT8")
        .utf8("")  # dx call
        .utf8("-10")  # report
        .utf8("FT8")  # tx mode
        .boolean(True)  # tx enabled
        .boolean(False)  # transmitting
        .boolean(True)  # decoding
        .u32(1500)  # rx df
        .u32(1500)  # tx df
        .utf8("AE5VG")  # de call
        .utf8("EL29")  # de grid
        .utf8("")  # dx grid
        .boolean(False)  # tx watchdog
        .utf8("")  # sub mode
        .boolean(False)  # fast mode
        .u8(3)  # special op = FIELD DAY
        .u32(QUINT32_MAX)  # freq tol = N/A
        .u32(15)  # T/R period
        .utf8("Default")  # config name
        .utf8("CQ AE5VG EL29")  # tx message
    )
    msg = protocol.parse(w.getvalue())
    f = msg.fields
    assert msg.type_name == "Status"
    assert f["dial_frequency"] == 14_074_000
    assert f["mode"] == "FT8"
    assert f["tx_enabled"] is True
    assert f["decoding"] is True
    assert f["de_call"] == "AE5VG"
    assert f["special_operation_mode"] == "FIELD DAY"
    assert f["frequency_tolerance"] is None  # 0xFFFFFFFF -> None
    assert f["tr_period"] == 15
    assert f["tx_message"] == "CQ AE5VG EL29"


def test_parse_decode():
    ms = (1 * 3600 + 2 * 60 + 3) * 1000
    w = _header(protocol.DECODE, "WSJT-X")
    (
        w.boolean(True)
        .qtime(ms)
        .i32(-12)
        .double(0.2)
        .u32(1500)
        .utf8("~")
        .utf8("CQ AE5VG EL29")
        .boolean(False)
        .boolean(False)
    )
    f = protocol.parse(w.getvalue()).fields
    assert f["new"] is True
    assert f["time"] == "01:02:03"
    assert f["snr"] == -12
    assert f["delta_time"] == 0.2
    assert f["delta_frequency"] == 1500
    assert f["message"] == "CQ AE5VG EL29"


def test_parse_qso_logged_datetimes():
    off = datetime(2026, 6, 27, 2, 30, 0, tzinfo=timezone.utc)
    on = datetime(2026, 6, 27, 2, 28, 0, tzinfo=timezone.utc)
    w = _header(protocol.QSO_LOGGED, "WSJT-X")
    (
        w.qdatetime(off)
        .utf8("WB4QOJ")
        .utf8("DM12")
        .u64(14_074_000)
        .utf8("FT8")
        .utf8("-10")
        .utf8("-12")
        .utf8("")  # tx power
        .utf8("")  # comments
        .utf8("")  # name
        .qdatetime(on)
        .utf8("AE5VG")  # operator call
        .utf8("AE5VG")  # my call
        .utf8("EL29")  # my grid
        .utf8("")  # exch sent
        .utf8("")  # exch recv
        .utf8("")  # adif prop mode
    )
    f = protocol.parse(w.getvalue()).fields
    assert f["dx_call"] == "WB4QOJ"
    assert f["tx_frequency"] == 14_074_000
    assert f["datetime_off"].startswith("2026-06-27T02:30:00")
    assert f["datetime_on"].startswith("2026-06-27T02:28:00")


def test_parse_tolerates_truncated_trailing_fields():
    # Status missing its last two fields (older client) -> partial dict, no crash.
    w = _header(protocol.STATUS, "WSJT-X")
    w.u64(7_074_000).utf8("FT4")  # then nothing
    f = protocol.parse(w.getvalue()).fields
    assert f["dial_frequency"] == 7_074_000
    assert f["mode"] == "FT4"
    assert "tx_message" not in f


def test_parse_unknown_type_keeps_id():
    w = Writer().u32(protocol.MAGIC).u32(3).u32(999).utf8("WSJT-X")
    msg = protocol.parse(w.getvalue())
    assert msg.id == "WSJT-X"
    assert msg.type_name == "Unknown(999)"
    assert msg.fields == {}


# --- building outbound, then parsing it back ---------------------------------


def test_build_and_parse_reply_round_trip():
    data = protocol.build_reply(
        "WSJT-X",
        time_ms=3_723_000,
        snr=-8,
        delta_time=0.1,
        delta_frequency=1234,
        mode="~",
        message="CQ W1AW FN31",
        modifiers=protocol.MODIFIERS["ctrl"],
    )
    # Header is well-formed and addressed to our id.
    msg_header = protocol.parse(
        data[:12] + data[12:]  # parse reads header + id; payload decode is In-only
    )
    assert msg_header.type == protocol.REPLY
    assert msg_header.id == "WSJT-X"


def test_build_configure_no_change_markers():
    data = protocol.build_configure("WSJT-X", mode="FT8", rx_df=1500)
    # frequency_tolerance and tr_period default to the 0xFFFFFFFF "no change" marker.
    assert data.count(b"\xff\xff\xff\xff") >= 2


def test_build_clear_and_halt():
    assert protocol.build_clear("WSJT-X", window=2)[-1] == 2
    assert protocol.build_halt_tx("WSJT-X", auto_tx_only=True)[-1] == 1
    assert protocol.build_halt_tx("WSJT-X", auto_tx_only=False)[-1] == 0


def test_build_highlight_invalid_color_clears():
    data = protocol.build_highlight_callsign("WSJT-X", "AE5VG", background=None, foreground=None)
    parsed_id = protocol.parse(data).id
    assert parsed_id == "WSJT-X"


def test_build_annotation_info_round_trip():
    data = protocol.build_annotation_info("WSJT-X", dx_call="DX1ABC", sort_order=42)
    msg = protocol.parse(data)
    assert msg.type == protocol.ANNOTATION_INFO
    assert msg.type_name == "AnnotationInfo"
    assert msg.id == "WSJT-X"
    # …DX call, then sort-order-provided=true (0x01) and the quint32 sort order 42.
    assert data.endswith(b"\x01\x00\x00\x00\x2a")


def test_build_annotation_info_no_sort_order():
    data = protocol.build_annotation_info("WSJT-X", dx_call="DX1ABC")
    # provided=false (0x00) and sort order 0.
    assert data.endswith(b"\x00\x00\x00\x00\x00")


def test_build_annotation_info_remove_marker():
    data = protocol.build_annotation_info("WSJT-X", dx_call="DX1ABC", sort_order=0xFFFFFFFF)
    assert data.endswith(b"\x01\xff\xff\xff\xff")
