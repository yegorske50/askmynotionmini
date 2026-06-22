"""Groq Whisper transcription provider.

We translate to English via the MiniMax LLM (the answer LLM) — see
`app/translation.py`. Groq's OpenAI-compatible endpoint does NOT accept
the OpenAI-specific `task` parameter, so we only call `transcribe` here.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import httpx

from app.providers.base import TranscriptResult, TranscriptSegment, TranscriptionProvider


class GroqTranscriber(TranscriptionProvider):
    name = "groq"

    def __init__(self, api_key: str, base_url: str = "https://api.groq.com/openai/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=180.0)

    def transcribe(self, audio_path: str, *, language: Optional[str] = None) -> TranscriptResult:
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        path = Path(audio_path)
        if not path.exists() or path.stat().st_size == 0:
            return TranscriptResult(
                language=language or "unknown",
                segments=[],
                full_text_original="",
                full_text_en="",
                source="whisper",
            )

        # Groq accepts: model, file, language, prompt, response_format,
        # temperature, timestamp_granularities. It does NOT accept OpenAI's
        # `task` parameter — sending it returns 400 Bad Request.
        data = {
            "model": "whisper-large-v3",
            "response_format": "verbose_json",
            "timestamp_granularities[]": "segment",
        }
        if language:
            data["language"] = language

        with open(path, "rb") as f:
            files = {"file": (path.name, f, "audio/wav")}
            last_err: Optional[Exception] = None
            orig_data: dict = {}
            for attempt in range(3):
                try:
                    r = self._client.post(
                        f"{self.base_url}/audio/transcriptions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        data=data,
                        files=files,
                    )
                    if r.status_code == 429 or r.status_code >= 500:
                        time.sleep(2 ** attempt)
                        f.seek(0)
                        continue
                    if not r.is_success:
                        # Surface Groq's actual error body in the
                        # exception so the user sees WHY their
                        # transcription failed.
                        body = r.text[:300]
                        raise RuntimeError(
                            f"Groq transcription failed ({r.status_code}): {body}"
                        )
                    orig_data = r.json()
                    break
                except Exception as e:
                    last_err = e
                    time.sleep(2 ** attempt)
                    f.seek(0)
            else:
                raise RuntimeError(f"Groq transcription failed: {last_err}")

        lang = (orig_data.get("language") or language or "unknown")
        segs_orig = orig_data.get("segments") or []
        full_orig = (orig_data.get("text") or "").strip()

        # Build segments. `text_en` is filled in by the translation step
        # (app/translation.py) using MiniMax so we don't waste a second
        # Groq call. If the detected language is already English, we can
        # mirror it now and skip the translation.
        if (lang or "").lower().startswith("en"):
            segments = [
                TranscriptSegment(
                    start=float(s.get("start", 0.0)),
                    end=float(s.get("end", 0.0)),
                    text_original=(s.get("text") or "").strip(),
                    text_en=(s.get("text") or "").strip(),
                    language=lang,
                )
                for s in segs_orig
            ]
            return TranscriptResult(
                language=lang,
                segments=segments,
                full_text_original=full_orig,
                full_text_en=full_orig,
                source="whisper",
            )

        segments = [
            TranscriptSegment(
                start=float(s.get("start", 0.0)),
                end=float(s.get("end", 0.0)),
                text_original=(s.get("text") or "").strip(),
                text_en="",  # filled in by translation step
                language=lang,
            )
            for s in segs_orig
        ]
        return TranscriptResult(
            language=lang,
            segments=segments,
            full_text_original=full_orig,
            full_text_en=full_orig,  # placeholder; replaced after translation
            source="whisper",
        )
