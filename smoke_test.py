#!/usr/bin/env python3
"""Phase-0 smoke test + datagram capture for wsjtx-mcp.

Goal: prove this machine can *receive* WSJT-X's UDP broadcasts and that our
standard-library QDataStream codec parses them — exactly the way the real MCP
server does. No transmit, no third-party packages.

Enable WSJT-X's UDP Server first: Settings → Reporting → UDP Server (default
127.0.0.1, port 2237). WSJT-X sends a Heartbeat every 15 s plus a Status on state
changes, so even with no radio you should see traffic within ~15 s.

Usage:

    uv run python smoke_test.py                 # listen 20 s on 127.0.0.1:2237
    uv run python smoke_test.py 30              # listen 30 s
    uv run python smoke_test.py 30 --save       # also write raw datagrams to captures/

Captured datagrams (one file per message type) make golden fixtures for the codec
tests.
"""

from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

from wsjtx_mcp import protocol
from wsjtx_mcp.qdatastream import DecodeError

HOST = os.environ.get("WSJTX_HOST", "127.0.0.1")
PORT = int(os.environ.get("WSJTX_PORT", "2237"))


def main() -> int:
    duration = 20.0
    save = "--save" in sys.argv
    for arg in sys.argv[1:]:
        if arg.replace(".", "", 1).isdigit():
            duration = float(arg)

    print(f"Binding UDP {HOST}:{PORT} for {duration:.0f}s (Ctrl-C to stop early)…")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((HOST, PORT))
    except OSError as exc:
        print(f"Could not bind: {type(exc).__name__} - {exc}")
        print("Is the port already owned by JTAlert/GridTracker, or is the host wrong?")
        return 1
    sock.settimeout(1.0)

    captures = Path(__file__).parent / "captures"
    if save:
        captures.mkdir(exist_ok=True)

    counts: dict[str, int] = {}
    seen_types: set[str] = set()
    deadline = time.time() + duration
    try:
        while time.time() < deadline:
            try:
                data, addr = sock.recvfrom(65535)
            except TimeoutError:
                continue
            try:
                msg = protocol.parse(data)
            except DecodeError as exc:
                print(f"  [unparseable {len(data)}B from {addr}] {exc}")
                continue
            counts[msg.type_name] = counts.get(msg.type_name, 0) + 1
            if msg.type_name not in seen_types:
                seen_types.add(msg.type_name)
                print(f"  first {msg.type_name:18} id={msg.id!r} from {addr[0]}:{addr[1]}")
                _print_highlights(msg)
                if save:
                    out = captures / f"{msg.type}_{msg.type_name}.bin"
                    out.write_bytes(data)
                    print(f"      saved {len(data)}B -> {out.name}")
    finally:
        sock.close()

    print()
    if not counts:
        print("No datagrams received. Check WSJT-X Settings → Reporting → UDP Server "
              f"= {HOST}:{PORT}, and that WSJT-X is running.")
        return 2
    print("Received:", ", ".join(f"{k}×{v}" for k, v in sorted(counts.items())))
    print("Success — this machine can receive and decode WSJT-X UDP. Ready for control.")
    return 0


def _print_highlights(msg: protocol.Message) -> None:
    f = msg.fields
    if msg.type == protocol.STATUS:
        print(f"      dial={f.get('dial_frequency')} mode={f.get('mode')} "
              f"tx_enabled={f.get('tx_enabled')} decoding={f.get('decoding')} "
              f"de={f.get('de_call')}/{f.get('de_grid')} special={f.get('special_operation_mode')}")
    elif msg.type == protocol.HEARTBEAT:
        print(f"      max_schema={f.get('max_schema')} version={f.get('version')}")
    elif msg.type in (protocol.DECODE, protocol.WSPR_DECODE):
        print(f"      {f.get('time')} snr={f.get('snr')} df={f.get('delta_frequency')} "
              f"msg={f.get('message') or f.get('callsign')!r}")


if __name__ == "__main__":
    sys.exit(main())
