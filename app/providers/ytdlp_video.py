"""yt-dlp video provider.

Pulls the best audio track (≤~m4a/aac/opus) and demuxes to 16kHz mono wav via
ffmpeg. Used for Instagram public reels, YouTube, etc.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from app.providers.base import VideoInfo, VideoProvider

_INSTAGRAM_RE = re.compile(
    r"https?://(www\.)?instagram\.com/"
    r"(?:"
    r"(?:p|reel|reels|tv)/[A-Za-z0-9_-]+/?(?:[?#].*)?"
    r"|share/reel/[A-Za-z0-9_-]+/?(?:[?#].*)?"
    r"|reel/audio/[0-9_-]+/?(?:[?#].*)?"
    r")",
    re.I,
)


def is_instagram_url(url: str) -> bool:
    return bool(_INSTAGRAM_RE.match(url.strip()))


def canonicalize_url(url: str) -> str:
    """Strip query string + trailing slash for cache key stability.

    Also normalizes Instagram share links (`/share/reel/<id>/`) to the
    canonical `/reel/<id>/` form so the cache key is stable across the
    two URL shapes Notion sometimes produces for the same reel.
    """
    u = url.strip()
    u = re.sub(r"\?.*$", "", u)
    u = re.sub(r"#.*$", "", u)
    u = u.rstrip("/")
    # instagram.com/share/reel/XXX -> instagram.com/reel/XXX
    u = re.sub(
        r"^(https?://(?:www\.)?instagram\.com/)share/(reel|reels|p|tv)/",
        r"\1\2/",
        u,
        flags=re.I,
    )
    return u


class YtDlpVideoProvider(VideoProvider):
    name = "yt-dlp"

    def __init__(self, cache_dir: str | None = None):
        self.cache_dir = cache_dir or os.environ.get("MEDIA_CACHE_DIR", "./media_cache")
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

    def fetch_audio(self, url: str) -> VideoInfo:
        canonical = canonicalize_url(url)
        # cache by canonical url's basename
        slug = re.sub(r"[^A-Za-z0-9]+", "_", canonical)[-80:]
        out_dir = Path(self.cache_dir) / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        wav_path = out_dir / "audio.wav"
        desc_path = out_dir / "description.txt"
        if wav_path.exists() and wav_path.stat().st_size > 0:
            description = ""
            if desc_path.exists():
                try:
                    description = desc_path.read_text(
                        encoding="utf-8", errors="ignore"
                    )
                except Exception:
                    description = ""
            return VideoInfo(
                canonical_url=canonical,
                author=None,
                local_audio_path=str(wav_path),
                duration=None,
                description=description,
            )

        # 1) download best audio with yt-dlp
        # Use a UA to avoid 403 on some CDNs.
        tmpl = str(out_dir / "src.%(ext)s")
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--no-warnings",
            "--no-progress",
            "-x",
            "--audio-format", "best",
            "-o", tmpl,
            url,
        ]
        last_err: str | None = None
        for attempt in range(3):
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
                if proc.returncode == 0:
                    last_err = None
                    break
                last_err = proc.stderr[-800:] if proc.stderr else proc.stdout[-800:]
                if "rate-limit" in (last_err or "").lower() or "429" in (last_err or ""):
                    time.sleep(3 + 2 ** attempt)
                    continue
                # geo / private / unavailable
                if any(tag in (last_err or "").lower() for tag in (
                    "private", "removed", "unavailable", "login", "not available",
                    "region", "blocked",
                )):
                    raise RuntimeError(f"unavailable: {last_err.strip()[:200]}")
                time.sleep(2 ** attempt)
            except subprocess.TimeoutExpired as e:
                last_err = f"timeout: {e}"
                time.sleep(2 ** attempt)
        if last_err:
            raise RuntimeError(f"yt-dlp failed: {last_err[:200]}")

        # 2) locate downloaded file
        src_candidates = sorted(
            out_dir.glob("src.*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not src_candidates:
            raise RuntimeError("yt-dlp produced no file")
        src = src_candidates[0]

        # 3) ffmpeg -> 16kHz mono wav
        ff = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(src),
            "-ac", "1", "-ar", "16000",
            "-vn",
            str(wav_path),
        ]
        try:
            proc = subprocess.run(ff, capture_output=True, text=True, timeout=120)
        except FileNotFoundError as e:
            raise RuntimeError(
                "ffmpeg not found. Install it with: brew install ffmpeg "
                "(macOS) or apt-get install ffmpeg (Linux). It's required "
                "to convert downloaded media to 16 kHz mono wav for Whisper."
            ) from e
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {proc.stderr[-300:]}")

        # cleanup source
        try:
            src.unlink()
        except OSError:
            pass

        # 4) extract description (Instagram caption) via a second yt-dlp
        # call that only dumps metadata. Best-effort; many reels are music
        # or text-on-screen with no speech, in which case the caption is
        # the primary signal we have.
        description = ""
        try:
            info_proc = subprocess.run(
                [
                    "yt-dlp",
                    "--no-warnings",
                    "--no-progress",
                    "--no-playlist",
                    "--skip-download",
                    "--print", "%(description)s",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if info_proc.returncode == 0:
                description = (info_proc.stdout or "").strip()
        except Exception:
            description = ""
        if description:
            try:
                desc_path.write_text(description, encoding="utf-8")
            except Exception:
                pass

        return VideoInfo(
            canonical_url=canonical,
            author=None,
            local_audio_path=str(wav_path),
            duration=None,
            description=description,
        )
