import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Note, Num, Status, Takeaway, useFetch } from "../components/Common";

interface Summary {
  level: string;
  strategy: string;
  cagr: number;
  sharpe: number;
  max_drawdown: number;
  turnover: number | null;
  final_value_of_100: number;
  source_ref: string;
}
interface Resp {
  summary: Summary[];
  equity: Record<string, { columns: string[]; rows: Record<string, number | string>[] }>;
  ic_by_year: { model: string; budget_id: string; ic: number | null; source_ref: string }[];
  ic_bootstrap: { level: string; model: string; mean_ic: number; ci_lo: number; ci_hi: number; p_two_sided: number }[];
  ablation: { model: string; variant: string; mean_ic: number; ic_drop_vs_full: number }[];
  evidence_answer: string;
  takeaway: string;
  holdout: { status: string; note: string };
  ledger: { entries: unknown[]; note: string };
}

const LINES: Record<string, string[]> = {
  sector: ["NIFTY500", "equal_weight", "ridge", "tier1_blend", "lgbm_ranker"],
  stock: ["NIFTY500", "equal_weight", "momentum_12m", "ridge", "tier2_ranker"],
};
const COLOURS = ["var(--neutral)", "var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];

export default function Backtest() {
  const state = useFetch<Resp>("/backtest");
  const [level, setLevel] = useState<"sector" | "stock">("sector");
  const [model, setModel] = useState("ridge");
  return (
    <>
      <h1>7. Backtest and evidence: would this have worked?</h1>
      <Status state={state}>
        {(d) => {
          const lines = LINES[level].filter((c) => d.equity[level].columns.includes(c));
          const ablation = d.ablation.filter((a) => a.model === model && (a.variant.startsWith("no_") || ["price_only", "budget_only", "price_plus_budget", "momentum_only", "full"].includes(a.variant)));
          const years = Array.from(new Set(d.ic_by_year.map((r) => r.budget_id))).sort();
          const icModels = ["ridge", "lgbm_ranker", "bayes_hier", "tier1_blend", "last_years_winners"];
          return (
            <>
              <Takeaway text={d.takeaway} />
              <Note text={`Does the budget data add anything beyond price momentum? ${d.evidence_answer}. See the evidence report for the full answer.`} />
              <div className="controls">
                <button className="btn" onClick={() => setLevel("sector")} aria-pressed={level === "sector"}>Top-3 sectors</button>
                <button className="btn" onClick={() => setLevel("stock")} aria-pressed={level === "stock"}>Top-15 stocks</button>
                <span className="muted">Net of 0.2% round-trip costs, rebuilt from out-of-sample predictions; stock results carry survivorship bias.</span>
              </div>
              <div className="legend">
                {lines.map((c, i) => (
                  <span key={c}><i style={{ background: COLOURS[i], opacity: c === "NIFTY500" ? 0.8 : 1 }} />{c}</span>
                ))}
              </div>
              <div className="chartbox" data-testid="equity-chart" style={{ height: 360 }}>
                <ResponsiveContainer>
                  <LineChart data={d.equity[level].rows}>
                    <CartesianGrid stroke="var(--border)" />
                    <XAxis dataKey="date" stroke="var(--text-2)" tickFormatter={(v) => String(v).slice(0, 4)} minTickGap={40} />
                    <YAxis scale="log" domain={["auto", "auto"]} stroke="var(--text-2)" />
                    <Tooltip />
                    {lines.map((c, i) => (
                      <Line key={c} dataKey={c} stroke={COLOURS[i]} dot={false} strokeWidth={c === "NIFTY500" ? 1.5 : 2} strokeDasharray={c === "NIFTY500" ? "5 4" : undefined} isAnimationActive={false} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="tablewrap">
                <table>
                  <thead>
                    <tr><th>Strategy</th><th className="n">CAGR</th><th className="n">Sharpe</th><th className="n">Max drawdown</th><th className="n">Turnover</th><th className="n">Value of 100</th></tr>
                  </thead>
                  <tbody>
                    {d.summary.filter((s) => s.level === level).map((s) => (
                      <tr key={s.strategy}>
                        <td>{s.strategy}</td>
                        <td className="n"><Num value={`${(s.cagr * 100).toFixed(1)}%`} source={s.source_ref} /></td>
                        <td className="n">{s.sharpe.toFixed(2)}</td>
                        <td className="n">{(s.max_drawdown * 100).toFixed(1)}%</td>
                        <td className="n">{s.turnover === null ? "n/a" : `${(s.turnover * 100).toFixed(0)}%`}</td>
                        <td className="n">{Math.round(s.final_value_of_100).toLocaleString("en-IN")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <h2>Information coefficient by test year (rank correlation of forecast and outcome)</h2>
              <div className="tablewrap">
                <table data-testid="ic-table">
                  <thead>
                    <tr><th>Budget</th>{icModels.map((m) => <th key={m} className="n">{m}</th>)}</tr>
                  </thead>
                  <tbody>
                    {years.map((y) => (
                      <tr key={y}>
                        <td>{y}</td>
                        {icModels.map((m) => {
                          const r = d.ic_by_year.find((x) => x.model === m && x.budget_id === y);
                          return <td key={m} className="n">{r && r.ic !== null ? <Num value={r.ic.toFixed(2)} source={r.source_ref} /> : "-"}</td>;
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <h2>Ablation: mean IC without each feature family</h2>
              <div className="controls">
                <label>Model <select value={model} onChange={(e) => setModel(e.target.value)} aria-label="Ablation model"><option>ridge</option><option>lgbm_ranker</option></select></label>
              </div>
              <div className="chartbox" data-testid="ablation-chart">
                <ResponsiveContainer>
                  <BarChart data={ablation} layout="vertical" margin={{ left: 60 }}>
                    <CartesianGrid stroke="var(--border)" />
                    <XAxis type="number" stroke="var(--text-2)" />
                    <YAxis type="category" dataKey="variant" width={150} stroke="var(--text-2)" tick={{ fontSize: 11 }} interval={0} />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="mean_ic" name="Mean IC" fill="var(--s1)" isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <h2>Hold-out</h2>
              <Note text={d.holdout.note} />
              <h2>Sealed-prediction ledger</h2>
              <Note text={d.ledger.note} />
            </>
          );
        }}
      </Status>
    </>
  );
}
