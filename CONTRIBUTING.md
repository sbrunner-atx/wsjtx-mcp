# Contributing

Thanks for your interest in **wsjtx-mcp**.

## Development setup

```sh
uv sync
uv run ruff check .
uv run pytest
```

The protocol layer (`qdatastream.py`, `protocol.py`, `methods.py`) is pure
standard library and unit-tested against byte fixtures — including **golden
fixtures captured from a live WSJT-X** (`tests/test_golden.py`). The tests need no
running WSJT-X.

To verify against your own station, run `uv run python smoke_test.py 22 --save`:
it binds the UDP port, decodes whatever WSJT-X broadcasts, and (with `--save`)
writes raw datagrams to `captures/` you can turn into new fixtures.

## House style

- Python 3.10+, `uv`, FastMCP, `src/` layout.
- `ruff` with `line-length = 100` (run it before pushing).
- Grouped-tools pattern: one tool per functional area taking an `operation`
  argument, plus the `wsjtx_call` escape hatch.
- Standard-library-only at runtime where possible (the only dependency is `mcp`).

## Safety

Anything that can key a transmitter must stay behind the **callsign transmit
gate**. New transmit-initiating paths must call `_require_tx(...)` and be covered
by a test that proves they are refused when `WSJTX_CALLSIGN` is blank.

## Reporting protocol discrepancies

If a field decodes wrong against your WSJT-X build, please open an issue with a
captured datagram (hex or base64) and your WSJT-X version — that is the fastest
path to a fix, and may become a new golden fixture.
