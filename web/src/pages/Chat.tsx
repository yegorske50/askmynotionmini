import { useEffect, useRef, useState } from "react";
import { api, Citation, Workspace } from "../lib/api";

type Msg = {
  id?: number;
  role: "user" | "assistant";
  content: string;
  sources?: Citation[];
  not_found?: boolean;
  streaming?: boolean;
};

// Group multiple citations that come from the same reel (transcript +
// caption + the user's one-line context all reference the same URL).
// Keeps the sources panel compact and shows all artifacts for a reel
// under one card.
type GroupedSource = {
  n: number;
  canonicalKey: string;
  title: string;
  type: string;
  language: string | null;
  deepLink: string;
  url: string;
  start: number | null;
  end: number | null;
  parts: Array<{
    kind: "transcript" | "caption" | "user_note" | "notion";
    snippet_original: string;
    snippet_en: string | null;
    timestamp?: string;
  }>;
};

function groupSources(sources: Citation[]): GroupedSource[] {
  const groups: Record<string, GroupedSource> = {};
  for (const s of sources) {
    // canonical key = canonical url for reels, or block id for notion
    const key = s.deep_link || s.url;
    if (!groups[key]) {
      groups[key] = {
        n: s.n,
        canonicalKey: key,
        title: s.title,
        type: s.type,
        language: s.language,
        deepLink: s.deep_link || s.url,
        url: s.url,
        start: s.start,
        end: s.end,
        parts: [],
      };
    }
    let kind: GroupedSource["parts"][0]["kind"] = "notion";
    if (s.type === "video_transcript") kind = "transcript";
    else if (s.type === "caption") kind = "caption";
    const timestamp =
      s.start != null && s.end != null
        ? `${fmtTimeRaw(s.start)}–${fmtTimeRaw(s.end)}`
        : undefined;
    groups[key].parts.push({
      kind,
      snippet_original: s.snippet_original || "",
      snippet_en: s.snippet_en || null,
      timestamp,
    });
    // keep the lowest n for stable chip numbering
    if (s.n < groups[key].n) groups[key].n = s.n;
  }
  // renumber sequentially
  return Object.values(groups)
    .sort((a, b) => a.n - b.n)
    .map((g, i) => ({ ...g, n: i + 1 }));
}

function fmtTimeRaw(s: number): string {
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return `${m}:${r.toString().padStart(2, "0")}`;
}

const SUGGESTED = [
  "What's the dosa batter ratio in my Notion page?",
  "How much water should I drink each day?",
  "What are the benefits of drinking warm water in the morning?",
];

export function Chat({ workspace }: { workspace: Workspace | null }) {
  const [convId, setConvId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .listConversations()
      .then((cs) => {
        if (cs.length > 0) {
          setConvId(cs[0].id);
          api.getConversation(cs[0].id).then((c) => {
            setMessages(
              c.messages.map((m) => ({
                id: m.id,
                role: m.role as any,
                content: m.content,
                sources: m.citations,
              }))
            );
          });
        }
      })
      .catch(() => {
        // ignore — likely needs auth
      });
  }, []);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, messages[messages.length - 1]?.content]);

  async function ensureConv() {
    if (convId) return convId;
    const c = await api.startConversation("New chat");
    setConvId(c.id);
    return c.id;
  }

  async function send(content: string) {
    if (!content.trim() || busy) return;
    setBusy(true);
    setError(null);
    const cid = await ensureConv();
    const userMsg: Msg = { role: "user", content };
    setMessages((m) => [...m, userMsg, { role: "assistant", content: "", streaming: true }]);
    setInput("");
    try {
      let acc = "";
      let finalSources: Citation[] = [];
      let notFound = false;
      for await (const ev of api.chatStream(cid, { content })) {
        if (ev.type === "delta") {
          acc += ev.delta;
          setMessages((m) => {
            const out = [...m];
            out[out.length - 1] = { ...out[out.length - 1], content: acc };
            return out;
          });
        } else if (ev.type === "final") {
          finalSources = ev.sources;
          notFound = ev.not_found;
          setMessages((m) => {
            const out = [...m];
            out[out.length - 1] = {
              ...out[out.length - 1],
              sources: finalSources,
              not_found: notFound,
              streaming: false,
            };
            return out;
          });
        }
      }
    } catch (e: any) {
      setError(String(e?.message || e));
      setMessages((m) => {
        const out = [...m];
        out[out.length - 1] = { ...out[out.length - 1], streaming: false };
        return out;
      });
    } finally {
      setBusy(false);
    }
  }

  if (!workspace) {
    return (
      <div className="max-w-2xl mx-auto p-6 text-sm text-ink-500">
        Connect a Notion page first (see the Connect tab).
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div ref={scroller} className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
          {messages.length === 0 && (
            <div className="space-y-2">
              <div className="text-sm text-ink-500">Try asking:</div>
              <div className="flex flex-wrap gap-2">
                {SUGGESTED.map((s) => (
                  <button
                    key={s}
                    className="btn-ghost border border-ink-200"
                    onClick={() => send(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <Bubble key={i} msg={m} />
          ))}
          {error && <div className="text-sm text-red-700">{error}</div>}
        </div>
      </div>

      <form
        className="border-t border-ink-200 bg-white"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <div className="max-w-3xl mx-auto px-4 py-3 flex items-end gap-2">
          <textarea
            className="input min-h-[44px] max-h-40 resize-y"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask anything about your Notion page or Instagram reels…"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
          />
          <button className="btn-primary" disabled={busy || !input.trim()} type="submit">
            Send
          </button>
        </div>
      </form>
    </div>
  );
}

function Bubble({ msg }: { msg: Msg }) {
  if (msg.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl px-4 py-2.5 bg-ink-900 text-white text-sm whitespace-pre-wrap">
          {msg.content}
        </div>
      </div>
    );
  }
  // Parse which source numbers the LLM actually cited [n] in the answer.
  // When the answer is empty (still streaming) we show everything so the
  // user has something to look at; once the answer lands we trim to
  // what's actually referenced.
  const cited = msg.content
    ? new Set(
        Array.from(msg.content.matchAll(/\[(\d+)\]/g))
          .map((m) => parseInt(m[1], 10))
          .filter((n) => Number.isFinite(n))
      )
    : null;
  const visible =
    msg.sources && cited
      ? msg.sources.filter((s) => cited.has(s.n))
      : msg.sources || [];
  return (
    <div className="flex">
      <div className="max-w-[92%]">
        <div
          className={
            "rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap " +
            (msg.not_found && !msg.content
              ? "bg-amber-50 text-amber-900 border border-amber-200"
              : "bg-white border border-ink-200 text-ink-900")
          }
        >
          {msg.content || (msg.streaming ? <span className="text-ink-400">thinking…</span> : "")}
        </div>
        {visible.length > 0 && (
          <SourcesPanel sources={groupSources(visible)} />
        )}
      </div>
    </div>
  );
}

function SourcesPanel({ sources }: { sources: GroupedSource[] }) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  return (
    <div className="mt-2">
      <div className="text-xs font-medium text-ink-500 mb-1">
        Sources ({sources.length})
      </div>
      <ul className="space-y-1.5">
        {sources.map((s) => {
          const open = !!expanded[s.canonicalKey];
          const isVideo = s.type === "video_transcript" || s.type === "caption";
          return (
            <li key={s.canonicalKey} className="card p-2.5 text-xs">
              <div className="flex items-center gap-2">
                <span className="citation-chip">{s.n}</span>
                <span className="font-medium truncate flex-1" title={s.title}>
                  {s.title}
                </span>
                {s.language && (
                  <span className="pill bg-ink-100 text-ink-700 uppercase">
                    {s.language}
                  </span>
                )}
                {isVideo && s.start != null && s.end != null && (
                  <span className="pill bg-blue-50 text-blue-700">
                    {fmtTime(s.start)}–{fmtTime(s.end)}
                  </span>
                )}
                <a
                  className="btn-ghost text-xs"
                  href={s.deepLink}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open
                </a>
                <button
                  className="btn-ghost text-xs"
                  onClick={() =>
                    setExpanded({ ...expanded, [s.canonicalKey]: !open })
                  }
                >
                  {open ? "Hide" : "Show"}
                </button>
              </div>
              {open && (
                <div className="mt-2 space-y-2">
                  {s.parts.length === 1 ? (
                    // Single artifact: show the snippet directly
                    <PartView part={s.parts[0]} />
                  ) : (
                    // Multiple artifacts (transcript + caption + user note):
                    // render each as its own collapsible subsection so
                    // you can read them in any order.
                    <div className="space-y-1.5">
                      {s.parts.map((p, i) => (
                        <PartView key={i} part={p} />
                      ))}
                    </div>
                  )}
                  <button
                    className="btn-ghost text-xs"
                    onClick={() => copyGroupedCitation(s)}
                  >
                    Copy citation
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

const PART_LABELS: Record<GroupedSource["parts"][0]["kind"], string> = {
  transcript: "Transcript",
  caption: "Instagram caption",
  user_note: "Your note",
  notion: "Notion",
};

function PartView({ part }: { part: GroupedSource["parts"][0] }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="border-l-2 border-ink-100 pl-2">
      <button
        className="text-ink-500 text-[11px] uppercase tracking-wide flex items-center gap-1.5"
        onClick={() => setOpen(!open)}
      >
        <span>{open ? "▾" : "▸"}</span>
        <span className="font-medium">
          {PART_LABELS[part.kind]}
          {part.timestamp ? ` · ${part.timestamp}` : ""}
        </span>
      </button>
      {open && (
        <div className="mt-1 space-y-1">
          {part.snippet_original && (
            <div className="text-ink-800 whitespace-pre-wrap">
              {part.snippet_original}
            </div>
          )}
          {part.snippet_en &&
            part.snippet_en !== part.snippet_original && (
              <div className="text-ink-500 text-[11px] italic whitespace-pre-wrap">
                EN: {part.snippet_en}
              </div>
            )}
        </div>
      )}
    </div>
  );
}

function fmtTime(s: number): string {
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return `${m}:${r.toString().padStart(2, "0")}`;
}

function copyGroupedCitation(s: GroupedSource) {
  const md = `[${s.n}] ${s.title} (${s.type}) — ${s.deepLink}`;
  navigator.clipboard?.writeText(md).catch(() => {});
}
