import { Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { crore, pct, signedPct } from "../api";
import { Note, Num, Status, Takeaway, useFetch } from "../components/Common";

interface Shap {
  feature: string;
  feature_value: number | null;
  base: number;
  shap: number;
  row: number;
}
interface Forecast {
  sector: { sector_id: string; name: string; budget_lines: string[]; is_control: boolean };
  forecast: { rank: number; expected_excess: number; p10: number; p90: number; p_beat: number; reasons: string[]; source_ref: string };
  shap: Shap[];
  cards: {
    surprise?: { value_pct: number | null; be_current_cr: number | null; re_previous_cr: number | null; source_ref: string };
    credibility?: { value_pct: number | null; years_used: number; source_ref: string };
  };
  history: { budget_id: string; expected_excess: number; actual: number | null }[];
  takeaway: string;
}
interface Curve {
  window: string;
  car: number | null;
  mean_car_all_budgets: number | null;
  t_stat: number | null;
  source_ref: string | null;
}
interface EventStudy {
  curve: Curve[];
  fpi_strip: { period_end: string; equity_net_cr: number | null; source_ref: string; after_budget: boolean }[];
  fpi_note: string | null;
  takeaway: string | null;
}

export default function DeepDive({ budgetId, sectorId, setSector, sectors }: { budgetId: string; sectorId: string; setSector: (s: string) => void; sectors: string[] }) {
  const f = useFetch<Forecast>(`/sectors/${sectorId}/forecast?budget_id=${budgetId}`);
  const e = useFetch<EventStudy>(`/sectors/${sectorId}/event-study?budget_id=${budgetId}`);
  return (
    <>
      <h1>3. Sector deep-dive: why this sector?</h1>
      <div className="controls">
        <label>
          Sector{" "}
          <select value={sectorId} onChange={(ev) => setSector(ev.target.value)} aria-label="Sector">
            {sectors.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
      </div>
      <Status state={f}>
        {(d) => {
          const top = d.shap.slice(0, 8);
          const rest = d.shap.slice(8).reduce((a, s) => a + s.shap, 0);
          const bars = [...top.map((s) => ({ name: s.feature, shap: s.shap })), { name: "all other features", shap: rest }];
          return (
            <>
              <Takeaway text={d.takeaway} />
              <div className="grid cols-2">
                <div className="card" data-testid="surprise-card">
                  <h3>Surprise</h3>
                  {d.cards.surprise ? (
                    <>
                      <div className="big">
                        <Num value={d.cards.surprise.value_pct === null ? "n/a" : `${d.cards.surprise.value_pct.toFixed(1)}%`} source={d.cards.surprise.source_ref} />
                      </div>
                      <p className="muted">
                        New allocation {crore(d.cards.surprise.be_current_cr)} against last year's revised estimate {crore(d.cards.surprise.re_previous_cr)}.
                      </p>
                    </>
                  ) : (
                    <p className="muted">No budget data for this sector and year.</p>
                  )}
                </div>
                <div className="card" data-testid="credibility-card">
                  <h3>Execution credibility</h3>
                  {d.cards.credibility && d.cards.credibility.value_pct !== null ? (
                    <>
                      <div className="big">
                        <Num value={`${d.cards.credibility.value_pct.toFixed(1)}%`} source={d.cards.credibility.source_ref} />
                      </div>
                      <p className="muted">Average gap between actual and budgeted spending over {d.cards.credibility.years_used} earlier year(s).</p>
                    </>
                  ) : (
                    <p className="muted">Not available: fewer than one earlier year of actuals.</p>
                  )}
                </div>
              </div>
              <h2>Why the model says what it says (SHAP, effect on expected excess return)</h2>
              <p className="muted">
                Expected {signedPct(d.forecast.expected_excess)} (80% interval {signedPct(d.forecast.p10, 0)} to {signedPct(d.forecast.p90, 0)}), rank {d.forecast.rank} of 15,
                P(beat Nifty 500) {pct(d.forecast.p_beat, 0)}.
              </p>
              <div className="chartbox" data-testid="shap-chart">
                <ResponsiveContainer>
                  <BarChart data={bars} layout="vertical" margin={{ left: 70 }}>
                    <CartesianGrid stroke="var(--border)" />
                    <XAxis type="number" stroke="var(--text-2)" tickFormatter={(v) => `${(Number(v) * 100).toFixed(0)}pp`} />
                    <YAxis type="category" dataKey="name" width={160} stroke="var(--text-2)" tick={{ fontSize: 11 }} />
                    <Tooltip formatter={(v) => `${(Number(v) * 100).toFixed(2)} pp`} />
                    <Bar dataKey="shap" isAnimationActive={false}>
                      {bars.map((b) => (
                        <Cell key={b.name} fill={b.shap >= 0 ? "var(--pos)" : "var(--neg)"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <h3>Three reasons</h3>
              <ol>
                {d.forecast.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ol>
              <details>
                <summary>All feature contributions</summary>
                <div className="tablewrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Feature</th>
                        <th className="n">Value</th>
                        <th className="n">Effect (pp)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.shap.map((s) => (
                        <tr key={s.feature}>
                          <td>{s.feature}</td>
                          <td className="n">{s.feature_value === null ? "missing" : s.feature_value.toFixed(3)}</td>
                          <td className="n"><Num value={(s.shap * 100).toFixed(2)} source={`shap_values_sector:${s.row}`} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </>
          );
        }}
      </Status>
      <h2>Budget-day event study (market model)</h2>
      <Status state={e}>
        {(d) => (
          <>
            <Takeaway text={d.takeaway} />
            <div className="chartbox" data-testid="car-chart">
              <ResponsiveContainer>
                <ComposedChart data={d.curve}>
                  <CartesianGrid stroke="var(--border)" />
                  <XAxis dataKey="window" stroke="var(--text-2)" />
                  <YAxis stroke="var(--text-2)" tickFormatter={(v) => `${(Number(v) * 100).toFixed(0)}%`} />
                  <Tooltip formatter={(v) => `${(Number(v) * 100).toFixed(1)}%`} />
                  <Bar dataKey="car" name="This budget" fill="var(--s1)" isAnimationActive={false} />
                  <Line dataKey="mean_car_all_budgets" name="Average over budgets" stroke="var(--s2)" strokeWidth={2} dot isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <p className="muted">Bars: cumulative abnormal return in each window; line: the average of the same window over all unlocked full budgets.</p>
            <h3>NSDL foreign-investor net equity flow, 90 days either side</h3>
            <Note text={d.fpi_note} />
            {d.fpi_strip.length > 0 && (
              <div className="tablewrap" data-testid="fpi-strip">
                <table>
                  <thead>
                    <tr>
                      <th>Fortnight ending</th>
                      <th className="n">Net equity (Rs crore)</th>
                      <th>Relative to budget</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.fpi_strip.map((r) => (
                      <tr key={r.period_end}>
                        <td>{r.period_end}</td>
                        <td className="n"><Num value={r.equity_net_cr === null ? "n/a" : Math.round(r.equity_net_cr).toLocaleString("en-IN")} source={r.source_ref} /></td>
                        <td>{r.after_budget ? "after (descriptive only)" : "before"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </Status>
    </>
  );
}
