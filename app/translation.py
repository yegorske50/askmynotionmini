"""Translate transcript text to English using the MiniMax LLM.

The Groq Whisper endpoint only transcribes in the original language —
it has no translate mode (the OpenAI-style `task=translate` parameter
returns 400 Bad Request on Groq). So after we get the original
transcript, we use the answer LLM (MiniMax) to translate it to
English for the RAG context.

We translate segment-by-segment so the timestamped segments keep their
boundaries. For long transcripts we batch segments to keep token usage
sane.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from app.providers import LLMProvider
from app.providers.base import ChatMessage, TranscriptSegment

# ISO-ish language hints → English target prompt instructions
_LANG_HINT = {
    "hi": "Hindi",
    "te": "Telugu",
    "ta": "Tamil",
    "kn": "Kannada",
    "ml": "Malayalam",
    "mr": "Marathi",
    "bn": "Bengali",
    "gu": "Gujarati",
    "pa": "Punjabi",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "ru": "Russian",
    "ar": "Arabic",
}


def _lang_name(code: str) -> str:
    if not code:
        return "the source language"
    code = code.lower()
    if code in _LANG_HINT:
        return _LANG_HINT[code]
    # Fallback: capitalize the code
    return code.upper()


def _extract_json_array(text: str) -> list[str]:
    """Best-effort JSON-array extraction. The model is instructed to
    reply with a single JSON array, but it sometimes wraps it in
    prose. Try strict parse first, then fall back to bracket regex."""
    text = (text or "").strip()
    # Strip code fences if any
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        v = json.loads(text)
        if isinstance(v, list):
            return [str(x) for x in v]
    except Exception:
        pass
    # fallback: grab the first [...] block
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            v = json.loads(m.group(0))
            if isinstance(v, list):
                return [str(x) for x in v]
        except Exception:
            pass
    return []


def translate_segments(
    segments: list[TranscriptSegment],
    *,
    source_language: Optional[str] = None,
    target_language: str = "English",
    llm: LLMProvider,
) -> list[TranscriptSegment]:
    """Translate each segment's `text_original` to `target_language` and
    fill in `text_en`. Keeps the segment list structure intact.
    """
    if not segments:
        return segments
    # If everything is already in the target language, no-op.
    src_lang = (source_language or (segments[0].language if segments else "") or "").lower()
    if src_lang.startswith(target_language.lower()[:2]):
        for s in segments:
            if not s.text_en:
                s.text_en = s.text_original
        return segments

    src_name = _lang_name(src_lang)
    out: list[TranscriptSegment] = []
    # Batch up to ~12 segments per call to keep prompt reasonable.
    BATCH = 12
    for i in range(0, len(segments), BATCH):
        batch = segments[i : i + BATCH]
        original_lines = [s.text_original for s in batch]
        prompt = (
            f"You are a precise translator. Translate the following {len(batch)} "
            f"short passages from {src_name} to {target_language}. Preserve the "
            f"meaning, tone, and approximate length. Reply ONLY with a JSON array "
            f"of exactly {len(batch)} translated strings, in the same order, with "
            f"no commentary, no numbering, and no code fences. Example: "
            f'["translation 1", "translation 2"].\n\n'
            + "\n".join(f"{idx+1}. {line}" for idx, line in enumerate(original_lines))
        )
        try:
            resp = llm.complete(
                [ChatMessage(role="user", content=prompt)], temperature=0.0, max_tokens=2048
            )
        except Exception:
            resp = ""
        translations = _extract_json_array(resp)
        # Pad or trim to match batch length
        if len(translations) < len(batch):
            translations += [""] * (len(batch) - len(translations))
        translations = translations[: len(batch)]
        for seg, en in zip(batch, translations):
            en_clean = (en or "").strip()
            out.append(
                TranscriptSegment(
                    start=seg.start,
                    end=seg.end,
                    text_original=seg.text_original,
                    text_en=en_clean or seg.text_original,
                    language=seg.language,
                )
            )
    return out


def translate_text(
    text: str,
    *,
    source_language: str,
    target_language: str = "English",
    llm: LLMProvider,
) -> str:
    """One-shot translation of a longer piece of text. Used for the
    `full_text_en` field after `translate_segments` has handled the
    per-segment fields.
    """
    if not text or not text.strip():
        return text
    src_name = _lang_name(source_language)
    if source_language.lower().startswith(target_language.lower()[:2]):
        return text
    prompt = (
        f"Translate the following {src_name} text to {target_language}. "
        f"Preserve the meaning and tone. Reply with only the translation, "
        f"no commentary or code fences.\n\n{text}"
    )
    try:
        return llm.complete(
            [ChatMessage(role="user", content=prompt)], temperature=0.0, max_tokens=2048
        ).strip()
    except Exception:
        return text
