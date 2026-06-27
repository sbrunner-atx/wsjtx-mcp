# Changelog

All notable changes to **wsjtx-mcp** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-06-26

Initial **experimental** release.

### Added
- Standard-library Qt `QDataStream` codec (schema 3 / Qt_5_4, big-endian,
  double-precision floats) covering ints, bool, double, utf8/QByteArray
  (null vs. empty), `QTime`, `QDateTime`, and `QColor`.
- Full WSJT-X message catalog (types 0–15): decoders for the broadcast messages
  (Heartbeat, Status, Decode, Clear, QSOLogged, WSPRDecode, LoggedADIF, Close)
  and builders for the control messages (Heartbeat, Clear, Reply, Close, Replay,
  HaltTx, FreeText, Location, HighlightCallsign, SwitchConfiguration, Configure).
- Background UDP listener tracking the latest Status, a Decode ring buffer with
  drain-since-last-poll semantics, completed QSOs (QSOLogged paired with ADIF),
  and a per-instance registry (Id → source address) for targeting control.
- Grouped MCP tools: `status`, `diagnostics`, `decodes`, `log`, `reply`,
  `free_text`, `transmit`, `configure`, `clear`, `highlight`, `location`,
  `switch_config`, and the `wsjtx_call` escape hatch.
- **Callsign transmit gate**: with `WSJTX_CALLSIGN` blank the server is
  receive-only and refuses every transmit-initiating message.
- `udp_relay.py` (mcp-host-bridge, UDP edition) for reaching a WSJT-X on another
  host from a loopback-only MCP client.
- Verified live against WSJT-X (reported version 3.0.2, schema 2 header / max
  schema 3): receive + decode of real Status/Heartbeat datagrams, target
  resolution, and an accepted control round-trip (Replay). Golden byte fixtures
  from that session are checked in.

### Known limitations
- No dial-frequency control over UDP (QSY is a rig-control concern).
- Cannot "Enable Tx" over UDP — transmission is initiated by `reply` or
  `free_text` send, and only halted via `transmit`.
- `Configure` cannot express "no change" for its two booleans (`fast_mode`,
  `generate_messages`), so they are always sent.
