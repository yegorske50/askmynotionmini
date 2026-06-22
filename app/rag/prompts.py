"""Answer prompt: cited, multi-language, useful even when the question
is about finding sources rather than extracting a single fact."""

from __future__ import annotations

import textwrap

SYSTEM = (
    "You are AskMyNotion, a careful assistant that answers questions using the "
    "provided source passages from a user's personal Notion page and Instagram "
    "reels.\n\n"
    "Guidelines:\n"
    "- Be helpful first. If the user asks 'show me sources about X' or 'what do I "
    "have on Y', list the relevant sources with a one-line explanation of each.\n"
    "- If sources are present and partially relevant, answer with what you can "
    "grounded in them. Cite inline as [n].\n"
    "- If the sources clearly do not contain anything about the topic, reply "
    "exactly: 'I couldn't find this in your Notion page.' and (briefly) suggest "
    "what the user could ingest. Do not invent facts.\n"
    "- When you cite a source, end your sentence with [n] (or [1][3] for "
    "multiple). If two sources disagree, present both with separate citations.\n"
    "- Be concise. No preamble, no 'Based on the sources...'. Just the answer."
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

        Answer in {answer_language}. Use inline citations like [1], [2].

        If the question is asking you to find / list / show sources, list the
        relevant ones with a one-line note on what each one is about — do not
        refuse just because the sources don't spell out a single exact answer.

        If the sources contain nothing about the topic, reply exactly:
        "I couldn't find this in your Notion page." and suggest what to ingest.
        """
    ).strip()

    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_prompt},
    ]
