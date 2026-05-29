import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listPeriods, lockPeriod, unlockPeriod } from "../api";

export function Periods({ canLock }: { canLock: boolean }) {
  const qc = useQueryClient();
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["periods"],
    queryFn: listPeriods,
  });

  const onLock = async (id: string) => {
    setErr(null);
    setBusy(id);
    try {
      await lockPeriod(id);
      qc.invalidateQueries({ queryKey: ["periods"] });
      qc.invalidateQueries({ queryKey: ["records"] });
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  };

  const onUnlock = async (id: string) => {
    setErr(null);
    setBusy(id);
    try {
      await unlockPeriod(id);
      qc.invalidateQueries({ queryKey: ["periods"] });
      qc.invalidateQueries({ queryKey: ["records"] });
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  };

  if (isLoading) return <div className="text-slate-500 text-sm">Loading…</div>;
  if (error)
    return <div className="text-sm text-red-600">{String(error)}</div>;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Reporting periods</h1>
        <p className="text-sm text-slate-500">
          Locking a period freezes every approved record whose `period_end`
          falls inside it. Locking is the audit gate; any records still
          `pending` or `flagged` block the lock until reviewed.
        </p>
        {!canLock && (
          <div className="mt-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2 inline-block">
            Only admin role can lock or unlock periods.
          </div>
        )}
      </div>
      {err && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2">
          {err}
        </div>
      )}
      <div className="card overflow-hidden">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-slate-600 text-xs uppercase">
            <tr>
              <th className="text-left p-3">Label</th>
              <th className="text-left p-3">Period</th>
              <th className="text-right p-3">Records</th>
              <th className="text-left p-3">Status</th>
              <th className="text-left p-3">Locked by</th>
              <th className="p-3" />
            </tr>
          </thead>
          <tbody>
            {data?.results.map((p: any) => (
              <tr key={p.id} className="border-t border-slate-100">
                <td className="p-3 font-medium">{p.label}</td>
                <td className="p-3 text-slate-600 whitespace-nowrap">
                  {p.period_start} → {p.period_end}
                </td>
                <td className="p-3 text-right">{p.records_in_period}</td>
                <td className="p-3">
                  <span
                    className={`badge ${
                      p.status === "locked"
                        ? "bg-slate-800 text-white"
                        : "bg-emerald-100 text-emerald-800"
                    }`}
                  >
                    {p.status}
                  </span>
                </td>
                <td className="p-3 text-xs text-slate-500">
                  {p.locked_by_username
                    ? `${p.locked_by_username} · ${new Date(
                        p.locked_at
                      ).toLocaleString()}`
                    : "—"}
                </td>
                <td className="p-3 text-right">
                  {canLock &&
                    (p.status === "open" ? (
                      <button
                        className="btn-primary"
                        disabled={busy === p.id}
                        onClick={() => onLock(p.id)}
                      >
                        {busy === p.id ? "Locking…" : "Lock period"}
                      </button>
                    ) : (
                      <button
                        className="btn-secondary"
                        disabled={busy === p.id}
                        onClick={() => onUnlock(p.id)}
                      >
                        {busy === p.id ? "Unlocking…" : "Unlock"}
                      </button>
                    ))}
                </td>
              </tr>
            ))}
            {data?.results.length === 0 && (
              <tr>
                <td colSpan={6} className="p-6 text-center text-slate-400">
                  No reporting periods yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
