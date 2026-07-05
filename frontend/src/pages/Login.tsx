import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, token } from "../api";
import { ErrorBanner } from "../components";

export default function Login() {
  const nav = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [org, setOrg] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true); setError(null);
    try {
      const res = mode === "login"
        ? await api.login({ email, password })
        : await api.register({ organization_name: org, email, password });
      token.set(res.access_token);
      nav("/");
    } catch (e: any) {
      setError(e.message ?? "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <div className="card" style={{ width: 380, padding: 28 }}>
        <div className="brand" style={{ fontSize: 18 }}>Scheduler Console</div>
        <div className="brand-sub" style={{ marginBottom: 20 }}>
          {mode === "login" ? "Sign in to your workspace" : "Create a new workspace"}
        </div>
        <ErrorBanner message={error} />
        {mode === "register" && (
          <div style={{ marginBottom: 12 }}>
            <label className="field-label">Organization name</label>
            <input className="input" value={org} onChange={(e) => setOrg(e.target.value)} placeholder="Acme Inc" />
          </div>
        )}
        <div style={{ marginBottom: 12 }}>
          <label className="field-label">Email</label>
          <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        </div>
        <div style={{ marginBottom: 18 }}>
          <label className="field-label">Password</label>
          <input className="input" type="password" value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()} placeholder="At least 8 characters" />
        </div>
        <button className="btn btn-primary" style={{ width: "100%" }} onClick={submit} disabled={busy}>
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create workspace"}
        </button>
        <div style={{ textAlign: "center", marginTop: 16, fontSize: 13 }} className="muted">
          {mode === "login" ? "No workspace yet? " : "Already have one? "}
          <span className="link" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}>
            {mode === "login" ? "Create one" : "Sign in"}
          </span>
        </div>
      </div>
    </div>
  );
}
