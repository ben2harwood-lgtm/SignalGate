"""Tests for the vision-extractor image preprocessing and reply parsing.

These cover the offline-testable half of the level-reading fix: the
upscale + price-axis-crop pipeline and the structured-reply parsing. The live
Claude engine is validated separately against real chart screenshots.
"""
from __future__ import annotations

import io

from PIL import Image

from app.vision_extractor import (
    _TARGET_LONG_EDGE,
    ExtractionResult,
    _parse_model_json,
    prepare_images,
)


def _png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_small_screenshot_is_upscaled_and_axis_cropped():
    """A Telegram-compressed screenshot yields an upscaled full image plus a
    zoomed right-axis crop — the fix for illegible price-scale digits."""
    prepared = prepare_images(_png(1280, 720), "image/png")
    assert len(prepared) == 2

    full = Image.open(io.BytesIO(prepared[0][0]))
    assert max(full.size) == _TARGET_LONG_EDGE  # upscaled to the target
    assert full.size[0] > full.size[1]          # orientation preserved

    strip = Image.open(io.BytesIO(prepared[1][0]))
    # The crop is a tall right-hand strip, zoomed well beyond source height.
    assert strip.size[1] > 720
    assert strip.size[1] <= _TARGET_LONG_EDGE
    assert strip.size[0] < strip.size[1]


def test_large_screenshot_is_not_upscaled():
    prepared = prepare_images(_png(3000, 1600), "image/png")
    full = Image.open(io.BytesIO(prepared[0][0]))
    assert full.size == (3000, 1600)  # already sharp; left alone


def test_undecodable_bytes_fall_back_untouched():
    """Preprocessing must never break extraction — bad input passes through."""
    prepared = prepare_images(b"definitely not an image", "image/png")
    assert prepared == [(b"definitely not an image", "image/png")]


def test_parse_surfaces_price_scale_numbers_in_notes():
    """The transcribed axis numbers appear in notes so the human confirming
    the preview can see exactly what the model read."""
    reply = (
        '{"price_scale_numbers": ["1.0950", "1.0900", "1.0850"],'
        ' "readable": true,'
        ' "signal_text": "EURUSD BUY SL 1.0850 TP1 1.0950",'
        ' "confidence": "LOW",'
        ' "notes": "SL mapped to zone bottom."}'
    )
    result = _parse_model_json(reply, engine="claude")
    assert isinstance(result, ExtractionResult)
    assert result.readable is True
    assert result.raw_text == "EURUSD BUY SL 1.0850 TP1 1.0950"
    assert "1.0950" in (result.notes or "")
    assert "Price scale read" in (result.notes or "")


def test_parse_garbage_reply_is_unreadable_not_a_guess():
    result = _parse_model_json("the model rambled with no JSON", engine="claude")
    assert result.readable is False
    assert result.raw_text == ""
