import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { get } from "../api";

interface SourceRow {
  ref: string;
  dataset: string;
  file: string;
  row: number;
  file_sha256: string;
  provenance: Record<string, string | number | null>;
  row_values: Record<string, unknown>;
  pdf_available: boolean;
  pdf_url: string | null;
}

const SourceCtx = createContext<(ref: string) => void>(() => undefined);

export function SourceProvider({ children }: { children: ReactNode }) {
  const [ref, setRef] = useState<string | null>(null);
  return (
    <SourceCtx.Provider value={setRef}>
      {children}
      {ref && <SourceDrawer reference={ref} onClose={() => setRef(null)} />}
    </SourceCtx.Provider>
  );
}

/** A number that opens its source row (dataset, file, provenance, PDF page when the PDF is in the repository). */
export function Num({ value, source, title }: { value: string; source?: string | null; title?: string }) {
  const open = useContext(SourceCtx);
  if (!source) return <span>{value}</span>;
  return (
    <button className="num" onClick={(e) => {
        e.stopPropagation();
        open(source);
      }} title={title ?? `Open source: ${source}`} aria-label={`${value}, open source ${source}`}>
      {value}
    </button>
  );
}

function SourceDrawer({ reference, onClose }: { reference: string; onClose: () => void }) {
  const [row, setRow] = useState<SourceRow | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setRow(null);
    setError(null);
    get<SourceRow>(`/sources/${encodeURIComponent(reference)}`).then(setRow).catch((e: Error) => setError(e.message));
  }, [reference]);
  const page = row ? String(row.provenance.source_page ?? "").match(/\d+/)?.[0] : undefined;
  return (
    <aside className="drawer" role="dialog" aria-label="Source" data-testid="source-drawer">
      <div className="controls">
        <strong>Source</strong>
        <span className="spacer" />
        <button className="btn" onClick={onClose}>
          Close
        </button>
      </div>
      {error && <p className="err">{error}</p>}
      {!row && !error && <p className="muted">Loading...</p>}
      {row && (
        <>
          <p>
            <code>{row.ref}</code> is row {row.row} of <code>{row.file}</code> (SHA-256 <code>{row.file_sha256.slice(0, 12)}...</code>).
          </p>
          <h3>Provenance</h3>
          <table>
            <tbody>
              {Object.entries(row.provenance).map(([k, v]) => (
                <tr key={k}>
                  <th>{k}</th>
                  <td>{k === "source_url" && v ? <a href={String(v)} target="_blank" rel="noreferrer">{String(v)}</a> : String(v ?? "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {row.pdf_available && row.pdf_url ? (
            <p>
              <a href={`${row.pdf_url}${page ? `#page=${page}` : ""}`} target="_blank" rel="noreferrer">
                Open the source PDF{page ? ` at page ${page}` : ""}
              </a>
            </p>
          ) : (
            <p className="muted">The source PDF is not stored in the repository; the provenance above says which document and page to open.</p>
          )}
          <h3>Row</h3>
          <div className="tablewrap">
            <table>
              <tbody>
                {Object.entries(row.row_values).map(([k, v]) => (
                  <tr key={k}>
                    <th>{k}</th>
                    <td>{v === null ? "" : String(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </aside>
  );
}

export function Takeaway({ text }: { text: string | null | undefined }) {
  return text ? <p className="takeaway" data-testid="takeaway">{text}</p> : null;
}

export function Note({ text }: { text: string | null | undefined }) {
  return text ? <p className="note" role="note">{text}</p> : null;
}

export function useFetch<T>(path: string | null): { data: T | null; error: string | null; loading: boolean } {
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: path !== null });
  useEffect(() => {
    if (path === null) {
      setState({ data: null, error: null, loading: false });
      return;
    }
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    get<T>(path)
      .then((data) => alive && setState({ data, error: null, loading: false }))
      .catch((e: Error) => alive && setState({ data: null, error: e.message, loading: false }));
    return () => {
      alive = false;
    };
  }, [path]);
  return state;
}

export function Status<T>({ state, children }: { state: { data: T | null; error: string | null; loading: boolean }; children: (data: T) => ReactNode }) {
  if (state.loading) return <p className="muted">Loading...</p>;
  if (state.error) return <p className="note" role="alert">{state.error}</p>;
  return state.data ? <>{children(state.data)}</> : null;
}

/** Diverging colour for an excess return: blue above 0, orange below, neutral at 0 (alpha keeps the text readable). */
export function tileColour(v: number, scale = 0.4): string {
  const a = Math.min(Math.abs(v) / scale, 1) * 0.5;
  return v >= 0 ? `color-mix(in srgb, var(--pos) ${a * 100}%, var(--surface))` : `color-mix(in srgb, var(--neg) ${a * 100}%, var(--surface))`;
}

export function Whisker({ p10, p90, mark, min = -0.8, max = 1.2 }: { p10: number; p90: number; mark: number; min?: number; max?: number }) {
  const pos = (v: number) => `${Math.max(0, Math.min(100, ((v - min) / (max - min)) * 100))}%`;
  return (
    <div className="whisker" role="img" aria-label={`80% interval ${(p10 * 100).toFixed(0)}% to ${(p90 * 100).toFixed(0)}%, expected ${(mark * 100).toFixed(0)}%`}>
      <span className="zero" style={{ left: pos(0) }} />
      <span className="range" style={{ left: pos(p10), width: `calc(${pos(p90)} - ${pos(p10)})` }} />
      <span className="mark" style={{ left: pos(mark) }} />
    </div>
  );
}
