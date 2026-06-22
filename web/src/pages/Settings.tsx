import { useState } from "react";
import { useEffect } from "react";
import { api, getAppPassword, setAppPassword } from "../lib/api";

export function Settings() {
  const [pwd, setPwd] = useState(getAppPassword() || "");
  const [ffmpegOk, setFfmpegOk] = useState<boolean | null>(null);
  const [llmInfo, setLlmInfo] = useState<{ reachable: boolean; url?: string; error?: string } | null>(null);

  useEffect(() => {
    api.health().then((h) => {
      setFfmpegOk(h.ffmpeg ?? null);
      setLlmInfo({
        reachable: h.llm_reachable ?? true,
        url: h.llm_url,
        error: h.llm_error,
      });
    }).catch(() => {});
  }, []);

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <h1 className="text-xl font-semibold">Settings</h1>

      <section className="card p-4 space-y-3">
        <h2 className="text-sm font-medium">App password (this device)</h2>
        <p className="text-xs text-ink-500">
          Only set this if you started the server with <code>APP_PASSWORD</code>.
          The token is stored in your browser's localStorage and sent as a Bearer header.
        </p>
        <input
          type="password"
          className="input"
          value={pwd}
          onChange={(e) => setPwd(e.target.value)}
        />
        <div className="flex gap-2">
          <button
            className="btn-primary"
            onClick={() => {
              setAppPassword(pwd.trim() || null);
              location.reload();
            }}
          >
            Save
          </button>
          <button
            className="btn-ghost"
            onClick={() => {
              setAppPassword(null);
              setPwd("");
              location.reload();
            }}
          >
            Clear
          </button>
        </div>
      </section>

      <section className="card p-4 space-y-2 text-sm">
        <h2 className="text-sm font-medium">System</h2>
        <div className="text-ink-700">
          <span className="font-medium">ffmpeg:</span>{" "}
          {ffmpegOk === null ? (
            <span className="text-ink-500">checking…</span>
          ) : ffmpegOk ? (
            <span className="pill bg-emerald-50 text-emerald-700">installed</span>
          ) : (
            <span className="pill bg-red-50 text-red-700">missing</span>
          )}
          {!ffmpegOk && (
            <div className="mt-2 text-xs text-ink-500">
              Required to convert downloaded reel audio for Whisper transcription.
              <br />
              Install with: <code>brew install ffmpeg</code>
            </div>
          )}
        </div>
        <div className="text-ink-700 mt-3">
          <span className="font-medium">LLM service:</span>{" "}
          {llmInfo === null ? (
            <span className="text-ink-500">checking…</span>
          ) : llmInfo.reachable ? (
            <span className="pill bg-emerald-50 text-emerald-700">reachable</span>
          ) : (
            <span className="pill bg-red-50 text-red-700">unreachable</span>
          )}
          {llmInfo && !llmInfo.reachable && (
            <div className="mt-2 text-xs text-ink-500">
              Could not reach <code>{llmInfo.url}</code>
              {llmInfo.error ? <> — {llmInfo.error}</> : null}
              <br />
              Check your <code>.env</code>{" "}
              <code>MINIMAX_BASE_URL</code>. Default is{" "}
              <code>https://api.minimax.io/v1</code>.
            </div>
          )}
        </div>
      </section>

      <section className="card p-4 space-y-2 text-sm">
        <h2 className="text-sm font-medium">What data leaves your machine</h2>
        <ul className="list-disc pl-5 space-y-1 text-ink-600">
          <li>
            <strong>MiniMax</strong> receives your question + the retrieved source snippets
            to generate the answer.
          </li>
          <li>
            <strong>Groq</strong> receives the audio of any Instagram reel you ask it to
            transcribe (default ASR provider). Set <code>ASR_PROVIDER=local</code> to switch
            to local <code>faster-whisper</code> for fully-offline transcription.
          </li>
          <li>
            <strong>Notion</strong> is only called by the local server when you enqueue
            an ingest or re-sync.
          </li>
          <li>
            Everything else (Notion text, transcript caches, embeddings, chat history)
            stays on disk in <code>./data</code> and <code>./media_cache</code>.
          </li>
        </ul>
        <p className="text-xs text-ink-500 mt-2">
          See <code>README.md</code> → "Privacy & Instagram ToS" for the full disclosure
          and how to run fully-offline.
        </p>
      </section>
    </div>
  );
}
