import { useEffect, useRef, useState, ReactNode } from "react";
import type { JobState } from "./api";

const STATE_COLOR: Record<string, string> = {
  queued: "#5b8def", scheduled: "#a06bff", claimed: "#f0a63a", running: "#f0a63a",
  completed: "#2fbf88", failed: "#e5484d", dead: "#e5484d", cancelled: "#7a8699",
};

export function StatePill({ state }: { state: JobState | string }) {
  const c = STATE_COLOR[state] ?? "#7a8699";
  return (
    <span className="pill" style={{ borderColor: `${c}44`, background: `${c}18`, color: c }}>
      <span className="dot" style={{ background: c }} />
      {state}
    </span>
  );
}

export function stateColor(s: string) { return STATE_COLOR[s] ?? "#7a8699"; }

/** Poll a fetcher on an interval, exposing data, error and a manual refetch. */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs = 3000, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const saved = useRef(fetcher);
  saved.current = fetcher;

  async function run() {
    try { setData(await saved.current()); setError(null); }
    catch (e: any) { setError(e.message ?? "request failed"); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    setLoading(true);
    run();
    const id = setInterval(run, intervalMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, refetch: run };
}

export function Stat({ label, value, color }: { label: string; value: ReactNode; color?: string }) {
  return (
    <div className="card" style={{ padding: "14px 16px" }}>
      <div className="field-label" style={{ marginBottom: 6 }}>{label}</div>
      <div className="mono" style={{ fontSize: 26, fontWeight: 600, color: color ?? "#e6ebf2", lineHeight: 1 }}>
        {value}
      </div>
    </div>
  );
}

export function timeAgo(iso: string | null): string {
  if (!iso) return " ";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 0) return "in " + fmt(-s);
  return fmt(s) + " ago";
}
function fmt(s: number): string {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "#000a", display: "flex",
      alignItems: "center", justifyContent: "center", zIndex: 50, padding: 20 }}>
      <div className="card" onClick={(e) => e.stopPropagation()}
        style={{ width: 480, maxWidth: "100%", padding: 20, maxHeight: "90vh", overflow: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>{title}</h3>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="card" style={{ borderColor: "#4a2327", background: "#1c1215",
      color: "#ff8b8f", padding: "10px 14px", fontSize: 13, marginBottom: 12 }}>
      {message}
    </div>
  );
}
