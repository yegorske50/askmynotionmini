"""End-to-end answer: retrieve -> prompt -> stream LLM -> emit citations."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

import structlog

from app.config import settings
from app.db import get_conn
from app.providers.base import ChatMessage
from app.rag.prompts import build_messages
from app.rag.retrieval import Hit, hybrid_retrieve, maybe_rerank

log = structlog.get_logger(__name__)


@dataclass
class CitationOut:
    n: int
    type: str
    title: str
    url: str
    deep_link: str
    snippet_original: str
    snippet_en: str | None
    language: str | None
    start: float | None
    end: float | None


@dataclass
class AnswerEvent:
    """Streamed answer event: either a text delta or a sources payload."""
    delta: str = ""
    sources: list[CitationOut] | None = None
    not_found: bool = False


def _hit_to_citation(n: int, hit: Hit, *, snippet_chars: int = 320) -> CitationOut:
    snip_o = (hit.text_original or "").strip()
    if len(snip_o) > snippet_chars:
        snip_o = snip_o[: snippet_chars - 1].rstrip() + "…"
    snip_e = hit.text_en
    if snip_e and len(snip_e) > snippet_chars:
        snip_e = snip_e[: snippet_chars - 1].rstrip() + "…"
    return CitationOut(
        n=n,
        type=hit.source_type,
        title=hit.title,
        url=hit.deep_link,
        deep_link=hit.deep_link,
        snippet_original=snip_o,
        snippet_en=snip_e,
        language=hit.language,
        start=hit.start_sec,
        end=hit.end_sec,
    )


def _detect_language(text: str) -> str:
    """Cheap language detection: Devanagari -> hi, Telugu script -> te, else en."""
    if not text:
        return "en"
    # Devanagari unicode range
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"
    # Telugu unicode range
    if re.search(r"[\u0C00-\u0C7F]", text):
        return "te"
    return "en"


def stream_answer(
    *,
    question: str,
    answer_language: str | None = None,
    conversation_id: int | None = None,
) -> Iterator[AnswerEvent]:
    """Yield text deltas, then a final AnswerEvent with sources (and a marker
    if the answer is "I couldn't find this in your Notion page.")."""
    embedder = _embedder()
    llm = _llm()

    with get_conn() as conn:
        row = conn.execute("SELECT id FROM workspace WHERE id = 1").fetchone()
        if not row:
            yield AnswerEvent(delta="(no workspace configured)")
            return
        workspace_id = int(row["id"])

        # If the embedder (which hits the MiniMax API) is unreachable we
        # still want the user to see *something*. Fall back to a pure
        # keyword search so the Sources panel is not empty, and surface
        # the error as a polite assistant message.
        try:
            hits = hybrid_retrieve(
                conn, query=question, workspace_id=workspace_id, embedder=embedder
            )
            if settings.enable_llm_rerank and hits:
                hits = maybe_rerank(hits, query=question, llm=llm)
        except Exception as e:
            log.warning("retrieval_failed", error=str(e)[:200])
            yield AnswerEvent(
                delta=(
                    "I couldn't reach the AI service to search your sources "
                    f"({type(e).__name__}). Your ingested data is safe — "
                    "this is a connection issue. Check that "
                    "MINIMAX_BASE_URL is reachable and try again."
                )
            )
            yield AnswerEvent(sources=[], not_found=True)
            return

    citations: list[CitationOut] = [_hit_to_citation(i + 1, h) for i, h in enumerate(hits)]
    contexts = [
        {
            "n": c.n,
            "source_type": c.type,
            "text_original": c.snippet_original,
            "text_en": c.snippet_en,
            "language": c.language,
            "start_sec": c.start,
            "end_sec": c.end,
            "deep_link": c.deep_link,
        }
        for c in citations
    ]

    lang = (answer_language or _detect_language(question) or "en").lower()
    msgs = build_messages(
        question=question, answer_language=lang, contexts=contexts
    )

    full = ""
    try:
        for ch in llm.stream_chat(
            [ChatMessage(role=m["role"], content=m["content"]) for m in msgs],
            temperature=0.2,
            max_tokens=800,
        ):
            if ch.delta:
                full += ch.delta
                yield AnswerEvent(delta=ch.delta)
    except Exception as e:
        # Never leak the raw exception (URL, stack, DNS detail) to the
        # user. Log it server-side, show a polite message.
        log.warning("llm.stream_failed", error=str(e)[:200])
        if not full.strip():
            # No answer text was produced. Yield a clean message
            # instead of the raw error.
            yield AnswerEvent(
                delta=(
                    f"I couldn't reach the AI service to generate an answer "
                    f"({type(e).__name__}). Your sources are listed below — "
                    "check MINIMAX_BASE_URL / network and try again."
                )
            )
            full = "(AI service unreachable)"

    # Fallbacks: if the LLM produced nothing (empty stream, or returned
    # only whitespace), give the user *something* based on the retrieved
    # sources instead of an empty answer.
    if not full.strip():
        if hits:
            top = citations[0]
            fallback = (
                f"Based on your sources, here is the most relevant match: "
                f"{top.snippet_original or top.snippet_en}"
            )
            full = fallback
            yield AnswerEvent(delta=fallback)
        else:
            fallback = (
                "I couldn't find anything in your Notion page or reels that "
                "matches this question. Try ingesting more sources, or check "
                "the spelling."
            )
            full = fallback
            yield AnswerEvent(delta=fallback)

    not_found = "couldn't find this in your notion page" in full.lower() or not hits

    # Persist messages (best-effort)
    try:
        with get_conn() as conn:
            if conversation_id is None:
                cur = conn.execute(
                    "INSERT INTO conversations(title) VALUES (?)",
                    (_short_title(question),),
                )
                conversation_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO messages(conversation_id, role, content) VALUES (?, ?, ?)",
                (conversation_id, "user", question),
            )
            conn.execute(
                "INSERT INTO messages(conversation_id, role, content, citations_json, model) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    conversation_id,
                    "assistant",
                    full,
                    _dump_citations(citations),
                    settings.MiniMax_model,
                ),
            )
    except Exception as e:
        log.warning("chat.persist_failed", error=str(e)[:200])

    yield AnswerEvent(sources=citations, not_found=not_found)


def _short_title(q: str) -> str:
    q = q.strip().splitlines()[0] if q.strip() else "Chat"
    return q[:60] if len(q) <= 60 else q[:59] + "…"


def _dump_citations(cits: list[CitationOut]) -> str:
    import orjson

    return orjson.dumps([c.__dict__ for c in cits]).decode("utf-8")


# Lazy provider accessors to avoid circular imports
def _embedder():
    from app.providers import get_embedder

    return get_embedder()


def _llm():
    from app.providers import get_llm

    return get_llm()
