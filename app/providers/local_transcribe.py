"""Local faster-whisper transcription (offline fallback for ASR_PROVIDER=local).

Heavy: we lazy-load on first call. The Mac stays light during non-Whisper work.
"""

from __future__ import annotations

import threading
from pathlib import Path

from app.providers.base import TranscriptionProvider, TranscriptResult, TranscriptSegment


class LocalWhisperTranscriber(TranscriptionProvider):
    name = "local-faster-whisper"

    def __init__(self, model_size: str = "small", device: str = "cpu", compute_type: str = "int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from faster_whisper import WhisperModel

                    self._model = WhisperModel(
                        self.model_size,
                        device=self.device,
                        compute_type=self.compute_type,
                    )
        return self._model

    def transcribe(self, audio_path: str, *, language: str | None = None) -> TranscriptResult:
        model = self._load()
        path = Path(audio_path)
        if not path.exists() or path.stat().st_size == 0:
            return TranscriptResult(
                language=language or "unknown",
                segments=[],
                full_text_original="",
                full_text_en="",
                source="whisper",
            )
        segs, info = model.transcribe(
            str(path),
            language=language,
            vad_filter=True,
            beam_size=5,
        )
        segs_list = list(segs)
        lang = info.language or (language or "unknown")
        segments = [
            TranscriptSegment(
                start=float(s.start),
                end=float(s.end),
                text_original=(s.text or "").strip(),
                text_en=(s.text or "").strip(),  # faster-whisper doesn't translate
                language=lang,
            )
            for s in segs_list
        ]
        full_orig = " ".join(s.text_original for s in segments).strip()
        return TranscriptResult(
            language=lang,
            segments=segments,
            full_text_original=full_orig,
            full_text_en=full_orig,
            source="whisper",
        )
