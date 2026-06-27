# Reaching a WSJT-X on another computer (UDP host bridge)

Sandboxed MCP clients — notably Claude Desktop — let their connector subprocess
reach only `127.0.0.1` (loopback), **not LAN IP addresses**, even with macOS
*Privacy & Security → Local Network* toggled on. So if WSJT-X runs on a different
machine than wsjtx-mcp, the server cannot talk to it directly.

The fix is a small **UDP relay** that runs *outside* the sandbox on the
wsjtx-mcp host, bridges the LAN to loopback, and routes WSJT-X's broadcasts in
and your control replies back out. WSJT-X's protocol is connectionless and
*bidirectional*, so this needs a UDP-aware relay — provided by the
**[`mcp-host-bridge`](https://github.com/sbrunner-atx/mcp-host-bridge)** tool
(the same loopback bridge used for fldigi / N3FJP, which gained a UDP mode and a
built-in `wsjtx` preset in v0.2.0).

## Topology

```
  remote WSJT-X                  bridge host (Mac)                 wsjtx-mcp
  Settings → Reporting           mcp-host-bridge (wsjtx)           (loopback only)
  UDP Server =          ──►   listen 0.0.0.0:2237     ──►   deliver 127.0.0.1:2238
  <bridge-LAN-IP> : 2237     (LAN socket)                   WSJTX_HOST=127.0.0.1
                             (loopback socket)              WSJTX_PORT=2238
  control replies       ◄──   loopback → LAN → back to the remote WSJT-X
```

- WSJT-X (remote) sends its UDP datagrams to the **bridge host's LAN IP**, port
  `2237`.
- The bridge learns the remote peer from the first datagram and forwards
  everything to wsjtx-mcp on `127.0.0.1:2238`.
- wsjtx-mcp's control replies go back to the bridge's loopback socket, which sends
  them on to the remote WSJT-X — exactly the address each datagram came from.

## Set it up with mcp-host-bridge

Install the bridge (no clone needed):

```sh
uvx mcp-host-bridge --help          # or: pipx install mcp-host-bridge
```

…or grab a per-OS binary from the
[mcp-host-bridge releases](https://github.com/sbrunner-atx/mcp-host-bridge/releases).

Then install the persistent `wsjtx` bridge service (cross-platform — launchd on
macOS, systemd on Linux, a Scheduled Task on Windows; `netsh portproxy` is
TCP-only and is skipped for UDP automatically):

```sh
mcp-host-bridge install wsjtx --to <remote-wsjtx-host>
# listens 0.0.0.0:2237 (LAN) and delivers 127.0.0.1:2238 (loopback).
# --to is an optional hint; the remote peer is auto-learned from the first datagram.

mcp-host-bridge status   wsjtx     # check it
mcp-host-bridge uninstall wsjtx    # remove it
```

**Critical wsjtx-mcp config for the bridged case:** set

- `WSJTX_HOST=127.0.0.1`
- **`WSJTX_PORT=2238`** — the bridge's *deliver* port, **not** the default `2237`
  (the bridge's own LAN socket occupies `2237` on that host),

and in the remote WSJT-X set **Settings → Reporting → UDP Server** to the bridge
host's LAN IP, port `2237` (and tick **Accept UDP requests** for control).

## Notes

- The bridge uses a **different loopback port** (`2238`) than the LAN port
  (`2237`) so its LAN socket and wsjtx-mcp's listener don't collide. Only the
  remote/bridged case uses `2238`.
- For a **local** WSJT-X (same machine), you don't need the bridge at all — point
  wsjtx-mcp straight at `127.0.0.1:2237` (the default).
- Multicast is an alternative to the bridge when every consumer is on the same
  LAN segment: set `WSJTX_MULTICAST` and WSJT-X's UDP Server to the same group.
- History: earlier wsjtx-mcp builds shipped a standalone `tools/udp_relay.py`;
  that relay now lives in `mcp-host-bridge` and the bundled copy has been retired.
