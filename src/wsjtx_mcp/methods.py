"""Value coercion, small lookup tables, and the escape-hatch builder map.

Kept separate from ``server.py`` so the parsing/classification logic is
unit-testable without the MCP SDK or a live WSJT-X.
"""

from __future__ import annotations

from wsjtx_mcp import protocol

_TRUE = {"1", "true", "yes", "on"}

# Clear / Window codes (Clear message, In direction).
WINDOW_CODES: dict[str, int] = {
    "band": 0,
    "band_activity": 0,
    "rx": 1,
    "rx_freq": 1,
    "rx_frequency": 1,
    "both": 2,
    "all": 2,
}

# A handful of named colours for the highlight tool (r, g, b).
COLOR_NAMES: dict[str, tuple[int, int, int]] = {
    "red": (255, 0, 0),
    "green": (0, 128, 0),
    "lime": (0, 255, 0),
    "blue": (0, 0, 255),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "yellow": (255, 255, 0),
    "orange": (255, 165, 0),
    "pink": (255, 192, 203),
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
}

# The special callsign that clears *all* highlighting requests at once.
CLEAR_ALL_CALLSIGN = "CLEARALL!"


class UnknownOperation(ValueError):
    """Raised when a group tool is given an operation it does not support."""


def as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in _TRUE
    return bool(value)


def window_code(name: str | int) -> int:
    if isinstance(name, int):
        return name
    key = str(name).strip().lower()
    if key not in WINDOW_CODES:
        raise UnknownOperation(
            f"Unknown window '{name}'. Valid: {', '.join(sorted(set(WINDOW_CODES)))}."
        )
    return WINDOW_CODES[key]


def parse_color(value) -> tuple[int, int, int, int] | None:
    """Parse a colour into ``(r, g, b, a)``, or ``None`` for invalid/clear.

    Accepts ``None`` / "" / "invalid" / "clear" → ``None`` (clears highlighting),
    a ``"#RRGGBB"`` / ``"RRGGBB"`` hex string, an ``(r, g, b[, a])`` sequence, or
    a named colour (red, green, yellow, …).
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        r, g, b = int(value[0]), int(value[1]), int(value[2])
        a = int(value[3]) if len(value) > 3 else 255
        return (r, g, b, a)
    text = str(value).strip().lower()
    if text in ("", "invalid", "clear", "none"):
        return None
    if text in COLOR_NAMES:
        r, g, b = COLOR_NAMES[text]
        return (r, g, b, 255)
    hex_text = text[1:] if text.startswith("#") else text
    if len(hex_text) == 6:
        try:
            r = int(hex_text[0:2], 16)
            g = int(hex_text[2:4], 16)
            b = int(hex_text[4:6], 16)
            return (r, g, b, 255)
        except ValueError:
            pass
    raise UnknownOperation(
        f"Could not parse colour '{value}'. Use a name (red, yellow, …), '#RRGGBB', "
        f"an (r,g,b) list, or 'clear'."
    )


def resolve_modifiers(value) -> int:
    """Resolve a modifier name (or int, or list of names) to the Reply bitmask."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, (list, tuple)):
        return _bits(value)
    return _bits([value])


def _bits(names) -> int:
    bits = 0
    for name in names:
        key = str(name).strip().lower()
        if key not in protocol.MODIFIERS:
            raise UnknownOperation(
                f"Unknown modifier '{name}'. Valid: {', '.join(sorted(protocol.MODIFIERS))}."
            )
        bits |= protocol.MODIFIERS[key]
    return bits


# --- escape-hatch builder map -----------------------------------------------
# name -> (builder, is_tx_initiating). The builder takes (instance_id, **fields,
# schema=...). ``is_tx_initiating`` is a predicate over the supplied fields.

_NEVER = lambda fields: False  # noqa: E731
_ALWAYS = lambda fields: True  # noqa: E731
_IF_SEND = lambda fields: as_bool(fields.get("send", False))  # noqa: E731

RAW_BUILDERS: dict[str, tuple] = {
    "heartbeat": (protocol.build_heartbeat, _NEVER),
    "clear": (protocol.build_clear, _NEVER),
    "reply": (protocol.build_reply, _ALWAYS),
    "close": (protocol.build_close, _NEVER),
    "replay": (protocol.build_replay, _NEVER),
    "halttx": (protocol.build_halt_tx, _NEVER),
    "halt_tx": (protocol.build_halt_tx, _NEVER),
    "freetext": (protocol.build_free_text, _IF_SEND),
    "free_text": (protocol.build_free_text, _IF_SEND),
    "location": (protocol.build_location, _NEVER),
    "highlightcallsign": (protocol.build_highlight_callsign, _NEVER),
    "highlight": (protocol.build_highlight_callsign, _NEVER),
    "switchconfiguration": (protocol.build_switch_configuration, _NEVER),
    "switch_configuration": (protocol.build_switch_configuration, _NEVER),
    "configure": (protocol.build_configure, _NEVER),
}
