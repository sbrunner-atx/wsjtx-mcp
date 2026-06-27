# Changelog

All notable changes to **wsjtx-mcp** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [0.1.2] - 2026-06-27

### Added
- **`AnnotationInfo` (message type 16)** plus a new **`annotate`** tool — the
  Fox/Hound sort-order annotation for a DX call (niche DXpedition use). The
  authoritative [`WSJTX/wsjtx`](https://github.com/WSJTX/wsjtx)
  `NetworkMessage.hpp` enum runs **0–16** (`Heartbeat … AnnotationInfo`); an
  earlier draft transcribed from a stale third-party mirror stopped at
  `Configure` (15) and wrongly treated AnnotationInfo as absent. **All 17 message
  types are now implemented.**

### Fixed
- Corrected the version/compatibility wording: the UDP message protocol is
  schema 3 / Qt_5_4 and stable across WSJT-X 2.1 → 3.x (verified live against
  **3.0.2**) — earlier docs said "2.x / 2.7 schema".
- Noted the 3.0.x `Configure` behaviour: a mode/submode change may move the dial
  to that band/mode's default frequency if the current one isn't in the table.

## [0.1.1] - 2026-06-26

Docs + packaging maintenance (no `src/` logic changes; codec, listener, and the
callsign transmit-gate are unchanged).

### Changed
- **Remote-host bridging now uses the published
  [`mcp-host-bridge`](https://github.com/sbrunner-atx/mcp-host-bridge) 0.2.0**,
  which ships UDP support and a built-in `wsjtx` preset. `docs/REMOTE-HOST.md`,
  `README.md`, `INSTALL.md`, `manifest.json`, and `server.json` now point at
  `mcp-host-bridge install wsjtx --to <rig-host>` (deliver port `2238`) instead of
  a hand-run relay + plist.
- Clarified that `reply` only auto-completes a QSO when WSJT-X's **"Auto Seq"** is
  enabled (a UI setting, not UDP-controllable), and that the UDP API is strong for
  search-and-pounce but cannot drive a call-CQ RUN cycle. Updated `README.md`,
  `docs/WSJTX-API.md`, `docs/WSJTX-API-SPEC.md`, the `reply` tool docstring, and
  `manifest.json`.

### Removed
- Retired the bundled `tools/udp_relay.py` — the UDP relay now lives in the
  `mcp-host-bridge` package.

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
