import { useState } from "react";
import { login } from "../api";

export function Login({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("breathe-esg-admin");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setLoading(true);
    try {
      await login(username, password);
      onLoggedIn();
    } catch (e: any) {
      setErr(e.message || "Sign-in failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-slate-50">
      <div className="card w-full max-w-sm p-6">
        <h1 className="text-xl font-semibold text-brand mb-1">Breathe ESG</h1>
        <p className="text-sm text-slate-500 mb-6">
          Sign in to review and approve emissions data.
        </p>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="text-sm font-medium text-slate-700 block mb-1">
              Username
            </label>
            <input
              className="input w-full"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
            />
          </div>
          <div>
            <label className="text-sm font-medium text-slate-700 block mb-1">
              Password
            </label>
            <input
              className="input w-full"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {err && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-md p-2">
              {err}
            </div>
          )}
          <button className="btn-primary w-full" disabled={loading}>
            {loading ? "Signing in…" : "Sign in"}
          </button>
          <p className="text-xs text-slate-400 text-center">
            Default credentials from <code className="bg-slate-100 px-1 rounded">manage.py bootstrap</code>:
            admin / breathe-esg-admin
          </p>
        </form>
      </div>
    </div>
  );
}
