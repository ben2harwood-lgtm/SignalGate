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

Two engines:
  * ClaudeExtractor - calls the Anthropic vision API (needs ANTHROPIC_API_KEY).
  * FakeExtractor   - deterministic canned output for tests / no-API demos.

Engine is chosen by SIGNAL_EXTRACTOR ("claude"|"fake"); if unset it auto-selects
"claude" when ANTHROPIC_API_KEY is present, otherwise "fake".
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Optional

# The model is asked for STRICT JSON. Temperature 0 for determinism. It must
# only transcribe values that are written on the image; it must NOT infer a
# number purely from where a line sits, and must flag low confidence instead of
# guessing. Required fields mirror what the deterministic parser needs.
EXTRACTION_PROMPT = """You are reading a trading-signal screenshot. It is one of:
  (A) a TEXT signal - symbol, direction, entry, SL and TP levels written as words/numbers, or
  (B) an annotated price CHART where the trade is drawn as COLOURED ZONES/BOXES (e.g. a
      green/teal zone and a red/pink zone) and the key price levels are printed on the
      right-hand price scale / as labels on the horizontal lines.

Use ONLY numbers that are actually printed somewhere in the image - as text labels OR on
the price axis/scale. Never fabricate a level that has no on-screen number. Reading a price
off the price scale and associating it with the coloured zone boundary (or line) at the same
height is allowed: that price is written text, not a guess.

Extract, if determinable:
- symbol (e.g. XAUUSD, GOLD, BTCUSD)
- direction (BUY/LONG or SELL/SHORT)
- entry (a price, or the word Market)
- stop loss (SL)
- take profits TP1, TP2, TP3

Reading a chart-style (type B) setup:
- Match each printed price-scale number to the zone edge / horizontal line at the same
  height, and use those as the actual levels.
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

Respond with ONLY a JSON object, no prose, in exactly this shape:
{"readable": true/false,
 "signal_text": "XAUUSD BUY ENTRY 2348 SL 2343 TP1 2353 TP2 2358 TP3 2363",
 "confidence": "HIGH"/"MEDIUM"/"LOW",
 "notes": "for charts: which printed prices map to entry/SL/TP and the direction assumption"}

Rules:
- "signal_text" must be a single line using the literal keywords ENTRY, SL, TP1, TP2, TP3
  followed by the numbers. Omit any field you genuinely cannot determine.
- You must be able to give at least symbol, direction, SL and TP1; if you cannot even after
  interpreting the zones, set "readable": false and explain what is missing in "notes".
- Only use numbers printed in the image. Never invent or round a level with no on-screen number."""

# Vision-capable model. Override with SIGNAL_EXTRACTOR_MODEL if needed.
DEFAULT_MODEL = os.getenv("SIGNAL_EXTRACTOR_MODEL", "claude-sonnet-4-5")


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


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


class ClaudeExtractor:
    """Reads the image with the Anthropic vision API via a plain HTTPS call.

    Uses httpx (already a project dependency) rather than the anthropic SDK, so
    no extra package is needed. Requires ANTHROPIC_API_KEY in the environment.
    """

    engine = "claude"

    def extract(self, image_bytes: bytes, mime: str = "image/png") -> ExtractionResult:
        import httpx  # already a dependency

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not _has_real_api_key(api_key):
            return ExtractionResult(
                raw_text="", engine=self.engine, confidence="LOW", readable=False,
                notes="ANTHROPIC_API_KEY not set on the server.",
            )

        b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        body = {
            "model": DEFAULT_MODEL,
            "max_tokens": 400,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime,
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": EXTRACTION_PROMPT},
                    ],
                }
            ],
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        try:
            with httpx.Client(timeout=60.0) as http:
                resp = http.post(ANTHROPIC_URL, headers=headers, json=body)
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            return ExtractionResult(
                raw_text="", engine=self.engine, confidence="LOW", readable=False,
                notes=f"Vision API error: {exc}",
            )

        text = "".join(
            block.get("text", "")
            for block in payload.get("content", [])
            if block.get("type") == "text"
        ).strip()
        return _parse_model_json(text, engine=self.engine)


def _parse_model_json(text: str, engine: str) -> ExtractionResult:
    """Leniently parse the model's JSON response into an ExtractionResult."""
    payload = None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Try to salvage a JSON object embedded in any extra prose.
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

    return ExtractionResult(
        raw_text=(payload.get("signal_text") or "").strip(),
        engine=engine,
        confidence=str(payload.get("confidence", "LOW")).upper(),
        readable=bool(payload.get("readable", False)),
        notes=payload.get("notes"),
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
