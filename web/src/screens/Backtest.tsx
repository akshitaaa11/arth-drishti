import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Note, Num, Status, Takeaway, useFetch } from "../components/Common";
import { Card, ColumnChart, HBars, Insight } from "../components/ui";

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
  holdout: { status: string; note: string; result?: { verdicts?: Record<string, { met: boolean; display: string; rule: string }> } };
  ledger: { entries: unknown[]; note: string };
}

const LINES: Record<string, string[]> = {
  sector: ["NIFTY500", "equal_weight", "ridge", "tier1_blend", "lgbm_ranker"],
  stock: ["NIFTY500", "equal_weight", "momentum_12m", "ridge", "tier2_ranker"],
};
const COLOURS = ["#9b9da5", "#2a55e8", "#ee4d86", "#12a150", "#f2872f"];

export default function Backtest() {
  const state = useFetch<Resp>("/backtest");
  const [level, setLevel] = useState<"sector" | "stock">("sector");
  const [model, setModel] = useState("ridge");
  const [icModel, setIcModel] = useState("tier1_blend");
  return (
    <>
      <div className="titlerow">
        <div>
          <h1>Backtest &amp; evidence</h1>
          <p className="lead">Would this have worked? Net of 0.2% round-trip costs, rebuilt from out-of-sample predictions; stock results carry survivorship bias.</p>
        </div>
        <div className="seg ctrl">
          <button aria-pressed={level === "sector"} onClick={() => setLevel("sector")}>Top-3 sectors</button>
          <button aria-pressed={level === "stock"} onClick={() => setLevel("stock")}>Top-15 stocks</button>
        </div>
      </div>
      <Status state={state}>
        {(d) => {
          const lines = LINES[level].filter((c) => d.equity[level].columns.includes(c));
          const ablation = d.ablation.filter((a) => a.model === model && (a.variant.startsWith("no_") || ["price_only", "budget_only", "price_plus_budget", "momentum_only", "full"].includes(a.variant)));
          const years = Array.from(new Set(d.ic_by_year.map((r) => r.budget_id))).sort();
          const icModels = ["ridge", "lgbm_ranker", "bayes_hier", "tier1_blend", "last_years_winners"];
          const icRows = d.ic_by_year.filter((r) => r.model === icModel && r.ic !== null);
          const ho = d.holdout;
          const verdicts = ho.result?.verdicts;
          const p1 = verdicts?.P1;
          return (
            <>
              <Takeaway text={d.takeaway} />
              <Note text={`Does the budget data add anything beyond price momentum? ${d.evidence_answer}. See the evidence report for the full answer.`} />
              <div className="bento">
                <Card className="s8" title="Growth of 100" info="What 100 rupees would have become by following each strategy since the first test budget, after 0.2% trading costs, on a log scale. The dashed line is the Nifty 500. Every line is rebuilt from out-of-sample predictions only, so none used information from the future." caption="Log scale; each line follows one strategy from the first test budget">
                  <div className="legend">
                    {lines.map((c, i) => (
                      <span key={c}><i style={{ background: COLOURS[i] }} />{c}</span>
                    ))}
                  </div>
                  <div className="chartbox" data-testid="equity-chart" style={{ height: 330 }}>
                    <ResponsiveContainer>
                      <LineChart data={d.equity[level].rows}>
                        <CartesianGrid stroke="var(--line)" vertical={false} />
                        <XAxis dataKey="date" stroke="var(--ink-3)" tickLine={false} axisLine={false} tickFormatter={(v) => String(v).slice(0, 4)} minTickGap={40} />
                        <YAxis scale="log" domain={["auto", "auto"]} stroke="var(--ink-3)" tickLine={false} axisLine={false} />
                        <Tooltip contentStyle={{ borderRadius: 14, border: "none", boxShadow: "0 8px 24px rgba(0,0,0,.15)" }} />
                        {lines.map((c, i) => (
                          <Line key={c} dataKey={c} stroke={COLOURS[i]} dot={false} strokeWidth={c === "NIFTY500" ? 1.6 : 2.2} strokeDasharray={c === "NIFTY500" ? "5 4" : undefined} isAnimationActive={false} />
                        ))}
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </Card>
                <Insight className="s4" tone="dusk" tag={ho.status === "evaluated" ? "Hold-out, run once" : "Hold-out"} info="The hold-out is a final exam: two budgets (FY2024-25 and FY2025-26) kept locked until one single, pre-planned run. This card shows whether that run happened and whether the primary rule was met."
                  big={p1 ? (p1.met ? "Met" : "Null") : "Not run"} title={p1 ? `Primary rule: ${p1.met ? "met" : "not met"} (${p1.display}).` : "The one-time hold-out has not been run."} text={ho.note} />
                <Card className="s8" title="Rank correlation by test year" info="For each test budget, how well the chosen model ranked sectors against what then happened (information coefficient). Blue columns are positive, pink negative; values near zero mean the ranking carried no information." caption="Information coefficient of the forecast and the outcome; blue positive, pink negative"
                  right={<select className="pillsel" value={icModel} onChange={(e) => setIcModel(e.target.value)} aria-label="IC model">{icModels.map((m) => <option key={m} value={m}>{m.replace(/_/g, " ")}</option>)}</select>}>
                  <ColumnChart ariaLabel="Information coefficient by year" height={310} initial={icRows.length - 1}
                    items={icRows.map((r) => ({ label: r.budget_id.replace("FY", ""), value: r.ic as number, display: (r.ic as number).toFixed(2), tip: <><b>{(r.ic as number).toFixed(2)}</b> | {r.budget_id}</> }))}
                    yFmt={(v) => v.toFixed(1)} />
                </Card>
                <Card className="s4" title="Ablation" info="A test of what the budget data adds. The model is re-run without one family of inputs at a time and the average rank correlation (IC) is compared. If removing the budget inputs does not hurt, the budget adds little beyond price." caption="Mean IC without each feature family"
                  right={<select className="pillsel" value={model} onChange={(e) => setModel(e.target.value)} aria-label="Ablation model"><option>ridge</option><option>lgbm_ranker</option></select>}>
                  <div data-testid="ablation-chart">
                    <HBars signed rows={ablation.map((a) => ({ label: a.variant.replace(/_/g, " "), value: a.mean_ic, display: a.mean_ic.toFixed(3) }))} />
                  </div>
                </Card>
                <Card className="s12" title="Strategy summary" info="CAGR is the compound annual growth rate, Sharpe is return per unit of risk, max drawdown the worst peak-to-trough fall, turnover how much of the portfolio changes each year, and 'value of 100' the end value of 100 rupees.">
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
                </Card>
                <Card className="s12" title="Information coefficient by test year" info="The rank correlation (IC) between each model's forecast ranking and what actually happened, for every test budget. Positive is good, near zero means no skill, one is perfect." caption="All models">
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
                </Card>
                <Card className="s6" title="Pre-registered hold-out rules" info="Before the hold-out budgets were looked at, a primary rule (P1) and four secondary rules (S1 to S4) were written down. They were applied mechanically to the result, so the outcome could not be spun.">
                  {verdicts ? (
                    <table>
                      <tbody>
                        {Object.entries(verdicts).map(([k, v]) => (
                          <tr key={k}><td><b style={{ fontWeight: 500 }}>{k}</b></td><td style={{ whiteSpace: "normal" }}>{v.rule}</td><td className="n muted">{v.display}</td><td><span className={`st ${v.met ? "low" : "high"}`}>{v.met ? "met" : "not met"}</span></td></tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <Note text={ho.note} />
                  )}
                </Card>
                <Card className="s6" title="Sealed-prediction ledger" info="A public record of forecasts sealed with a hash before their outcome is known. It is planned for the live year and is not built yet.">
                  <Note text={d.ledger.note} />
                </Card>
              </div>
            </>
          );
        }}
      </Status>
    </>
  );
}
