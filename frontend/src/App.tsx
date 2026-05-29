import { useState, useEffect, type ReactNode } from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
  Link,
  useNavigate,
  useLocation,
} from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { Ingestion } from "./pages/Ingestion";
import { RecordList } from "./pages/RecordList";
import { RecordDetail } from "./pages/RecordDetail";
import { Periods } from "./pages/Periods";
import { getToken, setToken, whoami, type Me } from "./api";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 0, refetchOnWindowFocus: false } },
});

function RequireAuth({
  children,
  me,
}: {
  children: ReactNode;
  me: Me | null;
}) {
  const location = useLocation();
  if (!me) return <Navigate to="/login" state={{ from: location }} replace />;
  return children;
}

function Shell({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const location = useLocation();
  const nav = (to: string, label: string) => {
    const active =
      location.pathname === to || location.pathname.startsWith(to + "/");
    return (
      <Link
        to={to}
        className={`px-3 py-2 text-sm rounded-md ${
          active ? "bg-brand text-white" : "text-slate-600 hover:bg-slate-100"
        }`}
      >
        {label}
      </Link>
    );
  };
  return (
    <div className="min-h-full">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-7xl px-4 py-3 flex items-center gap-6">
          <div className="font-semibold text-brand">Breathe&nbsp;ESG</div>
          <nav className="flex gap-1">
            {nav("/dashboard", "Dashboard")}
            {nav("/ingest", "Ingest")}
            {nav("/records", "Records")}
            {nav("/periods", "Reporting periods")}
          </nav>
          <div className="ml-auto text-sm text-slate-500 flex items-center gap-3">
            <span>
              {me.username}
              <span className="ml-1 badge bg-slate-100 text-slate-700">
                {me.role}
              </span>
            </span>
            <span className="text-slate-300">·</span>
            <span>{me.tenant?.name}</span>
            <button className="btn-secondary" onClick={onLogout}>
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Routes>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/ingest" element={<Ingestion />} />
          <Route path="/records" element={<RecordList />} />
          <Route path="/records/:id" element={<RecordDetail />} />
          <Route
            path="/periods"
            element={<Periods canLock={me.role === "admin"} />}
          />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function AppInner() {
  const [me, setMe] = useState<Me | null>(null);
  const [loaded, setLoaded] = useState(false);
  const navigate = useNavigate();

  const refresh = async () => {
    if (!getToken()) {
      setLoaded(true);
      return;
    }
    try {
      const data = await whoami();
      setMe(data);
    } catch {
      setToken(null);
    } finally {
      setLoaded(true);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const onLogout = () => {
    setToken(null);
    setMe(null);
    navigate("/login");
  };

  if (!loaded) return <div className="p-8 text-slate-500">Loading…</div>;

  return (
    <Routes>
      <Route
        path="/login"
        element={
          me ? <Navigate to="/dashboard" replace /> : <Login onLoggedIn={refresh} />
        }
      />
      <Route
        path="/*"
        element={
          <RequireAuth me={me}>
            {me ? <Shell me={me} onLogout={onLogout} /> : <span />}
          </RequireAuth>
        }
      />
    </Routes>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppInner />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
