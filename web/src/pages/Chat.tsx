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
  return (
    <div className="flex">
      <div className="max-w-[92%]">
        <div
          className={
            "rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap " +
            (msg.not_found
              ? "bg-amber-50 text-amber-900 border border-amber-200"
              : "bg-white border border-ink-200 text-ink-900")
          }
        >
          {msg.content ||
            (msg.streaming ? "…" : "")}
        </div>
        {msg.sources && msg.sources.length > 0 && (
          <SourcesPanel sources={msg.sources} />
        )}
      </div>
    </div>
  );
}

function SourcesPanel({ sources }: { sources: Citation[] }) {
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  return (
    <div className="mt-2">
      <div className="text-xs font-medium text-ink-500 mb-1">
        Sources ({sources.length})
      </div>
      <ul className="space-y-1.5">
        {sources.map((s) => {
          const open = expanded[s.n] || false;
          const isVideo = s.type === "video_transcript" || s.type === "caption";
          return (
            <li key={s.n} className="card p-2.5 text-xs">
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
                  href={s.deep_link || s.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open
                </a>
                <button
                  className="btn-ghost text-xs"
                  onClick={() => setExpanded({ ...expanded, [s.n]: !open })}
                >
                  {open ? "Hide" : "Show"}
                </button>
              </div>
              {open && (
                <div className="mt-2 space-y-2">
                  <div className="text-ink-700">{s.snippet_original}</div>
                  {s.snippet_en && s.snippet_en !== s.snippet_original && (
                    <details>
                      <summary className="cursor-pointer text-ink-500">
                        Show English
                      </summary>
                      <div className="mt-1 text-ink-700">{s.snippet_en}</div>
                    </details>
                  )}
                  <button
                    className="btn-ghost text-xs"
                    onClick={() => copyCitation(s)}
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

function fmtTime(s: number): string {
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return `${m}:${r.toString().padStart(2, "0")}`;
}

function copyCitation(s: Citation) {
  const md = `[${s.n}] ${s.title} (${s.type}) — ${s.deep_link || s.url}`;
  navigator.clipboard?.writeText(md).catch(() => {});
}
