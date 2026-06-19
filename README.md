# AskMyNotion

Local single-user RAG over a Notion page and any Instagram reels linked from it.
Answers cite their sources inline, list every supporting source, give
timestamps for video clips, work across English / Hindi / Telugu sources, and
answer in the question's language. If the answer isn't in your sources, the
app says so instead of inventing one.

> Designed to run on a **MacBook Air, 8 GB RAM, no GPU**, **$0 budget**. No
> Docker, no Postgres, no Redis, no Node at runtime — the frontend is
> prebuilt and committed. Peak RAM stays under ~2 GB.

```
                       ┌────────────────────────┐
   Notion page ───────►│  NotionSource (token)  │
                       └────────────┬───────────┘
                                    │ text + child pages
                                    ▼
                       ┌────────────────────────┐
                       │  Ingest: chunk + embed │  ──► SQLite + sqlite-vec + FTS5
                       └────────────┬───────────┘
                                    │ Instagram URLs
                                    ▼
   Instagram reels ───►│  yt-dlp + ffmpeg audio  │
                        └────────────┬───────────┘
                                     │ 16 kHz wav
                                     ▼
                        ┌────────────────────────┐
                        │  Groq Whisper (default)│  ──► original + EN segments
                        │  OR local faster-whisper│
                        └────────────┬───────────┘
                                     │ transcript
                                     ▼
                        ┌────────────────────────┐
   User question ──────►│  Hybrid retrieve (RRF) │  ──► top-10 chunks
                        └────────────┬───────────┘
                                     │ contexts + question
                                     ▼
                        ┌────────────────────────┐
                        │  MiniMax answer (SSE)  │  ──► cited answer
                        └────────────────────────┘
```

## Quick start

```bash
# 1. Install Python deps + build the prebuilt frontend
make install

# 2. Configure
cp .env.example .env
# ...edit NOTION_TOKEN, NOTION_PAGE_URL, GROQ_API_KEY, MINIMAX_API_KEY ...

# 3. (Optional) Load the demo corpus — no real credentials needed
make seed

# 4. Run
make dev
# Open http://127.0.0.1:8000
```

Only **Python 3.11** and **`ffmpeg`** are required at runtime. `yt-dlp`,
`groq`, `notion-client`, etc. are all Python packages installed by
`make install`.

## Two-step Notion setup

1. Create an internal integration at
   <https://www.notion.so/my-integrations>. Copy its token.
2. Open the Notion page you want to ingest. Click the “…” menu →
   **Connections** → add your integration. **Sub-pages must be shared too**
   if you want them included (recursion depth is capped at
   `NOTION_MAX_DEPTH=3` by default).
3. Paste the token + page URL into the app's **Connect** tab (or into your
   `.env`) and save. The Notion page id is parsed from the URL or accepted
   raw (32 hex chars, with or without dashes).

Notion only allows integrations to read pages explicitly shared with them.
Child pages that aren't shared are reported as `skipped` in the Ingest view
and the job continues.

## Getting a free Groq key (for transcription)

1. Sign up at <https://console.groq.com>.
2. Create an API key.
3. Set `GROQ_API_KEY=...` in `.env`.

The free tier is **2,000 transcriptions/day** and runs ~228× real-time on
Whisper-large-v3 — fast enough for the typical 50–100 reel page.

## MiniMax

`MINIMAX_API_KEY` and `MINIMAX_MODEL` (default `M2.7`) configure the answer
LLM. The app uses the OpenAI-compatible Chat Completions endpoint.

## Fully-offline mode

If you don't want audio to leave your machine, set:

```bash
ASR_PROVIDER=local
```

This swaps Groq for **faster-whisper `small` int8** running locally. The
embedding model is local by default (`multilingual-e5-small`, ~470 MB). With
both set, the only outbound call is MiniMax for the final answer. To go
fully offline (no MiniMax), set `MINIMAX_API_KEY=` and add a different local
LLM provider via `app/providers/factory.py`.

## Known limitations

- **Instagram fetching is fragile.** With 100+ reels, expect a meaningful
  minority to fail (private / removed / region-locked / login-walled /
  rate-limited). Failed reels are marked `unavailable` with a reason and the
  ingest continues. You can retry or paste a transcript manually for any
  failed reel from the Sources tab.
- **The mock ASR and the mock LLM are deterministic.** The seeded demo
  produces exact answers only when `MINIMAX_MOCK_PROVIDERS=1`. With real
  MiniMax/Groq, answers will vary slightly but stay grounded.
- **Single user, single workspace.** No auth, no isolation, no
  multi-tenancy. Optional `APP_PASSWORD` is a single shared bearer token.
- **No reranker by default.** `ENABLE_LLM_RERANK=1` enables an optional
  MiniMax rerank of the top-15 hits (adds latency).
- **No Postgres, Redis, Celery, or a runtime Node process.** Everything is
  in one Python process + one worker; the frontend is static.
- **Vector search is in Python.** We compute cosine in Python over the
  `chunks_vec` blob to keep the implementation portable. With ≤10k chunks
  per workspace this is fast enough on a Mac; above that, swap in
  sqlite-vec's `MATCH` operator if your build supports it.

## Privacy & Instagram ToS

- **Outbound data:** MiniMax (your question + the retrieved snippets) and
  Groq (audio of reels you ask it to transcribe). Nothing else.
- **Local data:** the SQLite DB (chunks, transcripts, chat history) under
  `./data/`, the media cache under `./media_cache/`. Your Notion token is
  read from `.env` and only used to talk to Notion.
- **Instagram ToS:** AskMyNotion is best-effort for **public** content.
  Private-account reels requiring login are out of scope. The
  `DISABLE_INSTAGRAM_FETCH=1` config flag lets you ingest Notion text only
  and paste transcripts manually for any reels you want included. You are
  responsible for respecting Instagram's Terms and applicable copyright
  law.

## Data model

See `app/db/schema.sql`. Key tables: `workspace` (singleton), `notion_pages`,
`notion_blocks`, `videos`, `video_transcripts`, `chunks`, `chunks_vec`
(sqlite-vec), `chunks_fts` (FTS5), `ingestion_jobs`, `conversations`,
`messages`, `media_cache`.

## API

JSON; SSE where noted.

```
POST   /api/workspace            set/replace Notion source
GET    /api/workspace            current config + counts
POST   /api/ingest               enqueue ingest -> {jobId}
POST   /api/resync               force full re-ingest
GET    /api/ingest/status        SSE: job + per-source progress
GET    /api/sources              list pages + reels (+ per-reel retry)
POST   /api/sources/{id}/retry   re-fetch/re-transcribe one reel
POST   /api/sources/{id}/transcript  manual transcript paste
DELETE /api/sources/{id}         drop a source + its chunks
POST   /api/conversations        start a chat
GET    /api/conversations        list
GET    /api/conversations/{id}   detail
POST   /api/conversations/{id}/messages   SSE streaming chat
GET    /health
```

## Repo layout

```
askmynotion/
  app/                  FastAPI + worker
    providers/          ABCs + impls (LLM, embed, ASR, video, notion)
    ingest/             Notion walk, IG pipeline, chunker, indexer
    rag/                hybrid retrieval + answer prompt
    db/                 sqlite-vec + FTS5 schema + connection
  web/                  Vite + React + TS + Tailwind source
  web/dist/             PREBUILT static assets (committed)
  scripts/seed_demo.py  seeded demo
  tests/                unit + golden-dataset tests
  Makefile              install / dev / test / seed / build
  .env.example
  PROMPT_NOTES.md
```

## Testing

```bash
make test-fast    # mock providers, no model downloads, runs in ~5s
make test         # full pytest (still uses mocks by default; real models on demand)
```

The golden-dataset tests assert that:
- A question about dosa batter cites the English reel **with timestamps**.
- A question about the Notion page cites a Notion block.
- A Telugu reel is correctly cited for an English question about water intake
  (cross-language retrieval).
- A Hindi question about warm water returns the Hindi reel.
- An unanswerable question returns "I couldn't find this in your Notion
  page" instead of a hallucination.

## Architecture notes

- **Provider abstraction.** Every side-effecting subsystem is accessed via
  a Python ABC in `app/providers/`. The rest of the app imports only the
  interface. Swapping in a different LLM, embedder, ASR, or video fetcher
  is a one-file change in `app/providers/factory.py`.
- **Resumable ingest.** Each ingest job is a row in `ingestion_jobs`; per-reel
  status is a row in `videos.status`. The worker (`app/worker.py`) polls
  `pending` jobs and re-claims `running` jobs that didn't finish — restart
  the process mid-ingest and it picks up where it left off.
- **Streaming answers.** `POST /api/conversations/{id}/messages` returns an
  SSE stream: `data: {"type":"delta","delta":"..."}` for tokens,
  `data: {"type":"final","sources":[...], "not_found":...}` once.
- **Hybrid retrieval.** Top-50 cosine (in Python over `chunks_vec`) fused
  with top-50 FTS5 BM25 via Reciprocal Rank Fusion (`k=60`); final top-10.

## License

MIT.
