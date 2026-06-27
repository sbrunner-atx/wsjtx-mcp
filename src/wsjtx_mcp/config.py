"""Runtime configuration for the WSJT-X MCP server.

Settings are read from environment variables.  In development you set these in
the Claude Desktop server entry's ``env`` block; in the packaged ``.mcpb``
desktop extension they are surfaced as a settings form and passed through as the
same environment variables.  The code therefore does not care which one set them.

Transmit policy: the **callsign is the single transmit gate**, exactly as in
``fldigi-mcp``.  If a callsign is configured, the transmit-initiating tools are
available (subject to the client's own approval prompt).  If it is blank,
transmit is impossible — the server refuses to send any message that could key
the radio (``Reply``, ``FreeText`` with ``Send=true``, or a raw keying message
via the escape hatch).  There is intentionally no separate "enable transmit"
flag — and note WSJT-X's UDP protocol cannot *enable* Tx anyway, only initiate a
specific transmission or halt one.

Host/port here are **where we bind and listen** for WSJT-X's broadcasts; control
replies are sent back to the address each datagram arrived from.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 2237


@dataclass
class Config:
    """Resolved server configuration."""

    host: str
    port: int
    callsign: str
    multicast: str
    instance: str

    @property
    def transmit_ready(self) -> bool:
        """True when transmit is permitted, i.e. a (non-blank) callsign is set."""
        return bool(self.callsign)

    @classmethod
    def from_env(cls) -> Config:
        try:
            port = int(os.environ.get("WSJTX_PORT", str(DEFAULT_PORT)))
        except ValueError:
            port = DEFAULT_PORT
        return cls(
            host=os.environ.get("WSJTX_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST,
            port=port,
            callsign=os.environ.get("WSJTX_CALLSIGN", "").strip().upper(),
            multicast=os.environ.get("WSJTX_MULTICAST", "").strip(),
            instance=os.environ.get("WSJTX_INSTANCE", "").strip(),
        )
