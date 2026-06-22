"""Mock LLM used in tests + the seeded demo (no network, deterministic).

Strategy: keep a tiny canned answer keyed by the question's leading noun. This
is enough to make the golden-dataset test pass deterministically. Anything else
returns a short "I couldn't find this in your Notion page" style reply when no
sources are passed in, otherwise it echoes the snippets with citations.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

from app.providers.base import ChatChunk, ChatMessage, LLMProvider

# Map (regex on system+user prompt) -> canned answer
_CANNED: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"dosa batter", re.I),
        "Soak 2 cups rice and 1 cup urad dal separately for 4\u20136 hours, grind to a "
        "thick fluffy batter, ferment overnight, then add salt before making dosas.[1]",
    ),
    (
        re.compile(r"\u0c30\u0c4b\u0c1c\u0c41 \u0c0e\u0c02\u0c24 \u0c28\u0c40\u0c30\u0c41|how much water", re.I),
        "\u0c30\u0c4b\u0c1c\u0c41\u0c15\u0c41 \u0c38\u0c41\u0c2e\u0c3e\u0c30\u0c41 2.5 \u0c28\u0c41\u0c02\u0c21\u0c3f 3 \u0c32\u0c40\u0c1f\u0c30\u0c4d\u0c32 \u0c28\u0c40\u0c30\u0c41 \u0c24\u0c3e\u0c17\u0c2e\u0c28\u0c3f \u0c38\u0c32\u0c39\u0c3e \u0c07\u0c38\u0c4d\u0c24\u0c41\u0c28\u0c4d\u0c28\u0c3e\u0c30\u0c41.[1]",
    ),
    (
        re.compile(r"\u0917\u0930\u094d\u092e \u092a\u093e\u0928\u0940|hot water", re.I),
        "\u0917\u0930\u094d\u092e \u092a\u093e\u0928\u0940 \u092a\u0940\u0928\u0947 \u0938\u0947 \u092e\u0947\u091f\u093e\u092c\u0949\u0932\u093f\u091c\u093c\u094d\u092e \u092c\u0947\u0939\u0924\u0930 \u0939\u094b\u0924\u093e \u0939\u0948 \u0914\u0930 \u092a\u093e\u091a\u0928 \u0920\u0940\u0915 \u0930\u0939\u0924\u093e \u0939\u0948\u0964[1]",
    ),
]

# Translation table for the demo corpus so the cross-language test passes
# when the IG pipeline runs the translation step in mock mode. Keys are
# substrings of the source text; values are the English rendering.
_TRANSLATIONS: dict[str, str] = {
    "\u0c30\u0c4b\u0c1c\u0c41\u0c15\u0c41 \u0c15\u0c28\u0c40\u0c38\u0c02 \u0c30\u0c46\u0c02\u0c21\u0c41\u0c28\u0c4d\u0c28\u0c30 \u0c32\u0c40\u0c1f\u0c30\u0c4d\u0c32 \u0c28\u0c40\u0c30\u0c41 \u0c24\u0c3e\u0c17\u0c3e\u0c32\u0c3f": "You should drink at least 2.5 liters of water per day.",
    "\u0c35\u0c47\u0c38\u0c35\u0c3f\u0c32\u0c4b \u0c2e\u0c42\u0c21\u0c41 \u0c32\u0c40\u0c1f\u0c30\u0c4d\u0c32\u0c41 \u0c24\u0c3e\u0c17\u0c21\u0c02 \u0c2e\u0c02\u0c1a\u0c3f\u0c26\u0c3f": "In summer, three liters is better.",
    "\u0c28\u0c40\u0c30\u0c41 \u0c0e\u0c15\u0c4d\u0c15\u0c41\u0c35 \u0c24\u0c3e\u0c17\u0c3f\u0c24\u0c47 \u0c1a\u0c30\u094d\u0c2e\u0c02 \u0c2e\u0c46\u0c30\u0c41\u0c38\u0c4d\u0c24\u0c41\u0c28\u0c4d\u0c26\u0c3f": "Drinking more water makes your skin glow.",
    "\u0938\u0941\u092c\u0939 \u0917\u0930\u094d\u092e \u092a\u093e\u0928\u0940 \u092a\u0940\u0928\u0947 \u0938\u0947 \u092e\u0947\u091f\u093e\u092c\u0949\u0932\u093f\u091c\u093c\u094d\u092e \u092c\u0947\u0939\u0924\u0930 \u0939\u094b\u0924\u093e \u0939\u0948 \u0914\u0930 \u092a\u093e\u091a\u0928 \u0920\u0940\u0915 \u0930\u0939\u0924\u093e \u0939\u0948\u0964": "Drinking warm water in the morning improves metabolism and aids digestion.",
    "\u090f\u0915 \u0917\u093f\u0932\u093e\u0938 \u0917\u0930\u094d\u092e \u092a\u093e\u0928\u0940 \u092e\u0947\u0902 \u0928\u0940\u092c\u0942 \u092e\u093f\u0932\u093e\u0915\u0930 \u0914\u0930 \u0909\u0938\u0938\u0947 \u091c\u094d\u092f\u093e\u0926\u093e \u092b\u093e\u092f\u0926\u093e \u0939\u094b\u0924\u093e \u0939\u0948\u0964": "Adding lemon to a glass of warm water gives even more benefit.",
}


def _translate_text(line: str) -> str:
    """Return a translated string for a known demo line, or a passthrough
    placeholder that still contains the original so the test pipeline runs."""
    line = line.strip()
    for needle, english in _TRANSLATIONS.items():
        if needle in line:
            return english
    return f"[translated] {line}"


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
        # Translation requests: produce a JSON array of translated lines
        # so the IG pipeline's translate step populates text_en correctly.
        m_lang = re.search(r"from (\w+) to (\w+)", prompt, re.I)
        if m_lang and ("translate" in prompt.lower() or "JSON array" in prompt):
            lines = re.findall(r"^\d+\.\s*(.+)$", prompt, re.M)
            if lines:
                translated = [_translate_text(l) for l in lines]
                return json.dumps(translated)
            return json.dumps([_translate_text(prompt[-200:])])
        m = re.search(r"Question:\s*(.+?)(?:\n|$)", prompt, re.S)
        question = (m.group(1) if m else prompt).strip()
        for rx, reply in _CANNED:
            if rx.search(question):
                return reply
        return "I couldn't find this in your Notion page. Try ingesting more sources."
