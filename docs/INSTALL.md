# Installing wsjtx-mcp

## 1. Enable WSJT-X's UDP Server

In WSJT-X: **Settings → Reporting → UDP Server**.

- **UDP Server**: the host running wsjtx-mcp. For a local setup leave it at
  `127.0.0.1`.
- **UDP Server port number**: `2237` (the default).
- **Accept UDP requests**: **tick this** if you want wsjtx-mcp to *control*
  WSJT-X (answer CQs, set free text, configure, etc.). It is **off by default**.
  Observing decodes and status works without it; commanding does not.

> Tip: if JTAlert / GridTracker / N1MM already use port 2237, see
> [Running alongside other UDP tools](#running-alongside-other-udp-tools).

## 2a. Install as a Claude Desktop extension (.mcpb)

1. Download `wsjtx-mcp.mcpb` from the
   [latest release](https://github.com/sbrunner-atx/wsjtx-mcp/releases).
2. If you previously installed an older build, **remove it first** (Settings →
   Extensions → uninstall, and wait for its tile to disappear) so the swap takes
   effect.
3. Double-click the `.mcpb`, or drag it onto Claude Desktop → Settings →
   Extensions.
4. Fill in the settings form:
   - **Operator callsign** — your licensed callsign. Leave **blank for
     receive-only**; set it to enable transmit.
   - **Listen host / port** — usually `127.0.0.1` / `2237`.
5. **Quit and reopen Claude Desktop** (Cmd-Q) so the new tools load.

## 2b. Install from PyPI (any MCP client)

```sh
uvx wsjtx-mcp        # or: pipx run wsjtx-mcp
```

Add it to your client's MCP config with the environment variables from the
[README configuration table](../README.md#configuration), e.g.:

```json
{
  "mcpServers": {
    "wsjtx-mcp": {
      "command": "uvx",
      "args": ["wsjtx-mcp"],
      "env": { "WSJTX_CALLSIGN": "", "WSJTX_HOST": "127.0.0.1", "WSJTX_PORT": "2237" }
    }
  }
}
```

## 3. Verify

Ask your client to run the **`status`** tool. You should see the current dial
frequency, mode, and the discovered instance within ~15 seconds (WSJT-X sends a
Heartbeat every 15 s plus a Status on each state change). If nothing appears, run
**`diagnostics`** — it reports whether the UDP listener bound and how many
datagrams have arrived.

## Running alongside other UDP tools

Only one process can own UDP `2237` on a host. Options:

- Point WSJT-X's **secondary** UDP server at wsjtx-mcp's host:port.
- Use a **multicast** group: set the same group in WSJT-X's UDP Server and in
  `WSJTX_MULTICAST`, so several listeners coexist.
- Run wsjtx-mcp on a different host than WSJT-X, bridged by the
  [`mcp-host-bridge`](https://github.com/sbrunner-atx/mcp-host-bridge) tool
  (`mcp-host-bridge install wsjtx --to <rig-host>`, then `WSJTX_PORT=2238`) —
  see [REMOTE-HOST.md](REMOTE-HOST.md).

## Transmit safety

The **callsign is the single transmit gate**. With it blank, wsjtx-mcp is
receive-only and refuses every transmit-initiating message. Per-transmit approval
also comes from your client's tool-permission prompt. You — the licensed control
operator — remain responsible for lawful operation (station ID, ability to
intervene, Part 97 automatic/remote-control rules).
