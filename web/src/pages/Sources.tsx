import { useEffect, useState } from "react";
import { api, type Sources, type SourceVideo } from "../lib/api";

export function Sources() {
  const [data, setData] = useState<Sources | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pasteFor, setPasteFor] = useState<SourceVideo | null>(null);

  async function refresh() {
    try {
      setErr(null);
      setData(await api.sources());
    } catch (e: any) {
      setErr(String(e?.message || e));
    }
  }
  useEffect(() => {
    refresh();
  }, []);

  if (err) return <div className="p-6 text-sm text-red-700">{err}</div>;
  if (!data) return <div className="p-6 text-sm text-ink-500">Loading…</div>;

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      <h1 className="text-xl font-semibold">Sources</h1>

      <section>
        <h2 className="text-sm font-medium text-ink-700 mb-2">
          Notion pages ({data.pages.length})
        </h2>
        <div className="card divide-y divide-ink-100">
          {data.pages.length === 0 ? (
            <div className="p-3 text-sm text-ink-500">No pages ingested yet.</div>
          ) : (
            data.pages.map((p) => (
              <div key={p.id} className="p-3 flex items-center gap-3">
                <span className="pill bg-ink-100 text-ink-700">depth {p.depth}</span>
                <span className="truncate font-medium flex-1" title={p.title}>
                  {p.title}
                </span>
                <span className="pill bg-blue-50 text-blue-700">{p.status}</span>
                <span className="text-xs text-ink-500">{p.block_count} blocks</span>
                <a
                  className="btn-ghost text-xs"
                  href={p.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open
                </a>
              </div>
            ))
          )}
        </div>
      </section>

      <section>
        <h2 className="text-sm font-medium text-ink-700 mb-2">
          Instagram reels ({data.videos.length})
        </h2>
        <div className="card divide-y divide-ink-100">
          {data.videos.length === 0 ? (
            <div className="p-3 text-sm text-ink-500">No reels ingested yet.</div>
          ) : (
            data.videos.map((v) => (
              <div key={v.id} className="p-3 flex items-center gap-3">
                <span
                  className={
                    "pill " +
                    (v.status === "done"
                      ? "bg-emerald-50 text-emerald-700"
                      : v.status === "unavailable"
                      ? "bg-red-50 text-red-700"
                      : "bg-ink-100 text-ink-700")
                  }
                >
                  {v.status}
                </span>
                {v.language && (
                  <span className="pill bg-ink-100 text-ink-700 uppercase">
                    {v.language}
                  </span>
                )}
                <span className="truncate flex-1" title={v.source_url}>
                  {v.source_url}
                </span>
                {v.error && (
                  <span className="text-xs text-red-700 max-w-[18rem] truncate" title={v.error}>
                    {v.error}
                  </span>
                )}
                {v.status === "unavailable" && (
                  <button
                    className="btn-ghost text-xs"
                    onClick={() => setPasteFor(v)}
                  >
                    Paste transcript
                  </button>
                )}
                <button
                  className="btn-ghost text-xs"
                  onClick={async () => {
                    await api.retrySource(v.id);
                    refresh();
                  }}
                >
                  Retry
                </button>
                <button
                  className="btn-danger text-xs"
                  onClick={async () => {
                    if (!confirm("Delete this source and its chunks?")) return;
                    await api.deleteSource(v.id);
                    refresh();
                  }}
                >
                  Delete
                </button>
              </div>
            ))
          )}
        </div>
      </section>

      {pasteFor && (
        <PasteTranscriptDialog
          video={pasteFor}
          onClose={() => setPasteFor(null)}
          onSaved={() => {
            setPasteFor(null);
            refresh();
          }}
        />
      )}
    </div>
  );
}

function PasteTranscriptDialog({
  video,
  onClose,
  onSaved,
}: {
  video: SourceVideo;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [text, setText] = useState("");
  const [lang, setLang] = useState(video.language || "en");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="card w-full max-w-2xl p-4 space-y-3">
        <div className="text-sm font-medium">Paste a transcript for this reel</div>
        <div className="text-xs text-ink-500 truncate">{video.source_url}</div>
        <textarea
          className="input min-h-[200px] font-mono text-xs"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste the full transcript text here…"
        />
        <div className="flex items-center gap-2">
          <label className="text-xs text-ink-500">Language</label>
          <input
            className="input max-w-[8rem]"
            value={lang}
            onChange={(e) => setLang(e.target.value)}
          />
        </div>
        {err && <div className="text-xs text-red-700">{err}</div>}
        <div className="flex justify-end gap-2">
          <button className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary"
            disabled={busy || !text.trim()}
            onClick={async () => {
              setBusy(true);
              setErr(null);
              try {
                await api.pasteTranscript(video.id, text.trim(), lang);
                onSaved();
              } catch (e: any) {
                setErr(String(e?.message || e));
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Saving…" : "Save & re-index"}
          </button>
        </div>
      </div>
    </div>
  );
}
