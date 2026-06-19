import { useEffect, useState } from "react";
import { api, IngestStatus, Workspace } from "../lib/api";

export function Ingest({ workspace }: { workspace: Workspace | null }) {
  const [status, setStatus] = useState<IngestStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!workspace) return;
    const close = api.ingestStatusStream((s) => {
      setStatus(s);
      if (s.final) {
        // Keep showing but mark as done.
      }
    });
    return close;
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
        Set up your workspace on the Connect tab first.
      </div>
    );
  }

  const reels = status?.reels || [];
  const totalReels = status?.total_videos ?? reels.length;
  const doneReels = status?.done_videos ?? reels.filter((r) => r.status === "done" || r.status === "unavailable").length;
  const totalBlocks = status?.total_blocks ?? 0;
  const doneBlocks = status?.done_blocks ?? 0;

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-4">
      <div className="flex items-center gap-2">
        <h1 className="text-xl font-semibold">Ingest</h1>
        <div className="ml-auto flex gap-2">
          <button className="btn-ghost" disabled={busy} onClick={() => go(false)}>
            Incremental re-sync
          </button>
          <button className="btn-primary" disabled={busy} onClick={() => go(true)}>
            Force full re-ingest
          </button>
        </div>
      </div>

      {err && <div className="text-sm text-red-700">{err}</div>}

      <div className="card p-4 space-y-3">
        <div className="text-sm text-ink-600">
          Status: <span className="font-medium">{status?.status || "idle"}</span>{" "}
          {status?.current_step && (
            <span className="text-ink-400">— {status.current_step}</span>
          )}
        </div>
        <Progress
          label="Notion blocks"
          done={doneBlocks}
          total={totalBlocks}
        />
        <Progress
          label="Instagram reels"
          done={doneReels}
          total={totalReels}
        />
        <Progress
          label="Indexed chunks"
          done={status?.indexed_chunks || 0}
          total={status?.indexed_chunks || 0}
        />
      </div>

      <div className="card p-4">
        <div className="text-sm font-medium mb-2">Reels</div>
        {reels.length === 0 ? (
          <div className="text-sm text-ink-500">No reels detected on this page yet.</div>
        ) : (
          <ul className="space-y-1 text-sm">
            {reels.map((r) => (
              <li key={r.id} className="flex items-center gap-2">
                <ReelStatusPill status={r.status} />
                <span className="truncate flex-1" title={r.source_url}>
                  {r.source_url}
                </span>
                {r.error && <span className="text-xs text-ink-500">{r.error}</span>}
                {(r.status === "unavailable" || r.status === "queued") && (
                  <button
                    className="btn-ghost text-xs"
                    onClick={async () => {
                      await api.retrySource(r.id);
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
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  return (
    <div>
      <div className="flex justify-between text-xs text-ink-500">
        <span>{label}</span>
        <span>
          {done}/{total} ({pct}%)
        </span>
      </div>
      <div className="h-1.5 bg-ink-100 rounded-full overflow-hidden mt-1">
        <div
          className="h-full bg-ink-900 transition-all"
          style={{ width: `${pct}%` }}
        />
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
