"""MiniMax LLM provider using the OpenAI-compatible Chat Completions API."""

from __future__ import annotations

from collections.abc import Iterator

import httpx

from app.providers.base import ChatChunk, ChatMessage, LLMProvider


class MiniMaxLLM(LLMProvider):
    name = "MiniMax"

    def __init__(self, api_key: str, model: str, base_url: str):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=60.0)

    def _payload(self, messages: list[ChatMessage], stream: bool, temperature: float, max_tokens: int) -> dict:
        return {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> Iterator[ChatChunk]:
        if not self.api_key:
            raise RuntimeError("MINIMAX_API_KEY is not set")
        url = f"{self.base_url}/chat/completions"
        with self._client.stream(
            "POST",
            url,
            headers=self._headers(),
            json=self._payload(messages, stream=True, temperature=temperature, max_tokens=max_tokens),
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    yield ChatChunk(delta="", finish_reason="stop")
                    return
                try:
                    import orjson

                    obj = orjson.loads(data)
                except Exception:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                ch = choices[0]
                delta = (ch.get("delta") or {}).get("content") or ""
                finish = ch.get("finish_reason")
                if delta or finish:
                    yield ChatChunk(delta=delta, finish_reason=finish)

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("MINIMAX_API_KEY is not set")
        url = f"{self.base_url}/chat/completions"
        resp = self._client.post(
            url,
            headers=self._headers(),
            json=self._payload(messages, stream=False, temperature=temperature, max_tokens=max_tokens),
        )
        resp.raise_for_status()
        obj = resp.json()
        return (obj["choices"][0]["message"]["content"] or "").strip()
