"""Server-level tests: the transmit gate and tool dispatch.

Importing the server binds the UDP listener (to a free port in CI). We inject a
synthetic instance via the client so control tools have a target to send to —
the datagrams go to a throwaway loopback address.
"""

from __future__ import annotations

import pytest

from wsjtx_mcp import protocol
from wsjtx_mcp import server as srv
from wsjtx_mcp.server import TransmitBlocked

ADDR = ("127.0.0.1", 50051)


@pytest.fixture(autouse=True)
def _restore_callsign():
    saved = srv.config.callsign
    yield
    srv.config.callsign = saved


def _inject_instance(instance="WSJT-X"):
    srv._wsjtx._handle(
        protocol.build_heartbeat(instance, max_schema=3, version="2.7.0"), ADDR
    )


def _inject_decode(message="CQ AE5VG EL29"):
    from wsjtx_mcp.qdatastream import Writer

    w = Writer()
    w.u32(protocol.MAGIC).u32(protocol.SCHEMA).u32(protocol.DECODE).utf8("WSJT-X")
    (
        w.boolean(True).qtime(3_600_000).i32(-10).double(0.1).u32(1500)
        .utf8("~").utf8(message).boolean(False).boolean(False)
    )
    srv._wsjtx._handle(w.getvalue(), ADDR)


needs_bind = pytest.mark.skipif(
    not srv._wsjtx.bound, reason="UDP listener not bound in this environment"
)


# --- transmit gate (no socket needed; gate is checked first) -----------------


def test_reply_blocked_without_callsign():
    srv.config.callsign = ""
    with pytest.raises(TransmitBlocked):
        srv.reply(message="CQ AE5VG EL29")


def test_free_text_send_blocked_without_callsign():
    srv.config.callsign = ""
    with pytest.raises(TransmitBlocked):
        srv.free_text(text="TEST", send=True)


def test_wsjtx_call_reply_blocked_without_callsign():
    srv.config.callsign = ""
    with pytest.raises(TransmitBlocked):
        srv.wsjtx_call("reply", {"time_ms": 0, "snr": 0, "delta_time": 0.0,
                                 "delta_frequency": 0, "mode": "~", "message": "CQ"})


# --- non-transmitting paths are allowed regardless of callsign ---------------


@needs_bind
def test_free_text_set_only_is_allowed_without_callsign():
    srv.config.callsign = ""
    _inject_instance()
    out = srv.free_text(text="73", send=False)
    assert out["operation"] == "free_text"
    assert out["send"] is False
    assert out["instance"] == "WSJT-X"


@needs_bind
def test_transmit_halt_always_allowed():
    srv.config.callsign = ""
    _inject_instance()
    out = srv.transmit("halt")
    assert out["operation"] == "halt"


@needs_bind
def test_configure_dispatch():
    _inject_instance()
    out = srv.configure(mode="FT8", rx_df=1500)
    assert out["operation"] == "configure"
    assert out["bytes"] > 0


@needs_bind
def test_clear_dispatch():
    _inject_instance()
    out = srv.clear(window="both")
    assert out["window_code"] == 2


@needs_bind
def test_highlight_clear_all():
    _inject_instance()
    out = srv.highlight(operation="clear_all")
    assert out["operation"] == "clear_all"


# --- gate-open path ----------------------------------------------------------


@needs_bind
def test_reply_allowed_with_callsign_and_decode():
    srv.config.callsign = "AE5VG"
    _inject_instance()
    _inject_decode("CQ AE5VG EL29")
    decode = srv._wsjtx.read_decodes(1)[0]
    out = srv.reply(seq=decode["seq"])
    assert out["operation"] == "reply"
    assert out["answered"] == "CQ AE5VG EL29"


# --- observe + escape hatch --------------------------------------------------


def test_status_reports_gate_state():
    srv.config.callsign = ""
    out = srv.status()
    assert out["transmit_ready"] is False
    assert "listening" in out


def test_wsjtx_call_unknown_message():
    from wsjtx_mcp.methods import UnknownOperation

    with pytest.raises(UnknownOperation):
        srv.wsjtx_call("nonsense")


def test_decodes_unknown_operation():
    from wsjtx_mcp.methods import UnknownOperation

    with pytest.raises(UnknownOperation):
        srv.decodes(operation="bogus")
