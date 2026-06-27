#!/usr/bin/env python3
"""A tiny loopback-to-remote **UDP** relay for WSJT-X (mcp-host-bridge, UDP edition).

Why this exists: sandboxed MCP clients (notably Claude Desktop) reach only
``127.0.0.1`` (loopback), not LAN addresses. ``wsjtx-mcp`` therefore cannot talk
directly to a WSJT-X running on another computer. The sibling ``relay.py`` solves
this for **TCP** services (fldigi, N3FJP); WSJT-X needs a **UDP** variant because
its protocol is connectionless and *bidirectional*: WSJT-X broadcasts datagrams
*in*, and control replies must go back to the address each datagram came *from*.

Topology (remote WSJT-X → this Mac → loopback-only wsjtx-mcp)::

    remote WSJT-X                this Mac                       wsjtx-mcp
    UDP Server =      ──►   --listen 0.0.0.0:2237   ──►   --deliver 127.0.0.1:2238
    <Mac-LAN-IP>:2237       (relay LAN socket A)          (WSJTX_HOST/PORT = 127.0.0.1:2238)
                            relay loopback socket B  ◄──   control replies
                            ──►  back to remote WSJT-X

The relay keeps one LAN-facing socket (A) and one loopback socket (B):

* A datagram arriving on **A** (from the remote WSJT-X) is remembered as the
  current remote peer, then sent out of **B** to ``--deliver`` (wsjtx-mcp). To
  wsjtx-mcp, socket B *is* the WSJT-X "instance" — a single loopback peer.
* A datagram arriving on **B** (a control reply from wsjtx-mcp) is sent out of
  **A** back to the last remote peer.

Standard-library only and self-contained, so it can run from a stable path under
launchd with the system ``/usr/bin/python3`` and no venv — exactly like its TCP
sibling. Run it with::

    python3 udp_relay.py run --listen 0.0.0.0:2237 --deliver 127.0.0.1:2238

Set wsjtx-mcp's ``WSJTX_HOST=127.0.0.1`` / ``WSJTX_PORT=2238``, and point the
remote WSJT-X's UDP Server at this Mac's LAN IP, port 2237.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading

__all__ = ["serve_udp", "split_hostport", "run_main"]


def split_hostport(value: str, default_port: int) -> tuple[str, int]:
    """Split ``host`` or ``host:port`` into ``(host, port)``."""
    value = value.strip()
    if ":" in value:
        host, _, port = value.rpartition(":")
        return host, int(port)
    return value, default_port


def serve_udp(
    listen_host: str,
    listen_port: int,
    deliver_host: str,
    deliver_port: int,
    remote_host: str | None = None,
    remote_port: int | None = None,
) -> None:
    """Block forever, proxying UDP between a remote WSJT-X and a loopback MCP server.

    ``remote_host``/``remote_port`` optionally pin the remote peer; otherwise it is
    learned from the first datagram that arrives on the LAN socket (WSJT-X always
    broadcasts first, so auto-learning is the normal case).
    """
    lan = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    lan.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lan.bind((listen_host, listen_port))

    loop = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    loop.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    loop.bind(("127.0.0.1", 0))  # ephemeral loopback source toward the MCP server

    deliver = (deliver_host, deliver_port)
    pinned = (remote_host, remote_port) if remote_host and remote_port else None
    state: dict[str, tuple[str, int] | None] = {"remote": pinned}
    remote_label = f"pinned {remote_host}:{remote_port}" if pinned else "auto"
    print(
        f"mcp-host-bridge(udp): LAN {listen_host}:{listen_port} <-> "
        f"deliver {deliver_host}:{deliver_port} (remote={remote_label})",
        flush=True,
    )

    def lan_to_loop() -> None:
        while True:
            try:
                data, addr = lan.recvfrom(65535)
            except OSError:
                break
            state["remote"] = addr  # learn / refresh the remote WSJT-X peer
            try:
                loop.sendto(data, deliver)
            except OSError:
                pass

    def loop_to_lan() -> None:
        while True:
            try:
                data, _ = loop.recvfrom(65535)
            except OSError:
                break
            remote = state["remote"]
            if remote is None:
                continue  # nothing heard yet — nowhere to send the control reply
            try:
                lan.sendto(data, remote)
            except OSError:
                pass

    t1 = threading.Thread(target=lan_to_loop, daemon=True)
    t2 = threading.Thread(target=loop_to_lan, daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()


def run_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mcp-host-bridge-udp-relay")
    sub = parser.add_subparsers(dest="cmd")
    p_run = sub.add_parser("run", help="Run the UDP relay in the foreground (Ctrl-C to stop).")
    p_run.add_argument("--listen", required=True, metavar="HOST:PORT",
                       help="LAN-facing bind where the remote WSJT-X sends (e.g. 0.0.0.0:2237).")
    p_run.add_argument("--deliver", required=True, metavar="HOST:PORT",
                       help="Loopback address where wsjtx-mcp listens (e.g. 127.0.0.1:2238).")
    p_run.add_argument("--remote", metavar="HOST:PORT", default=None,
                       help="Optional: pin the remote WSJT-X peer instead of auto-learning.")
    args = parser.parse_args(argv)
    if args.cmd != "run":
        parser.error("use: udp_relay.py run --listen HOST:PORT --deliver HOST:PORT")

    lh, lp = split_hostport(args.listen, 2237)
    dh, dp = split_hostport(args.deliver, 2238)
    rh = rp = None
    if args.remote:
        rh, rp = split_hostport(args.remote, 2237)
    try:
        serve_udp(lh, lp, dh, dp, rh, rp)
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        print(f"mcp-host-bridge udp relay failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run_main())
