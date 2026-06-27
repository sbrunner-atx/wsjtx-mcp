"""Tests for value coercion, lookup tables, and the escape-hatch builder map."""

from __future__ import annotations

import pytest

from wsjtx_mcp import methods, protocol


def test_window_code():
    assert methods.window_code("band") == 0
    assert methods.window_code("rx") == 1
    assert methods.window_code("both") == 2
    assert methods.window_code(2) == 2
    with pytest.raises(methods.UnknownOperation):
        methods.window_code("nope")


def test_parse_color_named_hex_tuple():
    assert methods.parse_color("red") == (255, 0, 0, 255)
    assert methods.parse_color("#0000ff") == (0, 0, 255, 255)
    assert methods.parse_color("00ff00") == (0, 255, 0, 255)
    assert methods.parse_color([1, 2, 3]) == (1, 2, 3, 255)
    assert methods.parse_color([1, 2, 3, 4]) == (1, 2, 3, 4)


def test_parse_color_clear_variants_are_none():
    for v in (None, "", "clear", "invalid", "none"):
        assert methods.parse_color(v) is None


def test_parse_color_bad_raises():
    with pytest.raises(methods.UnknownOperation):
        methods.parse_color("nonsense")


def test_resolve_modifiers():
    assert methods.resolve_modifiers(None) == 0
    assert methods.resolve_modifiers("ctrl") == protocol.MODIFIERS["ctrl"]
    assert methods.resolve_modifiers("cmd") == 0x04
    assert methods.resolve_modifiers(["shift", "alt"]) == 0x02 | 0x08
    assert methods.resolve_modifiers(0x10) == 0x10
    with pytest.raises(methods.UnknownOperation):
        methods.resolve_modifiers("hyper")


def test_raw_builders_tx_classification():
    # reply always keys; free_text only with send=true; others never.
    _, reply_is_tx = methods.RAW_BUILDERS["reply"]
    _, ft_is_tx = methods.RAW_BUILDERS["free_text"]
    _, cfg_is_tx = methods.RAW_BUILDERS["configure"]
    assert reply_is_tx({}) is True
    assert ft_is_tx({"send": True}) is True
    assert ft_is_tx({"send": False}) is False
    assert ft_is_tx({}) is False
    assert cfg_is_tx({"mode": "FT8"}) is False


def test_raw_builders_cover_inbound_types():
    # Every name maps to a real protocol builder.
    for name, (builder, _) in methods.RAW_BUILDERS.items():
        assert callable(builder), name


def test_raw_builders_includes_annotation_info():
    builder, is_tx = methods.RAW_BUILDERS["annotation_info"]
    assert builder is protocol.build_annotation_info
    assert is_tx({}) is False  # niche control message, never keys the radio
