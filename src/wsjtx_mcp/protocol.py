"""Pure WSJT-X UDP message catalog: build outbound, parse inbound.

This module is deliberately free of sockets and threads so it can be unit-tested
against captured byte fixtures with no running WSJT-X.  The socket plumbing lives
in :mod:`wsjtx_mcp.client`.

Every datagram is ``magic (quint32) | schema (quint32) | type (quint32) | Id
(utf8) | payload``.  Message types and their field layouts come straight from
``Network/NetworkMessage.hpp`` (schema 3).  Direction is relative to *us, the
server*: **Out** = WSJT-X → us (we decode), **In** = us → WSJT-X (we build).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from wsjtx_mcp.qdatastream import (
    QUINT32_MAX,
    DecodeError,
    Reader,
    Writer,
    qdatetime_to_text,
    qtime_to_text,
)

MAGIC = 0xADBCCBDA
SCHEMA = 3  # QDataStream::Qt_5_4
PULSE = 15  # Heartbeat cadence, seconds

# --- message type numbers (NetworkMessage::Type) -----------------------------

HEARTBEAT = 0
STATUS = 1
DECODE = 2
CLEAR = 3
REPLY = 4
QSO_LOGGED = 5
CLOSE = 6
REPLAY = 7
HALT_TX = 8
FREE_TEXT = 9
WSPR_DECODE = 10
LOCATION = 11
LOGGED_ADIF = 12
HIGHLIGHT_CALLSIGN = 13
SWITCH_CONFIGURATION = 14
CONFIGURE = 15
ANNOTATION_INFO = 16

TYPE_NAMES: dict[int, str] = {
    HEARTBEAT: "Heartbeat",
    STATUS: "Status",
    DECODE: "Decode",
    CLEAR: "Clear",
    REPLY: "Reply",
    QSO_LOGGED: "QSOLogged",
    CLOSE: "Close",
    REPLAY: "Replay",
    HALT_TX: "HaltTx",
    FREE_TEXT: "FreeText",
    WSPR_DECODE: "WSPRDecode",
    LOCATION: "Location",
    LOGGED_ADIF: "LoggedADIF",
    HIGHLIGHT_CALLSIGN: "HighlightCallsign",
    SWITCH_CONFIGURATION: "SwitchConfiguration",
    CONFIGURE: "Configure",
    ANNOTATION_INFO: "AnnotationInfo",
}

NAME_TO_TYPE: dict[str, int] = {name.lower(): num for num, name in TYPE_NAMES.items()}

# Special Operation Mode enum (Status field).
SPECIAL_OP_MODES: dict[int, str] = {
    0: "NONE",
    1: "NA VHF",
    2: "EU VHF",
    3: "FIELD DAY",
    4: "RTTY RU",
    5: "WW DIGI",
    6: "FOX",
    7: "HOUND",
    8: "ARRL DIGI",
}

# Reply.Modifiers — keyboard-modifier equivalents for a simulated double-click.
MODIFIERS: dict[str, int] = {
    "none": 0x00,
    "shift": 0x02,
    "ctrl": 0x04,  # CMD on macOS
    "cmd": 0x04,
    "alt": 0x08,
    "meta": 0x10,
    "keypad": 0x20,
    "group": 0x40,
}


@dataclass
class Message:
    """A parsed inbound datagram."""

    type: int
    type_name: str
    id: str | None
    schema: int
    fields: dict = field(default_factory=dict)


# --- inbound decoding --------------------------------------------------------


def _special_op(value: int) -> str:
    return SPECIAL_OP_MODES.get(value, f"UNKNOWN({value})")


def _opt_u32(value: int) -> int | None:
    """Map the protocol's 0xFFFFFFFF "not applicable / no change" to ``None``."""
    return None if value == QUINT32_MAX else value


def _dec_heartbeat(r: Reader, d: dict) -> None:
    # "Maximum schema number" was introduced with schema 3; treat its absence as
    # schema 2 (per the header's negotiation note).
    d["max_schema"] = r.u32() if not r.at_end() else 2
    d["version"] = r.utf8() if not r.at_end() else None
    d["revision"] = r.utf8() if not r.at_end() else None


def _dec_status(r: Reader, d: dict) -> None:
    d["dial_frequency"] = r.u64()
    d["mode"] = r.utf8()
    d["dx_call"] = r.utf8()
    d["report"] = r.utf8()
    d["tx_mode"] = r.utf8()
    d["tx_enabled"] = r.boolean()
    d["transmitting"] = r.boolean()
    d["decoding"] = r.boolean()
    d["rx_df"] = r.u32()
    d["tx_df"] = r.u32()
    d["de_call"] = r.utf8()
    d["de_grid"] = r.utf8()
    d["dx_grid"] = r.utf8()
    d["tx_watchdog"] = r.boolean()
    d["sub_mode"] = r.utf8()
    d["fast_mode"] = r.boolean()
    raw_special = r.u8()
    d["special_operation_mode"] = _special_op(raw_special)
    d["special_operation_mode_value"] = raw_special
    d["frequency_tolerance"] = _opt_u32(r.u32())
    d["tr_period"] = _opt_u32(r.u32())
    d["configuration_name"] = r.utf8()
    d["tx_message"] = r.utf8()


def _dec_decode(r: Reader, d: dict) -> None:
    d["new"] = r.boolean()
    time_ms = r.qtime()
    d["time_ms"] = time_ms
    d["time"] = qtime_to_text(time_ms)
    d["snr"] = r.i32()
    d["delta_time"] = r.double()
    d["delta_frequency"] = r.u32()
    d["mode"] = r.utf8()
    d["message"] = r.utf8()
    d["low_confidence"] = r.boolean()
    d["off_air"] = r.boolean()


def _dec_clear(r: Reader, d: dict) -> None:
    # Window is "In only"; an Out-direction Clear carries no payload past the Id.
    if not r.at_end():
        d["window"] = r.u8()


def _dec_qso_logged(r: Reader, d: dict) -> None:
    d["datetime_off"] = qdatetime_to_text(r.qdatetime())
    d["dx_call"] = r.utf8()
    d["dx_grid"] = r.utf8()
    d["tx_frequency"] = r.u64()
    d["mode"] = r.utf8()
    d["report_sent"] = r.utf8()
    d["report_received"] = r.utf8()
    d["tx_power"] = r.utf8()
    d["comments"] = r.utf8()
    d["name"] = r.utf8()
    d["datetime_on"] = qdatetime_to_text(r.qdatetime())
    d["operator_call"] = r.utf8()
    d["my_call"] = r.utf8()
    d["my_grid"] = r.utf8()
    d["exchange_sent"] = r.utf8()
    d["exchange_received"] = r.utf8()
    d["adif_propagation_mode"] = r.utf8()


def _dec_wspr_decode(r: Reader, d: dict) -> None:
    d["new"] = r.boolean()
    time_ms = r.qtime()
    d["time_ms"] = time_ms
    d["time"] = qtime_to_text(time_ms)
    d["snr"] = r.i32()
    d["delta_time"] = r.double()
    d["frequency"] = r.u64()
    d["drift"] = r.i32()
    d["callsign"] = r.utf8()
    d["grid"] = r.utf8()
    d["power"] = r.i32()
    d["off_air"] = r.boolean()


def _dec_logged_adif(r: Reader, d: dict) -> None:
    d["adif_text"] = r.utf8()


def _dec_close(r: Reader, d: dict) -> None:
    pass  # only the Id


_DECODERS = {
    HEARTBEAT: _dec_heartbeat,
    STATUS: _dec_status,
    DECODE: _dec_decode,
    CLEAR: _dec_clear,
    QSO_LOGGED: _dec_qso_logged,
    CLOSE: _dec_close,
    WSPR_DECODE: _dec_wspr_decode,
    LOGGED_ADIF: _dec_logged_adif,
}


def parse(datagram: bytes) -> Message:
    """Parse a datagram into a :class:`Message`.

    Honours the protocol's backward-compatibility rules: a truncated tail (older
    WSJT-X missing newer fields) yields a *partial* field dict rather than an
    error, and unknown message types decode to just their Id.
    """
    r = Reader(datagram)
    magic = r.u32()
    if magic != MAGIC:
        raise DecodeError(f"bad magic 0x{magic:08x} (expected 0x{MAGIC:08x})")
    schema = r.u32()
    mtype = r.u32()
    mid = r.utf8()
    d: dict = {}
    decoder = _DECODERS.get(mtype)
    if decoder is not None:
        try:
            decoder(r, d)
        except DecodeError:
            pass  # keep whatever decoded; ignore a missing/short trailing field
    return Message(
        type=mtype,
        type_name=TYPE_NAMES.get(mtype, f"Unknown({mtype})"),
        id=mid,
        schema=schema,
        fields=d,
    )


# --- outbound building -------------------------------------------------------


def _begin(message_type: int, instance_id: str, schema: int) -> Writer:
    w = Writer()
    w.u32(MAGIC)
    w.u32(schema)
    w.u32(message_type)
    w.utf8(instance_id)
    return w


def build_heartbeat(
    instance_id: str,
    max_schema: int = SCHEMA,
    version: str = "",
    revision: str = "",
    schema: int = SCHEMA,
) -> bytes:
    w = _begin(HEARTBEAT, instance_id, schema)
    w.u32(max_schema)
    w.utf8(version)
    w.utf8(revision)
    return w.getvalue()


def build_clear(instance_id: str, window: int = 0, schema: int = SCHEMA) -> bytes:
    w = _begin(CLEAR, instance_id, schema)
    w.u8(window)
    return w.getvalue()


def build_reply(
    instance_id: str,
    time_ms: int | None,
    snr: int,
    delta_time: float,
    delta_frequency: int,
    mode: str,
    message: str,
    low_confidence: bool = False,
    modifiers: int = 0,
    schema: int = SCHEMA,
) -> bytes:
    w = _begin(REPLY, instance_id, schema)
    w.qtime(time_ms)
    w.i32(snr)
    w.double(delta_time)
    w.u32(delta_frequency)
    w.utf8(mode)
    w.utf8(message)
    w.boolean(low_confidence)
    w.u8(modifiers)
    return w.getvalue()


def build_close(instance_id: str, schema: int = SCHEMA) -> bytes:
    return _begin(CLOSE, instance_id, schema).getvalue()


def build_replay(instance_id: str, schema: int = SCHEMA) -> bytes:
    return _begin(REPLAY, instance_id, schema).getvalue()


def build_halt_tx(instance_id: str, auto_tx_only: bool = False, schema: int = SCHEMA) -> bytes:
    w = _begin(HALT_TX, instance_id, schema)
    w.boolean(auto_tx_only)
    return w.getvalue()


def build_free_text(
    instance_id: str, text: str = "", send: bool = False, schema: int = SCHEMA
) -> bytes:
    w = _begin(FREE_TEXT, instance_id, schema)
    w.utf8(text)
    w.boolean(send)
    return w.getvalue()


def build_location(instance_id: str, location: str, schema: int = SCHEMA) -> bytes:
    w = _begin(LOCATION, instance_id, schema)
    w.utf8(location)
    return w.getvalue()


def build_highlight_callsign(
    instance_id: str,
    callsign: str,
    background: tuple | None = None,
    foreground: tuple | None = None,
    highlight_last: bool = False,
    schema: int = SCHEMA,
) -> bytes:
    """Build a HighlightCallsign message.

    ``background`` / ``foreground`` are ``(r, g, b[, a])`` 0-255 tuples, or
    ``None`` for an *invalid* colour — which clears highlighting for the call.
    """
    w = _begin(HIGHLIGHT_CALLSIGN, instance_id, schema)
    w.utf8(callsign)
    w.qcolor(background)
    w.qcolor(foreground)
    w.boolean(highlight_last)
    return w.getvalue()


def build_switch_configuration(instance_id: str, name: str, schema: int = SCHEMA) -> bytes:
    w = _begin(SWITCH_CONFIGURATION, instance_id, schema)
    w.utf8(name)
    return w.getvalue()


def build_configure(
    instance_id: str,
    mode: str = "",
    frequency_tolerance: int | None = None,
    submode: str = "",
    fast_mode: bool = False,
    tr_period: int | None = None,
    rx_df: int | None = None,
    dx_call: str = "",
    dx_grid: str = "",
    generate_messages: bool = False,
    schema: int = SCHEMA,
) -> bytes:
    """Build a Configure message.

    For the utf8 fields an empty string means "no change"; for the quint32 fields
    (``frequency_tolerance``, ``tr_period``, ``rx_df``) ``None`` is sent as the
    max-quint32 "no change" marker.  The two booleans are always transmitted —
    the protocol has no "no change" encoding for them.
    """
    w = _begin(CONFIGURE, instance_id, schema)
    w.utf8(mode)
    w.u32(QUINT32_MAX if frequency_tolerance is None else frequency_tolerance)
    w.utf8(submode)
    w.boolean(fast_mode)
    w.u32(QUINT32_MAX if tr_period is None else tr_period)
    w.u32(QUINT32_MAX if rx_df is None else rx_df)
    w.utf8(dx_call)
    w.utf8(dx_grid)
    w.boolean(generate_messages)
    return w.getvalue()


def build_annotation_info(
    instance_id: str,
    dx_call: str = "",
    sort_order: int | None = None,
    schema: int = SCHEMA,
) -> bytes:
    """Build an AnnotationInfo message (Fox/Hound sort-order annotation for a DX call).

    Niche DXpedition feature: a server can score callsigns and set a numeric sort
    order so the Hound queue can be sorted by it. ``sort_order=None`` sends "no
    sort order provided" (value 0); a value of ``0xFFFFFFFF`` removes a call's
    sort-order entry from WSJT-X's internal table.
    """
    w = _begin(ANNOTATION_INFO, instance_id, schema)
    w.utf8(dx_call)
    provided = sort_order is not None
    w.boolean(provided)
    w.u32(sort_order if provided else 0)
    return w.getvalue()
