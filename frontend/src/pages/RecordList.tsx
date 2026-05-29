import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listRecords, type ActivityRecord } from "../api";

const STATUS_TONE: Record<string, string> = {
  pending: "bg-amber-100 text-amber-800",
  approved: "bg-emerald-100 text-emerald-800",
  rejected: "bg-slate-200 text-slate-700",
  flagged: "bg-red-100 text-red-800",
  locked: "bg-slate-800 text-white",
};

const SCOPE_LABEL: Record<number, string> = {
  1: "S1",
  2: "S2",
  3: "S3",
};

export function RecordList() {
  const [scope, setScope] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [source, setSource] = useState<string>("");
  const [flagged, setFlagged] = useState<boolean>(false);

  const filters: Record<string, string> = {};
  if (scope) filters.scope = scope;
  if (status) filters.status = status;
  if (source) filters.source = source;
  if (flagged) filters.flagged = "1";

  const { data, isLoading, error } = useQuery({
    queryKey: ["records", filters],
    queryFn: () => listRecords(filters),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Records</h1>
          <p className="text-sm text-slate-500">
            All ingested activity rows for your tenant. Filter, then click into a
            row to review the raw payload and approve / reject.
          </p>
        </div>
      </div>

      <div className="card p-4 flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-2">
          Scope
          <select
            className="input"
            value={scope}
            onChange={(e) => setScope(e.target.value)}
          >
            <option value="">all</option>
            <option value="1">Scope 1</option>
            <option value="2">Scope 2</option>
            <option value="3">Scope 3</option>
          </select>
        </label>
        <label className="flex items-center gap-2">
          Status
          <select
            className="input"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="">all</option>
            <option value="pending">pending</option>
            <option value="approved">approved</option>
            <option value="rejected">rejected</option>
            <option value="flagged">flagged</option>
            <option value="locked">locked</option>
          </select>
        </label>
        <label className="flex items-center gap-2">
          Source
          <select
            className="input"
            value={source}
            onChange={(e) => setSource(e.target.value)}
          >
            <option value="">all</option>
            <option value="sap">SAP</option>
            <option value="utility_csv">Utility CSV</option>
            <option value="utility_pdf">Utility PDF</option>
            <option value="travel">Travel</option>
          </select>
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={flagged}
            onChange={(e) => setFlagged(e.target.checked)}
          />
          Only flagged
        </label>
        <button
          className="btn-secondary"
          onClick={() => {
            setScope("");
            setStatus("");
            setSource("");
            setFlagged(false);
          }}
        >
          Reset
        </button>
      </div>

      {isLoading && <div className="text-slate-500 text-sm">Loading…</div>}
      {error && <div className="text-sm text-red-600">{String(error)}</div>}

      {data && (
        <div className="card overflow-hidden">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wide">
              <tr>
                <th className="text-left p-3">Scope</th>
                <th className="text-left p-3">Activity</th>
                <th className="text-left p-3">Period</th>
                <th className="text-right p-3">Qty</th>
                <th className="text-left p-3">Unit</th>
                <th className="text-right p-3">kg CO₂e</th>
                <th className="text-left p-3">Source</th>
                <th className="text-left p-3">Status</th>
                <th className="text-left p-3">Flags</th>
              </tr>
            </thead>
            <tbody>
              {data.results.length === 0 && (
                <tr>
                  <td colSpan={9} className="p-6 text-center text-slate-400">
                    No records match these filters.
                  </td>
                </tr>
              )}
              {data.results.map((r: ActivityRecord) => (
                <tr
                  key={r.id}
                  className="border-t border-slate-100 hover:bg-slate-50"
                >
                  <td className="p-3">
                    <span className="badge bg-slate-100 text-slate-700">
                      {SCOPE_LABEL[r.scope]}
                    </span>
                  </td>
                  <td className="p-3">
                    <Link
                      to={`/records/${r.id}`}
                      className="text-brand hover:underline font-medium"
                    >
                      {r.activity_type}
                    </Link>
                    <div className="text-xs text-slate-500 truncate max-w-xs">
                      {r.description}
                    </div>
                  </td>
                  <td className="p-3 text-slate-600 whitespace-nowrap">
                    {r.period_start}
                    {r.period_start !== r.period_end && (
                      <> → {r.period_end}</>
                    )}
                  </td>
                  <td className="p-3 text-right font-mono">
                    {Number(r.quantity_normalized).toLocaleString()}
                  </td>
                  <td className="p-3 text-slate-600">{r.unit_normalized}</td>
                  <td className="p-3 text-right font-mono">
                    {r.co2e_kg ? Number(r.co2e_kg).toLocaleString() : "—"}
                  </td>
                  <td className="p-3 text-slate-600">{r.source_system}</td>
                  <td className="p-3">
                    <span
                      className={`badge ${
                        STATUS_TONE[r.status] || "bg-slate-100 text-slate-700"
                      }`}
                    >
                      {r.status}
                    </span>
                  </td>
                  <td className="p-3">
                    <div className="flex flex-wrap gap-1">
                      {r.flags?.map((f) => (
                        <span
                          key={f}
                          className="badge bg-red-50 text-red-700 border border-red-100"
                        >
                          {f}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="bg-slate-50 px-3 py-2 text-xs text-slate-500 border-t">
            {data.count} record{data.count === 1 ? "" : "s"} total
          </div>
        </div>
      )}
    </div>
  );
}
