import { crore, pct, signedPct } from "../api";
import { Note, Num, Status, Takeaway, useFetch, Whisker } from "../components/Common";
import { sectorLabel, AskBar, Card, ColumnChart, HBars, Insight, StepLine } from "../components/ui";

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

const nice = (s: string) => s.replace(/_/g, " ");

export default function DeepDive({ budgetId, sectorId, setSector, sectors, ask }: { budgetId: string; sectorId: string; setSector: (s: string) => void; sectors: string[]; ask: (q: string) => void }) {
  const f = useFetch<Forecast>(`/sectors/${sectorId}/forecast?budget_id=${budgetId}`);
  const e = useFetch<EventStudy>(`/sectors/${sectorId}/event-study?budget_id=${budgetId}`);
  return (
    <>
      <div className="titlerow">
        <div>
          <h1>Sector deep-dive</h1>
          <p className="lead">Why the model says what it says about {nice(sectorId)}, and how the sector reacted on past budget days.</p>
        </div>
        <div className="ctrl">
          <select className="pillsel" value={sectorId} onChange={(ev) => setSector(ev.target.value)} aria-label="Sector">
            {sectors.map((s) => (
              <option key={s} value={s}>{sectorLabel(s)}</option>
            ))}
          </select>
        </div>
      </div>
      <Status state={f}>
        {(d) => {
          const top = d.shap.slice(0, 7);
          const rest = d.shap.slice(7).reduce((a, s) => a + s.shap, 0);
          const bars = [...top.map((s) => ({ name: nice(s.feature), shap: s.shap })), { name: "all other features", shap: rest }];
          const curve = (e.data?.curve ?? []).filter((c) => c.car !== null);
          const c30 = curve.find((c) => c.window === "[0,+30]");
          const hist = d.history;
          return (
            <>
              <Takeaway text={d.takeaway} />
              <div className="bento">
                <Card className="s8" title="Budget-day reaction" info="How the sector's shares moved around the budget, beyond what the whole market did. Each column is a time window counted in trading days from the budget day ([0,+30] means the first 30 trading days after). Values are cumulative abnormal returns from a market model. Blue is above normal, pink below. The pill compares this budget with the average of all earlier budgets." caption={`Cumulative abnormal return after the ${budgetId} budget, by window (market model)`} style={{ paddingBottom: 132 }}>
                  <div data-testid="car-chart">
                    {curve.length > 0 ? (
                      <ColumnChart
                        ariaLabel="Cumulative abnormal return by window"
                        height={420}
                        initial={Math.max(curve.findIndex((c) => c.window === "[0,+30]"), 0)}
                        items={curve.map((c) => ({
                          label: c.window,
                          value: c.car as number,
                          display: signedPct(c.car, 1),
                          tip: <><b>{signedPct(c.car, 1)}</b>{c.mean_car_all_budgets !== null ? ` | average over budgets ${signedPct(c.mean_car_all_budgets, 1)}` : ""}</>,
                        }))}
                        yFmt={(v) => `${(v * 100).toFixed(0)}%`}
                      />
                    ) : (
                      <p className="muted">No event-study rows for this sector and budget.</p>
                    )}
                  </div>
                  <AskBar tag={nice(sectorId)} fallback={`Why is ${nice(sectorId)} ranked where it is?`} onAsk={ask} />
                </Card>
                <Card className="s4" title="The forecast" info="The model's out-of-sample forecast of this sector's return over the next 12 months, relative to the Nifty 500 index. The capsule is the 80% interval (the range that held about four times in five in past tests), and P(beat) is the model's chance of beating the index. The bars below show which inputs pushed the forecast up or down, in percentage points." caption={`${budgetId} · out-of-sample`}>
                  <div className="num-xl" style={{ marginTop: 14 }}><Num value={signedPct(d.forecast.expected_excess)} source={d.forecast.source_ref} /></div>
                  <div className="kpi-sub"><span className="chip">rank {d.forecast.rank} of 15</span><span className="chip">P(beat) {pct(d.forecast.p_beat, 0)}</span></div>
                  <Whisker p10={d.forecast.p10} p90={d.forecast.p90} mark={d.forecast.expected_excess} min={-0.6} max={1.0} />
                  <div className="cap">80% interval {signedPct(d.forecast.p10, 0)} to {signedPct(d.forecast.p90, 0)}</div>
                  <div style={{ marginTop: 16 }} data-testid="shap-chart">
                    <div className="cap" style={{ marginBottom: -4 }}>Effect on the expectation, percentage points (SHAP)</div>
                    <HBars signed rows={bars.map((b) => ({ label: b.name, value: b.shap, display: `${(b.shap * 100).toFixed(1)}` }))} />
                  </div>
                </Card>
                <Insight className="s4" tag="Event study" info="The 30-day abnormal return of this sector after the budget day, from a market model: the return beyond what the overall market explains. The text compares it with the average of earlier budgets." big={c30 ? signedPct(c30.car, 1) : "n/a"} title="Abnormal return in the 30 days after this budget"
                  text={e.data?.takeaway ?? undefined} />
                <Card className="s4" title="Expected vs realised" info="For every earlier budget, the pink line is what the sector actually returned over the following year relative to the Nifty 500, and the dashed blue line is what the model had expected. The gap between them is the honest track record." caption="Excess return over the Nifty 500 at each earlier budget (pink: realised, dashed: expected)">
                  <StepLine labels={hist.map((h) => h.budget_id.replace("FY", "").slice(2))} fmt={(v) => signedPct(v, 0)}
                    series={[{ name: "Realised", values: hist.map((h) => h.actual), colour: "#ee4d86" }, { name: "Expected", values: hist.map((h) => h.expected_excess), colour: "#2a55e8" }]} />
                </Card>
                <div className="stack s4">
                  <Card title="Surprise" info="How different this year's allocation is from last year's revised estimate, in percent. A positive surprise means the sector was given more than expected; the model uses this as one of its inputs." caption="New allocation vs last revised estimate" style={{ flex: 1 }}>
                    <div data-testid="surprise-card">
                      {d.cards.surprise ? (
                        <>
                          <div className="num-l" style={{ marginTop: 10 }}><Num value={d.cards.surprise.value_pct === null ? "n/a" : `${d.cards.surprise.value_pct.toFixed(1)}%`} source={d.cards.surprise.source_ref} /></div>
                          <p className="cap" style={{ marginTop: 8 }}>{crore(d.cards.surprise.be_current_cr)} against {crore(d.cards.surprise.re_previous_cr)}.</p>
                        </>
                      ) : (
                        <p className="muted">No budget data for this sector and year.</p>
                      )}
                    </div>
                  </Card>
                  <Card title="Execution credibility" info="Whether the sector's ministries actually spend what the budget promises. It is the average gap between actual and budgeted spending over earlier years; negative means money was left unspent." caption="Actual vs budgeted spending, earlier years" style={{ flex: 1 }}>
                    <div data-testid="credibility-card">
                      {d.cards.credibility && d.cards.credibility.value_pct !== null ? (
                        <>
                          <div className="num-l" style={{ marginTop: 10 }}><Num value={`${d.cards.credibility.value_pct.toFixed(1)}%`} source={d.cards.credibility.source_ref} /></div>
                          <p className="cap" style={{ marginTop: 8 }}>Average over {d.cards.credibility.years_used} earlier year(s).</p>
                        </>
                      ) : (
                        <p className="muted">Not available: fewer than one earlier year of actuals.</p>
                      )}
                    </div>
                  </Card>
                </div>
                <Card className="s6" title="Three reasons" info="The three largest contributions to this forecast, written in plain English with their data source. They come from the SHAP analysis of the model." caption="Plain-English reading of the largest contributions">
                  <ol style={{ margin: "8px 0 0", padding: 0, listStyle: "none" }}>
                    {d.forecast.reasons.map((r, i) => (
                      <li key={r} style={{ display: "flex", gap: 12, padding: "12px 0", borderTop: i ? "1px solid var(--line)" : "none" }}>
                        <span className="chip" style={{ height: 22, flex: "none" }}>{i + 1}</span>
                        <span>{r}</span>
                      </li>
                    ))}
                  </ol>
                </Card>
                <Card className="s6" title="Foreign-investor flow" info="Net buying or selling of Indian equities by foreign portfolio investors in the sector, from NSDL fortnightly reports, 90 days either side of the budget. Where reports were not collected the card says so rather than guessing." caption="NSDL net equity flow, 90 days either side of the budget">
                  <Note text={e.data?.fpi_note} />
                  {e.data && e.data.fpi_strip.length > 0 && (
                    <div className="tablewrap" data-testid="fpi-strip">
                      <table>
                        <thead>
                          <tr><th>Fortnight ending</th><th className="n">Net equity (Rs crore)</th><th>Relative to budget</th></tr>
                        </thead>
                        <tbody>
                          {e.data.fpi_strip.map((r) => (
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
                </Card>
                <Card className="s12" title="All feature contributions" info="Every input the model used for this sector and its effect on the forecast in percentage points (SHAP value). Positive pushed the expected return up, negative pushed it down." caption="SHAP values for this forecast">
                  <div className="tablewrap">
                    <table>
                      <thead><tr><th>Feature</th><th className="n">Value</th><th className="n">Effect (pp)</th></tr></thead>
                      <tbody>
                        {d.shap.map((s) => (
                          <tr key={s.feature}>
                            <td>{nice(s.feature)}</td>
                            <td className="n">{s.feature_value === null ? "missing" : s.feature_value.toFixed(3)}</td>
                            <td className="n"><Num value={(s.shap * 100).toFixed(2)} source={`shap_values_sector:${s.row}`} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              </div>
            </>
          );
        }}
      </Status>
    </>
  );
}
