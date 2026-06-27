"""Golden-fixture tests against REAL datagrams captured from a live WSJT-X.

These bytes were recorded from WSJT-X (reported version 3.0.2, header schema 2 /
max schema 3) on 2026-06-26 via ``smoke_test.py``. Decoding them here field-by-
field proves the codec against true wire data, with no running WSJT-X needed —
the same "tests don't need the live app" principle as the rest of the suite.
"""

from __future__ import annotations

import base64

from wsjtx_mcp import protocol

# Heartbeat: id="WSJT-X", max_schema=3, version="3.0.2", revision="ccdfaf".
HEARTBEAT_B64 = "rbzL2gAAAAIAAAAAAAAABldTSlQtWAAAAAMAAAAFMy4wLjIAAAAGY2NkZmFm"

# Status: 14.074 MHz FT8, decoding, de=WW6CC, Special Operation Mode = FIELD DAY.
STATUS_B64 = (
    "rbzL2gAAAAIAAAABAAAABldTSlQtWAAAAAAA1sCQAAAAA0ZUOP////8AAAADLTE1AAAAA0ZUOAAA"
    "AQAABdwAAAXcAAAABVdXNkNDAAAAAP////8A/////wAD//////////8AAAAHRGVmYXVsdP////8="
)


def test_golden_heartbeat():
    msg = protocol.parse(base64.b64decode(HEARTBEAT_B64))
    assert msg.type_name == "Heartbeat"
    assert msg.id == "WSJT-X"
    assert msg.schema == 2  # this build emits a schema-2 header…
    assert msg.fields["max_schema"] == 3  # …while advertising it supports schema 3
    assert msg.fields["version"] == "3.0.2"
    assert msg.fields["revision"] == "ccdfaf"


def test_golden_status():
    msg = protocol.parse(base64.b64decode(STATUS_B64))
    f = msg.fields
    assert msg.type_name == "Status"
    assert msg.id == "WSJT-X"
    assert f["dial_frequency"] == 14_074_000
    assert f["mode"] == "FT8"
    assert f["dx_call"] is None  # null QByteArray, distinct from empty
    assert f["report"] == "-15"
    assert f["tx_enabled"] is False
    assert f["transmitting"] is False
    assert f["decoding"] is True
    assert f["rx_df"] == 1500
    assert f["tx_df"] == 1500
    assert f["de_call"] == "WW6CC"
    assert f["de_grid"] == ""  # empty, present
    assert f["special_operation_mode"] == "FIELD DAY"
    assert f["frequency_tolerance"] is None  # 0xFFFFFFFF -> not applicable
    assert f["configuration_name"] == "Default"


def test_golden_status_negotiation_value():
    # A client tracking this peer should settle on schema 3 (min of ours, max 3).
    msg = protocol.parse(base64.b64decode(HEARTBEAT_B64))
    assert min(protocol.SCHEMA, msg.fields["max_schema"]) == 3
