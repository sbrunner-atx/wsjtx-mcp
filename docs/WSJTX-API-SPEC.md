# WSJT-X UDP Protocol — Machine-Readable Spec (for wsjtx-mcp)

The structured message catalog the `wsjtx-mcp` code is built from. Deliberately
terse and unambiguous. The prose companion is [`WSJTX-API.md`](WSJTX-API.md).

Source of truth: `Network/NetworkMessage.hpp` in the authoritative
[`WSJTX/wsjtx`](https://github.com/WSJTX/wsjtx) repository (schema **3** /
`QDataStream::Qt_5_4`), cross-checked against the User Guide's "Protocol
Specifications / Reporting (UDP Server)" section and the `pywsjtx` reference
implementation. Covers all **17** message types (**0–16**, `Heartbeat …
AnnotationInfo`).

> **Verified live** against WSJT-X reporting version **3.0.2** on 2026-06-26
> (Heartbeat header schema **2**, advertised max schema **3**). Real captured
> `Status` and `Heartbeat` datagrams are committed as golden fixtures
> (`tests/test_golden.py`). A control round-trip (`Replay` → response burst) was
> also confirmed live. Items confirmed this way are flagged **[live]**.

## Transport

| Property | Value |
| --- | --- |
| Protocol | **UDP** (WSJT-X is mostly a *broadcaster*; your app binds and receives) |
| Default endpoint | `127.0.0.1:2237` (WSJT-X → Settings → Reporting → UDP Server) |
| Addressing | Unicast or multicast group |
| Byte order | **Big-endian**, Qt `QDataStream` serialization |
| Floats | **All floating-point fields are doubles** (64-bit IEEE-754) |
| Heartbeat cadence | every **15 s** (`NetworkMessage::pulse`) |
| Control prerequisite | WSJT-X **"Accept UDP requests"** must be ON (OFF by default) |
| Targeting | every control message carries the target instance `Id`; replies go to the **source address** the datagram arrived from |

## Datagram framing

```
quint32 magic = 0xADBCCBDA
quint32 schema                 (1 Qt_5_0[broken], 2 Qt_5_2, 3 Qt_5_4)
quint32 message type           (see catalog)
utf8    Id                     (first payload field of EVERY message)
…       type-specific payload
```

## Type encodings

| Type | Wire format |
| --- | --- |
| `quint8/32/64`, `qint32/64` | big-endian, fixed width |
| `bool` | 1 byte `0x00`/`0x01` |
| `double` | 8-byte IEEE-754 |
| `utf8` (QByteArray) | `quint32` length + bytes, no terminator; `0xFFFFFFFF`=null, `0`=empty (distinct) |
| `QTime` | `quint32` ms since midnight; `0xFFFFFFFF`=invalid |
| `QDateTime` | `qint64` Julian day + `quint32` ms + `quint8` timespec (0 local, 1 UTC, 2 offset→`qint32`) |
| `QColor` | `qint8` spec (0 invalid, 1 RGB) + 5×`quint16` (alpha, red, green, blue, pad); channel `c`→`c<<8\|c` |
| `0xFFFFFFFF` sentinel | "not applicable / no change" for Frequency Tolerance, T/R Period, Rx DF |

## Confidence legend

- **C** = Confirmed live (decoded from a real datagram, or a control accepted).
- **D** = Documented (field layout from `NetworkMessage.hpp`; not yet exercised
  live in this environment — e.g. no radio, so no Decode/QSOLogged were emitted).

## Kind / safety classification

- **observe** — receive-only, no datagram sent. Always allowed (`readOnlyHint`).
- **control** — sends a non-keying control datagram (never puts RF on air; e.g.
  `Configure`, `Clear`, `HaltTx`). Needs Approval tier.
- **transmit** — initiates a transmission. **Gated by `WSJTX_CALLSIGN`** (blank =
  refused). Only `Reply` and `FreeText` with `Send=true`.

---

## Message catalog

Direction: **Out** = WSJT-X→us, **In** = us→WSJT-X. "Kind" applies to the In
(actionable) messages.

### 0 · Heartbeat — Out/In — control · **C [live]**
`Id` utf8 · `Maximum schema number` quint32 · `version` utf8 · `revision` utf8.
Liveness + schema negotiation. Absent "max schema" ⇒ assume schema 2. Negotiated
outbound schema = `min(ours, peer max)`.

### 1 · Status — Out — observe · **C [live]**
`Id` · `Dial Frequency` quint64 · `Mode` utf8 · `DX call` utf8 · `Report` utf8 ·
`Tx Mode` utf8 · `Tx Enabled` bool · `Transmitting` bool · `Decoding` bool ·
`Rx DF` quint32 · `Tx DF` quint32 · `DE call` utf8 · `DE grid` utf8 ·
`DX grid` utf8 · `Tx Watchdog` bool · `Sub-mode` utf8 · `Fast mode` bool ·
`Special Operation Mode` quint8 · `Frequency Tolerance` quint32 ·
`T/R Period` quint32 · `Configuration Name` utf8 · `Tx Message` utf8.

### 2 · Decode — Out — observe · **D**
`Id` · `New` bool · `Time` QTime · `snr` qint32 · `Delta time` double ·
`Delta frequency` quint32 · `Mode` utf8 · `Message` utf8 ·
`Low confidence` bool · `Off air` bool. The RX data plane.

### 3 · Clear — Out/In — control · **D** (Out path **C [live]** via Replay burst)
Out: `Id` only. In: `Id` · `Window` quint8 (0 Band Activity, 1 Rx Freq, 2 both).

### 4 · Reply — In — **transmit** · **D**
`Id` · `Time` QTime · `snr` qint32 · `Delta time` double ·
`Delta frequency` quint32 · `Mode` utf8 · `Message` utf8 · `Low confidence` bool ·
`Modifiers` quint8. Must exactly match a prior CQ/QRZ decode; ≡ double-click.
**Initiates TX.** Full auto-completion of the QSO requires WSJT-X **"Auto Seq"**
ON (not UDP-controllable); with it off, only the first transmission is sent.

### 5 · QSOLogged — Out — observe · **D**
`Id` · `Date & Time Off` QDateTime · `DX call` · `DX grid` ·
`Tx frequency` quint64 · `Mode` · `Report sent` · `Report received` ·
`Tx power` · `Comments` · `Name` · `Date & Time On` QDateTime ·
`Operator call` · `My call` · `My grid` · `Exchange sent` ·
`Exchange received` · `ADIF Propagation mode` (all utf8 unless noted).

### 6 · Close — Out/In — control · **D**
`Id` only. Out = WSJT-X shutting down; In = ask it to close.

### 7 · Replay — In — control · **C [live]**
`Id` only. WSJT-X re-emits current Band-Activity decodes (`New=false`) + a Status.

### 8 · HaltTx — In — control (takes off air) · **D**
`Id` · `Auto Tx Only` bool (end-of-period vs immediate).

### 9 · FreeText — In — **transmit if Send** · **D**
`Id` · `Text` utf8 · `Send` bool. `Send=true` **initiates TX**.

### 10 · WSPRDecode — Out — observe · **D**
`Id` · `New` bool · `Time` QTime · `snr` qint32 · `Delta time` double ·
`Frequency` quint64 · `Drift` qint32 · `Callsign` utf8 · `Grid` utf8 ·
`Power (dBm)` qint32 · `Off air` bool.

### 11 · Location — In — control · **D**
`Id` · `Location` utf8 (Maidenhead 4/6, session override).

### 12 · LoggedADIF — Out — observe · **D**
`Id` · `ADIF text` utf8 (one-record ADIF document; forward to N3FJP).

### 13 · HighlightCallsign — In — control · **D**
`Id` · `Callsign` utf8 · `Background Color` QColor · `Foreground Color` QColor ·
`Highlight last` bool. Invalid QColor clears; keep < ~100 active.

### 14 · SwitchConfiguration — In — control · **D**
`Id` · `Configuration Name` utf8 (must already exist).

### 15 · Configure — In — control · **D**
`Id` · `Mode` utf8 · `Frequency Tolerance` quint32 · `Submode` utf8 ·
`Fast Mode` bool · `T/R Period` quint32 · `Rx DF` quint32 · `DX Call` utf8 ·
`DX Grid` utf8 · `Generate Messages` bool. Empty utf8 / `0xFFFFFFFF` = no change.
**No dial frequency.** (3.0.x note: a mode/submode change may also move the dial
to that band/mode's default frequency if the current one isn't in the table.)

### 16 · AnnotationInfo — In — control · **D**
`Id` · `DX Call` utf8 · `Sort Order Provided` bool · `Sort Order` quint32.
Fox/Hound sort-order annotation for a DX call (niche DXpedition use — score
callers so the Hound queue can be sorted). `Sort Order` `0xFFFFFFFF` removes a
call's entry. Reachable via the `annotate` tool or `wsjtx_call`.

### Enumerations

- **Special Operation Mode**: 0 NONE, 1 NA VHF, 2 EU VHF, **3 FIELD DAY**,
  4 RTTY RU, 5 WW DIGI, 6 FOX, 7 HOUND, 8 ARRL DIGI.
- **Reply.Modifiers** (bitmask): 0x00 none, 0x02 SHIFT, 0x04 CTRL/CMD, 0x08 ALT,
  0x10 META, 0x20 KEYPAD, 0x40 group-switch.

## Notes

- **`AnnotationInfo` (type 16) IS in mainline.** The authoritative
  [`WSJTX/wsjtx`](https://github.com/WSJTX/wsjtx) `Network/NetworkMessage.hpp`
  enum runs `Heartbeat … Configure, AnnotationInfo` — 17 types, **0–16** — all of
  which wsjtx-mcp now implements. (An earlier draft, transcribed from a stale
  third-party mirror that stopped at `Configure`=15, wrongly called it absent;
  corrected in 0.1.2.)
- WSJT-X 3.0.2 emits a **schema-2 header** while advertising **max schema 3**.
  The codec is byte-identical for the message types we send across schema 2/3
  (the differences are confined to QDateTime/QColor edge cases that share the
  same Qt ≥ 5.2 layout), so either negotiated value is safe.
