"""Answer prompt: cited, multi-language, honest "not found" fallback."""

from __future__ import annotations

import textwrap

SYSTEM = (
    "You are AskMyNotion, a careful assistant that answers questions using ONLY "
    "the provided source passages from a user's personal Notion page and Instagram "
    "reels. Be precise and grounded. If the answer is not contained in the "
    "sources, reply exactly: 'I couldn't find this in your Notion page.' and "
    "suggest what the user could ingest. Never invent facts. Every non-trivial "
    "claim must end with a citation in the form [n] where n is the source number. "
    "If multiple sources support a point, cite them all: [1][3]. If two sources "
    "disagree, present both with separate citations."
)


def build_messages(
    *,
    question: str,
    answer_language: str,
    contexts: list[dict],
) -> list[dict]:
    """Build the OpenAI-style messages array. `contexts` is a list of dicts
    with keys: n, text_original, text_en, language, source_type, start_sec,
    end_sec, deep_link.
    """
    ctx_lines = []
    for c in contexts:
        header = f"[{c['n']}]"
        if c["source_type"] in ("video_transcript", "caption") and c.get("start_sec") is not None:
            ts = f" @ {c['start_sec']:.0f}s–{c['end_sec']:.0f}s"
        else:
            ts = ""
        text = (c.get("text_en") or c.get("text_original") or "").strip()
        lang = c.get("language") or "unknown"
        ctx_lines.append(f"{header} ({c['source_type']}, lang={lang}{ts}) {text}")
    ctx_block = "\n\n".join(ctx_lines) if ctx_lines else "(no sources)"

    user_prompt = textwrap.dedent(
        f"""
        Sources (cited as [n]):

        {ctx_block}

        Question: {question.strip()}

        Answer in {answer_language}. Use inline citations like [1], [2]. If the
        answer is not in the sources, say "I couldn't find this in your Notion page."
        and suggest what to ingest.
        """
    ).strip()

    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_prompt},
    ]
