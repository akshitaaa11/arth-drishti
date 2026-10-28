import { Fragment, useState } from "react";
import { crore, pct, signedPct } from "../api";
import { Note, Num, Status, Takeaway, useFetch } from "../components/Common";
import { Avatar, Card, sectorLabel } from "../components/ui";

interface Stock {
  symbol: string;
  sector_id: string;
  rank: number;
  expected_excess: number;
  p10: number;
  p90: number;
  p_beat: number;
  liquidity_cr: number | null;
  risk: string | null;
  reasons: string[];
  source_ref: string;
  features_ref: string | null;
}
interface Resp {
  stocks: Stock[];
  note: string | null;
  survivorship: string;
  order_win_flag: string;
  takeaway: string | null;
}

export default function Watchlist({ budgetId, sectors }: { budgetId: string; sectors: string[] }) {
  const [sector, setSector] = useState("");
  const [risk, setRisk] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const qs = `budget_id=${budgetId}${sector ? `&sector=${sector}` : ""}${risk ? `&risk=${risk}` : ""}`;
  const state = useFetch<Resp>(`/stocks?${qs}`);
  return (
    <>
      <div className="titlerow">
        <div>
          <h1>Stock watchlist</h1>
          <p className="lead">Stocks ranked by the Tier-2 model within the budget-sensitive sectors. Weaker than the sector forecasts, and the stock list has survivorship bias.</p>
        </div>
        <div className="ctrl">
          <select className="pillsel" value={sector} onChange={(e) => setSector(e.target.value)} aria-label="Sector filter">
            <option value="">All sectors</option>
            {sectors.map((s) => (
              <option key={s} value={s}>{sectorLabel(s)}</option>
            ))}
          </select>
          <select className="pillsel" value={risk} onChange={(e) => setRisk(e.target.value)} aria-label="Risk filter">
            <option value="">Any risk</option>
            <option>low</option>
            <option>medium</option>
            <option>high</option>
          </select>
        </div>
      </div>
      <Status state={state}>
        {(d) => (
          <>
            <Takeaway text={d.takeaway} />
            <Note text={d.note} />
            <Card title="Ranked stocks" caption={`${d.survivorship} Order-win flag: ${d.order_win_flag}. Risk is the 90-day volatility tercile. Click a row for its three reasons.`}>
              <div className="tablewrap">
                <table data-testid="watchlist">
                  <thead>
                    <tr>
                      <th className="n">Rank</th>
                      <th>Stock</th>
                      <th>Sector</th>
                      <th className="n">Expected excess</th>
                      <th className="n">80% interval</th>
                      <th className="n">P(beat)</th>
                      <th className="n">Liquidity</th>
                      <th>Risk</th>
                      <th>Order win</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.stocks.slice(0, 60).map((s, i) => (
                      <Fragment key={s.symbol}>
                        <tr onClick={() => setOpen(open === s.symbol ? null : s.symbol)} style={{ cursor: "pointer" }}>
                          <td className="n">{s.rank}</td>
                          <td><Avatar name={s.symbol} i={i} /><strong style={{ fontWeight: 500 }}>{s.symbol}</strong></td>
                          <td className="muted">{sectorLabel(s.sector_id)}</td>
                          <td className="n"><Num value={signedPct(s.expected_excess)} source={s.source_ref} /></td>
                          <td className="n muted">{signedPct(s.p10, 0)} to {signedPct(s.p90, 0)}</td>
                          <td className="n">{pct(s.p_beat, 0)}</td>
                          <td className="n"><Num value={crore(s.liquidity_cr)} source={s.features_ref} /></td>
                          <td><span className={`st ${s.risk ?? "medium"}`}>{s.risk}</span></td>
                          <td className="muted">n/a</td>
                        </tr>
                        {open === s.symbol && (
                          <tr>
                            <td colSpan={9}>
                              <ul style={{ margin: 0, paddingLeft: 18 }}>
                                {s.reasons.map((r) => (
                                  <li key={r}>{r}</li>
                                ))}
                              </ul>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="cap" style={{ marginTop: 12 }}>Showing the top 60 of {d.stocks.length} stocks.</p>
            </Card>
          </>
        )}
      </Status>
    </>
  );
}
