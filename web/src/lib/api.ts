// Tiny typed fetch helper for the AskMyNotion API.

export type SourceVideo = {
  id: number;
  source_url: string;
  author: string | null;
  status: string;
  error: string | null;
  language: string | null;
  has_transcript: boolean;
};

export type SourceNotionPage = {
  id: number;
  notion_page_id: string;
  title: string;
  url: string;
  depth: number;
  status: string;
  block_count: number;
};

export type Sources = { pages: SourceNotionPage[]; videos: SourceVideo[] };

export type Workspace = {
  name: string;
  notion_page_id: string;
  notion_page_url: string;
  mode: "token" | "public";
  counts: { pages: number; videos: number; chunks: number };
};

export type Citation = {
  n: number;
  type: "notion_block" | "video_transcript" | "caption";
  title: string;
  url: string;
  deep_link: string;
  snippet_original: string;
  snippet_en: string | null;
  language: string | null;
  start: number | null;
  end: number | null;
};

export type IngestStatus = {
  job_id: number;
  status: string;
  total_blocks: number;
  done_blocks: number;
  total_videos: number;
  done_videos: number;
  indexed_chunks: number;
  current_step: string;
  error: string | null;
  final?: boolean;
  reels?: Array<{ id: number; source_url: string; status: string; error: string | null }>;
};

const APP_PASSWORD_KEY = "askmynotion.app_password";

export function getAppPassword(): string | null {
  return localStorage.getItem(APP_PASSWORD_KEY);
}
export function setAppPassword(p: string | null) {
  if (p) localStorage.setItem(APP_PASSWORD_KEY, p);
  else localStorage.removeItem(APP_PASSWORD_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string>) || {}),
  };
  const pwd = getAppPassword();
  if (pwd) headers["Authorization"] = `Bearer ${pwd}`;
  const r = await fetch(path, { ...init, headers });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`${r.status} ${r.statusText}: ${text}`);
  }
  if (r.status === 204) return undefined as unknown as T;
  return (await r.json()) as T;
}

export const api = {
  health: () => request<{ status: string; chunks: number; videos: number }>("/health"),
  getWorkspace: () => request<Workspace>("/api/workspace"),
  setWorkspace: (body: { notion_token?: string; notion_page_url: string; name?: string }) =>
    request<Workspace>("/api/workspace", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  ingest: () => request<{ job_id: number }>("/api/ingest", { method: "POST" }),
  resync: () => request<{ job_id: number }>("/api/resync", { method: "POST" }),
  resetStuckJobs: () =>
    request<{ reset: boolean; previous_id?: number; new_job_id?: number; reason?: string }>(
      "/api/ingest/reset_stuck",
      { method: "POST" }
    ),
  sources: () => request<Sources>("/api/sources"),
  retrySource: (id: number) =>
    request<{ ok: boolean }>(`/api/sources/${id}/retry`, { method: "POST" }),
  deleteSource: (id: number) =>
    request<{ ok: boolean }>(`/api/sources/${id}`, { method: "DELETE" }),
  pasteTranscript: (id: number, text: string, language?: string) =>
    request<{ ok: boolean }>(`/api/sources/${id}/transcript`, {
      method: "POST",
      body: JSON.stringify({ text, language }),
    }),
  listConversations: () =>
    request<Array<{ id: number; title: string; created_at: string }>>(
      "/api/conversations"
    ),
  startConversation: (title?: string) =>
    request<{ id: number }>("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  getConversation: (id: number) =>
    request<{
      id: number;
      title: string;
      messages: Array<{
        id: number;
        role: string;
        content: string;
        citations?: Citation[];
      }>;
    }>(`/api/conversations/${id}`),
  ingestStatusStream: (onEvent: (s: IngestStatus) => void) => {
    const es = new EventSource(
      "/api/ingest/status" + (getAppPassword() ? `?_pwd=${encodeURIComponent(getAppPassword()!)}` : "")
    );
    es.addEventListener("data" as any, false as any);
    es.onmessage = (e) => {
      try {
        onEvent(JSON.parse(e.data));
      } catch {
        // ignore
      }
    };
    es.onerror = () => {
      // browser will auto-reconnect; the server's last "final" event will
      // arrive before any further changes.
    };
    return () => es.close();
  },
  chatStream: async function* (
    conversationId: number,
    body: { content: string; answer_language?: string }
  ): AsyncGenerator<
    | { type: "delta"; delta: string }
    | { type: "final"; sources: Citation[]; not_found: boolean }
  > {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const pwd = getAppPassword();
    if (pwd) headers["Authorization"] = `Bearer ${pwd}`;
    const r = await fetch(`/api/conversations/${conversationId}/messages`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    if (!r.ok || !r.body) {
      throw new Error(`${r.status} ${r.statusText}`);
    }
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        for (const line of chunk.split("\n")) {
          if (line.startsWith("data: ")) {
            const data = line.slice(6).trim();
            if (!data) continue;
            try {
              yield JSON.parse(data);
            } catch {
              // ignore
            }
          }
        }
      }
    }
  },
};
