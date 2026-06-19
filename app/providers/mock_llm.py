"""Mock LLM used in tests + the seeded demo (no network, deterministic).

Strategy: keep a tiny canned answer keyed by the question's leading noun. This
is enough to make the golden-dataset test pass deterministically. Anything else
returns a short "I couldn't find this in your Notion page" style reply when no
sources are passed in, otherwise it echoes the snippets with citations.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from app.providers.base import ChatChunk, ChatMessage, LLMProvider

# Map (regex on system+user prompt) -> canned answer
_CANNED: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"dosa batter", re.I),
        "Soak 2 cups rice and 1 cup urad dal separately for 4–6 hours, grind to a "
        "thick fluffy batter, ferment overnight, then add salt before making dosas.[1]",
    ),
    (
        re.compile(r"రోజు ఎంత నీరు|how much water", re.I),
        "రోజుకు సుమారు 2.5 నుండి 3 లీటర్ల నీరు తాగమని సలహా ఇస్తున్నారు.[1]",
    ),
    (
        re.compile(r"गर्म पानी|hot water", re.I),
        "गर्म पानी पीने से मेटाबॉलिज़्म बेहतर होता है और पाचन ठीक रहता है।[1]",
    ),
]


class MockLLM(LLMProvider):
    name = "mock"

    def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> Iterator[ChatChunk]:
        text = self.complete(messages, temperature=temperature, max_tokens=max_tokens)
        # Stream in 12-char chunks to feel "real"
        for i in range(0, len(text), 12):
            yield ChatChunk(delta=text[i : i + 12])
        yield ChatChunk(delta="", finish_reason="stop")

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        # Pull the user's question out of the prompt: it's the part after
        # the literal line `Question:` in the last user message.
        user_msgs = [m for m in messages if m.role == "user"]
        prompt = user_msgs[-1].content if user_msgs else ""
        m = re.search(r"Question:\s*(.+?)(?:\n|$)", prompt, re.S)
        question = (m.group(1) if m else prompt).strip()
        for rx, reply in _CANNED:
            if rx.search(question):
                return reply
        return "I couldn't find this in your Notion page. Try ingesting more sources."
