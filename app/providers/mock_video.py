"""Mock video provider — returns a fake wav path keyed by URL.

The seed script writes tiny silent wav files into the cache dir so the
transcriber mock can key off them.
"""

from __future__ import annotations

import wave
from pathlib import Path

from app.providers.base import VideoInfo, VideoProvider
from app.providers.ytdlp_video import canonicalize_url


class MockVideoProvider(VideoProvider):
    name = "mock"

    def __init__(self, cache_dir: str | None = None):
        self.cache_dir = cache_dir or "./media_cache"
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

    def fetch_audio(self, url: str) -> VideoInfo:
        canonical = canonicalize_url(url)
        # Write a short silent wav so the transcriber has a real file to inspect.
        out = Path(self.cache_dir) / (canonical.replace("/", "__") + ".wav")
        if not out.exists():
            with wave.open(str(out), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(b"\x00\x00" * 1600)  # 0.1s silence
        return VideoInfo(
            canonical_url=canonical,
            author=None,
            local_audio_path=str(out),
            duration=0.1,
        )
