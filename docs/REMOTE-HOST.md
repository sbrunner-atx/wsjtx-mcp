# Reaching a WSJT-X on another computer (UDP host bridge)

Sandboxed MCP clients — notably Claude Desktop — let their connector subprocess
reach only `127.0.0.1` (loopback), **not LAN IP addresses**, even with macOS
*Privacy & Security → Local Network* toggled on. So if WSJT-X runs on a different
machine than wsjtx-mcp, the server cannot talk to it directly.

The fix is a small **UDP relay** that runs *outside* the sandbox on the
wsjtx-mcp host, bridges the LAN to loopback, and routes WSJT-X's broadcasts in
and your control replies back out. WSJT-X's protocol is connectionless and
*bidirectional*, so this needs a UDP-aware relay (`tools/udp_relay.py` in this
repo, the UDP sibling of the TCP `mcp-host-bridge` relay used by fldigi-mcp /
contest-mcp).

## Topology

```
  remote WSJT-X                  bridge host (Mac)                 wsjtx-mcp
  Settings → Reporting           udp_relay.py                      (loopback only)
  UDP Server =          ──►   --listen 0.0.0.0:2237   ──►   --deliver 127.0.0.1:2238
  <bridge-LAN-IP> : 2237     (LAN socket A)                 WSJTX_HOST=127.0.0.1
                             (loopback socket B)            WSJTX_PORT=2238
  control replies       ◄──   B → A → back to the remote WSJT-X
```

- WSJT-X (remote) sends its UDP datagrams to the **bridge host's LAN IP**, port
  `2237`.
- The relay learns the remote peer from the first datagram and forwards
  everything to wsjtx-mcp on `127.0.0.1:2238`.
- wsjtx-mcp's control replies go back to the relay's loopback socket, which sends
  them on to the remote WSJT-X — exactly the address each datagram came from.

## Run it

```sh
python3 ~/.mcp-host-bridge/udp_relay.py run \
  --listen 0.0.0.0:2237 \
  --deliver 127.0.0.1:2238
```

Then set wsjtx-mcp's config to `WSJTX_HOST=127.0.0.1`, `WSJTX_PORT=2238`, and in
the remote WSJT-X set **UDP Server** to the bridge host's LAN IP, port `2237`
(and tick **Accept UDP requests** for control).

## Run it under launchd (macOS, auto-start)

Save as `~/Library/LaunchAgents/com.mcp-host-bridge.wsjtx.plist` and
`launchctl load` it (mirrors the existing TCP bridge agents; uses the system
`/usr/bin/python3`, so no venv/PATH dependency):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.mcp-host-bridge.wsjtx</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/YOU/.mcp-host-bridge/udp_relay.py</string>
        <string>run</string>
        <string>--listen</string>
        <string>0.0.0.0:2237</string>
        <string>--deliver</string>
        <string>127.0.0.1:2238</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>/tmp/mcp-host-bridge-wsjtx.log</string>
    <key>StandardErrorPath</key><string>/tmp/mcp-host-bridge-wsjtx.err</string>
</dict>
</plist>
```

```sh
launchctl load ~/Library/LaunchAgents/com.mcp-host-bridge.wsjtx.plist
# to update args later:
launchctl unload ~/Library/LaunchAgents/com.mcp-host-bridge.wsjtx.plist && \
launchctl load   ~/Library/LaunchAgents/com.mcp-host-bridge.wsjtx.plist
```

## Notes

- Run the relay on a **different loopback port** (`2238`) than the LAN port
  (`2237`) so the relay's LAN socket and wsjtx-mcp's listener don't collide.
- For a **local** WSJT-X (same machine), you don't need the relay at all — point
  wsjtx-mcp straight at `127.0.0.1:2237`.
- Multicast is an alternative to the relay when every consumer is on the same
  LAN segment: set `WSJTX_MULTICAST` and WSJT-X's UDP Server to the same group.
