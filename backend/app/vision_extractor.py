"""Screenshot -> signal-text extraction (for chart/image signals).

SAFETY DESIGN
-------------
This module's ONLY job is to convert an uploaded image into the same one-line
signal text a human would type, e.g.:

    "XAUUSD BUY ENTRY 2348 SL 2343 TP1 2353 TP2 2358 TP3 2363"

That text is then fed to the deterministic parser (parser.py), which remains the
SOLE authority on whether a signal is structurally valid and safe (SL on the
correct side, TP ordering, etc.). The vision step never produces final trade
numbers that bypass the parser, and the bot never broadcasts a signal without a
human (the signal provider) confirming the extracted numbers first.

ACCURACY DESIGN (why levels used to get missed)
-----------------------------------------------
Chart levels live in the tiny digits of the right-hand price scale. Telegram
photo compression shrinks screenshots to ~1280px, making those digits nearly
illegible. Three countermeasures:
  1. The full image is upscaled toward the model's high-resolution vision limit
     so digits span more pixels.
  2. A ZOOMED CROP of the right-hand price-scale strip is sent as a second
     image, so the axis numbers are directly legible.
  3. The prompt forces a transcribe-first procedure (list every price-scale
     number before mapping any level) and structured output guarantees a
     machine-readable reply.

Two engines:
  * ClaudeExtractor - calls the Claude API via the official anthropic SDK
    (needs ANTHROPIC_API_KEY).
  * FakeExtractor   - deterministic canned output for tests / no-API demos.

Engine is chosen by SIGNAL_EXTRACTOR ("claude"|"fake"); if unset it auto-selects
"claude" when ANTHROPIC_API_KEY is present, otherwise "fake".
"""
from __future__ import annotations

import base64
import io
import json
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

EXTRACTION_PROMPT = """You are reading a trading-signal screenshot. You get TWO images:
  * Image 1: the full screenshot.
  * Image 2: a magnified crop of the RIGHT-HAND EDGE of image 1 (the price scale /
    axis area), provided so the small price digits are legible. Image 2 shows the
    same content as the right edge of image 1, just bigger.
(If only one image is provided, treat it as image 1 and read the price scale from it.)

The screenshot is one of:
  (A) a TEXT signal - symbol, direction, entry, SL and TP levels written as words/numbers, or
  (B) an annotated price CHART where the trade is drawn as COLOURED ZONES/BOXES (e.g. a
      green/teal zone and a red/pink zone) and the key price levels are printed on the
      right-hand price scale / as labels on the horizontal lines.

Follow this procedure IN ORDER:
  STEP 1 - TRANSCRIBE: read EVERY number printed on the right-hand price scale (use
    image 2), top to bottom, plus any price labels printed on lines/zones in image 1.
    Record them all in "price_scale_numbers" exactly as printed, before deciding anything.
  STEP 2 - LOCATE: in image 1, find the trade structure: entry line/level, zone edges
    (top and bottom of each coloured box), and any marked horizontal lines.
  STEP 3 - MATCH: pair each structure from step 2 with the transcribed number at the
    same vertical height. Every level you output MUST be one of the numbers from step 1.
  STEP 4 - ASSEMBLE the signal.

Use ONLY numbers that are actually printed somewhere in the image - as text labels OR on
the price axis/scale. Never fabricate, interpolate, or round a level that has no on-screen
number. Reading a price off the price scale and associating it with the coloured zone
boundary (or line) at the same height is allowed: that price is written text, not a guess.

Extract, if determinable:
- symbol (e.g. EURUSD, GBPJPY, USDJPY, XAUUSD, GOLD, BTCUSD)
- direction (BUY/LONG or SELL/SHORT)
- entry (a price, or the word Market)
- stop loss (SL)
- take profits TP1, TP2, TP3

Reading a chart-style (type B) setup:
- Infer direction from the layout using the usual convention, and STATE the assumption in
  "notes": entry near a LOWER green/support/buy zone with target levels ABOVE => BUY, and
  SL is the level BELOW entry; entry near an UPPER red/resistance/sell zone with target
  levels BELOW => SELL, and SL is the level ABOVE entry.
- ENTRY = the entry/current level; SL = the protective level on the opposite side from the
  targets; take profits are the target zone edges/levels in the profit direction
  (TP1<TP2<TP3 for BUY, TP1>TP2>TP3 for SELL).
- A chart read is INTERPRETED, so set "confidence" to LOW (MEDIUM at most) and in "notes"
  say exactly which printed price you mapped to entry/SL/each TP and which direction you
  assumed, so a human can verify and correct before anything is sent.

Output fields:
- "price_scale_numbers": every number you transcribed in step 1, as printed.
- "signal_text": a single line using the literal keywords ENTRY, SL, TP1, TP2, TP3
  followed by the numbers. Omit any field you genuinely cannot determine. Empty string
  if unreadable.
- You must be able to give at least symbol, direction, SL and TP1; if you cannot even
  after interpreting the zones, set "readable": false and explain what is missing in
  "notes".
- Only use numbers printed in the image. Never invent or round a level with no
  on-screen number."""

# JSON schema for structured output — the API guarantees the reply matches this,
# so extraction can never fail on malformed JSON. Property order mirrors the
# transcribe-first procedure.
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "price_scale_numbers": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Every number printed on the price scale / labels, as printed.",
        },
        "readable": {"type": "boolean"},
        "signal_text": {
            "type": "string",
            "description": "e.g. XAUUSD BUY ENTRY 2348 SL 2343 TP1 2353 TP2 2358 TP3 2363",
        },
        "confidence": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
        "notes": {
            "type": "string",
            "description": "Which printed price maps to entry/SL/each TP and any direction assumption.",
        },
    },
    "required": ["price_scale_numbers", "readable", "signal_text", "confidence", "notes"],
    "additionalProperties": False,
}

# Vision model. Claude Opus 4.8 reads high-resolution images (2576px long edge)
# and is markedly better at small-text/level reading than older models.
# Override with SIGNAL_EXTRACTOR_MODEL if needed.
DEFAULT_MODEL = os.getenv("SIGNAL_EXTRACTOR_MODEL", "claude-opus-4-8")

# Preprocessing targets. Stay under the model's 2576px cap so the API never
# downscales what we send.
_TARGET_LONG_EDGE = 2400
_AXIS_CROP_FRACTION = 0.22   # right-hand strip width (price scale lives here)
_MAX_AXIS_ZOOM = 4.0


@dataclass
class ExtractionResult:
    """Outcome of reading an image. `raw_text` feeds the deterministic parser."""

    raw_text: str                 # canonical one-line signal text ("" if unreadable)
    engine: str                   # "claude" | "fake"
    confidence: str = "LOW"       # HIGH | MEDIUM | LOW
    readable: bool = False
    notes: Optional[str] = None


class FakeExtractor:
    """Deterministic extractor for tests and API-less demos.

    Returns FAKE_EXTRACTOR_TEXT (a valid BUY setup by default) so the whole
    photo -> preview -> confirm -> broadcast flow can be exercised offline.
    """

    engine = "fake"

    def extract(self, image_bytes: bytes, mime: str = "image/png") -> ExtractionResult:
        text = os.getenv(
            "FAKE_EXTRACTOR_TEXT",
            "XAUUSD BUY ENTRY 2348 SL 2343 TP1 2353 TP2 2358 TP3 2363",
        )
        if text.upper().startswith("REJECT"):
            return ExtractionResult(
                raw_text="", engine=self.engine, confidence="LOW",
                readable=False, notes="fake extractor forced reject",
            )
        return ExtractionResult(
            raw_text=text, engine=self.engine, confidence="HIGH",
            readable=True, notes="fake extractor (no real OCR performed)",
        )


def prepare_images(image_bytes: bytes, mime: str) -> List[Tuple[bytes, str]]:
    """Preprocess a screenshot so the price-scale digits are legible.

    Returns [(full_image, mime), (axis_crop, mime)]:
      * full image, upscaled (LANCZOS) toward the model's high-res limit when
        the source is small (Telegram photo compression -> ~1280px);
      * a magnified crop of the right-hand strip where the price scale lives.

    Falls back to the original bytes untouched if Pillow is unavailable or the
    image cannot be decoded — extraction still works, just without the boost.
    """
    try:
        from PIL import Image
    except ImportError:
        return [(image_bytes, mime)]

    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception:  # noqa: BLE001 — undecodable input: send as-is
        return [(image_bytes, mime)]

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    width, height = img.size
    long_edge = max(width, height)

    # Full image: upscale small screenshots so glyphs span more pixels.
    full = img
    if long_edge < _TARGET_LONG_EDGE:
        scale = _TARGET_LONG_EDGE / long_edge
        full = img.resize(
            (round(width * scale), round(height * scale)), Image.LANCZOS
        )

    # Right-hand price-scale strip, zoomed up to 4x (bounded by the model cap).
    crop_width = max(1, int(width * _AXIS_CROP_FRACTION))
    strip = img.crop((width - crop_width, 0, width, height))
    s_w, s_h = strip.size
    zoom = min(_TARGET_LONG_EDGE / max(s_w, s_h), _MAX_AXIS_ZOOM)
    if zoom > 1.0:
        strip = strip.resize((round(s_w * zoom), round(s_h * zoom)), Image.LANCZOS)

    prepared: List[Tuple[bytes, str]] = []
    for im in (full, strip):
        buf = io.BytesIO()
        im.save(buf, format="PNG")  # PNG: no fresh JPEG artifacts on the digits
        prepared.append((buf.getvalue(), "image/png"))
    return prepared


class ClaudeExtractor:
    """Reads the image with the Claude API via the official anthropic SDK.

    Sends the preprocessed image pair (full + zoomed price-axis crop), uses
    adaptive thinking for the chart interpretation, and structured output so
    the reply is always valid JSON. Requires ANTHROPIC_API_KEY.
    """

    engine = "claude"

    def extract(self, image_bytes: bytes, mime: str = "image/png") -> ExtractionResult:
        import anthropic

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not _has_real_api_key(api_key):
            return ExtractionResult(
                raw_text="", engine=self.engine, confidence="LOW", readable=False,
                notes="ANTHROPIC_API_KEY not set on the server.",
            )

        content: list = []
        for img_bytes, img_mime in prepare_images(image_bytes, mime):
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img_mime,
                        "data": base64.standard_b64encode(img_bytes).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": EXTRACTION_PROMPT})

        client = anthropic.Anthropic(api_key=api_key, timeout=150.0)
        try:
            response = client.messages.create(
                model=DEFAULT_MODEL,
                max_tokens=8000,  # room for adaptive thinking + the JSON reply
                thinking={"type": "adaptive"},
                output_config={"format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}},
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.APIStatusError as exc:
            return ExtractionResult(
                raw_text="", engine=self.engine, confidence="LOW", readable=False,
                notes=f"Vision API error {exc.status_code}: {exc.message}",
            )
        except anthropic.APIConnectionError:
            return ExtractionResult(
                raw_text="", engine=self.engine, confidence="LOW", readable=False,
                notes="Vision API unreachable (network error).",
            )
        except Exception as exc:  # noqa: BLE001 — never crash the preview flow
            return ExtractionResult(
                raw_text="", engine=self.engine, confidence="LOW", readable=False,
                notes=f"Vision API error: {exc}",
            )

        # A safety refusal or truncated reply is treated as unreadable — the
        # human provider retries or types the signal; nothing is guessed.
        if response.stop_reason == "refusal":
            return ExtractionResult(
                raw_text="", engine=self.engine, confidence="LOW", readable=False,
                notes="Vision model declined to read this image.",
            )
        if response.stop_reason == "max_tokens":
            return ExtractionResult(
                raw_text="", engine=self.engine, confidence="LOW", readable=False,
                notes="Vision reply was truncated; try again or type the signal.",
            )

        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        return _parse_model_json(text, engine=self.engine)


def _parse_model_json(text: str, engine: str) -> ExtractionResult:
    """Parse the model's JSON response into an ExtractionResult.

    Structured output guarantees valid JSON on the happy path; the lenient
    salvage below is defence in depth only.
    """
    payload = None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                payload = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                payload = None

    if not isinstance(payload, dict):
        # Could not get structured output; treat as unreadable rather than guess.
        return ExtractionResult(
            raw_text="", engine=engine, confidence="LOW", readable=False,
            notes="Could not parse model response.",
        )

    notes = payload.get("notes") or ""
    # Surface the transcribed price-scale numbers so the human confirming the
    # preview can see exactly what the model read off the axis.
    scale_numbers = payload.get("price_scale_numbers")
    if isinstance(scale_numbers, list) and scale_numbers:
        transcribed = ", ".join(str(n) for n in scale_numbers[:20])
        notes = (notes + " " if notes else "") + f"[Price scale read: {transcribed}]"

    return ExtractionResult(
        raw_text=(payload.get("signal_text") or "").strip(),
        engine=engine,
        confidence=str(payload.get("confidence", "LOW")).upper(),
        readable=bool(payload.get("readable", False)),
        notes=notes or None,
    )


def get_extractor():
    """Select the extractor engine from env."""
    engine = os.getenv("SIGNAL_EXTRACTOR", "").strip().lower()
    if not engine:
        engine = "claude" if _has_real_api_key(os.getenv("ANTHROPIC_API_KEY")) else "fake"
    if engine == "claude":
        return ClaudeExtractor()
    if engine == "fake":
        return FakeExtractor()
    raise ValueError(f"Unknown SIGNAL_EXTRACTOR: {engine!r} (use 'claude' or 'fake')")


def _has_real_api_key(value: Optional[str]) -> bool:
    if not value:
        return False
    return value.strip().lower() not in {"replace_me", "changeme", "todo"}
