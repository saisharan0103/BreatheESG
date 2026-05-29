import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  approveRecord,
  editRecord,
  getRecord,
  rejectRecord,
} from "../api";

export function RecordDetail() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["record", id],
    queryFn: () => getRecord(id!),
    enabled: !!id,
  });
  const [editing, setEditing] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (isLoading) return <div className="text-slate-500 text-sm">Loading…</div>;
  if (error)
    return (
      <div className="text-sm text-red-600">Failed: {String(error)}</div>
    );
  if (!data) return null;

  const refetchAll = () => {
    qc.invalidateQueries({ queryKey: ["record", id] });
    qc.invalidateQueries({ queryKey: ["records"] });
    qc.invalidateQueries({ queryKey: ["summary"] });
  };

  const onApprove = async () => {
    try {
      await approveRecord(id!);
      refetchAll();
    } catch (e: any) {
      setErr(e.message);
    }
  };
  const onReject = async () => {
    const note = prompt("Reject reason?") || "";
    try {
      await rejectRecord(id!, note);
      refetchAll();
    } catch (e: any) {
      setErr(e.message);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <Link
            to="/records"
            className="text-sm text-slate-500 hover:underline"
          >
            ← back to records
          </Link>
          <h1 className="text-2xl font-semibold mt-1">
            {data.activity_type}
            <span
              className={`ml-3 badge ${
                data.status === "approved"
                  ? "bg-emerald-100 text-emerald-800"
                  : data.status === "rejected"
                  ? "bg-slate-200"
                  : data.status === "locked"
                  ? "bg-slate-800 text-white"
                  : data.status === "flagged"
                  ? "bg-red-100 text-red-800"
                  : "bg-amber-100 text-amber-800"
              }`}
            >
              {data.status}
            </span>
          </h1>
          {data.description && (
            <div className="text-sm text-slate-500 mt-1">{data.description}</div>
          )}
        </div>
        <div className="flex gap-2">
          {data.status !== "locked" && (
            <>
              <button className="btn-secondary" onClick={() => setEditing((s) => !s)}>
                {editing ? "Close edit" : "Edit"}
              </button>
              <button className="btn-primary" onClick={onApprove} disabled={data.status === "approved"}>
                Approve
              </button>
              <button className="btn-danger" onClick={onReject} disabled={data.status === "rejected"}>
                Reject
              </button>
            </>
          )}
        </div>
      </div>

      {err && <div className="text-sm text-red-600">{err}</div>}

      {data.flags?.length > 0 && (
        <div className="card p-4 border-red-100 bg-red-50">
          <div className="text-sm font-medium text-red-800 mb-1">Flags</div>
          <div className="flex flex-wrap gap-1">
            {data.flags.map((f: string) => (
              <span key={f} className="badge bg-white border border-red-200 text-red-700">
                {f}
              </span>
            ))}
          </div>
        </div>
      )}

      {editing && <EditPanel id={id!} record={data} onSaved={refetchAll} />}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="card p-5">
          <div className="text-sm font-medium text-slate-700 mb-3">Normalized</div>
          <Field label="Scope" v={`Scope ${data.scope}`} />
          <Field label="Activity type" v={data.activity_type} />
          <Field label="Quantity" v={`${Number(data.quantity_normalized).toLocaleString()} ${data.unit_normalized}`} />
          <Field label="Period" v={`${data.period_start} → ${data.period_end}`} />
          <Field
            label="CO₂e"
            v={
              data.co2e_kg
                ? `${Number(data.co2e_kg).toLocaleString()} kg`
                : "—"
            }
          />
          {data.cost_amount && (
            <Field
              label="Cost"
              v={`${Number(data.cost_amount).toLocaleString()} ${data.cost_currency}`}
            />
          )}
          {data.is_edited && (
            <div className="mt-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
              This record has been edited since ingestion. Original values are
              still in the raw payload.
            </div>
          )}
        </div>

        <div className="card p-5">
          <div className="text-sm font-medium text-slate-700 mb-3">As ingested</div>
          <Field label="Source" v={data.source_system} />
          <Field label="Source record ID" v={data.source_record_id || "—"} />
          <Field
            label="Raw quantity"
            v={`${Number(data.quantity_raw).toLocaleString()} ${data.unit_raw || ""}`}
          />
          {data.batch_info && (
            <>
              <Field label="Batch" v={data.batch_info.id} mono />
              <Field
                label="File"
                v={`${data.batch_info.original_filename || "—"} (${data.batch_info.file_size_bytes ?? 0} bytes)`}
              />
              <Field
                label="SHA-256"
                v={data.batch_info.file_sha256 || "—"}
                mono
              />
            </>
          )}
          {data.emission_factor && (
            <Field
              label="Factor"
              v={`${data.emission_factor.kg_co2e_per_unit} kg CO₂e / ${data.emission_factor.unit} (${data.emission_factor.region} ${data.emission_factor.year}, ${data.emission_factor.source.toUpperCase()})`}
            />
          )}
        </div>
      </div>

      <div className="card p-5">
        <div className="text-sm font-medium text-slate-700 mb-2">Raw payload</div>
        <pre className="text-xs overflow-auto bg-slate-50 p-3 rounded border border-slate-200 max-h-80">
          {JSON.stringify(data.raw_payload, null, 2)}
        </pre>
      </div>

      <div className="card p-5">
        <div className="text-sm font-medium text-slate-700 mb-2">Edit history</div>
        {data.revisions?.length === 0 && (
          <div className="text-sm text-slate-400">No edits.</div>
        )}
        <div className="space-y-2">
          {data.revisions?.map((rev: any) => (
            <div key={rev.id} className="text-sm border-b border-slate-100 pb-2">
              <div>
                <span className="font-mono text-xs">{rev.field_name}</span>{" "}
                <span className="text-slate-500">changed</span>{" "}
                <span className="font-mono bg-red-50 px-1">{rev.old_value}</span>{" "}
                →{" "}
                <span className="font-mono bg-emerald-50 px-1">{rev.new_value}</span>
              </div>
              <div className="text-xs text-slate-500">
                {rev.edited_by_username || "?"} · {new Date(rev.edited_at).toLocaleString()}
                {rev.reason && ` · ${rev.reason}`}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="card p-5">
        <div className="text-sm font-medium text-slate-700 mb-2">Review trail</div>
        {data.review_actions?.length === 0 && (
          <div className="text-sm text-slate-400">No actions yet.</div>
        )}
        <div className="space-y-2">
          {data.review_actions?.map((a: any) => (
            <div key={a.id} className="text-sm">
              <span className="font-medium">{a.action}</span>{" "}
              <span className="text-slate-500">by {a.actor_username || "?"}</span>{" "}
              <span className="text-slate-400 text-xs">
                · {new Date(a.at).toLocaleString()}
              </span>
              {a.note && <span className="ml-2 text-slate-600">— {a.note}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Field({ label, v, mono }: { label: string; v: string; mono?: boolean }) {
  return (
    <div className="flex justify-between items-baseline py-1.5 text-sm border-b border-slate-50 last:border-0">
      <div className="text-slate-500">{label}</div>
      <div className={mono ? "font-mono text-xs" : ""}>{v}</div>
    </div>
  );
}

function EditPanel({
  id,
  record,
  onSaved,
}: {
  id: string;
  record: any;
  onSaved: () => void;
}) {
  const [qty, setQty] = useState(record.quantity_normalized);
  const [unit, setUnit] = useState(record.unit_normalized);
  const [activity, setActivity] = useState(record.activity_type);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await editRecord(id, {
        quantity_normalized: qty,
        unit_normalized: unit,
        activity_type: activity,
        reason,
      });
      onSaved();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card p-5 border-brand">
      <div className="text-sm font-medium text-slate-700 mb-3">Edit</div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
        <label className="block">
          <div className="text-slate-500 mb-1">Quantity</div>
          <input
            className="input w-full"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
          />
        </label>
        <label className="block">
          <div className="text-slate-500 mb-1">Unit</div>
          <input
            className="input w-full"
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
          />
        </label>
        <label className="block">
          <div className="text-slate-500 mb-1">Activity type</div>
          <input
            className="input w-full"
            value={activity}
            onChange={(e) => setActivity(e.target.value)}
          />
        </label>
      </div>
      <label className="block mt-3 text-sm">
        <div className="text-slate-500 mb-1">Reason (kept in audit log)</div>
        <input
          className="input w-full"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. supplier rebill; unit was L not GAL"
        />
      </label>
      {err && <div className="text-sm text-red-600 mt-2">{err}</div>}
      <div className="mt-3 flex justify-end gap-2">
        <button className="btn-primary" disabled={busy} onClick={save}>
          {busy ? "Saving…" : "Save change"}
        </button>
      </div>
    </div>
  );
}
