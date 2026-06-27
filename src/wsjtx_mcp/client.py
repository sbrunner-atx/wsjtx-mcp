"""A small, dependency-free UDP client for WSJT-X's message protocol.

Unlike a request/response API, WSJT-X mostly *broadcasts*: it pushes ``Status``,
``Decode``, ``QSOLogged`` and friends on state changes, and accepts a limited set
of inbound control messages.  So this client is built around a **background
listener thread** that binds the UDP port, parses every datagram, and maintains:

* the latest ``Status`` snapshot,
* a bounded ring buffer of ``Decode`` / ``WSPRDecode`` lines (the RX data plane),
* a bounded buffer of completed QSOs (``QSOLogged`` paired with ``LoggedADIF``),
* a registry of discovered WSJT-X **instances** — each instance's unique ``Id``
  and the *source address* its datagrams arrived from, which is exactly where any
  control reply must be sent.

You cannot command an instance until you have *received* a datagram from it (to
learn its ``Id`` and address); the listener handles that automatically.

The rest of the project talks to WSJT-X only through :class:`WsjtxClient`, never
to raw sockets, which keeps the protocol logic (in :mod:`wsjtx_mcp.protocol`)
unit-testable without a socket.
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from collections import deque

from wsjtx_mcp import diag, protocol
from wsjtx_mcp.qdatastream import DecodeError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 2237


class WsjtxError(RuntimeError):
    """Raised when the listener can't bind, or a command has no target."""


class WsjtxClient:
    """A UDP listener + sender for one or more WSJT-X instances."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        multicast: str = "",
        decode_maxlen: int = 2000,
        qso_maxlen: int = 200,
    ) -> None:
        self.host = host or DEFAULT_HOST
        self.port = int(port or DEFAULT_PORT)
        self.multicast = multicast.strip()

        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._closed = False
        self._bound = False
        self._bind_error: str | None = None
        self._started_at: float | None = None

        # state
        self._status: dict | None = None
        self._instances: dict[str, dict] = {}
        self._decodes: deque[dict] = deque(maxlen=decode_maxlen)
        self._decode_seq = 0
        self._last_drained = 0
        self._qso: deque[dict] = deque(maxlen=qso_maxlen)
        self._negotiated_schema = protocol.SCHEMA
        self._last_addr: tuple[str, int] | None = None
        self._stats: dict = {"datagrams": 0, "by_type": {}, "last_datagram_at": None}

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        """Bind the UDP socket and spawn the listener thread (idempotent).

        Bind failures are captured (not raised) so the server can still load and
        report the problem through ``diagnostics``; :meth:`ensure_started` re-tries
        on demand.
        """
        with self._lock:
            if self._bound:
                return
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if hasattr(socket, "SO_REUSEPORT"):
                    try:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                    except OSError:
                        pass
                bind_host = "" if self.multicast else self.host
                sock.bind((bind_host, self.port))
                if self.multicast:
                    mreq = struct.pack(
                        "=4sl", socket.inet_aton(self.multicast), socket.INADDR_ANY
                    )
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                sock.settimeout(1.0)
            except OSError as exc:
                self._bind_error = diag.bind_error(self.host, self.port, exc)
                return
            self._sock = sock
            self._bound = True
            self._bind_error = None
            self._closed = False
            self._started_at = time.time()
            self._thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._thread.start()

    def ensure_started(self) -> None:
        if not self._bound:
            self.start()
        if not self._bound:
            raise WsjtxError(self._bind_error or "WSJT-X UDP listener is not bound.")

    def stop(self) -> None:
        self._closed = True
        with self._lock:
            sock, self._sock = self._sock, None
            self._bound = False
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    @property
    def bound(self) -> bool:
        return self._bound

    @property
    def bind_error(self) -> str | None:
        return self._bind_error

    @property
    def negotiated_schema(self) -> int:
        return self._negotiated_schema

    # -- listener -------------------------------------------------------------

    def _reader_loop(self) -> None:
        sock = self._sock
        if sock is None:
            return
        while not self._closed:
            try:
                data, addr = sock.recvfrom(65535)
            except TimeoutError:
                continue
            except OSError:
                break
            self._handle(data, addr)

    def _handle(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            msg = protocol.parse(data)
        except DecodeError:
            return
        with self._lock:
            self._stats["datagrams"] += 1
            self._stats["last_datagram_at"] = time.time()
            counts = self._stats["by_type"]
            counts[msg.type_name] = counts.get(msg.type_name, 0) + 1
            self._last_addr = addr
            self._route(msg, addr)

    def _route(self, msg: protocol.Message, addr: tuple[str, int]) -> None:
        if msg.id is not None:
            inst = self._instances.setdefault(msg.id, {})
            inst["addr"] = addr
            inst["last_seen"] = time.time()

        if msg.type == protocol.HEARTBEAT:
            inst = self._instances[msg.id]
            inst["max_schema"] = msg.fields.get("max_schema")
            inst["version"] = msg.fields.get("version")
            inst["revision"] = msg.fields.get("revision")
            inst["last_heartbeat"] = time.time()
            peer_max = msg.fields.get("max_schema")
            if isinstance(peer_max, int):
                self._negotiated_schema = min(protocol.SCHEMA, peer_max)
        elif msg.type == protocol.STATUS:
            self._status = {"instance": msg.id, **msg.fields}
        elif msg.type in (protocol.DECODE, protocol.WSPR_DECODE):
            self._decode_seq += 1
            kind = "wspr" if msg.type == protocol.WSPR_DECODE else "decode"
            self._decodes.append(
                {"seq": self._decode_seq, "instance": msg.id, "kind": kind, **msg.fields}
            )
        elif msg.type == protocol.CLEAR:
            self._decodes.clear()
        elif msg.type == protocol.QSO_LOGGED:
            self._qso.append({"instance": msg.id, "qso": msg.fields, "adif": None})
        elif msg.type == protocol.LOGGED_ADIF:
            adif = msg.fields.get("adif_text")
            # Pair with the most recent QSOLogged from the same instance that has
            # no ADIF yet; otherwise record the ADIF on its own.
            for entry in reversed(self._qso):
                if entry["instance"] == msg.id and entry["adif"] is None:
                    entry["adif"] = adif
                    break
            else:
                self._qso.append({"instance": msg.id, "qso": None, "adif": adif})
        elif msg.type == protocol.CLOSE:
            self._instances.pop(msg.id, None)

    # -- targeting / sending --------------------------------------------------

    def instances(self) -> dict[str, dict]:
        with self._lock:
            return {k: dict(v) for k, v in self._instances.items()}

    def resolve_target(self, instance: str | None = None) -> tuple[str, tuple[str, int]]:
        """Return ``(instance_id, address)`` to send a control message to.

        Targeting order: an explicit ``instance`` argument, else (if exactly one
        instance has been seen) that one.  Raises if the target is ambiguous or
        nothing has been heard yet — you must receive a datagram first.
        """
        with self._lock:
            known = self._instances
            if instance:
                inst = known.get(instance)
                if not inst or "addr" not in inst:
                    raise WsjtxError(
                        f"No WSJT-X instance with Id {instance!r} has been heard from yet. "
                        f"Known: {sorted(known)} (wait for a Heartbeat/Status, or run "
                        f"`status`/`diagnostics`)."
                    )
                return instance, inst["addr"]
            addressable = [(k, v) for k, v in known.items() if "addr" in v]
            if not addressable:
                raise WsjtxError(
                    "No WSJT-X instance has been heard from yet — cannot target a control "
                    "message. WSJT-X must broadcast at least one Heartbeat/Status first "
                    "(check that its UDP Server points at this host:port)."
                )
            if len(addressable) > 1:
                raise WsjtxError(
                    f"Multiple WSJT-X instances are active: {[k for k, _ in addressable]}. "
                    f"Pass `instance` to choose one."
                )
            chosen_id, inst = addressable[0]
            return chosen_id, inst["addr"]

    def sendto(self, datagram: bytes, addr: tuple[str, int]) -> None:
        self.ensure_started()
        assert self._sock is not None
        self._sock.sendto(datagram, addr)

    # -- state accessors ------------------------------------------------------

    def status(self) -> dict | None:
        with self._lock:
            return dict(self._status) if self._status is not None else None

    def read_decodes(self, limit: int | None = None) -> list[dict]:
        with self._lock:
            items = list(self._decodes)
        if limit is not None and limit >= 0:
            items = items[-limit:]
        return items

    def drain_decodes(self) -> list[dict]:
        """Return decodes seen since the previous drain, and advance the cursor."""
        with self._lock:
            fresh = [d for d in self._decodes if d["seq"] > self._last_drained]
            if fresh:
                self._last_drained = fresh[-1]["seq"]
            return fresh

    def clear_local_decodes(self) -> int:
        with self._lock:
            n = len(self._decodes)
            self._decodes.clear()
            return n

    def read_qso_log(self, limit: int | None = None) -> list[dict]:
        with self._lock:
            items = list(self._qso)
        if limit is not None and limit >= 0:
            items = items[-limit:]
        return items

    def stats(self) -> dict:
        with self._lock:
            return {
                "bound": self._bound,
                "bind_error": self._bind_error,
                "listen": f"{self.host}:{self.port}",
                "multicast": self.multicast or None,
                "started_at": self._started_at,
                "negotiated_schema": self._negotiated_schema,
                "datagrams": self._stats["datagrams"],
                "by_type": dict(self._stats["by_type"]),
                "last_datagram_at": self._stats["last_datagram_at"],
                "instances": {k: dict(v) for k, v in self._instances.items()},
            }
