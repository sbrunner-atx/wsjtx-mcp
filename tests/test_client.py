"""Tests for the UDP client's state machine, fed synthetic datagrams directly.

These never open a socket: we call ``_handle`` with crafted bytes + a fake source
address, exercising routing, buffering, drain semantics, QSO pairing, and target
resolution without a running WSJT-X.
"""

from __future__ import annotations

import pytest

from wsjtx_mcp import protocol
from wsjtx_mcp.client import WsjtxClient, WsjtxError
from wsjtx_mcp.qdatastream import Writer

ADDR = ("127.0.0.1", 50001)
ADDR2 = ("127.0.0.1", 50002)


def _header(message_type: int, instance_id: str) -> Writer:
    w = Writer()
    w.u32(protocol.MAGIC).u32(protocol.SCHEMA).u32(message_type).utf8(instance_id)
    return w


def _heartbeat(instance="WSJT-X", max_schema=3) -> bytes:
    return protocol.build_heartbeat(instance, max_schema=max_schema, version="2.7.0")


def _status(instance="WSJT-X", dial=14_074_000) -> bytes:
    w = _header(protocol.STATUS, instance)
    (
        w.u64(dial).utf8("FT8").utf8("").utf8("-10").utf8("FT8")
        .boolean(True).boolean(False).boolean(True).u32(1500).u32(1500)
        .utf8("AE5VG").utf8("EL29").utf8("").boolean(False).utf8("")
        .boolean(False).u8(0).u32(0xFFFFFFFF).u32(15).utf8("Default").utf8("CQ")
    )
    return w.getvalue()


def _decode(instance="WSJT-X", message="CQ AE5VG EL29") -> bytes:
    w = _header(protocol.DECODE, instance)
    (
        w.boolean(True).qtime(3_600_000).i32(-10).double(0.1).u32(1500)
        .utf8("~").utf8(message).boolean(False).boolean(False)
    )
    return w.getvalue()


def _qso_logged(instance="WSJT-X", call="WB4QOJ") -> bytes:
    w = _header(protocol.QSO_LOGGED, instance)
    (
        w.qdatetime(None).utf8(call).utf8("DM12").u64(14_074_000).utf8("FT8")
        .utf8("-10").utf8("-12").utf8("").utf8("").utf8("")
        .qdatetime(None).utf8("AE5VG").utf8("AE5VG").utf8("EL29")
        .utf8("").utf8("").utf8("")
    )
    return w.getvalue()


def _logged_adif(instance="WSJT-X", text="<call:6>WB4QOJ<EOR>") -> bytes:
    w = _header(protocol.LOGGED_ADIF, instance)
    w.utf8(text)
    return w.getvalue()


def make_client() -> WsjtxClient:
    # Construct without start() so no socket is bound.
    return WsjtxClient(host="127.0.0.1", port=2237)


def test_status_snapshot_and_instance_registry():
    c = make_client()
    c._handle(_heartbeat(), ADDR)
    c._handle(_status(), ADDR)
    snap = c.status()
    assert snap["instance"] == "WSJT-X"
    assert snap["dial_frequency"] == 14_074_000
    assert "WSJT-X" in c.instances()


def test_schema_negotiation_downgrades():
    c = make_client()
    c._handle(_heartbeat(max_schema=2), ADDR)
    assert c.negotiated_schema == 2


def test_decode_buffer_and_drain_cursor():
    c = make_client()
    c._handle(_decode(message="CQ ONE"), ADDR)
    c._handle(_decode(message="CQ TWO"), ADDR)
    first = c.drain_decodes()
    assert [d["message"] for d in first] == ["CQ ONE", "CQ TWO"]
    assert c.drain_decodes() == []  # cursor advanced
    c._handle(_decode(message="CQ THREE"), ADDR)
    assert [d["message"] for d in c.drain_decodes()] == ["CQ THREE"]


def test_read_decodes_limit():
    c = make_client()
    for i in range(5):
        c._handle(_decode(message=f"M{i}"), ADDR)
    assert [d["message"] for d in c.read_decodes(2)] == ["M3", "M4"]
    assert len(c.read_decodes(None)) == 5


def test_clear_message_empties_decode_buffer():
    c = make_client()
    c._handle(_decode(), ADDR)
    assert c.read_decodes(None)
    c._handle(protocol.build_clear("WSJT-X", window=0), ADDR)
    assert c.read_decodes(None) == []


def test_qso_logged_pairs_with_adif():
    c = make_client()
    c._handle(_qso_logged(call="WB4QOJ"), ADDR)
    c._handle(_logged_adif(text="<call:6>WB4QOJ<EOR>"), ADDR)
    qsos = c.read_qso_log()
    assert len(qsos) == 1
    assert qsos[0]["qso"]["dx_call"] == "WB4QOJ"
    assert qsos[0]["adif"] == "<call:6>WB4QOJ<EOR>"


def test_resolve_target_single_instance():
    c = make_client()
    c._handle(_heartbeat(), ADDR)
    target_id, addr = c.resolve_target()
    assert target_id == "WSJT-X"
    assert addr == ADDR


def test_resolve_target_requires_a_heard_instance():
    c = make_client()
    with pytest.raises(WsjtxError):
        c.resolve_target()


def test_resolve_target_ambiguous_without_explicit_instance():
    c = make_client()
    c._handle(_heartbeat(instance="A"), ADDR)
    c._handle(_heartbeat(instance="B"), ADDR2)
    with pytest.raises(WsjtxError):
        c.resolve_target()
    # but explicit choice works
    assert c.resolve_target("B")[1] == ADDR2


def test_close_message_removes_instance():
    c = make_client()
    c._handle(_heartbeat(), ADDR)
    c._handle(protocol.build_close("WSJT-X"), ADDR)
    assert "WSJT-X" not in c.instances()
