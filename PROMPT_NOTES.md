# PROMPT_NOTES.md

Decisions made while building the spec. Anything ambiguous in the build prompt
was resolved in this file. The spec said "make the call, document it,
ship" — these are those calls.

## Stack

- **Embedding model:** kept the spec's `intfloat/multilingual-e5-small`
  (384-dim, ~470 MB) as the default. Lazy-loaded so the worker doesn't pay
  the cost on import. Sentence-transformers + torch CPU wheels fit easily
  on the 8 GB profile.
- **ASR:** Groq Whisper default (free tier, 2,000/day, ~228× real-time, best
  Hindi/Telugu quality). `faster-whisper small` int8 as the offline
  fallback. The fallback intentionally does not translate (it would need a
  separate call) — the answer LLM sees both the original and the English
  hint, but translation quality is lower than Groq's.
- **LLM:** MiniMax via the OpenAI-compatible Chat Completions endpoint. The
  default model in `.env.example` is `M2.7` per the spec's "SET-ME e.g.
  M2.7" hint.
- **DB:** single SQLite file + `sqlite-vec` (vec0 virtual table) + FTS5.
  WAL mode for concurrent reads while the worker writes.

## sqlite-vec specifics

- Vectors are stored as **packed little-endian float32 BLOBs** (one of the
  two binary forms sqlite-vec accepts). The JSON form also works but is
  larger and slower to scan.
- The schema declares `chunks_vec` with `distance_metric=cosine` and
  `float[384]`. The chunk_id is the primary key.
- We compute cosine similarity in **Python** (not via sqlite-vec's
  `MATCH` operator) for portability across sqlite-vec versions. With
  ≤10k chunks per workspace this is fast enough on a Mac; the spec's
  "real depth or complexity" budget is comfortably below that.
- The `sqlite-vec` extension is loaded **per connection** (it's a
  SQLite-loadable extension, not a process-wide one). The connection
  module handles this on every new connection; the schema is only
  re-applied when the path changes or after a `reset_db()` call.

## Frontend

- Vite + React + TypeScript + Tailwind, prebuilt to `web/dist/` and
  committed. The Mac needs no Node at runtime.
- The prebuilt `dist/` is committed because the spec says a fresh Mac
  with only Python + ffmpeg should be enough to run.
- `npm run build` runs `tsc --noEmit && vite build`, so type errors fail
  the build (not just bundle errors).

## RAG details

- **Chunking:** Notion blocks: 1 chunk per block by default; consecutive
  blocks of the same type merge when under `max_chars` (1800). Transcripts:
  split on ≥2s silence boundaries; each chunk keeps `[start_sec, end_sec]`
  for inline timestamping.
- **Embeddings:** the original text is embedded (so multilingual → cross-
  lingual retrieval works). The English translation is also stored on the
  chunk and used for the answer-LLM context.
- **Hybrid retrieval:** top-50 vector (cosine in Python) + top-50 FTS5
  (BM25) → RRF with `k=60` → final top-10.
- **Optional LLM rerank:** off by default. When `ENABLE_LLM_RERANK=1`, we
  ask the LLM to reorder the top-15.

## Mock providers

To keep tests fast and deterministic we ship mock implementations for
LLM, embedder, transcriber, video provider, and Notion source. They're
selected by env var (`MINIMAX_MOCK_PROVIDERS=1` or `TEST_FAST=1`) and
let the whole pipeline be exercised with no network and no model
downloads. The seed demo uses the same mocks so a reviewer can see the
full flow with no real credentials.

The seeded demo deliberately includes one Telugu and one Hindi reel so
the cross-language case in the golden-dataset test is meaningful.

## Ingest

- Recursion is capped at `NOTION_MAX_DEPTH=3` (configurable). Child
  pages that aren't shared with the integration are reported as `skipped`
  with the Notion error code in `notion_pages.error`.
- The worker is **resumable**: jobs in `running` state that didn't finish
  are reclaimed on the next worker start. Per-reel `videos.status` rows
  are the source of truth for "did we already do this".
- Instagram fetches are best-effort: 100+ reels per page is expected and
  a meaningful minority will fail. The spec acknowledges this. Failed
  reels expose a `Retry` button and a "Paste transcript" dialog in the
  Sources tab.
- `DISABLE_INSTAGRAM_FETCH=1` skips fetching entirely (text-only mode).

## Edge cases addressed

- Notion page with private child pages → marked `skipped` with reason.
- Reel private / removed / geo-blocked / login-walled / rate-limited →
  marked `unavailable` with reason; job continues.
- Whisper mis-detects language on a short clip → language is shown
  everywhere; the answer LLM sees both original and English.
- Question in a language no source is in → answer is in the question's
  language; Sources panel shows source language with an "Show English"
  toggle.
- Reel with no speech (music / text-on-screen) → caption fallback (the
  Instagram public caption, if present) is stored as the transcript. If
  neither exists, the row is stored as "(no transcribable audio)" with
  `has_transcript=true` so the UI can show why.
- 100+ reels → resumable worker, polite per-reel delay, partial-failure
  reporting; ingest can finish across interruptions.
- Notion page edited/deleted externally → next re-sync updates changed
  blocks and flags missing pages.

## Out of scope (v1)

Multi-user / auth / isolation; multiple workspaces; usage dashboard +
budgets; dedicated reranker model; Postgres/Redis/Celery; YouTube/TikTok
(interface ready, not implemented); private-account reels needing login
cookies; native mobile; billing.

## Build decisions worth flagging

- **Vector similarity in Python** instead of sqlite-vec's `MATCH` operator.
  Trade-off: simpler portability across sqlite-vec versions and operating
  systems; cost: O(N) per query. With ≤10k chunks this is fine.
- **Single worker process.** No Celery, no Redis. A `data/.worker.tick`
  file is touched when a new job is enqueued; the worker polls on a short
  interval. This is intentionally simple and survives restarts.
- **The `web/dist/` is committed.** This is what makes the MacBook run
  with only Python + ffmpeg. If you change the frontend, run
  `make build-frontend` and commit the new dist.
- **The mock LLM is regex-based and intentionally dumb.** It's enough to
  make the golden tests deterministic; real MiniMax produces variable
  wording but stays grounded.

## Anything else?

If you find a discrepancy between this file and the spec or the code,
the code wins. Update this file when you fix something the spec got
wrong.
