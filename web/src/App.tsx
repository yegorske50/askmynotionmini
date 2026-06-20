import { Component, ReactNode, useEffect, useState } from "react";
import { Connect } from "./pages/Connect";
import { Ingest } from "./pages/Ingest";
import { Chat } from "./pages/Chat";
import { Sources } from "./pages/Sources";
import { Settings } from "./pages/Settings";
import { api, getAppPassword, setAppPassword, Workspace } from "./lib/api";

type Tab = "connect" | "ingest" | "chat" | "sources" | "settings";

// ─── Error Boundary (top-level so a render error doesn't white-canvas) ────
class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error, info: unknown) {
    // eslint-disable-next-line no-console
    console.error("App error boundary caught:", error, info);
  }
  render() {
    if (this.state.error) {
      return (
        <div className="max-w-2xl mx-auto p-6">
          <div className="card p-4 bg-red-50 border-red-200 space-y-2">
            <div className="text-sm font-medium text-red-900">
              Something went wrong rendering this view.
            </div>
            <pre className="text-xs text-red-800 whitespace-pre-wrap break-words">
              {String(this.state.error?.message || this.state.error)}
            </pre>
            <div className="flex gap-2 pt-2">
              <button
                className="btn-primary"
                onClick={() => {
                  this.setState({ error: null });
                }}
              >
                Try again
              </button>
              <button
                className="btn-ghost"
                onClick={() => location.reload()}
              >
                Reload page
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

// ─── App ────────────────────────────────────────────────────────────────────
function AppInner() {
  const [tab, setTab] = useState<Tab>("connect");
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needsAuth, setNeedsAuth] = useState(false);
  const [pwdInput, setPwdInput] = useState("");
  const [health, setHealth] = useState<{
    chunks: number;
    videos: number;
    status: string;
  } | null>(null);

  async function refresh() {
    try {
      setError(null);
      const w = await api.getWorkspace();
      setWorkspace(w);
      setNeedsAuth(false);
    } catch (e: any) {
      const msg = String(e?.message || e);
      if (msg.includes("401")) {
        setNeedsAuth(true);
      } else if (msg.includes("404")) {
        setWorkspace(null);
      } else {
        setError(msg);
      }
    }
    try {
      setHealth(await api.health());
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  const hasWorkspace = !!workspace;

  return (
    <div className="h-full flex flex-col">
      <header className="border-b border-ink-200 bg-white">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center gap-4">
          <div className="font-semibold text-lg">AskMyNotion</div>
          <nav className="flex gap-1 ml-2 text-sm">
            <TabBtn active={tab === "chat"} onClick={() => setTab("chat")}>
              Chat
            </TabBtn>
            <TabBtn active={tab === "ingest"} onClick={() => setTab("ingest")}>
              Ingest
            </TabBtn>
            <TabBtn active={tab === "sources"} onClick={() => setTab("sources")}>
              Sources
            </TabBtn>
            <TabBtn active={tab === "connect"} onClick={() => setTab("connect")}>
              Connect
            </TabBtn>
            <TabBtn active={tab === "settings"} onClick={() => setTab("settings")}>
              Settings
            </TabBtn>
          </nav>
          <div className="ml-auto text-xs text-ink-500 flex items-center gap-3">
            {hasWorkspace ? (
              <span
                className="pill bg-emerald-50 text-emerald-700"
                title={workspace!.notion_page_url}
              >
                ✓ {workspace!.name}
              </span>
            ) : (
              <span
                className="pill bg-amber-50 text-amber-700"
                title="No workspace set"
              >
                not connected
              </span>
            )}
            {health && (
              <>
                <span title="chunks">📚 {health.chunks}</span>
                <span title="videos">🎞 {health.videos}</span>
              </>
            )}
          </div>
        </div>
      </header>

      {needsAuth && (
        <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 text-sm flex items-center gap-2">
          <span>App password required:</span>
          <input
            type="password"
            className="input max-w-[16rem]"
            value={pwdInput}
            onChange={(e) => setPwdInput(e.target.value)}
            placeholder="APP_PASSWORD"
          />
          <button
            className="btn-primary"
            onClick={() => {
              setAppPassword(pwdInput.trim() || null);
              setPwdInput("");
              refresh();
            }}
          >
            Unlock
          </button>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border-b border-red-200 text-red-700 px-4 py-2 text-sm flex items-center gap-2">
          <span className="flex-1">{error}</span>
          <button className="btn-ghost text-xs" onClick={() => setError(null)}>
            dismiss
          </button>
        </div>
      )}

      {!hasWorkspace && tab !== "connect" && (
        <div className="bg-amber-50 border-b border-amber-200 text-amber-900 px-4 py-2 text-sm flex items-center gap-2">
          <span className="flex-1">
            Workspace not configured. Head to{" "}
            <button
              className="underline font-medium"
              onClick={() => setTab("connect")}
            >
              Connect
            </button>{" "}
            to set up your Notion page.
          </span>
        </div>
      )}

      <main className="flex-1 min-h-0">
        <ErrorBoundary>
          {tab === "connect" && (
            <Connect
              workspace={workspace}
              onSaved={refresh}
              onGoIngest={() => setTab("ingest")}
            />
          )}
          {tab === "ingest" && <Ingest workspace={workspace} />}
          {tab === "chat" && <Chat workspace={workspace} />}
          {tab === "sources" && <Sources />}
          {tab === "settings" && <Settings />}
        </ErrorBoundary>
      </main>
    </div>
  );
}

function TabBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={
        "px-3 py-1.5 rounded-md text-sm transition-colors " +
        (active
          ? "bg-ink-900 text-white"
          : "text-ink-700 hover:bg-ink-100")
      }
    >
      {children}
    </button>
  );
}

export function App() {
  return <AppInner />;
}
