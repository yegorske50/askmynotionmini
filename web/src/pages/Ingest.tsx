import { useEffect, useRef, useState } from "react";
import { api, IngestStatus, Workspace } from "../lib/api";

export function Ingest({ workspace }: { workspace: Workspace | null }) {
  const [status, setStatus] = useState<IngestStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [sseState, setSseState] = useState<"connecting" | "open" | "error" | "closed">("closed");
  const esRef = useRef<EventSource | null>(null);

  // Subscribe to SSE; fall back to polling on error.
  useEffect(() => {
    if (!workspace) return;
    let cancelled = false;
    let pollTimer: number | null = null;
    setSseState("connecting");

    const fallbackToPolling = () => {
      if (cancelled) return;
      setSseState("error");
      const tick = async () => {
        if (cancelled) return;
        try {
          const r = await fetch("/api/ingest/status?poll=1", {
            headers: apiAuthHeaders(),
          });
          if (r.ok) {
            const j = await r.json();
            setStatus(j);
          }
        } catch {
          // ignore
        } finally {
          if (!cancelled) {
            pollTimer = window.setTimeout(tick, 1500);
          }
        }
      };
      tick();
    };

    try {
      const url =
        "/api/ingest/status" + (pwdQueryString() || "");
      const es = new EventSource(url);
      esRef.current = es;
      es.onopen = () => {
        if (!cancelled) setSseState("open");
      };
      es.onmessage = (e) => {
        if (cancelled) return;
        try {
          setStatus(JSON.parse(e.data));
        } catch {
          // ignore non-JSON keepalives
        }
      };
      es.onerror = () => {
        try {
          es.close();
        } catch {
          // ignore
        }
        esRef.current = null;
        if (!cancelled) fallbackToPolling();
      };
    } catch (e) {
      console.error("SSE failed, falling back to polling", e);
      fallbackToPolling();
    }

    return () => {
      cancelled = true;
      if (esRef.current) {
        try {
          esRef.current.close();
        } catch {
          // ignore
        }
        esRef.current = null;
      }
      if (pollTimer) window.clearTimeout(pollTimer);
      setSseState("closed");
    };
  }, [workspace]);

  async function go(full: boolean) {
    setBusy(true);
    setErr(null);
    try {
      if (full) await api.resync();
      else await api.ingest();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  }

  if (!workspace) {
    return (
      <div className="max-w-2xl mx-auto p-6 text-sm text-ink-500">
        Set up your workspace on the{" "}
        <button
          className="underline"
          onClick={() => {
            const btns = document.querySelectorAll("button");
            btns.forEach((b) => {
              if (b.textContent === "Connect") (b as HTMLButtonElement).click();
            });
          }}
        >
          Connect
        </button>{" "}
        tab first.
      </div>
    );
  }

  const reels = status?.reels || [];
  const totalReels = status?.total_videos ?? reels.length;
  const doneReels =
    status?.done_videos ??
    reels.filter((r) => r.status === "done" || r.status === "unavailable").length;
  const totalBlocks = status?.total_blocks ?? 0;
  const doneBlocks = status?.done_blocks ?? 0;
  const indexed = status?.indexed_chunks ?? 0;

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-4">
      <div className="flex items-center gap-2">
        <h1 className="text-xl font-semibold">Ingest</h1>
        <div className="ml-auto flex gap-2">
          <button
            className="btn-ghost text-xs"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setErr(null);
              setInfo(null);
              try {
                const r = await api.resetStuckJobs();
                if (r.reset) {
                  setInfo(
                    `Recovered: marked job #${r.previous_id} as error, enqueued a fresh job #${r.new_job_id}.`
                  );
                } else {
                  setInfo(`Nothing to recover: ${r.reason}`);
                }
              } catch (e: any) {
                setErr(String(e?.message || e));
              } finally {
                setBusy(false);
              }
            }}
            title="If a job is stuck in 'running', mark it error and enqueue a fresh one"
          >
            Recover stuck job
          </button>
          <button className="btn-ghost" disabled={busy} onClick={() => go(false)}>
            Incremental re-sync
          </button>
          <button className="btn-primary" disabled={busy} onClick={() => go(true)}>
            Force full re-ingest
          </button>
        </div>
      </div>

      {err && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md p-2">
          {err}
        </div>
      )}
      {info && (
        <div className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-md p-2">
          {info}
        </div>
      )}

      <div className="card p-4 space-y-3">
        <div className="text-sm text-ink-600 flex items-center gap-2">
          <span>
            Status: <span className="font-medium">{status?.status || "idle"}</span>
          </span>
          {sseState === "connecting" && (
            <span className="pill bg-ink-100 text-ink-700">connecting…</span>
          )}
          {sseState === "open" && (
            <span className="pill bg-emerald-50 text-emerald-700">live</span>
          )}
          {sseState === "error" && (
            <span className="pill bg-amber-50 text-amber-700">polling</span>
          )}
        </div>
        {status?.current_step && (
          <div className="text-xs text-ink-500">{status.current_step}</div>
        )}
        <Progress label="Notion blocks" done={doneBlocks} total={totalBlocks} />
        <Progress label="Instagram reels" done={doneReels} total={totalReels} />
        <Progress label="Indexed chunks" done={indexed} total={indexed} />
      </div>

      <div className="card p-4">
        <div className="text-sm font-medium mb-2">Reels</div>
        {reels.length === 0 ? (
          <div className="text-sm text-ink-500">
            No reels detected on this page yet. Reels on your Notion page will appear here
            after you start an ingest.
          </div>
        ) : (
          <ul className="space-y-1 text-sm">
            {reels.map((r) => (
              <li key={r.id} className="flex items-center gap-2">
                <ReelStatusPill status={r.status} />
                <span className="truncate flex-1" title={r.source_url}>
                  {r.source_url}
                </span>
                {r.error && (
                  <span className="text-xs text-ink-500 max-w-[20rem] truncate" title={r.error}>
                    {r.error}
                  </span>
                )}
                {(r.status === "unavailable" || r.status === "queued") && (
                  <button
                    className="btn-ghost text-xs"
                    onClick={async () => {
                      try {
                        await api.retrySource(r.id);
                      } catch (e: any) {
                        setErr(String(e?.message || e));
                      }
                    }}
                  >
                    Retry
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Progress({ label, done, total }: { label: string; done: number; total: number }) {
  const d = Number.isFinite(done) ? done : 0;
  const t = Number.isFinite(total) ? total : 0;
  const pct = t > 0 ? Math.min(100, Math.round((d / t) * 100)) : 0;
  return (
    <div>
      <div className="flex justify-between text-xs text-ink-500">
        <span>{label}</span>
        <span>
          {d}/{t} ({pct}%)
        </span>
      </div>
      <div className="h-1.5 bg-ink-100 rounded-full overflow-hidden mt-1">
        <div className="h-full bg-ink-900 transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function ReelStatusPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    queued: "bg-ink-100 text-ink-700",
    fetching: "bg-blue-50 text-blue-700",
    transcribing: "bg-amber-50 text-amber-700",
    done: "bg-emerald-50 text-emerald-700",
    unavailable: "bg-red-50 text-red-700",
  };
  return <span className={"pill " + (map[status] || "bg-ink-100 text-ink-700")}>{status}</span>;
}

function pwdQueryString(): string {
  if (typeof window === "undefined") return "";
  const pwd = window.localStorage.getItem("askmynotion.app_password");
  return pwd ? `?_pwd=${encodeURIComponent(pwd)}` : "";
}

function apiAuthHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const pwd = window.localStorage.getItem("askmynotion.app_password");
  return pwd ? { Authorization: `Bearer ${pwd}` } : {};
}
