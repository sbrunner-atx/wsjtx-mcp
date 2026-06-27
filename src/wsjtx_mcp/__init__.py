"""wsjtx-mcp — control WSJT-X (FT8/FT4/JT65/MSK144/Q65/WSPR) from MCP clients.

WSJT-X exposes a one-way-ish **UDP message protocol** (Qt ``QDataStream``, schema
3 / Qt_5_4, big-endian) rather than a request/response API: it *broadcasts*
``Status``, ``Decode``, ``QSOLogged`` and friends as state changes, and honours a
small set of inbound *control* messages (``Reply``, ``FreeText``, ``HaltTx``,
``Configure`` …) only when "Accept UDP requests" is enabled.

This package speaks that protocol directly with Python's standard-library
:mod:`socket` and a hand-rolled ``QDataStream`` codec — no third-party wrapper —
and presents it to MCP clients (Claude Desktop, the MCP Inspector) as a small set
of logically-grouped tools.

It is the weak-signal leg of an "operate → log" trio alongside ``fldigi-mcp``
(broad digital modes) and ``contest-mcp`` (N3FJP logging).
"""

__version__ = "0.1.0"
