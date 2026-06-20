-- ─── AskMyNotion schema ───────────────────────────────────────────────────────
-- Idempotent: every CREATE uses IF NOT EXISTS. Safe to re-run on startup.
-- PRAGMA are emitted from the Python connection wrapper, not here.

-- ─── Workspace (singleton, single user) ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS workspace (
    id                         INTEGER PRIMARY KEY CHECK (id = 1),
    name                       TEXT NOT NULL DEFAULT 'My Notion',
    notion_page_id             TEXT NOT NULL,
    notion_page_url            TEXT NOT NULL,
    mode                       TEXT NOT NULL DEFAULT 'token',   -- 'token' | 'public'
    notion_last_edited_time    TEXT,
    created_at                 TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─── Notion pages ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notion_pages (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id        INTEGER NOT NULL,
    notion_page_id      TEXT NOT NULL,
    parent_page_id      TEXT,
    title               TEXT NOT NULL,
    url                 TEXT NOT NULL,
    depth               INTEGER NOT NULL DEFAULT 0,
    last_edited_time    TEXT,
    last_ingested_at    TEXT,
    status              TEXT NOT NULL DEFAULT 'pending',  -- pending|ingested|skipped|error
    error               TEXT,
    UNIQUE(workspace_id, notion_page_id)
);
CREATE INDEX IF NOT EXISTS idx_notion_pages_ws ON notion_pages(workspace_id);
CREATE INDEX IF NOT EXISTS idx_notion_pages_parent ON notion_pages(parent_page_id);

-- ─── Notion blocks (text-bearing) ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notion_blocks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    notion_page_id  TEXT NOT NULL,
    block_id        TEXT NOT NULL,
    type            TEXT NOT NULL,
    text            TEXT NOT NULL,
    deep_link       TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(notion_page_id, block_id)
);
CREATE INDEX IF NOT EXISTS idx_notion_blocks_page ON notion_blocks(notion_page_id);

-- ─── Videos (Instagram reels, etc.) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS videos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id    INTEGER NOT NULL,
    source_url      TEXT NOT NULL,
    canonical_url   TEXT NOT NULL,
    author          TEXT,
    status          TEXT NOT NULL DEFAULT 'queued',  -- queued|fetching|transcribing|done|unavailable
    error           TEXT,
    language        TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(workspace_id, canonical_url)
);
CREATE INDEX IF NOT EXISTS idx_videos_ws ON videos(workspace_id);
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);

-- ─── Transcripts ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS video_transcripts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id            INTEGER NOT NULL UNIQUE,
    language            TEXT,
    full_text_original  TEXT,
    full_text_en        TEXT,
    segments_json       TEXT NOT NULL,  -- JSON: [{start,end,text_original,text_en,language}]
    source              TEXT NOT NULL,  -- whisper|caption|manual
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─── Chunks (the unit of retrieval) ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chunks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id    INTEGER NOT NULL,
    source_type     TEXT NOT NULL,    -- notion_block | video_transcript | caption
    source_id       INTEGER NOT NULL,  -- notion_pages.id | videos.id | video_transcripts.id
    block_id        TEXT,             -- notion block_id when applicable
    video_id        INTEGER,          -- videos.id when applicable
    text_original   TEXT NOT NULL,
    text_en         TEXT,             -- nullable (e.g. when source is already English-only)
    language        TEXT,             -- ISO code, e.g. en, hi, te
    start_sec       REAL,             -- for video chunks
    end_sec         REAL,             -- for video chunks
    deep_link       TEXT NOT NULL,    -- Notion deep link or reel URL
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chunks_ws ON chunks(workspace_id);
CREATE INDEX IF NOT EXISTS idx_chunks_video ON chunks(video_id);
CREATE INDEX IF NOT EXISTS idx_chunks_block ON chunks(block_id);

-- ─── sqlite-vec: vector search over chunks ────────────────────────────────────
-- 384-dim float32 vectors (multilingual-e5-small). Cosine distance.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    embedding float[384] distance_metric=cosine
);

-- ─── FTS5: keyword/BM25 over original + English text ──────────────────────────
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text_original,
    text_en,
    tokenize='porter unicode61 remove_diacritics 2'
);

-- ─── Ingestion jobs ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id    INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending|running|done|error
    total_blocks    INTEGER NOT NULL DEFAULT 0,
    done_blocks     INTEGER NOT NULL DEFAULT 0,
    total_videos    INTEGER NOT NULL DEFAULT 0,
    done_videos     INTEGER NOT NULL DEFAULT 0,
    indexed_chunks  INTEGER NOT NULL DEFAULT 0,
    current_step    TEXT NOT NULL DEFAULT '',
    error           TEXT,
    debug_json      TEXT,           -- last set of URLs found, etc.
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_ws ON ingestion_jobs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON ingestion_jobs(status);

-- ─── Chat history ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL DEFAULT 'New chat',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id  INTEGER NOT NULL,
    role             TEXT NOT NULL,    -- user|assistant
    content          TEXT NOT NULL,
    citations_json   TEXT,             -- JSON list of citation dicts
    model            TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);

-- ─── Media cache (transcripts keyed by canonical URL) ─────────────────────────
CREATE TABLE IF NOT EXISTS media_cache (
    canonical_url   TEXT PRIMARY KEY,
    transcript_json TEXT NOT NULL,    -- JSON: same shape as video_transcripts.segments_json
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
