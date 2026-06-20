import { useState } from "react";
import { api, Workspace } from "../lib/api";

export function Connect({
  workspace,
  onSaved,
  onGoIngest,
}: {
  workspace: Workspace | null;
  onSaved: () => void;
  onGoIngest: () => void;
}) {
  const [notionToken, setNotionToken] = useState("");
  const [pageUrl, setPageUrl] = useState(workspace?.notion_page_url || "");
  const [name, setName] = useState(workspace?.name || "My Notion");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  async function save() {
    setBusy(true);
    setErr(null);
    setSavedAt(null);
    try {
      await api.setWorkspace({
        notion_token: notionToken || undefined,
        notion_page_url: pageUrl,
        name,
      });
      setSavedAt(Date.now());
      onSaved();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <h1 className="text-xl font-semibold">Connect your Notion</h1>

      {workspace && (
        <div className="card p-4 bg-emerald-50 border-emerald-200">
          <div className="text-sm font-medium text-emerald-900">
            ✓ Connected
          </div>
          <div className="text-xs text-emerald-700 mt-1">
            Page: <span className="font-medium">{workspace.name}</span>{" "}
            <span className="text-emerald-600">
              ({workspace.counts.pages} pages, {workspace.counts.videos} videos,{" "}
              {workspace.counts.chunks} chunks)
            </span>
          </div>
          <div className="text-xs text-emerald-700 mt-1 truncate" title={workspace.notion_page_url}>
            <a
              className="underline"
              href={workspace.notion_page_url}
              target="_blank"
              rel="noreferrer"
            >
              {workspace.notion_page_url}
            </a>
          </div>
          <div className="mt-3 flex gap-2">
            <button className="btn-primary" onClick={onGoIngest}>
              Go to Ingest →
            </button>
          </div>
        </div>
      )}

      <div className="card p-4 space-y-3">
        <div>
          <label className="text-sm font-medium">Notion internal-integration token</label>
          <input
            className="input mt-1"
            value={notionToken}
            onChange={(e) => setNotionToken(e.target.value)}
            placeholder="secret_..."
            autoComplete="off"
          />
          <p className="text-xs text-ink-500 mt-1">
            Get one at{" "}
            <a
              className="underline"
              href="https://www.notion.so/my-integrations"
              target="_blank"
              rel="noreferrer"
            >
              notion.so/my-integrations
            </a>
            . Then share your target page with the integration
            ("…" → "Connections" → add the integration).
          </p>
        </div>

        <div>
          <label className="text-sm font-medium">Root Notion page URL or id</label>
          <input
            className="input mt-1"
            value={pageUrl}
            onChange={(e) => setPageUrl(e.target.value)}
            placeholder="https://www.notion.so/My-Page-1234567890abcdef1234567890abcdef"
          />
        </div>

        <div>
          <label className="text-sm font-medium">Workspace name</label>
          <input
            className="input mt-1"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        {err && (
          <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md p-2">
            {err}
          </div>
        )}
        {savedAt && !err && (
          <div className="text-sm text-emerald-700">
            ✓ Saved. Click <strong>Go to Ingest</strong> above (or the Ingest tab) to start.
          </div>
        )}

        <div className="flex gap-2">
          <button className="btn-primary" disabled={busy || !pageUrl} onClick={save}>
            {busy ? "Saving…" : workspace ? "Update" : "Save & continue"}
          </button>
          {workspace && (
            <button className="btn-ghost" onClick={onGoIngest}>
              Skip → Ingest
            </button>
          )}
        </div>
      </div>

      <div className="text-sm text-ink-500 leading-relaxed">
        <p className="font-medium text-ink-700 mb-1">Two-step Notion setup</p>
        <ol className="list-decimal pl-5 space-y-1">
          <li>
            Create an internal integration at notion.so/my-integrations. Copy its token.
          </li>
          <li>
            Open the Notion page you want to ingest. Click the "…" menu → "Connections" → add
            your integration. Sub-pages must be shared too if you want them included.
          </li>
          <li>Paste the token + page URL above and save.</li>
        </ol>
        <p className="mt-3">
          Notion only allows integrations to read pages explicitly shared with them. If a child
          page is not shared, it's reported as <code>skipped</code> in the Ingest view and the
          job continues.
        </p>
      </div>
    </div>
  );
}
