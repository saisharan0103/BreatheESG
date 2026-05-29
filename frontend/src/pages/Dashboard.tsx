import { useQuery } from "@tanstack/react-query";
import { getSummary } from "../api";

const SCOPE_LABELS: Record<number, string> = {
  1: "Scope 1 — direct",
  2: "Scope 2 — purchased electricity",
  3: "Scope 3 — value chain",
};

const STATUS_TONE: Record<string, string> = {
  pending: "bg-amber-100 text-amber-800",
  approved: "bg-emerald-100 text-emerald-800",
  rejected: "bg-slate-200 text-slate-700",
  flagged: "bg-red-100 text-red-800",
  locked: "bg-slate-800 text-white",
};

const SOURCE_LABELS: Record<string, string> = {
  sap: "SAP",
  utility_csv: "Utility CSV",
  utility_pdf: "Utility PDF",
  travel: "Travel",
};

export function Dashboard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["summary"],
    queryFn: getSummary,
  });
  if (isLoading) return <div className="text-slate-500">Loading…</div>;
  if (error)
    return (
      <div className="text-sm text-red-600">Failed to load: {String(error)}</div>
    );
  if (!data) return null;

  const totalCo2eTonnes = Number(data.total_co2e_kg || 0) / 1000;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Overview</h1>
        <p className="text-slate-500 text-sm">
          Carbon &amp; activity data ingested into the platform, by scope and by review state.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="card p-5">
          <div className="text-sm text-slate-500">Total records</div>
          <div className="mt-2 text-3xl font-semibold">{data.total_records}</div>
        </div>
        <div className="card p-5">
          <div className="text-sm text-slate-500">Total CO₂e</div>
          <div className="mt-2 text-3xl font-semibold">
            {totalCo2eTonnes.toFixed(2)}
            <span className="text-base font-medium text-slate-500 ml-1">t</span>
          </div>
        </div>
        <div className="card p-5">
          <div className="text-sm text-slate-500">Source breakdown</div>
          <div className="mt-2 text-sm space-y-1">
            {data.by_source.length === 0 && (
              <div className="text-slate-400">No data ingested yet.</div>
            )}
            {data.by_source.map((s: any) => (
              <div key={s.source_system} className="flex justify-between">
                <span>{SOURCE_LABELS[s.source_system] || s.source_system}</span>
                <span className="font-medium">{s.count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="card p-5">
          <div className="text-sm font-medium text-slate-700 mb-3">By scope</div>
          <div className="space-y-2">
            {data.by_scope.map((s: any) => (
              <div key={s.scope} className="flex items-center justify-between text-sm">
                <span>{SCOPE_LABELS[s.scope]}</span>
                <span className="text-slate-500">
                  {s.count} rec ·{" "}
                  <span className="font-mono">
                    {((Number(s.co2e_kg || 0)) / 1000).toFixed(2)} t
                  </span>
                </span>
              </div>
            ))}
          </div>
        </div>
        <div className="card p-5">
          <div className="text-sm font-medium text-slate-700 mb-3">By review status</div>
          <div className="space-y-2">
            {data.by_status.map((s: any) => (
              <div key={s.status} className="flex items-center justify-between text-sm">
                <span
                  className={`badge ${
                    STATUS_TONE[s.status] || "bg-slate-100 text-slate-700"
                  }`}
                >
                  {s.status}
                </span>
                <span className="text-slate-700 font-medium">{s.count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
