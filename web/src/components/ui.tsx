import { useId, useState, type ReactNode } from "react";

/** A card with an optional title row. */
export function Card({ title, caption, right, className = "", children, style }: { title?: ReactNode; caption?: ReactNode; right?: ReactNode; className?: string; children: ReactNode; style?: React.CSSProperties }) {
  return (
    <section className={`card ${className}`} style={style}>
      {(title || right) && (
        <div className="head">
          <div>
            {title && <h3>{title}</h3>}
            {caption && <div className="cap">{caption}</div>}
          </div>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Icon({ name }: { name: "sun" | "moon" | "spark" | "bubble" | "search" }) {
  const d = {
    sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19",
    moon: "M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10z",
    spark: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z",
    bubble: "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z",
    search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-3.5-3.5",
  }[name];
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

export interface ColItem {
  label: string;
  value: number;
  display: string;
  tip?: ReactNode;
}

/**
 * Hatched royal-blue columns on a quiet panel: grey headers with the value, one highlighted column with a pale blue wash and a floating pill,
 * and light stepped ramps joining each bar's top to the next. Negative values hang below a zero line (pink).
 */
export function ColumnChart({ items, height = 230, initial = 0, yFmt, ariaLabel }: { items: ColItem[]; height?: number; initial?: number; yFmt?: (v: number) => string; ariaLabel: string }) {
  const [sel, setSel] = useState(Math.min(initial, Math.max(items.length - 1, 0)));
  if (items.length === 0) return null;
  const vals = items.map((i) => i.value);
  const vmax = Math.max(0, ...vals) * 1.14 || 1e-9;
  const vmin = Math.min(0, ...vals) * 1.14;
  const range = vmax - vmin || 1;
  const yOf = (v: number) => ((vmax - v) / range) * height;
  const zero = yOf(0);
  const raw = range / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = ([1, 2, 2.5, 5, 10].find((m) => m * mag >= raw) ?? 10) * mag;
  const ticks: number[] = [];
  for (let t = Math.ceil(vmin / step) * step; t <= vmax + 1e-9; t += step) ticks.push(Math.abs(t) < step / 1e6 ? 0 : t);
  return (
    <div className={`cols ${items.length > 8 ? "dense" : ""}`} role="img" aria-label={ariaLabel} data-testid="columns">
      <div className="yaxis" style={{ height }}>
        {ticks.map((t, k) => (
          <span key={k} style={{ top: yOf(t) }}>{yFmt ? yFmt(t) : Math.round(t).toString()}</span>
        ))}
      </div>
      {items.map((it, i) => {
        const next = items[i + 1];
        const top = it.value >= 0 ? yOf(it.value) : zero;
        const h = Math.max(3, Math.abs(yOf(it.value) - zero));
        return (
          <div key={it.label + i} className={`col ${i === sel ? "sel" : ""}`} tabIndex={0} onMouseEnter={() => setSel(i)} onFocus={() => setSel(i)} onClick={() => setSel(i)}>
            <div className="hd">
              <div className="l" title={it.label}>{it.label}</div>
              <div className="v">{it.display}</div>
            </div>
            <div className="body" style={{ height }}>
              {vmin < 0 && <span className="zeroline" style={{ top: zero }} />}
              <div className={`bar ${it.value < 0 ? "neg" : ""}`} style={{ top, height: h }}>
                <i />
              </div>
              {next && (
                <div className={`ramp ${it.value < 0 && next.value < 0 ? "neg" : ""}`} style={{ top: 0, height, clipPath: `polygon(0 ${yOf(it.value)}px, 100% ${yOf(next.value)}px, 100% ${zero}px, 0 ${zero}px)` }} />
              )}
              {i === sel && it.tip && <div className="coltip" style={{ ...(i < items.length / 2 ? { left: 10 } : { right: 6 }), top: Math.max(6, (it.value >= 0 ? top : top + h) - 40) }}>{it.tip}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export type HTone = "green" | "blue" | "pink" | "orange";
export interface HRowItem {
  label: ReactNode;
  value: number;
  display: ReactNode;
  tone?: HTone;
}
/** Hatched horizontal progress bars. With `signed`, bars grow from a centre line (left for negatives). */
export function HBars({ rows, signed = false, max }: { rows: HRowItem[]; signed?: boolean; max?: number }) {
  const m = max ?? Math.max(...rows.map((r) => Math.abs(r.value)), 1e-9);
  return (
    <div>
      {rows.map((r, i) => {
        const w = (Math.abs(r.value) / m) * (signed ? 50 : 100);
        const tone = r.tone ?? (signed ? (r.value >= 0 ? "blue" : "pink") : (["green", "blue", "pink", "orange"] as HTone[])[i % 4]);
        return (
          <div className="hrow" key={i}>
            <div className="t">
              <span>{r.label}</span>
              <b>{r.display}</b>
            </div>
            <div className="htrack">
              {signed && <span className="hdiv" />}
              <div className={`hfill h-${tone}`} style={signed ? { position: "absolute", top: 0, bottom: 0, [r.value >= 0 ? "left" : "right"]: "50%", width: `${w}%` } : { width: `${Math.max(w, 2)}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Columns of dots (bottom-up), the hovered column darker with a pill above it. */
export function DotMatrix({ cols, rows = 10, tone = "green", initial = 0 }: { cols: { filled: number; tip: string }[]; rows?: number; tone?: "green" | "blue"; initial?: number }) {
  const [sel, setSel] = useState(Math.min(initial, Math.max(cols.length - 1, 0)));
  return (
    <div className={`dots ${tone}`} role="img" aria-label="dot matrix" data-testid="dotmatrix">
      {cols.map((c, i) => (
        <div key={i} className={`dotcol ${i === sel ? "sel" : ""}`} onMouseEnter={() => setSel(i)} onClick={() => setSel(i)}>
          {Array.from({ length: rows }, (_, r) => (
            <i key={r} className={r < c.filled ? "on" : ""} />
          ))}
          {i === sel && <span className="dotpill" style={{ left: "50%", top: -30 }}>{c.tip}</span>}
        </div>
      ))}
    </div>
  );
}

/** Step line with a vertical-hatch wash under the first series and a marker with a pill. */
export function StepLine({ series, labels, height = 190, fmt, colour = "#ee4d86" }: { series: { name: string; values: (number | null)[]; colour?: string }[]; labels: string[]; height?: number; fmt: (v: number) => string; colour?: string }) {
  const id = useId().replace(/:/g, "");
  const [sel, setSel] = useState(labels.length - 1);
  const W = 420;
  const pad = { l: 8, r: 8, t: 34, b: 24 };
  const all = series.flatMap((s) => s.values).filter((v): v is number => v !== null);
  if (all.length === 0) return null;
  const lo = Math.min(...all, 0);
  const hi = Math.max(...all, 0) || 1;
  const x = (i: number) => pad.l + (i / Math.max(labels.length - 1, 1)) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + ((hi - v) / (hi - lo || 1)) * (height - pad.t - pad.b);
  const path = (vals: (number | null)[]) => {
    let d = "";
    let prev: number | null = null;
    vals.forEach((v, i) => {
      if (v === null) return;
      d += prev === null ? `M${x(i)},${y(v)}` : ` L${x(i)},${y(prev)} L${x(i)},${y(v)}`;
      prev = v;
    });
    return d;
  };
  const main = series[0];
  const mp = path(main.values);
  const firstIdx = main.values.findIndex((v) => v !== null);
  let lastIdx = main.values.length - 1;
  while (lastIdx > 0 && main.values[lastIdx] === null) lastIdx--;
  const sv = main.values[sel];
  return (
    <svg className="stepsvg" viewBox={`0 0 ${W} ${height}`} role="img" aria-label={`${main.name} by period`} data-testid="stepline">
      <defs>
        <pattern id={`h${id}`} width="6" height="6" patternUnits="userSpaceOnUse">
          <path d="M1 0V6" stroke={main.colour ?? colour} strokeOpacity="0.32" strokeWidth="1.6" />
        </pattern>
        <linearGradient id={`f${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity="1" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
        <mask id={`m${id}`}>
          <rect width={W} height={height} fill={`url(#f${id})`} />
        </mask>
      </defs>
      {lo < 0 && <line x1={pad.l} x2={W - pad.r} y1={y(0)} y2={y(0)} stroke="var(--ink-3)" strokeOpacity="0.35" />}
      <path d={`${mp} L${x(lastIdx)},${height - pad.b} L${x(firstIdx)},${height - pad.b} Z`} fill={`url(#h${id})`} mask={`url(#m${id})`} />
      {series.slice(1).map((s) => (
        <path key={s.name} d={path(s.values)} fill="none" stroke={s.colour ?? "#2a55e8"} strokeWidth="2" strokeLinejoin="round" strokeDasharray="5 4" />
      ))}
      <path d={mp} fill="none" stroke={main.colour ?? colour} strokeWidth="2.6" strokeLinejoin="round" />
      {sv !== null && sv !== undefined && (
        <g>
          <circle cx={x(sel)} cy={y(sv)} r="4" fill={main.colour ?? colour} />
          <circle cx={x(sel)} cy={y(sv)} r="8" fill="none" stroke={main.colour ?? colour} strokeOpacity="0.3" />
          <rect x={Math.min(Math.max(x(sel) - 34, 0), W - 68)} y={y(sv) - 32} width="68" height="22" rx="8" fill="var(--pill)" />
          <text x={Math.min(Math.max(x(sel), 34), W - 34)} y={y(sv) - 17} textAnchor="middle" style={{ fill: "var(--pill-ink)", fontSize: 11, fontWeight: 500 }}>{fmt(sv)}</text>
        </g>
      )}
      {labels.map((l, i) => (
        <g key={i}>
          <rect x={x(i) - (W / labels.length) / 2} y={0} width={W / labels.length} height={height} fill="transparent" onMouseEnter={() => setSel(i)} onClick={() => setSel(i)} />
          {(labels.length <= 9 || i % Math.ceil(labels.length / 7) === 0) && <text x={x(i)} y={height - 6} textAnchor="middle">{l}</text>}
        </g>
      ))}
    </svg>
  );
}

/** Gradient insight card with grain. */
export function Insight({ tone = "sunset", tag, big, title, text, className = "", style }: { tone?: "sunset" | "ocean" | "dusk"; tag: string; big: ReactNode; title: ReactNode; text?: ReactNode; className?: string; style?: React.CSSProperties }) {
  return (
    <section className={`insight ${tone} ${className}`} style={style}>
      <span className="tagline"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /></svg>{tag}</span>
      <div className="big">{big}</div>
      <b>{title}</b>
      {text && <p>{text}</p>}
      <div className="segs"><i /><i /><i /></div>
    </section>
  );
}

/** The floating "what would you like to explore next?" prompt that hands a question to the Copilot. */
export function AskBar({ tag, fallback, onAsk }: { tag: string; fallback: string; onAsk: (q: string) => void }) {
  const [text, setText] = useState("");
  return (
    <div className="askbar">
      <div className="q"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /></svg>What would you like to explore next?</div>
      <form onSubmit={(e) => { e.preventDefault(); onAsk(text.trim() || fallback); }}>
        <span style={{ fontSize: 13, whiteSpace: "nowrap" }}>Ask the Copilot about</span>
        <span className="tag">/{tag}</span>
        <input aria-label="Question for the Copilot" value={text} onChange={(e) => setText(e.target.value)} placeholder={fallback} />
        <button type="submit">Ask</button>
      </form>
    </div>
  );
}

const AV = ["", "o", "g", "p"];
export function Avatar({ name, i = 0 }: { name: string; i?: number }) {
  return <span className={`avatar ${AV[i % 4]}`}>{name.slice(0, 2).toUpperCase()}</span>;
}

const ACR: Record<string, string> = { fmcg: "FMCG", it_control: "IT services (control)", psu_banks: "PSU banks", psu: "PSU" };
/** Readable sector name from an id such as "psu_banks". */
export function sectorLabel(id: string): string {
  return ACR[id] ?? id.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}
