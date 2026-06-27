<!-- mcp-name: io.github.sbrunner-atx/wsjtx-mcp -->

# wsjtx-mcp

An [MCP](https://modelcontextprotocol.io) server that controls **WSJT-X**
(FT8/FT4/JT65/MSK144/Q65/WSPR…) from MCP clients such as Claude Desktop and the
MCP Inspector.

It is the weak-signal leg of an "operate → log" trio for amateur radio:

- **[fldigi-mcp](https://github.com/sbrunner-atx/fldigi-mcp)** — operate broad
  digital modes via fldigi (XML-RPC).
- **[contest-mcp](https://github.com/sbrunner-atx/contest-mcp)** — log QSOs to
  N3FJP (TCP API).
- **wsjtx-mcp** *(this one)* — operate the FT8/FT4 weak-signal world via WSJT-X
  (UDP message protocol).

> ⚠️ **Experimental (v0.1).** Transmit is gated behind your callsign and you keep
> the operator in command. Read the [Transmit safety](#transmit-safety) section.

## How it is different

WSJT-X does **not** offer a request/response API. It *broadcasts* state over UDP
(`Status`, `Decode`, `QSOLogged`, `Heartbeat`, …) and honours a small set of
inbound *control* messages. So this server runs a **background UDP listener** that
continuously parses datagrams and keeps the latest status, a buffer of decodes,
and completed QSOs — you read those, and nudge WSJT-X with control messages.

Consequences worth knowing up front:

- **No dial-frequency control over UDP.** You can read the dial frequency from
  `Status`, and set mode/sub-mode/Rx DF/T-R period via `configure`, but **QSY is a
  rig-control concern** (Hamlib/CAT or the UI), not this server.
- **You can start and halt Tx, but cannot toggle "Enable Tx".** Transmission is
  *started* by answering a CQ (`reply`) or by `free_text` with `send=true`, and
  *stopped* by `transmit halt`. There is no UDP command for the "Enable Tx",
  "Auto Seq", "Call 1st", or "Hold Tx Freq" checkboxes — those stay UI settings.
- **`reply` gives hands-free QSOs only when WSJT-X's "Auto Seq" is on.** A `reply`
  is equivalent to double-clicking a CQ; with **Auto Seq enabled** (the usual
  FT8/FT4 default) WSJT-X then sequences the whole exchange to `QSOLogged` with no
  further calls. With Auto Seq *off*, `reply` starts only the first transmission.
- **Best for search-and-pounce, weak for RUN.** The API is built to *answer* CQs
  (and only CQ/QRZ decodes), so S&P is fully automatable. It has no clean way to
  drive a repeating *call-CQ* (RUN) cycle — that needs WSJT-X's own "Enable Tx",
  or a `free_text` CQ re-sent each period.

## Requirements

- WSJT-X 2.1 through 3.x — the UDP message protocol is **schema 3 / Qt_5_4** and
  has been stable across those releases (verified live against WSJT-X **3.0.2**).
- In WSJT-X: **Settings → Reporting → UDP Server**
  - **UDP Server** = the host running this server (default `127.0.0.1`), **port
    `2237`**.
  - **Accept UDP requests** = **ON** to allow *control* (it is OFF by default).
    Observing decodes/status works without it; commanding does not.

## Install (Claude Desktop)

Download the `wsjtx-mcp.mcpb` from the
[latest release](https://github.com/sbrunner-atx/wsjtx-mcp/releases) and
double-click it, or drag it onto Claude Desktop → Settings → Extensions. Fill in
the settings form (callsign, host, port). See [docs/INSTALL.md](docs/INSTALL.md).

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `WSJTX_HOST` | `127.0.0.1` | UDP address to **bind/listen** on. |
| `WSJTX_PORT` | `2237` | WSJT-X UDP Server port. |
| `WSJTX_CALLSIGN` | _(empty)_ | Operator callsign — **the single transmit gate**. Blank = receive-only. |
| `WSJTX_MULTICAST` | _(off)_ | Optional multicast group to join (coexist with other UDP consumers). |
| `WSJTX_INSTANCE` | _(auto)_ | Target a specific WSJT-X `Id` when several instances broadcast. |

Host/port are **where this server listens**; control replies are sent back to the
address each datagram arrived from.

## Tools

| Tool | Kind | What it does |
| --- | --- | --- |
| `status` | observe | Latest `Status` snapshot + listener/instance health. |
| `diagnostics` | observe | Host/network + bind status + datagram counts + gate state. |
| `decodes` | observe/nudge | `read` / `drain` (poll new) / `clear_local` / `replay`. The RX plane. |
| `log` | observe | Buffered completed QSOs (`QSOLogged` + `LoggedADIF`) → feed N3FJP. |
| `reply` | **transmit** | Answer a buffered CQ/QRZ decode (auto-sequences the QSO when WSJT-X "Auto Seq" is on). |
| `free_text` | **transmit** if `send` | Set the Tx5 free-text message; `send=true` keys the radio. |
| `transmit` | control | `halt` / `halt_auto` — stop transmitting (UDP can't *enable* Tx). |
| `configure` | control | Mode/sub-mode/Rx DF/T-R period/freq-tol/DX call+grid. **No dial freq.** |
| `clear` | control | Clear the Band Activity / Rx Frequency windows. |
| `highlight` | control | Colour or clear a callsign in Band Activity. |
| `location` | control | Override the session Maidenhead grid. |
| `switch_config` | control | Switch to a named WSJT-X configuration. |
| `annotate` | control | Set a Fox/Hound sort-order annotation for a DX call (niche, DXpedition). |
| `wsjtx_call` | escape hatch | Build & send any message type by name (gate still applies). |

## Transmit safety

The **callsign is the single transmit gate**, exactly as in fldigi-mcp. With
`WSJTX_CALLSIGN` blank the server is **receive-only**: it refuses every
transmit-initiating message — `reply`, `free_text` with `send=true`, and any
keying message via `wsjtx_call`. `transmit halt`, `clear`, `configure`,
`highlight`, `location`, `replay`, and all reads are always available (they don't
put you on the air; halt takes you *off*).

Beyond that gate:

- Per-transmit approval comes from the Claude Desktop tool-permission prompt —
  lean on it for human-in-the-loop control.
- WSJT-X's own **Tx Watchdog** and the `Tx Enabled` / `Transmitting` flags
  (surfaced in `status`) are extra safety signals.
- Operating under **Part 97 automatic/remote control** is the operator's
  responsibility: ensure station identification and a control operator who can
  intervene.

## Running alongside other UDP tools

Only one process can normally own UDP `2237` on a host. If JTAlert, GridTracker,
or N1MM already consume it, either point WSJT-X's *secondary* UDP server here, use
a **multicast** group (`WSJTX_MULTICAST`) so several listeners coexist, or run
this server on a different host. To reach a WSJT-X on **another machine**, install
the [`mcp-host-bridge`](https://github.com/sbrunner-atx/mcp-host-bridge) tool
(`mcp-host-bridge install wsjtx --to <rig-host>`) and set `WSJTX_PORT=2238` —
sandboxed MCP clients reach only loopback, and the bridge does the LAN hop. See
[docs/REMOTE-HOST.md](docs/REMOTE-HOST.md).

## Development

```sh
uv sync
uv run ruff check .
uv run pytest
```

The protocol codec is pure standard library and unit-tested against byte
fixtures, so the tests need no running WSJT-X. A `smoke_test.py` proves a live
WSJT-X is reachable receive-only. The field-tested message reference lives in
[docs/WSJTX-API.md](docs/WSJTX-API.md).

## License

MIT © 2026 Stefan Brunner (AE5VG)
