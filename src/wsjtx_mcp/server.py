"""wsjtx-mcp: an MCP server that controls WSJT-X over its UDP message protocol.

Tools are organised into logical **groups** (one permission each) rather than one
tool per message.  Each group tool takes an ``operation`` argument where it has
more than one mode, and every documented capability is reachable either through a
group or the ``wsjtx_call`` escape hatch (which also reaches message types added
by newer WSJT-X builds).

Permission model:

* **Observe** tools are marked ``readOnlyHint`` so clients can default them to
  *Always Allow*: ``status``, ``diagnostics``, ``log``.  ``decodes`` is observe
  too, but ``replay`` mildly nudges WSJT-X so it isn't flagged read-only.
* **Non-transmitting control** (``configure``, ``clear``, ``highlight``,
  ``location``, ``switch_config``, ``transmit halt``) default to *Needs Approval*
  but never key the radio — ``transmit halt`` only takes you *off* the air.
* **Transmit-initiating** operations — ``reply`` and ``free_text`` with
  ``send=true`` (and any keying message through ``wsjtx_call``) — are refused
  unless ``WSJTX_CALLSIGN`` is set.  That callsign is the single transmit gate,
  exactly as in ``fldigi-mcp``.

WSJT-X note: its UDP protocol can *halt* transmission but cannot *enable* "Enable
Tx", and cannot set the dial frequency.  Those asymmetries are documented on the
relevant tools.
"""

from __future__ import annotations

import sys
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from wsjtx_mcp import __version__, diag, methods, protocol
from wsjtx_mcp.client import WsjtxClient
from wsjtx_mcp.config import Config

config = Config.from_env()
mcp = FastMCP("wsjtx-mcp")
_wsjtx = WsjtxClient(config.host, config.port, multicast=config.multicast)
# Start listening immediately so decodes and QSOs broadcast before the first tool
# call are still captured. Bind errors are surfaced via `diagnostics`, not raised.
_wsjtx.start()

READ_ONLY = ToolAnnotations(readOnlyHint=True)


class TransmitBlocked(RuntimeError):
    """Raised when a transmit-initiating message is attempted with no callsign."""


def _require_tx(what: str) -> None:
    if not config.transmit_ready:
        raise TransmitBlocked(
            f"REFUSED: {what} would initiate a transmission, but the transmit gate is "
            "closed. Set WSJTX_CALLSIGN to your licensed callsign to enable transmit "
            "(blank = receive-only). HaltTx, configure, clear, highlight, location and "
            "all reads remain available."
        )


def _dispatch(builder, instance: str | None, **kwargs) -> dict:
    """Resolve the target instance, build a control datagram, and send it."""
    target_id, addr = _wsjtx.resolve_target(instance)
    datagram = builder(target_id, schema=_wsjtx.negotiated_schema, **kwargs)
    _wsjtx.sendto(datagram, addr)
    return {"instance": target_id, "sent_to": f"{addr[0]}:{addr[1]}", "bytes": len(datagram)}


# --- status (observe) --------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
def status() -> dict:
    """Latest WSJT-X state snapshot plus listener/connection health.

    Returns the most recent ``Status`` broadcast — dial frequency, mode/sub-mode,
    Tx Enabled / Transmitting / Decoding, DE/DX call & grid, Rx/Tx DF, T/R period,
    special-operation mode (e.g. FIELD DAY), configuration name, current Tx
    message — together with the discovered instances and the transmit-gate state.

    If no ``Status`` has arrived yet, that is reported with guidance (WSJT-X must
    have its UDP Server pointed at this host:port).
    """
    snap = _wsjtx.status()
    stats = _wsjtx.stats()
    out: dict[str, Any] = {
        "listening": stats["listen"],
        "bound": stats["bound"],
        "transmit_ready": config.transmit_ready,
        "callsign": config.callsign or None,
        "instances": list(stats["instances"].keys()),
        "datagrams_received": stats["datagrams"],
    }
    if not stats["bound"]:
        out["bind_error"] = stats["bind_error"]
    if snap is None:
        out["status"] = None
        out["note"] = (
            "No Status received yet. Confirm WSJT-X Settings → Reporting → UDP Server "
            f"is {config.host}:{config.port}, and that WSJT-X is running. Control also "
            "requires 'Accept UDP requests' to be enabled there."
        )
    else:
        out["status"] = snap
    return out


# --- diagnostics (observe, no commanding) ------------------------------------


@mcp.tool(annotations=READ_ONLY)
def diagnostics() -> dict:
    """Host + network + listener diagnostics for troubleshooting connectivity.

    Does NOT command WSJT-X. Reports the resolved WSJTX_HOST/PORT, whether the UDP
    listener is bound (and any bind error), datagram counts by message type, the
    discovered instances, the transmit-gate state, and this host's network
    interfaces — so you can tell whether this process can even receive WSJT-X's
    broadcasts (e.g. host-side vs. sandboxed, or a port already owned by JTAlert /
    GridTracker).
    """
    net = diag.network_interfaces()
    stats = _wsjtx.stats()
    return {
        "wsjtx_host": config.host,
        "wsjtx_port": config.port,
        "multicast": config.multicast or None,
        "resolved_listen": stats["listen"],
        "bound": stats["bound"],
        "bind_error": stats["bind_error"],
        "negotiated_schema": stats["negotiated_schema"],
        "datagrams_received": stats["datagrams"],
        "datagrams_by_type": stats["by_type"],
        "last_datagram_at": stats["last_datagram_at"],
        "instances": stats["instances"],
        "transmit_ready": config.transmit_ready,
        "callsign": config.callsign or None,
        "accept_udp_requests_note": (
            "Control messages are honoured ONLY if WSJT-X Settings → Reporting → "
            "'Accept UDP requests' is enabled (OFF by default)."
        ),
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "server_version": __version__,
        "hostname": net["hostname"],
        "fqdn": net["fqdn"],
        "primary_outbound_ip": net["primary_outbound_ip"],
        "interface_command": net["interface_command"],
        "ipv4_addresses": net["ipv4_addresses"],
        "interfaces_raw": net["interfaces_raw"],
    }


# --- decodes (observe + replay nudge) ----------------------------------------


@mcp.tool()
def decodes(operation: str = "read", limit: int = 50) -> dict:
    """The RX data plane: buffered ``Decode`` / ``WSPRDecode`` lines.

    operations:
      - read (limit): the most recent N decodes (default 50).
      - drain: every decode seen since the last drain — the polling primitive for
        automation. Advances an internal cursor so each line is returned once.
      - clear_local: empty our local buffer (does not touch WSJT-X).
      - replay: ask WSJT-X to re-broadcast its current Band-Activity decodes (each
        with New=false) followed by a Status — useful to backfill state on
        connect. (No transmit; safe.)

    Each decode carries: kind (decode/wspr), New, time, snr, delta_time,
    delta_frequency, mode, message, low_confidence, off_air, and a `seq` you can
    pass to the `reply` tool.
    """
    if operation == "read":
        return {"operation": "read", "decodes": _wsjtx.read_decodes(limit)}
    if operation == "drain":
        return {"operation": "drain", "decodes": _wsjtx.drain_decodes()}
    if operation == "clear_local":
        return {"operation": "clear_local", "cleared": _wsjtx.clear_local_decodes()}
    if operation == "replay":
        result = _dispatch(protocol.build_replay, None)
        return {"operation": "replay", **result}
    raise methods.UnknownOperation(
        "operation must be one of: read, drain, clear_local, replay"
    )


# --- log (observe) -----------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
def log(limit: int = 20) -> dict:
    """Read buffered completed QSOs (``QSOLogged`` paired with ``LoggedADIF``).

    Observe-only: WSJT-X emits these when the operator accepts its "Log QSO"
    dialog. Each entry has the structured QSO record (call, grids, frequency,
    mode, reports, times, exchanges, propagation mode) and the one-record ADIF
    document — ready to forward to N3FJP via contest-mcp.
    """
    return {"qsos": _wsjtx.read_qso_log(limit)}


# --- reply (TRANSMIT-GATED) --------------------------------------------------


@mcp.tool()
def reply(
    seq: int | None = None,
    message: str | None = None,
    modifiers: Any = None,
    instance: str | None = None,
) -> dict:
    """Answer a buffered decode — **initiates a transmission** (gated by callsign).

    Equivalent to double-clicking that decode in the Band Activity window. WSJT-X
    only acts if the message **exactly** matches a prior decode that is a CQ or
    QRZ, then auto-sequences the rest of the FT8/FT4 QSO itself.

    Identify the decode by `seq` (from the `decodes` tool) or by exact `message`
    text (the most recent matching buffered decode is used). `modifiers` may be a
    name or list (shift, ctrl/cmd, alt, meta, keypad, group) to mimic
    modifier-clicks.
    """
    _require_tx("reply")
    decode = _find_decode(seq, message)
    if decode is None:
        raise ValueError(
            "No matching buffered decode. Pass a `seq` from the `decodes` tool, or an "
            "exact `message`. Note WSJT-X only honours a Reply that matches a prior "
            "CQ/QRZ decode."
        )
    mods = methods.resolve_modifiers(modifiers)
    result = _dispatch(
        protocol.build_reply,
        instance,
        time_ms=decode.get("time_ms"),
        snr=int(decode.get("snr", 0)),
        delta_time=float(decode.get("delta_time", 0.0)),
        delta_frequency=int(decode.get("delta_frequency", 0)),
        mode=decode.get("mode") or "",
        message=decode.get("message") or "",
        low_confidence=bool(decode.get("low_confidence", False)),
        modifiers=mods,
    )
    return {
        "operation": "reply",
        "answered": decode.get("message"),
        "seq": decode.get("seq"),
        **result,
    }


def _find_decode(seq: int | None, message: str | None) -> dict | None:
    items = _wsjtx.read_decodes(None)
    if seq is not None:
        return next((d for d in items if d.get("seq") == seq), None)
    if message is not None:
        for d in reversed(items):
            if (d.get("message") or "").strip() == message.strip():
                return d
    return None


# --- free_text (send=true is TRANSMIT-GATED) ---------------------------------


@mcp.tool()
def free_text(text: str = "", send: bool = False, instance: str | None = None) -> dict:
    """Set the free-text (Tx5) message; with ``send=true`` **initiates TX** (gated).

    Setting the text alone (send=false) is safe and always allowed. With
    send=true the message is transmitted — that keys the radio, so it requires
    WSJTX_CALLSIGN. An empty `text` with send=true sends the *current* free text
    unchanged; empty text with send=false clears it.
    """
    if send:
        _require_tx("free_text(send=true)")
    result = _dispatch(protocol.build_free_text, instance, text=text, send=send)
    return {"operation": "free_text", "send": send, "text": text, **result}


# --- transmit (halt only — UDP cannot enable Tx) -----------------------------


@mcp.tool()
def transmit(operation: str = "halt", instance: str | None = None) -> dict:
    """Stop transmitting. (WSJT-X's UDP protocol can halt but cannot *enable* Tx.)

    operations:
      - halt: stop immediately (takes you off the air now).
      - halt_auto: stop at the end of the current transmission period.

    Always allowed — halting only ever takes you *off* the air. To *start* a
    transmission use `reply` (answer a CQ) or `free_text` with send=true.
    """
    if operation == "halt":
        result = _dispatch(protocol.build_halt_tx, instance, auto_tx_only=False)
    elif operation == "halt_auto":
        result = _dispatch(protocol.build_halt_tx, instance, auto_tx_only=True)
    else:
        raise methods.UnknownOperation("operation must be one of: halt, halt_auto")
    return {"operation": operation, **result}


# --- configure (mode/submode/etc — NOT dial frequency) -----------------------


@mcp.tool()
def configure(
    mode: str = "",
    submode: str = "",
    frequency_tolerance: int | None = None,
    fast_mode: bool = False,
    tr_period: int | None = None,
    rx_df: int | None = None,
    dx_call: str = "",
    dx_grid: str = "",
    generate_messages: bool = False,
    instance: str | None = None,
) -> dict:
    """Set operating parameters via a ``Configure`` message (no transmit).

    Sets: mode, submode, frequency tolerance, fast mode, T/R period, Rx DF, DX
    call, DX grid, and whether to regenerate the standard messages. Empty string
    = "no change" for text fields; ``None`` = "no change" for the numeric fields.

    IMPORTANT caveats:
      - There is **no dial-frequency control** over UDP. QSY is a rig-control
        concern (Hamlib/CAT or the WSJT-X UI), not this tool.
      - The protocol has no "no change" for the two booleans, so `fast_mode` and
        `generate_messages` are **always sent** (defaulting to false). Pass them
        explicitly if you care about their state.
    """
    result = _dispatch(
        protocol.build_configure,
        instance,
        mode=mode,
        submode=submode,
        frequency_tolerance=frequency_tolerance,
        fast_mode=fast_mode,
        tr_period=tr_period,
        rx_df=rx_df,
        dx_call=dx_call,
        dx_grid=dx_grid,
        generate_messages=generate_messages,
    )
    return {"operation": "configure", **result}


# --- clear (band-activity windows) -------------------------------------------


@mcp.tool()
def clear(window: str = "band", instance: str | None = None) -> dict:
    """Clear a WSJT-X decode window (no transmit).

    window: 'band' (Band Activity, default), 'rx' (Rx Frequency), or 'both'.
    """
    code = methods.window_code(window)
    result = _dispatch(protocol.build_clear, instance, window=code)
    return {"operation": "clear", "window": window, "window_code": code, **result}


# --- highlight (colour a callsign in Band Activity) --------------------------


@mcp.tool()
def highlight(
    operation: str = "set",
    callsign: str = "",
    background: Any = None,
    foreground: Any = None,
    highlight_last: bool = False,
    instance: str | None = None,
) -> dict:
    """Colour (or clear) a callsign in the Band Activity panel (no transmit).

    operations:
      - set (callsign, background, foreground, highlight_last): apply colours.
        Colours accept a name (red, yellow, …), '#RRGGBB', or [r,g,b].
      - clear (callsign): cancel highlighting for one callsign (sends an invalid
        colour).
      - clear_all: cancel every highlight at once.

    Keep the number of active highlights modest (a rough cap of ~100) so WSJT-X
    decoding performance isn't impacted.
    """
    if operation == "clear_all":
        result = _dispatch(
            protocol.build_highlight_callsign,
            instance,
            callsign=methods.CLEAR_ALL_CALLSIGN,
            background=None,
            foreground=None,
            highlight_last=False,
        )
        return {"operation": "clear_all", **result}
    if not callsign:
        raise ValueError("highlight requires a `callsign`.")
    if operation == "clear":
        bg = fg = None
    elif operation == "set":
        bg = methods.parse_color(background)
        fg = methods.parse_color(foreground)
    else:
        raise methods.UnknownOperation("operation must be one of: set, clear, clear_all")
    result = _dispatch(
        protocol.build_highlight_callsign,
        instance,
        callsign=callsign,
        background=bg,
        foreground=fg,
        highlight_last=methods.as_bool(highlight_last),
    )
    return {"operation": operation, "callsign": callsign, **result}


# --- location (session grid override) ----------------------------------------


@mcp.tool()
def location(grid: str, instance: str | None = None) -> dict:
    """Override the session Maidenhead grid (4- or 6-character). No transmit.

    Session-lifetime only — does not change the persistent setting. Intended for
    mobile/portable operation where the grid changes during a session.
    """
    result = _dispatch(protocol.build_location, instance, location=grid)
    return {"operation": "location", "grid": grid, **result}


# --- switch_config (named WSJT-X configuration) ------------------------------


@mcp.tool()
def switch_config(name: str, instance: str | None = None) -> dict:
    """Switch WSJT-X to a named configuration (which must already exist). No transmit."""
    result = _dispatch(protocol.build_switch_configuration, instance, name=name)
    return {"operation": "switch_config", "name": name, **result}


# --- escape hatch ------------------------------------------------------------


@mcp.tool()
def wsjtx_call(
    message: str,
    fields: dict | None = None,
    instance: str | None = None,
) -> dict:
    """Escape hatch: build and send any WSJT-X message type by name.

    `message` is a type name (heartbeat, clear, reply, close, replay, halt_tx,
    free_text, location, highlight, switch_configuration, configure). `fields` is
    a dict of builder arguments for that type (see protocol.build_* signatures),
    e.g. message="configure", fields={"mode":"FT8","rx_df":1500}.

    The same transmit gate applies: a keying message — `reply`, or `free_text`
    with send=true — is refused unless WSJTX_CALLSIGN is set.
    """
    key = message.strip().lower()
    spec = methods.RAW_BUILDERS.get(key)
    if spec is None:
        raise methods.UnknownOperation(
            f"Unknown message '{message}'. Valid: {', '.join(sorted(set(methods.RAW_BUILDERS)))}."
        )
    builder, is_tx = spec
    fields = fields or {}
    if is_tx(fields):
        _require_tx(f"wsjtx_call({message})")
    result = _dispatch(builder, instance, **fields)
    return {"message": protocol.TYPE_NAMES.get(_type_for(key), key), "fields": fields, **result}


def _type_for(key: str) -> int:
    builder = methods.RAW_BUILDERS[key][0]
    # Map builder back to a type number for a tidy echo (best-effort).
    return {
        protocol.build_heartbeat: protocol.HEARTBEAT,
        protocol.build_clear: protocol.CLEAR,
        protocol.build_reply: protocol.REPLY,
        protocol.build_close: protocol.CLOSE,
        protocol.build_replay: protocol.REPLAY,
        protocol.build_halt_tx: protocol.HALT_TX,
        protocol.build_free_text: protocol.FREE_TEXT,
        protocol.build_location: protocol.LOCATION,
        protocol.build_highlight_callsign: protocol.HIGHLIGHT_CALLSIGN,
        protocol.build_switch_configuration: protocol.SWITCH_CONFIGURATION,
        protocol.build_configure: protocol.CONFIGURE,
    }.get(builder, -1)


def main() -> None:
    """Console-script entry point (wired up in pyproject.toml's [project.scripts])."""
    mcp.run()


if __name__ == "__main__":
    main()
