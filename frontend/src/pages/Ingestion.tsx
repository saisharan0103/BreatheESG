import { useState } from "react";
import { ingest } from "../api";

type Source = "sap" | "utility-csv" | "utility-pdf" | "travel";

const SOURCES: {
  source: Source;
  title: string;
  blurb: string;
  accept: string;
  realShape: string;
}[] = [
  {
    source: "sap",
    title: "SAP — fuel & procurement",
    blurb:
      "Flat-file export from SE16/SE16N or ALV download of the EKKO+EKPO+MSEG join. Both English (MATNR/WERKS/MENGE/BUDAT) and German (Material/Werk/Menge/Buchungsdatum) headers are supported, with `;`/`,` delimiter and `1.234,56` numbers auto-detected.",
    accept: ".csv,.txt",
    realShape: "CSV — comma or semicolon delimited",
  },
  {
    source: "utility-csv",
    title: "Utility portal — electricity CSV",
    blurb:
      "Per-billing-period rows from a supplier portal (EDF Energy Hub, British Gas Business, ConEd). MPAN, period start/end, kWh and tariff are recognised; day/night split is summed; estimated reads are flagged.",
    accept: ".csv,.txt",
    realShape: "CSV",
  },
  {
    source: "utility-pdf",
    title: "Utility bill — PDF",
    blurb:
      "Embedded-text PDF bills (not scans). We extract MPAN, billing period, total kWh. If extraction is partial the row lands in `flagged` with the raw text attached so an analyst can fix it.",
    accept: ".pdf",
    realShape: "PDF with text layer",
  },
  {
    source: "travel",
    title: "Corporate travel — Concur-style export",
    blurb:
      "Per-segment CSV or JSON from a Concur/Navan admin export. Flights without distance are reconstructed from IATA pairs; cabin class is normalised; haul category uses origin/destination country to distinguish domestic from short-haul cross-border.",
    accept: ".csv,.json",
    realShape: "CSV / JSON, one row per segment",
  },
];

export function Ingestion() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Ingest data</h1>
        <p className="text-sm text-slate-500">
          Upload a real-shape export from one of the three sources. Rows are
          normalized, factored, and queued for analyst review.
        </p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {SOURCES.map((s) => (
          <UploaderCard key={s.source} {...s} />
        ))}
      </div>
    </div>
  );
}

function UploaderCard(props: {
  source: Source;
  title: string;
  blurb: string;
  accept: string;
  realShape: string;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      const data = await ingest(props.source, file);
      setResult(data);
    } catch (e: any) {
      setErr(e.message || "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card p-5">
      <div className="font-medium text-slate-900">{props.title}</div>
      <div className="text-xs text-slate-500 mt-0.5">{props.realShape}</div>
      <p className="text-sm text-slate-600 mt-2">{props.blurb}</p>
      <form onSubmit={onSubmit} className="mt-4 flex items-center gap-2">
        <input
          type="file"
          accept={props.accept}
          onChange={(e) => setFile(e.target.files?.[0] || null)}
          className="text-sm flex-1"
        />
        <button className="btn-primary" disabled={!file || busy}>
          {busy ? "Uploading…" : "Upload"}
        </button>
      </form>
      {err && (
        <div className="mt-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded p-2">
          {err}
        </div>
      )}
      {result && (
        <div className="mt-3 text-sm bg-slate-50 border border-slate-200 rounded p-3 space-y-1">
          <div>
            <span className="font-medium">Status:</span>{" "}
            <span
              className={
                result.status === "parsed"
                  ? "text-emerald-700"
                  : result.status === "partial"
                  ? "text-amber-700"
                  : "text-red-700"
              }
            >
              {result.status}
            </span>
          </div>
          <div>
            <span className="font-medium">Rows ingested:</span>{" "}
            {result.rows_ingested} · errored: {result.rows_errored}
          </div>
          {result.parser_notes && (
            <details className="text-xs text-slate-600">
              <summary className="cursor-pointer">Parser notes</summary>
              <pre className="overflow-auto whitespace-pre-wrap">
                {JSON.stringify(result.parser_notes, null, 2)}
              </pre>
            </details>
          )}
          {result.error_summary && (
            <details className="text-xs text-red-700">
              <summary className="cursor-pointer">Errors</summary>
              <pre className="overflow-auto whitespace-pre-wrap">
                {result.error_summary}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
